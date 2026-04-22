"""Focused data presence checker for analysis variables.

This script validates that the non-SurveyXact measurements used in your analysis
exist in the session manifest and contain usable values.

Checks:
- Reading comprehension accuracy (%): present and has paragraph-level data
- Reading time (sec): present and > 0
- Detectability identification accuracy (True/False): present and has trial-level data
- Detectability response time (ms): present and > 0
- Blinks count: present and > 0
- Saccades count: present and > 0
- Saccades duration (ms): present and > 0
- Fixations count and length (ms): present and > 0

Usage:
    python logs/validate/test_data_workflow.py
    python logs/validate/test_data_workflow.py --participant P001
    python logs/validate/test_data_workflow.py --participant P001 --session S02
    python logs/validate/test_data_workflow.py --all
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_OUTCOMES = {
    "reading_comprehension_accuracy_pct": "Reading comprehension accuracy (%)",
    "reading_time_sec": "Reading time (sec)",
    "detectability_identification_accuracy_true_false": "Detectability identification accuracy",
    "detectability_response_time_ms": "Detectability response time (ms)",
    "blinks_count": "Blinks count",
    "saccades_count": "Saccades count",
    "saccades_duration_ms": "Saccades duration (ms)",
    "fixations_count_and_length_ms": "Fixations count and length (ms)",
}


def _safe_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class DataPresenceChecker:
    """Check that required analysis values exist and are non-zero where expected."""

    def __init__(self, logs_dir: Path, session_id: str = "auto") -> None:
        self.logs_dir = Path(logs_dir)
        self.session_id = session_id

    def _manifest_path(self, participant_id: str, session_id: str) -> Path:
        return self.logs_dir / participant_id / session_id / "session_manifest.json"

    def _available_sessions(self, participant_id: str) -> list[str]:
        participant_dir = self.logs_dir / participant_id
        if not participant_dir.exists() or not participant_dir.is_dir():
            return []

        sessions = []
        for candidate in participant_dir.iterdir():
            if not candidate.is_dir() or not candidate.name.startswith("S"):
                continue
            if (candidate / "session_manifest.json").exists():
                sessions.append(candidate.name)

        def _session_sort_key(session_name: str) -> tuple[int, str]:
            suffix = session_name[1:]
            if suffix.isdigit():
                return (int(suffix), session_name)
            return (-1, session_name)

        return sorted(sessions, key=_session_sort_key)

    def _resolve_session_id(self, participant_id: str) -> str | None:
        if self.session_id != "auto":
            return self.session_id

        sessions = self._available_sessions(participant_id)
        if not sessions:
            return None
        return sessions[-1]

    def _load_manifest(self, participant_id: str) -> tuple[dict[str, Any] | None, str | None]:
        resolved_session = self._resolve_session_id(participant_id)
        if resolved_session is None:
            return None, None

        manifest_path = self._manifest_path(participant_id, resolved_session)
        if not manifest_path.exists():
            return None, resolved_session
        try:
            with manifest_path.open("r", encoding="utf-8") as fh:
                return json.load(fh), resolved_session
        except json.JSONDecodeError:
            return None, resolved_session

    def _outcome_value(self, manifest: dict[str, Any], key: str) -> Any:
        outcomes = manifest.get("outcomes", {})
        if not isinstance(outcomes, dict):
            return None
        outcome = outcomes.get(key, {})
        if not isinstance(outcome, dict):
            return None
        return outcome.get("value")

    def _has_nonempty_values(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, dict):
            return any(self._has_nonempty_values(item) for item in value.values())
        if isinstance(value, list):
            return any(self._has_nonempty_values(item) for item in value)
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return True
        return True

    def _sum_numeric_leaf_values(self, value: Any) -> float:
        if isinstance(value, dict):
            return sum(self._sum_numeric_leaf_values(item) for item in value.values())
        if isinstance(value, list):
            return sum(self._sum_numeric_leaf_values(item) for item in value)
        number = _safe_number(value)
        return float(number) if number is not None else 0.0

    def _check_outcome(self, manifest: dict[str, Any], key: str) -> tuple[bool, str]:
        value = self._outcome_value(manifest, key)
        label = REQUIRED_OUTCOMES[key]

        if key == "reading_comprehension_accuracy_pct":
            if not isinstance(value, dict):
                return False, f"{label}: missing summary data"
            if not self._has_nonempty_values(value.get("paragraph_level")):
                return False, f"{label}: paragraph-level answers missing"
            if _safe_number(value.get("overall_mean_pct")) is None:
                return False, f"{label}: overall mean missing"
            return True, f"{label}: ok"

        if key == "reading_time_sec":
            if not isinstance(value, dict):
                return False, f"{label}: missing summary data"
            if _safe_number(value.get("overall_mean_sec")) in (None, 0.0):
                return False, f"{label}: overall mean is missing or zero"
            return True, f"{label}: ok"

        if key == "detectability_identification_accuracy_true_false":
            if not isinstance(value, dict):
                return False, f"{label}: missing summary data"
            if not self._has_nonempty_values(value.get("trial_level")):
                return False, f"{label}: trial-level data missing"
            if _safe_number(value.get("accuracy_pct")) is None:
                return False, f"{label}: accuracy summary missing"
            return True, f"{label}: ok"

        if key == "detectability_response_time_ms":
            if not isinstance(value, dict):
                return False, f"{label}: missing summary data"
            if _safe_number(value.get("mean_rt_ms")) in (None, 0.0):
                return False, f"{label}: mean RT is missing or zero"
            return True, f"{label}: ok"

        if key == "blinks_count":
            if not isinstance(value, dict):
                return False, f"{label}: missing summary data"
            total = self._sum_numeric_leaf_values(value.get("by_condition", {}))
            if total <= 0:
                return False, f"{label}: no blink counts found"
            return True, f"{label}: ok"

        if key == "saccades_count":
            if not isinstance(value, dict):
                return False, f"{label}: missing summary data"
            total = self._sum_numeric_leaf_values(value.get("by_condition", {}))
            if total <= 0:
                return False, f"{label}: no saccade counts found"
            return True, f"{label}: ok"

        if key == "saccades_duration_ms":
            if not isinstance(value, dict):
                return False, f"{label}: missing summary data"
            total = self._sum_numeric_leaf_values(value.get("by_condition", {}))
            if total <= 0:
                return False, f"{label}: no saccade durations found"
            return True, f"{label}: ok"

        if key == "fixations_count_and_length_ms":
            if not isinstance(value, dict):
                return False, f"{label}: missing summary data"
            count_total = self._sum_numeric_leaf_values(value.get("fixations_count_by_condition", {}))
            duration_total = self._sum_numeric_leaf_values(value.get("fixations_duration_by_condition", {}))
            if count_total <= 0:
                return False, f"{label}: no fixation counts found"
            if duration_total <= 0:
                return False, f"{label}: no fixation durations found"
            return True, f"{label}: ok"

        return False, f"{label}: unsupported check"

    def validate_participant(self, participant_id: str) -> dict[str, Any]:
        manifest, resolved_session = self._load_manifest(participant_id)
        if manifest is None:
            if self.session_id == "auto":
                missing_message = (
                    f"Missing or invalid manifest for {participant_id}; "
                    f"no session with session_manifest.json was found"
                )
            else:
                missing_message = (
                    f"Missing or invalid manifest for {participant_id} "
                    f"in session {self.session_id}"
                )
            return {
                "participant_id": participant_id,
                "session_id": resolved_session or self.session_id,
                "ok": False,
                "missing": ["session_manifest.json"],
                "missing_labels": ["session_manifest.json"],
                "messages": [missing_message],
            }

        missing: list[str] = []
        missing_labels: list[str] = []
        messages: list[str] = []
        passed = 0

        for key in REQUIRED_OUTCOMES:
            ok, message = self._check_outcome(manifest, key)
            messages.append(message)
            if ok:
                passed += 1
            else:
                missing.append(key)
                missing_labels.append(REQUIRED_OUTCOMES[key])

        return {
            "participant_id": participant_id,
            "session_id": resolved_session or self.session_id,
            "ok": len(missing) == 0,
            "passed": passed,
            "total": len(REQUIRED_OUTCOMES),
            "missing": missing,
            "missing_labels": missing_labels,
            "messages": messages,
        }

    def validate_all(self) -> dict[str, Any]:
        participants = sorted(
            d.name for d in self.logs_dir.iterdir()
            if d.is_dir() and d.name.startswith("P")
        )
        reports = [self.validate_participant(participant_id) for participant_id in participants]
        return {
            "participants": reports,
            "total_participants": len(reports),
            "valid_participants": sum(1 for report in reports if report["ok"]),
        }


def _print_participant_report(report: dict[str, Any]) -> None:
    participant_id = report["participant_id"]
    session_id = report.get("session_id", "unknown")
    status = "OK" if report["ok"] else "MISSING DATA"
    passed = report.get("passed", 0)
    total = report.get("total", len(REQUIRED_OUTCOMES))
    missing_labels = report.get("missing_labels", [])
    print("\n" + "=" * 70)
    if report["ok"]:
        print(f"{participant_id}: Data complete ({passed}/{total})")
    else:
        missing_text = ", ".join(missing_labels) if missing_labels else "unknown"
        print(f"{participant_id}: Missing data ({passed}/{total}), missing {missing_text}")
    print(f"DATA CHECK: {participant_id} ({session_id})")
    print("=" * 70)
    print(f"Status: {status}")
    print(f"Passed: {passed}/{total}")

    for message in report.get("messages", []):
        prefix = "✓" if ": ok" in message else "✗"
        print(f"{prefix} {message}")

    if missing_labels:
        print("\nMissing checks:")
        for label in missing_labels:
            print(f"  - {label}")


def _print_summary(report: dict[str, Any]) -> None:
    print("\n" + "=" * 70)
    print("DATA CHECK SUMMARY")
    print("=" * 70)
    print(f"Participants checked: {report['total_participants']}")
    print(f"Participants with all required data: {report['valid_participants']}")

    for participant_report in report.get("participants", []):
        status = "OK" if participant_report["ok"] else "MISSING DATA"
        missing_labels = participant_report.get("missing_labels", [])
        missing_text = ", ".join(missing_labels) if missing_labels else "none"
        session_id = participant_report.get("session_id", "unknown")
        print(
            f"- {participant_report['participant_id']} ({session_id}): {status} "
            f"({participant_report.get('passed', 0)}/{participant_report.get('total', len(REQUIRED_OUTCOMES))}), "
            f"missing: {missing_text}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Check required analysis data exists")
    parser.add_argument("--participant", help="Participant ID, e.g. P001")
    parser.add_argument("--all", action="store_true", help="Check all participants in logs/")
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Path to the logs directory (default: logs/)",
    )
    parser.add_argument(
        "--session",
        default="auto",
        help="Session ID to check (default: auto, uses latest available session)",
    )

    args = parser.parse_args()
    checker = DataPresenceChecker(args.logs_dir, session_id=args.session)

    if args.all or not args.participant:
        report = checker.validate_all()
        _print_summary(report)
        if report["total_participants"] == 0:
            return 1
        return 0 if report["valid_participants"] == report["total_participants"] else 1

    if args.participant:
        participant_id = args.participant
        if not participant_id.startswith("P"):
            participant_id = f"P{int(participant_id):03d}"
        checker.session_id = args.session
        report = checker.validate_participant(participant_id)
        _print_participant_report(report)
        return 0 if report["ok"] else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
