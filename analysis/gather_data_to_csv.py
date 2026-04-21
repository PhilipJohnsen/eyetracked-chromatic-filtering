from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


CONDITIONS: Tuple[str, ...] = ("none", "full", "eyetracked")
TEXT_ORDER: Tuple[str, ...] = ("Salt", "Hubble", "Bees")
TEXT_TO_FILE: Dict[str, str] = {
	"Salt": "salt.txt",
	"Hubble": "hubble.txt",
	"Bees": "colonycollapse.txt",
}
EVENT_TYPES: Tuple[str, ...] = ("saccade", "fixation", "blink")
TEXT_TO_TEXT_LABEL: Dict[str, str] = {
	"salt": "Salt",
	"the hubble telescope": "Hubble",
	"hubble": "Hubble",
	"colony collapse of pollinators": "Bees",
	"bees": "Bees",
}
TEXT_NUMERIC_MAP: Dict[str, float] = {
	"very low": 1.0,
	"very high": 21.0,
	"perfect": 21.0,
	"failure": 1.0,
}
QUESTIONNAIRE_EXCLUDED_COLUMNS: Tuple[str, ...] = ("", "fill in your participant number below", "what is your participant number?", "which text did you just read?")


def _safe_float(value: Any) -> Optional[float]:
	if value is None:
		return None
	text = str(value).strip()
	if not text:
		return None
	try:
		number = float(text)
	except ValueError:
		return None
	if math.isnan(number):
		return None
	return number


def _safe_int(value: Any) -> Optional[int]:
	number = _safe_float(value)
	if number is None:
		return None
	return int(number)


def _format_number(value: Optional[float], decimals: int = 3) -> str:
	if value is None:
		return ""
	return f"{value:.{decimals}f}"


def _load_csv_rows(path: Path) -> List[Dict[str, str]]:
	if not path.exists():
		return []
	encodings = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
	for enc in encodings:
		try:
			with path.open("r", encoding=enc, newline="") as f:
				rows_raw = list(csv.reader(f))
			if not rows_raw:
				return []

			header_index = 0
			for i, candidate in enumerate(rows_raw):
				nonempty = [c.strip() for c in candidate if c and c.strip()]
				if len(nonempty) >= 2:
					header_index = i
					break

			header = rows_raw[header_index]
			data_rows = rows_raw[header_index + 1 :]

			parsed: List[Dict[str, str]] = []
			for raw_row in data_rows:
				if not any((cell or "").strip() for cell in raw_row):
					continue

				row_dict: Dict[str, str] = {}
				for idx, key in enumerate(header):
					value = raw_row[idx] if idx < len(raw_row) else ""
					row_dict[key] = value

				if len(raw_row) > len(header):
					row_dict[""] = " ".join(raw_row[len(header) :])

				parsed.append(row_dict)

			return parsed
		except UnicodeDecodeError:
			continue
	return []


def _normalize_header(header: str) -> str:
	header = (header or "").strip()
	header = header.replace("\ufeff", "")
	header = re.sub(r"\s+", " ", header)
	return header


def _normalize_key(header: str) -> str:
	return _normalize_header(header).lower()


def _clean_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
	cleaned: List[Dict[str, str]] = []
	for row in rows:
		new_row: Dict[str, str] = {}
		for k, v in row.items():
			normalized_key = _normalize_header(str(k or ""))
			if isinstance(v, list):
				value_text = " ".join(str(item or "") for item in v).strip()
			else:
				value_text = str(v or "").strip()
			new_row[normalized_key] = value_text
		cleaned.append(new_row)
	return cleaned


def _participant_number_from_id(participant_id: str) -> Optional[int]:
	if not participant_id:
		return None
	if participant_id.startswith("P") and participant_id[1:].isdigit():
		return int(participant_id[1:])
	return None


def _participant_id_from_number(participant_number: int) -> str:
	return f"P{participant_number:03d}"


def _extract_participant_number(row: Dict[str, str]) -> Optional[int]:
	for key, value in row.items():
		key_norm = _normalize_key(key)
		if "participant number" in key_norm:
			n = _safe_int(value)
			if n is not None:
				return n
	return None


