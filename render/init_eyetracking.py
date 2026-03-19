import threading
import time
from typing import Tuple

try:
    import tobii_research as tr
except ImportError:
    tr = None


class BaseTracker:
    def __init__(self, window):
        self.window = window

    def calibrate(self):
        """Optional: perform calibration. In your setup you calibrate via Tobii Manager, so this can be a no-op."""
        pass

    def get_gaze_position(self) -> Tuple[float, float]:
        """Return normalized gaze position (x, y) in [0,1]."""
        raise NotImplementedError

    def cleanup(self):
        """Release resources / subscriptions."""
        pass


# -----------------------------
# Mouse-based tracker fallback
# -----------------------------
import glfw

class MouseTracker(BaseTracker):
    def get_gaze_position(self) -> Tuple[float, float]:
        # Use window size to normalize mouse position
        win_width, win_height = glfw.get_window_size(self.window)
        mouse_x, mouse_y = glfw.get_cursor_pos(self.window)

        # Clamp to window
        mouse_x = max(0, min(mouse_x, win_width))
        mouse_y = max(0, min(mouse_y, win_height))

        # Normalize to [0, 1]
        norm_x = mouse_x / max(1, win_width)
        norm_y = mouse_y / max(1, win_height)

        return (norm_x, norm_y)


# -----------------------------
# Tobii-based tracker
# -----------------------------

class TobiiTracker(BaseTracker):
    def __init__(self, window):
        super().__init__(window)

        if tr is None:
            raise RuntimeError(
                "tobii_research module not available. Install with: pip install tobii-research"
            )

        self._latest_lock = threading.Lock()
        self._latest_gaze = (0.5, 0.5)  # start in center
        self._has_valid_gaze = False
        self._eyetracker = None

        self._start_tobii_stream()

    # --- Internal helpers ---

    def _start_tobii_stream(self):
        eyetrackers = tr.find_all_eyetrackers()
        if not eyetrackers:
            raise RuntimeError("No Tobii eye trackers found")

        self._eyetracker = eyetrackers[0]
        print(
            f"[tobii] Using eye tracker {self._eyetracker.model} "
            f"SN={self._eyetracker.serial_number} FW={self._eyetracker.firmware_version}"
        )

        self._eyetracker.subscribe_to(
            tr.EYETRACKER_GAZE_DATA,
            self._gaze_callback,
            as_dictionary=True,
        )

    def _gaze_callback(self, gaze_data):
        """
        Gaze callback using tobii_research.

        Fields (with as_dictionary=True):
          - left_gaze_point_on_display_area:  (x, y)
          - right_gaze_point_on_display_area: (x, y)
          - left_gaze_point_validity:  0 or 1
          - right_gaze_point_validity: 0 or 1
        """
        left_point = gaze_data.get("left_gaze_point_on_display_area")
        right_point = gaze_data.get("right_gaze_point_on_display_area")
        left_valid = gaze_data.get("left_gaze_point_validity", 0)
        right_valid = gaze_data.get("right_gaze_point_validity", 0)

        x = y = None
        valid = False

        # Binocular average when both are valid
        if left_valid == 1 and right_valid == 1 and left_point and right_point:
            x = (left_point[0] + right_point[0]) * 0.5
            y = (left_point[1] + right_point[1]) * 0.5
            valid = True
        elif left_valid == 1 and left_point:
            x, y = left_point
            valid = True
        elif right_valid == 1 and right_point:
            x, y = right_point
            valid = True

        if valid and x is not None and y is not None:
            # Ensure we stay in [0, 1] range to avoid shader issues
            x = max(0.0, min(1.0, float(x)))
            y = max(0.0, min(1.0, float(y)))
            with self._latest_lock:
                self._latest_gaze = (x, y)
                self._has_valid_gaze = True

    # --- Public API expected by eyetracked-render-loop.py ---

    def calibrate(self):
        """
        You are calibrating via Tobii Eye Tracker Manager.
        The device stores calibration and applies it to the gaze stream automatically,
        so there is nothing we need to do here.
        """
        print("[tobii] Using existing calibration from Tobii Eye Tracker Manager.")

    def get_gaze_position(self) -> Tuple[float, float]:
        """Return latest known gaze position in [0,1] coordinates."""
        with self._latest_lock:
            return self._latest_gaze

    def cleanup(self):
        if self._eyetracker is not None:
            try:
                self._eyetracker.unsubscribe_from(tr.EYETRACKER_GAZE_DATA, self._gaze_callback)
            except Exception as e:
                print(f"[tobii] Error while unsubscribing: {e}")
            self._eyetracker = None
        print("[tobii] Tracker cleaned up.")


# -----------------------------
# Factory used by eyetracked-render-loop.py
# -----------------------------

def initialize_eyetracker(window, gaze_source: str = "mouse") -> BaseTracker:
    """
    Factory function used by eyetracked-render-loop.py.

    Args:
        window: GLFW window handle (used for mouse fallback).
        gaze_source: "tobii" or "mouse" (comes from settings).

    Returns:
        An object with .calibrate(), .get_gaze_position(), .cleanup().
    """
    gaze_source = (gaze_source or "mouse").lower().strip()

    if gaze_source == "tobii":
        print("[eyetracking] Initializing Tobii-based tracker")
        return TobiiTracker(window)
    else:
        print("[eyetracking] Using mouse-based tracker")
        return MouseTracker(window)