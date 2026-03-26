from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ContentPaths:
    """Filesystem paths used for experiment content loading."""

    base_dir: Path
    texts_base_dir: Path
    paragraph_text_dir: Path
    mcq_text_dir: Path
    detectability_text_dir: Path


@dataclass(frozen=True)
class ContentBundle:
    """Loaded experiment content and constants required by the protocol."""

    paths: ContentPaths
    practice_paragraph_file: str
    paragraph_text_map: dict[str, str]
    mcq_items_by_paragraph: dict[str, list[dict[str, object]]]
    training_text: str
    mcq_items_practice: list[dict[str, object]]
    detectability_trial_map: dict[str, str]
    detectability_texts: list[str]
    detectability_test_trials: int
    detectability_block_trials: int
    detectability_block_count: int
    detectability_total_trials: int


@dataclass(frozen=True)
class ContentValidationResult:
    """Validation output for required content files and payloads."""

    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


class ContentLoader:
    """Load and validate text content used by ParticipantExperiment.

    This class centralizes the content loading currently embedded in ParticipantTest.
    """

    def __init__(
        self,
        *,
        base_dir: Path,
        practice_paragraph_file: str = "generations.txt",
        detectability_test_trials: int = 6,
        detectability_block_trials: int = 12,
        detectability_block_count: int = 3,
    ) -> None:
        self._base_dir = base_dir
        self._practice_paragraph_file = practice_paragraph_file
        self._detectability_test_trials = detectability_test_trials
        self._detectability_block_trials = detectability_block_trials
        self._detectability_block_count = detectability_block_count

    def build_paths(self) -> ContentPaths:
        texts_base_dir = self._base_dir / "experiment_helper" / "texts"
        return ContentPaths(
            base_dir=self._base_dir,
            texts_base_dir=texts_base_dir,
            paragraph_text_dir=texts_base_dir / "paragraphs",
            mcq_text_dir=texts_base_dir / "MCQ_and_answers",
            detectability_text_dir=texts_base_dir / "detectibilityText",
        )

    def load(self) -> ContentBundle:
        paths = self.build_paths()
        paragraph_text_map = self._load_paragraph_text_map_from_dir(paths.paragraph_text_dir)
        mcq_items_by_paragraph = self._load_mcq_map_for_paragraphs(
            paragraph_files=list(paragraph_text_map.keys()),
            mcq_dir=paths.mcq_text_dir,
        )
        detectability_trial_map = self._load_detectability_trial_map_from_dir(paths.detectability_text_dir)
        detectability_total_trials = self._detectability_test_trials + (
            self._detectability_block_trials * self._detectability_block_count
        )

        return ContentBundle(
            paths=paths,
            practice_paragraph_file=self._practice_paragraph_file,
            paragraph_text_map=paragraph_text_map,
            mcq_items_by_paragraph=mcq_items_by_paragraph,
            training_text=paragraph_text_map.get(self._practice_paragraph_file, ""),
            mcq_items_practice=mcq_items_by_paragraph.get(self._practice_paragraph_file, []),
            detectability_trial_map=detectability_trial_map,
            detectability_texts=list(detectability_trial_map.values()),
            detectability_test_trials=self._detectability_test_trials,
            detectability_block_trials=self._detectability_block_trials,
            detectability_block_count=self._detectability_block_count,
            detectability_total_trials=detectability_total_trials,
        )

    def validate(self, bundle: ContentBundle) -> ContentValidationResult:
        errors: list[str] = []

        paragraph_files = sorted(bundle.paragraph_text_map.keys())
        if not paragraph_files:
            errors.append(f"No paragraph files could be loaded from {bundle.paths.paragraph_text_dir}")

        if not bundle.training_text:
            errors.append(
                f"Practice paragraph '{bundle.practice_paragraph_file}' is missing or empty"
            )

        if not bundle.mcq_items_practice:
            errors.append(
                f"Practice MCQ file for '{bundle.practice_paragraph_file}' is missing or empty"
            )

        missing_mcq = [name for name in paragraph_files if not bundle.mcq_items_by_paragraph.get(name)]
        if missing_mcq:
            errors.append(f"Missing MCQ sets for paragraph files: {', '.join(missing_mcq)}")

        required_trials = [
            f"trial_{idx:02d}.txt" for idx in range(1, bundle.detectability_total_trials + 1)
        ]
        missing_trials = [name for name in required_trials if name not in bundle.detectability_trial_map]
        if missing_trials:
            errors.append(
                f"Missing detectability trial files ({len(missing_trials)}): "
                f"{', '.join(missing_trials[:8])}"
                + (" ..." if len(missing_trials) > 8 else "")
            )

        return ContentValidationResult(errors=errors)

    @staticmethod
    def _load_utf8_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8").lstrip("\ufeff").strip()
        except OSError:
            return ""

    def _load_mcq_items_from_txt(self, path: Path) -> list[dict[str, object]]:
        raw = self._load_utf8_text(path)
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

    def _load_detectability_trial_map_from_dir(self, dir_path: Path) -> dict[str, str]:
        trials: dict[str, str] = {}
        try:
            for path in sorted(dir_path.glob("trial_*.txt")):
                content = self._load_utf8_text(path)
                if content:
                    trials[path.name] = content
            if trials:
                return trials

            for path in sorted(dir_path.glob("*.txt")):
                content = self._load_utf8_text(path)
                if content:
                    trials[path.name] = content
        except OSError:
            return {}
        return trials

    def _load_paragraph_text_map_from_dir(self, dir_path: Path) -> dict[str, str]:
        paragraphs: dict[str, str] = {}
        try:
            for path in sorted(dir_path.glob("*.txt")):
                content = self._load_utf8_text(path)
                if content:
                    paragraphs[path.name] = content
        except OSError:
            return {}
        return paragraphs

    def _load_mcq_map_for_paragraphs(
        self,
        paragraph_files: list[str],
        mcq_dir: Path,
    ) -> dict[str, list[dict[str, object]]]:
        mcq_map: dict[str, list[dict[str, object]]] = {}
        for paragraph_file in paragraph_files:
            qa_file = f"{Path(paragraph_file).stem}QA.txt"
            items = self._load_mcq_items_from_txt(mcq_dir / qa_file)
            if items:
                mcq_map[paragraph_file] = items
        return mcq_map
