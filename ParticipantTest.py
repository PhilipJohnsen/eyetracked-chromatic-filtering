"""Participant-facing experiment flow entry point.

This version uses a single fullscreen window and frame-based transitions to:
- Keep keyboard focus stable across all segments
- Remove visible close/open stutter between screens
- Support the current protocol (intro, calibration, reading practice,
  three reading-comprehension blocks with questionnaires and breaks,
  detectability practice + task blocks, final questionnaire, and debrief)

Screen class hierarchy
----------------------
BaseScreen          â€” shared root/helper access, panel construction
  DarkInfoScreen    â€” dark background, title + body, SPACE to continue
  LightTextScreen   â€” light background, scrollable long-form reading text
  MCQScreen         â€” light background, single multiple-choice question
  DetectabilityTextScreen     â€” light background, auto-advances after N seconds
  DetectabilityResponseScreen â€” light background, asks which blur was perceived
"""

from __future__ import annotations

import csv
from dataclasses import asdict
from itertools import permutations
import subprocess
import sys
import time
import tkinter as tk
from tkinter import messagebox
import webbrowser
from pathlib import Path
from typing import Callable

from render.init_eyetracking import TobiiGazeTracker
from experiment_helper.content_loading_experiment import ContentLoader
from experiment_helper.scheduling_experiment import (
    build_counterbalancing_report_lines,
    build_latin_filter_order,
    build_main_trial_file_names,
    build_paragraph_order,
    build_practice_trial_file_names,
    prepare_session_order,
    reading_cycle_orders,
    validate_counterbalancing_matrix,
)
from experiment_helper.session_logging_experiment import SessionLogger
from experiment_helper.slide_classes_experiment import (
    CALIBRATION_COPY,
    DETECTABILITY_ACK_COPY,
    DETECTABILITY_TRANSITION_COPY,
    DarkInfoCopy,
    DarkInfoScreen,
    DetectabilityResponseScreen,
    DetectabilityTextScreen,
    INTRO_COPY,
    LightTextScreen,
    MCQScreen,
    ONE_MINUTE_BREAK_COPY,
    QUALITATIVE_QUESTIONS_COPY,
    READING_COMPREHENSION_INTRO_COPY,
    READING_TASK_REMINDER_COPY,
    STUDY_PURPOSE_COPY,
    THANK_YOU_COPY,
    TimedBreakScreen,
    THREE_MINUTE_BREAK_COPY,
)


class ExperimentContentError(RuntimeError):
    """Raised when required experiment text content cannot be loaded."""


# Initialize content via helper module.
BASE_DIR = Path(__file__).resolve().parent

# ============================================================================
# GLOBAL EXPERIMENT STATE: Content, Configuration, and Outcomes Tracking
# ============================================================================

PRACTICE_PARAGRAPH_FILE = "generations.txt"
# Detectability trial structure: 6 practice + 3 blocks of 12 trials each = 42 total
DETECTABILITY_TEST_TRIALS = 6  # Number of practice trials
DETECTABILITY_BLOCK_TRIALS = 12  # Trials per main block
DETECTABILITY_BLOCK_COUNT = 3  # Number of main trial blocks
DETECTABILITY_TOTAL_TRIALS = DETECTABILITY_TEST_TRIALS + (DETECTABILITY_BLOCK_TRIALS * DETECTABILITY_BLOCK_COUNT)  # 42 total

CONTENT_LOADER = ContentLoader(
    base_dir=BASE_DIR,
    practice_paragraph_file=PRACTICE_PARAGRAPH_FILE,
    detectability_test_trials=DETECTABILITY_TEST_TRIALS,
    detectability_block_trials=DETECTABILITY_BLOCK_TRIALS,
    detectability_block_count=DETECTABILITY_BLOCK_COUNT,
)
CONTENT_BUNDLE = CONTENT_LOADER.load()
CONTENT_VALIDATION = CONTENT_LOADER.validate(CONTENT_BUNDLE)

TEXTS_BASE_DIR = CONTENT_BUNDLE.paths.texts_base_dir
PARAGRAPH_TEXT_DIR = CONTENT_BUNDLE.paths.paragraph_text_dir
MCQ_TEXT_DIR = CONTENT_BUNDLE.paths.mcq_text_dir
DETECTABILITY_TEXT_DIR = CONTENT_BUNDLE.paths.detectability_text_dir

PARAGRAPH_TEXT_MAP = CONTENT_BUNDLE.paragraph_text_map
MCQ_ITEMS_BY_PARAGRAPH = CONTENT_BUNDLE.mcq_items_by_paragraph
TRAINING_TEXT = CONTENT_BUNDLE.training_text
MCQ_ITEMS = CONTENT_BUNDLE.mcq_items_practice
DETECTABILITY_TRIAL_MAP = CONTENT_BUNDLE.detectability_trial_map
DETECTABILITY_TEXTS = CONTENT_BUNDLE.detectability_texts


def _collect_content_load_errors() -> list[str]:
    """Return a list of required-content loading errors, if any."""
    return list(CONTENT_VALIDATION.errors)

# Timing parameters for detectability task stimulus presentation
# Fixed black-screen duration shown before every detectability stimulus.
# Must be >= worst-case renderer startup time (Tobii eyetracking ~3 s)
# so the pre-trial gap is always identical regardless of blur condition.
DETECTABILITY_PRE_TRIAL_PAUSE_S = 3.5  # Black screen before stimulus (allows renderer init)
DETECTABILITY_POST_TRIAL_PAUSE_S = 0.2  # Black screen after stimulus
DETECTABILITY_READING_TIME_S = 4.0  # Duration each stimulus text is displayed

#Eye movement event extraction
#Generally taken from Kar's paper in IEEE
EYE_EVENT_VELOCITY_THRESHOLD_NDC_PER_S = 2.0 #2 seems to work when testing on my own saccades and fixations
EYE_EVENT_MIN_FIXATION_MS = 50.0 #Lower than Kar, to ensure that small fixations are not missed
EYE_EVENT_MIN_SACCADE_MS = 24.0 #Minimum duration for saccade, a bit higher than Kar to be less trigger happy on saccade event
EYE_EVENT_MAX_SACCADE_MS = 200.0 #Maximum duration for saccade, same as Kar
EYE_EVENT_MIN_BLINK_MS = 100.0 #Lower than Kar (who has 300ms), to ensure no blinks are missed
EYE_EVENT_MAX_INTER_SAMPLE_GAP_S = 0.05 #Forced gap between sampling to avoid casematching fixations or blinks due to no new info

# Blur conditions and counterbalancing design
FILTER_CONDITIONS = ["none", "full", "eyetracked"]  # The three conditions
# All permutations of conditions for Latin-square counterbalancing
LATIN_FILTER_ORDERS = [list(p) for p in permutations(FILTER_CONDITIONS)]

# Post-experiment questionnaire URLs (hosted on SurveyXact)
QUESTIONNAIRE_URL_FULL = "https://www.survey-xact.dk/LinkCollector?key=NRCKWQCGJP95"  # Full questionnaire
QUESTIONNAIRE_URL_EYES = "https://www.survey-xact.dk/LinkCollector?key=3MPW279ZLN9N"  # Eye-strain focused
QUESTIONNAIRE_URL_DEMOGRAPHICS = "https://www.survey-xact.dk/LinkCollector?key=N453H41CU1CJ"  # Demographics survey
QUESTIONNAIRE_TEXT = "Link to questionnaire"
# Case variants for backwards compatibility
questionnaire_url_full = QUESTIONNAIRE_URL_FULL
questionnaire_url_eyes = QUESTIONNAIRE_URL_EYES
questionnaire_url_demographics = QUESTIONNAIRE_URL_DEMOGRAPHICS
# Outcome metrics collected during the experiment

OUTCOME_KEYS = [
    "reading_comprehension_accuracy_pct",
    "reading_time_sec",
    "detectability_identification_accuracy_true_false",
    "detectability_collapsed_binary_dprime_hautus",
    "detectability_response_time_ms",
    "nasa_tlx_overall_workload",
    "eye_strain_symptom_total",
    "sus_usability_score_0_50",
    "blinks_count",
    "saccades_count",
    "saccades_duration_ms",
    "fixations_count_and_length_ms",
# ============================================================================
# DATA STRUCTURES FOR EXPERIMENT CONTENT
# ============================================================================
# These dataclasses store text content for different screens and are instantiated
# at module load time with specific text for each experiment phase.

]


# ---------------------------------------------------------------------------
# Experiment orchestrator
# ---------------------------------------------------------------------------

