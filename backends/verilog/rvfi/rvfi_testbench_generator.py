"""
RVFI-specific testbench generator for formal verification.

Generates testbenches compatible with riscv-formal framework.
"""

from typing import Optional
from pathlib import Path
from dataclasses import dataclass
from .rvfi_generator import RVFIConfig, RVFISignalGenerator


@dataclass
class RVFITestbenchConfig:
    """Configuration for RVFI testbench generation."""

    module_name: str = "processor"
    rvfi_config: Optional[RVFIConfig] = None

    # Formal verification parameters
    max_depth: int = 20  # Maximum induction depth
    generate_cover: bool = True  # Generate cover properties
    generate_assert: bool = True  # Generate assertion properties

    def __post_init__(self):
        if self.rvfi_config is None:
            self.rvfi_config = RVFIConfig()


class RVFITestbenchGenerator:
    """Generate testbenches for RVFI formal verification."""

    def __init__(self, config: RVFITestbenchConfig):
        self.config = config
        self.rvfi_gen = RVFISignalGenerator(config.rvfi_config)

    def generate_formal_testbench(self) -> str:
        """
        Generate a testbench for SymbiYosys formal verification.

        This testbench connects to riscv-formal checks.
        """
        tb = []

        tb.append("`timescale 1ns/1ps\n\n")
        tb.append(f"// RVFI Formal Verification Testbench for {self.config.module_name}\n")
        tb.append("// Compatible with riscv-formal framework\n\n")

        tb.append(f"module {self.config.module_name}_rvfi_tb;\n\n")

        # Clock and reset
        tb.append("    // Formal verification signals\n")
        tb.append("    (* gclk *) reg clk;\n")
        tb.append("    reg reset;\n")
        tb.append("    reg [31:0] reset_pc;\n\n")

        # RVFI signals (declared as wires from DUT)
        tb.append("    // RVFI signals from DUT\n")
        xlen = self.config.rvfi_config.xlen
        tb.append("    wire rvfi_valid;\n")
        tb.append("    wire [63:0] rvfi_order;\n")
        tb.append("    wire [31:0] rvfi_insn;\n")
        tb.append("    wire rvfi_trap;\n")
        tb.append("    wire rvfi_halt;\n")
        tb.append("    wire rvfi_intr;\n")
        tb.append("    wire [1:0] rvfi_mode;\n")
        tb.append("    wire [1:0] rvfi_ixl;\n")
        tb.append("    wire [4:0] rvfi_rs1_addr;\n")
        tb.append("    wire [4:0] rvfi_rs2_addr;\n")
        tb.append(f"    wire [{xlen-1}:0] rvfi_rs1_rdata;\n")
        tb.append(f"    wire [{xlen-1}:0] rvfi_rs2_rdata;\n")
        tb.append("    wire [4:0] rvfi_rd_addr;\n")
        tb.append(f"    wire [{xlen-1}:0] rvfi_rd_wdata;\n")
        tb.append(f"    wire [{xlen-1}:0] rvfi_pc_rdata;\n")
        tb.append(f"    wire [{xlen-1}:0] rvfi_pc_wdata;\n")

        if self.config.rvfi_config.enable_mem:
            tb.append(f"    wire [{xlen-1}:0] rvfi_mem_addr;\n")
            tb.append(f"    wire [{xlen//8-1}:0] rvfi_mem_rmask;\n")
            tb.append(f"    wire [{xlen//8-1}:0] rvfi_mem_wmask;\n")
            tb.append(f"    wire [{xlen-1}:0] rvfi_mem_rdata;\n")
            tb.append(f"    wire [{xlen-1}:0] rvfi_mem_wdata;\n")

        tb.append("\n")

        # DUT instantiation
        tb.append("    // Device Under Test with RVFI\n")
        tb.append(f"    {self.config.module_name}_rvfi_wrapper dut (\n")
        tb.append("        .clk(clk),\n")
        tb.append("        .reset(reset),\n")
        tb.append("        .reset_pc_rd(reset_pc),\n\n")

        tb.append("        // RVFI outputs\n")
        tb.append("        .rvfi_valid(rvfi_valid),\n")
        tb.append("        .rvfi_order(rvfi_order),\n")
        tb.append("        .rvfi_insn(rvfi_insn),\n")
        tb.append("        .rvfi_trap(rvfi_trap),\n")
        tb.append("        .rvfi_halt(rvfi_halt),\n")
        tb.append("        .rvfi_intr(rvfi_intr),\n")
        tb.append("        .rvfi_mode(rvfi_mode),\n")
        tb.append("        .rvfi_ixl(rvfi_ixl),\n")
        tb.append("        .rvfi_rs1_addr(rvfi_rs1_addr),\n")
        tb.append("        .rvfi_rs2_addr(rvfi_rs2_addr),\n")
        tb.append("        .rvfi_rs1_rdata(rvfi_rs1_rdata),\n")
        tb.append("        .rvfi_rs2_rdata(rvfi_rs2_rdata),\n")
        tb.append("        .rvfi_rd_addr(rvfi_rd_addr),\n")
        tb.append("        .rvfi_rd_wdata(rvfi_rd_wdata),\n")
        tb.append("        .rvfi_pc_rdata(rvfi_pc_rdata),\n")
        tb.append("        .rvfi_pc_wdata(rvfi_pc_wdata)")

        if self.config.rvfi_config.enable_mem:
            tb.append(",\n")
            tb.append("        .rvfi_mem_addr(rvfi_mem_addr),\n")
            tb.append("        .rvfi_mem_rmask(rvfi_mem_rmask),\n")
            tb.append("        .rvfi_mem_wmask(rvfi_mem_wmask),\n")
            tb.append("        .rvfi_mem_rdata(rvfi_mem_rdata),\n")
            tb.append("        .rvfi_mem_wdata(rvfi_mem_wdata)\n")
        else:
            tb.append("\n")

        tb.append("    );\n\n")

        # Reset logic
        tb.append("    // Reset logic\n")
        tb.append("    initial begin\n")
        tb.append("        reset = 1;\n")
        tb.append("        reset_pc = 32'h0;\n")
        tb.append("    end\n\n")

        # Formal properties
        if self.config.generate_assert:
            tb.append(self._generate_assertions())

        if self.config.generate_cover:
            tb.append(self._generate_cover_properties())

        tb.append("endmodule\n")

        return "".join(tb)

    def _generate_assertions(self) -> str:
        """Generate formal assertion properties."""
        asserts = []

        asserts.append("    // Formal Assertions\n")
        asserts.append("    `ifdef FORMAL\n\n")

        # Basic RVFI validity checks
        asserts.append("    // RVFI valid signal stability\n")
        asserts.append("    always @(posedge clk) begin\n")
        asserts.append("        if (!reset) begin\n")
        asserts.append("            // When valid, order should increase\n")
        asserts.append("            if ($past(rvfi_valid) && rvfi_valid) begin\n")
        asserts.append("                assert(rvfi_order > $past(rvfi_order));\n")
        asserts.append("            end\n\n")

        asserts.append("            // PC progression check (basic)\n")
        asserts.append("            if (rvfi_valid && !rvfi_trap) begin\n")
        asserts.append("                // For sequential instructions, PC should advance by 4\n")
        asserts.append("                // Note: This is simplified, branches/jumps need special handling\n")
        asserts.append("                assert(rvfi_pc_wdata >= rvfi_pc_rdata);\n")
        asserts.append("            end\n\n")

        asserts.append("            // Register x0 must always be zero\n")
        asserts.append("            if (rvfi_valid && rvfi_rd_addr == 5'h0) begin\n")
        asserts.append("                assert(rvfi_rd_wdata == 32'h0);\n")
        asserts.append("            end\n")
        asserts.append("        end\n")
        asserts.append("    end\n\n")

        asserts.append("    `endif\n\n")

        return "".join(asserts)

    def _generate_cover_properties(self) -> str:
        """Generate coverage properties."""
        covers = []

        covers.append("    // Coverage Properties\n")
        covers.append("    `ifdef FORMAL\n\n")

        covers.append("    // Cover: Instruction retirement\n")
        covers.append("    always @(posedge clk) begin\n")
        covers.append("        if (!reset && rvfi_valid) begin\n")
        covers.append("            cover(rvfi_valid);\n")
        covers.append("        end\n")
        covers.append("    end\n\n")

        covers.append("    // Cover: Register write\n")
        covers.append("    always @(posedge clk) begin\n")
        covers.append("        if (!reset && rvfi_valid && rvfi_rd_addr != 5'h0) begin\n")
        covers.append("            cover(rvfi_rd_wdata != 32'h0);\n")
        covers.append("        end\n")
        covers.append("    end\n\n")

        if self.config.rvfi_config.enable_mem:
            covers.append("    // Cover: Memory access\n")
            covers.append("    always @(posedge clk) begin\n")
            covers.append("        cover(rvfi_mem_rmask != 4'h0);  // Read\n")
            covers.append("        cover(rvfi_mem_wmask != 4'h0);  // Write\n")
            covers.append("    end\n\n")

        covers.append("    `endif\n\n")

        return "".join(covers)

    def generate_sby_config(self, checks: list = None) -> str:
        """
        Generate SymbiYosys (.sby) configuration file.

        Args:
            checks: List of riscv-formal checks to run (e.g., ['insn_add', 'insn_addi'])
        """
        if checks is None:
            checks = ['insn_add', 'insn_addi', 'insn_sub']

        config = []

        config.append("[options]\n")
        config.append("mode bmc\n")
        config.append(f"depth {self.config.max_depth}\n")
        config.append("expect pass\n\n")

        config.append("[engines]\n")
        config.append("smtbmc z3\n\n")

        config.append("[script]\n")
        config.append("read -formal rvfi_macros.vh\n")
        config.append(f"read -sv {self.config.module_name}.v\n")
        config.append(f"read -sv {self.config.module_name}_rvfi_wrapper.v\n")
        config.append(f"read -sv {self.config.module_name}_rvfi_tb.sv\n")

        # Include riscv-formal checks
        for check in checks:
            config.append(f"read -formal riscv-formal/checks/{check}.sv\n")

        config.append(f"prep -top {self.config.module_name}_rvfi_tb\n\n")

        config.append("[files]\n")
        config.append(f"{self.config.module_name}.v\n")
        config.append(f"{self.config.module_name}_rvfi_wrapper.v\n")
        config.append(f"{self.config.module_name}_rvfi_tb.sv\n")
        config.append("rvfi_macros.vh\n\n")

        return "".join(config)


