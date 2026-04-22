"""Superficial eye-event validity checker.

Goal
----
Quickly validate eye-event data quality for participant sessions by scanning
`eye_events.csv` and flagging suspicious
patterns that often indicate collection or parsing issues.

Checks include:
- Missing files / empty files
- Event counts by type (blink, saccade, fixation)
- Duration stats (min/mean/p50/p95/max)
- Implausibly long event durations
- Burst-rate sanity checks in short windows (e.g., 20 blinks in 2 seconds)

Usage
-----
python logs/validate/test_eyedata_validity.py --participant P001 --session S02
python logs/validate/test_eyedata_validity.py --participant 2
python logs/validate/test_eyedata_validity.py --all
python logs/validate/test_eyedata_validity.py --all --session S02
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any


US_PER_SECOND = 1_000_000.0


@dataclass(frozen=True)
class Thresholds:
	# Duration sanity thresholds (ms)
	blink_duration_ms_max: float = 2000.0
	saccade_duration_ms_max: float = 15000.0
	fixation_duration_ms_max: float = 10000.0

	# Burst sanity checks: count within short window
	burst_window_seconds: float = 2.0
	blink_burst_count_max: int = 20
	saccade_burst_count_max: int = 60
	fixation_burst_count_max: int = 60


def _safe_float(value: Any) -> float | None:
	try:
		return float(value)
	except (TypeError, ValueError):
		return None


def _safe_int(value: Any) -> int | None:
	try:
		return int(value)
	except (TypeError, ValueError):
		return None


def _percentile(values: list[float], p: float) -> float | None:
	if not values:
		return None
	if p <= 0:
		return min(values)
	if p >= 100:
		return max(values)

	sorted_vals = sorted(values)
	rank = (len(sorted_vals) - 1) * (p / 100.0)
	low = int(rank)
	high = min(low + 1, len(sorted_vals) - 1)
	if low == high:
		return sorted_vals[low]
	weight = rank - low
	return sorted_vals[low] * (1.0 - weight) + sorted_vals[high] * weight


def _format_num(value: float | None, digits: int = 3) -> str:
	if value is None:
		return "n/a"
	return f"{value:.{digits}f}"


def _format_row_list(row_numbers: list[int], *, max_items: int = 10) -> str:
	if not row_numbers:
		return "n/a"
	unique_sorted = sorted(set(row_numbers))
	if len(unique_sorted) <= max_items:
		return ", ".join(str(n) for n in unique_sorted)
	head = ", ".join(str(n) for n in unique_sorted[:max_items])
	return f"{head}, ... (+{len(unique_sorted) - max_items} more)"


class EyeDataValidityChecker:
	def __init__(self, logs_dir: Path, session_id: str = "auto") -> None:
		self.logs_dir = Path(logs_dir)
		self.session_id = session_id
		self.thresholds = Thresholds()

	def _participant_dir(self, participant_id: str) -> Path:
		return self.logs_dir / participant_id

	def _session_dir(self, participant_id: str, session_id: str) -> Path:
		return self._participant_dir(participant_id) / session_id

	def _available_sessions(self, participant_id: str) -> list[str]:
		participant_dir = self._participant_dir(participant_id)
		if not participant_dir.exists() or not participant_dir.is_dir():
			return []

		out: list[str] = []
		for child in participant_dir.iterdir():
			if not child.is_dir() or not child.name.startswith("S"):
				continue
			if (child / "eye_events.csv").exists():
				out.append(child.name)

		def sort_key(name: str) -> tuple[int, str]:
			suffix = name[1:]
			if suffix.isdigit():
				return (int(suffix), name)
			return (-1, name)

		return sorted(out, key=sort_key)

	def _resolve_session(self, participant_id: str) -> str | None:
		if self.session_id != "auto":
			return self.session_id
		sessions = self._available_sessions(participant_id)
		return sessions[-1] if sessions else None

	def _load_csv_rows(self, csv_path: Path) -> list[dict[str, str]]:
		if not csv_path.exists():
			return []
		try:
			with csv_path.open("r", encoding="utf-8", newline="") as fh:
				reader = csv.DictReader(fh)
				rows: list[dict[str, str]] = []
				for row_num, row in enumerate(reader, start=2):
					mutable_row = dict(row)
					mutable_row["__row_num"] = str(row_num)
					rows.append(mutable_row)
				return rows
		except OSError:
			return []

	def _burst_window_info(
		self,
		timestamps_with_rows: list[tuple[int, int]],
		window_seconds: float,
	) -> tuple[int, list[int]]:
		if not timestamps_with_rows:
			return 0, []

		window_us = int(window_seconds * US_PER_SECOND)
		ts = sorted(timestamps_with_rows, key=lambda x: x[0])
		best = 0
		best_i = 0
		best_j = 0
		j = 0
		for i in range(len(ts)):
			while j < len(ts) and ts[j][0] - ts[i][0] <= window_us:
				j += 1
			if (j - i) > best:
				best = j - i
				best_i = i
				best_j = j

		rows = [row_num for _, row_num in ts[best_i:best_j] if row_num > 0]
		return best, rows

	def _event_stats(self, event_rows: list[dict[str, str]], event_type: str) -> dict[str, Any]:
		rows = [r for r in event_rows if str(r.get("event_type", "")).strip().lower() == event_type]

		durations: list[float] = []
		starts_with_rows: list[tuple[int, int]] = []
		non_positive_duration_count = 0
		non_positive_duration_rows: list[int] = []
		duration_records: list[tuple[int, float]] = []

		for row in rows:
			row_num = _safe_int(row.get("__row_num")) or 0
			dur = _safe_float(row.get("duration_ms"))
			if dur is not None:
				durations.append(dur)
				duration_records.append((row_num, dur))
				if dur <= 0:
					non_positive_duration_count += 1
					non_positive_duration_rows.append(row_num)

			start_us = _safe_int(row.get("start_system_time_stamp"))
			if start_us is not None:
				starts_with_rows.append((start_us, row_num))

		return {
			"event_type": event_type,
			"count": len(rows),
			"durations": durations,
			"start_timestamps_with_rows": starts_with_rows,
			"duration_records": duration_records,
			"non_positive_duration_count": non_positive_duration_count,
			"non_positive_duration_rows": non_positive_duration_rows,
			"duration_min_ms": min(durations) if durations else None,
			"duration_mean_ms": mean(durations) if durations else None,
			"duration_p50_ms": _percentile(durations, 50),
			"duration_p95_ms": _percentile(durations, 95),
			"duration_max_ms": max(durations) if durations else None,
		}

	def validate_participant(self, participant_id: str) -> dict[str, Any]:
		resolved_session = self._resolve_session(participant_id)
		if resolved_session is None:
			return {
				"participant_id": participant_id,
				"session_id": self.session_id,
				"ok": False,
				"issues": ["No session with eye_events.csv found"],
				"event_stats": {},
			}

		session_dir = self._session_dir(participant_id, resolved_session)
		eye_events_path = session_dir / "eye_events.csv"
		eye_windows_path = session_dir / "eye_windows.csv"

		if not eye_events_path.exists():
			return {
				"participant_id": participant_id,
				"session_id": resolved_session,
				"ok": False,
				"issues": [f"Missing file: {eye_events_path.name}"],
				"event_stats": {},
			}

		event_rows = self._load_csv_rows(eye_events_path)
		window_rows = self._load_csv_rows(eye_windows_path) if eye_windows_path.exists() else []

		issues: list[str] = []

		blink_stats = self._event_stats(event_rows, "blink")
		saccade_stats = self._event_stats(event_rows, "saccade")
		fixation_stats = self._event_stats(event_rows, "fixation")

		if not event_rows:
			issues.append("eye_events.csv has no rows")

		# Duration threshold checks
		if (blink_stats["duration_max_ms"] or 0.0) > self.thresholds.blink_duration_ms_max:
			rows = [
				row_num
				for row_num, duration in blink_stats["duration_records"]
				if duration > self.thresholds.blink_duration_ms_max
			]
			issues.append(
				"Blink duration max exceeds threshold "
				f"({blink_stats['duration_max_ms']:.3f} ms > {self.thresholds.blink_duration_ms_max:.1f} ms); "
				f"rows: {_format_row_list(rows)}"
			)
		if (saccade_stats["duration_max_ms"] or 0.0) > self.thresholds.saccade_duration_ms_max:
			rows = [
				row_num
				for row_num, duration in saccade_stats["duration_records"]
				if duration > self.thresholds.saccade_duration_ms_max
			]
			issues.append(
				"Saccade duration max exceeds threshold "
				f"({saccade_stats['duration_max_ms']:.3f} ms > {self.thresholds.saccade_duration_ms_max:.1f} ms); "
				f"rows: {_format_row_list(rows)}"
			)
		if (fixation_stats["duration_max_ms"] or 0.0) > self.thresholds.fixation_duration_ms_max:
			rows = [
				row_num
				for row_num, duration in fixation_stats["duration_records"]
				if duration > self.thresholds.fixation_duration_ms_max
			]
			issues.append(
				"Fixation duration max exceeds threshold "
				f"({fixation_stats['duration_max_ms']:.3f} ms > {self.thresholds.fixation_duration_ms_max:.1f} ms); "
				f"rows: {_format_row_list(rows)}"
			)

		# Non-positive durations
		for stats in [blink_stats, saccade_stats, fixation_stats]:
			bad = int(stats["non_positive_duration_count"])
			if bad > 0:
				issues.append(
					f"{stats['event_type']}: {bad} events have non-positive duration; "
					f"rows: {_format_row_list(stats['non_positive_duration_rows'])}"
				)

		# Burst checks in short windows
		blink_burst, blink_burst_rows = self._burst_window_info(
			blink_stats["start_timestamps_with_rows"],
			self.thresholds.burst_window_seconds,
		)
		saccade_burst, saccade_burst_rows = self._burst_window_info(
			saccade_stats["start_timestamps_with_rows"],
			self.thresholds.burst_window_seconds,
		)
		fixation_burst, fixation_burst_rows = self._burst_window_info(
			fixation_stats["start_timestamps_with_rows"],
			self.thresholds.burst_window_seconds,
		)

		if blink_burst > self.thresholds.blink_burst_count_max:
			issues.append(
				f"Blink burst too high: {blink_burst} in {self.thresholds.burst_window_seconds:.1f}s "
				f"(threshold {self.thresholds.blink_burst_count_max}); "
				f"rows in densest window: {_format_row_list(blink_burst_rows)}"
			)
		if saccade_burst > self.thresholds.saccade_burst_count_max:
			issues.append(
				f"Saccade burst too high: {saccade_burst} in {self.thresholds.burst_window_seconds:.1f}s "
				f"(threshold {self.thresholds.saccade_burst_count_max}); "
				f"rows in densest window: {_format_row_list(saccade_burst_rows)}"
			)
		if fixation_burst > self.thresholds.fixation_burst_count_max:
			issues.append(
				f"Fixation burst too high: {fixation_burst} in {self.thresholds.burst_window_seconds:.1f}s "
				f"(threshold {self.thresholds.fixation_burst_count_max}); "
				f"rows in densest window: {_format_row_list(fixation_burst_rows)}"
			)

		# Optional window coverage info
		windows_with_timestamps = 0
		for row in window_rows:
			flag = str(row.get("has_tracker_timestamps", "")).strip().lower()
			if flag == "true":
				windows_with_timestamps += 1
		if window_rows and windows_with_timestamps == 0:
			issues.append("eye_windows.csv has rows but none with tracker timestamps")

		return {
			"participant_id": participant_id,
			"session_id": resolved_session,
			"ok": len(issues) == 0,
			"issues": issues,
			"event_stats": {
				"blink": blink_stats,
				"saccade": saccade_stats,
				"fixation": fixation_stats,
			},
			"burst_summary": {
				"window_seconds": self.thresholds.burst_window_seconds,
				"blink_max_count": blink_burst,
				"saccade_max_count": saccade_burst,
				"fixation_max_count": fixation_burst,
			},
			"paths": {
				"eye_events": str(eye_events_path),
				"eye_windows": str(eye_windows_path),
			},
			"window_summary": {
				"n_windows": len(window_rows),
				"n_windows_with_timestamps": windows_with_timestamps,
			},
		}

	def validate_all(self) -> dict[str, Any]:
		participants = sorted(
			d.name for d in self.logs_dir.iterdir()
			if d.is_dir() and d.name.startswith("P")
		)
		reports = [self.validate_participant(pid) for pid in participants]
		return {
			"participants": reports,
			"total_participants": len(reports),
			"valid_participants": sum(1 for r in reports if r["ok"]),
		}


def _print_event_stats(stats: dict[str, Any]) -> None:
	print(
		f"  - {stats['event_type']}: n={stats['count']} | "
		f"dur_ms min/mean/p50/p95/max = "
		f"{_format_num(stats['duration_min_ms'])}/"
		f"{_format_num(stats['duration_mean_ms'])}/"
		f"{_format_num(stats['duration_p50_ms'])}/"
		f"{_format_num(stats['duration_p95_ms'])}/"
		f"{_format_num(stats['duration_max_ms'])}"
	)


def _print_participant_report(report: dict[str, Any]) -> None:
	participant_id = report["participant_id"]
	session_id = report.get("session_id", "unknown")
	status = "OK" if report.get("ok", False) else "ISSUES FOUND"

	print("\n" + "=" * 78)
	print(f"EYE DATA VALIDITY: {participant_id} ({session_id})")
	print("=" * 78)
	print(f"Status: {status}")

	event_stats = report.get("event_stats", {})
	if event_stats:
		print("Event stats:")
		for event_name in ["blink", "saccade", "fixation"]:
			stats = event_stats.get(event_name)
			if isinstance(stats, dict):
				_print_event_stats(stats)

	burst_summary = report.get("burst_summary", {})
	if burst_summary:
		print(
			"Burst summary: "
			f"blink={burst_summary.get('blink_max_count', 0)}, "
			f"saccade={burst_summary.get('saccade_max_count', 0)}, "
			f"fixation={burst_summary.get('fixation_max_count', 0)} "
			f"within {burst_summary.get('window_seconds', 0.0)}s"
		)

	window_summary = report.get("window_summary", {})
	if window_summary:
		print(
			"Window coverage: "
			f"n_windows={window_summary.get('n_windows', 0)}, "
			f"with_timestamps={window_summary.get('n_windows_with_timestamps', 0)}"
		)

	issues = report.get("issues", [])
	if issues:
		print("Issues:")
		for issue in issues:
			print(f"  - {issue}")


def _print_summary(summary: dict[str, Any]) -> None:
	print("\n" + "=" * 78)
	print("EYE DATA VALIDITY SUMMARY")
	print("=" * 78)
	print(f"Participants checked: {summary.get('total_participants', 0)}")
	print(f"Participants without flagged issues: {summary.get('valid_participants', 0)}")

	for report in summary.get("participants", []):
		pid = report.get("participant_id", "unknown")
		sid = report.get("session_id", "unknown")
		status = "OK" if report.get("ok", False) else "ISSUES"
		issues = report.get("issues", [])
		issue_count = len(issues)
		print(f"- {pid} ({sid}): {status}, issue_count={issue_count}")
		if issues:
			for issue in issues:
				print(f"    * {issue}")


def _normalize_participant_id(raw: str) -> str:
	if raw.startswith("P"):
		return raw
	return f"P{int(raw):03d}"


def main() -> int:
	parser = argparse.ArgumentParser(description="Superficial eye-event validity checker")
	parser.add_argument("--participant", help="Participant ID, e.g. P001 or 1")
	parser.add_argument("--all", action="store_true", help="Validate all participants under logs/")
	parser.add_argument(
		"--logs-dir",
		type=Path,
		default=Path(__file__).resolve().parents[1],
		help="Path to logs directory (default: logs/)",
	)
	parser.add_argument(
		"--session",
		default="auto",
		help="Session ID to validate (default: auto, latest SXX with eye_events.csv)",
	)

	args = parser.parse_args()
	checker = EyeDataValidityChecker(args.logs_dir, session_id=args.session)

	if args.all or not args.participant:
		summary = checker.validate_all()
		_print_summary(summary)
		if summary["total_participants"] == 0:
			return 1
		return 0 if summary["valid_participants"] == summary["total_participants"] else 1

	participant_id = _normalize_participant_id(args.participant)
	report = checker.validate_participant(participant_id)
	_print_participant_report(report)
	return 0 if report.get("ok", False) else 1


if __name__ == "__main__":
	raise SystemExit(main())
