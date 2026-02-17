"""
no-eyetracking-render-loop_improved.py

Goal:
  Continuous click-through overlay that renders a blurred version of the desktop
  WITHOUT capturing itself (no feedback / "telephone game").

Strategy (high level):
  1) Create an always-on-top GLFW window that is:
     - borderless
     - transparent framebuffer capable
     - click-through via Win32 extended styles
  2) Tell Windows: "exclude this window from capture" using
     SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE).
     Correctness claim:
       - If the capture path honors the affinity flag, the captured frames
         will not include our overlay => no feedback loop.
  3) In the render loop:
       capture_desktop_excluding_hwnd(hwnd) -> blur_renderer.process(frame) -> draw fullscreen.
     Correctness claim:
       - We apply the filter exactly once per fresh captured frame.
       - We do not recursively filter our own output if (2) works.
"""

import time
from pathlib import Path
import ctypes
import numpy as np
import glfw
from OpenGL.GL import *
from OpenGL.GL.shaders import compileProgram, compileShader

from dxgi_capture import capture_desktop_excluding_hwnd
from render_blur import GasusianBlurRenderer


# -----------------------------
# Win32 helpers (click-through + exclude-from-capture)
# -----------------------------

user32 = ctypes.windll.user32

GWL_EXSTYLE = -20
GWL_STYLE   = -16

# Extended window styles
WS_EX_LAYERED      = 0x00080000
WS_EX_TRANSPARENT  = 0x00000020  # makes window "hit-test transparent" => click-through
WS_EX_TOOLWINDOW   = 0x00000080  # hide from Alt-Tab (optional, but common for overlays)
WS_EX_TOPMOST      = 0x00000008  # keep above normal windows

# Normal window styles
WS_POPUP = 0x80000000

# Layered attributes
LWA_ALPHA = 0x00000002

# Display affinity:
# WDA_EXCLUDEFROMCAPTURE = 0x11 (Win10 2004+). If unsupported, call will fail.
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def _set_clickthrough_overlay_styles(hwnd: int) -> None:
    """
    Make the GLFW window:
      - borderless (popup)
      - layered (allows transparency composition)
      - click-through (WS_EX_TRANSPARENT)
      - toolwindow (avoid taskbar/alt-tab)
      - topmost

    Correctness argument:
      * WS_EX_TRANSPARENT makes hit-testing pass through to underlying windows,
        so the user can interact with the OS "as if there was no filter active".
      * Borderless/topmost makes it behave like a full-screen overlay.
    """
    if not hwnd:
        return

    # Set regular style to popup (borderless). We still let GLFW manage size.
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    style &= ~0x00CF0000  # strip caption/border-ish bits defensively
    style |= WS_POPUP
    user32.SetWindowLongW(hwnd, GWL_STYLE, style)

    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ex |= (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)

    # Ensure the layered window is fully opaque (alpha=255).
    # Correctness: we want the overlay visible, but still click-through.
    user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)

    # Force style update (applies changes immediately).
    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0,
                        0x0001 | 0x0002 | 0x0020 | 0x0040)  # NOSIZE|NOMOVE|FRAMECHANGED|NOACTIVATE


def _attempt_exclude_from_capture(hwnd: int) -> bool:
    """
    Attempt to exclude this overlay HWND from being captured.

    Correctness argument:
      - If the capture API respects window display affinity, then subsequent
        desktop captures will omit this overlay, preventing "telephone game"
        feedback (blurring blurred output repeatedly).

    Limitations:
      - Requires Windows 10 version 2004+ for WDA_EXCLUDEFROMCAPTURE semantics.
      - Some capture methods / drivers may ignore it.
    """
    if not hwnd:
        return False
    ok = user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
    return bool(ok)


# -----------------------------
# OpenGL helpers
# -----------------------------

def _create_display_shader() -> int:
    """Minimal fullscreen triangle shader that displays a sampler2D."""
    vert = r"""
    #version 330 core
    out vec2 vUV;
    void main() {
        vec2 pos;
        if (gl_VertexID == 0) pos = vec2(-1.0, -1.0);
        if (gl_VertexID == 1) pos = vec2( 3.0, -1.0);
        if (gl_VertexID == 2) pos = vec2(-1.0,  3.0);
        gl_Position = vec4(pos, 0.0, 1.0);
        vUV = 0.5 * (pos + 1.0);
        vUV.y = 1.0 - vUV.y; // keep consistent with captured frame origin
    }
    """
    frag = r"""
    #version 330 core
    in vec2 vUV;
    out vec4 outColor;
    uniform sampler2D uTexture;
    void main() {
        outColor = texture(uTexture, vUV);
    }
    """
    return compileProgram(
        compileShader(vert, GL_VERTEX_SHADER),
        compileShader(frag, GL_FRAGMENT_SHADER),
    )


