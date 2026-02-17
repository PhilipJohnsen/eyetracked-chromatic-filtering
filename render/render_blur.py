import os
import ctypes
import numpy as np
import time

from OpenGL.GL import *
from OpenGL.GL.shaders import compileProgram, compileShader

#Load the fullscreen triangle vertex shader
FULLSCREEN_VERT = r"""
#version 330 core
out vec2 vUV;

void main(){
  vec2 pos;
  if (gl_VertexID == 0) pos = vec2(-1.0, -1.0);
  if (gl_VertexID == 1) pos = vec2( 3.0, -1.0);
  if (gl_VertexID == 2) pos = vec2(-1.0,  3.0);

  gl_Position = vec4(pos, 0.0, 1.0);
  vUV = 0.5 * (pos + 1.0);
}
"""

#Load settings
def _load_text(path: str) -> str:
  with open(path, "r", encoding="utf-8") as f:
    return f.read()
    #returns the content of the defined path to settings, expecting normal utf8 textformat


#Compile blur program shaders
def _compile_blur_program(blur_glsl_path: str, blur_dir: str) ->int:
  """blur_dir: 'H' or 'V'"""

  blur_src = _load_text(blur_glsl_path) #get the string of the path to use in call later

  # Insert #define after #version line
  lines = blur_src.split('\n', 1)
  version_line = lines[0] if len(lines) > 0 else ""
  rest = lines[1] if len(lines) > 1 else ""
  
  if blur_dir == "H":
    blur_define = "#define BLUR_DIR vec2(1.0,0.0)"
  elif blur_dir == "V":
    blur_define = "#define BLUR_DIR vec2(0.0,1.0)"
  else:
    raise ValueError("Wrong value for blur_dir, should be 'H' or 'V'")

  frag_src = version_line + "\n" + blur_define + "\n" + rest

  return compileProgram( #use the glsl shader compiler
      compileShader(FULLSCREEN_VERT, GL_VERTEX_SHADER),
      compileShader(frag_src, GL_FRAGMENT_SHADER)
    )
                     
#Create the texture in rgb8 format
def _create_rgb8_texture(w: int, h: int) -> int:
  tex = glGenTextures(1)
  glBindTexture(GL_TEXTURE_2D, tex)

  #make the texture have 3 bytes per pixel for 0-255 value for R,G,B channels independently
  glPixelStorei(GL_UNPACK_ALIGNMENT, 1) #value 1 meaning that we use byte alignment, khronos.org documentation

  glTexImage2D(
    GL_TEXTURE_2D, 0, GL_RGB8, w, h,  #target, level, internalformat, width, height
    0, GL_RGB, GL_UNSIGNED_BYTE, #border, format, type
    None #data
  )

  #filter
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)

  #clamp to edge to avoid edge artifacts and drift
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)

  glBindTexture(GL_TEXTURE_2D, 0)
  return tex

#Create a framebuffer object with the RGB values
def _create_fbo_with_color_tex(color_tex: int) -> int:
  fbo = glGenFramebuffers(1)
  glBindFramebuffer(GL_FRAMEBUFFER,fbo)
  glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, color_tex, 0)

  status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
  if status != GL_FRAMEBUFFER_COMPLETE:
    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    raise RuntimeError(f"FBO not complete: status = 0x{status:x}")

  glBindFramebuffer(GL_FRAMEBUFFER,0)
  return fbo


def _check_fbo_status(tag: str) -> None:
  status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
  if status != GL_FRAMEBUFFER_COMPLETE:
    print(f"[gl] FBO incomplete {tag}: status=0x{status:x}")


def _check_gl_error(tag: str) -> None:
  err = glGetError()
  if err == GL_NO_ERROR:
    return
  while err != GL_NO_ERROR:
    print(f"[gl] error {tag}: 0x{err:04x}")
    err = glGetError()