def _map_to_numeric(
	raw_value: str,
	participant_id: str,
	file_label: str,
	field_name: str,
	text_label: Optional[str],
	warnings: List[str],
) -> Optional[float]:
	value = (raw_value or "").strip()
	if not value:
		return None

	numeric = _safe_float(value)
	if numeric is not None:
		return numeric

	lower = value.lower()
	if lower in TEXT_NUMERIC_MAP:
		mapped = TEXT_NUMERIC_MAP[lower]
		where = f" text={text_label}" if text_label else ""
		warnings.append(
			f"[{file_label}] participant={participant_id}{where} field=\"{field_name}\" mapped text \"{value}\" -> {mapped:g}"
		)
		return mapped

	where = f" text={text_label}" if text_label else ""
	warnings.append(
		f"[{file_label}] participant={participant_id}{where} field=\"{field_name}\" has non-numeric value \"{value}\" (left blank)"
	)
	return None


def _load_demographics(questionnaire_dir: Path) -> Dict[int, Dict[str, str]]:
	rows = _clean_rows(_load_csv_rows(questionnaire_dir / "Demographic.csv"))
	by_participant: Dict[int, Dict[str, str]] = {}

	for row in rows:
		number = _extract_participant_number(row)
		if number is None:
			continue

		by_participant[number] = {
			"Demographic age": row.get("What is your age?", ""),
			"Demographic gender": row.get("What is your gender (assigned at birth)?", ""),
			"Demographic main occupation": row.get("What is your main occupation", ""),
		}

	return by_participant


def _load_eyes_general(questionnaire_dir: Path) -> Dict[int, Dict[str, str]]:
	rows = _clean_rows(_load_csv_rows(questionnaire_dir / "Eyes.csv"))
	by_participant: Dict[int, Dict[str, str]] = {}

	for row in rows:
		number = _extract_participant_number(row)
		if number is None:
			continue

		out: Dict[str, str] = {}
		for key, raw in row.items():
			if _normalize_key(key) in QUESTIONNAIRE_EXCLUDED_COLUMNS:
				continue
			out[f"Eye strain general {key}"] = raw
		by_participant[number] = out

	return by_participant


def _load_nasa_and_text_eyestrain(
	questionnaire_dir: Path,
	warnings: List[str],
) -> Dict[int, Dict[str, str]]:
	rows = _clean_rows(_load_csv_rows(questionnaire_dir / "NasaTLXandEyes.csv"))
	by_participant: Dict[int, Dict[str, Dict[str, str]]] = {}
	nasa_fields = [
		"How mentally demanding was the task?",
		"How Physically demanding was the task?",
		"How hurried or rushed was the pace of the task? - Sæt kun 1 markering",
		"How successful were you in acomplishing what you were asked to do?",
		"How hard did you have to work to accomplish your level of performance?",
		"How insecure, discouraged, irritated, stressed, and annoyed were you?",
	]
	nasa_fields_norm = {_normalize_key(x) for x in nasa_fields}

	for row in rows:
		number = _extract_participant_number(row)
		if number is None:
			continue

		text_raw = row.get("Which text did you just read?", "")
		text_label = TEXT_TO_TEXT_LABEL.get(text_raw.strip().lower())
		if not text_label:
			warnings.append(
				f"[NasaTLXandEyes] participant=P{number:03d} unknown text label \"{text_raw}\"; row skipped"
			)
			continue

		out_for_text = by_participant.setdefault(number, {}).setdefault(text_label, {})

		value_by_norm_key = {_normalize_key(k): v for k, v in row.items()}

		for field in nasa_fields:
			field_norm = _normalize_key(field)
			raw_for_field = value_by_norm_key.get(field_norm, "")
			numeric = _map_to_numeric(
				raw_value=raw_for_field,
				participant_id=f"P{number:03d}",
				file_label="NasaTLXandEyes",
				field_name=field,
				text_label=text_label,
				warnings=warnings,
			)
			out_for_text[f"NASA {field} \"{text_label}\""] = _format_number(numeric)

		nasa_values: List[float] = []
		for field in nasa_fields:
			v = _safe_float(out_for_text.get(f"NASA {field} \"{text_label}\""))
			if v is not None:
				nasa_values.append(v)
		out_for_text[f"NASA TLX overall \"{text_label}\""] = _format_number(
			(sum(nasa_values) / len(nasa_values)) if nasa_values else None
		)

		for key, raw in row.items():
			key_norm = _normalize_key(key)
			if key_norm in QUESTIONNAIRE_EXCLUDED_COLUMNS:
				continue
			if key_norm in nasa_fields_norm:
				continue
			if key_norm == _normalize_key("Fill in your participant number below"):
				continue
			if key_norm == _normalize_key("Which text did you just read?"):
				continue

			numeric = _map_to_numeric(
				raw_value=raw,
				participant_id=f"P{number:03d}",
				file_label="NasaTLXandEyes",
				field_name=key,
				text_label=text_label,
				warnings=warnings,
			)
			out_for_text[f"Text questionnaire {key} \"{text_label}\""] = _format_number(numeric)

	final: Dict[int, Dict[str, str]] = {}
	for number, per_text in by_participant.items():
		flattened: Dict[str, str] = {}
		for text_label, metrics in per_text.items():
			flattened.update(metrics)
		final[number] = flattened

	return final


