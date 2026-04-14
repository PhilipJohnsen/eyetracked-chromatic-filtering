from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from typing import Callable


@dataclass(frozen=True)
class SessionIdentity:
    """Identity fields for one participant session."""

    participant_id: str
    participant_number: int
    session_id: str


@dataclass(frozen=True)
class SessionPaths:
    """Resolved filesystem paths for session outputs."""

    session_dir: Path
    events_log_path: Path
    segments_log_path: Path
    manifest_log_path: Path
    eye_events_log_path: Path
    eye_windows_log_path: Path
    outcomes_flat_log_path: Path
    detectability_trials_log_path: Path
    detectability_summary_log_path: Path


@dataclass
class SessionLoggingState:
    """Mutable state for write fallbacks and in-memory mirrors."""

    fallback_active: bool = False
    fallback_reason: str = ""
    in_memory_events: list[dict[str, object]] | None = None
    in_memory_segments: list[dict[str, object]] | None = None

    def __post_init__(self) -> None:
        if self.in_memory_events is None:
            self.in_memory_events = []
        if self.in_memory_segments is None:
            self.in_memory_segments = []


class SessionLogger:
    """Session logging subsystem for events, segments, manifests, and exports.

    This class is intentionally orchestration-friendly: ParticipantExperiment can call
    small methods while this class encapsulates I/O details and data serialization.
    """

    def __init__(
        self,
        *,
        base_dir: Path,
        participant_number: int,
        latin_variant_index: int,
        session_order: dict[str, object],
        outcome_keys: list[str],
    ) -> None:
        self.base_dir = base_dir
        self.participant_number = participant_number
        self.participant_id = f"P{participant_number:03d}"
        self.session_id = "S01"
        self.latin_variant_index = latin_variant_index
        self.session_order = session_order
        self.outcome_keys = list(outcome_keys)

        self.session_started_utc = self.utc_now_iso()
        self.paths: SessionPaths | None = None
        self.state = SessionLoggingState()

        self.segment_starts: dict[str, tuple[str, float]] = {}
        self.active_eye_window_starts: dict[str, dict[str, object]] = {}
        self.eye_capture_windows: list[dict[str, object]] = []
        self.eye_movement_window_summaries: list[dict[str, object]] = []

        self.logging_finalized = False
        self.outcomes: dict[str, dict[str, object]] = {
            key: {"value": None, "status": "pending", "source": "participant_test"}
            for key in self.outcome_keys
        }

    def initialize_session_paths(self) -> SessionPaths:
        logs_root = self.base_dir / "logs"
        preferred_participant_dir = logs_root / self.participant_id

        try:
            preferred_participant_dir.mkdir(parents=True, exist_ok=True)
            self.session_id = self.next_session_id(preferred_participant_dir)
            session_dir = preferred_participant_dir / self.session_id
            session_dir.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            self.state.fallback_active = True
            self.state.fallback_reason = f"session dir fallback: {exc}"
            fallback_dir = logs_root / "_fallback"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self.session_id = f"FALLBACK_{stamp}"
            session_dir = fallback_dir

        self.paths = SessionPaths(
            session_dir=session_dir,
            events_log_path=session_dir / "events.jsonl",
            segments_log_path=session_dir / "segments.csv",
            manifest_log_path=session_dir / "session_manifest.json",
            eye_events_log_path=session_dir / "eye_events.csv",
            eye_windows_log_path=session_dir / "eye_windows.csv",
            outcomes_flat_log_path=session_dir / "outcomes_flat.csv",
            detectability_trials_log_path=session_dir / "detectability_trials.csv",
            detectability_summary_log_path=session_dir / "detectability_summary.csv",
        )
        self._ensure_segments_header()
        return self.paths

    def next_session_id(self, participant_dir: Path) -> str:
        existing: list[int] = []
        for child in participant_dir.glob("S*"):
            if child.is_dir() and len(child.name) >= 2 and child.name[1:].isdigit():
                existing.append(int(child.name[1:]))
        return f"S{(max(existing) + 1) if existing else 1:02d}"

    def utc_now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def log_event(self, event_type: str, payload: dict[str, object]) -> None:
        self.safe_write_event(
            {
                "event_type": event_type,
                "timestamp_utc": self.utc_now_iso(),
                "payload": payload,
            }
        )

    def segment_start(
        self,
        segment_name: str,
        payload: dict[str, object] | None = None,
        *,
        start_eye_window: Callable[[str, dict[str, object] | None], None] | None = None,
    ) -> None:
        start_utc = self.utc_now_iso()
        self.segment_starts[segment_name] = (start_utc, time.perf_counter())
        if start_eye_window is not None:
            start_eye_window(segment_name, payload)
        self.log_event(f"{segment_name}_started", payload or {})

    def segment_end(
        self,
        segment_name: str,
        *,
        status: str,
        metrics: dict[str, object] | None = None,
        end_eye_window: Callable[[str, str], None] | None = None,
    ) -> None:
        if end_eye_window is not None:
            end_eye_window(segment_name, status)

        start = self.segment_starts.pop(segment_name, None)
        if start is None:
            start_utc = self.utc_now_iso()
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
            "ended_at_utc": self.utc_now_iso(),
            "status": status,
            "metrics": out_metrics,
        }
        self.safe_write_segment_row(row)

        payload = dict(out_metrics)
        payload["status"] = status
        self.log_event(f"{segment_name}_completed", payload)

    def safe_write_event(self, event: dict[str, object]) -> None:
        self.state.in_memory_events.append(event)
        if self.paths is None:
            return
        try:
            with self.paths.events_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=True) + "\n")
        except OSError as exc:
            self.state.fallback_active = True
            self.state.fallback_reason = f"events write failed: {exc}"

    def safe_write_segment_row(self, row: dict[str, object]) -> None:
        self.state.in_memory_segments.append(row)
        if self.paths is None:
            return
        try:
            with self.paths.segments_log_path.open("a", encoding="utf-8", newline="") as fh:
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
        except OSError as exc:
            self.state.fallback_active = True
            self.state.fallback_reason = f"segments write failed: {exc}"

    def write_manifest(self, *, notes: dict[str, object] | None = None) -> None:
        if self.paths is None:
            return

        manifest = {
            "participant": {
                "participant_id": self.participant_id,
                "participant_number": self.participant_number,
                "session_id": self.session_id,
                "date_utc": self.session_started_utc,
            },
            "created_at_utc": self.session_started_utc,
            "updated_at_utc": self.utc_now_iso(),
            "logging": {
                "fallback_active": self.state.fallback_active,
                "fallback_reason": self.state.fallback_reason,
                "events_path": str(self.paths.events_log_path),
                "segments_path": str(self.paths.segments_log_path),
                "eye_events_path": str(self.paths.eye_events_log_path),
                "eye_windows_path": str(self.paths.eye_windows_log_path),
                "outcomes_flat_path": str(self.paths.outcomes_flat_log_path),
                "detectability_trials_path": str(self.paths.detectability_trials_log_path),
                "detectability_summary_path": str(self.paths.detectability_summary_log_path),
            },
            "schedule": {
                "latin_variant_index": self.latin_variant_index,
                "reading_order_index": self.session_order.get("reading_order_index", None),
                "practice_trial_files": self.session_order.get("practice_trial_files", []),
                "block_trial_files": self.session_order.get("block_trial_files", []),
                "main_filter_counts": self.session_order.get("main_filter_counts", {}),
                "paragraph_order": self.session_order.get("paragraph_order", []),
                "comprehension_paragraphs": self.session_order.get("comprehension_paragraphs", []),
            },
            "outcomes": self.outcomes,
            "notes": notes or {},
        }

        try:
            self.paths.manifest_log_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
        except OSError as exc:
            self.state.fallback_active = True
            self.state.fallback_reason = f"manifest write failed: {exc}"

    def set_outcome(
        self,
        key: str,
        value: object,
        *,
        status: str = "logged",
        source: str = "participant_test",
    ) -> None:
        self.outcomes[key] = {
            "value": value,
            "status": status,
            "source": source,
        }

    def attach_eye_movement_window_summaries(self, summaries: list[dict[str, object]]) -> None:
        normalized: list[dict[str, object]] = []
        for row in summaries:
            if not isinstance(row, dict):
                continue
            events_raw = row.get("events", {})
            events_normalized: dict[str, list[dict[str, object]]] = {
                "blinks": [],
                "saccades": [],
                "fixations": [],
            }
            if isinstance(events_raw, dict):
                for key in ["blinks", "saccades", "fixations"]:
                    bucket = events_raw.get(key, [])
                    if not isinstance(bucket, list):
                        continue
                    for event in bucket:
                        if isinstance(event, dict):
                            events_normalized[key].append(dict(event))

            normalized.append(
                {
                    "label": str(row.get("label", "window")),
                    "condition": str(row.get("condition", "")),
                    "section": str(row.get("section", "")),
                    "section_index": int(row.get("section_index", 0) or 0),
                    "phase": str(row.get("phase", "")),
                    "step": str(row.get("step", "")),
                    "trial_index": int(row.get("trial_index", 0) or 0),
                    "trial_file": str(row.get("trial_file", "")),
                    "start_system_time_stamp": int(row.get("start_system_time_stamp", 0) or 0),
                    "end_system_time_stamp": int(row.get("end_system_time_stamp", 0) or 0),
                    "blinks_count": int(row.get("blinks_count", 0) or 0),
                    "saccades_count": int(row.get("saccades_count", 0) or 0),
                    "saccades_total_duration_ms": float(row.get("saccades_total_duration_ms", 0.0) or 0.0),
                    "fixations_count": int(row.get("fixations_count", 0) or 0),
                    "fixations_total_duration_ms": float(row.get("fixations_total_duration_ms", 0.0) or 0.0),
                    "events": events_normalized,
                }
            )

        self.eye_movement_window_summaries = normalized
        self.log_event(
            "eye_movement_windows_attached",
            {
                "n_windows": len(normalized),
                "conditions": sorted({str(r.get("condition", "")) for r in normalized}),
            },
        )

    def compute_detectability_dprime(
        self,
        *,
        filter_conditions: list[str],
        detectability_trial_records: list[dict[str, object]],
    ) -> dict[str, float]:
        # Lazily import to keep this helper independent from external dependencies.
        from statistics import NormalDist

        by_condition: dict[str, dict[str, int]] = {
            c: {"hits": 0, "misses": 0, "fa": 0, "cr": 0}
            for c in filter_conditions
        }

        for rec in detectability_trial_records:
            true_cond = str(rec.get("condition", "none"))
            selected_cond = str(rec.get("selected_condition", "none"))
            for cond in filter_conditions:
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

    def finalize_eye_movement_outcomes(self, *, filter_conditions: list[str]) -> None:
        rows = [r for r in self.eye_movement_window_summaries if isinstance(r, dict)]
        if not rows:
            return

        by_condition: dict[str, list[dict[str, object]]] = {c: [] for c in filter_conditions}
        for row in rows:
            condition = str(row.get("condition", ""))
            if condition in by_condition:
                by_condition[condition].append(row)

        if all(not cond_rows for cond_rows in by_condition.values()):
            by_condition = {"all": rows}

        def _mean(values: list[float]) -> float | None:
            if not values:
                return None
            return round(sum(values) / len(values), 3)

        def _aggregate(metric_key: str, *, cast=float) -> dict[str, object]:
            out: dict[str, object] = {}
            for condition, cond_rows in by_condition.items():
                values: list[float] = []
                for row in cond_rows:
                    try:
                        values.append(float(cast(row.get(metric_key, 0))))
                    except (TypeError, ValueError):
                        continue
                out[condition] = {
                    "n_windows": len(values),
                    "mean": _mean(values),
                    "sum": round(sum(values), 3) if values else 0.0,
                    "values": [round(v, 3) for v in values],
                    "log1p_values": [round(math.log1p(max(0.0, v)), 6) for v in values],
                }
            return out

        blink_by_condition = _aggregate("blinks_count", cast=int)
        saccade_count_by_condition = _aggregate("saccades_count", cast=int)
        saccade_duration_by_condition = _aggregate("saccades_total_duration_ms", cast=float)
        fixation_count_by_condition = _aggregate("fixations_count", cast=int)
        fixation_duration_by_condition = _aggregate("fixations_total_duration_ms", cast=float)

        self.set_outcome(
            "blinks_count",
            {
                "window_level": rows,
                "by_condition": blink_by_condition,
            },
            source="eyetracker_pipeline",
        )
        self.set_outcome(
            "saccades_count",
            {
                "window_level": rows,
                "by_condition": saccade_count_by_condition,
            },
            source="eyetracker_pipeline",
        )
        self.set_outcome(
            "saccades_duration_ms",
            {
                "window_level": rows,
                "by_condition": saccade_duration_by_condition,
            },
            source="eyetracker_pipeline",
        )
        self.set_outcome(
            "fixations_count_and_length_ms",
            {
                "window_level": rows,
                "fixations_count_by_condition": fixation_count_by_condition,
                "fixations_duration_by_condition": fixation_duration_by_condition,
            },
            source="eyetracker_pipeline",
        )

    def finalize(
        self,
        *,
        quit_requested: bool,
        notes: dict[str, object] | None = None,
    ) -> None:
        if self.logging_finalized:
            return
        self.logging_finalized = True
        self.log_event(
            "session_completed",
            {
                "status": "quit" if quit_requested else "ok",
                "outcome_status_counts": {
                    status: sum(1 for v in self.outcomes.values() if v.get("status") == status)
                    for status in {str(v.get("status")) for v in self.outcomes.values()}
                },
            },
        )
        self.write_manifest(notes=notes)

    def _ensure_segments_header(self) -> None:
        if self.paths is None:
            return
        if self.paths.segments_log_path.exists():
            return
        try:
            with self.paths.segments_log_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["segment_name", "started_at_utc", "ended_at_utc", "status", "metrics_json"])
        except OSError as exc:
            self.state.fallback_active = True
            self.state.fallback_reason = f"segments header write failed: {exc}"
