#!/usr/bin/env python3
"""
Generate 8086 testbench using the enhanced testbench generator.
"""

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from backends.verilog.verilog_testbench_generator import TestbenchConfig, generate_testbench_files

# Configuration for 8086
config = TestbenchConfig(
    module_name="cpu_8086_test",
    clock_period=10,  # 10ns = 100MHz
    reset_cycles=5,
    timeout_cycles=100000,  # Increase timeout for comprehensive tests
    # Memory configuration
    imem_name="imem",
    imem_addr_width=16,  # 8086 has 20-bit physical address space, but we use 16-bit here
    imem_data_width=8,   # 8086 has 8-bit memory interface
    dmem_name="dmem",    # 8086 uses same memory for data
    dmem_addr_width=16,
    dmem_data_width=8,
    # Processor interface signals
    pc_signal_name="ip",  # 8086 uses instruction pointer (IP)
    pc_width=16,  # 8086 has 16-bit IP
    reset_pc_signal="reset_ip",
    reset_pc_value=0x0000,  # 8086 tests start at 0x0000
    # Test file format
    test_file_format="bin",  # 8086 tests are binary, not ELF
    bin_load_offset=0,  # Load from address 0
    # Completion detection
    detect_pc_stall=True,  # Detect infinite loop or HLT
    pc_stall_cycles=10,     # IP must be stuck for 10 cycles
)

# Generate testbench and FuseSoC core files
rtl_file = project_root / "examples/verilog/8086_test/8086_test.v"
output_dir = project_root / "examples/verilog/8086_test"

files = generate_testbench_files(
    module_name="cpu_8086_test",
    rtl_file=str(rtl_file),
    output_dir=output_dir,
    config=config
)

print(f"Generated testbench: {files['testbench']}")
print(f"Generated core file: {files['core']}")
print("\nTo run a test:")
print("  ./examples/verilog/8086_test/sim_8086 +bin_load=<test.bin> +pass_addr=<addr> +fail_addr=<addr>")