#Gaussian blur
#----------------------
class GaussianBlurRenderer:
  """GPU only separable gaussian blur.
        input tex (captured frame -> horizontal pass -> intermediate texture -> vertical pass -> final output texture

    Usage:
      r = GaussianBlurRenderer(w, h, blur_glsl_path="shaders/blur.glsl")
      r.set_params(radius_rgb=(0,2,6), sigma_rgb=(0.001,1.0,3.0))
      out_tex = r.process(frame_np)  # returns GL texture id (output)
  """
  
  #Initialize gaussian blur
  def __init__(self, width:int, height:int, blur_glsl_path: str, input_format: int = GL_RGB):
    self.w=int(width)
    self.h=int(height)
    self.input_format = input_format

    if not os.path.exists(blur_glsl_path):
      raise FileNotFoundError(blur_glsl_path)

    #core VAO
    self.vao = glGenVertexArrays(1)
    glBindVertexArray(self.vao)
    
    #programs
    self.prog_h = _compile_blur_program(blur_glsl_path, "H")
    self.prog_v = _compile_blur_program(blur_glsl_path, "V")
    
    #textures
    self.tex_in = _create_rgb8_texture(self.w,self.h)
    self.tex_temp = _create_rgb8_texture(self.w,self.h)
    self.tex_out = _create_rgb8_texture(self.w, self.h)

    #FBO for pass 1 and 2(output)
    self.fbo_temp = _create_fbo_with_color_tex(self.tex_temp)
    self.fbo_out = _create_fbo_with_color_tex(self.tex_out)

    #Cache uniform for programs
    self._cache_uniforms()

    #load parameters CURRENTLY STATIC IMPLEMENT SETTINGS LOAD IF NEEDED
    self.set_params(radius_rgb=(0,2,6), sigma_rgb=(0.001,1.0,3.0))

    #fixed texel size
    self._set_texel_size(self.prog_h)
    self._set_texel_size(self.prog_v)
                    
    #clean binds for futur
    glBindVertexArray(0)

    self._upload_count = 0
    self._upload_log_every = 120
                    
  #Set the uniforms
  def _cache_uniforms(self):
    self.loc={}

    def getloc(prog, name):
      loc = glGetUniformLocation(prog,name)
      if loc<0 : 
        raise RuntimeError(f"Uniform '{name}' not found in program {prog}")
      return loc

    #Use same uniforms for both programs
    for tag,prog in (("h", self.prog_h), ("v", self.prog_v)):
      self.loc[(tag, "uInput")] = getloc(prog, "uInput")
      self.loc[(tag, "uTexelSize")] = getloc(prog, "uTexelSize")
      self.loc[(tag, "uRadiusRGB")] = getloc(prog, "uRadiusRGB")
      self.loc[(tag, "uSigmaRGB")] = getloc(prog, "uSigmaRGB")

      #Bind sampler to texture unit 0 once
      glUseProgram(prog)
      glUniform1i(self.loc[(tag, "uInput")], 0)
      glUseProgram(0)


  #Set the texel size
  def _set_texel_size(self, prog:int):
    tag = "h" if prog==self.prog_h else "v"
    glUseProgram(prog)
    glUniform2f(self.loc[(tag,"uTexelSize")], 1.0/self.w, 1.0/self.h)
    glUseProgram(0)


  #Load parameters from /init/settings.txt
  def set_params(self, radius_rgb=(0,2,6), sigma_rgb=(0.001,1.0,3.0)):
    rR, rG, rB = map(int, radius_rgb)
    sR, sG, sB = map(float, sigma_rgb)

    for tag, prog in (("h", self.prog_h), ("v", self.prog_v)):
        glUseProgram(prog)
        glUniform3i(self.loc[(tag, "uRadiusRGB")], rR, rG, rB)
        glUniform3f(self.loc[(tag, "uSigmaRGB")], sR, sG, sB)
        glUseProgram(0)

  #Upload the frame
  def upload_frame(self, frame_rgb: np.ndarray):
    """Uploads the uint8 frame to self.tex_in.
      frame_rgb shape is (H,W,3|4) uint8, format controlled by input_format."""

    if frame_rgb is None:
      raise ValueError("FrameRGB is None")
    if frame_rgb.dtype != np.uint8 or frame_rgb.ndim != 3 or frame_rgb.shape[2] not in (3, 4):
      raise ValueError(f"Expected uint8 HxWx3/4, got dtype={frame_rgb.dtype}, shape={frame_rgb.shape}")
    if frame_rgb.shape[0] != self.h or frame_rgb.shape[1] != self.w:
      raise ValueError(f"Frame size {frame_rgb.shape[1]}x{frame_rgb.shape[0]} != renderer {self.w}x{self.h}")
    if not frame_rgb.flags["C_CONTIGUOUS"]:
        frame_rgb = np.ascontiguousarray(frame_rgb)

    if frame_rgb.shape[2] == 3 and self.input_format not in (GL_RGB, GL_BGR):
      raise ValueError("input_format must be GL_RGB or GL_BGR for 3-channel input")
    if frame_rgb.shape[2] == 4 and self.input_format not in (GL_RGBA, GL_BGRA):
      raise ValueError("input_format must be GL_RGBA or GL_BGRA for 4-channel input")

    glBindTexture(GL_TEXTURE_2D, self.tex_in)
    glPixelStorei(GL_UNPACK_ALIGNMENT,1) #specified byte alignment for the 3 channels
    self._upload_count += 1
    if self._upload_count == 1:
      print("[gl] starting first glTexSubImage2D", flush=True)
    t0 = time.perf_counter()
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, self.w, self.h, self.input_format, GL_UNSIGNED_BYTE, frame_rgb)
    dt_ms = (time.perf_counter() - t0) * 1000.0
    if self._upload_count == 1 or dt_ms > 10.0 or (self._upload_count % self._upload_log_every) == 0:
      print(f"[gl] glTexSubImage2D took {dt_ms:.2f} ms (count={self._upload_count})", flush=True)
    _check_gl_error("after glTexSubImage2D")
    glBindTexture(GL_TEXTURE_2D, 0)

  #Draw the fullscreen
  def _draw_fullscreen(self):
    glBindVertexArray(self.vao)
    glDrawArrays(GL_TRIANGLES,0,3)
    glBindVertexArray(0)

  #Process the pipeline for the blur
  def process(self, frame_rgb: np.ndarray) -> int:
    """Full GPU pipeline for blur of one frame.
            upload -> blur horizontal -> blur vertical -> output filtered image
        Returns: 
            GL texture ID of blurred output (called self.tex_out)
    """
    # 1) upload the frame
    self.upload_frame(frame_rgb)
    glDisable(GL_DEPTH_TEST) #no need for z buffering test

    # Save previous viewport to avoid leaking GL state into the main display
    prev_viewport = glGetIntegerv(GL_VIEWPORT)
    # set viewport for the FBO passes (match the FBO/texture size)
    glViewport(0, 0, self.w, self.h)

    # 2) Horizontal pass: tex_in -> tex_temp
          #specifically DIR is H
    glBindFramebuffer(GL_FRAMEBUFFER, self.fbo_temp)
    _check_fbo_status("horizontal pass")
    glClearColor(0.0, 0.0, 0.0, 1.0)
    glClear(GL_COLOR_BUFFER_BIT)
    glUseProgram(self.prog_h)
    glActiveTexture(GL_TEXTURE0)
    glBindTexture(GL_TEXTURE_2D, self.tex_in)
    self._draw_fullscreen()

    # 3) Vertical pass: tex_temp -> tex_out
            #specifically DIR is V
    glBindFramebuffer(GL_FRAMEBUFFER, self.fbo_out)
    _check_fbo_status("vertical pass")
    glClearColor(0.0, 0.0, 0.0, 1.0)
    glClear(GL_COLOR_BUFFER_BIT)
    glUseProgram(self.prog_v)
    glActiveTexture(GL_TEXTURE0)
    glBindTexture(GL_TEXTURE_2D, self.tex_temp)
    self._draw_fullscreen()

    # Unbind the textures, now that the frame is filtered
    glBindTexture(GL_TEXTURE_2D, 0)
    glUseProgram(0)
    glBindFramebuffer(GL_FRAMEBUFFER, 0)

    # Restore previous viewport so we don't affect the window/framebuffer draw
    try:
      glViewport(prev_viewport[0], prev_viewport[1], prev_viewport[2], prev_viewport[3])
    except Exception:
      # If retrieving/restoring the previous viewport failed for any reason,
      # silently continue so we don't break the pipeline.
      pass

    # return the GL tex ID of the filtered output
    return self.tex_out


  #Read back the output of the image for debugging to the CPU, should be computed to the same integers as the previous CPU based renderer
  def readback_output(self) -> np.ndarray:
    """
    Reads back the blurred output to the CPU. This is a slow process, but will verify correctness
    Same output from GPU render as previous CPU render with same frame and settings verifies correctness
    """
    glBindFramebuffer(GL_FRAMEBUFFER, self.fbo_out)
    glReadBuffer(GL_COLOR_ATTACHMENT0)

    buf = glReadPixels(0,0,self.w,self.h, GL_RGB, GL_UNSIGNED_BYTE)
    glBindFramebuffer(GL_FRAMEBUFFER,0)

    img = np.frombuffer(buf, dtype=np.uint8).reshape((self.h,self.w,3))

    return img


  #Cleanup after 
  def cleanup(self):
    #Programs and textures
    glDeleteProgram(self.prog_h)
    glDeleteProgram(self.prog_v)
    glDeleteTextures([self.tex_in, self.tex_temp, self.tex_out])

    #Framebuffers and vertex array object
    glDeleteFramebuffers(2, [self.fbo_temp, self.fbo_out])
    glDeleteVertexArrays(1, [self.vao])















