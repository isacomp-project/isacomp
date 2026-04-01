"""
Integration module to add RVFI generation to backends/verilog/verilog_generator.py

This extends the existing Verilog generation with RVFI wrapper capability.
"""

from typing import Dict, Optional
from pathlib import Path
from core.resource_graph import ResourceGraph
from .rvfi_generator import RVFIConfig, generate_rvfi_wrapper
from .rvfi_testbench_generator import generate_rvfi_testbench_files
from backends.verilog import generate_verilog


def generate_verilog_with_rvfi(graph: ResourceGraph,
                                module_name: str = "processor",
                                output_dir: str = "examples/verilog",
                                rvfi_config: Optional[RVFIConfig] = None,
                                processor_signals: Optional[Dict[str, str]] = None,
                                rvfi_checks: list = None) -> dict:
    """
    Generate Verilog RTL with RVFI wrapper and formal testbenches.

    Args:
        graph: ResourceGraph to generate from
        module_name: Name of the processor module
        output_dir: Directory to write output files
        rvfi_config: Optional RVFI configuration
        processor_signals: Mapping of RVFI signals to processor signals
        rvfi_checks: List of riscv-formal checks to include

    Returns:
        Dictionary with paths to generated files
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate base processor RTL
    print(f"Generating base processor RTL: {module_name}.v")
    processor_code = generate_verilog(graph, module_name)
    processor_file = output_path / f"{module_name}.v"
    processor_file.write_text(processor_code)

    # Create RVFI config if not provided
    if rvfi_config is None:
        rvfi_config = RVFIConfig(xlen=32, nret=1, enable_mem=True)

    # Create processor signal mapping if not provided
    if processor_signals is None:
        # Default RISC-V signal mapping
        processor_signals = {
            'pc': 'pc_rd',
            'instruction': 'instruction',  # May need to be inferred
            'rs1_addr': 'rs1',
            'rs2_addr': 'rs2',
            'rd_addr': 'rd',
            'rs1_data': 'rs1_data',
            'rs2_data': 'rs2_data',
            'rd_data': 'rd_data',
        }

    # Generate RVFI wrapper
    print(f"Generating RVFI wrapper: {module_name}_rvfi_wrapper.v")
    wrapper_code = generate_rvfi_wrapper(
        processor_module=module_name,
        config=rvfi_config,
        processor_signals=processor_signals
    )
    wrapper_file = output_path / f"{module_name}_rvfi_wrapper.v"
    wrapper_file.write_text(wrapper_code)

    # Generate RVFI testbenches and formal verification files
    print(f"Generating RVFI formal verification files")
    rvfi_files = generate_rvfi_testbench_files(
        module_name=module_name,
        output_dir=output_path,
        rvfi_config=rvfi_config,
        checks=rvfi_checks
    )

    print("\nGenerated files:")
    print(f"  Processor RTL: {processor_file}")
    print(f"  RVFI Wrapper:  {wrapper_file}")
    print(f"  RVFI Testbench: {rvfi_files['testbench']}")
    print(f"  SymbiYosys Config: {rvfi_files['sby_config']}")
    print(f"  README: {rvfi_files['readme']}")

    return {
        'processor': processor_file,
        'rvfi_wrapper': wrapper_file,
        'rvfi_testbench': rvfi_files['testbench'],
        'sby_config': rvfi_files['sby_config'],
        'readme': rvfi_files['readme']
    }


if __name__ == "__main__":
    print("RVFI Integration Module")
    print("=" * 60)
    print("\nUsage example:")
    print("""
from core.resource_graph import ResourceGraph
from core.graph_merger import merge_instructions
from verilog_rvfi_integration import generate_verilog_with_rvfi
from .rvfi_generator import RVFIConfig

# Merge instructions
instruction_files = {
    'add': 'isa/riscv32/add.isa',
    'addi': 'isa/riscv32/addi.isa',
}
graph = merge_instructions(instruction_files)
graph.optimize()

# Generate with RVFI
files = generate_verilog_with_rvfi(
    graph=graph,
    module_name="riscv32_alu",
    output_dir="examples/verilog/riscv32_alu_rvfi",
    rvfi_config=RVFIConfig(xlen=32, enable_mem=True),
    rvfi_checks=['insn_add', 'insn_addi']
)

print(f"Generated: {files['rvfi_wrapper']}")
""")
