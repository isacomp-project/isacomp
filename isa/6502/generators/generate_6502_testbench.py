#!/usr/bin/env python3
"""
Generate 6502 testbench using the enhanced testbench generator.
"""

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from backends.verilog.verilog_testbench_generator import TestbenchConfig, generate_testbench_files

# Configuration for 6502
config = TestbenchConfig(
    module_name="cpu_6502_test",
    clock_period=10,  # 10ns = 100MHz
    reset_cycles=5,
    timeout_cycles=100000,  # Increase timeout for functional test
    # Memory configuration
    imem_name="imem",
    imem_addr_width=16,  # 6502 has 16-bit address space
    imem_data_width=8,   # 6502 has 8-bit data
    dmem_name="dmem",    # 6502 uses same memory for data
    dmem_addr_width=16,
    dmem_data_width=8,
    # Processor interface signals
    pc_signal_name="pc_rd",
    pc_width=16,  # 6502 has 16-bit PC
    reset_pc_signal="reset_pc_rd",
    reset_pc_value=0x0400,  # Klaus Dormann test starts at 0x0400
    # Test file format
    test_file_format="bin",  # 6502 functional test is binary, not ELF
    bin_load_offset=0,  # Load entire 64KB image
    # Completion detection
    detect_pc_stall=True,  # Detect JMP * infinite loop
    pc_stall_cycles=10,     # PC must be stuck for 10 cycles
)

# Generate testbench and FuseSoC core files
rtl_file = project_root / "examples/verilog/6502_test/6502_test.v"
output_dir = project_root / "examples/verilog/6502_test"

files = generate_testbench_files(
    module_name="cpu_6502_test",
    rtl_file=str(rtl_file),
    output_dir=output_dir,
    config=config
)

print(f"Generated testbench: {files['testbench']}")
print(f"Generated core file: {files['core']}")
print("\nTo run the test:")
print("  fusesoc run --target=sim isacomp:cpu_6502_test:1.0.0 \\")
print("    --bin_load=isa/6502/6502_65C02_functional_tests/bin_files/6502_functional_test.bin")
