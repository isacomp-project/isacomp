#!/usr/bin/env python3
"""
Run 8086 tests in batches to avoid hanging
"""

import subprocess
import sys
from pathlib import Path

# Get project root and script directory
script_dir = Path(__file__).parent
project_root = script_dir.parent.parent

# Import the test cases from the main test file
from run_multiple_8086_tests import test_cases

def run_batch(tests, batch_num, total_batches):
    """Run a batch of tests"""
    print(f"\n{'='*70}")
    print(f"BATCH {batch_num}/{total_batches}: Testing {len(tests)} files")
    print(f"{'='*70}\n")

    passed = 0
    failed = 0
    failures = []

    for i, (isa_file, test_data, test_name) in enumerate(tests, 1):
        print(f"[{i}/{len(tests)}] {test_name}...", end=" ", flush=True)

        try:
            result = subprocess.run(
                ["python3", str(script_dir / "run_8086_json_test.py"), isa_file, test_data],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=project_root
            )

            if result.returncode == 0 and "TEST PASSED" in result.stdout:
                print("✓")
                passed += 1
            else:
                print("✗ FAILED")
                failed += 1
                failures.append((test_name, isa_file))
        except subprocess.TimeoutExpired:
            print("✗ TIMEOUT")
            failed += 1
            failures.append((test_name, isa_file))
        except Exception as e:
            print(f"✗ ERROR: {e}")
            failed += 1
            failures.append((test_name, isa_file))

    return passed, failed, failures

# Run tests in batches
batch_size = 50
total_tests = len(test_cases)
num_batches = (total_tests + batch_size - 1) // batch_size

total_passed = 0
total_failed = 0
all_failures = []

for batch_num in range(1, num_batches + 1):
    start_idx = (batch_num - 1) * batch_size
    end_idx = min(start_idx + batch_size, total_tests)
    batch = test_cases[start_idx:end_idx]

    passed, failed, failures = run_batch(batch, batch_num, num_batches)
    total_passed += passed
    total_failed += failed
    all_failures.extend(failures)

    print(f"\nBatch {batch_num} summary: {passed} passed, {failed} failed")

# Final summary
print(f"\n{'='*70}")
print(f"FINAL SUMMARY: {total_passed} passed, {total_failed} failed out of {total_tests} tests")
print(f"{'='*70}")

if all_failures:
    print(f"\nFailed tests ({len(all_failures)}):")
    for test_name, isa_file in all_failures:
        print(f"  - {test_name} ({isa_file})")

sys.exit(0 if total_failed == 0 else 1)
