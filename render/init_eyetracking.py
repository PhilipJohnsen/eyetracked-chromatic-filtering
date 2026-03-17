"""
init_eyetracking.py

Unified eye tracking interface supporting Tobii Pro SDK hardware.

The sole purpose is to deliver a gazePos in NDC coords [0,1]² for the render loop.
This allows the eyetracking render overlay to determine foveal and peripheral regions,
applying Gaussian blurring only in the periphery based on gaze position.

Tobii Research API Used Directly:
==================================
- tr.find_all_eyetrackers()        → List[EyeTracker] (NATIVE)
- tracker.subscribe_to(...)        → Subscribe to data (NATIVE)
- tr.EYETRACKER_GAZE_DATA          → Subscription constant (NATIVE)
- GazeData.left_eye / right_eye    → EyeData (NATIVE)
- EyeData.gaze_point.position_on_display_area  → (x, y) [0,1] (NATIVE)
- EyeData.gaze_point.validity      → 0 for valid (NATIVE)

No custom EyeTracker/MouseTracker in tobii_research, so we wrap only for:
  1. Lock-free buffering of gaze data (callback pre-computes, render reads)
  2. Mouse fallback when hardware unavailable
"""

import glfw
import tobii_research as tr
import time
from typing import Tuple


class TobiiGazeTracker:
    """Thin wrapper around native tr.EyeTracker with lock-free gaze buffering.
    
    The Tobii callback (_on_gaze_data) pre-computes normalized gaze position on the tracker
    thread. The render thread simply reads the cached result, avoiding lock contention."""
    
    def __init__(self):
        """Initialize (does not connect yet)."""
        self.tracker = None  # Will be assigned tr.EyeTracker instance
        self.gaze_data = None  # Buffered native tobii_research.GazeData
        self.last_valid_position = (0.5, 0.5)  #Fallback during blinks
        self._cached_position = (0.5, 0.5)  # Cached position to avoid lock contention
    
    def initialize(self) -> bool:
        """Connect to Tobii hardware using tr.find_all_eyetrackers().
        
        Subscribes to native EYETRACKER_GAZE_DATA stream.
        
        Returns:
            True if connected, False otherwise
        """
        try:
            # Use native tobii_research function
            eyetrackers = tr.find_all_eyetrackers()
            
            if not eyetrackers:
                print("[eyetracking] [ERROR] No Tobii eye trackers found")
                print("[eyetracking]   Ensure:")
                print("[eyetracking]   - Device is connected and powered")
                print("[eyetracking]   - Tobii Eye Tracker Manager is running")
                print("[eyetracking]   - Device drivers are installed")
                return False
            
            # Assign first native tr.EyeTracker instance
            self.tracker = eyetrackers[0]
            
            #Log device info from native tracker properties
            print(f"[eyetracking] [OK] Connected to: {self.tracker.model}")
            print(f"[eyetracking]   Serial: {self.tracker.serial_number}")
            print(f"[eyetracking]   Device: {self.tracker.device_name}")
            
            #Subscribe to gaze data stream
            self.tracker.subscribe_to(tr.EYETRACKER_GAZE_DATA, self._on_gaze_data)
            print("[eyetracking] [OK] Subscribed to native gaze data stream")
            
            return True
        
        except Exception as e:
            print(f"[eyetracking] [ERROR] Error initializing: {e}")
            return False
    
    def _on_gaze_data(self, gaze_data):
        """Callback for native tr.EYETRACKER_GAZE_DATA stream.
        
        Called by tracker thread. Directly updates cached position without locks.
        In CPython, tuple assignment is atomic, so no synchronization needed.

        GazeData structure (from tobii_research):
          - left_eye: EyeData with gaze_point (x, y, validity)
          - right_eye: EyeData with gaze_point (x, y, validity)
          - system_time_stamp: int
        """
        self.gaze_data = gaze_data
        
        # Pre-compute position in callback to avoid lock in render thread
        valid_points = []
        
        if gaze_data.left_eye and gaze_data.left_eye.gaze_point:
            gp = gaze_data.left_eye.gaze_point
            if gp.validity == 0 and gp.position_on_display_area:
                p = gp.position_on_display_area
                valid_points.append((p.x, p.y))
        
        if gaze_data.right_eye and gaze_data.right_eye.gaze_point:
            gp = gaze_data.right_eye.gaze_point
            if gp.validity == 0 and gp.position_on_display_area:
                p = gp.position_on_display_area
                valid_points.append((p.x, p.y))
        
        if valid_points:
            avg_x = sum(p[0] for p in valid_points) / len(valid_points)
            avg_y = sum(p[1] for p in valid_points) / len(valid_points)
            self._cached_position = (max(0.0, min(1.0, avg_x)), max(0.0, min(1.0, avg_y)))
            self.last_valid_position = self._cached_position
    
    def get_gaze_position(self) -> Tuple[float, float]:
        """Get cached normalized gaze position (no locking overhead).
        
        The callback (_on_gaze_data) pre-computes the position on the tracker thread,
        so this is just a simple read - no locks needed.
        
        During blinking, Tobii marks data as invalid. Returns the last valid position
        instead of falling back to screen center.
        
        Returns:
            (x, y) in [0,1]², or last valid position if currently blinking
        """
        return self._cached_position
    
    def calibrate(
        self,
        point_presenter=None,
        points=None,
        retries: int = 1,
        settle_time_s: float = 0.8,
    ) -> bool:
        """Run native Tobii screen-based calibration.

        Uses tobii_research.ScreenBasedCalibration and collects points in normalized
        display coordinates where (0,0) is top-left and (1,1) is bottom-right.

        Args:
            point_presenter: Optional callback called before each sample collection.
                Signature:
                  point_presenter(x, y, index, total, attempt) -> bool | None
                Return False to abort calibration.
            points: Optional sequence of normalized points [(x, y), ...].
                Defaults to a 5-point pattern suitable for Tobii Pro Fusion.
            retries: Number of additional passes for points that fail collection.
            settle_time_s: Time to wait at each point before collect_data().

        Returns:
            True if compute_and_apply succeeds, otherwise False.
        """
        if self.tracker is None:
            print("[eyetracking] [ERROR] Cannot calibrate: tracker not initialized")
            return False

        if point_presenter is None:
            print("[eyetracking] Calibration skipped: no point presenter was provided")
            print("[eyetracking] Use ParticipantTest calibration segment for interactive setup")
            return True

        if points is None:
            #Standard 5-point calibration pattern in display-area coordinates.
            points = [
                (0.50, 0.50),
                (0.10, 0.10),
                (0.90, 0.10),
                (0.10, 0.90),
                (0.90, 0.90),
            ]

        calibration = tr.ScreenBasedCalibration(self.tracker)
        points_to_collect = list(points)

        print("[eyetracking] Starting Tobii screen-based calibration...")

        try:
            calibration.enter_calibration_mode()

            for attempt in range(retries + 1):
                failed_points = []
                total = len(points_to_collect)

                for idx, (x, y) in enumerate(points_to_collect, start=1):
                    if point_presenter is not None:
                        should_continue = point_presenter(x, y, idx, total, attempt)
                        if should_continue is False:
                            print("[eyetracking] Calibration aborted by presenter callback")
                            return False

                    time.sleep(max(0.0, settle_time_s))
                    status = calibration.collect_data(float(x), float(y))

                    if status != tr.CALIBRATION_STATUS_SUCCESS:
                        failed_points.append((x, y))
                        print(f"[eyetracking]   collect_data failed at ({x:.2f}, {y:.2f})")

                if not failed_points:
                    break

                #Discarding failed points before retry is recommended by Tobii flow.
                for x, y in failed_points:
                    calibration.discard_data(float(x), float(y))

                points_to_collect = failed_points
                print(
                    f"[eyetracking] Retrying {len(points_to_collect)} failed points "
                    f"(attempt {attempt + 1}/{retries})"
                )

            result = calibration.compute_and_apply()
            if result.status == tr.CALIBRATION_STATUS_SUCCESS:
                print("[eyetracking] [OK] Calibration applied successfully")
                return True

            print(f"[eyetracking] [ERROR] Calibration apply failed: {result.status}")
            return False

        except Exception as e:
            print(f"[eyetracking] [ERROR] Calibration error: {e}")
            return False
        finally:
            try:
                calibration.leave_calibration_mode()
            except Exception as e:
                print(f"[eyetracking] [ERROR] Failed to leave calibration mode cleanly: {e}")
    
    def cleanup(self):
        """Unsubscribe from native tracker stream and cleanup."""
        if self.tracker is not None:
            try:
                self.tracker.unsubscribe_from(tr.EYETRACKER_GAZE_DATA)
                print("[eyetracking] [OK] Disconnected")
            except Exception as e:
                print(f"[eyetracking] [ERROR] Cleanup error: {e}")
            finally:
                self.tracker = None


