"""
Verilog testbench generator with FuseSoC integration.

This module generates testbenches for ISAComp-generated processors that can:
- Load RISC-V ELF binaries using the elf-loader VPI module
- Drive clock and reset signals
- Monitor processor state and detect completion
- Integrate with FuseSoC for easy simulation
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestbenchConfig:
    """Configuration for testbench generation."""
    module_name: str = "processor"
    clock_period: int = 10  # ns
    reset_cycles: int = 5
    timeout_cycles: int = 10000
    # Memory configuration
    imem_name: str = "imem"  # Instruction memory instance name
    imem_addr_width: int = 32
    imem_data_width: int = 32
    # Optional data memory
    dmem_name: Optional[str] = None
    dmem_addr_width: int = 32
    dmem_data_width: int = 32
    # Processor interface signals
    pc_signal_name: str = "pc_rd"  # Name of PC signal in RTL
    reset_pc_signal: str = "reset_pc_rd"  # Name of reset PC port
    # Completion detection
    completion_signal: Optional[str] = None  # e.g., "halted" or specific PC value
    completion_pc: Optional[int] = None  # PC value that indicates completion
    # Memory loading method
    use_hex_loading: bool = False  # If True, use $readmemh instead of $elf_load_file

    @classmethod
    def from_isa_config(cls, isa_config, module_name: str = "processor", **overrides):
        """Create TestbenchConfig from ISAConfig."""
        from core.isa_config import ISAConfig

        config = cls(
            module_name=module_name,
            clock_period=isa_config.clock_period_ns,
            reset_cycles=isa_config.reset_cycles,
            timeout_cycles=isa_config.default_timeout_cycles,
            imem_addr_width=isa_config.imem_addr_width,
            imem_data_width=isa_config.imem_data_width,
            dmem_addr_width=isa_config.dmem_addr_width,
            dmem_data_width=isa_config.dmem_data_width,
            pc_signal_name=isa_config.pc_signal_name,
            reset_pc_signal=isa_config.reset_pc_signal,
            completion_signal=isa_config.completion_signal,
            completion_pc=isa_config.completion_address,
        )

        # Apply overrides
        for key, value in overrides.items():
            if hasattr(config, key):
                setattr(config, key, value)

        return config


class VerilogTestbenchGenerator:
    """Generate testbenches for ISAComp processors with elf-loader support."""

    def __init__(self, config: TestbenchConfig):
        self.config = config

    def generate_testbench(self) -> str:
        """Generate complete testbench Verilog code."""
        tb = []

        # Module header
        tb.append(f"`timescale 1ns/1ps\n")
        tb.append(f"module {self.config.module_name}_tb;\n\n")

        # Clock and reset
        tb.append("    // Clock and reset\n")
        tb.append("    reg clk;\n")
        tb.append("    reg reset;\n\n")

        # Processor interface signals
        tb.append("    // Processor interface\n")
        tb.append(self._generate_processor_signals())
        tb.append("\n")

        # Memory for ELF loading
        tb.append("    // Memory for ELF loading\n")
        tb.append(self._generate_memory_arrays())
        tb.append("\n")

        # DUT instantiation
        tb.append("    // Device Under Test\n")
        tb.append(self._generate_dut_instantiation())
        tb.append("\n")

        # Clock generation
        tb.append("    // Clock generation\n")
        tb.append(f"    initial clk = 0;\n")
        tb.append(f"    always #({self.config.clock_period}/2) clk = ~clk;\n\n")

        # Memory loading and initialization
        if self.config.use_hex_loading:
            tb.append("    // Hex file loading and test execution\n")
            tb.append(self._generate_hex_loading_logic())
        else:
            tb.append("    // ELF loading and test execution\n")
            tb.append(self._generate_elf_loading_logic())
        tb.append("\n")

        # Completion detection
        tb.append("    // Completion detection\n")
        tb.append(self._generate_completion_logic())
        tb.append("\n")

        # Optional: waveform dumping
        tb.append("    // Waveform dumping\n")
        tb.append("    initial begin\n")
        tb.append("        if ($test$plusargs(\"vcd\")) begin\n")
        tb.append(f"            $dumpfile(\"{self.config.module_name}_tb.vcd\");\n")
        tb.append("            $dumpvars(0, %s_tb);\n" % self.config.module_name)
        tb.append("        end\n")
        tb.append("    end\n\n")

        tb.append("endmodule\n")

        return "".join(tb)

    def _generate_processor_signals(self) -> str:
        """Generate processor-specific signals based on configuration."""
        signals = []

        # Reset value signals
        signals.append("    // Reset value signals\n")
        width = self.config.imem_data_width
        signals.append(f"    wire [{width-1}:0] {self.config.reset_pc_signal} = {width}'h0;\n")

        return "".join(signals)

    def _generate_memory_arrays(self) -> str:
        """Generate memory arrays for instruction and data memory."""
        # Note: We don't actually need memory arrays in the testbench anymore
        # The elf-loader VPI writes .mem files that the processor's $readmemh loads
        return ""

    def _generate_dut_instantiation(self) -> str:
        """Generate DUT instantiation."""
        inst = []

        inst.append(f"    {self.config.module_name} dut (\n")
        inst.append("        .clk(clk),\n")
        inst.append("        .reset(reset),\n")
        inst.append(f"        .{self.config.reset_pc_signal}({self.config.reset_pc_signal})\n")
        inst.append("        // Add other ports as needed\n")
        inst.append("    );\n")

        return "".join(inst)

    def _generate_elf_loading_logic(self) -> str:
        """Generate ELF loading and initialization logic using elf-loader VPI."""
        logic = []

        logic.append("    integer i;\n")
        logic.append("    integer elf_size;\n")
        logic.append("    reg [31:0] elf_data;\n")
        logic.append("    integer mem_file;\n")
        logic.append("    string elf_file;\n\n")

        logic.append("    initial begin\n")
        logic.append("        // Get ELF file from plusargs\n")
        logic.append("        if (!$value$plusargs(\"elf_load=%s\", elf_file)) begin\n")
        logic.append("            $display(\"ERROR: No ELF file specified. Use +elf_load=<file.elf>\");\n")
        logic.append("            $finish;\n")
        logic.append("        end\n\n")

        logic.append("        // Load ELF file using VPI\n")
        logic.append("        $display(\"Loading ELF file: %s\", elf_file);\n")
        logic.append("        $elf_load_file(elf_file);\n")
        logic.append("        elf_size = $elf_get_size();\n")
        logic.append("        $display(\"ELF size: %0d bytes\", elf_size);\n\n")

        logic.append("        // Write ELF data directly to processor's instruction memory\n")
        if self.config.dmem_name:
            logic.append("        // The ELF file contains both .text (code) and .data (initialized data) sections\n")
            logic.append("        // We load everything into both imem and dmem at the appropriate addresses\n")
        logic.append("        $display(\"Loading %0d bytes into instruction memory...\", elf_size);\n")
        logic.append("        for (i = 0; i < elf_size; i = i + 4) begin\n")
        logic.append("            elf_data = $elf_read_32(i);\n")
        logic.append(f"            // Load into imem (word-addressed)\n")
        logic.append(f"            dut.{self.config.imem_name}[i/4] = elf_data;\n")
        if self.config.dmem_name:
            logic.append(f"            // Also load into dmem for .data section (word-addressed)\n")
            logic.append(f"            dut.{self.config.dmem_name}[i/4] = elf_data;\n")
        logic.append("        end\n")
        if self.config.dmem_name:
            logic.append("        $display(\"Loaded program into instruction and data memory\");\n\n")
        else:
            logic.append("        $display(\"Loaded program into instruction memory\");\n\n")

        # Also create empty rf.mem and dmem.mem if they don't exist
        logic.append("        // Create empty register file if needed\n")
        logic.append("        mem_file = $fopen(\"rf.mem\", \"w\");\n")
        logic.append("        if (mem_file != 0) begin\n")
        logic.append("            $fclose(mem_file);\n")
        logic.append("        end\n\n")

        if self.config.dmem_name:
            logic.append("        // Create empty data memory if needed\n")
            logic.append(f"        mem_file = $fopen(\"{self.config.dmem_name}.mem\", \"w\");\n")
            logic.append("        if (mem_file != 0) begin\n")
            logic.append("            $fclose(mem_file);\n")
            logic.append("        end\n\n")

        logic.append("        // Create empty dmem.mem if needed\n")
        logic.append("        mem_file = $fopen(\"dmem.mem\", \"w\");\n")
        logic.append("        if (mem_file != 0) begin\n")
        logic.append("            $fclose(mem_file);\n")
        logic.append("        end\n\n")

        logic.append("        // Reset sequence - start before memories load\n")
        logic.append("        reset = 1;\n\n")

        logic.append("        // Wait for memories to be loaded by $readmemh\n")
        logic.append("        #10;\n\n")

        logic.append("        // Release reset and start execution\n")
        logic.append(f"        repeat({self.config.reset_cycles}) @(posedge clk);\n")
        logic.append("        reset = 0;\n")
        logic.append("        $display(\"Reset released, starting execution...\");\n")
        logic.append(f"        $display(\"Initial PC: 0x%08x\", dut.{self.config.pc_signal_name});\n")
        logic.append("    end\n")

        return "".join(logic)

    def _generate_hex_loading_logic(self) -> str:
        """Generate hex file loading logic using $readmemh."""
        logic = []

        logic.append("    initial begin\n")
        logic.append("        // Wait for memories to be loaded by $readmemh\n")
        logic.append("        #10;\n\n")

        logic.append("        // Reset sequence\n")
        logic.append("        reset = 1;\n")
        logic.append(f"        repeat({self.config.reset_cycles}) @(posedge clk);\n")
        logic.append("        reset = 0;\n")
        logic.append("        $display(\"Reset released, starting execution...\");\n")
        logic.append(f"        $display(\"Initial PC: 0x%08x\", dut.{self.config.pc_signal_name});\n")
        logic.append("    end\n")

        return "".join(logic)

    def _generate_completion_logic(self) -> str:
        """Generate logic to detect test completion."""
        logic = []

        logic.append("    integer cycle_count;\n")
        logic.append("    reg [31:0] pass_pc;\n")
        logic.append("    reg [31:0] fail_pc;\n")
        logic.append("    reg pass_pc_valid;\n")
        logic.append("    reg fail_pc_valid;\n\n")

        logic.append("    initial begin\n")
        logic.append("        cycle_count = 0;\n")
        logic.append("        pass_pc_valid = 0;\n")
        logic.append("        fail_pc_valid = 0;\n\n")

        logic.append("        // Extract pass/fail addresses from ELF symbols\n")
        logic.append("        if ($value$plusargs(\"pass_addr=%h\", pass_pc)) begin\n")
        logic.append("            pass_pc_valid = 1;\n")
        logic.append("            $display(\"Pass address: 0x%08x\", pass_pc);\n")
        logic.append("        end\n\n")

        logic.append("        if ($value$plusargs(\"fail_addr=%h\", fail_pc)) begin\n")
        logic.append("            fail_pc_valid = 1;\n")
        logic.append("            $display(\"Fail address: 0x%08x\", fail_pc);\n")
        logic.append("        end\n\n")

        logic.append("        @(negedge reset);  // Wait for reset to deassert\n\n")

        logic.append("        // Monitor execution\n")
        logic.append("        forever begin\n")
        logic.append("            @(posedge clk);\n")
        logic.append("            cycle_count = cycle_count + 1;\n\n")

        pc_sig = f"dut.{self.config.pc_signal_name}"

        logic.append("            // Debug: Print PC every 100 cycles\n")
        logic.append("            if (cycle_count % 100 == 0) begin\n")
        logic.append(f"                $display(\"Cycle %0d: PC = 0x%08x\", cycle_count, {pc_sig});\n")
        logic.append("            end\n\n")

        # Timeout check
        logic.append(f"            if (cycle_count >= {self.config.timeout_cycles}) begin\n")
        logic.append("                $display(\"ERROR: Timeout after %0d cycles\", cycle_count);\n")
        logic.append(f"                $display(\"Final PC: 0x%08x\", {pc_sig});\n")
        logic.append("                $display(\"FAILED\");\n")
        logic.append("                $finish(1);\n")
        logic.append("            end\n\n")

        # Pass/fail detection
        logic.append("            // Check for pass condition\n")
        logic.append(f"            if (pass_pc_valid && {pc_sig} == pass_pc) begin\n")
        logic.append("                $display(\"*** TEST PASSED *** at cycle %0d (PC=0x%08x)\", cycle_count, pass_pc);\n")
        logic.append("                $finish(0);\n")
        logic.append("            end\n\n")

        logic.append("            // Check for fail condition\n")
        logic.append(f"            if (fail_pc_valid && {pc_sig} == fail_pc) begin\n")
        logic.append("                $display(\"*** TEST FAILED *** at cycle %0d (PC=0x%08x)\", cycle_count, fail_pc);\n")
        logic.append("                $finish(1);\n")
        logic.append("            end\n\n")

        # Legacy completion detection
        if self.config.completion_signal:
            logic.append(f"            // Check completion signal\n")
            logic.append(f"            if (dut.{self.config.completion_signal}) begin\n")
            logic.append("                $display(\"Test completed at cycle %0d\", cycle_count);\n")
            logic.append("                $finish(0);\n")
            logic.append("            end\n")
        elif self.config.completion_pc:
            logic.append(f"            // Check for completion PC (legacy)\n")
            width = self.config.imem_data_width
            logic.append(f"            if ({pc_sig} == {width}'h{self.config.completion_pc:08x}) begin\n")
            logic.append("                $display(\"Test completed at cycle %0d (PC reached 0x%08x)\", ")
            logic.append(f"cycle_count, {width}'h{self.config.completion_pc:08x});\n")
            logic.append("                $finish(0);\n")
            logic.append("            end\n")

        logic.append("        end\n")
        logic.append("    end\n")

        return "".join(logic)


class FuseSoCCoreGenerator:
    """Generate FuseSoC .core files for ISAComp processors."""

    def __init__(self, core_name: str, module_name: str = "processor"):
        self.core_name = core_name
        self.module_name = module_name
        self.version = "1.0.0"

    def generate_core_file(self,
                          rtl_files: List[str],
                          testbench_file: str,
                          toplevel: str) -> str:
        """Generate FuseSoC .core file in CAPI2 format."""

        core = []

        # CAPI version
        core.append("CAPI=2:\n\n")

        # Core metadata
        core.append(f"name: isacomp:{self.core_name}:{self.version}\n")
        core.append(f"description: ISAComp generated {self.core_name} processor\n\n")

        # Filesets
        core.append("filesets:\n")

        # RTL files
        core.append("  rtl:\n")
        core.append("    files:\n")
        for rtl_file in rtl_files:
            core.append(f"      - {rtl_file}\n")
        core.append("    file_type: systemVerilogSource\n\n")

        # Testbench files
        core.append("  tb:\n")
        core.append("    files:\n")
        core.append(f"      - {testbench_file}\n")
        core.append("    file_type: systemVerilogSource\n")
        core.append("    depend:\n")
        core.append("      - ::elf-loader\n\n")

        # Parameters
        core.append("parameters:\n")
        core.append("  elf_load:\n")
        core.append("    datatype: file\n")
        core.append("    description: ELF file to load for testing\n")
        core.append("    paramtype: plusarg\n")
        core.append("  pass_addr:\n")
        core.append("    datatype: str\n")
        core.append("    description: PC address that indicates test pass\n")
        core.append("    paramtype: plusarg\n")
        core.append("  fail_addr:\n")
        core.append("    datatype: str\n")
        core.append("    description: PC address that indicates test fail\n")
        core.append("    paramtype: plusarg\n\n")

        # Targets
        core.append("targets:\n")

        # Default target (for synthesis/implementation)
        core.append("  default:\n")
        core.append("    filesets: [rtl]\n")
        core.append(f"    toplevel: {self.module_name}\n\n")

        # Simulation target
        core.append("  sim:\n")
        core.append("    default_tool: icarus\n")
        core.append("    filesets: [rtl, tb]\n")
        core.append(f"    toplevel: {toplevel}\n")
        core.append("    parameters: [elf_load, pass_addr, fail_addr]\n")
        core.append("    tools:\n")
        core.append("      icarus:\n")
        core.append("        iverilog_options:\n")
        core.append("          - -g2012  # Enable SystemVerilog support\n")
        core.append("      modelsim:\n")
        core.append("        vlog_options:\n")
        core.append("          - -sv\n")
        core.append("      verilator:\n")
        core.append("        mode: cc\n")
        core.append("        verilator_options:\n")
        core.append("          - --trace\n")
        core.append("          - -Wall\n\n")

        return "".join(core)


def generate_testbench_files(module_name: str,
                            rtl_file: str,
                            output_dir: Path,
                            config: Optional[TestbenchConfig] = None) -> Dict[str, Path]:
    """
    Generate testbench and FuseSoC files for a processor module.

    Args:
        module_name: Name of the processor module
        rtl_file: Path to the RTL file
        output_dir: Directory to write output files
        config: Optional testbench configuration

    Returns:
        Dictionary with paths to generated files
    """
    if config is None:
        config = TestbenchConfig(module_name=module_name)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate testbench
    tb_gen = VerilogTestbenchGenerator(config)
    testbench_code = tb_gen.generate_testbench()
    testbench_file = output_dir / f"{module_name}_tb.sv"
    testbench_file.write_text(testbench_code)

    # Generate FuseSoC core file
    core_gen = FuseSoCCoreGenerator(core_name=module_name, module_name=module_name)
    core_content = core_gen.generate_core_file(
        rtl_files=[str(Path(rtl_file).name)],
        testbench_file=str(testbench_file.name),
        toplevel=f"{module_name}_tb"
    )
    core_file = output_dir / f"{module_name}.core"
    core_file.write_text(core_content)

    return {
        'testbench': testbench_file,
        'core': core_file
    }


if __name__ == "__main__":
    # Example usage
    config = TestbenchConfig(
        module_name="riscv32_processor",
        imem_name="imem",
        completion_pc=0xFFFFFFFC  # Example completion address
    )

    files = generate_testbench_files(
        module_name="riscv32_processor",
        rtl_file="riscv32_processor.v",
        output_dir=Path("examples/verilog/build"),
        config=config
    )

    print(f"Generated testbench: {files['testbench']}")
    print(f"Generated core file: {files['core']}")
