from __future__ import annotations

from itertools import permutations
import random
from typing import Iterable


def build_practice_trial_file_names(detectability_test_trials: int) -> list[str]:
    return [f"trial_{idx:02d}.txt" for idx in range(1, detectability_test_trials + 1)]


def build_main_trial_file_names(
    detectability_test_trials: int,
    detectability_total_trials: int,
) -> list[str]:
    start = detectability_test_trials + 1
    return [f"trial_{idx:02d}.txt" for idx in range(start, detectability_total_trials + 1)]


def reading_cycle_orders(
    paragraph_files: Iterable[str],
    practice_paragraph_file: str,
) -> list[list[str]]:
    files = sorted(str(name) for name in paragraph_files)
    if practice_paragraph_file not in files:
        raise ValueError(
            f"Practice paragraph '{practice_paragraph_file}' is not available in loaded paragraph texts"
        )

    main_candidates = [name for name in files if name != practice_paragraph_file]
    if len(main_candidates) < 3:
        raise ValueError("Reading counterbalancing requires at least 3 non-practice paragraphs")

    main_set = main_candidates[:3]
    return [list(order) for order in permutations(main_set)]


def build_paragraph_order(
    participant_number: int,
    paragraph_files: Iterable[str],
    practice_paragraph_file: str,
) -> list[str]:
    cycle_orders = reading_cycle_orders(paragraph_files, practice_paragraph_file)
    order_index = (participant_number - 1) % len(cycle_orders)
    return [practice_paragraph_file] + cycle_orders[order_index]


def build_latin_filter_order(
    n_trials: int,
    latin_filter_orders: list[list[str]],
    latin_variant_index: int,
    *,
    block_offset: int = 0,
) -> list[str]:
    base = latin_filter_orders[latin_variant_index][:]
    if block_offset:
        shift = block_offset % len(base)
        base = base[shift:] + base[:shift]

    sequence: list[str] = []
    while len(sequence) < n_trials:
        sequence.extend(base)
    return sequence[:n_trials]


def validate_counterbalancing_matrix(
    *,
    max_participant: int,
    paragraph_files: Iterable[str],
    practice_paragraph_file: str,
    latin_filter_orders: list[list[str]],
) -> None:
    if max_participant < 6:
        raise ValueError("Counterbalancing validation requires at least 6 participants")
    if max_participant % 6 != 0:
        raise ValueError("Counterbalancing validation max_participant must be divisible by 6")

    cycle_orders = reading_cycle_orders(paragraph_files, practice_paragraph_file)
    for cycle_start in range(1, max_participant + 1, 6):
        reading_orders = {
            tuple(cycle_orders[(pid - 1) % 6])
            for pid in range(cycle_start, cycle_start + 6)
        }
        if len(reading_orders) != 6:
            raise ValueError(
                f"Reading counterbalancing failed for participants {cycle_start}-{cycle_start + 5}"
            )

        latin_orders = {
            tuple(latin_filter_orders[(pid - 1) % len(latin_filter_orders)])
            for pid in range(cycle_start, cycle_start + 6)
        }
        if len(latin_orders) != 6:
            raise ValueError(
                f"Latin-order counterbalancing failed for participants {cycle_start}-{cycle_start + 5}"
            )


def build_counterbalancing_report_lines(
    *,
    participant_number: int,
    latin_variant_index: int,
    session_order: dict[str, object],
    max_participant: int,
    paragraph_files: Iterable[str],
    practice_paragraph_file: str,
    latin_filter_orders: list[list[str]],
) -> list[str]:
    cycle_orders = reading_cycle_orders(paragraph_files, practice_paragraph_file)
    reading_order_index = int(session_order.get("reading_order_index", -1))
    main_filter_counts = dict(session_order.get("main_filter_counts", {}))

    lines: list[str] = []
    lines.append("[counterbalance] participant schedule")
    lines.append(
        "[counterbalance] participant="
        f"{participant_number} "
        f"reading_order_index={reading_order_index + 1}/6 "
        f"reading_order={session_order.get('comprehension_paragraphs', [])} "
        f"latin_variant={latin_variant_index + 1}/6 "
        f"main_detectability_counts={main_filter_counts}"
    )

    expected_repetitions = max_participant // len(latin_filter_orders)

    latin_counts: dict[tuple[str, ...], int] = {
        tuple(order): 0 for order in latin_filter_orders
    }
    reading_counts: dict[tuple[str, ...], int] = {
        tuple(order): 0 for order in cycle_orders
    }

    for pid in range(1, max_participant + 1):
        latin_order = tuple(latin_filter_orders[(pid - 1) % len(latin_filter_orders)])
        reading_order = tuple(cycle_orders[(pid - 1) % len(cycle_orders)])
        latin_counts[latin_order] = latin_counts.get(latin_order, 0) + 1
        reading_counts[reading_order] = reading_counts.get(reading_order, 0) + 1

    latin_ok = all(count == expected_repetitions for count in latin_counts.values())
    order_ok = all(count == expected_repetitions for count in reading_counts.values())

    lines.append(f"\n[counterbalance] Latin-balanced for {max_participant}: {latin_ok}")
    for order, count in sorted(latin_counts.items()):
        lines.append(f"[counterbalance]   latin_order={list(order)} count={count}")

    lines.append(f"[counterbalance] Order-balanced for {max_participant}: {order_ok}")
    for order, count in sorted(reading_counts.items()):
        lines.append(f"[counterbalance]   reading_order={list(order)} count={count}")

    return lines


