# eyetracked-chromatic-filtering
A real-time eye-tracked chromatic filtering implementation for the prevention of myopia in children. 

This is a bachelors project developed at the University of Copenhagen, Data science Institute (DIKU). 

The project aims to use real-time eye-tracking and rendering to apply chromatic filtering that adjusts the composition of light on the screen, to prevent lengthening of the eye when viewing a screen for extended periods of time. The project relies on previous clinical results.

The aim of the project is to demonstrate and user-test the feasability of using screen based eye tracking to use chromatic filtering in the peripheral vision of the user, while not applying the filter to the center of the users gaze. 

The eye tracking technology used is from Tobii, a Swedish eye tracking hardware company. 

## Table of Contents
- [Setup Guide](#setup-guide)
- [PSF Calculation Guide](#psf-calculation-guide)
- [Running the Render Loop](#running-the-render-loop)

## Setup Guide
Setting up this chromatic filtering is designed to be easily accessible. I recommend setting up a virtual environment to ensure compatibility across packages.
### Prerequisites
- Python 3.10+
- Windows 10/11
- GPU with OpenGL support

## Benchmarked specs
The repo has been benchmarked for performance with these specs:
- CPU: Ryzen 9 5900x 12c/24t @ 4.40GHz
- RAM: 32 GB (4x8GB) DDR4 3200MT/s
- GPU: AMD Radeon RX 9070 XT, 16GB VRAM

During the initial development phase, these are the benchmarks without eye tracking active (render/no-eyetracking-render-loop.py):
- CPU: Resting usage 4%, spikes to 42% upon setup, rests aroud 10% usage       with blur running @1440p60
- RAM: Resting usage 12.0GB, increases to 12.3GB usage                         with blur running @1440p60
- GPU: Resting usage 34%, increases to 35% usage                               with blur running @1440p60

### Installation
1. Clone the repository
```bash
git clone https://github.com/PhilipJohnsen/eyetracked-chromatic-filtering
cd eyetracked-chromatic-filtering
```

2. Create a virtual environment
```bash
python -m venv .venv
.venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r render/utility/requirements.txt
```

4. Configure settings in `render/utility/settings.txt`:
The settings are configured already, and are suited for 40cm viewing distance, 6.5mm pupil size, and specifcally the 1440p monitor AG271QX. Change the settings per your needs.

## PSF Calculation
### Understand the point spread function
PSF describes how light from a point source spreads across the image plane. In this project, the PSF is calculated based on the human longtitudinal chromatic abberration (LCA) function.

### Calculate the PSF
1. Open `PSF_test_rosencrone.ipynb`
2. Set your specifics, such as focal length, pupil size, viewing distance and pixel pitch.
3. Run the notebook, check the plots alignment and update render/utility/settings.txt, specifically the "radius_rgb" and "sigma_rgb".

## Running the render loop
### No Eyetracking mode
To test with if you do not have eye tracking hardware at your disposal.
```bash
.venv\Scripts\activate
python render/no-eyetracking-render-loop.py
```
This will:
- Open a borderless, overlay window that you can click through
- Capture real-time desktop images at your desired FPS (given hardware can keep up)
- Apply chromatic aberration with gaussian blur kernel via GPU shader
- Display the corrected output
- Currently no smooth shutdown, close with CTRL+C keyboardinterrupt in the cmd from which you launched the program.

## Troubleshooting
- **No frame captured**: Ensure DXcam can access your display
- **Performance issues**: Reduce `target_fps` or `overlay_size`
- **Shader errors**: Verify `shader_path` points to valid GLSL file
- **Black screen**: Check if your windows DPI scaling is at 1.00x. If Windows upscaling is not =1.00x, the DXcam capture can throw errors resulting in a black screen.

## License
None yet, repo is still a WIP
