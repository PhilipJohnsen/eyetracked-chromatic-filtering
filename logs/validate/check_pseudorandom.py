#!/usr/bin/env python
"""Verify pseudorandom distribution of detectability trials across 24 participants."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiment_helper.scheduling_experiment import prepare_session_order
from experiment_helper.content_loading_experiment import ContentLoader

BASE_DIR = REPO_ROOT

# Use same config as ParticipantTest.py
PRACTICE_PARAGRAPH_FILE = "generations.txt"
DETECTABILITY_TEST_TRIALS = 6
DETECTABILITY_BLOCK_TRIALS = 12
DETECTABILITY_BLOCK_COUNT = 3
DETECTABILITY_TOTAL_TRIALS = DETECTABILITY_TEST_TRIALS + (DETECTABILITY_BLOCK_TRIALS * DETECTABILITY_BLOCK_COUNT)

CONTENT_LOADER = ContentLoader(
    base_dir=BASE_DIR,
    practice_paragraph_file=PRACTICE_PARAGRAPH_FILE,
    detectability_test_trials=DETECTABILITY_TEST_TRIALS,
    detectability_block_trials=DETECTABILITY_BLOCK_TRIALS,
    detectability_block_count=DETECTABILITY_BLOCK_COUNT,
)
CONTENT_BUNDLE = CONTENT_LOADER.load()

FILTER_CONDITIONS = ["none", "full", "eyetracked"]
from itertools import permutations
LATIN_FILTER_ORDERS = [list(p) for p in permutations(FILTER_CONDITIONS)]

# Simulate for 24 participants
trial_sets = {}
condition_counts = {i: {'none': 0, 'full': 0, 'eyetracked': 0} for i in range(1, 25)}

for pid in range(1, 25):
    latin_idx = (pid - 1) % len(LATIN_FILTER_ORDERS)
    
    session_order = prepare_session_order(
        participant_number=pid,
        latin_variant_index=latin_idx,
        paragraph_files=CONTENT_BUNDLE.paragraph_text_map.keys(),
        practice_paragraph_file=PRACTICE_PARAGRAPH_FILE,
        detectability_trial_map=CONTENT_BUNDLE.detectability_trial_map,
        detectability_test_trials=DETECTABILITY_TEST_TRIALS,
        detectability_block_trials=DETECTABILITY_BLOCK_TRIALS,
        detectability_block_count=DETECTABILITY_BLOCK_COUNT,
        detectability_total_trials=DETECTABILITY_TOTAL_TRIALS,
        filter_conditions=FILTER_CONDITIONS,
        latin_filter_orders=LATIN_FILTER_ORDERS,
    )
    
    trial_files = session_order['practice_trial_files'] + [f for block in session_order['block_trial_files'] for f in block]
    trial_sets[pid] = trial_files
    
    # Count conditions per participant (main blocks only)
    main_filters = []
    for block_filters in session_order['block_filter_orders']:
        main_filters.extend(block_filters)
    
    for cond in FILTER_CONDITIONS:
        condition_counts[pid][cond] = main_filters.count(cond)

# Check consistency
print("=== TRIAL TEXT DISTRIBUTION ===")
print(f"P001 practice trial order: {trial_sets[1][:6]}")
print(f"P002 practice trial order: {trial_sets[2][:6]}")
print(f"P007 practice trial order: {trial_sets[7][:6]}")

# Are practice trials different per participant?
practice_orders_unique = len(set(tuple(trial_sets[p][:6]) for p in range(1, 25)))
print(f"\nUnique practice trial orders (out of 24): {practice_orders_unique}")

# Check block trials
print(f"\nP001 block 1 trials: {trial_sets[1][6:18]}")
print(f"P002 block 1 trials: {trial_sets[2][6:18]}")

block1_unique = len(set(tuple(trial_sets[p][6:18]) for p in range(1, 25)))
print(f"Unique block 1 trial orders (out of 24): {block1_unique}")

# Check all 36 main trials
main_unique = len(set(tuple(trial_sets[p][6:42]) for p in range(1, 25)))
print(f"Unique main trial sequences (out of 24): {main_unique}")

print("\n=== CONDITION DISTRIBUTION (MAIN BLOCKS ONLY) ===")
all_balanced = True
for cond in FILTER_CONDITIONS:
    counts = [condition_counts[p][cond] for p in range(1, 25)]
    print(f"{cond:12s}: ", end="")
    expected = 12
    if all(c == expected for c in counts):
        print(f"✓ All participants have exactly {expected} trials")
    else:
        print(f"✗ IMBALANCED: {counts}")
        all_balanced = False

if all_balanced:
    print("\n✓ PERFECT BALANCE: All conditions have exactly 12 trials per participant")
else:
    print("\n✗ CONDITIONS NOT BALANCED")

print("\n=== LATIN SQUARE DISTRIBUTION (24 PARTICIPANTS) ===")
latin_variants = {}
for pid in range(1, 25):
    latin_idx = (pid - 1) % len(LATIN_FILTER_ORDERS)
    variant = latin_idx
    latin_variants[variant] = latin_variants.get(variant, 0) + 1

all_equal = True
for var in range(6):
    count = latin_variants.get(var, 0)
    status = "✓" if count == 4 else "✗"
    print(f"Latin variant {var}: {count} participants (expected 4) {status}")
    if count != 4:
        all_equal = False

if all_equal and len(latin_variants) == 6:
    print("\n✓ PERFECT DISTRIBUTION: All 6 Latin square variants used equally")
else:
    print("\n✗ LATIN SQUARE NOT PROPERLY DISTRIBUTED")

print("\n=== SUMMARY ===")
print(f"Configuration: {DETECTABILITY_BLOCK_COUNT} blocks × {DETECTABILITY_BLOCK_TRIALS} trials/block = {DETECTABILITY_BLOCK_COUNT * DETECTABILITY_BLOCK_TRIALS} main trials")
print(f"           +  {DETECTABILITY_TEST_TRIALS} practice trials = {DETECTABILITY_TOTAL_TRIALS} total")
print(f"Conditions: {len(FILTER_CONDITIONS)} ({', '.join(FILTER_CONDITIONS)})")
print(f"Expected per condition: {DETECTABILITY_BLOCK_TRIALS * DETECTABILITY_BLOCK_COUNT // len(FILTER_CONDITIONS)}")