def _collect_questionnaire_data(
	logs_root: Path,
	warnings: List[str],
) -> Dict[int, Dict[str, str]]:
	questionnaire_dir = logs_root / "Questionnaires"

	demo = _load_demographics(questionnaire_dir)
	eyes_general = _load_eyes_general(questionnaire_dir)
	nasa_and_text_eyes = _load_nasa_and_text_eyestrain(questionnaire_dir, warnings)

	participant_numbers = set(demo) | set(eyes_general) | set(nasa_and_text_eyes)
	merged: Dict[int, Dict[str, str]] = {}
	for number in participant_numbers:
		payload: Dict[str, str] = {}
		payload.update(demo.get(number, {}))
		payload.update(eyes_general.get(number, {}))
		payload.update(nasa_and_text_eyes.get(number, {}))
		merged[number] = payload

	return merged


def _find_session_dirs(logs_root: Path) -> Iterable[Tuple[str, str, Path]]:
	for participant_dir in sorted(logs_root.glob("P*")):
		if not participant_dir.is_dir():
			continue
		participant_id = participant_dir.name
		for session_dir in sorted(participant_dir.glob("S*")):
			if not session_dir.is_dir():
				continue
			session_id = session_dir.name
			yield participant_id, session_id, session_dir


def _build_reading_lookup(
	segments_rows: List[Dict[str, str]],
) -> Dict[str, Dict[str, Optional[float]]]:
	by_index: Dict[str, Dict[str, Any]] = {}

	for row in segments_rows:
		metrics_raw = row.get("metrics_json", "")
		try:
			metrics = json.loads(metrics_raw) if metrics_raw else {}
		except json.JSONDecodeError:
			metrics = {}

		name = row.get("segment_name", "")
		if name.startswith("reading_paragraph_"):
			idx = name.split("reading_paragraph_", 1)[1]
			by_index.setdefault(idx, {})
			by_index[idx]["paragraph_file"] = str(metrics.get("paragraph_file", "")).lower()
			by_index[idx]["condition"] = str(metrics.get("condition", "")).lower()
			by_index[idx]["reading_time_sec"] = _safe_float(metrics.get("reading_time_sec"))

		if name.startswith("mcq_reading") and name.endswith("-mcq"):
			idx = name.split("mcq_reading", 1)[1].split("-mcq", 1)[0]
			by_index.setdefault(idx, {})
			by_index[idx]["comprehension_pct"] = _safe_float(metrics.get("accuracy_pct"))

	lookup: Dict[str, Dict[str, Optional[float]]] = {}
	for idx_data in by_index.values():
		file_name = str(idx_data.get("paragraph_file", "")).lower()
		if not file_name:
			continue

		text_name = None
		for label, expected_file in TEXT_TO_FILE.items():
			if expected_file == file_name:
				text_name = label
				break

		if not text_name:
			continue

		lookup[text_name] = {
			"reading_time_sec": idx_data.get("reading_time_sec"),
			"comprehension_pct": idx_data.get("comprehension_pct"),
			"condition": idx_data.get("condition"),
			"paragraph_index": _safe_int(idx_data.get("paragraph_index")),
		}
	return lookup