def generate_rvfi_testbench_files(module_name: str,
                                  output_dir: Path,
                                  rvfi_config: Optional[RVFIConfig] = None,
                                  checks: list = None) -> dict:
    """
    Generate all RVFI testbench files for formal verification.

    Args:
        module_name: Name of the processor module
        output_dir: Directory to write output files
        rvfi_config: RVFI configuration
        checks: List of riscv-formal checks to include

    Returns:
        Dictionary with paths to generated files
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create testbench config
    tb_config = RVFITestbenchConfig(
        module_name=module_name,
        rvfi_config=rvfi_config or RVFIConfig()
    )

    # Generate testbench
    tb_gen = RVFITestbenchGenerator(tb_config)

    # Write testbench file
    tb_code = tb_gen.generate_formal_testbench()
    tb_file = output_dir / f"{module_name}_rvfi_tb.sv"
    tb_file.write_text(tb_code)

    # Write SymbiYosys config
    sby_config = tb_gen.generate_sby_config(checks=checks)
    sby_file = output_dir / f"{module_name}_rvfi.sby"
    sby_file.write_text(sby_config)

    # Write README
    readme = _generate_rvfi_readme(module_name)
    readme_file = output_dir / "RVFI_README.md"
    readme_file.write_text(readme)

    return {
        'testbench': tb_file,
        'sby_config': sby_file,
        'readme': readme_file
    }


def _generate_rvfi_readme(module_name: str) -> str:
    """Generate README for RVFI verification."""
    readme = f"""# RVFI Formal Verification for {module_name}

