"""Participant-facing experiment flow entry point.

This version uses a single fullscreen window and frame-based transitions to:
- Keep keyboard focus stable across all segments
- Remove visible close/open stutter between screens
- Support the full 26-step protocol (intro, calibration, practice, detectability,
  reading-comprehension blocks, timed breaks, questionnaires, and final debrief)

Screen class hierarchy
----------------------
BaseScreen          — shared root/helper access, panel construction
  DarkInfoScreen    — dark background, title + body, SPACE to continue
  LightTextScreen   — light background, scrollable long-form reading text
  MCQScreen         — light background, single multiple-choice question
  DetectabilityTextScreen     — light background, auto-advances after N seconds
  DetectabilityResponseScreen — light background, asks which blur was perceived
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import permutations
import json
import random
from statistics import NormalDist
import subprocess
import sys
import textwrap
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path


# ---------------------------------------------------------------------------
# Experiment content
# ---------------------------------------------------------------------------

def _load_utf8_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").lstrip("\ufeff").strip()
    except OSError:
        return ""


def _load_mcq_items_from_txt(path: Path) -> list[dict[str, object]]:
    """Parse MCQ blocks from a .txt file.

    Expected block format:
    Q: question text
    1: option one
    2: option two
    3: option three
    4: option four
    A: <1-4>

    Blocks are separated by one or more blank lines.
    """
    raw = _load_utf8_text(path)
    if not raw:
        return []

    items: list[dict[str, object]] = []
    for chunk in [c.strip() for c in raw.split("\n\n") if c.strip()]:
        question = ""
        options: dict[int, str] = {}
        answer = 0

        for line in [ln.strip() for ln in chunk.splitlines() if ln.strip()]:
            if line.startswith("Q:"):
                question = line[2:].strip()
            elif len(line) >= 2 and line[0] in "1234" and line[1] == ":":
                options[int(line[0])] = line[2:].strip()
            elif line.startswith("A:"):
                try:
                    answer = int(line[2:].strip())
                except ValueError:
                    answer = 0

        if question and len(options) == 4 and answer in {1, 2, 3, 4}:
            items.append(
                {
                    "question": question,
                    "options": [options[1], options[2], options[3], options[4]],
                    "correct": answer,
                }
            )

    return items


def _load_detectability_texts_from_dir(dir_path: Path) -> list[str]:
    texts: list[str] = []
    try:
        for path in sorted(dir_path.glob("*.txt")):
            content = _load_utf8_text(path)
            if content:
                texts.append(content)
    except OSError:
        return []
    return texts


def _load_detectability_trial_map_from_dir(dir_path: Path) -> dict[str, str]:
    trials: dict[str, str] = {}
    try:
        for path in sorted(dir_path.glob("trial_*.txt")):
            content = _load_utf8_text(path)
            if content:
                trials[path.name] = content
        if trials:
            return trials

        # Fallback to any .txt if trial_* naming is unavailable.
        for path in sorted(dir_path.glob("*.txt")):
            content = _load_utf8_text(path)
            if content:
                trials[path.name] = content
    except OSError:
        return {}
    return trials


def _load_paragraph_text_map_from_dir(dir_path: Path) -> dict[str, str]:
    paragraphs: dict[str, str] = {}
    try:
        for path in sorted(dir_path.glob("*.txt")):
            content = _load_utf8_text(path)
            if content:
                paragraphs[path.name] = content
    except OSError:
        return {}
    return paragraphs


def _load_mcq_map_for_paragraphs(
    paragraph_files: list[str],
    mcq_dir: Path,
) -> dict[str, list[dict[str, object]]]:
    mcq_map: dict[str, list[dict[str, object]]] = {}
    for paragraph_file in paragraph_files:
        qa_file = f"{Path(paragraph_file).stem}QA.txt"
        items = _load_mcq_items_from_txt(mcq_dir / qa_file)
        if items:
            mcq_map[paragraph_file] = items
    return mcq_map


BASE_DIR = Path(__file__).resolve().parent
PARAGRAPH_TEXT_DIR = BASE_DIR / "texts" / "paragraphs"
MCQ_TEXT_DIR = BASE_DIR / "texts" / "MCQ_and_answers"
DETECTABILITY_TEXT_DIR = BASE_DIR / "texts" / "detectibilityText"
PRACTICE_PARAGRAPH_FILE = "generations.txt"

PARAGRAPH_TEXT_MAP = _load_paragraph_text_map_from_dir(PARAGRAPH_TEXT_DIR)
MCQ_ITEMS_BY_PARAGRAPH = _load_mcq_map_for_paragraphs(list(PARAGRAPH_TEXT_MAP.keys()), MCQ_TEXT_DIR)
TRAINING_TEXT = PARAGRAPH_TEXT_MAP.get(PRACTICE_PARAGRAPH_FILE, "")
MCQ_ITEMS = MCQ_ITEMS_BY_PARAGRAPH.get(PRACTICE_PARAGRAPH_FILE, [])

if not TRAINING_TEXT:
    TRAINING_TEXT = "Practice paragraph missing: texts/paragraphs/generations.txt"

if not MCQ_ITEMS:
    MCQ_ITEMS = [
        {
            "question": "According to the passage, how long is one generation approximately?",
            "options": ["12 years", "22 years", "35 years", "50 years"],
            "correct": 2,
        },
        {
            "question": "How many generations are typically alive at the same time?",
            "options": ["2", "3", "4", "5"],
            "correct": 3,
        },
        {
            "question": "Which set lists the four archetypes named by Strauss and Howe?",
            "options": [
                "Idealist, Reactive, Civic, Adaptive",
                "Traditionalist, Rebel, Hero, Nomad",
                "Optimist, Realist, Pragmatist, Visionary",
                "Founder, Builder, Keeper, Reformer",
            ],
            "correct": 1,
        },
    ]


DETECTABILITY_TRIAL_MAP = _load_detectability_trial_map_from_dir(DETECTABILITY_TEXT_DIR)
DETECTABILITY_TEXTS = list(DETECTABILITY_TRIAL_MAP.values())

if not DETECTABILITY_TEXTS:  # fallback if cannot read from directory
    print(f"WARNING: No detectability texts found in {DETECTABILITY_TEXT_DIR}. Using hardcoded defaults.")
    DETECTABILITY_TEXTS = [
        "Morning sunlight stretched across the library tables as students settled into quiet reading.",
        "The cyclist paused at the crossing and checked both lanes before moving forward.",
        "A soft wind moved the leaves while the fountain continued its steady rhythm.",
        "She highlighted two sentences in her notes and rewrote the key idea in the margin.",
        "The train arrived exactly on time, and the platform cleared within a minute.",
        "Clouds gathered over the harbor, but the water remained almost completely still.",
        "He organized the tools by size, then tested each one before closing the case.",
        "The presenter spoke clearly, and the audience followed along without interruption.",
        "After dinner, they reviewed tomorrow's plan and set alarms for an early start.",
    ]
    DETECTABILITY_TRIAL_MAP = {
        f"trial_{idx:02d}.txt": snippet for idx, snippet in enumerate(DETECTABILITY_TEXTS, start=1)
    }


CONDITION_LABELS = {
    "none": "No blur",
    "full": "Full blur",
    "eyetracked": "Eyetracked blur",
}

READING_WRAP_WIDTH = 88
QUESTION_WRAP_WIDTH = 88
OPTION_WRAP_WIDTH = 84
SNIPPET_WRAP_WIDTH = 88

DETECTABILITY_TEST_TRIALS = 6
DETECTABILITY_BLOCK_TRIALS = 12
DETECTABILITY_BLOCK_COUNT = 3
DETECTABILITY_TOTAL_TRIALS = DETECTABILITY_TEST_TRIALS + (DETECTABILITY_BLOCK_TRIALS * DETECTABILITY_BLOCK_COUNT)
# Fixed black-screen duration shown before every detectability stimulus.
# Must be >= worst-case renderer startup time (Tobii eyetracking ~3 s)
# so the pre-trial gap is always identical regardless of blur condition.
DETECTABILITY_PRE_TRIAL_PAUSE_S = 4.0
DETECTABILITY_POST_TRIAL_PAUSE_S = 0.2
FILTER_CONDITIONS = ["none", "full", "eyetracked"]
LATIN_FILTER_ORDERS = [list(p) for p in permutations(FILTER_CONDITIONS)]

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
]


@dataclass(frozen=True)
class DarkInfoCopy:
    title: str
    body: str


@dataclass(frozen=True)
class CalibrationCopy:
    title: str
    body: str


INTRO_COPY = DarkInfoCopy(
    title="Welcome",
    body=(
        "This experiment is about eye-tracked chromatic filtering.\n\n"
        "Press SPACE to continue.\n\n\n"
        "Press CTRL+SHIFT+Q to quit."
    ),
)

READING_COMPREHENSION_INTRO_COPY = DarkInfoCopy(
    title="Reading Comprehension",
    body=(
        "You will now complete a short reading-comprehension practice paragraph and MCQs.\n"
        "Later in the experiment you will read 3 additional paragraphs with MCQs.\n\n"
        "Press SPACE to continue.\n\n\n"
        "Press CTRL+SHIFT+Q to quit."
    ),
)

DETECTABILITY_ACK_COPY = DarkInfoCopy(
    title="Detectability",
    body=(
        "You will read short text snippets with different blur conditions.\n"
        "Each snippet is shown for 3 seconds.\n"
        "Afterward, you will answer what blur type you think was shown.\n\n"
        "You will start with detectability trials 1-6, then complete 3 blocks of 12 trials.\n\n"
        "1 = No blur\n"
        "2 = Full blur\n"
        "3 = Eyetracked blur\n\n\n\n\n\n"
        "Press SPACE to begin. Press CTRL+SHIFT+Q to quit."
    ),
)

ONE_MINUTE_BREAK_COPY = DarkInfoCopy(
    title="Break",
    body=(
        "You now have a 1 minute break.\n"
        "Ask any questions to the experimenter now; notes can be taken qualitatively.\n\n"
        "The timer will run automatically."
    ),
)

THREE_MINUTE_BREAK_COPY = DarkInfoCopy(
    title="Eye Rest Break",
    body=(
        "Please rest your eyes for 3 minutes.\n"
        "Try to look away from the monitor during the break.\n\n"
        "The timer will run automatically."
    ),
)

DETECTABILITY_TRANSITION_COPY = DarkInfoCopy(
    title="Detectability Trials",
    body=(
        "You will now continue to the detectability trials.\n\n"
        "A short text snippet will be displayed for 3 seconds.\n"
        "Please read the text and determine which filter is active.\n\n"
        "1 = No blur\n"
        "2 = Full blur\n"
        "3 = Eyetracked blur\n\n"
        "Press SPACE to begin. Press CTRL+SHIFT+Q to quit."
    ),
)

QUALITATIVE_QUESTIONS_COPY = DarkInfoCopy(
    title="Qualitative Questions",
    body=(
        "Please answer the qualitative questions from the experimenter.\n"
        "You can describe difficulty, comfort, and any blur-related observations.\n\n"
        "Press SPACE when finished.\n\n"
        "Press CTRL+SHIFT+Q to quit."
    ),
)

THANK_YOU_COPY = DarkInfoCopy(
    title="Thank You",
    body=(
        "Thank you for participating.\n\n"
        "Press SPACE to continue."
    ),
)

STUDY_PURPOSE_COPY = DarkInfoCopy(
    title="What We Are Studying",
    body=(
        "This study investigates eye-tracked chromatic filtering and how it influences\n"
        "reading comprehension and blur detectability during text-based tasks.\n\n"
        "Press SPACE to finish."
    ),
)

CALIBRATION_COPY = CalibrationCopy(
    title="Calibration",
    body=(
        "Calibration will now be performed by the experimenter using the Tobii Pro Fusion eye tracker.\n\n"
        "Please sit comfortably and follow the experimenter's instructions.\n\n"
        "Ask the experimenter to start calibration in the Tobii Eye Tracking Manager.\n\n"
        "Press SPACE when the experimenter tells you that calibration is complete.\n\n"
        "Press CTRL+SHIFT+Q to quit at any time."
    ),
)


# ---------------------------------------------------------------------------
# Screen classes
# ---------------------------------------------------------------------------
class BaseScreen:
    """Shared access to the root window and experiment helper methods.

    Subclasses receive the experiment instance so they can call
    _wait_for_keys, _wait_ms, _show_frame, and _ensure_focus without
    duplicating logic.
    """

    def __init__(self, experiment: "ParticipantExperiment") -> None:
        self._exp = experiment
        self.root = experiment.root

    # -- panel builders -------------------------------------------------------

    def _build_dark_panel(self, relwidth: float = 0.68, relheight: float = 0.62) -> tk.Frame:
        container = self._exp._show_frame("#0B0F14")
        panel = tk.Frame(
            container,
            bg="#0B0F14",
            highlightbackground="#39424E",
            highlightthickness=2,
            bd=0,
        )
        panel.place(relx=0.5, rely=0.5, anchor="center", relwidth=relwidth, relheight=relheight)
        return panel

    def _build_light_panel(self, relwidth: float = 0.56, relheight: float = 0.62) -> tk.Frame:
        container = self._exp._show_frame("#FAFAFA")
        panel = tk.Frame(
            container,
            bg="#FAFAFA",
            highlightbackground="#9C9C9C",
            highlightthickness=2,
            bd=0,
        )
        panel.place(relx=0.5, rely=0.5, anchor="center", relwidth=relwidth, relheight=relheight)
        return panel

    def _add_section_banner(self, panel: tk.Frame, text: str) -> None:
        tk.Label(
            panel,
            text=text,
            fg="#0A3558",
            bg="#DDEFFC",
            font=("Verdana", 12, "bold"),
            justify=tk.LEFT,
            anchor="w",
            padx=14,
            pady=8,
        ).pack(fill=tk.X, padx=24, pady=(24, 18))


class DarkInfoScreen(BaseScreen):
    """Light-themed info slide with title/body and a section banner.

    Waits for SPACE before returning.  Returns True if the participant
    pressed SPACE, False if they quit.

    Used for: introduction, practice acknowledgement, detectability
    acknowledgement, and (indirectly) the calibration screen base.
    """

    def show(self, title: str, body: str,
             relwidth: float = 0.68, relheight: float = 0.62) -> bool:
        panel = self._build_light_panel(relwidth=relwidth, relheight=relheight)
        self._add_section_banner(panel, "INFORMATION")

        tk.Label(
            panel,
            text=title,
            fg="black",
            bg="#FAFAFA",
            font=("Verdana", 32, "bold"),
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=54, pady=(0, 20))

        tk.Label(
            panel,
            text=body,
            fg="black",
            bg="#FAFAFA",
            font=("Verdana", 18),
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=54, pady=(0, 56))

        return self._exp._wait_for_keys({"<space>": "CONTINUE"}) == "CONTINUE"


class LightTextScreen(BaseScreen):
    """Light-background slide for reading a long-form passage.

    Renders the text with 1.5× line spacing and waits for SPACE.
    Returns True on SPACE, False on quit.

    Used for: practice reading passage.
    """

    def show(self, header: str, body: str, footer: str,
             relwidth: float = 0.62, relheight: float = 0.80) -> bool:
        panel = self._build_light_panel(relwidth=relwidth, relheight=relheight)

        tk.Label(
            panel,
            text=header,
            fg="black",
            bg="#FAFAFA",
            font=("Verdana", 14, "bold"),
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=72, pady=(34, 20))

        text_widget = tk.Text(
            panel,
            wrap=tk.WORD,
            font=("Verdana", 14),
            bg="#FAFAFA",
            fg="black",
            relief=tk.FLAT,
            highlightthickness=0,
            borderwidth=0,
            padx=0,
            pady=0,
        )
        text_widget.pack(fill=tk.BOTH, expand=True, padx=72)
        text_widget.insert("1.0", textwrap.fill(body, width=READING_WRAP_WIDTH))
        text_widget.tag_add("body", "1.0", "end")
        body_font = tkfont.Font(font=("Verdana", 14))
        line_px = max(1, int(body_font.metrics("linespace")))
        # 1.5 line spacing via internal leading.
        text_widget.tag_configure(
            "body",
            justify="left",
            lmargin1=0,
            lmargin2=0,
            spacing1=0,
            spacing2=int(line_px * 0.5),
            spacing3=0,
        )
        text_widget.config(state=tk.DISABLED)

        tk.Label(
            panel,
            text=footer,
            fg="black",
            bg="#FAFAFA",
            font=("Verdana", 12),
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=72, pady=(20, 34))

        return self._exp._wait_for_keys({"<space>": "CONTINUE"}) == "CONTINUE"


class MCQScreen(BaseScreen):
    """Light-background slide for a single multiple-choice question.

    Displays up to 4 numbered options and waits for a key press in 1-4.
    Returns the selected option number as a string (e.g. "2"), or "QUIT".

    Used for: practice MCQ block, one instance per question.
    """

    def show(self, headline: str, question: str,
             options: list[str], instruction: str,
             n_options: int = 4) -> str:
        panel = self._build_light_panel(relwidth=0.72, relheight=0.74)

        tk.Label(
            panel,
            text=headline,
            fg="black",
            bg="#FAFAFA",
            font=("Verdana", 16, "bold"),
            anchor="w",
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=64, pady=(34, 20))

        tk.Label(
            panel,
            text=textwrap.fill(question, width=QUESTION_WRAP_WIDTH),
            fg="black",
            bg="#FAFAFA",
            font=("Verdana", 14),
            anchor="w",
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=64, pady=(0, 24))

        options_row = tk.Frame(panel, bg="#FAFAFA")
        options_row.pack(fill=tk.X, padx=64, pady=(0, 20))

        shown_options = options[:n_options]
        for col in range(n_options):
            options_row.grid_columnconfigure(col, weight=1, uniform="mcq_col")

        for opt_idx, opt_text in enumerate(shown_options, start=1):
            option_card = tk.Frame(
                options_row,
                bg="#FAFAFA",
                highlightbackground="#B7D9F2",
                highlightthickness=2,
                bd=0,
            )
            option_card.grid(row=0, column=opt_idx - 1, sticky="nsew", padx=8)

            tk.Label(
                option_card,
                text=f"[{opt_idx}]",
                fg="#0A3558",
                bg="#DDEFFC",
                font=("Verdana", 18, "bold"),
                padx=14,
                pady=8,
            ).pack(pady=(12, 10))

            tk.Label(
                option_card,
                text=textwrap.fill(opt_text, width=18),
                fg="black",
                bg="#FAFAFA",
                font=("Verdana", 12),
                justify=tk.CENTER,
                anchor="n",
            ).pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 12))

        tk.Label(
            panel,
            text=instruction,
            fg="black",
            bg="#FAFAFA",
            font=("Verdana", 12),
            anchor="w",
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=64, pady=(24, 34))

        key_map = {str(i): str(i) for i in range(1, n_options + 1)}
        return self._exp._wait_for_keys(key_map)


class DetectabilityTextScreen(BaseScreen):
    """Light-background slide that shows a short snippet for a fixed duration.

    The screen advances automatically after ``duration_s`` seconds.
    Returns True if time elapsed normally, False if the participant quit.

    Used for: each detectability trial's stimulus phase.
    """

    def show(self, snippet: str, idx: int, total: int,
             duration_s: float = 5.0) -> bool:
        self.root.attributes("-topmost", False)
        panel = self._build_light_panel(relwidth=0.56, relheight=0.58)

        tk.Label(
            panel,
            text=f"Detectability Trial {idx} of {total}",
            fg="black",
            bg="#FAFAFA",
            font=("Verdana", 16, "bold"),
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=64, pady=(30, 24))

        tk.Label(
            panel,
            text=textwrap.fill(snippet, width=SNIPPET_WRAP_WIDTH),
            fg="black",
            bg="#FAFAFA",
            font=("Verdana", 14),
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=64, pady=(0, 30))

        tk.Label(
            panel,
            text="",
            fg="black",
            bg="#FAFAFA",
            font=("Verdana", 12),
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=64, pady=(0, 30))

        return self._exp._wait_ms(duration_s)


class DetectabilityResponseScreen(BaseScreen):
    """Light-background slide asking which blur condition was perceived.

    Returns the selected key ("1", "2", or "3"), or "QUIT".

    Used for: each detectability trial's response phase.
    """

    def show(self, idx: int, total: int) -> str:
        self.root.attributes("-topmost", True)
        panel = self._build_light_panel(relwidth=0.56, relheight=0.64)

        tk.Label(
            panel,
            text=f"Detectability Response {idx} of {total}",
            fg="black",
            bg="#FAFAFA",
            font=("Verdana", 16, "bold"),
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=64, pady=(30, 12))

        tk.Label(
            panel,
            text="What blur did you perceive in the previous text?",
            fg="black",
            bg="#FAFAFA",
            font=("Verdana", 13),
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=64, pady=(0, 24))

        options_row = tk.Frame(panel, bg="#FAFAFA")
        options_row.pack(fill=tk.X, padx=64, pady=(0, 0))

        for col in range(3):
            options_row.grid_columnconfigure(col, weight=1, uniform="det_col")

        for key, label, sublabel in [
            ("1", "[1]", "No blur"),
            ("2", "[2]", "Full blur"),
            ("3", "[3]", "Eyetracked blur"),
        ]:
            card = tk.Frame(
                options_row,
                bg="#FAFAFA",
                highlightbackground="#B7D9F2",
                highlightthickness=2,
                bd=0,
            )
            card.grid(row=0, column=int(key) - 1, sticky="nsew", padx=8)

            tk.Label(
                card,
                text=label,
                fg="#0A3558",
                bg="#DDEFFC",
                font=("Verdana", 22, "bold"),
                padx=14,
                pady=10,
            ).pack(pady=(16, 8))

            tk.Label(
                card,
                text=sublabel,
                fg="black",
                bg="#FAFAFA",
                font=("Verdana", 13),
                justify=tk.CENTER,
                anchor="n",
            ).pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 16))

        tk.Label(
            panel,
            text="Press CTRL+SHIFT+Q to quit.",
            fg="#888888",
            bg="#FAFAFA",
            font=("Verdana", 10),
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=64, pady=(28, 20))

        return self._exp._wait_for_keys({"1": "1", "2": "2", "3": "3"})


# ---------------------------------------------------------------------------
# Experiment orchestrator
# ---------------------------------------------------------------------------

class ParticipantExperiment:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Eye-tracked Chromatic Filtering Experiment")
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="black")

        self.current_frame: tk.Frame | None = None
        self.quit_requested = False
        self._wait_var: tk.StringVar | None = None
        self.active_blur_condition: str = "none"
        self.active_blur_process: subprocess.Popen | None = None
        self.active_blur_log_handle = None
        self.last_blur_start_ok = False
        self.last_blur_start_msg = ""
        self.base_dir = Path(__file__).resolve().parent
        self.participant_number = self._resolve_participant_number()
        self.latin_variant_index = (self.participant_number - 1) % len(LATIN_FILTER_ORDERS)
        self.session_order: dict[str, object] = self._prepare_session_order()
        self.session_started_utc = self._utc_now_iso()

        self.participant_id = f"P{self.participant_number:03d}"
        self.session_id = "S01"
        self.session_dir: Path | None = None
        self.events_log_path: Path | None = None
        self.segments_log_path: Path | None = None
        self.manifest_log_path: Path | None = None
        self._log_fallback_active = False
        self._log_fallback_reason = ""
        self._in_memory_events: list[dict[str, object]] = []
        self._in_memory_segments: list[dict[str, object]] = []
        self._logging_finalized = False

        self._segment_starts: dict[str, tuple[str, float]] = {}
        self._reading_time_by_index: dict[int, float] = {}
        self._reading_mcq_summary_by_index: dict[int, dict[str, object]] = {}
        self._detectability_trial_records: list[dict[str, object]] = []
        self._last_mcq_result: dict[str, object] | None = None

        self.outcomes: dict[str, dict[str, object]] = {
            key: {"value": None, "status": "pending", "source": "participant_test"}
            for key in OUTCOME_KEYS
        }
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

        self._init_session_logging()

        self.root.protocol("WM_DELETE_WINDOW", self._request_quit)
        self.root.bind("<Control-Shift-Q>", self._request_quit, add="+")

        # Screen instances — one per screen type, reused across segments.
        self._dark_info = DarkInfoScreen(self)
        self._light_text = LightTextScreen(self)
        self._mcq = MCQScreen(self)
        self._det_text = DetectabilityTextScreen(self)
        self._det_response = DetectabilityResponseScreen(self)

    def _resolve_participant_number(self) -> int:
        """Resolve participant number from CLI flag or environment.

        Supported CLI forms:
        - --participant=3
        - --participant 3
        """
        argv = sys.argv[1:]
        for idx, arg in enumerate(argv):
            if arg.startswith("--participant="):
                raw = arg.split("=", 1)[1].strip()
                if raw.isdigit() and int(raw) > 0:
                    return int(raw)
            if arg == "--participant" and idx + 1 < argv:
                raw = argv[idx + 1].strip()
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
        return 1

    def _practice_trial_file_names(self) -> list[str]:
        return [f"trial_{idx:02d}.txt" for idx in range(1, DETECTABILITY_TEST_TRIALS + 1)]

    def _main_trial_file_names(self) -> list[str]:
        start = DETECTABILITY_TEST_TRIALS + 1
        end = DETECTABILITY_TOTAL_TRIALS
        return [f"trial_{idx:02d}.txt" for idx in range(start, end + 1)]

    def _build_paragraph_order(self) -> list[str]:
        paragraphs_dir = self.base_dir / "texts" / "paragraphs"
        files = sorted([p.name for p in paragraphs_dir.glob("*.txt")])
        if not files:
            return [PRACTICE_PARAGRAPH_FILE]

        rng = random.Random(1100 + self.participant_number)
        primary = PRACTICE_PARAGRAPH_FILE
        others = [name for name in files if name != primary]
        rng.shuffle(others)
        if primary in files:
            return [primary] + others
        return others

    def _build_latin_filter_order(self, n_trials: int, *, block_offset: int = 0) -> list[str]:
        base = LATIN_FILTER_ORDERS[self.latin_variant_index][:]
        if block_offset:
            shift = block_offset % len(base)
            base = base[shift:] + base[:shift]

        sequence: list[str] = []
        while len(sequence) < n_trials:
            sequence.extend(base)
        return sequence[:n_trials]

    def _prepare_session_order(self) -> dict[str, object]:
        paragraph_order = self._build_paragraph_order()
        comprehension_paragraphs = [name for name in paragraph_order if name != PRACTICE_PARAGRAPH_FILE][:3]

        if len(comprehension_paragraphs) < 3:
            all_available = sorted(PARAGRAPH_TEXT_MAP.keys())
            fillers = [name for name in all_available if name != PRACTICE_PARAGRAPH_FILE]
            while len(comprehension_paragraphs) < 3 and fillers:
                comprehension_paragraphs.append(fillers[(len(comprehension_paragraphs) - 1) % len(fillers)])

        if len(comprehension_paragraphs) < 3:
            comprehension_paragraphs = comprehension_paragraphs + [PRACTICE_PARAGRAPH_FILE] * (3 - len(comprehension_paragraphs))

        available_trials = set(DETECTABILITY_TRIAL_MAP.keys())
        required_trials = self._practice_trial_file_names() + self._main_trial_file_names()
        missing = [name for name in required_trials if name not in available_trials]
        if missing:
            print(f"WARNING: Missing detectability trial files: {missing}")

        # Fixed trial-ID sets per phase for all participants.
        practice_trial_ids = [name for name in self._practice_trial_file_names() if name in available_trials]

        block_trial_id_sets: list[list[str]] = []
        for block_idx in range(DETECTABILITY_BLOCK_COUNT):
            block_start = DETECTABILITY_TEST_TRIALS + (block_idx * DETECTABILITY_BLOCK_TRIALS) + 1
            block_end = block_start + DETECTABILITY_BLOCK_TRIALS - 1
            block_ids = [
                f"trial_{idx:02d}.txt"
                for idx in range(block_start, block_end + 1)
                if f"trial_{idx:02d}.txt" in available_trials
            ]
            block_trial_id_sets.append(block_ids)

        # Deterministic per-item filter assignment (Latin-square variant by participant).
        practice_filter_assignment = self._build_latin_filter_order(len(practice_trial_ids), block_offset=0)
        block_filter_assignments = [
            self._build_latin_filter_order(len(block_ids), block_offset=block_idx)
            for block_idx, block_ids in enumerate(block_trial_id_sets)
        ]

        practice_trial_to_filter = {
            trial_name: condition
            for trial_name, condition in zip(practice_trial_ids, practice_filter_assignment)
        }

        block_trial_to_filter: list[dict[str, str]] = []
        for block_ids, filter_assignment in zip(block_trial_id_sets, block_filter_assignments):
            block_trial_to_filter.append(
                {
                    trial_name: condition
                    for trial_name, condition in zip(block_ids, filter_assignment)
                }
            )

        # Shuffled display order per participant while preserving per-item assignment.
        practice_trial_files = practice_trial_ids[:]
        practice_rng = random.Random(2100 + self.participant_number)
        practice_rng.shuffle(practice_trial_files)
        practice_filter_order = [practice_trial_to_filter[name] for name in practice_trial_files]

        block_trial_files: list[list[str]] = []
        block_filter_orders: list[list[str]] = []
        for block_idx, block_ids in enumerate(block_trial_id_sets):
            shown_ids = block_ids[:]
            block_rng = random.Random(3100 + self.participant_number + block_idx)
            block_rng.shuffle(shown_ids)
            block_trial_files.append(shown_ids)
            block_filter_orders.append([block_trial_to_filter[block_idx][name] for name in shown_ids])

        combined_trials: list[tuple[str, str, str]] = []
        for trial_name in practice_trial_files:
            text = DETECTABILITY_TRIAL_MAP.get(trial_name, "")
            condition = practice_trial_to_filter.get(trial_name, "none")
            if text:
                combined_trials.append((trial_name, text, condition))

        for block_idx, shown_ids in enumerate(block_trial_files):
            mapping = block_trial_to_filter[block_idx]
            for trial_name in shown_ids:
                text = DETECTABILITY_TRIAL_MAP.get(trial_name, "")
                condition = mapping.get(trial_name, "none")
                if text:
                    combined_trials.append((trial_name, text, condition))

        print(
            "[schedule] participant="
            f"{self.participant_number} latin_variant={self.latin_variant_index + 1}/{len(LATIN_FILTER_ORDERS)}"
        )

        return {
            "participant_number": self.participant_number,
            "latin_variant_index": self.latin_variant_index,
            "paragraph_order": paragraph_order,
            "practice_paragraph": PRACTICE_PARAGRAPH_FILE,
            "comprehension_paragraphs": comprehension_paragraphs,
            "practice_trial_id_set": practice_trial_ids,
            "block_trial_id_sets": block_trial_id_sets,
            "practice_trial_files": practice_trial_files,
            "block_trial_files": block_trial_files,
            "practice_filter_assignment": practice_filter_assignment,
            "block_filter_assignments": block_filter_assignments,
            "practice_filter_order": practice_filter_order,
            "block_filter_orders": block_filter_orders,
            "combined_trials": combined_trials,
        }

    # -- logging helpers ------------------------------------------------------
    def _utc_now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _safe_write_event(self, event: dict[str, object]) -> None:
        self._in_memory_events.append(event)
        if self.events_log_path is None:
            return
        try:
            with self.events_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=True) + "\n")
        except OSError as e:
            self._log_fallback_active = True
            self._log_fallback_reason = f"events write failed: {e}"

    def _safe_write_segment_row(self, row: dict[str, object]) -> None:
        self._in_memory_segments.append(row)
        if self.segments_log_path is None:
            return
        try:
            with self.segments_log_path.open("a", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(
                    [
                        row["segment_name"],
                        row["started_at_utc"],
                        row["ended_at_utc"],
                        row["status"],
                        json.dumps(row["metrics"], ensure_ascii=True),
                    ]
                )
        except OSError as e:
            self._log_fallback_active = True
            self._log_fallback_reason = f"segments write failed: {e}"

    def _write_manifest(self) -> None:
        manifest = {
            "participant": {
                "participant_id": self.participant_id,
                "participant_number": self.participant_number,
                "session_id": self.session_id,
                "date_utc": self.session_started_utc,
            },
            "created_at_utc": self.session_started_utc,
            "updated_at_utc": self._utc_now_iso(),
            "logging": {
                "fallback_active": self._log_fallback_active,
                "fallback_reason": self._log_fallback_reason,
                "events_path": str(self.events_log_path) if self.events_log_path else None,
                "segments_path": str(self.segments_log_path) if self.segments_log_path else None,
            },
            "schedule": {
                "latin_variant_index": self.latin_variant_index,
                "practice_trial_files": self.session_order.get("practice_trial_files", []),
                "block_trial_files": self.session_order.get("block_trial_files", []),
                "paragraph_order": self.session_order.get("paragraph_order", []),
                "comprehension_paragraphs": self.session_order.get("comprehension_paragraphs", []),
            },
            "outcomes": self.outcomes,
            "notes": {
                "surveyxact": "Questionnaire variables are marked pending_surveyxact until SurveyXact integration is completed.",
                "eye_metrics": "Blink/saccade/fixation variables are marked pending_eyetracker_pipeline until the eye-event extraction stage is connected.",
            },
        }

        if self.manifest_log_path is None:
            return
        try:
            self.manifest_log_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
        except OSError as e:
            self._log_fallback_active = True
            self._log_fallback_reason = f"manifest write failed: {e}"

    def _next_session_id(self, participant_dir: Path) -> str:
        existing: list[int] = []
        for child in participant_dir.glob("S*"):
            if child.is_dir() and len(child.name) >= 2 and child.name[1:].isdigit():
                existing.append(int(child.name[1:]))
        return f"S{(max(existing) + 1) if existing else 1:02d}"

    def _init_session_logging(self) -> None:
        logs_root = self.base_dir / "logs"
        preferred_participant_dir = logs_root / self.participant_id

        try:
            preferred_participant_dir.mkdir(parents=True, exist_ok=True)
            self.session_id = self._next_session_id(preferred_participant_dir)
            self.session_dir = preferred_participant_dir / self.session_id
            self.session_dir.mkdir(parents=True, exist_ok=False)
        except OSError as e:
            self._log_fallback_active = True
            self._log_fallback_reason = f"session dir fallback: {e}"
            fallback_dir = logs_root / "_fallback"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self.session_id = f"FALLBACK_{stamp}"
            self.session_dir = fallback_dir

        self.events_log_path = self.session_dir / "events.jsonl"
        self.segments_log_path = self.session_dir / "segments.csv"
        self.manifest_log_path = self.session_dir / "session_manifest.json"

        if not self.segments_log_path.exists():
            try:
                with self.segments_log_path.open("w", encoding="utf-8", newline="") as fh:
                    writer = csv.writer(fh)
                    writer.writerow(["segment_name", "started_at_utc", "ended_at_utc", "status", "metrics_json"])
            except OSError as e:
                self._log_fallback_active = True
                self._log_fallback_reason = f"segments header write failed: {e}"

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
        self._safe_write_event(
            {
                "event_type": event_type,
                "timestamp_utc": self._utc_now_iso(),
                "payload": payload,
            }
        )

    def _segment_start(self, segment_name: str, payload: dict[str, object] | None = None) -> None:
        start_utc = self._utc_now_iso()
        self._segment_starts[segment_name] = (start_utc, time.perf_counter())
        self._log_event(f"{segment_name}_started", payload or {})

    def _segment_end(self, segment_name: str, *, status: str, metrics: dict[str, object] | None = None) -> None:
        start = self._segment_starts.pop(segment_name, None)
        if start is None:
            start_utc = self._utc_now_iso()
            elapsed_s = None
        else:
            start_utc, start_perf = start
            elapsed_s = round(time.perf_counter() - start_perf, 3)

        out_metrics: dict[str, object] = dict(metrics or {})
        if elapsed_s is not None and "elapsed_s" not in out_metrics:
            out_metrics["elapsed_s"] = elapsed_s

        row = {
            "segment_name": segment_name,
            "started_at_utc": start_utc,
            "ended_at_utc": self._utc_now_iso(),
            "status": status,
            "metrics": out_metrics,
        }
        self._safe_write_segment_row(row)
        payload = dict(out_metrics)
        payload["status"] = status
        self._log_event(f"{segment_name}_completed", payload)

    def _set_outcome(self, key: str, value: object, *, status: str = "logged", source: str = "participant_test") -> None:
        self.outcomes[key] = {
            "value": value,
            "status": status,
            "source": source,
        }

    def _compute_detectability_dprime(self) -> dict[str, float]:
        by_condition: dict[str, dict[str, int]] = {
            c: {"hits": 0, "misses": 0, "fa": 0, "cr": 0}
            for c in FILTER_CONDITIONS
        }

        for rec in self._detectability_trial_records:
            true_cond = str(rec.get("condition", "none"))
            selected_cond = str(rec.get("selected_condition", "none"))
            for cond in FILTER_CONDITIONS:
                if true_cond == cond and selected_cond == cond:
                    by_condition[cond]["hits"] += 1
                elif true_cond == cond and selected_cond != cond:
                    by_condition[cond]["misses"] += 1
                elif true_cond != cond and selected_cond == cond:
                    by_condition[cond]["fa"] += 1
                else:
                    by_condition[cond]["cr"] += 1

        normal = NormalDist()
        out: dict[str, float] = {}
        for cond, counts in by_condition.items():
            hits = counts["hits"]
            misses = counts["misses"]
            fa = counts["fa"]
            cr = counts["cr"]
            hit_rate = (hits + 0.5) / (hits + misses + 1.0)
            fa_rate = (fa + 0.5) / (fa + cr + 1.0)
            out[cond] = round(normal.inv_cdf(hit_rate) - normal.inv_cdf(fa_rate), 6)
        return out

    def _finalize_outcomes(self) -> None:
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

        if self._detectability_trial_records:
            total = len(self._detectability_trial_records)
            correct = sum(1 for r in self._detectability_trial_records if bool(r.get("is_correct")))
            self._set_outcome(
                "detectability_identification_accuracy_true_false",
                {
                    "correct": correct,
                    "total": total,
                    "accuracy_pct": round((100.0 * correct / total), 3) if total else None,
                    "trial_level": self._detectability_trial_records,
                },
            )

            rt_values = [int(r.get("rt_ms", 0)) for r in self._detectability_trial_records]
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

    def _finalize_logging(self) -> None:
        if self._logging_finalized:
            return
        self._logging_finalized = True
        self._finalize_outcomes()
        self._log_event(
            "session_completed",
            {
                "status": "quit" if self.quit_requested else "ok",
                "outcome_status_counts": {
                    status: sum(1 for v in self.outcomes.values() if v.get("status") == status)
                    for status in {str(v.get("status")) for v in self.outcomes.values()}
                },
            },
        )
        self._write_manifest()

    # -- core window helpers --------------------------------------------------
    def _request_quit(self, _event: tk.Event | None = None) -> None:
        self.quit_requested = True
        if self._wait_var is not None:
            self._wait_var.set("QUIT")

    def _ensure_focus(self) -> None:
        self.root.update_idletasks()
        self.root.lift()
        self.root.focus_force()

    def _show_frame(self, bg: str) -> tk.Frame:
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
        while time.perf_counter() < deadline:
            if self.quit_requested:
                return False
            self.root.update()
            time.sleep(0.01)
        return not self.quit_requested

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
        log_path = self.base_dir / "logs" / "detectability_render.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        self.active_blur_log_handle = open(log_path, "a", encoding="utf-8")
        self.active_blur_log_handle.write(
            f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] START condition={condition} script={script_name}\n"
        )
        self.active_blur_log_handle.flush()

        try:
            self.active_blur_process = subprocess.Popen(
                [sys.executable, script_name],
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
        """Calibration slide with instructions only.

        Actual eye-tracker calibration is handled externally via
        the Tobii Eye Tracking Manager (Tobii Pro Fusion).
        """
        return self._dark_info.show(
            title=CALIBRATION_COPY.title,
            body=CALIBRATION_COPY.body,
            relwidth=0.68,
            relheight=0.72,
        )

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
            footer="Press SPACE to continue to the questions. Press CTRL+SHIFT+Q to quit.",
        )
        elapsed = round(time.perf_counter() - started, 3)
        self._segment_end(segment, status="ok" if ok else "quit", metrics={"reading_time_sec": elapsed})
        return ok

    def _paragraph_text_for_file(self, paragraph_file: str) -> str:
        text = PARAGRAPH_TEXT_MAP.get(paragraph_file, "")
        if text:
            return text
        return f"Paragraph content missing for {paragraph_file}."

    def _mcq_items_for_paragraph(self, paragraph_file: str) -> list[dict[str, object]]:
        items = MCQ_ITEMS_BY_PARAGRAPH.get(paragraph_file, [])
        if items:
            return items
        if paragraph_file == PRACTICE_PARAGRAPH_FILE:
            return MCQ_ITEMS
        return []

    def run_mcq_block(self, items: list[dict[str, object]], *, headline_prefix: str, log_prefix: str) -> bool:
        if not items:
            print(f"[{log_prefix}] WARNING: No MCQ items found; skipping this MCQ block.")
            self._log_event(
                "mcq_block_skipped",
                {"log_prefix": log_prefix, "reason": "no_items"},
            )
            return True

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
                instruction="Answer using keys 1-4. Press CTRL+SHIFT+Q to quit.",
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

    def run_reading_comprehension_paragraph(self, paragraph_index: int) -> bool:
        paragraph_files = self._comprehension_paragraph_files()
        if paragraph_index < 1 or paragraph_index > len(paragraph_files):
            print(f"[reading] missing paragraph index {paragraph_index}")
            return False

        paragraph_file = paragraph_files[paragraph_index - 1]
        segment = f"reading_paragraph_{paragraph_index}"
        self._segment_start(segment, {"paragraph_index": paragraph_index, "paragraph_file": paragraph_file})
        started = time.perf_counter()
        ok = self._light_text.show(
            header=(
                f"Reading Comprehension Paragraph {paragraph_index}\n"
                "Read carefully. MCQs will follow."
            ),
            body=self._paragraph_text_for_file(paragraph_file),
            footer="Press SPACE to continue to the questions. Press CTRL+SHIFT+Q to quit.",
        )
        elapsed = round(time.perf_counter() - started, 3)
        if ok:
            self._reading_time_by_index[paragraph_index] = elapsed
        self._segment_end(
            segment,
            status="ok" if ok else "quit",
            metrics={"paragraph_file": paragraph_file, "reading_time_sec": elapsed},
        )
        return ok

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

            if not self._det_text.show(snippet, idx, len(phase_trials)):
                self._black_transition(stop_blur=True)
                self._segment_end(segment, status="quit", metrics={"stopped_on_trial": idx, "stage": "stimulus"})
                return False

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

    def run_questionnaire_blank_screen(self, *, step_number: int) -> bool:
        segment = f"questionnaire_blank_{step_number}"
        self._segment_start(segment, {"step_number": step_number, "source": "surveyxact_pending"})
        ok = self._dark_info.show(
            title=f"Questionnaire Slide {step_number}",
            body=(
                "Please complete the questionnaire section now.\n\n"
                "Press SPACE to continue when done.\n\n"
                "Press CTRL+SHIFT+Q to quit."
            ),
        )
        self._segment_end(segment, status="ok" if ok else "quit", metrics={"step_number": step_number})
        return ok

    def run_timed_break_screen(self, copy: DarkInfoCopy, duration_s: int) -> bool:
        panel = self._dark_info._build_light_panel(relwidth=0.68, relheight=0.64)
        self._dark_info._add_section_banner(panel, "BREAK")

        tk.Label(
            panel,
            text=copy.title,
            fg="black",
            bg="#FAFAFA",
            font=("Verdana", 30, "bold"),
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=54, pady=(0, 20))

        tk.Label(
            panel,
            text=copy.body,
            fg="black",
            bg="#FAFAFA",
            font=("Verdana", 16),
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=54, pady=(0, 24))

        timer_label = tk.Label(
            panel,
            text="",
            fg="#0A3558",
            bg="#DDEFFC",
            font=("Verdana", 20, "bold"),
            justify=tk.LEFT,
            anchor="w",
            padx=14,
            pady=10,
        )
        timer_label.pack(fill=tk.X, padx=54, pady=(0, 26))

        for remaining in range(max(1, duration_s), 0, -1):
            if self.quit_requested:
                return False
            timer_label.config(text=f"Time remaining: {remaining} seconds")
            self.root.update()
            time.sleep(1)

        timer_label.config(text="Break complete.")
        tk.Label(
            panel,
            text="Press SPACE to continue.",
            fg="black",
            bg="#FAFAFA",
            font=("Verdana", 14),
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=54, pady=(0, 34))

        return self._wait_for_keys({"<space>": "CONTINUE"}) == "CONTINUE"

    def run_detectability_transition_screen(self) -> bool:
        return self._dark_info.show(**asdict(DETECTABILITY_TRANSITION_COPY))

    def run_qualitative_questions_screen(self) -> bool:
        segment = "qualitative_questions"
        self._segment_start(segment, {"source": "experimenter_notes"})
        ok = self._dark_info.show(**asdict(QUALITATIVE_QUESTIONS_COPY))
        self._segment_end(segment, status="ok" if ok else "quit")
        return ok

    def run_thank_you_screen(self) -> bool:
        return self._dark_info.show(**asdict(THANK_YOU_COPY))

    def run_study_purpose_screen(self) -> bool:
        return self._dark_info.show(**asdict(STUDY_PURPOSE_COPY))

    # -- main entry -----------------------------------------------------------

    def run(self) -> int:
        print("[flow] starting 26-step participant protocol")

        if not self.run_introduction_segment():
            print("[flow] ended at step 1 (intro)")
            return 0

        if not self.run_calibration_segment():
            print("[flow] ended at step 2 (calibration)")
            return 0

        if not self.run_reading_comprehension_intro_screen():
            print("[flow] ended at step 3 (reading intro)")
            return 0

        if not self.run_practice_reading_screen():
            print("[flow] ended at step 4 (practice paragraph)")
            return 0

        if not self.run_training_mcq_block():
            print("[flow] ended at step 5 (practice MCQs)")
            return 0

        if not self.run_detectability_ack_screen():
            print("[flow] ended at step 6 (detectability intro)")
            return 0

        if not self.run_detectability_phase(phase="practice", display_label="Detectability trials 1-6"):
            print("[flow] ended at step 7 (detectability trials 1-6)")
            return 0

        if not self.run_timed_break_screen(ONE_MINUTE_BREAK_COPY, duration_s=60):
            print("[flow] ended at step 8 (1-minute break)")
            return 0

        if not self.run_reading_comprehension_paragraph(1):
            print("[flow] ended at step 9 (reading paragraph 1)")
            return 0

        if not self.run_reading_comprehension_mcq(1):
            print("[flow] ended at step 10 (reading paragraph 1 MCQs)")
            return 0

        if not self.run_detectability_transition_screen():
            print("[flow] ended before step 11 (detectability block 1 transition)")
            return 0

        if not self.run_detectability_phase(phase="block1", display_label="Detectability block 1"):
            print("[flow] ended at step 12 (detectability block 1)")
            return 0

        if not self.run_questionnaire_blank_screen(step_number=12):
            print("[flow] ended at step 13 (questionnaire blank)")
            return 0

        if not self.run_timed_break_screen(THREE_MINUTE_BREAK_COPY, duration_s=180):
            print("[flow] ended at step 14 (3-minute break)")
            return 0

        if not self.run_reading_comprehension_paragraph(2):
            print("[flow] ended at step 15 (reading paragraph 2)")
            return 0

        if not self.run_reading_comprehension_mcq(2):
            print("[flow] ended at step 16 (reading paragraph 2 MCQs)")
            return 0

        if not self.run_detectability_transition_screen():
            print("[flow] ended before step 17 (detectability block 2 transition)")
            return 0

        if not self.run_detectability_phase(phase="block2", display_label="Detectability block 2"):
            print("[flow] ended at step 18 (detectability block 2)")
            return 0

        if not self.run_questionnaire_blank_screen(step_number=17):
            print("[flow] ended at step 19 (questionnaire blank)")
            return 0

        if not self.run_timed_break_screen(THREE_MINUTE_BREAK_COPY, duration_s=180):
            print("[flow] ended at step 20 (3-minute break)")
            return 0

        if not self.run_reading_comprehension_paragraph(3):
            print("[flow] ended at step 21 (reading paragraph 3)")
            return 0

        if not self.run_reading_comprehension_mcq(3):
            print("[flow] ended at step 22 (reading paragraph 3 MCQs)")
            return 0

        if not self.run_detectability_transition_screen():
            print("[flow] ended before step 23 (detectability block 3 transition)")
            return 0

        if not self.run_detectability_phase(phase="block3", display_label="Detectability block 3"):
            print("[flow] ended at step 23 (detectability block 3)")
            return 0

        if not self.run_questionnaire_blank_screen(step_number=22):
            print("[flow] ended at step 24 (questionnaire blank)")
            return 0

        if not self.run_questionnaire_blank_screen(step_number=23):
            print("[flow] ended at step 25 (questionnaire blank)")
            return 0

        if not self.run_qualitative_questions_screen():
            print("[flow] ended at step 26 (qualitative questions)")
            return 0

        if not self.run_thank_you_screen():
            print("[flow] ended at step 27 (thank you)")
            return 0

        if not self.run_study_purpose_screen():
            print("[flow] ended at step 28 (study purpose)")
            return 0

        print("[flow] complete: all 29 steps finished")
        self._finalize_logging()
        return 0

    def close(self) -> None:
        self._finalize_logging()
        self._stop_blur_renderer()
        self.root.destroy()


def main() -> int:
    app = ParticipantExperiment()
    try:
        return app.run()
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main())