def _extract_paragraph_window_labels(
	segments_rows: List[Dict[str, str]],
) -> Dict[str, str]:
	labels: Dict[str, str] = {}
	for row in segments_rows:
		name = row.get("segment_name", "")
		if not name.startswith("reading_paragraph_"):
			continue

		metrics_raw = row.get("metrics_json", "")
		try:
			metrics = json.loads(metrics_raw) if metrics_raw else {}
		except json.JSONDecodeError:
			metrics = {}

		paragraph_file = str(metrics.get("paragraph_file", "")).lower()
		for text_name, expected_file in TEXT_TO_FILE.items():
			if paragraph_file == expected_file:
				labels[text_name] = name
				break

	return labels


def _aggregate_eye_events(
	eye_events_rows: List[Dict[str, str]],
	window_labels_by_text: Dict[str, str],
) -> Dict[str, Dict[str, Dict[str, Optional[float]]]]:
	# text -> event_type -> {count, avg_duration_ms}
	result: Dict[str, Dict[str, Dict[str, Optional[float]]]] = {
		text: {
			event_type: {"count": 0, "duration_sum_ms": 0.0, "avg_duration_ms": None}
			for event_type in EVENT_TYPES
		}
		for text in TEXT_ORDER
	}

	label_to_text = {label: text for text, label in window_labels_by_text.items()}

	for row in eye_events_rows:
		window_label = row.get("window_label", "")
		text_name = label_to_text.get(window_label)
		if not text_name:
			continue

		event_type = row.get("event_type", "").strip().lower()
		if event_type not in EVENT_TYPES:
			continue

		duration_ms = _safe_float(row.get("duration_ms"))
		bucket = result[text_name][event_type]
		bucket["count"] = int(bucket["count"] or 0) + 1
		if duration_ms is not None:
			bucket["duration_sum_ms"] = float(bucket["duration_sum_ms"] or 0.0) + duration_ms

	for text_name in TEXT_ORDER:
		for event_type in EVENT_TYPES:
			bucket = result[text_name][event_type]
			count = int(bucket["count"] or 0)
			duration_sum = float(bucket["duration_sum_ms"] or 0.0)
			bucket["avg_duration_ms"] = (duration_sum / count) if count > 0 else None

	return result


def _aggregate_detectability(
	detectability_rows: List[Dict[str, str]],
) -> Dict[str, Optional[float]]:
	main_rows: List[Dict[str, str]] = []
	for row in detectability_rows:
		phase = str(row.get("phase", "")).strip().lower()
		is_main_block = str(row.get("is_main_block", "")).strip().lower()
		if phase == "practice":
			continue
		if is_main_block in {"true", "1", "yes"}:
			main_rows.append(row)

	result: Dict[str, Optional[float]] = {
		"correct_none": 0,
		"correct_full": 0,
		"correct_eyetracked": 0,
		"rt_avg_total": None,
		"rt_avg_none": None,
		"rt_avg_full": None,
		"rt_avg_eyetracked": None,
	}

	rt_by_condition: Dict[str, List[float]] = {c: [] for c in CONDITIONS}
	all_rt: List[float] = []

	for row in main_rows:
		condition = str(row.get("condition", "")).strip().lower()
		is_correct = str(row.get("is_correct", "")).strip().lower() == "true"
		rt_ms = _safe_float(row.get("rt_ms"))

		if condition in CONDITIONS:
			if is_correct:
				key = f"correct_{condition}"
				result[key] = int(result[key] or 0) + 1
			if rt_ms is not None:
				rt_by_condition[condition].append(rt_ms)

		if rt_ms is not None:
			all_rt.append(rt_ms)

	if all_rt:
		result["rt_avg_total"] = sum(all_rt) / len(all_rt)

	for condition in CONDITIONS:
		values = rt_by_condition[condition]
		result[f"rt_avg_{condition}"] = (sum(values) / len(values)) if values else None

	return result


