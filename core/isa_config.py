"""
ISA-specific configuration for testbench generation.

This module defines configurations for different ISAs, including toolchain
paths, memory layouts, and simulation parameters.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict
from pathlib import Path


@dataclass
class ISAConfig:
    """Configuration for a specific ISA."""

    # ISA identification
    name: str
    arch: str  # e.g., "rv32i", "mips32", "arm32"

    # Toolchain paths
    toolchain_prefix: str  # e.g., "riscv32-unknown-elf-", "mips-unknown-elf-"
    gcc_path: Optional[str] = None  # Override default path
    objdump_path: Optional[str] = None
    objcopy_path: Optional[str] = None
    nm_path: Optional[str] = None

    # GCC flags
    gcc_arch_flags: List[str] = None  # e.g., ["-march=rv32i", "-mabi=ilp32"]
    gcc_common_flags: List[str] = None  # e.g., ["-nostdlib", "-nostartfiles"]

    # Memory configuration
    text_start_addr: int = 0x0  # Start address for .text section
    data_start_addr: Optional[int] = None  # Start address for .data section
    imem_addr_width: int = 12  # Instruction memory address width (in bits)
    imem_data_width: int = 32  # Instruction memory data width
    dmem_addr_width: int = 12  # Data memory address width
    dmem_data_width: int = 32  # Data memory data width

    # Processor interface
    pc_signal_name: str = "pc_rd"  # Name of PC signal in generated RTL
    reset_pc_signal: str = "reset_pc_rd"  # Name of reset PC input
    has_separate_imem_dmem: bool = True  # Whether ISA has separate I/D memories

    # Test completion
    completion_method: str = "label"  # "label", "signal", or "address"
    pass_label: str = "pass"  # Label name for test pass
    fail_label: str = "fail"  # Label name for test fail
    completion_signal: Optional[str] = None  # Signal name for completion
    completion_address: Optional[int] = None  # Specific completion address

    # Simulation parameters
    default_timeout_cycles: int = 100000
    clock_period_ns: int = 10
    reset_cycles: int = 5

    def __post_init__(self):
        """Set default values after initialization."""
        if self.gcc_common_flags is None:
            self.gcc_common_flags = ["-nostdlib", "-nostartfiles"]

        if self.gcc_arch_flags is None:
            self.gcc_arch_flags = []

    def get_tool_path(self, tool: str) -> str:
        """Get path to a specific tool."""
        tool_map = {
            'gcc': self.gcc_path,
            'objdump': self.objdump_path,
            'objcopy': self.objcopy_path,
            'nm': self.nm_path
        }

        if tool in tool_map and tool_map[tool]:
            return tool_map[tool]

        # Default: use toolchain prefix
        return f"{self.toolchain_prefix}{tool}"

    def get_gcc_flags(self, text_addr: Optional[int] = None) -> List[str]:
        """Get complete GCC flags for compilation."""
        flags = []
        flags.extend(self.gcc_arch_flags)
        flags.extend(self.gcc_common_flags)

        # Add text section address
        addr = text_addr if text_addr is not None else self.text_start_addr
        flags.append(f"-Ttext=0x{addr:x}")

        return flags


# Predefined ISA configurations
ISA_CONFIGS = {
    'riscv32': ISAConfig(
        name='riscv32',
        arch='rv32i',
        toolchain_prefix='isa/riscv32/bin/riscv64-unknown-elf-',
        gcc_arch_flags=['-march=rv32i', '-mabi=ilp32'],
        gcc_common_flags=['-nostdlib', '-nostartfiles'],
        text_start_addr=0x0,
        imem_addr_width=12,
        pc_signal_name='pc_rd',
        reset_pc_signal='reset_pc_rd',
        pass_label='pass',
        fail_label='fail'
    ),

    'mips32': ISAConfig(
        name='mips32',
        arch='mips32',
        toolchain_prefix='mips-unknown-elf-',
        gcc_arch_flags=['-march=mips32', '-mabi=32'],
        gcc_common_flags=['-nostdlib', '-nostartfiles', '-mno-abicalls'],
        text_start_addr=0x0,
        imem_addr_width=12,
        pc_signal_name='pc_rd',
        reset_pc_signal='reset_pc_rd',
        pass_label='pass',
        fail_label='fail'
    ),

    '6502': ISAConfig(
        name='6502',
        arch='6502',
        toolchain_prefix='6502-',
        gcc_arch_flags=[],  # 6502 uses cc65 or ca65
        gcc_common_flags=[],
        text_start_addr=0x0,
        imem_addr_width=16,  # 6502 has 16-bit address space (64KB)
        imem_data_width=8,   # 6502 has 8-bit data
        dmem_addr_width=16,
        dmem_data_width=8,
        pc_signal_name='pc_rd',
        reset_pc_signal='reset_pc_rd',
        pass_label='pass',
        fail_label='fail'
    ),

    '8086': ISAConfig(
        name='8086',
        arch='8086',
        toolchain_prefix='i686-elf-',  # Or ia16-elf- if available
        gcc_arch_flags=['-march=i8086'],
        gcc_common_flags=['-nostdlib', '-nostartfiles'],
        text_start_addr=0x0,
        imem_addr_width=20,  # 8086 has 20-bit address space (1MB)
        imem_data_width=16,  # 8086 has 16-bit data
        dmem_addr_width=20,
        dmem_data_width=16,
        pc_signal_name='pc_rd',
        reset_pc_signal='reset_pc_rd',
        pass_label='pass',
        fail_label='fail'
    ),

    'i486': ISAConfig(
        name='i486',
        arch='i486',
        toolchain_prefix='i686-elf-',
        gcc_arch_flags=['-march=i486', '-m32'],
        gcc_common_flags=['-nostdlib', '-nostartfiles'],
        text_start_addr=0x0,
        imem_addr_width=32,  # i486 has 32-bit address space (4GB)
        imem_data_width=32,  # i486 has 32-bit data
        dmem_addr_width=32,
        dmem_data_width=32,
        pc_signal_name='pc_rd',
        reset_pc_signal='reset_pc_rd',
        pass_label='pass',
        fail_label='fail'
    ),

    'm68k': ISAConfig(
        name='m68k',
        arch='m68000',
        toolchain_prefix='m68k-elf-',
        gcc_arch_flags=['-m68000'],
        gcc_common_flags=['-nostdlib', '-nostartfiles'],
        text_start_addr=0x0,
        imem_addr_width=24,  # M68000 has 24-bit address bus
        imem_data_width=16,  # M68000 has 16-bit data bus (instructions are 16-bit words)
        dmem_addr_width=24,
        dmem_data_width=16,  # 16-bit data bus
        pc_signal_name='pc_rd',
        reset_pc_signal='reset_pc_rd',
        pass_label='pass',
        fail_label='fail'
    ),

    'openpower': ISAConfig(
        name='openpower',
        arch='power64',
        toolchain_prefix='powerpc64le-linux-gnu-',
        gcc_arch_flags=['-mcpu=power9', '-m64'],
        gcc_common_flags=['-nostdlib', '-nostartfiles'],
        text_start_addr=0x0,
        imem_addr_width=14,  # OpenPOWER uses 64-bit addresses, but limited for simulation
        imem_data_width=32,  # 32-bit instruction words
        dmem_addr_width=14,
        dmem_data_width=64,  # 64-bit data
        pc_signal_name='pc_rd',
        reset_pc_signal='reset_pc_rd',
        pass_label='pass',
        fail_label='fail'
    ),

    'z80': ISAConfig(
        name='z80',
        arch='z80',
        toolchain_prefix='z80-unknown-elf-',  # SDCC or z88dk
        gcc_arch_flags=[],  # Z80 uses specialized assemblers (z80asm, sdasz80)
        gcc_common_flags=[],
        text_start_addr=0x0,
        imem_addr_width=16,  # Z80 has 16-bit address space (64KB)
        imem_data_width=8,   # Z80 has 8-bit data bus
        dmem_addr_width=16,
        dmem_data_width=8,
        pc_signal_name='pc_rd',
        reset_pc_signal='reset_pc_rd',
        pass_label='pass',
        fail_label='fail'
    ),

    'j2': ISAConfig(
        name='j2',
        arch='sh2',
        toolchain_prefix='sh-elf-',  # Using sh-elf- (apt: gcc-sh-elf)
        gcc_arch_flags=['-m2', '-mb'],  # -m2 for SH-2/j2, -mb for big-endian (can use -ml for little-endian)
        gcc_common_flags=['-nostdlib', '-nostartfiles'],
        text_start_addr=0x0,
        imem_addr_width=12,  # 4KB instruction memory for basic implementation
        imem_data_width=16,  # j2 has 16-bit instructions (SH-2 compatible)
        dmem_addr_width=12,  # 4KB data memory
        dmem_data_width=32,  # j2 has 32-bit data width
        pc_signal_name='pc_rd',
        reset_pc_signal='reset_pc_rd',
        pass_label='pass',
        fail_label='fail'
    ),

    'tdmi': ISAConfig(
        name='tdmi',
        arch='armv4t',
        toolchain_prefix='arm-none-eabi-',  # Using arm-none-eabi- (apt: gcc-arm-none-eabi)
        gcc_arch_flags=['-march=armv4t', '-marm'],  # ARMv4T for ARM7TDMI compatibility
        gcc_common_flags=['-nostdlib', '-nostartfiles', '-mno-thumb-interwork'],
        text_start_addr=0x0,
        imem_addr_width=14,  # 16KB instruction memory
        imem_data_width=32,  # ARM mode: 32-bit instructions
        dmem_addr_width=14,  # 16KB data memory
        dmem_data_width=32,  # 32-bit data width
        pc_signal_name='pc_rd',
        reset_pc_signal='reset_pc_rd',
        pass_label='pass',
        fail_label='fail'
    ),

    'microvax': ISAConfig(
        name='microvax',
        arch='vax',
        toolchain_prefix='microvax-',  # Custom toolchain prefix
        gcc_arch_flags=[],  # No standard GCC for VAX - we use custom assembler
        gcc_common_flags=[],
        text_start_addr=0x0,
        imem_addr_width=12,  # 4KB instruction/data memory (unified)
        imem_data_width=32,  # 32-bit instructions
        dmem_addr_width=12,  # 4KB data memory
        dmem_data_width=32,  # 32-bit data width
        pc_signal_name='pc_rd',
        reset_pc_signal='reset_pc_rd',
        has_separate_imem_dmem=False,  # Unified memory
        pass_label='pass',
        fail_label='fail'
    ),
}


def get_isa_config(isa_name: str) -> ISAConfig:
    """Get ISA configuration by name."""
    if isa_name in ISA_CONFIGS:
        return ISA_CONFIGS[isa_name]
    raise ValueError(f"Unknown ISA: {isa_name}. Available: {list(ISA_CONFIGS.keys())}")


def register_isa_config(config: ISAConfig):
    """Register a new ISA configuration."""
    ISA_CONFIGS[config.name] = config