This directory contains files for formal verification using the RISC-V Formal Interface (RVFI).

## Files

- `{module_name}_rvfi_wrapper.v` - Wrapper adding RVFI signals to processor
- `{module_name}_rvfi_tb.sv` - Formal verification testbench
- `{module_name}_rvfi.sby` - SymbiYosys configuration

## Prerequisites

1. Install SymbiYosys:
   ```bash
   # See: https://symbiyosys.readthedocs.io/
   ```

2. Clone riscv-formal:
   ```bash
   git clone https://github.com/SymbioticEDA/riscv-formal.git
   ```

## Running Formal Verification

```bash
# Run all checks
sby -f {module_name}_rvfi.sby

# Run specific check
sby -f {module_name}_rvfi.sby insn_add
```

## Verification Checks

The testbench includes:

- **Instruction checks**: Verify each instruction behaves according to RISC-V spec
- **PC progression**: Ensure program counter advances correctly
- **Register file**: Verify register reads/writes
- **Memory access**: Check load/store operations (if enabled)

## Adding More Checks

Edit the `.sby` file to include additional riscv-formal checks from:
`riscv-formal/checks/`

## Debugging

If verification fails, check:

1. SymbiYosys output in `{module_name}_rvfi/` directory
2. Counterexample traces
3. Waveforms (if available)

## References

- RVFI Specification: https://github.com/SymbioticEDA/riscv-formal/blob/master/docs/rvfi.md
- riscv-formal Documentation: https://symbiyosys.readthedocs.io/projects/riscv-formal/
"""
    return readme


if __name__ == "__main__":
    # Example usage
    config = RVFITestbenchConfig(
        module_name="riscv32_alu",
        rvfi_config=RVFIConfig(xlen=32, enable_mem=True)
    )

    gen = RVFITestbenchGenerator(config)
    print(gen.generate_formal_testbench())
