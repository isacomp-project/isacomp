"""
RISC-V Formal Interface (RVFI) generator for ISAComp processors.

This module generates RVFI output signals for formal verification of RISC-V
processors using the riscv-formal framework.

RVFI Specification: https://github.com/SymbioticEDA/riscv-formal/blob/master/docs/rvfi.md
"""

from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class RVFIConfig:
    """Configuration for RVFI signal generation."""

    # Core parameters
    xlen: int = 32  # Register width (32 for RV32, 64 for RV64)
    nret: int = 1   # Number of instructions retired per cycle
    ilen: int = 32  # Maximum instruction width

    # Enable optional signal groups
    enable_csr: bool = False  # Enable CSR tracking
    enable_mem: bool = True   # Enable memory access tracking

    # CSRs to track (if enable_csr is True)
    tracked_csrs: List[str] = None

    def __post_init__(self):
        if self.tracked_csrs is None:
            self.tracked_csrs = []


class RVFISignalGenerator:
    """
    Generate RVFI signals for a RISC-V processor core.

    RVFI provides a standardized interface for formal verification by exposing
    internal processor state changes for each retired instruction.
    """

    def __init__(self, config: RVFIConfig):
        self.config = config

    def generate_rvfi_outputs(self) -> str:
        """Generate RVFI output port declarations."""
        signals = []
        xlen = self.config.xlen
        nret = self.config.nret
        ilen = self.config.ilen

        signals.append("    // RVFI (RISC-V Formal Interface) Outputs\n")

        # Instruction Metadata
        signals.append("    // Instruction Metadata\n")
        signals.append(f"    output wire [{nret}-1:0] rvfi_valid,\n")
        signals.append(f"    output wire [{nret*64}-1:0] rvfi_order,\n")
        signals.append(f"    output wire [{nret*ilen}-1:0] rvfi_insn,\n")
        signals.append(f"    output wire [{nret}-1:0] rvfi_trap,\n")
        signals.append(f"    output wire [{nret}-1:0] rvfi_halt,\n")
        signals.append(f"    output wire [{nret}-1:0] rvfi_intr,\n")
        signals.append(f"    output wire [{nret*2}-1:0] rvfi_mode,\n")
        signals.append(f"    output wire [{nret*2}-1:0] rvfi_ixl,\n\n")

        # Register Access
        signals.append("    // Integer Register Read/Write\n")
        signals.append(f"    output wire [{nret*5}-1:0] rvfi_rs1_addr,\n")
        signals.append(f"    output wire [{nret*5}-1:0] rvfi_rs2_addr,\n")
        signals.append(f"    output wire [{nret*xlen}-1:0] rvfi_rs1_rdata,\n")
        signals.append(f"    output wire [{nret*xlen}-1:0] rvfi_rs2_rdata,\n")
        signals.append(f"    output wire [{nret*5}-1:0] rvfi_rd_addr,\n")
        signals.append(f"    output wire [{nret*xlen}-1:0] rvfi_rd_wdata,\n\n")

        # Program Counter
        signals.append("    // Program Counter\n")
        signals.append(f"    output wire [{nret*xlen}-1:0] rvfi_pc_rdata,\n")
        signals.append(f"    output wire [{nret*xlen}-1:0] rvfi_pc_wdata,\n\n")

        # Memory Access
        if self.config.enable_mem:
            signals.append("    // Memory Access\n")
            signals.append(f"    output wire [{nret*xlen}-1:0] rvfi_mem_addr,\n")
            signals.append(f"    output wire [{nret*(xlen//8)}-1:0] rvfi_mem_rmask,\n")
            signals.append(f"    output wire [{nret*(xlen//8)}-1:0] rvfi_mem_wmask,\n")
            signals.append(f"    output wire [{nret*xlen}-1:0] rvfi_mem_rdata,\n")
            signals.append(f"    output wire [{nret*xlen}-1:0] rvfi_mem_wdata,\n\n")

        # CSR Access
        if self.config.enable_csr and self.config.tracked_csrs:
            signals.append("    // CSR Access\n")
            for csr in self.config.tracked_csrs:
                signals.append(f"    // CSR: {csr}\n")
                signals.append(f"    output wire [{nret*xlen}-1:0] rvfi_csr_{csr}_rmask,\n")
                signals.append(f"    output wire [{nret*xlen}-1:0] rvfi_csr_{csr}_wmask,\n")
                signals.append(f"    output wire [{nret*xlen}-1:0] rvfi_csr_{csr}_rdata,\n")
                signals.append(f"    output wire [{nret*xlen}-1:0] rvfi_csr_{csr}_wdata,\n")
            signals.append("\n")

        return "".join(signals)

    def generate_rvfi_registers(self) -> str:
        """Generate internal RVFI registers and logic."""
        code = []
        xlen = self.config.xlen
        nret = self.config.nret
        ilen = self.config.ilen

        code.append("    // RVFI Internal Registers\n")
        code.append(f"    reg [{nret}-1:0] rvfi_valid_r;\n")
        code.append(f"    reg [63:0] rvfi_order_r;\n")
        code.append(f"    reg [{ilen-1}:0] rvfi_insn_r;\n")
        code.append(f"    reg rvfi_trap_r;\n")
        code.append(f"    reg rvfi_halt_r;\n")
        code.append(f"    reg rvfi_intr_r;\n")
        code.append(f"    reg [1:0] rvfi_mode_r;\n")
        code.append(f"    reg [1:0] rvfi_ixl_r;\n")
        code.append(f"    reg [4:0] rvfi_rs1_addr_r;\n")
        code.append(f"    reg [4:0] rvfi_rs2_addr_r;\n")
        code.append(f"    reg [{xlen-1}:0] rvfi_rs1_rdata_r;\n")
        code.append(f"    reg [{xlen-1}:0] rvfi_rs2_rdata_r;\n")
        code.append(f"    reg [4:0] rvfi_rd_addr_r;\n")
        code.append(f"    reg [{xlen-1}:0] rvfi_rd_wdata_r;\n")
        code.append(f"    reg [{xlen-1}:0] rvfi_pc_rdata_r;\n")
        code.append(f"    reg [{xlen-1}:0] rvfi_pc_wdata_r;\n")

        if self.config.enable_mem:
            code.append(f"    reg [{xlen-1}:0] rvfi_mem_addr_r;\n")
            code.append(f"    reg [{xlen//8-1}:0] rvfi_mem_rmask_r;\n")
            code.append(f"    reg [{xlen//8-1}:0] rvfi_mem_wmask_r;\n")
            code.append(f"    reg [{xlen-1}:0] rvfi_mem_rdata_r;\n")
            code.append(f"    reg [{xlen-1}:0] rvfi_mem_wdata_r;\n")

        code.append("\n")

        # Assign registers to outputs
        code.append("    // RVFI Output Assignments\n")
        code.append("    assign rvfi_valid = rvfi_valid_r;\n")
        code.append("    assign rvfi_order = rvfi_order_r;\n")
        code.append("    assign rvfi_insn = rvfi_insn_r;\n")
        code.append("    assign rvfi_trap = rvfi_trap_r;\n")
        code.append("    assign rvfi_halt = rvfi_halt_r;\n")
        code.append("    assign rvfi_intr = rvfi_intr_r;\n")
        code.append("    assign rvfi_mode = rvfi_mode_r;\n")
        code.append("    assign rvfi_ixl = rvfi_ixl_r;\n")
        code.append("    assign rvfi_rs1_addr = rvfi_rs1_addr_r;\n")
        code.append("    assign rvfi_rs2_addr = rvfi_rs2_addr_r;\n")
        code.append("    assign rvfi_rs1_rdata = rvfi_rs1_rdata_r;\n")
        code.append("    assign rvfi_rs2_rdata = rvfi_rs2_rdata_r;\n")
        code.append("    assign rvfi_rd_addr = rvfi_rd_addr_r;\n")
        code.append("    assign rvfi_rd_wdata = rvfi_rd_wdata_r;\n")
        code.append("    assign rvfi_pc_rdata = rvfi_pc_rdata_r;\n")
        code.append("    assign rvfi_pc_wdata = rvfi_pc_wdata_r;\n")

        if self.config.enable_mem:
            code.append("    assign rvfi_mem_addr = rvfi_mem_addr_r;\n")
            code.append("    assign rvfi_mem_rmask = rvfi_mem_rmask_r;\n")
            code.append("    assign rvfi_mem_wmask = rvfi_mem_wmask_r;\n")
            code.append("    assign rvfi_mem_rdata = rvfi_mem_rdata_r;\n")
            code.append("    assign rvfi_mem_wdata = rvfi_mem_wdata_r;\n")

        code.append("\n")

        return "".join(code)

    def generate_rvfi_update_logic(self,
                                   pc_signal: str = "pc",
                                   insn_signal: str = "instruction",
                                   rs1_addr_signal: str = "rs1_addr",
                                   rs2_addr_signal: str = "rs2_addr",
                                   rd_addr_signal: str = "rd_addr",
                                   rs1_data_signal: str = "rs1_data",
                                   rs2_data_signal: str = "rs2_data",
                                   rd_data_signal: str = "rd_data") -> str:
        """Generate logic to update RVFI signals based on processor state."""
        code = []

        code.append("    // RVFI Update Logic\n")
        code.append("    always @(posedge clk) begin\n")
        code.append("        if (reset) begin\n")
        code.append("            rvfi_valid_r <= 1'b0;\n")
        code.append("            rvfi_order_r <= 64'h0;\n")
        code.append("            rvfi_trap_r <= 1'b0;\n")
        code.append("            rvfi_halt_r <= 1'b0;\n")
        code.append("            rvfi_intr_r <= 1'b0;\n")
        code.append("            rvfi_mode_r <= 2'b11;  // Machine mode\n")
        code.append(f"            rvfi_ixl_r <= 2'b{1 if self.config.xlen == 32 else 2};  // XLEN encoding\n")
        code.append("        end else begin\n")
        code.append("            // Capture instruction retirement\n")
        code.append("            // TODO: This needs to be connected to actual instruction retirement signal\n")
        code.append("            rvfi_valid_r <= 1'b1;  // Set when instruction retires\n")
        code.append("            \n")
        code.append("            if (rvfi_valid_r) begin\n")
        code.append("                rvfi_order_r <= rvfi_order_r + 64'h1;\n")
        code.append("            end\n")
        code.append("            \n")
        code.append("            // Capture instruction and operands\n")
        code.append(f"            rvfi_insn_r <= {insn_signal};\n")
        code.append(f"            rvfi_rs1_addr_r <= {rs1_addr_signal};\n")
        code.append(f"            rvfi_rs2_addr_r <= {rs2_addr_signal};\n")
        code.append(f"            rvfi_rd_addr_r <= {rd_addr_signal};\n")
        code.append(f"            rvfi_rs1_rdata_r <= {rs1_data_signal};\n")
        code.append(f"            rvfi_rs2_rdata_r <= {rs2_data_signal};\n")
        code.append(f"            rvfi_rd_wdata_r <= {rd_data_signal};\n")
        code.append("            \n")
        code.append("            // Capture PC\n")
        code.append(f"            rvfi_pc_rdata_r <= {pc_signal};  // PC before instruction\n")
        code.append(f"            rvfi_pc_wdata_r <= {pc_signal} + 4;  // PC after instruction (TODO: handle branches)\n")

        if self.config.enable_mem:
            code.append("            \n")
            code.append("            // Memory access tracking\n")
            code.append("            // TODO: Connect to actual memory signals\n")
            code.append("            rvfi_mem_addr_r <= 32'h0;\n")
            code.append("            rvfi_mem_rmask_r <= 4'h0;\n")
            code.append("            rvfi_mem_wmask_r <= 4'h0;\n")
            code.append("            rvfi_mem_rdata_r <= 32'h0;\n")
            code.append("            rvfi_mem_wdata_r <= 32'h0;\n")

        code.append("        end\n")
        code.append("    end\n\n")

        return "".join(code)