def _build_reading_output_columns() -> List[str]:
	base_columns = [
		"Participant ID",
		"Session ID",
		"Condition",
		"Reading paragraph",
	]

	columns = list(base_columns)

	columns.extend(
		[
			"Saccade count",
			"Saccade avg duration",
			"Fixation count",
			"Fixation avg duration",
			"Blink count",
			"Blink avg duration",
			"Comprehension% (questions correct)",
			"Reading time",
		]
	)

	columns.extend(
		[
			"Detectability correct count condition=None",
			"Detectability correct count condition=Full",
			"Detectability correct count condition=Eyetracked",
			"Response time total avg MS",
			"Response time avg condition=None",
			"Response time avg condition=Full",
			"Response time avg condition=Eyetracked",
		]
	)

	return columns


def _build_condition_row(
	participant_id: str,
	session_id: str,
	condition: str,
	reading_lookup: Dict[str, Dict[str, Optional[float]]],
	eye_stats: Dict[str, Dict[str, Dict[str, Optional[float]]]],
	detectability: Dict[str, Optional[float]],
) -> Dict[str, Any]:
	matched_text: Optional[str] = None
	for text in TEXT_ORDER:
		text_condition = str(reading_lookup.get(text, {}).get("condition", "")).strip().lower()
		if text_condition == condition:
			matched_text = text
			break

	row: Dict[str, Any] = {
		"Participant ID": participant_id,
		"Session ID": session_id,
		"Condition": condition,
		"Reading paragraph": matched_text or "",
	}

	for event_name, event_key in (("Saccade", "saccade"), ("Fixation", "fixation"), ("Blink", "blink")):
		if matched_text is None:
			row[f"{event_name} count"] = ""
			row[f"{event_name} avg duration"] = ""
			continue

		stats = eye_stats.get(matched_text, {}).get(event_key, {})
		row[f"{event_name} count"] = str(int(stats.get("count") or 0))
		row[f"{event_name} avg duration"] = _format_number(_safe_float(stats.get("avg_duration_ms")))

	if matched_text is None:
		row["Comprehension% (questions correct)"] = ""
		row["Reading time"] = ""
	else:
		text_data = reading_lookup.get(matched_text, {})
		row["Comprehension% (questions correct)"] = _format_number(
			_safe_float(text_data.get("comprehension_pct"))
		)
		row["Reading time"] = _format_number(_safe_float(text_data.get("reading_time_sec")))

	row["Detectability correct count condition=None"] = str(int(detectability.get("correct_none") or 0))
	row["Detectability correct count condition=Full"] = str(int(detectability.get("correct_full") or 0))
	row["Detectability correct count condition=Eyetracked"] = str(int(detectability.get("correct_eyetracked") or 0))

	row["Response time total avg MS"] = _format_number(_safe_float(detectability.get("rt_avg_total")))
	row["Response time avg condition=None"] = _format_number(_safe_float(detectability.get("rt_avg_none")))
	row["Response time avg condition=Full"] = _format_number(_safe_float(detectability.get("rt_avg_full")))
	row["Response time avg condition=Eyetracked"] = _format_number(
		_safe_float(detectability.get("rt_avg_eyetracked"))
	)

	return row


def build_reading_dataset(logs_root: Path) -> List[Dict[str, Any]]:
	rows: List[Dict[str, Any]] = []

	for participant_id, session_id, session_dir in _find_session_dirs(logs_root):
		segments_rows = _load_csv_rows(session_dir / "segments.csv")
		eye_events_rows = _load_csv_rows(session_dir / "eye_events.csv")
		detectability_rows = _load_csv_rows(session_dir / "detectability_trials.csv")

		if not segments_rows:
			continue

		reading_lookup = _build_reading_lookup(segments_rows)
		window_labels_by_text = _extract_paragraph_window_labels(segments_rows)
		eye_stats = _aggregate_eye_events(eye_events_rows, window_labels_by_text)
		detectability = _aggregate_detectability(detectability_rows)

		for condition in CONDITIONS:
			rows.append(
				_build_condition_row(
					participant_id=participant_id,
					session_id=session_id,
					condition=condition,
					reading_lookup=reading_lookup,
					eye_stats=eye_stats,
					detectability=detectability,
				)
			)

	return rows


