from __future__ import annotations

from dataclasses import dataclass
import time
import textwrap
import tkinter as tk
import tkinter.font as tkfont


CONDITION_LABELS = {
    "none": "No blur",
    "full": "Full blur",
    "eyetracked": "Eyetracked blur",
}

READING_WRAP_WIDTH = 88
QUESTION_WRAP_WIDTH = 88
OPTION_WRAP_WIDTH = 84
SNIPPET_WRAP_WIDTH = 88
DETECTABILITY_READING_TIME_S = 3.0


@dataclass(frozen=True)
class DarkInfoCopy:
    """Container for dark-themed info screen content (title + body text)."""

    title: str
    body: str


@dataclass(frozen=True)
class CalibrationCopy:
    """Container for calibration-specific screen text and templates."""

    title: str
    setup: str
    tracker_missing: str
    progress_template: str
    success: str
    failure: str


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
        "This is a practice task for reading comprehension. You will read a short paragagraph on screen. \n Read it at your normal pace. When you finish, press the spacebar. \n You will then answer 3 questions about what you read. \n Take your time.\n"
        "\nLater in the experiment you will read 3 additional paragraphs with MCQs.\n\n"
        "Press SPACE to continue.\n\n\n\n\n"
        "Press CTRL+SHIFT+Q to quit."
    ),
)

READING_TASK_REMINDER_COPY = DarkInfoCopy(
    title="Reading Task Reminder",
    body=(
        "You will read a short paragraph on screen. Read it at your normal pace.\n"
        "When you finish, press the spacebar. You will then answer 3 questions\n"
        "about what you read. Take your time.\n\n"
        "Press SPACE to continue.\n\n"
        "Press CTRL+SHIFT+Q to quit."
    ),
)

DETECTABILITY_ACK_COPY = DarkInfoCopy(
    title="Detectability",
    body=(
        "You will read short text snippets with different screen blur conditions.\n"
        "Each snippet is shown for 3 seconds.\n"
        "Afterward, you will answer what blur type you think was shown.\n\n"
        "You will start with 6 practice tasks to get a feel for the task. Then you will complete 36 trials.\n\n"
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
        "Ask any questions to the experimenter now.\n\n"
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
    setup=(
        "Calibration Setup\n\n"
        "Press SPACE to start eye-tracker calibration.\n"
        "Press CTRL+SHIFT+Q to quit."
    ),
    tracker_missing=(
        "No Tobii tracker detected.\n\n"
        "Press SPACE to continue in development mode (skip calibration).\n"
        "Press CTRL+SHIFT+Q to quit.\n\n"
        "When Tobii Pro Fusion is available, rerun calibration."
    ),
    progress_template=(
        "Calibrating... Point {index}/{total}\n"
        "Attempt {attempt}\n\n"
        "Keep your head still and look at the white dot.\n"
        "Press CTRL+SHIFT+Q to quit."
    ),
    success=(
        "Calibration complete.\n\n"
        "Press SPACE to continue.\n"
        "Press CTRL+SHIFT+Q to quit."
    ),
    failure=(
        "Calibration failed or was interrupted.\n\n"
        "Press CTRL+SHIFT+Q to quit."
    ),
)


class BaseScreen:
    """Shared access to the root window and experiment helper methods."""

    def __init__(self, experiment: object) -> None:
        self._exp = experiment
        self.root = experiment.root  # type: ignore[attr-defined]

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
    def show(self, title: str, body: str, relwidth: float = 0.68, relheight: float = 0.62) -> bool:
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
    def show(self, header: str, body: str, footer: str, relwidth: float = 0.62, relheight: float = 0.80) -> bool:
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
    def show(self, headline: str, question: str, options: list[str], instruction: str, n_options: int = 4) -> str:
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
    def show(self, snippet: str, idx: int, total: int, duration_s: float = DETECTABILITY_READING_TIME_S) -> bool:
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


class TimedBreakScreen(BaseScreen):
    def show(self, copy: DarkInfoCopy, duration_s: int) -> bool:
        panel = self._build_light_panel(relwidth=0.68, relheight=0.64)
        self._add_section_banner(panel, "BREAK")

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

        # Drop any stale queued skip from earlier screens so this break only
        # fast-forwards on an intentional Ctrl+Shift+R during this break.
        while self._exp._consume_timer_skip():
            pass

        self._exp._timer_wait_active = True
        try:
            for remaining in range(max(1, duration_s), 0, -1):
                if self._exp.quit_requested:
                    return False
                if self._exp._consume_timer_skip():
                    break
                timer_label.config(text=f"Time remaining: {remaining} seconds")

                elapsed = 0.0
                while elapsed < 1.0:
                    if self._exp.quit_requested:
                        return False
                    self.root.update()
                    time.sleep(0.05)
                    elapsed += 0.05
        finally:
            self._exp._timer_wait_active = False

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

        return self._exp._wait_for_keys({"<space>": "CONTINUE"}) == "CONTINUE"
