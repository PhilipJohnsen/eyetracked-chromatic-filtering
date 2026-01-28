#A python implementation using DXcam to duplicate desktop via DXGI with high FPS. 

#This video stream is used to capture the users desktop, and deliver images to the rendering shader.
#A python implementation using DXcam to duplicate desktop via DXGI with high FPS. 

#This video stream is used to capture the users desktop, and deliver images to the rendering shader.

import time
import cv2
import numpy as np
import dxcam
import msvcrt

def main():
    #Make a capture, choose primary monitor
    cam = dxcam.create(output_color="RGB")
    cam.start(target_fps=60) #Adjust to match display refresh rate

    last = time.time()
    frames = 0

    print("Press 'q' in this console to quit (or Ctrl+C).")
    try:
        while True:
            frame = cam.get_latest_frame()  # numpy array (H, W, 3) or None
            if frame is None:
                continue

            # headless: do not open any window; process frame here if needed

            frames += 1
            if time.time() - last >= 1.0:  # Every second
                print("FPS:", frames)  # Print frames per second
                frames = 0
                last = time.time()  # Reset last time

            # Check for console keypress (Windows)
            if msvcrt.kbhit():
                key = msvcrt.getwch()
                if key.lower() == 'q':
                    print("Quitting...")
                    break
    except KeyboardInterrupt:
        print("Interrupted by user")
    finally:
        # Ensure cleanup always runs
        cam.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
