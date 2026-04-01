#!/usr/bin/env python3
"""Set up and run tests for all 6502 variants.

This script:
1. Converts Klaus Dormann test binaries to Verilog hex format
2. Copies testbench files to each variant directory
3. Runs tests using iverilog simulation

Usage:
    python3 test_all_variants.py [--variant NAME]  # Test specific variant
    python3 test_all_variants.py --setup-only      # Just set up, don't run
    python3 test_all_variants.py                   # Test all variants
"""

import sys
import os
import shutil
import subprocess
from pathlib import Path

# All 6502 variants
VARIANTS = {
    '6502': {
        'module': 'cpu_6502_test',
        'test_bin': '6502_functional_test.bin',
        'has_bcd': True,
        'has_65c02': False,
    },
    '2a03': {
        'module': 'cpu_2a03_test',
        'test_bin': '6502_functional_test.bin',  # Same test, but BCD parts will work differently
        'has_bcd': False,
        'has_65c02': False,
    },
    '65c02': {
        'module': 'cpu_65c02_test',
        'test_bin': '65C02_extended_opcodes_test.bin',  # Tests 65C02 extended opcodes
        'has_bcd': True,
        'has_65c02': True,
    },
    '65sc02': {
        'module': 'cpu_65sc02_test',
        'test_bin': '65C02_extended_opcodes_test.bin',
        'has_bcd': True,
        'has_65c02': True,
    },
    '6510': {
        'module': 'cpu_6510_test',
        'test_bin': '6502_functional_test.bin',
        'has_bcd': True,
        'has_65c02': False,
    },
    '6507': {
        'module': 'cpu_6507_test',
        'test_bin': '6502_functional_test.bin',
        'has_bcd': True,
        'has_65c02': False,
    },
}

def bin_to_hex(bin_path: Path, hex_path: Path):
    """Convert binary file to Verilog hex format."""
    with open(bin_path, 'rb') as f:
        data = f.read()

    with open(hex_path, 'w') as f:
        for byte in data:
            f.write(f'{byte:02x}\n')

    # Pad to 64KB if smaller
    remaining = 65536 - len(data)
    if remaining > 0:
        with open(hex_path, 'a') as f:
            for _ in range(remaining):
                f.write('00\n')

    print(f"  Created {hex_path} ({len(data)} bytes)")

def setup_variant(variant_name: str, project_root: Path):
    """Set up test infrastructure for a variant."""
    config = VARIANTS[variant_name]
    variant_dir = project_root / 'examples' / 'verilog' / f'{variant_name}_test'
    template_dir = project_root / 'examples' / 'verilog' / '6502_test'
    test_bin_dir = project_root / '6502' / '6502_65C02_functional_tests'

    print(f"\nSetting up {variant_name}...")

    # Check if variant directory exists
    if not variant_dir.exists():
        print(f"  ERROR: {variant_dir} does not exist. Run regen_{variant_name}.py first.")
        return False

    # Check if generated Verilog exists
    verilog_file = variant_dir / f'{variant_name}_test.v'
    if not verilog_file.exists():
        print(f"  ERROR: {verilog_file} does not exist. Run regen_{variant_name}.py first.")
        return False

    # Convert test binary to hex
    test_bin = test_bin_dir / config['test_bin']
    if test_bin.exists():
        hex_file = variant_dir / 'imem.hex'
        bin_to_hex(test_bin, hex_file)
    else:
        print(f"  WARNING: {test_bin} not found. Skipping hex conversion.")

    # Copy testbench files (adapting for variant)
    files_to_copy = [
        '6502_dpi.c',
        'fake6502_wrapper.c',
        'main.cpp',
        'Makefile.fake6502',
        'count_cycles.c',
        'test_cycles.c',
        'make_checkpoint.c',
    ]

    for filename in files_to_copy:
        src = template_dir / filename
        dst = variant_dir / filename
        if src.exists() and not dst.exists():
            shutil.copy(src, dst)
            print(f"  Copied {filename}")

    # Create variant-specific testbench
    create_testbench(variant_name, config, variant_dir, template_dir)

    # Create variant-specific build script
    create_build_script(variant_name, config, variant_dir)

    # Create variant-specific run script
    create_run_script(variant_name, config, variant_dir)

    return True

def create_testbench(variant_name: str, config: dict, variant_dir: Path, template_dir: Path):
    """Create a variant-specific testbench by adapting the template."""
    template_tb = template_dir / 'cpu_6502_test_tb_verilator.sv'
    output_tb = variant_dir / f'{config["module"]}_tb_verilator.sv'

    if not template_tb.exists():
        print(f"  WARNING: Template testbench not found")
        return

    with open(template_tb, 'r') as f:
        content = f.read()

    # Replace module names
    content = content.replace('cpu_6502_test_tb', f'{config["module"]}_tb')
    content = content.replace('cpu_6502_test', config['module'])

    # For 2A03 (no BCD), we might want to skip BCD-specific tests
    # The test should still run, just the BCD results will differ

    with open(output_tb, 'w') as f:
        f.write(content)

    print(f"  Created {output_tb.name}")

