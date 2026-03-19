import time
import threading
import sys

try:
    import tobii_research as tr
except ImportError:
    print("tobii_research is not installed. Install with: pip install tobii-research")
    sys.exit(1)


def main():
    print("Looking for connected Tobii eye trackers...")
    found_eyetrackers = tr.find_all_eyetrackers()

    if not found_eyetrackers:
        print("No Tobii eye trackers found.")
        return

    # For testing, just take the first tracker found
    eyetracker = found_eyetrackers[0]
    print(f"Using eye tracker:\n"
          f"  Address: {eyetracker.address}\n"
          f"  Serial number: {eyetracker.serial_number}\n"
          f"  Model: {eyetracker.model}\n"
          f"  Firmware version: {eyetracker.firmware_version}")

    stop_event = threading.Event()

    def gaze_data_callback(gaze_data):
        """
        Callback function called by tobii_research for each gaze data sample.

        gaze_data is a dict as described in tobii_research docs:
        - gaze_data["device_time_stamp"]
        - gaze_data["system_time_stamp"]
        - gaze_data["left_gaze_point_on_display_area"]   -> (x, y) in [0..1]
        - gaze_data["right_gaze_point_on_display_area"]  -> (x, y) in [0..1]
        - gaze_data["left_gaze_origin_in_user_coordinate_system"]
        - gaze_data["right_gaze_origin_in_user_coordinate_system"]
        - gaze_data["left_gaze_point_validity"]          -> 0 or 1
        - gaze_data["right_gaze_point_validity"]         -> 0 or 1
        """
        # You can filter by validity; here we just print everything
        left_point = gaze_data.get("left_gaze_point_on_display_area")
        right_point = gaze_data.get("right_gaze_point_on_display_area")

        left_valid = gaze_data.get("left_gaze_point_validity")
        right_valid = gaze_data.get("right_gaze_point_validity")

        device_ts = gaze_data.get("device_time_stamp")
        system_ts = gaze_data.get("system_time_stamp")

        print(
            f"DeviceTS={device_ts} SystemTS={system_ts} | "
            f"L: {left_point} (valid={left_valid}) | "
            f"R: {right_point} (valid={right_valid})"
        )

        # Optionally stop after some condition (e.g., N samples or time)


    # Subscribe to gaze data
    print("Subscribing to gaze data...")
    eyetracker.subscribe_to(
        tr.EYETRACKER_GAZE_DATA,
        gaze_data_callback,
        as_dictionary=True
    )

    try:
        # Run for 10 seconds; adjust as needed
        duration_sec = 10
        print(f"Collecting gaze data for {duration_sec} seconds...")
        stop_event.wait(timeout=duration_sec)
    finally:
        print("Unsubscribing from gaze data and shutting down.")
        eyetracker.unsubscribe_from(tr.EYETRACKER_GAZE_DATA, gaze_data_callback)


if __name__ == "__main__":
    main()