def prepare_session_order(
    *,
    participant_number: int,
    latin_variant_index: int,
    paragraph_files: Iterable[str],
    practice_paragraph_file: str,
    detectability_trial_map: dict[str, str],
    detectability_test_trials: int,
    detectability_block_trials: int,
    detectability_block_count: int,
    detectability_total_trials: int,
    filter_conditions: list[str],
    latin_filter_orders: list[list[str]],
) -> dict[str, object]:
    paragraph_order = build_paragraph_order(
        participant_number,
        paragraph_files,
        practice_paragraph_file,
    )

    comprehension_paragraphs = [name for name in paragraph_order if name != practice_paragraph_file][:3]
    if len(comprehension_paragraphs) != 3:
        raise ValueError(
            f"Reading counterbalancing requires exactly 3 main paragraphs; found {len(comprehension_paragraphs)}"
        )
    reading_order_index = (participant_number - 1) % 6

    practice_trial_names = build_practice_trial_file_names(detectability_test_trials)
    main_trial_names = build_main_trial_file_names(detectability_test_trials, detectability_total_trials)
    required_trials = practice_trial_names + main_trial_names

    available_trials = set(detectability_trial_map.keys())
    missing = [name for name in required_trials if name not in available_trials]
    if missing:
        raise ValueError(
            f"Missing required detectability trial files ({len(missing)}): {', '.join(missing)}"
        )

    practice_trial_ids = [name for name in practice_trial_names if name in available_trials]

    block_trial_id_sets: list[list[str]] = []
    for block_idx in range(detectability_block_count):
        block_start = detectability_test_trials + (block_idx * detectability_block_trials) + 1
        block_end = block_start + detectability_block_trials - 1
        block_ids = [
            f"trial_{idx:02d}.txt"
            for idx in range(block_start, block_end + 1)
            if f"trial_{idx:02d}.txt" in available_trials
        ]
        block_trial_id_sets.append(block_ids)

    practice_filter_assignment = build_latin_filter_order(
        len(practice_trial_ids),
        latin_filter_orders,
        latin_variant_index,
        block_offset=0,
    )
    block_filter_assignments = [
        build_latin_filter_order(
            len(block_ids),
            latin_filter_orders,
            latin_variant_index,
            block_offset=block_idx,
        )
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

    practice_trial_files = practice_trial_ids[:]
    practice_rng = random.Random(2100 + participant_number)
    practice_rng.shuffle(practice_trial_files)
    practice_filter_order = [practice_trial_to_filter[name] for name in practice_trial_files]

    block_trial_files: list[list[str]] = []
    block_filter_orders: list[list[str]] = []
    for block_idx, block_ids in enumerate(block_trial_id_sets):
        shown_ids = block_ids[:]
        block_rng = random.Random(3100 + participant_number + block_idx)
        block_rng.shuffle(shown_ids)
        block_trial_files.append(shown_ids)
        block_filter_orders.append([block_trial_to_filter[block_idx][name] for name in shown_ids])

    expected_per_condition = (detectability_block_trials * detectability_block_count) // len(filter_conditions)
    all_main_filters = [cond for order in block_filter_orders for cond in order]
    main_filter_counts = {cond: all_main_filters.count(cond) for cond in filter_conditions}
    if any(main_filter_counts.get(cond, 0) != expected_per_condition for cond in filter_conditions):
        raise ValueError(
            "Detectability counterbalancing failed: expected "
            f"{expected_per_condition} trials per condition, got {main_filter_counts}"
        )

    combined_trials: list[tuple[str, str, str]] = []
    for trial_name in practice_trial_files:
        text = detectability_trial_map.get(trial_name, "")
        condition = practice_trial_to_filter.get(trial_name, "none")
        if text:
            combined_trials.append((trial_name, text, condition))

    for block_idx, shown_ids in enumerate(block_trial_files):
        mapping = block_trial_to_filter[block_idx]
        for trial_name in shown_ids:
            text = detectability_trial_map.get(trial_name, "")
            condition = mapping.get(trial_name, "none")
            if text:
                combined_trials.append((trial_name, text, condition))

    return {
        "participant_number": participant_number,
        "reading_order_index": reading_order_index,
        "latin_variant_index": latin_variant_index,
        "paragraph_order": paragraph_order,
        "practice_paragraph": practice_paragraph_file,
        "comprehension_paragraphs": comprehension_paragraphs,
        "practice_trial_id_set": practice_trial_ids,
        "block_trial_id_sets": block_trial_id_sets,
        "practice_trial_files": practice_trial_files,
        "block_trial_files": block_trial_files,
        "practice_filter_assignment": practice_filter_assignment,
        "block_filter_assignments": block_filter_assignments,
        "practice_filter_order": practice_filter_order,
        "block_filter_orders": block_filter_orders,
        "main_filter_counts": main_filter_counts,
        "combined_trials": combined_trials,
    }
