"""
dxgi_capture.py (DXcam backend)

Uses DXcam (Desktop Duplication API)implementation written purely in python to capture frames.
DXcam respects WDA_EXCLUDEFROMCAPTURE in the desktop duplication path.
DXcam uses the desktop duplication API from Windows, and will thus respect the windows based flag.
Furthermore, DXcam has high performance, reaching 1080p240 on an Nvidia RTX 3090 GPU, with tabs and code running (according to author of DXcam)

Requirements:
  - Windows 10+
  - pip install dxcam numpy opencv-python

Notes:
  - DXcam returns frames as numpy arrays;
  - Arrays are output in RGB format when downstream needs RGB inputs
"""

#Imports needed
import time
from typing import Optional
import numpy as np
import cv2
import dxcam

#Debugging flag, true while in development, will select False when deployment is ready
DEBUG_DXCAM = True


class DXCamCapture:
    """DXcam-based capture that returns frames for CV processing."""
    def __init__(self, output_idx: int = 0, target_fps: Optional[int] = None):
        self.output_idx = output_idx
        self.target_fps = target_fps
        self.camera = None
        self._running = False

    def start(self) -> None:
        """Initialize DXcam and optionally start its capture thread."""
        self.camera = dxcam.create(output_idx=self.output_idx)
        if self.camera is None:
            raise RuntimeError("DXcam.create failed: no camera returned")
        if self.target_fps:
            #Video_mode ensures a smooth 60fps capture, even when idle or no new movement. Can cause performance overhead
            self.camera.start(target_fps=self.target_fps, video_mode=True) 
            self._running = True

    def get_frame(self, rgb: bool = False) -> Optional[np.ndarray]:
        """Capture a frame.

        Args:
            rgb: When True, convert BGR to RGB for downstream code expecting RGB.

        Returns:
            Numpy array for the frame, or None if no frame is available yet.
        """
        if self.camera is None:
            return None
        if self._running:
            frame = self.camera.get_latest_frame()
        else:
            frame = self.camera.grab()
        if frame is None:
            return None

        #DXcam returns BGR(A). Convert to RGB if flagged.
        if rgb:
            if frame.shape[-1] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
            else:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        #A frame was obtained, return the np.ndarray
        return frame

    def stop(self) -> None:
        """Stop capture and release camera."""
        if self.camera is None:
            return
        if self._running:
            try:
                self.camera.stop()
            except Exception:
                pass
        self.camera = None
        self._running = False

_capture = None

def capture_desktop_excluding_hwnd(
    output_idx: int = 0,
    target_fps: Optional[int] = None,
    rgb: bool = False,
) -> Optional[np.ndarray]:
    """Capture a frame using DXcam.

    Uses Desktop Duplication under the hood and respects WDA_EXCLUDEFROMCAPTURE.

    Args:
        output_idx: Monitor index to capture.
        target_fps: If set, uses a background capture thread.
        rgb: Convert output to RGB.
    """
    global _capture

    if _capture is None:
        _capture = DXCamCapture(output_idx=output_idx, target_fps=target_fps)
        _capture.start()

    return _capture.get_frame(rgb=rgb)


def cleanup() -> None:
    """Clean up capture instance."""
    global _capture
    if _capture:
        _capture.stop()
        _capture = None


if __name__ == "__main__":
    print("Testing DXcam Desktop Duplication...")

    for i in range(5):
        start = time.perf_counter()
        frame = capture_desktop_excluding_hwnd(rgb=False)
        elapsed = time.perf_counter() - start

        if frame is not None:
            fps = 1.0 / elapsed if elapsed > 0 else 0
            print(f"Frame {i+1}: {frame.shape}, {elapsed*1000:.1f}ms, {fps:.1f} fps")
        else:
            print(f"Frame {i+1}: No frame yet")

        time.sleep(0.05)

    cleanup()
    print("Done!")
