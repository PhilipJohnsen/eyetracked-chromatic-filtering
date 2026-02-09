import os
import ctypes
import numpy as np

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

  if blur_dir == "H":
    frag_src = "#define BLUR_DIR vec2(1.0,0.0)\n" + blur_src
  elif blur_dir == "V":
    frag_src = "#define BLUR_DIR vec2(0.0,1.0)\n"+blur_src
  else:
    raise ValueError("Wrong value for blur_dir, should be 'H' or 'V'

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

  #repeat border to avoid blur kernel issues, repeating border allows filtering corner pixels, and averages to a good viewing result
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_MIRRORED_REPEAT)
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_MIRRORED_REPEAT)

  glBindtexture(GL_TEXTURE_2D, 0)
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


#Gaussian blur
#----------------------
class GasusianBlurRenderer:
  """GPU only separable gaussian blur.
        input tex (captured frame -> horizontal pass -> intermediate texture -> vertical pass -> final output texture

    Usage:
      r = GaussianBlurRenderer(w, h, blur_glsl_path="shaders/blur.glsl")
      r.set_params(radius_rgb=(0,2,6), sigma_rgb=(0.001,1.0,3.0))
      out_tex = r.process(frame_np)  # returns GL texture id (output)
  """
  
  #Initialize gaussian blur
  def __init__(self, width:int, height:int, blur_glsl_path: str):
    self.w=int(width)
    self.h=int(height)

    if not os.path.exists(blur_glsl_path):
      raise FileNotFoundError(blur_glsl_path)

    #core VAO

    #programs

    #textures

    #FBO for pass 1 and 2(output)

    #Cache uniform for programs


    #load parameters


    #fixed texel size

    #clean binds for futur

  #Set the uniforms

  #Set the texel size



  #Load parameters from /init/settings.txt


  #Upload the frame


  #Draw the fullscreen


  #Process the pipeline for the blur


  #Read back the output of the image for debugging to the CPU, should be computed to the same integers as the previous CPU based renderer

  #Cleanup after 