def generate_rvfi_wrapper(processor_module: str,
                          config: RVFIConfig,
                          processor_signals: Dict[str, str]) -> str:
    """
    Generate a wrapper module that adds RVFI to an existing processor.

    Args:
        processor_module: Name of the processor module to wrap
        config: RVFI configuration
        processor_signals: Mapping of RVFI signal names to processor signal names

    Returns:
        Verilog code for wrapper module
    """
    gen = RVFISignalGenerator(config)

    wrapper = []
    wrapper.append(f"// RVFI Wrapper for {processor_module}\n")
    wrapper.append(f"// Generated by ISAComp RVFI Generator\n\n")
    wrapper.append(f"module {processor_module}_rvfi_wrapper (\n")
    wrapper.append("    input wire clk,\n")
    wrapper.append("    input wire reset,\n")
    wrapper.append("    input wire [31:0] reset_pc_rd,\n\n")

    # Add RVFI outputs
    wrapper.append(gen.generate_rvfi_outputs())

    # Standard processor outputs (example)
    wrapper.append("    // Processor outputs (pass through)\n")
    wrapper.append("    output wire [31:0] pc_out\n")
    wrapper.append(");\n\n")

    # Instantiate original processor
    wrapper.append(f"    // Instantiate original processor\n")
    wrapper.append(f"    wire [31:0] pc_internal;\n")
    wrapper.append(f"    wire [31:0] instruction_internal;\n")
    wrapper.append(f"    // Add more internal wires as needed\n\n")

    wrapper.append(f"    {processor_module} processor_inst (\n")
    wrapper.append("        .clk(clk),\n")
    wrapper.append("        .reset(reset),\n")
    wrapper.append("        .reset_pc_rd(reset_pc_rd)\n")
    wrapper.append("        // Add more port connections\n")
    wrapper.append("    );\n\n")

    # Add RVFI generation logic
    wrapper.append(gen.generate_rvfi_registers())
    wrapper.append(gen.generate_rvfi_update_logic(
        pc_signal=processor_signals.get('pc', 'pc_internal'),
        insn_signal=processor_signals.get('instruction', 'instruction_internal')
    ))

    wrapper.append("    // Pass through processor outputs\n")
    wrapper.append("    assign pc_out = pc_internal;\n\n")

    wrapper.append("endmodule\n")

    return "".join(wrapper)


if __name__ == "__main__":
    # Example usage
    config = RVFIConfig(xlen=32, nret=1, enable_mem=True)
    gen = RVFISignalGenerator(config)

    print("// RVFI Output Signals:")
    print(gen.generate_rvfi_outputs())
    print("\n// RVFI Registers:")
    print(gen.generate_rvfi_registers())