def create_build_script(variant_name: str, config: dict, variant_dir: Path):
    """Create a variant-specific Verilator build script."""
    script_path = variant_dir / 'build_verilator.sh'

    content = f'''#!/bin/bash
# Build script for {variant_name} co-simulation testbench using Verilator

set -e

echo "Building {variant_name} co-simulation testbench..."

verilator --cc --exe --build --timing \\
    --top-module {config['module']}_tb \\
    -Wall -Wno-fatal \\
    {variant_name}_test.v \\
    {config['module']}_tb_verilator.sv \\
    6502_dpi.c \\
    fake6502_wrapper.c \\
    main.cpp \\
    -CFLAGS "-I."

echo ""
echo "Build complete! Run with: ./obj_dir/V{config['module']}_tb"
'''

    with open(script_path, 'w') as f:
        f.write(content)

    script_path.chmod(0o755)
    print(f"  Created build_verilator.sh")

def create_run_script(variant_name: str, config: dict, variant_dir: Path):
    """Create a variant-specific run script for iverilog."""
    script_path = variant_dir / 'run_test.sh'

    # Dormann test addresses
    pass_addr = '3469'
    fail_addr = '3463'

    content = f'''#!/bin/bash
# Run {variant_name} test using iverilog

echo "Running {variant_name} test..."

# Check if processor exists
if [ ! -f "{variant_name}_test.v" ]; then
    echo "ERROR: {variant_name}_test.v not found. Generate processor first."
    exit 1
fi

# Check for test hex file
if [ ! -f "imem.hex" ]; then
    echo "ERROR: imem.hex not found. Run test_all_variants.py --setup-only first."
    exit 1
fi

# Compile with iverilog
echo "Compiling..."
iverilog -g2012 -o sim {variant_name}_test.v {config['module']}_tb_verilator.sv 2>&1 | grep -i error || true

if [ ! -f "sim" ]; then
    echo "ERROR: Compilation failed"
    exit 1
fi

# Run simulation (timeout after 120 seconds)
echo "Running simulation..."
timeout 120 vvp sim 2>&1 | tee test_output.log

# Check results
if grep -q "TEST PASSED" test_output.log; then
    echo "✅ {variant_name.upper()} TEST PASSED"
    exit 0
elif grep -q "MISMATCH" test_output.log; then
    echo "❌ {variant_name.upper()} CO-SIMULATION MISMATCH"
    tail -20 test_output.log
    exit 1
else
    echo "❌ {variant_name.upper()} TEST INCOMPLETE"
    tail -20 test_output.log
    exit 1
fi
'''

    with open(script_path, 'w') as f:
        f.write(content)

    script_path.chmod(0o755)
    print(f"  Created run_test.sh")

def run_variant_test(variant_name: str, project_root: Path) -> bool:
    """Run test for a specific variant."""
    config = VARIANTS[variant_name]
    variant_dir = project_root / 'examples' / 'verilog' / f'{variant_name}_test'

    print(f"\n{'='*60}")
    print(f"Testing {variant_name.upper()}")
    print(f"{'='*60}")

    # Check if Verilator is available
    try:
        subprocess.run(['verilator', '--version'], capture_output=True, check=True)
        has_verilator = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        has_verilator = False
        print("  Verilator not available, skipping co-simulation test")

    if has_verilator:
        # Build with Verilator
        build_script = variant_dir / 'build_verilator.sh'
        if build_script.exists():
            print("  Building with Verilator...")
            result = subprocess.run(
                ['bash', str(build_script)],
                cwd=variant_dir,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                print(f"  Build failed: {result.stderr}")
                return False

            # Run the test
            exe = variant_dir / 'obj_dir' / f'V{config["module"]}_tb'
            if exe.exists():
                print("  Running Verilator simulation...")
                result = subprocess.run(
                    [str(exe)],
                    cwd=variant_dir,
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 minute timeout
                )
                print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
                if 'TEST PASSED' in result.stdout:
                    print(f"  ✅ {variant_name.upper()} PASSED")
                    return True
                elif 'MISMATCH' in result.stdout or 'MISMATCH' in result.stderr:
                    print(f"  ❌ {variant_name.upper()} MISMATCH")
                    return False

    return False

def main():
    project_root = Path(__file__).parent.parent.parent.parent  # isa/6502/test -> 6502 -> isa -> project root

    # Parse arguments
    setup_only = '--setup-only' in sys.argv
    specific_variant = None
    for arg in sys.argv[1:]:
        if arg.startswith('--variant='):
            specific_variant = arg.split('=')[1]
        elif arg == '--variant' and len(sys.argv) > sys.argv.index(arg) + 1:
            specific_variant = sys.argv[sys.argv.index(arg) + 1]

    variants_to_test = [specific_variant] if specific_variant else list(VARIANTS.keys())

    print("="*60)
    print("6502 Variant Test Suite")
    print("="*60)

    # Setup phase
    for variant in variants_to_test:
        if variant not in VARIANTS:
            print(f"Unknown variant: {variant}")
            print(f"Available: {', '.join(VARIANTS.keys())}")
            sys.exit(1)
        setup_variant(variant, project_root)

    if setup_only:
        print("\nSetup complete. Run without --setup-only to execute tests.")
        return

    # Test phase
    results = {}
    for variant in variants_to_test:
        try:
            results[variant] = run_variant_test(variant, project_root)
        except Exception as e:
            print(f"  Error testing {variant}: {e}")
            results[variant] = False

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    for variant, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"  {variant:10s}: {status}")

    # Exit with error if any failed
    if not all(results.values()):
        sys.exit(1)

if __name__ == '__main__':
    main()