def _check_gl_error(tag: str) -> None:
    """Prints any GL errors and clears the error flag."""
    err = glGetError()
    if err == GL_NO_ERROR:
        return
    while err != GL_NO_ERROR:
        print(f"[gl] error {tag}: 0x{err:04x}")
        err = glGetError()


def _log_frame_info_once(frame: np.ndarray, label: str) -> None:
    if frame is None:
        print(f"[capture] {label}: None")
        return
    print(
        f"[capture] {label}: shape={frame.shape}, dtype={frame.dtype}, "
        f"contiguous={frame.flags['C_CONTIGUOUS']}, strides={frame.strides}"
    )


# -----------------------------
# Main loop
# -----------------------------

def main():
    # Settings (keep your existing defaults; tune as needed)
    target_fps = 60
    force_rgb = False
    capture_format = "rgb"
    debug_gl_finish = True
    gl_finish_interval = 60
    overlay_size = (2560, 1440)
    overlay_pos = (0, 0)
    radius_rgb = (0, 2, 6)
    sigma_rgb  = (0.001, 1.0, 3.0)

    blur_glsl_path = Path(__file__).parent / "shader" / "blur.glsl"

    if not glfw.init():
        raise RuntimeError("Failed to initialize GLFW")

    # GLFW hints:
    # Correctness argument:
    #   - DECORATED false => no border/title (overlay feel)
    #   - FLOATING true => always-on-top (GLFW side; we also set WS_EX_TOPMOST)
    #   - TRANSPARENT_FRAMEBUFFER true => allows OS composition if needed
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.FOCUSED, glfw.FALSE)  # try not to steal focus
    glfw.window_hint(glfw.RESIZABLE, glfw.TRUE)

    # Start with a small overlay so we can verify capture exclusion behavior.
    window = glfw.create_window(overlay_size[0], overlay_size[1], "Chromatic Filtering Overlay (no eyetracking)", None, None)
    if not window:
        glfw.terminate()
        raise RuntimeError("Failed to create GLFW window")

    glfw.make_context_current(window)
    glfw.swap_interval(0)  # uncapped; we do our own pacing

    # Obtain HWND
    try:
        hwnd = int(glfw.get_win32_window(window))
    except Exception:
        hwnd = 0

    # Apply overlay styles (click-through + topmost + borderless)
    _set_clickthrough_overlay_styles(hwnd)

    # Attempt to exclude from capture (the key anti-feedback mechanism)
    excluded = _attempt_exclude_from_capture(hwnd)
    print(f"[overlay] SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) success: {excluded}")

    if not excluded:
        print("[overlay] WARNING: Failed to exclude from capture. This may cause feedback loops (blurred blur).")

    # Capture the first frame to determine resolution.
    # Correctness argument:
    #   - We want the overlay to match the capture resolution exactly to avoid scaling artifacts.
    print("[capture] Capturing first frame to determine resolution...")
    first = None
    while first is None and not glfw.window_should_close(window):
        first = capture_desktop_excluding_hwnd(hwnd if excluded else None, rgb=force_rgb)
        glfw.poll_events()
        time.sleep(0.02)

    if first is None:
        print("[capture] No frame received; quitting.")
        glfw.destroy_window(window)
        glfw.terminate()
        return

    _log_frame_info_once(first, "first frame")

    if first.ndim != 3 or first.shape[2] not in (3, 4):
        print(f"[capture] Unexpected frame format: {first.shape}")
        glfw.destroy_window(window)
        glfw.terminate()
        return

    if capture_format == "bgr":
        input_format = GL_BGRA if first.shape[2] == 4 else GL_BGR
    else:
        input_format = GL_RGBA if first.shape[2] == 4 else GL_RGB
    print(f"[capture] Using input_format=0x{int(input_format):x}")

    cap_h, cap_w = first.shape[:2]
    print(f"[capture] Resolution: {cap_w}x{cap_h}")

    # Keep overlay small and pinned top-left so we can observe capture exclusion.
    glfw.set_window_size(window, overlay_size[0], overlay_size[1])
    glfw.set_window_pos(window, overlay_pos[0], overlay_pos[1])

    # Initialize blur renderer for capture resolution
    blur_renderer = GasusianBlurRenderer(cap_w, cap_h, str(blur_glsl_path), input_format=input_format)
    blur_renderer.set_params(radius_rgb=radius_rgb, sigma_rgb=sigma_rgb)

    # Display program + VAO
    display_prog = _create_display_shader()
    vao = glGenVertexArrays(1)
    glBindVertexArray(vao)
    glBindVertexArray(0)
    tex_loc = glGetUniformLocation(display_prog, "uTexture")

    # Basic GL state
    glDisable(GL_DEPTH_TEST)

    print("Press Q in the overlay window to quit (or close it).")

    frames = 0
    last_fps_t = time.perf_counter()

    try:
        while not glfw.window_should_close(window):
            t0 = time.perf_counter()

            # 1) Capture a fresh desktop frame.
            # Correctness argument:
            #   - If WDA_EXCLUDEFROMCAPTURE is honored, this frame does NOT include our overlay.
            #   - Therefore we are filtering the true desktop, not our prior filtered output.
            frame = capture_desktop_excluding_hwnd(hwnd if excluded else None, rgb=force_rgb)
            if frame is None:
                glfw.poll_events()
                time.sleep(0.001)
                continue

            if frame.ndim != 3 or frame.shape[2] not in (3, 4):
                print(f"[capture] Unexpected frame format: {frame.shape}")
                glfw.poll_events()
                time.sleep(0.001)
                continue

            if frame.shape[2] == 4 and input_format not in (GL_BGRA, GL_RGBA):
                print("[capture] WARNING: Got 4-channel frame, but input_format is not GL_BGRA/GL_RGBA")

            if not frame.flags["C_CONTIGUOUS"]:
                frame = np.ascontiguousarray(frame)

            # (Optional) sanity stats you can enable during debugging:
            # m, mx = float(frame.mean()), int(frame.max())
            # print("[capture] mean/max:", m, mx)

            # 2) Process on GPU (separable blur passes).
            # Correctness argument:
            #   - This applies the filter exactly once per new frame.
            out_tex = blur_renderer.process(frame)
            _check_gl_error("after blur process")

            # 3) Present to overlay.
            fb_w, fb_h = glfw.get_framebuffer_size(window)
            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            glViewport(0, 0, fb_w, fb_h)

            glClearColor(0.0, 0.0, 0.0, 0.0)  # alpha 0 ok; we draw full-screen anyway
            glClear(GL_COLOR_BUFFER_BIT)

            glUseProgram(display_prog)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, out_tex)
            glUniform1i(tex_loc, 0)

            glBindVertexArray(vao)
            glDrawArrays(GL_TRIANGLES, 0, 3)
            glBindVertexArray(0)

            _check_gl_error("after draw")

            glfw.swap_buffers(window)
            glfw.poll_events()

            if debug_gl_finish and frames % gl_finish_interval == 0:
                glFinish()
                _check_gl_error("after glFinish")

            # Avoid glFinish(); it hard-stalls the GPU every frame.
            # Correctness argument:
            #   - Swap buffers + normal GL pipeline is sufficient for continuous rendering.
            #   - If you need explicit sync later, use fences; but default is faster.

            # FPS telemetry
            frames += 1
            now = time.perf_counter()
            if now - last_fps_t >= 1.0:
                print(f"FPS: {frames}  (excluded_from_capture={excluded})")
                frames = 0
                last_fps_t = now

            # Quit on Q
            if glfw.get_key(window, glfw.KEY_Q) == glfw.PRESS:
                print("Quitting (Q key).")
                break

            # Frame pacing
            dt = time.perf_counter() - t0
            target_dt = 1.0 / max(1, int(target_fps))
            if dt < target_dt:
                time.sleep(target_dt - dt)

    finally:
        blur_renderer.cleanup()
        glDeleteProgram(display_prog)
        glDeleteVertexArrays(1, [vao])
        glfw.destroy_window(window)
        glfw.terminate()


if __name__ == "__main__":
    main()