def build_questionnaire_dataset(
	logs_root: Path,
) -> Tuple[List[Dict[str, Any]], List[str]]:
	warnings: List[str] = []
	questionnaire_by_participant = _collect_questionnaire_data(logs_root, warnings)
	rows: List[Dict[str, Any]] = []

	for participant_number in sorted(questionnaire_by_participant.keys()):
		payload = questionnaire_by_participant[participant_number]
		row: Dict[str, Any] = {
			"Participant ID": _participant_id_from_number(participant_number),
			"Participant number": str(participant_number),
		}
		row.update(payload)
		rows.append(row)

	return rows, warnings


def write_reading_csv(rows: List[Dict[str, Any]], output_path: Path) -> None:
	columns = _build_reading_output_columns()
	extra_columns = sorted({k for row in rows for k in row.keys() if k not in columns})
	columns.extend(extra_columns)
	output_path.parent.mkdir(parents=True, exist_ok=True)

	with output_path.open("w", encoding="utf-8", newline="") as f:
		writer = csv.DictWriter(f, fieldnames=columns)
		writer.writeheader()
		for row in rows:
			writer.writerow(row)


def write_questionnaire_csv(rows: List[Dict[str, Any]], output_path: Path) -> None:
	columns = ["Participant ID", "Participant number"]
	extra_columns = sorted({k for row in rows for k in row.keys() if k not in columns})
	columns.extend(extra_columns)
	output_path.parent.mkdir(parents=True, exist_ok=True)

	with output_path.open("w", encoding="utf-8", newline="") as f:
		writer = csv.DictWriter(f, fieldnames=columns)
		writer.writeheader()
		for row in rows:
			writer.writerow(row)


def main() -> None:
	parser = argparse.ArgumentParser(
		description=(
			"Build participant/session condition-level CSV from logs/PXXX/SXX. "
			"Outputs one row per condition (none/full/eyetracked) per session."
		)
	)
	parser.add_argument(
		"--logs-root",
		type=Path,
		default=Path("logs"),
		help="Root logs directory containing participant folders (default: logs)",
	)
	parser.add_argument(
		"--output",
		type=Path,
		default=Path("analysis") / "aggregated_participant_condition_metrics.csv",
		help="[Deprecated] Backward-compatibility alias for --reading-output",
	)
	parser.add_argument(
		"--reading-output",
		type=Path,
		default=Path("analysis") / "aggregated_reading_eye_metrics.csv",
		help="Output CSV path for reading comprehension + eye metrics",
	)
	parser.add_argument(
		"--questionnaire-output",
		type=Path,
		default=Path("analysis") / "aggregated_questionnaire_metrics.csv",
		help="Output CSV path for questionnaire data (one row per participant)",
	)
	args = parser.parse_args()

	reading_output_path = args.reading_output
	if args.output != Path("analysis") / "aggregated_participant_condition_metrics.csv":
		reading_output_path = args.output

	reading_rows = build_reading_dataset(args.logs_root)
	questionnaire_rows, warnings = build_questionnaire_dataset(args.logs_root)

	write_reading_csv(reading_rows, reading_output_path)
	write_questionnaire_csv(questionnaire_rows, args.questionnaire_output)

	if warnings:
		print("\nQuestionnaire value warnings (please verify):")
		for msg in warnings:
			print(f"- {msg}")

	print(f"Wrote {len(reading_rows)} rows to {reading_output_path}")
	print(f"Wrote {len(questionnaire_rows)} rows to {args.questionnaire_output}")


if __name__ == "__main__":
	main()