class MouseTracker:
    """Fallback: Mouse-based gaze (no native tobii_research equivalent)."""
    
    def __init__(self, window):
        self.window = window
    
    def initialize(self) -> bool:
        print("[eyetracking] [INFO] Using mouse (development mode, no Tobii hardware)")
        return True
    
    def get_gaze_position(self) -> Tuple[float, float]:
        """Get gaze from mouse cursor."""
        try:
            mx, my = glfw.get_cursor_pos(self.window)
            w, h = glfw.get_framebuffer_size(self.window)
            return (
                max(0.0, min(1.0, mx / max(1, w))),
                max(0.0, min(1.0, my / max(1, h)))
            )
        except:
            return (0.5, 0.5)
    
    def calibrate(self) -> bool:
        return True
    
    def cleanup(self):
        pass


def initialize_eyetracker(window, gaze_source: str = "tobii"):
    """Initialize eye tracking: try native tobii_research hardware, fallback to mouse.
    
    Uses native tobii_research.find_all_eyetrackers() to detect hardware.
    
    Args:
        window: GLFW window
        gaze_source: "tobii" to attempt hardware (falls back to mouse if unavailable),
                     "mouse" to force mouse tracker (development/baseline mode)
    
    Returns:
        TobiiGazeTracker or MouseTracker instance
    """
    if gaze_source == "tobii":
        tracker = TobiiGazeTracker()
        if tracker.initialize():
            return tracker
        print("[eyetracking] Tobii not found, falling back to mouse")
    else:
        print(f"[eyetracking] gaze_source='{gaze_source}': using mouse tracker")
    mt = MouseTracker(window)
    mt.initialize()
    return mt


# Legacy interface
def get_gaze_pos(window, win_width: int, win_height: int, tracker=None) -> Tuple[float, float]:
    """Backward compatibility."""
    if tracker is None:
        tracker = MouseTracker(window)
    return tracker.get_gaze_position()
