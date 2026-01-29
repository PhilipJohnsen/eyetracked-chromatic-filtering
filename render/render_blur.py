import os
import ctypes
import numpy as np

from OpenGL.GL import *
from OpenGL.GL.shaders import compileProgram, compileShader

#Load the fullscreen triangle vertex shader


#Load settings



#Compile blur program shaders


#Create the texture in rgb8 format



#Create a framebuffer object with the RGB values



#Gaussian blur
#----------------------
  #Initialize gaussian blur

  #Set the uniforms

  #Set the texel size



  #Load parameters from /init/settings.txt


  #Upload the frame


  #Draw the fullscreen


  #Process the pipeline for the blur


  #Read back the output of the image for debugging to the CPU, should be computed to the same integers as the previous CPU based renderer

  #Cleanup after 