class ParticipantExperiment:
    """Main experiment controller: manages window, flow, logging, and eye-tracking.
    
        This class orchestrates the entire participant-facing experiment, including:
        - Window and UI state management
        - Experiment flow (showing screens in sequence)
        - Blur renderer subprocess management
        - Eye-tracking initialization and data collection
        - Session logging (events, segments, outcomes, eye data)
        - Participant randomization and counterbalancing
    
        Typical use:
            app = ParticipantExperiment()
            exit_code = app.run()  # Run experiment to completion
            app.close()  # Clean up resources
        """
    
    def __init__(self) -> None:
        """Initialize window, state, experiment order, logging, and screen instances."""
            # Create and configure fullscreen window
        self.root = tk.Tk()
        self.root.title("Eye-tracked Chromatic Filtering Experiment")
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="black")

        content_errors = _collect_content_load_errors()
        if content_errors:
            error_message = "Failed to load required experiment texts:\n\n- " + "\n- ".join(content_errors)
            self._show_fatal_startup_error(error_message)
            raise ExperimentContentError(error_message)
    # UI state: track current frame and quit/skip requests

        self.current_frame: tk.Frame | None = None
        self.quit_requested = False
        self._wait_var: tk.StringVar | None = None
        self._timer_wait_active = False
        self._skip_timer_requested = False
            # Blur renderer state
        self.active_blur_condition: str = "none"
        self.active_blur_process: subprocess.Popen | None = None
        self.active_blur_log_handle = None
        self.last_blur_start_ok = False
        self.last_blur_start_msg = ""
            # Participant identifier and experiment parameters
        self.base_dir = Path(__file__).resolve().parent
            # Resolve participant number from CLI --participant=N or env var
        self.participant_number = self._resolve_participant_number()
            # Determine Latin-square variant based on participant number
        self.latin_variant_index = (self.participant_number - 1) % len(LATIN_FILTER_ORDERS)
            # Build session order: which tasks, in what order, with what parameters
        try:
            self.session_order: dict[str, object] = self._prepare_session_order()
            self._validate_counterbalancing_matrix(max_participant=24)
            self._print_counterbalancing_report(max_participant=24)
        except ExperimentContentError as exc:
            self._show_fatal_startup_error(str(exc))
            raise
    # Session IDs and logging paths

        self.participant_id = f"P{self.participant_number:03d}"
        self.session_id = "S01"
        self.session_dir: Path | None = None
        self.events_log_path: Path | None = None
        self.segments_log_path: Path | None = None
        self.manifest_log_path: Path | None = None
        self.eye_events_log_path: Path | None = None
        self.eye_windows_log_path: Path | None = None
        self.outcomes_flat_log_path: Path | None = None
        self.detectability_trials_log_path: Path | None = None
        self.detectability_summary_log_path: Path | None = None
        self._log_fallback_active = False
        self._log_fallback_reason = ""
            # In-memory event buffers (used if file writes fail)
        self._in_memory_events: list[dict[str, object]] = []
        self._in_memory_segments: list[dict[str, object]] = []
        self._logging_finalized = False
    # Session metrics: collected during experiment and written at end

        self._segment_starts: dict[str, tuple[str, float]] = {}
        self._reading_time_by_index: dict[int, float] = {}
        self._reading_mcq_summary_by_index: dict[int, dict[str, object]] = {}
        self._detectability_trial_records: list[dict[str, object]] = []
        self._eye_movement_window_summaries: list[dict[str, object]] = []
        self._eye_capture_windows: list[dict[str, object]] = []
        self._active_eye_window_starts: dict[str, dict[str, object]] = {}
        self._session_eyetracker: TobiiGazeTracker | None = None
        self._eyetracker_init_attempted = False
        self._last_mcq_result: dict[str, object] | None = None
    # Outcomes and logging backend

        self._session_logger = SessionLogger(
            base_dir=self.base_dir,
            participant_number=self.participant_number,
            latin_variant_index=self.latin_variant_index,
            session_order=self.session_order,
            outcome_keys=OUTCOME_KEYS,
        )
        self.outcomes = self._session_logger.outcomes

        # Mark outcomes from external sources (SurveyXact, eyetracker pipeline)
        self.outcomes["nasa_tlx_overall_workload"]["status"] = "pending_surveyxact"
        self.outcomes["nasa_tlx_overall_workload"]["source"] = "surveyxact"
        self.outcomes["eye_strain_symptom_total"]["status"] = "pending_surveyxact"
        self.outcomes["eye_strain_symptom_total"]["source"] = "surveyxact"
        self.outcomes["sus_usability_score_0_50"]["status"] = "pending_surveyxact"
        self.outcomes["sus_usability_score_0_50"]["source"] = "surveyxact"
        self.outcomes["blinks_count"]["status"] = "pending_eyetracker_pipeline"
        self.outcomes["saccades_count"]["status"] = "pending_eyetracker_pipeline"
        self.outcomes["saccades_duration_ms"]["status"] = "pending_eyetracker_pipeline"
        self.outcomes["fixations_count_and_length_ms"]["status"] = "pending_eyetracker_pipeline"
        
        # Record session start time (now that _session_logger is initialized)
        self.session_started_utc = self._utc_now_iso()
    # Initialize session logging (creates directories and log file handles)

        self._init_session_logging()
    # Bind window close button and keyboard shortcuts

        self.root.protocol("WM_DELETE_WINDOW", self._request_quit)
        self.root.bind("<Control-Shift-Q>", self._request_quit, add="+")
        # Register both key spellings to be robust across keyboard/layout handling.
        self.root.bind("<Control-Shift-R>", self._request_timer_skip, add="+")
        self.root.bind("<Control-Shift-r>", self._request_timer_skip, add="+")
    # Instantiate screen objects (one per type, reused across experiment)

        # Screen instances - one per screen type, reused across segments.
        self._dark_info = DarkInfoScreen(self)
        self._light_text = LightTextScreen(self)
        self._mcq = MCQScreen(self)
        self._det_text = DetectabilityTextScreen(self)
        self._det_response = DetectabilityResponseScreen(self)
        self._timed_break = TimedBreakScreen(self)

    def _show_fatal_startup_error(self, message: str) -> None:
        """Show a fatal startup error and close the window."""
        try:
            messagebox.showerror("Experiment Content Error", message, parent=self.root)
        except tk.TclError:
            pass
        self.quit_requested = True
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _resolve_participant_number(self) -> int:
        """Resolve participant number from CLI flag or environment.

        Supported CLI forms:
        - --participant=3
        - --participant 3
            # Check command-line arguments for --participant flag
        """
        argv = sys.argv[1:]
        for idx, arg in enumerate(argv):
                        # Format: --participant=3
            if arg.startswith("--participant="):
                raw = arg.split("=", 1)[1].strip()
                if raw.isdigit() and int(raw) > 0:
                    return int(raw)
                        # Format: --participant 3
            if arg == "--participant" and idx + 1 < len(argv):
                raw = argv[idx + 1].strip()
                    # Fallback: check PARTICIPANT_NUMBER environment variable
                if raw.isdigit() and int(raw) > 0:
                    return int(raw)

        env_raw = ""
        try:
            import os
            env_raw = os.getenv("PARTICIPANT_NUMBER", "").strip()
        except Exception:
            env_raw = ""

        if env_raw.isdigit() and int(env_raw) > 0:
            return int(env_raw)
            # Default to participant 1 if no number provided
        return 1

    def _practice_trial_file_names(self) -> list[str]:
        """Return list of practice trial filenames (trial_01.txt through trial_06.txt)."""
        return build_practice_trial_file_names(DETECTABILITY_TEST_TRIALS)

    def _main_trial_file_names(self) -> list[str]:
        """Return list of main block trial filenames (trial_07.txt through trial_42.txt)."""
        return build_main_trial_file_names(DETECTABILITY_TEST_TRIALS, DETECTABILITY_TOTAL_TRIALS)

    def _reading_cycle_orders(self) -> list[list[str]]:
        """Return the six unique reading orders for the three main paragraphs."""
        try:
            return reading_cycle_orders(PARAGRAPH_TEXT_MAP.keys(), PRACTICE_PARAGRAPH_FILE)
        except ValueError as exc:
            raise ExperimentContentError(str(exc)) from exc

    def _build_paragraph_order(self) -> list[str]:
        """Build reading order with 6-participant counterbalancing cycles.

        Participants are grouped in cycles of six (1-6, 7-12, 13-18, ...).
        Within each cycle, the three main reading paragraphs appear in all 3! = 6
        unique orders exactly once. The practice paragraph is always first.
        """
        try:
            return build_paragraph_order(
                self.participant_number,
                PARAGRAPH_TEXT_MAP.keys(),
                PRACTICE_PARAGRAPH_FILE,
            )
        except ValueError as exc:
            raise ExperimentContentError(str(exc)) from exc

    def _validate_counterbalancing_matrix(self, *, max_participant: int) -> None:
        """Validate reading and condition-order counterbalancing over participant cycles."""
        try:
            validate_counterbalancing_matrix(
                max_participant=max_participant,
                paragraph_files=PARAGRAPH_TEXT_MAP.keys(),
                practice_paragraph_file=PRACTICE_PARAGRAPH_FILE,
                latin_filter_orders=LATIN_FILTER_ORDERS,
            )
        except ValueError as exc:
            raise ExperimentContentError(str(exc)) from exc

    def _print_counterbalancing_report(self, *, max_participant: int) -> None:
        """Print counterbalancing details and cycle-level checks to console."""
        lines = build_counterbalancing_report_lines(
            participant_number=self.participant_number,
            latin_variant_index=self.latin_variant_index,
            session_order=self.session_order,
            max_participant=max_participant,
            paragraph_files=PARAGRAPH_TEXT_MAP.keys(),
            practice_paragraph_file=PRACTICE_PARAGRAPH_FILE,
            latin_filter_orders=LATIN_FILTER_ORDERS,
        )
        for line in lines:
            print(line)


    def _build_latin_filter_order(self, n_trials: int, *, block_offset: int = 0) -> list[str]:
        """Generate filter order for n_trials using Latin-square counterbalancing.
        
                Uses participant's Latin variant and optional block offset to shift the
                base pattern. Repeats the 3-condition pattern (none/full/eyetracked) as needed.
        
                Args:
                    n_trials: How many trials need filter assignments
                    block_offset: Block index (used to rotate pattern)
        
                Returns:
                    List of condition strings repeated to reach n_trials
        """
                # Get base pattern for this participant's Latin-square variant
        return build_latin_filter_order(
            n_trials,
            LATIN_FILTER_ORDERS,
            self.latin_variant_index,
            block_offset=block_offset,
        )

    def _prepare_session_order(self) -> dict[str, object]:
        """Build complete experiment session plan: which tasks in what order with what parameters.
        
                This is the master schedule generated once at init time, used by run() to
                execute the experiment in the correct sequence. Includes:
                - Reading paragraphs and their MCQs
                - Detectability trials (practice and main blocks) with filter assignments
                - Breaks and questionnaires
        
                Returns:
                    Dict with 'steps' key containing list of task dictionaries
        """
        try:
            session_order = prepare_session_order(
                participant_number=self.participant_number,
                latin_variant_index=self.latin_variant_index,
                paragraph_files=PARAGRAPH_TEXT_MAP.keys(),
                practice_paragraph_file=PRACTICE_PARAGRAPH_FILE,
                detectability_trial_map=DETECTABILITY_TRIAL_MAP,
                detectability_test_trials=DETECTABILITY_TEST_TRIALS,
                detectability_block_trials=DETECTABILITY_BLOCK_TRIALS,
                detectability_block_count=DETECTABILITY_BLOCK_COUNT,
                detectability_total_trials=DETECTABILITY_TOTAL_TRIALS,
                filter_conditions=FILTER_CONDITIONS,
                latin_filter_orders=LATIN_FILTER_ORDERS,
            )
        except ValueError as exc:
            raise ExperimentContentError(str(exc)) from exc

        print(
            "[schedule] participant="
            f"{self.participant_number} "
            f"reading_order={int(session_order.get('reading_order_index', -1)) + 1}/6 "
            f"latin_variant={self.latin_variant_index + 1}/{len(LATIN_FILTER_ORDERS)} "
            f"main_detectability_counts={session_order.get('main_filter_counts', {})}"
        )
        return session_order

    # -- logging helpers ------------------------------------------------------
    def _utc_now_iso(self) -> str:
        """Return current UTC timestamp as ISO 8601 string."""
        return self._session_logger.utc_now_iso()

    def _safe_write_event(self, event: dict[str, object]) -> None:
        """Log an event (single timestamped action/state change).
        
            Writes to events CSV or in-memory buffer if file writes fail.
        """
        self._session_logger.safe_write_event(event)
        self._in_memory_events = self._session_logger.state.in_memory_events
        self._log_fallback_active = self._session_logger.state.fallback_active
        self._log_fallback_reason = self._session_logger.state.fallback_reason

    def _safe_write_segment_row(self, row: dict[str, object]) -> None:
        """Log a segment completion (timing, metadata, outcomes for one experiment phase).
        
            Writes to segments CSV or in-memory buffer if file writes fail.
        """
        self._session_logger.safe_write_segment_row(row)
        self._in_memory_segments = self._session_logger.state.in_memory_segments
        self._log_fallback_active = self._session_logger.state.fallback_active
        self._log_fallback_reason = self._session_logger.state.fallback_reason

    def _write_manifest(self) -> None:
        """Write session manifest: participant ID, session ID, participant number, start time."""
        self._session_logger.outcomes = self.outcomes
        self._session_logger.write_manifest(
            notes={
                "surveyxact": "Questionnaire variables are marked pending_surveyxact until SurveyXact integration is completed.",
                "eye_metrics": "Blink/saccade/fixation variables are marked pending_eyetracker_pipeline until the eye-event extraction stage is connected.",
            }
        )
        self._log_fallback_active = self._session_logger.state.fallback_active
        self._log_fallback_reason = self._session_logger.state.fallback_reason

    def _init_session_logging(self) -> None:
        """Create session directory, open log file handles, write manifest."""
        paths = self._session_logger.initialize_session_paths()
        self.session_id = self._session_logger.session_id
        self.session_dir = paths.session_dir
        self.events_log_path = paths.events_log_path
        self.segments_log_path = paths.segments_log_path
        self.manifest_log_path = paths.manifest_log_path
        self.eye_events_log_path = paths.eye_events_log_path
        self.eye_windows_log_path = paths.eye_windows_log_path
        self.outcomes_flat_log_path = paths.outcomes_flat_log_path
        self.detectability_trials_log_path = paths.detectability_trials_log_path
        self.detectability_summary_log_path = paths.detectability_summary_log_path
        self._log_fallback_active = self._session_logger.state.fallback_active
        self._log_fallback_reason = self._session_logger.state.fallback_reason

        self._safe_write_event(
            {
                "event_type": "session_started",
                "timestamp_utc": self._utc_now_iso(),
                "payload": {
                    "participant_id": self.participant_id,
                    "session_id": self.session_id,
                    "participant_number": self.participant_number,
                    "latin_variant_index": self.latin_variant_index,
                    "fallback_active": self._log_fallback_active,
                    "fallback_reason": self._log_fallback_reason,
                },
            }
        )
        self._write_manifest()

    def _log_event(self, event_type: str, payload: dict[str, object]) -> None:
        """Log a timestamped event with type and payload dict."""
        self._session_logger.log_event(event_type, payload)

    def _segment_start(self, segment_name: str, payload: dict[str, object] | None = None) -> None:
        """Mark the start of a numbered experiment segment (timing checkpoint)."""
        self._session_logger.segment_start(
            segment_name,
            payload,
            start_eye_window=lambda label, data: self._eye_window_start(label, payload=data),
        )
        self._segment_starts = self._session_logger.segment_starts

    def _segment_end(self, segment_name: str, *, status: str, metrics: dict[str, object] | None = None) -> None:
        """Mark the end of a segment and write segment log row with status/metrics."""
        self._session_logger.segment_end(
            segment_name,
            status=status,
            metrics=metrics,
            end_eye_window=lambda label, state: self._eye_window_end(label, status=state),
        )
        self._segment_starts = self._session_logger.segment_starts
        self._in_memory_segments = self._session_logger.state.in_memory_segments
        self._log_fallback_active = self._session_logger.state.fallback_active
        self._log_fallback_reason = self._session_logger.state.fallback_reason

    def _ensure_session_eyetracker(self, *, force_retry: bool = False) -> TobiiGazeTracker | None:
        """Initialize eye tracker on first call (or retry if forced).
        
                Returns:
                    TobiiGazeTracker instance if successful, None if unavailable or error
        """
        if self._session_eyetracker is not None:
            return self._session_eyetracker
        if self._eyetracker_init_attempted and not force_retry:
            return None

        self._eyetracker_init_attempted = True
        tracker = TobiiGazeTracker()
        if not tracker.initialize():
            return None
        self._session_eyetracker = tracker
        return tracker

    def _latest_tracker_timestamp(self) -> int | None:
        """Get most recent eye-tracking data timestamp from tracker."""
        tracker = self._session_eyetracker
        if tracker is None:
            return None
        return tracker.get_latest_system_time_stamp()

    def _eye_window_start(self, label: str, payload: dict[str, object] | None = None) -> None:
        """Mark start of an eye capture window (linked to a segment for analysis)."""
        tracker = self._ensure_session_eyetracker()
        start_ts = self._latest_tracker_timestamp() if tracker is not None else None

        data = dict(payload or {})
        self._active_eye_window_starts[label] = {
            "label": label,
            "condition": str(data.get("condition", "none")),
            "section": str(data.get("section", "")),
            "section_index": int(data.get("section_index", 0) or 0),
            "phase": str(data.get("phase", "")),
            "step": str(data.get("step", "")),
            "trial_index": int(data.get("trial_index", 0) or 0),
            "trial_file": str(data.get("trial_file", "")),
            "tracker_available": bool(tracker is not None),
            "start_system_time_stamp": int(start_ts or 0),
            "start_utc": self._utc_now_iso(),
            "start_perf_counter": time.perf_counter(),
        }

    def _eye_window_end(self, label: str, *, status: str) -> None:
        """Mark end of an eye capture window and record its timing."""
        start_info = self._active_eye_window_starts.pop(label, None)
        if not isinstance(start_info, dict):
            return

        tracker_available = bool(start_info.get("tracker_available", False))
        end_ts = self._latest_tracker_timestamp() if tracker_available else None

        start_ts = int(start_info.get("start_system_time_stamp", 0) or 0)
        end_ts_int = int(end_ts or 0)
        has_tracker_timestamps = start_ts > 0 and end_ts_int > start_ts
        start_perf = float(start_info.get("start_perf_counter", 0.0) or 0.0)
        elapsed_s = round(max(0.0, time.perf_counter() - start_perf), 3) if start_perf > 0 else None

        window = dict(start_info)
        window["status"] = status
        window["end_system_time_stamp"] = end_ts_int
        window["end_utc"] = self._utc_now_iso()
        window["elapsed_s"] = elapsed_s
        window["has_tracker_timestamps"] = has_tracker_timestamps
        window.pop("start_perf_counter", None)
        self._eye_capture_windows.append(window)

    def _finalize_eye_capture_windows(self) -> None:
        """Process eye capture windows: match with tracked eye data, close any unclosed."""
        if self._active_eye_window_starts:
            for label in list(self._active_eye_window_starts.keys()):
                self._eye_window_end(label, status="quit")

        if not self._eye_capture_windows:
            self._log_event(
                "eye_capture_windows_finalized",
                {
                    "n_windows": 0,
                    "n_windows_with_tracker_timestamps": 0,
                    "tracker_connected": bool(self._session_eyetracker is not None),
                },
            )
            return

        counts_by_condition: dict[str, int] = {}
        ts_counts_by_condition: dict[str, int] = {}
        windows_with_timestamps: list[dict[str, object]] = []
        for window in self._eye_capture_windows:
            cond = str(window.get("condition", ""))
            counts_by_condition[cond] = counts_by_condition.get(cond, 0) + 1
            if bool(window.get("has_tracker_timestamps", False)):
                ts_counts_by_condition[cond] = ts_counts_by_condition.get(cond, 0) + 1
                windows_with_timestamps.append(window)

        self._log_event(
            "eye_capture_windows_finalized",
            {
                "n_windows": len(self._eye_capture_windows),
                "n_windows_with_tracker_timestamps": len(windows_with_timestamps),
                "by_condition": counts_by_condition,
                "with_tracker_timestamps_by_condition": ts_counts_by_condition,
                "tracker_connected": bool(self._session_eyetracker is not None),
            },
        )

        tracker = self._session_eyetracker
        if tracker is None or not windows_with_timestamps:
            return

        summaries = tracker.summarize_eye_movement_windows(
            windows_with_timestamps,
            velocity_threshold_ndc_per_s=EYE_EVENT_VELOCITY_THRESHOLD_NDC_PER_S,
            min_fixation_ms=EYE_EVENT_MIN_FIXATION_MS,
            min_saccade_ms=EYE_EVENT_MIN_SACCADE_MS,
            max_saccade_ms=EYE_EVENT_MAX_SACCADE_MS,
            min_blink_ms=EYE_EVENT_MIN_BLINK_MS,
            max_inter_sample_gap_s=EYE_EVENT_MAX_INTER_SAMPLE_GAP_S,
        )
        if summaries:
            self.attach_eye_movement_window_summaries(summaries)

    def _write_eye_windows_csv(self) -> None:
        """Write eye capture windows to CSV (timestamps and linkage to segments)."""
        if self.eye_windows_log_path is None:
            return

        fieldnames = [
            "participant_id",
            "participant_number",
            "session_id",
            "label",
            "section",
            "section_index",
            "phase",
            "step",
            "condition",
            "trial_index",
            "trial_file",
            "status",
            "tracker_available",
            "has_tracker_timestamps",
            "start_system_time_stamp",
            "end_system_time_stamp",
            "start_utc",
            "end_utc",
            "elapsed_s",
        ]

        rows: list[dict[str, object]] = []
        for window in self._eye_capture_windows:
            if not isinstance(window, dict):
                continue
            rows.append(
                {
                    "participant_id": self.participant_id,
                    "participant_number": self.participant_number,
                    "session_id": self.session_id,
                    "label": str(window.get("label", "window")),
                    "section": str(window.get("section", "")),
                    "section_index": int(window.get("section_index", 0) or 0),
                    "phase": str(window.get("phase", "")),
                    "step": str(window.get("step", "")),
                    "condition": str(window.get("condition", "")),
                    "trial_index": int(window.get("trial_index", 0) or 0),
                    "trial_file": str(window.get("trial_file", "")),
                    "status": str(window.get("status", "")),
                    "tracker_available": bool(window.get("tracker_available", False)),
                    "has_tracker_timestamps": bool(window.get("has_tracker_timestamps", False)),
                    "start_system_time_stamp": int(window.get("start_system_time_stamp", 0) or 0),
                    "end_system_time_stamp": int(window.get("end_system_time_stamp", 0) or 0),
                    "start_utc": str(window.get("start_utc", "")),
                    "end_utc": str(window.get("end_utc", "")),
                    "elapsed_s": self._safe_float(window.get("elapsed_s")),
                }
            )

        try:
            with self.eye_windows_log_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                if rows:
                    writer.writerows(rows)
        except OSError as e:
            self._log_fallback_active = True
            self._log_fallback_reason = f"eye windows write failed: {e}"

    def _set_outcome(self, key: str, value: object, *, status: str = "logged", source: str = "participant_test") -> None:
        """Record an outcome metric (e.g., reading time, MCQ accuracy, d-prime)."""
        self._session_logger.set_outcome(key, value, status=status, source=source)
        self.outcomes = self._session_logger.outcomes

    def _safe_float(self, value: object) -> float | None:
        """Safely convert value to float, returning None if conversion fails."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _outcome_value(self, key: str) -> object:
        """Retrieve the recorded value for an outcome key."""
        return self.outcomes.get(key, {}).get("value")

    def _write_outcomes_flat_csv(self) -> None:
        """Write all outcomes as single CSV row (one outcome per column)."""
        if self.outcomes_flat_log_path is None:
            return

        reading_acc = self._outcome_value("reading_comprehension_accuracy_pct")
        reading_time = self._outcome_value("reading_time_sec")
        detect_acc = self._outcome_value("detectability_identification_accuracy_true_false")
        detect_rt = self._outcome_value("detectability_response_time_ms")
        detect_dprime = self._outcome_value("detectability_collapsed_binary_dprime_hautus")
        nasa = self._outcome_value("nasa_tlx_overall_workload")
        eye_strain = self._outcome_value("eye_strain_symptom_total")

        blink_total = int(sum(int(r.get("blinks_count", 0) or 0) for r in self._eye_movement_window_summaries))
        saccade_total = int(sum(int(r.get("saccades_count", 0) or 0) for r in self._eye_movement_window_summaries))
        saccade_duration_total = round(
            sum(float(r.get("saccades_total_duration_ms", 0.0) or 0.0) for r in self._eye_movement_window_summaries),
            3,
        )
        fixation_total = int(sum(int(r.get("fixations_count", 0) or 0) for r in self._eye_movement_window_summaries))
        fixation_duration_total = round(
            sum(float(r.get("fixations_total_duration_ms", 0.0) or 0.0) for r in self._eye_movement_window_summaries),
            3,
        )

        row = {
            "participant_id": self.participant_id,
            "participant_number": self.participant_number,
            "session_id": self.session_id,
            "session_started_utc": self.session_started_utc,
            "session_completed_utc": self._utc_now_iso(),
            "session_status": "quit" if self.quit_requested else "ok",
            "reading_comprehension_accuracy_pct": (
                reading_acc.get("overall_mean_pct") if isinstance(reading_acc, dict) else self._safe_float(reading_acc)
            ),
            "reading_time_sec": (
                reading_time.get("overall_mean_sec") if isinstance(reading_time, dict) else self._safe_float(reading_time)
            ),
            "detectability_identification_accuracy_true_false": (
                detect_acc.get("accuracy_pct") if isinstance(detect_acc, dict) else self._safe_float(detect_acc)
            ),
            "detectability_response_time_ms": (
                detect_rt.get("mean_rt_ms") if isinstance(detect_rt, dict) else self._safe_float(detect_rt)
            ),
            "detectability_dprime_none": (
                detect_dprime.get("none") if isinstance(detect_dprime, dict) else None
            ),
            "detectability_dprime_full": (
                detect_dprime.get("full") if isinstance(detect_dprime, dict) else None
            ),
            "detectability_dprime_eyetracked": (
                detect_dprime.get("eyetracked") if isinstance(detect_dprime, dict) else None
            ),
            "nasa_tlx_overall_workload": self._safe_float(nasa),
            "eye_strain_symptom_total": self._safe_float(eye_strain),
            "blinks_count": blink_total,
            "saccades_count": saccade_total,
            "saccades_duration_ms": saccade_duration_total,
            "fixations_count": fixation_total,
            "fixations_length_ms": fixation_duration_total,
        }

        try:
            with self.outcomes_flat_log_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
                writer.writeheader()
                writer.writerow(row)
        except OSError as e:
            self._log_fallback_active = True
            self._log_fallback_reason = f"outcomes flat write failed: {e}"

    def _write_detectability_trials_csv(self) -> None:
        """Write one row per detectability trial for downstream analysis."""
        if self.detectability_trials_log_path is None:
            return

        fieldnames = [
            "participant_id",
            "participant_number",
            "session_id",
            "phase",
            "is_main_block",
            "trial_index",
            "trial_file",
            "condition",
            "selected_key",
            "selected_condition",
            "is_correct",
            "rt_ms",
        ]

        rows: list[dict[str, object]] = []
        for trial in self._detectability_trial_records:
            if not isinstance(trial, dict):
                continue
            phase = str(trial.get("phase", ""))
            rows.append(
                {
                    "participant_id": self.participant_id,
                    "participant_number": self.participant_number,
                    "session_id": self.session_id,
                    "phase": phase,
                    "is_main_block": phase == "all_blocks" or phase.startswith("block"),
                    "trial_index": int(trial.get("trial_index", 0) or 0),
                    "trial_file": str(trial.get("trial_file", "")),
                    "condition": str(trial.get("condition", "")),
                    "selected_key": int(trial.get("selected_key", 0) or 0),
                    "selected_condition": str(trial.get("selected_condition", "")),
                    "is_correct": bool(trial.get("is_correct", False)),
                    "rt_ms": int(trial.get("rt_ms", 0) or 0),
                }
            )

        try:
            with self.detectability_trials_log_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                if rows:
                    writer.writerows(rows)
        except OSError as e:
            self._log_fallback_active = True
            self._log_fallback_reason = f"detectability trials write failed: {e}"

    def _write_detectability_summary_csv(self) -> None:
        """Write summary rows for detectability by phase and by condition."""
        if self.detectability_summary_log_path is None:
            return

        fieldnames = [
            "participant_id",
            "participant_number",
            "session_id",
            "group_type",
            "group_value",
            "n_trials",
            "n_correct",
            "accuracy_pct",
            "mean_rt_ms",
        ]

        grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
        for trial in self._detectability_trial_records:
            if not isinstance(trial, dict):
                continue
            phase = str(trial.get("phase", ""))
            condition = str(trial.get("condition", ""))
            grouped.setdefault(("phase", phase), []).append(trial)
            grouped.setdefault(("condition", condition), []).append(trial)

        rows: list[dict[str, object]] = []
        for (group_type, group_value), records in sorted(grouped.items()):
            n_trials = len(records)
            n_correct = sum(1 for r in records if bool(r.get("is_correct", False)))
            rt_values = [int(r.get("rt_ms", 0) or 0) for r in records if int(r.get("rt_ms", 0) or 0) > 0]
            rows.append(
                {
                    "participant_id": self.participant_id,
                    "participant_number": self.participant_number,
                    "session_id": self.session_id,
                    "group_type": group_type,
                    "group_value": group_value,
                    "n_trials": n_trials,
                    "n_correct": n_correct,
                    "accuracy_pct": round((100.0 * n_correct / n_trials), 3) if n_trials else None,
                    "mean_rt_ms": round(sum(rt_values) / len(rt_values), 3) if rt_values else None,
                }
            )

        try:
            with self.detectability_summary_log_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                if rows:
                    writer.writerows(rows)
        except OSError as e:
            self._log_fallback_active = True
            self._log_fallback_reason = f"detectability summary write failed: {e}"

    def _write_eye_events_csv(self) -> None:
        """Write eye events from tracker (gaze points, blinks, saccades, fixations)."""
        if self.eye_events_log_path is None:
            return

        fieldnames = [
            "participant_id",
            "participant_number",
            "session_id",
            "window_label",
            "section",
            "section_index",
            "phase",
            "step",
            "condition",
            "trial_index",
            "trial_file",
            "event_type",
            "event_index_in_window",
            "start_system_time_stamp",
            "end_system_time_stamp",
            "duration_ms",
            "centroid_x",
            "centroid_y",
            "amplitude_ndc",
            "peak_velocity_ndc_per_s",
            "mean_velocity_ndc_per_s",
            "source_window_start_system_time_stamp",
            "source_window_end_system_time_stamp",
        ]

        rows: list[dict[str, object]] = []
        for window in self._eye_movement_window_summaries:
            events = window.get("events", {})
            if not isinstance(events, dict):
                continue

            section = str(window.get("section", ""))
            phase = str(window.get("phase", ""))
            step = str(window.get("step", ""))
            condition = str(window.get("condition", ""))
            trial_file = str(window.get("trial_file", ""))
            label = str(window.get("label", "window"))
            section_index = int(window.get("section_index", 0) or 0)
            trial_index = int(window.get("trial_index", 0) or 0)
            source_start = int(window.get("start_system_time_stamp", 0) or 0)
            source_end = int(window.get("end_system_time_stamp", 0) or 0)

            for event_type in ["blinks", "saccades", "fixations"]:
                bucket = events.get(event_type, [])
                if not isinstance(bucket, list):
                    continue
                for idx, event in enumerate(bucket, start=1):
                    if not isinstance(event, dict):
                        continue
                    rows.append(
                        {
                            "participant_id": self.participant_id,
                            "participant_number": self.participant_number,
                            "session_id": self.session_id,
                            "window_label": label,
                            "section": section,
                            "section_index": section_index,
                            "phase": phase,
                            "step": step,
                            "condition": condition,
                            "trial_index": trial_index,
                            "trial_file": trial_file,
                            "event_type": event_type[:-1],
                            "event_index_in_window": idx,
                            "start_system_time_stamp": int(event.get("start_system_time_stamp", 0) or 0),
                            "end_system_time_stamp": int(event.get("end_system_time_stamp", 0) or 0),
                            "duration_ms": self._safe_float(event.get("duration_ms")),
                            "centroid_x": self._safe_float(event.get("centroid_x")),
                            "centroid_y": self._safe_float(event.get("centroid_y")),
                            "amplitude_ndc": self._safe_float(event.get("amplitude_ndc")),
                            "peak_velocity_ndc_per_s": self._safe_float(event.get("peak_velocity_ndc_per_s")),
                            "mean_velocity_ndc_per_s": self._safe_float(event.get("mean_velocity_ndc_per_s")),
                            "source_window_start_system_time_stamp": source_start,
                            "source_window_end_system_time_stamp": source_end,
                        }
                    )

        try:
            with self.eye_events_log_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                if rows:
                    writer.writerows(rows)
        except OSError as e:
            self._log_fallback_active = True
            self._log_fallback_reason = f"eye events write failed: {e}"

    def _compute_detectability_dprime(self) -> dict[str, float]:
        """Compute d-prime (sensitivity) based on hit/false-alarm rates.
        
                Returns:
                    Dict with keys like 'dprime_full_vs_none', 'dprime_eyetracked_vs_none', etc.
        """
        analyzed_detectability_records = [
            r for r in self._detectability_trial_records
            if str(r.get("phase", "")) == "all_blocks"
            or str(r.get("phase", "")).startswith("block")
        ]
        return self._session_logger.compute_detectability_dprime(
            filter_conditions=FILTER_CONDITIONS,
            detectability_trial_records=analyzed_detectability_records,
        )

    def attach_eye_movement_window_summaries(self, summaries: list[dict[str, object]]) -> None:
        """Attach eye movement analysis summaries (blinks, saccades, fixations) from pipeline."""
        self._session_logger.attach_eye_movement_window_summaries(summaries)
        self._eye_movement_window_summaries = self._session_logger.eye_movement_window_summaries

    def _finalize_eye_movement_outcomes(self) -> None:
        """Extract eye movement metrics from summaries and populate outcomes."""
        self._session_logger.eye_movement_window_summaries = self._eye_movement_window_summaries
        self._session_logger.finalize_eye_movement_outcomes(filter_conditions=FILTER_CONDITIONS)
        self.outcomes = self._session_logger.outcomes

    def _finalize_outcomes(self) -> None:
        """Compute final outcomes: reading comprehension accuracy, detectability d-prime, etc."""
        if self._reading_mcq_summary_by_index:
            accuracy_values = [
                float(v["accuracy_pct"])
                for _, v in sorted(self._reading_mcq_summary_by_index.items())
                if "accuracy_pct" in v
            ]
            if accuracy_values:
                self._set_outcome(
                    "reading_comprehension_accuracy_pct",
                    {
                        "paragraph_level": {
                            str(k): v for k, v in sorted(self._reading_mcq_summary_by_index.items())
                        },
                        "overall_mean_pct": round(sum(accuracy_values) / len(accuracy_values), 3),
                    },
                )

        if self._reading_time_by_index:
            values = [float(v) for _, v in sorted(self._reading_time_by_index.items())]
            self._set_outcome(
                "reading_time_sec",
                {
                    "paragraph_level": {
                        str(k): round(v, 3)
                        for k, v in sorted(self._reading_time_by_index.items())
                    },
                    "overall_mean_sec": round(sum(values) / len(values), 3),
                },
            )

        analyzed_detectability_records = [
            r for r in self._detectability_trial_records
            if str(r.get("phase", "")) == "all_blocks"
            or str(r.get("phase", "")).startswith("block")
        ]

        if analyzed_detectability_records:
            total = len(analyzed_detectability_records)
            correct = sum(1 for r in analyzed_detectability_records if bool(r.get("is_correct")))
            self._set_outcome(
                "detectability_identification_accuracy_true_false",
                {
                    "correct": correct,
                    "total": total,
                    "accuracy_pct": round((100.0 * correct / total), 3) if total else None,
                    "trial_level": analyzed_detectability_records,
                },
            )

            rt_values = [int(r.get("rt_ms", 0)) for r in analyzed_detectability_records]
            if rt_values:
                self._set_outcome(
                    "detectability_response_time_ms",
                    {
                        "mean_rt_ms": round(sum(rt_values) / len(rt_values), 3),
                        "n": len(rt_values),
                    },
                )

            self._set_outcome(
                "detectability_collapsed_binary_dprime_hautus",
                self._compute_detectability_dprime(),
            )

        self._finalize_eye_movement_outcomes()

    def _finalize_logging(self) -> None:
        """Write all log files: outcomes, eye windows, eye events, manifest.
        
            Called at end of experiment (success or quit) to ensure all data is written.
        """
        if self._logging_finalized:
            return
        self._logging_finalized = True
        self._finalize_eye_capture_windows()
        self._finalize_outcomes()
        self._write_eye_windows_csv()
        self._write_eye_events_csv()
        self._write_outcomes_flat_csv()
        self._write_detectability_trials_csv()
        self._write_detectability_summary_csv()
        self._session_logger.outcomes = self.outcomes
        self._session_logger.finalize(
            quit_requested=self.quit_requested,
            notes={
                "surveyxact": "Questionnaire variables are marked pending_surveyxact until SurveyXact integration is completed.",
                "eye_metrics": "Blink/saccade/fixation variables are marked pending_eyetracker_pipeline until the eye-event extraction stage is connected.",
            },
        )
        self._log_fallback_active = self._session_logger.state.fallback_active
        self._log_fallback_reason = self._session_logger.state.fallback_reason

    # -- core window helpers --------------------------------------------------
    def _request_quit(self, _event: tk.Event | None = None) -> None:
        """Mark quit requested (called via CTRL+SHIFT+Q or window close button)."""
        self.quit_requested = True
        if self._wait_var is not None:
            self._wait_var.set("QUIT")

    def _request_timer_skip(self, _event: tk.Event | None = None) -> None:
        """Mark to skip current timer (called via CTRL+SHIFT+R; used for testing/breaks)."""
        # Queue the skip even if the timer is about to start; this avoids race conditions
        # where Ctrl+Shift+R is pressed just before _timer_wait_active flips to True.
        self._skip_timer_requested = True
    # Also request quit if timer is not active

    def _consume_timer_skip(self) -> bool:
        """Check and consume timer skip flag. Returns True if skip was requested."""
        if self._skip_timer_requested:
            self._skip_timer_requested = False
            return True
        return False

    def _ensure_focus(self) -> None:
        """Bring window to front and request keyboard focus (called before waiting for keys)."""
        self.root.update_idletasks()
        # If blur overlay is active, avoid lifting the Tk window above it.
        # The overlay is click-through and non-focusable, so keyboard focus
        # typically remains on this app without forcing z-order changes.
        blur_active = self.active_blur_process is not None and self.active_blur_process.poll() is None
        if not blur_active:
            self.root.lift()
            self.root.focus_force()

    def _show_frame(self, bg: str) -> tk.Frame:
        """Create/clear current frame with given background color. Returns the frame.
        
            This is called by each screen to get a fresh frame to populate with widgets.
        """
        if self.current_frame is not None:
            self.current_frame.destroy()

        frame = tk.Frame(self.root, bg=bg)
        frame.pack(fill=tk.BOTH, expand=True)
        self.current_frame = frame
        self.root.configure(bg=bg)
        self._ensure_focus()
        return frame

    def _wait_for_keys(self, key_map: dict[str, str]) -> str:
        if self.quit_requested:
            return "QUIT"

        result = tk.StringVar(value="")
        self._wait_var = result
        binding_ids: list[tuple[str, str]] = []

        def _make_handler(value: str):
            def _handler(_event: tk.Event | None = None) -> None:
                result.set(value)
            return _handler

        for key_seq, value in key_map.items():
            bind_id = self.root.bind(key_seq, _make_handler(value), add="+")
            if bind_id is not None:
                binding_ids.append((key_seq, bind_id))

        self._ensure_focus()
        self.root.wait_variable(result)

        for key_seq, bind_id in binding_ids:
            self.root.unbind(key_seq, bind_id)

        self._wait_var = None
        choice = result.get()
        if choice == "QUIT":
            self.quit_requested = True
        return choice

    def _wait_ms(self, duration_s: float) -> bool:
        deadline = time.perf_counter() + max(0.0, duration_s)
        self._ensure_focus()
        self._timer_wait_active = True
        try:
            while time.perf_counter() < deadline:
                if self.quit_requested:
                    return False
                if self._consume_timer_skip():
                    return True
                self.root.update()
                time.sleep(0.01)
            return not self.quit_requested
        finally:
            self._timer_wait_active = False

    # -- blur renderer helpers ------------------------------------------------
    def _start_blur_renderer(self, condition: str) -> None:
        self._stop_blur_renderer()

        if condition == "none":
            self.active_blur_condition = "none"
            self.last_blur_start_ok = True
            self.last_blur_start_msg = "No-blur condition selected"
            return

        script_name = (
            "no-eyetracking-render-loop.py"
            if condition == "full"
            else "eyetracking-render-loop.py"
        )
        render_dir = self.base_dir / "render"
        script_path = render_dir / script_name
        log_path = self.base_dir / "logs" / "detectability_render.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        self.active_blur_log_handle = open(log_path, "a", encoding="utf-8")
        self.active_blur_log_handle.write(
            f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] START condition={condition} script={script_path}\n"
        )
        self.active_blur_log_handle.flush()

        try:
            if not script_path.exists():
                raise FileNotFoundError(f"Renderer script not found: {script_path}")
            self.active_blur_process = subprocess.Popen(
                [sys.executable, "-u", str(script_path)],
                cwd=str(render_dir),
                stdout=self.active_blur_log_handle,
                stderr=self.active_blur_log_handle,
            )
            self.active_blur_condition = condition
            # Renderer startup status is checked later via _check_renderer_status(),
            # after the fixed pre-trial pause has elapsed. This keeps _start_blur_renderer
            # non-blocking so that the pause duration is always constant.
            self.last_blur_start_ok = True
            self.last_blur_start_msg = f"Renderer launched ({condition}), pending status check"
        except Exception as e:
            self.last_blur_start_ok = False
            self.last_blur_start_msg = f"Renderer launch failed for {condition}: {e}"
            self.active_blur_process = None
            self.active_blur_condition = "none"

    def _stop_blur_renderer(self) -> None:
        if self.active_blur_process is None:
            self.active_blur_condition = "none"
            if self.active_blur_log_handle is not None:
                try:
                    self.active_blur_log_handle.close()
                except Exception:
                    pass
                self.active_blur_log_handle = None
            return

        process = self.active_blur_process
        self.active_blur_process = None

        try:
            process.terminate()
            process.wait(timeout=0.8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=0.8)
        except Exception:
            pass
        finally:
            self.active_blur_condition = "none"
            if self.active_blur_log_handle is not None:
                try:
                    self.active_blur_log_handle.write(
                        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] STOP\n"
                    )
                    self.active_blur_log_handle.flush()
                    self.active_blur_log_handle.close()
                except Exception:
                    pass
                self.active_blur_log_handle = None

    def _check_renderer_status(self) -> None:
        """Poll the active renderer process and update last_blur_start_ok.

        Called after the pre-trial pause has elapsed so that even slow-starting
        renderers (e.g. Tobii eyetracking) have had time to initialise.
        """
        if self.active_blur_process is None:
            return
        code = self.active_blur_process.poll()
        if code is None:
            self.last_blur_start_ok = True
            self.last_blur_start_msg = f"Renderer active ({self.active_blur_condition})"
        else:
            self.last_blur_start_ok = False
            self.last_blur_start_msg = (
                f"Renderer exited early for {self.active_blur_condition} (code={code})"
            )

    def _black_transition(
        self,
        *,
        start_condition: str | None = None,
        stop_blur: bool = False,
        duration_s: float = 1.0,
    ) -> bool:
        # Use a black transition frame so renderer startup differences are not visible.
        self._show_frame("black")
        self.root.attributes("-topmost", True)
        if stop_blur:
            self._stop_blur_renderer()
        if start_condition is not None:
            # Non-blocking: renderer subprocess is spawned immediately and the
            # fixed duration_s wait below gives it time to fully initialise.
            self._start_blur_renderer(start_condition)
        ok = self._wait_ms(duration_s)
        # Deferred health-check: by now even the slowest renderer (Tobii) should
        # have finished startup, so the poll result is meaningful.
        if start_condition is not None:
            self._check_renderer_status()
        return ok



    # -- experiment segments --------------------------------------------------
    def run_introduction_segment(self) -> bool:
        return self._dark_info.show(**asdict(INTRO_COPY))

    def run_calibration_segment(self) -> bool:
        """Display calibration instruction screen and wait for experimenter.
        
        Simply informs the participant that eye tracking calibration is required
        and to wait for the experimenter to open the calibration software.
        """
        try:
            # Allow switching to external calibration software (Alt+Tab).
            self.root.attributes("-topmost", False)
        except tk.TclError:
            pass

        try:
            return self._dark_info.show(
                title="Eye Tracker Calibration",
                body=(
                    "The eye tracker needs to be calibrated.\n\n"
                    "Please wait for the experimenter to open\n"
                    "the calibration software.\n\n"
                    "Follow the instructions on the calibration screen.\n\n"
                    "Press the spacebar when calibration is complete."
                ),
            )
        finally:
            # Restore always-on-top for the rest of the experiment flow.
            try:
                self.root.attributes("-topmost", True)
                self._ensure_focus()
            except tk.TclError:
                pass


    def run_reading_comprehension_intro_screen(self) -> bool:
        return self._dark_info.show(**asdict(READING_COMPREHENSION_INTRO_COPY))

    def run_practice_reading_screen(self) -> bool:
        segment = "practice_reading"
        self._segment_start(segment, {"paragraph_file": PRACTICE_PARAGRAPH_FILE})
        started = time.perf_counter()
        ok = self._light_text.show(
            header=(
                "Read the paragraph below carefully.\n"
                "You will answer multiple-choice questions next."
            ),
            body=TRAINING_TEXT,
            footer="Press the spacebar to continue to the questions.",
        )
        elapsed = round(time.perf_counter() - started, 3)
        self._segment_end(segment, status="ok" if ok else "quit", metrics={"reading_time_sec": elapsed})
        return ok

    def _paragraph_text_for_file(self, paragraph_file: str) -> str:
        text = PARAGRAPH_TEXT_MAP.get(paragraph_file, "")
        if text:
            return text
        raise ExperimentContentError(f"Paragraph content missing for {paragraph_file}")

    def _mcq_items_for_paragraph(self, paragraph_file: str) -> list[dict[str, object]]:
        items = MCQ_ITEMS_BY_PARAGRAPH.get(paragraph_file, [])
        if items:
            return items
        raise ExperimentContentError(f"MCQ items missing for paragraph file {paragraph_file}")

    def run_mcq_block(self, items: list[dict[str, object]], *, headline_prefix: str, log_prefix: str) -> bool:
        if not items:
            raise ExperimentContentError(f"No MCQ items found for block '{log_prefix}'")

        answers: list[int] = []
        rt_ms_values: list[int] = []
        segment = f"mcq_{log_prefix}"
        self._segment_start(segment, {"headline_prefix": headline_prefix, "n_items": len(items)})

        for idx, item in enumerate(items, start=1):
            started_at = time.perf_counter()
            choice = self._mcq.show(
                headline=f"{headline_prefix} {idx} of {len(items)}",
                question=str(item["question"]),
                options=[str(option) for option in item["options"]],
                instruction="Select your answer using number keys 1 to 4.",
                n_options=4,
            )
            if choice == "QUIT":
                self._segment_end(segment, status="quit", metrics={"stopped_on_trial": idx})
                return False

            rt_ms = int((time.perf_counter() - started_at) * 1000)
            rt_ms_values.append(rt_ms)
            answers.append(int(choice))
            print(f"[{log_prefix}] q={idx} choice={choice} rt_ms={rt_ms}")
            self._log_event(
                "mcq_trial",
                {
                    "log_prefix": log_prefix,
                    "trial_index": idx,
                    "choice": int(choice),
                    "correct": int(item["correct"]),
                    "is_correct": int(choice) == int(item["correct"]),
                    "rt_ms": rt_ms,
                },
            )

        correct = sum(
            1 for i, selected in enumerate(answers)
            if selected == int(items[i]["correct"])
        )
        mean_rt = int(sum(rt_ms_values) / len(rt_ms_values)) if rt_ms_values else 0
        accuracy_pct = (100.0 * correct / len(items)) if items else 0.0
        self._last_mcq_result = {
            "log_prefix": log_prefix,
            "n_items": len(items),
            "correct": correct,
            "accuracy_pct": round(accuracy_pct, 3),
            "mean_rt_ms": mean_rt,
        }
        self._segment_end(
            segment,
            status="ok",
            metrics={
                "n_items": len(items),
                "correct": correct,
                "accuracy_pct": round(accuracy_pct, 3),
                "mean_rt_ms": mean_rt,
            },
        )
        print(f"[{log_prefix}] complete: {correct}/{len(items)} correct. Mean RT={mean_rt} ms.")
        return True

    def run_training_mcq_block(self) -> bool:
        return self.run_mcq_block(
            MCQ_ITEMS,
            headline_prefix="Practice Question",
            log_prefix="practice-mcq",
        )

    def _comprehension_paragraph_files(self) -> list[str]:
        files = self.session_order.get("comprehension_paragraphs", [])
        if isinstance(files, list):
            return [str(name) for name in files][:3]
        return []

    def _comprehension_filter_order(self) -> list[str]:
        """Return the 3 reading-comprehension filter conditions for this participant."""
        return self._build_latin_filter_order(3, block_offset=0)

    def run_reading_comprehension_paragraph(self, paragraph_index: int) -> bool:
        paragraph_files = self._comprehension_paragraph_files()
        if paragraph_index < 1 or paragraph_index > len(paragraph_files):
            print(f"[reading] missing paragraph index {paragraph_index}")
            return False

        reminder_segment = f"reading_task_reminder_{paragraph_index}"
        self._segment_start(reminder_segment, {"paragraph_index": paragraph_index})
        reminder_ok = self._dark_info.show(**asdict(READING_TASK_REMINDER_COPY))
        self._segment_end(reminder_segment, status="ok" if reminder_ok else "quit")
        if not reminder_ok:
            return False

        paragraph_file = paragraph_files[paragraph_index - 1]
        filter_order = self._comprehension_filter_order()
        condition = filter_order[paragraph_index - 1] if paragraph_index - 1 < len(filter_order) else "none"

        # Reuse the detectability trigger path so renderer startup/timing is identical.
        if not self._black_transition(
            start_condition=condition,
            duration_s=DETECTABILITY_PRE_TRIAL_PAUSE_S,
        ):
            return False

        if condition != "none" and not self.last_blur_start_ok:
            print(f"[reading] WARNING: {self.last_blur_start_msg}")

        segment = f"reading_paragraph_{paragraph_index}"
        self._segment_start(
            segment,
            {
                "paragraph_index": paragraph_index,
                "paragraph_file": paragraph_file,
                "condition": condition,
            },
        )
        started = time.perf_counter()
        try:
            ok = self._light_text.show(
                header=(
                    f"Reading Comprehension Paragraph {paragraph_index}\n"
                    "Read carefully. Multiple-choice questions will follow."
                ),
                body=self._paragraph_text_for_file(paragraph_file),
                footer="Press the spacebar to continue to the questions.",
            )
            elapsed = round(time.perf_counter() - started, 3)
            if ok:
                self._reading_time_by_index[paragraph_index] = elapsed
            self._segment_end(
                segment,
                status="ok" if ok else "quit",
                metrics={
                    "paragraph_file": paragraph_file,
                    "condition": condition,
                    "reading_time_sec": elapsed,
                },
            )
            return ok
        finally:
            # Match detectability shutdown flow: stop blur during a black transition.
            self._black_transition(
                stop_blur=True,
                duration_s=DETECTABILITY_POST_TRIAL_PAUSE_S,
            )

    def run_reading_comprehension_mcq(self, paragraph_index: int) -> bool:
        paragraph_files = self._comprehension_paragraph_files()
        if paragraph_index < 1 or paragraph_index > len(paragraph_files):
            print(f"[reading-mcq] missing paragraph index {paragraph_index}")
            return False

        paragraph_file = paragraph_files[paragraph_index - 1]
        items = self._mcq_items_for_paragraph(paragraph_file)
        ok = self.run_mcq_block(
            items,
            headline_prefix=f"Paragraph {paragraph_index} Question",
            log_prefix=f"reading{paragraph_index}-mcq",
        )
        if ok and self._last_mcq_result is not None:
            self._reading_mcq_summary_by_index[paragraph_index] = {
                "paragraph_file": paragraph_file,
                "n_items": self._last_mcq_result.get("n_items"),
                "correct": self._last_mcq_result.get("correct"),
                "accuracy_pct": self._last_mcq_result.get("accuracy_pct"),
                "mean_rt_ms": self._last_mcq_result.get("mean_rt_ms"),
            }
        return ok

    def run_detectability_ack_screen(self) -> bool:
        return self._dark_info.show(**asdict(DETECTABILITY_ACK_COPY))

    def _build_detectability_trials(self) -> list[tuple[str, str, str]]:
        scheduled = self.session_order.get("combined_trials", [])
        trials: list[tuple[str, str, str]] = []
        for trial_name, snippet, condition in scheduled:
            trials.append((str(trial_name), str(snippet), str(condition)))
        return trials

    def _detectability_trials_for_phase(self, phase: str) -> list[tuple[str, str, str]]:
        trials = self._build_detectability_trials()
        if phase == "practice":
            return trials[:DETECTABILITY_TEST_TRIALS]

        if phase == "all_blocks":
            # Return all 36 main trial blocks (blocks 1-3 combined)
            start = DETECTABILITY_TEST_TRIALS
            end = DETECTABILITY_TEST_TRIALS + (DETECTABILITY_BLOCK_COUNT * DETECTABILITY_BLOCK_TRIALS)
            return trials[start:end]

        if phase.startswith("block"):
            try:
                block_idx = int(phase.replace("block", ""))
            except ValueError:
                return []
            if block_idx < 1 or block_idx > DETECTABILITY_BLOCK_COUNT:
                return []
            start = DETECTABILITY_TEST_TRIALS + (block_idx - 1) * DETECTABILITY_BLOCK_TRIALS
            end = start + DETECTABILITY_BLOCK_TRIALS
            return trials[start:end]

        return []

    def run_detectability_phase(self, *, phase: str, display_label: str) -> bool:
        phase_trials = self._detectability_trials_for_phase(phase)
        if not phase_trials:
            print(f"[detectability] ERROR: no trials for phase={phase}")
            return False

        responses: list[tuple[int, str, int, int]] = []
        segment = f"detectability_{phase}"
        self._segment_start(segment, {"phase": phase, "label": display_label, "n_trials": len(phase_trials)})
        print(f"[detectability] phase={phase} label={display_label} n_trials={len(phase_trials)}")

        for idx, (trial_name, snippet, condition) in enumerate(phase_trials, start=1):
            trial_window_label = f"eye_{phase}_{idx}_{trial_name}"

            # Use the fixed pre-trial pause so every condition has the same
            # visible gap between the previous response and the new stimulus.
            if not self._black_transition(
                start_condition=condition,
                duration_s=DETECTABILITY_PRE_TRIAL_PAUSE_S,
            ):
                self._segment_end(segment, status="quit", metrics={"stopped_on_trial": idx, "stage": "pre_trial"})
                return False

            if condition != "none" and not self.last_blur_start_ok:
                print(f"[detectability] WARNING: {self.last_blur_start_msg}")

            self._eye_window_start(
                trial_window_label,
                payload={
                    "condition": condition,
                    "section": "detectability",
                    "section_index": 1,
                    "phase": phase,
                    "step": "stimulus",
                    "trial_index": idx,
                    "trial_file": trial_name,
                },
            )
            if not self._det_text.show(snippet, idx, len(phase_trials)):
                self._eye_window_end(trial_window_label, status="quit")
                self._black_transition(stop_blur=True)
                self._segment_end(segment, status="quit", metrics={"stopped_on_trial": idx, "stage": "stimulus"})
                return False
            self._eye_window_end(trial_window_label, status="ok")

            # Stop blur while screen is black, but keep this pause short because
            # shutdown is fast and the participant is moving straight to response.
            if not self._black_transition(
                stop_blur=True,
                duration_s=DETECTABILITY_POST_TRIAL_PAUSE_S,
            ):
                self._segment_end(segment, status="quit", metrics={"stopped_on_trial": idx, "stage": "post_trial"})
                return False

            started_at = time.perf_counter()
            choice = self._det_response.show(idx, len(phase_trials))
            if choice == "QUIT":
                self._segment_end(segment, status="quit", metrics={"stopped_on_trial": idx, "stage": "response"})
                return False

            rt_ms = int((time.perf_counter() - started_at) * 1000)
            responses.append((idx, condition, int(choice), rt_ms))
            selected_condition = {1: "none", 2: "full", 3: "eyetracked"}.get(int(choice), "none")
            is_correct = selected_condition == condition
            trial_record = {
                "phase": phase,
                "trial_index": idx,
                "trial_file": trial_name,
                "condition": condition,
                "selected_key": int(choice),
                "selected_condition": selected_condition,
                "is_correct": is_correct,
                "rt_ms": rt_ms,
            }
            self._detectability_trial_records.append(trial_record)
            self._log_event("detectability_trial", trial_record)
            print(
                f"[detectability] phase={phase} trial={idx} "
                f"trial_file={trial_name} condition={condition} choice={choice} rt_ms={rt_ms}"
            )

        correct = 0
        expected = {"none": 1, "full": 2, "eyetracked": 3}
        for _, condition, selected, _ in responses:
            if selected == expected[condition]:
                correct += 1
        mean_rt = int(sum(rt for _, _, _, rt in responses) / len(responses)) if responses else 0
        self._segment_end(
            segment,
            status="ok",
            metrics={
                "phase": phase,
                "label": display_label,
                "n_trials": len(responses),
                "correct": correct,
                "accuracy_pct": round((100.0 * correct / len(responses)), 3) if responses else None,
                "mean_rt_ms": mean_rt,
            },
        )
        print(f"[detectability] {display_label} complete: {correct}/{len(responses)} matched expected. Mean RT={mean_rt} ms.")
        return True

    def run_questionnaire_blank_screen(
        self,
        *,
        step_number: int,
        title: str = "Questionnaire",
        questionnaire_url: str,
        questionnaire_text: str = QUESTIONNAIRE_TEXT,
    ) -> bool:
        segment = f"questionnaire_blank_{step_number}"
        self._segment_start(
            segment,
            {
                "step_number": step_number,
                "source": "survey_link_placeholder",
                "questionnaire_title": title,
                "questionnaire_url": questionnaire_url,
            },
        )

        url_opened = False
        open_error = ""
        try:
            # Turn off always-on-top while participant completes the external survey.
            self.root.attributes("-topmost", False)
            url_opened = bool(webbrowser.open(questionnaire_url, new=2, autoraise=True))
        except Exception as exc:
            open_error = str(exc)

        body = (
            "You are now being redirected to the questionnaire website.\n\n"
            "Complete the questionnaire in your browser.\n"
            "When you are done, return to this window.\n\n"
            "Press the spacebar when you have finished the questionnaire."
        )

        if not url_opened:
            body = (
                "Automatic browser redirect could not be confirmed.\n\n"
                "If you need to stop the experiment, please tell the experimenter.\n"
                "Once the questionnaire is open, complete it and return here.\n\n"
                "Press the spacebar when finished."
            )

        ok = self._dark_info.show(
            title=title,
            body=body,
        )

        # Restore always-on-top to keep task flow focused in the experiment app.
        try:
            self.root.attributes("-topmost", True)
            self._ensure_focus()
        except tk.TclError:
            pass

        self._segment_end(
            segment,
            status="ok" if ok else "quit",
            metrics={
                "step_number": step_number,
                "url": questionnaire_url,
                "url_label": questionnaire_text,
                "url_opened": url_opened,
                "open_error": open_error,
            },
        )
        return ok

    def run_timed_break_screen(self, copy: DarkInfoCopy, duration_s: int) -> bool:
        """Show break screen with countdown timer. Returns False if quit.
        
            Displays remaining time and auto-advances after duration_s seconds
            (or when CTRL+SHIFT+R is pressed).
        """
        return self._timed_break.show(copy, duration_s)

    def run_detectability_transition_screen(self) -> bool:
        """Show transition screen before main detectability blocks. Returns False if quit."""
        return self._dark_info.show(**asdict(DETECTABILITY_TRANSITION_COPY))

    def run_qualitative_questions_screen(self) -> bool:
        """Show prompt for experimenter-administered qualitative questions. Returns False if quit."""
        segment = "qualitative_questions"
        self._segment_start(segment, {"source": "experimenter_notes"})
        ok = self._dark_info.show(**asdict(QUALITATIVE_QUESTIONS_COPY))
        self._segment_end(segment, status="ok" if ok else "quit")
        return ok

    def run_thank_you_screen(self) -> bool:
        """Show final thank you and study purpose debrief. Returns False if quit."""
        return self._dark_info.show(**asdict(THANK_YOU_COPY))

    def run_study_purpose_screen(self) -> bool:
        """Show study purpose explanation. Returns False if quit."""
        return self._dark_info.show(**asdict(STUDY_PURPOSE_COPY))

    def _run_step(self, step_number: int, end_label: str, action: Callable[[], bool]) -> bool:
        """Execute one experiment step and log it. Returns False if quit.
        
            This is the main wrapper for running each task/screen. It:
            - Calls the action function
            - Logs segment start/end with timing
            - Handles eye tracking windows
            - Records outcomes
        """
        """Run one protocol step and emit the standard end-of-flow message on failure."""
        if action():
            return True
        print(f"[flow] ended at step {step_number} ({end_label})")
        return False

    def _make_reading_paragraph_action(self, paragraph_index: int) -> Callable[[], bool]:
        """Return a closure that displays paragraph at given index."""
        return lambda: self.run_reading_comprehension_paragraph(paragraph_index)

    def _make_reading_mcq_action(self, paragraph_index: int) -> Callable[[], bool]:
        """Return a closure that displays MCQs for paragraph at given index."""
        return lambda: self.run_reading_comprehension_mcq(paragraph_index)

    def _make_questionnaire_action(self, *, step_number: int, title: str, questionnaire_url: str) -> Callable[[], bool]:
        """Return a closure that displays questionnaire URL and opens browser."""
        return lambda: self.run_questionnaire_blank_screen(
            step_number=step_number,
            title=title,
            questionnaire_url=questionnaire_url,
        )

    def _make_break_action(self, copy: DarkInfoCopy, *, duration_s: int) -> Callable[[], bool]:
        """Return a closure that displays timed break screen."""
        return lambda: self.run_timed_break_screen(copy, duration_s=duration_s)

    def _make_detectability_phase_action(self, *, phase: str, display_label: str) -> Callable[[], bool]:
        """Return a closure that runs detectability phase (practice or main block)."""
        return lambda: self.run_detectability_phase(phase=phase, display_label=display_label)

    # -- main entry -----------------------------------------------------------

    def run(self) -> int:
        """Execute complete experiment flow in order. Returns exit code (0 on success)."""
        print("[flow] starting participant protocol")

        # Declarative protocol steps keep ordering explicit while avoiding repetitive call boilerplate.
        protocol_steps: list[tuple[int, str, Callable[[], bool]]] = [
            (1, "intro", self.run_introduction_segment),
            (
                2,
                "demographics survey",
                self._make_questionnaire_action(
                    step_number=2,
                    title="Demographics",
                    questionnaire_url=questionnaire_url_demographics,
                ),
            ),
            (3, "reading intro", self.run_reading_comprehension_intro_screen),
            (4, "practice paragraph", self.run_practice_reading_screen),
            (5, "practice MCQs", self.run_training_mcq_block),
            (6, "calibration before reading paragraph 1", self.run_calibration_segment),
            (7, "reading paragraph 1", self._make_reading_paragraph_action(1)),
            (8, "reading paragraph 1 MCQs", self._make_reading_mcq_action(1)),
            (
                9,
                "questionnaire after reading 1",
                self._make_questionnaire_action(
                    step_number=9,
                    title="Questionnaire (After Reading 1)",
                    questionnaire_url=questionnaire_url_full,
                ),
            ),
            (10, "1-minute break", self._make_break_action(ONE_MINUTE_BREAK_COPY, duration_s=60)),
            (11, "calibration before reading paragraph 2", self.run_calibration_segment),
            (12, "reading paragraph 2", self._make_reading_paragraph_action(2)),
            (13, "reading paragraph 2 MCQs", self._make_reading_mcq_action(2)),
            (
                14,
                "questionnaire after reading 2",
                self._make_questionnaire_action(
                    step_number=14,
                    title="Questionnaire (After Reading 2)",
                    questionnaire_url=questionnaire_url_full,
                ),
            ),
            (15, "1-minute break", self._make_break_action(ONE_MINUTE_BREAK_COPY, duration_s=60)),
            (16, "calibration before reading paragraph 3", self.run_calibration_segment),
            (17, "reading paragraph 3", self._make_reading_paragraph_action(3)),
            (18, "reading paragraph 3 MCQs", self._make_reading_mcq_action(3)),
            (
                19,
                "questionnaire after reading 3",
                self._make_questionnaire_action(
                    step_number=19,
                    title="Questionnaire (After Reading 3)",
                    questionnaire_url=questionnaire_url_full,
                ),
            ),
            (20, "3-minute break", self._make_break_action(THREE_MINUTE_BREAK_COPY, duration_s=180)),
            (21, "detectability intro", self.run_detectability_ack_screen),
            (22, "calibration before detectability practice", self.run_calibration_segment),
            (
                23,
                "detectability practice 1-6",
                self._make_detectability_phase_action(
                    phase="practice",
                    display_label="Detectability practice trials 1-6",
                ),
            ),
            (24, "detectability reminder before main trials", self.run_detectability_transition_screen),
            (
                25,
                "detectability main trials 1-36",
                self._make_detectability_phase_action(
                    phase="all_blocks",
                    display_label="Detectability main trial block (1-36)",
                ),
            ),
            (
                26,
                "questionnaire after detectability",
                self._make_questionnaire_action(
                    step_number=26,
                    title="Eye Strain (After Detectability)",
                    questionnaire_url=questionnaire_url_eyes,
                ),
            ),
            (27, "study goals debrief", self.run_study_purpose_screen),
            (28, "thank you", self.run_thank_you_screen),
        ]

        for step_number, end_label, action in protocol_steps:
            if not self._run_step(step_number, end_label, action):
                return 0

        print("[flow] complete: all protocol steps finished")
        self._finalize_logging()
        return 0

    def close(self) -> None:
        """Clean up resources: stop blur renderer, finalize logging, destroy window.
        
                Called from main() to ensure resources are released whether experiment
                completes normally, participant quits, or an error occurs.
        """
        self._finalize_logging()
        self._stop_blur_renderer()
        if self._session_eyetracker is not None:
            try:
                self._session_eyetracker.cleanup()
            except Exception:
                pass
            self._session_eyetracker = None
        self.root.destroy()
# ============================================================================
# MODULE ENTRY POINT
# ============================================================================



def main() -> int:
    """Application entry point: create experiment and run to completion.
    
    Returns:
        Exit code: 0 for normal completion, 1 for error
    """
    app: ParticipantExperiment | None = None
    try:
        app = ParticipantExperiment()
        return app.run()
    except ExperimentContentError as exc:
        print(f"[fatal] {exc}")
        return 1
    finally:
        if app is not None:
            app.close()


if __name__ == "__main__":
        # Start the application
    raise SystemExit(main())



