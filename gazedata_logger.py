"""This file logs gaze data from a Tobii eye tracker to a .TXT file. It is used
when not using the Tobii hardware as a standin"""
from __future__ import annotations

import argparse
import csv
import signal
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Adjust this import to match your project structure.
# It assumes the same TobiiGazeTracker you use in ParticipantTest.py.
from render.init_eyetracking import TobiiTracker


@dataclass
class GazeSample:
    """
    Container for a single gaze sample.

    Extend this dataclass to match whatever your TobiiTracker returns.
    The fields below are a common subset:
    - timestamp_utc: ISO8601 UTC string
    - system_time_s: local monotonic or wall-clock time (float seconds)
    - gaze_x, gaze_y: normalized coordinates in [0, 1] if available
    - validity: tracker-defined quality metric / boolean
    - left_x, left_y, left_valid: per-eye data if available
    - right_x, right_y, right_valid
    """
    timestamp_utc: str
    system_time_s: float

    gaze_x: Optional[float]
    gaze_y: Optional[float]
    validity: Optional[float]

    left_x: Optional[float]
    left_y: Optional[float]
    left_valid: Optional[float]

    right_x: Optional[float]
    right_y: Optional[float]
    right_valid: Optional[float]

    # Add more fields as needed (pupil_diameter, etc.)


class GracefulKiller:
    """
    Simple Ctrl+C / SIGINT handler to allow a clean shutdown.
    """

    def __init__(self) -> None:
        self.kill_now = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame) -> None:  # type: ignore[override]
        print(f"\n[logger] Received signal {signum}, stopping after current loop...")
        self.kill_now = True


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tobii gaze logger to .txt (CSV) file.")
    parser.add_argument(
        "--participant",
        type=int,
        default=0,
        help="Optional participant number for naming/logging.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="gaze_log.txt",
        help="Output .txt path (CSV format). Default: gaze_log.txt",
    )
    parser.add_argument(
        "--flush-every",
        type=int,
        default=25,
        help="Flush to disk after this many samples (default: 25).",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=0,
        help="Optional maximum number of samples to record (0 = unlimited).",
    )
    return parser.parse_args(argv)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_gaze_sample(raw: Dict[str, Any]) -> GazeSample:
    """
    Convert a raw gaze dict (from TobiiTracker) into a GazeSample.

    You MUST adapt this function to however `TobiiTracker` exposes data.
    The code below assumes something like:

        raw = {
            "timestamp": <float or int, seconds or ms>,
            "gaze_x": <float or None>,
            "gaze_y": <float or None>,
            "validity": <float or int>,
            "left": {"x": ..., "y": ..., "valid": ...},
            "right": {"x": ..., "y": ..., "valid": ...},
        }

    If your actual structure is different, update the key access accordingly.
    """
    now_utc = _utc_now_iso()
    system_time = time.time()

    left = raw.get("left", {}) or {}
    right = raw.get("right", {}) or {}

    return GazeSample(
        timestamp_utc=now_utc,
        system_time_s=system_time,
        gaze_x=raw.get("gaze_x"),
        gaze_y=raw.get("gaze_y"),
        validity=raw.get("validity"),

        left_x=left.get("x"),
        left_y=left.get("y"),
        left_valid=left.get("valid"),

        right_x=right.get("x"),
        right_y=right.get("y"),
        right_valid=right.get("valid"),
    )


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[logger] Starting Tobii gaze logger.")
    if args.participant > 0:
        print(f"[logger] Participant: {args.participant}")
    print(f"[logger] Output file: {output_path}")
    print("[logger] Press Ctrl+C to stop.\n")

    tracker = TobiiTracker(window=None)
    if not tracker.initialize():
        print("[logger] ERROR: Failed to initialize Tobii tracker.")
        return 1

    # You may need to start an explicit "tracking" mode depending on your API.
    # For example:
    #   tracker.start_tracking()
    # or similar, if your wrapper exposes such a method.
    #
    # If TobiiTracker already starts streaming in `initialize()`, you may skip this.

    killer = GracefulKiller()

    # Open file and write header row
    fieldnames = [f.name for f in GazeSample.__dataclass_fields__.values()]  # type: ignore[attr-defined]

    n_samples = 0
    flush_every = max(1, int(args.flush_every))
    max_samples = max(0, int(args.max_samples))

    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()

        print("[logger] Logging gaze samples...")
        try:
            while not killer.kill_now:
                # Replace this with however you pull a single sample from your tracker.
                #
                # Examples:
                #   raw_sample = tracker.get_sample()
                #   raw_sample = tracker.read_gaze()
                #
                # Or, if the API is callback-based, you may instead want this script
                # to register a callback and have the callback call writer.writerow().
                #
                # For a simple polling example, let's assume a blocking or timeout-based call:
                raw_sample: Optional[Dict[str, Any]] = tracker.get_sample()  # <-- ADAPT THIS

                if raw_sample is None:
                    # No sample available - small sleep to avoid a tight loop.
                    time.sleep(0.005)
                    continue

                sample = build_gaze_sample(raw_sample)
                writer.writerow(asdict(sample))
                n_samples += 1

                if n_samples % flush_every == 0:
                    fh.flush()
                    print(f"[logger] {n_samples} samples written...", end="\r", flush=True)

                if max_samples > 0 and n_samples >= max_samples:
                    print(f"\n[logger] Reached max_samples={max_samples}, stopping...")
                    break

        except KeyboardInterrupt:
            # Redundant because of GracefulKiller, but safe.
            print("\n[logger] KeyboardInterrupt received, stopping...")
        finally:
            print(f"\n[logger] Total samples written: {n_samples}")
            try:
                # If your tracker has an explicit stop method, call it here.
                # e.g., tracker.stop_tracking()
                tracker.cleanup()
            except Exception:
                pass

    print(f"[logger] Log written to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))