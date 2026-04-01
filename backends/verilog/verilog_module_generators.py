"""
Verilog module generators for specialized hardware components.

This module provides classes to generate parameterized Verilog code for
common hardware components like multiplexers, counters, and hazard
detection units.
"""

from typing import List, Dict, Optional
from dataclasses import dataclass, field


@dataclass
class MuxGenerator:
    """Generate Verilog for multiplexer modules."""

    name: str
    num_inputs: int
    data_width: int = 32
    select_type: str = 'binary'  # 'binary', 'one_hot', or 'priority'
    has_default: bool = False  # For priority muxes with default value

    def generate_module(self) -> str:
        """Generate complete Verilog module for the multiplexer."""
        if self.select_type == 'one_hot':
            return self._generate_one_hot_mux()
        elif self.select_type == 'priority':
            return self._generate_priority_mux()
        else:
            return self._generate_binary_mux()

    def _generate_binary_mux(self) -> str:
        """Generate binary-encoded multiplexer."""
        select_width = (self.num_inputs - 1).bit_length() if self.num_inputs > 1 else 1

        verilog = f"module {self.name}(\n"

        # Input ports
        for i in range(self.num_inputs):
            verilog += f"    input wire [{self.data_width-1}:0] in_{i},\n"

        # Select signal
        verilog += f"    input wire [{select_width-1}:0] sel,\n"

        # Output port
        verilog += f"    output logic [{self.data_width-1}:0] out\n"
        verilog += ");\n\n"

        # Mux logic using case statement
        verilog += "    always_comb begin\n"
        verilog += "        case (sel)\n"

        for i in range(self.num_inputs):
            verilog += f"            {select_width}'d{i}: out = in_{i};\n"

        verilog += f"            default: out = {self.data_width}'d0;\n"
        verilog += "        endcase\n"
        verilog += "    end\n\n"
        verilog += "endmodule\n"

        return verilog

    def _generate_one_hot_mux(self) -> str:
        """Generate one-hot encoded multiplexer."""
        verilog = f"module {self.name}(\n"

        # Input ports
        for i in range(self.num_inputs):
            verilog += f"    input wire [{self.data_width-1}:0] in_{i},\n"

        # One-hot select signals
        for i in range(self.num_inputs):
            verilog += f"    input wire sel_{i},\n"

        # Output port
        verilog = verilog.rstrip(',\n') + ',\n'
        verilog += f"    output logic [{self.data_width-1}:0] out\n"
        verilog += ");\n\n"

        # OR-based mux logic
        verilog += "    always_comb begin\n"
        verilog += "        out = "

        terms = [f"(sel_{i} ? in_{i} : {self.data_width}'d0)" for i in range(self.num_inputs)]
        verilog += " | ".join(terms) + ";\n"

        verilog += "    end\n\n"
        verilog += "endmodule\n"

        return verilog

    def _generate_priority_mux(self) -> str:
        """Generate priority-encoded multiplexer with optional default value."""
        verilog = f"module {self.name}(\n"

        # Input ports
        for i in range(self.num_inputs):
            verilog += f"    input wire [{self.data_width-1}:0] in_{i},\n"

        # Priority select signals (one for each input)
        for i in range(self.num_inputs):
            verilog += f"    input wire sel_{i},\n"

        # Optional default input
        if self.has_default:
            verilog += f"    input wire [{self.data_width-1}:0] default_in,\n"

        # Output port
        verilog = verilog.rstrip(',\n') + ',\n'
        verilog += f"    output logic [{self.data_width-1}:0] out\n"
        verilog += ");\n\n"

        # Priority-based mux logic using if-else chain
        verilog += "    always_comb begin\n"

        # Handle case with no inputs (only default)
        if self.num_inputs == 0:
            # No inputs - just assign default
            if self.has_default:
                verilog += "        out = default_in;\n"
            else:
                verilog += f"        out = {self.data_width}'d0;\n"
        else:
            # First select has highest priority
            for i in range(self.num_inputs):
                if i == 0:
                    verilog += f"        if (sel_{i}) begin\n"
                else:
                    verilog += f"        end else if (sel_{i}) begin\n"
                verilog += f"            out = in_{i};\n"

            # Default case
            verilog += "        end else begin\n"
            if self.has_default:
                verilog += "            out = default_in;\n"
            else:
                verilog += f"            out = {self.data_width}'d0;\n"
            verilog += "        end\n"

        verilog += "    end\n\n"
        verilog += "endmodule\n"

        return verilog

    def get_port_connections(self, input_signals: List[str], select_signal, output_signal: str,
                            default_signal: Optional[str] = None) -> str:
        """Generate instantiation with port connections.

        Args:
            input_signals: List of input signal names
            select_signal: For binary mux: string signal name. For one-hot/priority: list of select signals
            output_signal: Output signal name
            default_signal: Default input signal name (for priority muxes with default)
        """
        connections = []

        for i, sig in enumerate(input_signals):
            connections.append(f"    .in_{i}({sig})")

        if self.select_type in ['one_hot', 'priority']:
            # select_signal should be a list of individual select signals
            if isinstance(select_signal, list):
                for i, sel_sig in enumerate(select_signal):
                    connections.append(f"    .sel_{i}({sel_sig})")
            else:
                # Fallback: assume it's a vector signal
                for i in range(self.num_inputs):
                    connections.append(f"    .sel_{i}({select_signal}[{i}])")
        else:
            connections.append(f"    .sel({select_signal})")

        # Add default input port for priority muxes with default
        if self.select_type == 'priority' and self.has_default and default_signal:
            connections.append(f"    .default_in({default_signal})")

        connections.append(f"    .out({output_signal})")

        return f"{self.name} {self.name}_inst(\n" + ",\n".join(connections) + "\n);"


@dataclass
class CounterGenerator:
    """Generate Verilog for counter modules."""

    name: str
    width: int = 32
    max_value: Optional[int] = None
    has_enable: bool = True
    has_reset_value: bool = True
    count_direction: str = 'up'  # 'up' or 'down'

    def generate_module(self) -> str:
        """Generate complete Verilog module for the counter."""
        verilog = f"module {self.name}(\n"
        verilog += "    input wire clk,\n"
        verilog += "    input wire reset,\n"

        if self.has_reset_value:
            verilog += f"    input wire [{self.width-1}:0] reset_value,\n"

        if self.has_enable:
            verilog += "    input wire enable,\n"

        verilog += f"    output logic [{self.width-1}:0] count\n"
        verilog += ");\n\n"

        # Counter logic
        verilog += "    always_ff @(posedge clk) begin\n"
        verilog += "        if (reset) begin\n"

        if self.has_reset_value:
            verilog += "            count <= reset_value;\n"
        else:
            verilog += f"            count <= {self.width}'d0;\n"

        verilog += "        end"

        if self.has_enable:
            verilog += " else if (enable) begin\n"
        else:
            verilog += " else begin\n"

        # Count operation
        if self.max_value is not None:
            if self.count_direction == 'up':
                verilog += f"            if (count >= {self.width}'d{self.max_value}) begin\n"
                verilog += f"                count <= {self.width}'d0;\n"
                verilog += "            end else begin\n"
                verilog += "                count <= count + 1;\n"
                verilog += "            end\n"
            else:  # down
                verilog += f"            if (count == {self.width}'d0) begin\n"
                verilog += f"                count <= {self.width}'d{self.max_value};\n"
                verilog += "            end else begin\n"
                verilog += "                count <= count - 1;\n"
                verilog += "            end\n"
        else:
            if self.count_direction == 'up':
                verilog += "            count <= count + 1;\n"
            else:  # down
                verilog += "            count <= count - 1;\n"

        verilog += "        end\n"
        verilog += "    end\n\n"
        verilog += "endmodule\n"

        return verilog

    def get_port_connections(self, enable_signal: Optional[str] = None,
                            reset_value_signal: Optional[str] = None,
                            output_signal: str = "count_out") -> str:
        """Generate instantiation with port connections."""
        connections = [
            "    .clk(clk)",
            "    .reset(reset)"
        ]

        if self.has_reset_value and reset_value_signal:
            connections.append(f"    .reset_value({reset_value_signal})")

        if self.has_enable and enable_signal:
            connections.append(f"    .enable({enable_signal})")

        connections.append(f"    .count({output_signal})")

        return f"{self.name} {self.name}_inst(\n" + ",\n".join(connections) + "\n);"


@dataclass
class LatencyCounterGenerator:
    """Generate Verilog for latency counter FSMs.

    This is a unified counter for both static and variable latency operations.
    The FSM has three states:
    - Idle (counter = 0): Wait for start signal
    - Busy (0 < counter < target): Incrementing each cycle
    - Complete (counter == target): Signal completion, return to idle

    Supports two modes:
    - Static latency: Fixed target value
    - Variable latency: Random target using $random (for testing)
    """

    name: str
    width: int = 4  # Counter width (enough for 0-15)
    latency_mode: str = 'static'  # 'static' or 'variable'
    static_latency: int = 2  # For static mode: fixed latency cycles
    min_latency: int = 2    # For variable mode: minimum random latency
    max_latency: int = 15   # For variable mode: maximum random latency

    def generate_inline_logic(self, counter_reg: str, target_reg: Optional[str],
                              start_expr: str, complete_name: str,
                              idle_name: Optional[str] = None) -> Dict[str, str]:
        """Generate inline Verilog logic (not a separate module).

        Returns dict with:
        - 'declarations': Register declarations
        - 'comb_logic': Combinational assignments
        - 'seq_logic': Sequential always block
        """
        result = {'declarations': '', 'comb_logic': '', 'seq_logic': ''}

        if self.latency_mode == 'variable':
            # Variable latency: use random target
            result['declarations'] += f"    reg [{self.width-1}:0] {counter_reg};  // Latency counter\n"
            result['declarations'] += f"    reg [{self.width-1}:0] {target_reg};   // Random target ({self.min_latency}-{self.max_latency})\n"

            # Complete when counter reaches target (and not idle)
            result['comb_logic'] += f"    assign {complete_name} = ({counter_reg} != {self.width}'d0) && ({counter_reg} == {target_reg});\n"
            if idle_name:
                result['comb_logic'] += f"    assign {idle_name} = ({counter_reg} == {self.width}'d0);\n"

            # Sequential logic with random target
            latency_range = self.max_latency - self.min_latency
            result['seq_logic'] += f"    // Latency counter FSM (random {self.min_latency}-{self.max_latency} cycles)\n"
            result['seq_logic'] += f"    always @(posedge clk) begin\n"
            result['seq_logic'] += f"        if (reset) begin\n"
            result['seq_logic'] += f"            {counter_reg} <= {self.width}'d0;\n"
            result['seq_logic'] += f"            {target_reg} <= {self.width}'d{self.min_latency};\n"
            result['seq_logic'] += f"        end else begin\n"
            result['seq_logic'] += f"            if ({counter_reg} == {self.width}'d0) begin\n"
            result['seq_logic'] += f"                if ({start_expr}) begin\n"
            result['seq_logic'] += f"                    {counter_reg} <= {self.width}'d1;\n"
            result['seq_logic'] += f"                    {target_reg} <= ({self.width}'d{self.min_latency}) + ($random & {self.width}'d{latency_range});\n"
            result['seq_logic'] += f"                end\n"
            result['seq_logic'] += f"            end else if ({counter_reg} == {target_reg}) begin\n"
            result['seq_logic'] += f"                {counter_reg} <= {self.width}'d0;\n"
            result['seq_logic'] += f"            end else begin\n"
            result['seq_logic'] += f"                {counter_reg} <= {counter_reg} + {self.width}'d1;\n"
            result['seq_logic'] += f"            end\n"
            result['seq_logic'] += f"        end\n"
            result['seq_logic'] += f"    end\n"

        else:
            # Static latency: fixed target
            # Latency 0 = no stall (combinational/instant memory)
            # Latency N = N cycles of stall (memory takes N cycles to respond)
            import math

            if self.static_latency == 0:
                counter_bits = 2  # Minimal counter
                result['declarations'] += f"    reg [{counter_bits-1}:0] {counter_reg};  // Latency counter (always complete for latency-0)\n"

                # Complete is always true for latency 0 - no stall needed
                result['comb_logic'] += f"    assign {complete_name} = 1'b1;  // Latency 0: always complete (no stall)\n"
                if idle_name:
                    result['comb_logic'] += f"    assign {idle_name} = 1'b1;  // Latency 0: always idle\n"

                # No FSM needed for latency 0
                result['seq_logic'] += f"    // Latency counter FSM (latency 0) - no stall needed\n"
                result['seq_logic'] += f"    always @(posedge clk) begin\n"
                result['seq_logic'] += f"        if (reset) begin\n"
                result['seq_logic'] += f"            {counter_reg} <= {counter_bits}'d0;\n"
                result['seq_logic'] += f"        end\n"
                result['seq_logic'] += f"    end\n"
            else:
                # For latency N > 0, stall for N cycles
                counter_bits = max(2, math.ceil(math.log2(self.static_latency + 1)))

                result['declarations'] += f"    reg [{counter_bits-1}:0] {counter_reg};  // Latency counter (0=idle, {self.static_latency}=complete)\n"

                # Complete when counter reaches target
                result['comb_logic'] += f"    assign {complete_name} = ({counter_reg} == {counter_bits}'d{self.static_latency});\n"
                if idle_name:
                    result['comb_logic'] += f"    assign {idle_name} = ({counter_reg} == {counter_bits}'d0);\n"

                # Sequential logic with fixed target
                result['seq_logic'] += f"    // Latency counter FSM ({self.static_latency}-cycle stall)\n"
                result['seq_logic'] += f"    always @(posedge clk) begin\n"
                result['seq_logic'] += f"        if (reset) begin\n"
                result['seq_logic'] += f"            {counter_reg} <= {counter_bits}'d0;\n"
                result['seq_logic'] += f"        end else begin\n"
                result['seq_logic'] += f"            if ({counter_reg} == {counter_bits}'d0) begin\n"
                result['seq_logic'] += f"                if ({start_expr}) begin\n"
                result['seq_logic'] += f"                    {counter_reg} <= {counter_bits}'d1;\n"
                result['seq_logic'] += f"                end\n"
                result['seq_logic'] += f"            end else if ({counter_reg} == {counter_bits}'d{self.static_latency}) begin\n"
                result['seq_logic'] += f"                {counter_reg} <= {counter_bits}'d0;\n"
                result['seq_logic'] += f"            end else begin\n"
                result['seq_logic'] += f"                {counter_reg} <= {counter_reg} + {counter_bits}'d1;\n"
                result['seq_logic'] += f"            end\n"
                result['seq_logic'] += f"        end\n"
                result['seq_logic'] += f"    end\n"

        return result


@dataclass
class HazardDetectorGenerator:
    """Generate Verilog for pipeline hazard detection units."""

    name: str
    num_sources: int = 2
    num_destinations: int = 1
    address_width: int = 5  # Register file address width

    def generate_module(self) -> str:
        """Generate complete Verilog module for hazard detection."""
        verilog = f"module {self.name}(\n"

        # Source register inputs (from decode stage)
        for i in range(self.num_sources):
            verilog += f"    input wire [{self.address_width-1}:0] src_{i}_addr,\n"
            verilog += f"    input wire src_{i}_valid,\n"

        # Destination register inputs (from execute/memory/writeback stages)
        for i in range(self.num_destinations):
            verilog += f"    input wire [{self.address_width-1}:0] dest_{i}_addr,\n"
            verilog += f"    input wire dest_{i}_valid,\n"
            verilog += f"    input wire dest_{i}_ready,\n"

        # Hazard detection outputs
        verilog += "    output logic stall,\n"
        verilog += "    output logic flush,\n"

        # Forward control outputs
        for i in range(self.num_sources):
            verilog += f"    output logic [{self.num_destinations-1}:0] forward_src_{i}\n"
            if i < self.num_sources - 1:
                verilog += ","

        verilog += "\n);\n\n"

        # Hazard detection logic
        verilog += "    always_comb begin\n"
        verilog += "        stall = 1'b0;\n"
        verilog += "        flush = 1'b0;\n"

        for i in range(self.num_sources):
            verilog += f"        forward_src_{i} = {self.num_destinations}'d0;\n"

        verilog += "\n"

        # Check for hazards
        for src_idx in range(self.num_sources):
            verilog += f"        // Check source {src_idx} for hazards\n"
            verilog += f"        if (src_{src_idx}_valid) begin\n"

            for dest_idx in range(self.num_destinations):
                verilog += f"            if (dest_{dest_idx}_valid && " \
                          f"(src_{src_idx}_addr == dest_{dest_idx}_addr)) begin\n"
                verilog += f"                if (dest_{dest_idx}_ready) begin\n"
                verilog += f"                    // Forward from destination {dest_idx}\n"
                verilog += f"                    forward_src_{src_idx}[{dest_idx}] = 1'b1;\n"
                verilog += "                end else begin\n"
                verilog += "                    // Data not ready - stall pipeline\n"
                verilog += "                    stall = 1'b1;\n"
                verilog += "                end\n"
                verilog += "            end\n"

            verilog += "        end\n\n"

        verilog += "    end\n\n"
        verilog += "endmodule\n"

        return verilog

    def get_port_connections(self, src_addrs: List[str], src_valids: List[str],
                            dest_addrs: List[str], dest_valids: List[str],
                            dest_readys: List[str],
                            stall_signal: str = "stall",
                            flush_signal: str = "flush",
                            forward_signals: List[str] = None) -> str:
        """Generate instantiation with port connections."""
        connections = []

        for i, (addr, valid) in enumerate(zip(src_addrs, src_valids)):
            connections.append(f"    .src_{i}_addr({addr})")
            connections.append(f"    .src_{i}_valid({valid})")

        for i, (addr, valid, ready) in enumerate(zip(dest_addrs, dest_valids, dest_readys)):
            connections.append(f"    .dest_{i}_addr({addr})")
            connections.append(f"    .dest_{i}_valid({valid})")
            connections.append(f"    .dest_{i}_ready({ready})")

        connections.append(f"    .stall({stall_signal})")
        connections.append(f"    .flush({flush_signal})")

        if forward_signals:
            for i, sig in enumerate(forward_signals):
                connections.append(f"    .forward_src_{i}({sig})")

        return f"{self.name} {self.name}_inst(\n" + ",\n".join(connections) + "\n);"


def generate_module_library() -> str:
    """Generate a complete Verilog file with all common module types."""
    verilog = "// Auto-generated Verilog module library\n"
    verilog += "// Contains: MUX, Counter, ALU, Hazard Detector\n\n"

    # Generate a 4-input mux
    mux4 = MuxGenerator(name="mux_4to1", num_inputs=4, data_width=32)
    verilog += mux4.generate_module() + "\n"

    # Generate an 8-input mux
    mux8 = MuxGenerator(name="mux_8to1", num_inputs=8, data_width=32)
    verilog += mux8.generate_module() + "\n"

    # Generate a counter
    counter = CounterGenerator(name="counter_32b", width=32)
    verilog += counter.generate_module() + "\n"

    # Generate hazard detector
    hazard = HazardDetectorGenerator(name="hazard_detector", num_sources=2, num_destinations=2)
    verilog += hazard.generate_module() + "\n"

    return verilog


@dataclass
class ReadOnlyCacheGenerator:
    """Generate parameterized read-only cache Verilog module.

    This generates a complete read-only cache implementation including:
    - Tag array storage
    - Valid bit tracking
    - Data array storage
    - Hit/miss detection logic
    - Refill FSM for cache misses
    - Multiple read ports support
    - Configurable replacement policy
    """

    name: str
    num_read_ports: int = 1
    block_size: int = 32        # bytes per cache line
    associativity: int = 1      # 1 = direct-mapped
    num_rows: int = 64          # number of cache sets
    address_width: int = 32
    data_width: int = 32
    replacement_policy: str = 'lru'  # 'lru', 'random', 'fifo'
    has_flush: bool = False     # Whether cache has flush input for invalidation

    def __post_init__(self):
        """Calculate derived parameters."""
        self.offset_width = (self.block_size - 1).bit_length()
        self.index_width = (self.num_rows - 1).bit_length()
        self.tag_width = self.address_width - self.offset_width - self.index_width
        self.words_per_line = self.block_size * 8 // self.data_width

    def generate_module(self) -> str:
        """Generate complete Verilog module for the read-only cache."""
        verilog = self._generate_module_header()
        verilog += self._generate_parameters()
        verilog += self._generate_storage_arrays()
        verilog += self._generate_address_decoding()
        verilog += self._generate_hit_logic()
        verilog += self._generate_read_logic()
        verilog += self._generate_refill_fsm()
        verilog += self._generate_replacement_logic()
        verilog += "endmodule\n"
        return verilog

    def _generate_module_header(self) -> str:
        """Generate module declaration with ports."""
        verilog = f"module {self.name} #(\n"
        verilog += f"    parameter BLOCK_SIZE = {self.block_size},\n"
        verilog += f"    parameter ASSOCIATIVITY = {self.associativity},\n"
        verilog += f"    parameter NUM_ROWS = {self.num_rows},\n"
        verilog += f"    parameter ADDR_WIDTH = {self.address_width},\n"
        verilog += f"    parameter DATA_WIDTH = {self.data_width}\n"
        verilog += ")(\n"
        verilog += "    input  wire clk,\n"
        verilog += "    input  wire reset,\n"

        # Read ports
        for i in range(self.num_read_ports):
            verilog += f"\n    // Read port {i}\n"
            verilog += f"    input  wire [ADDR_WIDTH-1:0] read_addr_{i},\n"
            verilog += f"    input  wire read_req_{i},\n"
            verilog += f"    output reg [DATA_WIDTH-1:0] read_data_{i},\n"
            verilog += f"    output reg read_valid_{i},\n"

        # Flush input (optional - for fence.i, sfence.vma, etc.)
        if self.has_flush:
            verilog += "\n    // Flush control (invalidates all cache entries)\n"
            verilog += "    input  wire flush,\n"

        # Refill interface
        verilog += "\n    // Refill interface to backing memory\n"
        verilog += "    output reg [ADDR_WIDTH-1:0] refill_addr,\n"
        verilog += "    output reg refill_req,\n"
        verilog += "    input  wire [DATA_WIDTH-1:0] refill_data,\n"
        verilog += "    input  wire refill_valid\n"
        verilog += ");\n\n"
        return verilog

    def _generate_parameters(self) -> str:
        """Generate local parameters."""
        verilog = "    // Derived parameters\n"
        verilog += f"    localparam OFFSET_WIDTH = {self.offset_width};\n"
        verilog += f"    localparam INDEX_WIDTH = {self.index_width};\n"
        verilog += f"    localparam TAG_WIDTH = ADDR_WIDTH - OFFSET_WIDTH - INDEX_WIDTH;\n"
        verilog += f"    localparam WORDS_PER_LINE = {self.words_per_line};\n"
        verilog += f"    localparam WORD_OFFSET_WIDTH = {(self.words_per_line - 1).bit_length() if self.words_per_line > 1 else 1};\n\n"
        return verilog

    def _generate_storage_arrays(self) -> str:
        """Generate tag, valid, and data arrays."""
        verilog = "    // Storage arrays\n"

        if self.associativity == 1:
            # Direct-mapped cache
            verilog += "    reg [TAG_WIDTH-1:0] tag_array [0:NUM_ROWS-1];\n"
            verilog += "    reg valid_array [0:NUM_ROWS-1];\n"
            verilog += "    reg [DATA_WIDTH*WORDS_PER_LINE-1:0] data_array [0:NUM_ROWS-1];\n"
        else:
            # Set-associative cache - 2D arrays [row][way]
            verilog += f"    reg [TAG_WIDTH-1:0] tag_array [0:NUM_ROWS-1][0:ASSOCIATIVITY-1];\n"
            verilog += f"    reg valid_array [0:NUM_ROWS-1][0:ASSOCIATIVITY-1];\n"
            verilog += f"    reg [DATA_WIDTH*WORDS_PER_LINE-1:0] data_array [0:NUM_ROWS-1][0:ASSOCIATIVITY-1];\n"

            if self.replacement_policy == 'lru':
                # LRU tracking for set-associative
                lru_width = self.associativity - 1
                verilog += f"    reg [{lru_width}:0] lru_array [0:NUM_ROWS-1];\n"

        verilog += "\n"
        return verilog

    def _generate_address_decoding(self) -> str:
        """Generate address field extraction."""
        verilog = "    // Address decoding\n"

        for i in range(self.num_read_ports):
            verilog += f"    wire [TAG_WIDTH-1:0] tag_{i} = read_addr_{i}[ADDR_WIDTH-1:ADDR_WIDTH-TAG_WIDTH];\n"
            verilog += f"    wire [INDEX_WIDTH-1:0] index_{i} = read_addr_{i}[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH];\n"
            if self.words_per_line > 1:
                verilog += f"    wire [WORD_OFFSET_WIDTH-1:0] word_offset_{i} = read_addr_{i}[OFFSET_WIDTH-1:OFFSET_WIDTH-WORD_OFFSET_WIDTH];\n"
            verilog += "\n"

        return verilog

    def _generate_hit_logic(self) -> str:
        """Generate cache hit detection logic."""
        verilog = "    // Hit detection\n"

        for i in range(self.num_read_ports):
            if self.associativity == 1:
                # Direct-mapped
                verilog += f"    wire hit_{i} = valid_array[index_{i}] && (tag_array[index_{i}] == tag_{i});\n"
            else:
                # Set-associative - check all ways using 2D array [index][way]
                verilog += f"    wire [{self.associativity-1}:0] way_hit_{i};\n"
                for way in range(self.associativity):
                    verilog += f"    assign way_hit_{i}[{way}] = valid_array[index_{i}][{way}] && (tag_array[index_{i}][{way}] == tag_{i});\n"
                verilog += f"    wire hit_{i} = |way_hit_{i};\n"
                # Way selection (one-hot to binary)
                way_bits = (self.associativity - 1).bit_length()
                verilog += f"    reg [{way_bits-1}:0] hit_way_{i};\n"
                verilog += f"    always @* begin\n"
                verilog += f"        hit_way_{i} = 0;\n"
                for way in range(self.associativity):
                    verilog += f"        if (way_hit_{i}[{way}]) hit_way_{i} = {way};\n"
                verilog += f"    end\n"

            verilog += "\n"

        return verilog

    def _generate_read_logic(self) -> str:
        """Generate read data selection logic."""
        verilog = "    // Read data selection\n"

        for i in range(self.num_read_ports):
            verilog += f"    always @* begin\n"
            verilog += f"        read_valid_{i} = read_req_{i} && hit_{i};\n"

            if self.associativity == 1:
                if self.words_per_line > 1:
                    verilog += f"        read_data_{i} = data_array[index_{i}][word_offset_{i}*DATA_WIDTH +: DATA_WIDTH];\n"
                else:
                    verilog += f"        read_data_{i} = data_array[index_{i}];\n"
            else:
                # Use 2D array: [index][way]
                if self.words_per_line > 1:
                    verilog += f"        read_data_{i} = data_array[index_{i}][hit_way_{i}][word_offset_{i}*DATA_WIDTH +: DATA_WIDTH];\n"
                else:
                    verilog += f"        read_data_{i} = data_array[index_{i}][hit_way_{i}];\n"

            verilog += f"    end\n\n"

        return verilog

    def _generate_refill_fsm(self) -> str:
        """Generate cache miss handling and refill FSM."""
        verilog = "    // Refill FSM states (using localparam for iverilog compatibility)\n"
        verilog += "    localparam IDLE = 2'b00;\n"
        verilog += "    localparam REFILL = 2'b01;\n"
        verilog += "    localparam UPDATE = 2'b10;\n\n"
        verilog += "    reg [1:0] state, next_state;\n"
        verilog += "    reg [ADDR_WIDTH-1:0] miss_addr;\n"
        verilog += "    reg [INDEX_WIDTH-1:0] refill_index;\n"
        verilog += "    reg [TAG_WIDTH-1:0] refill_tag;\n"

        if self.words_per_line > 1:
            word_cnt_bits = max(1, (self.words_per_line - 1).bit_length())
            verilog += f"    reg [{word_cnt_bits-1}:0] refill_word_cnt;\n"
            verilog += "    reg [DATA_WIDTH*WORDS_PER_LINE-1:0] refill_line_data;\n"

        if self.associativity > 1:
            way_bits = (self.associativity - 1).bit_length()
            verilog += f"    reg [{way_bits-1}:0] refill_way;\n"

        verilog += "\n"

        # Miss detection (priority: port 0 first)
        verilog += "    // Miss detection\n"
        verilog += "    wire miss = "
        miss_conditions = [f"(read_req_{i} && !hit_{i})" for i in range(self.num_read_ports)]
        verilog += " || ".join(miss_conditions) + ";\n"

        verilog += "    reg [ADDR_WIDTH-1:0] miss_addr_comb;\n"
        verilog += "    always @* begin\n"
        verilog += f"        miss_addr_comb = read_addr_0;\n"
        for i in range(self.num_read_ports):
            verilog += f"        if (read_req_{i} && !hit_{i}) miss_addr_comb = read_addr_{i};\n"
        verilog += "    end\n\n"

        # FSM logic
        verilog += "    // FSM state register\n"
        verilog += "    always @(posedge clk) begin\n"
        verilog += "        if (reset) begin\n"
        verilog += "            state <= IDLE;\n"
        verilog += "            miss_addr <= 0;\n"
        verilog += "            refill_index <= 0;\n"
        verilog += "            refill_tag <= 0;\n"
        if self.words_per_line > 1:
            verilog += "            refill_word_cnt <= 0;\n"
            verilog += "            refill_line_data <= 0;\n"
        verilog += "        end else begin\n"
        verilog += "            state <= next_state;\n"
        verilog += "            if (state == IDLE && miss) begin\n"
        verilog += "                miss_addr <= miss_addr_comb;\n"
        verilog += "                refill_index <= miss_addr_comb[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH];\n"
        verilog += "                refill_tag <= miss_addr_comb[ADDR_WIDTH-1:ADDR_WIDTH-TAG_WIDTH];\n"
        verilog += "            end\n"
        if self.words_per_line > 1:
            verilog += "            if (state == REFILL && refill_valid) begin\n"
            verilog += "                refill_line_data[refill_word_cnt*DATA_WIDTH +: DATA_WIDTH] <= refill_data;\n"
            verilog += "                refill_word_cnt <= refill_word_cnt + 1;\n"
            verilog += "            end\n"
            verilog += "            if (state == UPDATE) refill_word_cnt <= 0;\n"
        verilog += "        end\n"
        verilog += "    end\n\n"

        # FSM next state logic
        verilog += "    // FSM next state logic\n"
        verilog += "    always @* begin\n"
        verilog += "        next_state = state;\n"
        verilog += "        refill_req = 1'b0;\n"
        verilog += "        refill_addr = miss_addr;\n"
        verilog += "        case (state)\n"
        verilog += "            IDLE: begin\n"
        verilog += "                if (miss) next_state = REFILL;\n"
        verilog += "            end\n"
        verilog += "            REFILL: begin\n"
        verilog += "                refill_req = 1'b1;\n"
        if self.words_per_line > 1:
            verilog += "                refill_addr = {refill_tag, refill_index, refill_word_cnt, {(OFFSET_WIDTH-WORD_OFFSET_WIDTH){1'b0}}};\n"
            verilog += f"                if (refill_valid && refill_word_cnt == WORDS_PER_LINE-1) next_state = UPDATE;\n"
        else:
            verilog += "                if (refill_valid) next_state = UPDATE;\n"
        verilog += "            end\n"
        verilog += "            UPDATE: begin\n"
        verilog += "                next_state = IDLE;\n"
        verilog += "            end\n"
        verilog += "            default: next_state = IDLE;\n"
        verilog += "        endcase\n"
        verilog += "    end\n\n"

        # Cache update logic - use integer loop variable for iverilog
        verilog += "    // Cache update on refill complete\n"
        verilog += "    integer init_i;\n"
        if self.associativity > 1:
            verilog += "    integer init_j;\n"
        verilog += "    always @(posedge clk) begin\n"
        # Flush invalidates all entries, same as reset
        if self.has_flush:
            verilog += "        if (reset || flush) begin\n"
        else:
            verilog += "        if (reset) begin\n"
        if self.associativity == 1:
            verilog += "            for (init_i = 0; init_i < NUM_ROWS; init_i = init_i + 1) begin\n"
            verilog += "                valid_array[init_i] <= 1'b0;\n"
            verilog += "            end\n"
        else:
            # Use nested loops for 2D array
            verilog += "            for (init_i = 0; init_i < NUM_ROWS; init_i = init_i + 1) begin\n"
            verilog += "                for (init_j = 0; init_j < ASSOCIATIVITY; init_j = init_j + 1) begin\n"
            verilog += "                    valid_array[init_i][init_j] <= 1'b0;\n"
            verilog += "                end\n"
            verilog += "            end\n"
        verilog += "        end else if (state == UPDATE) begin\n"

        if self.associativity == 1:
            verilog += "            valid_array[refill_index] <= 1'b1;\n"
            verilog += "            tag_array[refill_index] <= refill_tag;\n"
            if self.words_per_line > 1:
                verilog += "            data_array[refill_index] <= refill_line_data;\n"
            else:
                verilog += "            data_array[refill_index] <= refill_data;\n"
        else:
            # Use 2D array access [index][way]
            verilog += "            valid_array[refill_index][refill_way] <= 1'b1;\n"
            verilog += "            tag_array[refill_index][refill_way] <= refill_tag;\n"
            if self.words_per_line > 1:
                verilog += "            data_array[refill_index][refill_way] <= refill_line_data;\n"
            else:
                verilog += "            data_array[refill_index][refill_way] <= refill_data;\n"

        verilog += "        end\n"
        verilog += "    end\n\n"

        return verilog

    def _generate_replacement_logic(self) -> str:
        """Generate replacement policy logic for set-associative caches."""
        if self.associativity == 1:
            return ""  # Direct-mapped doesn't need replacement logic

        verilog = "    // Replacement policy logic\n"

        if self.replacement_policy == 'lru':
            verilog += "    // LRU replacement\n"
            verilog += "    integer lru_init_i;\n"
            verilog += "    always @(posedge clk) begin\n"
            verilog += "        if (reset) begin\n"
            verilog += "            for (lru_init_i = 0; lru_init_i < NUM_ROWS; lru_init_i = lru_init_i + 1) begin\n"
            verilog += "                lru_array[lru_init_i] <= 0;\n"
            verilog += "            end\n"
            verilog += "            refill_way <= 0;\n"
            verilog += "        end else begin\n"
            # Update LRU on hit
            for i in range(self.num_read_ports):
                verilog += f"            if (hit_{i}) begin\n"
                verilog += f"                // Update LRU for port {i} hit\n"
                verilog += f"                lru_array[index_{i}] <= hit_way_{i};\n"
                verilog += f"            end\n"
            # Select victim way on miss - use 2D array access
            verilog += "            if (state == IDLE && miss) begin\n"
            verilog += "                // Find invalid way first, then use LRU\n"
            verilog += "                refill_way <= 0;\n"
            for way in range(self.associativity):
                verilog += f"                if (!valid_array[miss_addr_comb[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH]][{way}]) refill_way <= {way};\n"
            verilog += "                else refill_way <= lru_array[miss_addr_comb[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH]] ^ 1;\n"
            verilog += "            end\n"
            verilog += "        end\n"
            verilog += "    end\n\n"

        elif self.replacement_policy == 'random':
            verilog += "    // Random replacement using LFSR\n"
            verilog += "    reg [7:0] lfsr;\n"
            verilog += "    always @(posedge clk) begin\n"
            verilog += "        if (reset) begin\n"
            verilog += "            lfsr <= 8'hA5;  // Non-zero seed\n"
            verilog += "            refill_way <= 0;\n"
            verilog += "        end else begin\n"
            verilog += "            lfsr <= {lfsr[6:0], lfsr[7] ^ lfsr[5] ^ lfsr[4] ^ lfsr[3]};\n"
            verilog += "            if (state == IDLE && miss) begin\n"
            way_bits = (self.associativity - 1).bit_length()
            verilog += f"                refill_way <= lfsr[{way_bits-1}:0];\n"
            verilog += "            end\n"
            verilog += "        end\n"
            verilog += "    end\n\n"

        elif self.replacement_policy == 'fifo':
            verilog += "    // FIFO replacement\n"
            way_bits = (self.associativity - 1).bit_length()
            verilog += f"    reg [{way_bits-1}:0] fifo_ptr [0:NUM_ROWS-1];\n"
            verilog += "    integer fifo_init_i;\n"
            verilog += "    always @(posedge clk) begin\n"
            verilog += "        if (reset) begin\n"
            verilog += "            for (fifo_init_i = 0; fifo_init_i < NUM_ROWS; fifo_init_i = fifo_init_i + 1) begin\n"
            verilog += "                fifo_ptr[fifo_init_i] <= 0;\n"
            verilog += "            end\n"
            verilog += "            refill_way <= 0;\n"
            verilog += "        end else begin\n"
            verilog += "            if (state == IDLE && miss) begin\n"
            verilog += "                refill_way <= fifo_ptr[miss_addr_comb[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH]];\n"
            verilog += "            end\n"
            verilog += "            if (state == UPDATE) begin\n"
            verilog += "                fifo_ptr[refill_index] <= (fifo_ptr[refill_index] + 1) % ASSOCIATIVITY;\n"
            verilog += "            end\n"
            verilog += "        end\n"
            verilog += "    end\n\n"

        return verilog

    def get_port_connections(self,
                            read_addrs: List[str],
                            read_reqs: List[str],
                            read_datas: List[str],
                            read_valids: List[str],
                            refill_addr: str,
                            refill_req: str,
                            refill_data: str,
                            refill_valid: str,
                            flush_signal: Optional[str] = None) -> str:
        """Generate instantiation with port connections.

        Args:
            read_addrs: List of read address signal names
            read_reqs: List of read request signal names
            read_datas: List of read data signal names
            read_valids: List of read valid signal names
            refill_addr: Refill address signal name
            refill_req: Refill request signal name
            refill_data: Refill data signal name
            refill_valid: Refill valid signal name
            flush_signal: Optional flush signal name (for fence.i, sfence.vma, etc.)
        """
        connections = [
            "    .clk(clk)",
            "    .reset(reset)"
        ]

        # Flush port (if cache has flush support)
        if self.has_flush:
            flush_expr = flush_signal if flush_signal is not None else "1'b0"
            connections.append(f"    .flush({flush_expr})")

        for i in range(self.num_read_ports):
            connections.append(f"    .read_addr_{i}({read_addrs[i]})")
            connections.append(f"    .read_req_{i}({read_reqs[i]})")
            connections.append(f"    .read_data_{i}({read_datas[i]})")
            connections.append(f"    .read_valid_{i}({read_valids[i]})")

        connections.append(f"    .refill_addr({refill_addr})")
        connections.append(f"    .refill_req({refill_req})")
        connections.append(f"    .refill_data({refill_data})")
        connections.append(f"    .refill_valid({refill_valid})")

        return f"{self.name} {self.name}_inst(\n" + ",\n".join(connections) + "\n);"


@dataclass
class ReadWriteCacheGenerator:
    """Generate parameterized read-write cache Verilog module.

    This generates a complete read-write cache with write-through policy including:
    - Tag array storage
    - Valid bit tracking
    - Data array storage
    - Hit/miss detection logic
    - Refill FSM for cache read misses
    - Write-through path to backing memory
    - Multiple read ports support
    - Single write port (multiple writes muxed before cache)
    - Optional write-read forwarding
    - Optional write allocate on write miss
    - Configurable replacement policy
    """

    name: str
    num_read_ports: int = 1
    num_write_ports: int = 1        # Typically 1 (writes are muxed before cache)
    block_size: int = 32            # bytes per cache line
    associativity: int = 1          # 1 = direct-mapped
    num_rows: int = 64              # number of cache sets
    address_width: int = 32
    data_width: int = 32
    replacement_policy: str = 'lru'  # 'lru', 'random', 'fifo'
    write_allocate: bool = False     # Allocate cache line on write miss
    write_read_fwd: bool = False     # Forward writes to concurrent reads

    def __post_init__(self):
        """Calculate derived parameters."""
        self.offset_width = (self.block_size - 1).bit_length()
        self.index_width = (self.num_rows - 1).bit_length()
        self.tag_width = self.address_width - self.offset_width - self.index_width
        self.words_per_line = self.block_size * 8 // self.data_width
        self.byte_enable_width = self.data_width // 8

    def generate_module(self) -> str:
        """Generate complete Verilog module for the read-write cache."""
        verilog = self._generate_module_header()
        verilog += self._generate_parameters()
        verilog += self._generate_storage_arrays()
        verilog += self._generate_address_decoding()
        verilog += self._generate_hit_logic()
        verilog += self._generate_read_logic()
        verilog += self._generate_write_logic()
        verilog += self._generate_fsm()
        verilog += self._generate_replacement_logic()
        verilog += "endmodule\n"
        return verilog

    def _generate_module_header(self) -> str:
        """Generate module declaration with ports."""
        verilog = f"module {self.name} #(\n"
        verilog += f"    parameter BLOCK_SIZE = {self.block_size},\n"
        verilog += f"    parameter ASSOCIATIVITY = {self.associativity},\n"
        verilog += f"    parameter NUM_ROWS = {self.num_rows},\n"
        verilog += f"    parameter ADDR_WIDTH = {self.address_width},\n"
        verilog += f"    parameter DATA_WIDTH = {self.data_width}\n"
        verilog += ")(\n"
        verilog += "    input  wire clk,\n"
        verilog += "    input  wire reset,\n"

        # Read ports
        for i in range(self.num_read_ports):
            verilog += f"\n    // Read port {i}\n"
            verilog += f"    input  wire [ADDR_WIDTH-1:0] read_addr_{i},\n"
            verilog += f"    input  wire read_req_{i},\n"
            verilog += f"    output reg [DATA_WIDTH-1:0] read_data_{i},\n"
            verilog += f"    output reg read_valid_{i},\n"

        # Write port (single, writes are muxed before reaching cache)
        verilog += "\n    // Write port\n"
        verilog += "    input  wire [ADDR_WIDTH-1:0] write_addr,\n"
        verilog += "    input  wire [DATA_WIDTH-1:0] write_data,\n"
        verilog += f"    input  wire [{self.byte_enable_width}-1:0] write_byte_enable,\n"
        verilog += "    input  wire write_req,\n"
        verilog += "    output reg write_complete,\n"

        # Refill interface to backing memory (for read misses)
        verilog += "\n    // Refill interface to backing memory (read misses)\n"
        verilog += "    output reg [ADDR_WIDTH-1:0] refill_addr,\n"
        verilog += "    output reg refill_req,\n"
        verilog += "    input  wire [DATA_WIDTH-1:0] refill_data,\n"
        verilog += "    input  wire refill_valid,\n"

        # Write-through interface to backing memory
        verilog += "\n    // Write-through interface to backing memory\n"
        verilog += "    output reg [ADDR_WIDTH-1:0] write_through_addr,\n"
        verilog += "    output reg [DATA_WIDTH-1:0] write_through_data,\n"
        verilog += f"    output reg [{self.byte_enable_width}-1:0] write_through_byte_enable,\n"
        verilog += "    output reg write_through_req,\n"
        verilog += "    input  wire write_through_complete,\n"

        # Control signals
        verilog += "\n    // Control signals\n"
        verilog += "    output wire idle,\n"
        verilog += "    output wire complete\n"
        verilog += ");\n\n"
        return verilog

    def _generate_parameters(self) -> str:
        """Generate local parameters."""
        verilog = "    // Derived parameters\n"
        verilog += f"    localparam OFFSET_WIDTH = {self.offset_width};\n"
        verilog += f"    localparam INDEX_WIDTH = {self.index_width};\n"
        verilog += f"    localparam TAG_WIDTH = ADDR_WIDTH - OFFSET_WIDTH - INDEX_WIDTH;\n"
        verilog += f"    localparam WORDS_PER_LINE = {self.words_per_line};\n"
        verilog += f"    localparam WORD_OFFSET_WIDTH = {(self.words_per_line - 1).bit_length() if self.words_per_line > 1 else 1};\n"
        verilog += f"    localparam BYTE_ENABLE_WIDTH = {self.byte_enable_width};\n\n"
        return verilog

    def _generate_storage_arrays(self) -> str:
        """Generate tag, valid, and data arrays."""
        verilog = "    // Storage arrays\n"

        if self.associativity == 1:
            # Direct-mapped cache
            verilog += "    reg [TAG_WIDTH-1:0] tag_array [0:NUM_ROWS-1];\n"
            verilog += "    reg valid_array [0:NUM_ROWS-1];\n"
            verilog += "    reg [DATA_WIDTH*WORDS_PER_LINE-1:0] data_array [0:NUM_ROWS-1];\n"
        else:
            # Set-associative cache
            verilog += f"    reg [TAG_WIDTH-1:0] tag_array [0:NUM_ROWS-1][0:ASSOCIATIVITY-1];\n"
            verilog += f"    reg valid_array [0:NUM_ROWS-1][0:ASSOCIATIVITY-1];\n"
            verilog += f"    reg [DATA_WIDTH*WORDS_PER_LINE-1:0] data_array [0:NUM_ROWS-1][0:ASSOCIATIVITY-1];\n"

            if self.replacement_policy == 'lru':
                lru_width = self.associativity - 1
                verilog += f"    reg [{lru_width}:0] lru_array [0:NUM_ROWS-1];\n"

        verilog += "\n"
        return verilog

    def _generate_address_decoding(self) -> str:
        """Generate address field extraction for read and write ports."""
        verilog = "    // Address decoding - read ports\n"

        for i in range(self.num_read_ports):
            verilog += f"    wire [TAG_WIDTH-1:0] read_tag_{i} = read_addr_{i}[ADDR_WIDTH-1:ADDR_WIDTH-TAG_WIDTH];\n"
            verilog += f"    wire [INDEX_WIDTH-1:0] read_index_{i} = read_addr_{i}[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH];\n"
            if self.words_per_line > 1:
                verilog += f"    wire [WORD_OFFSET_WIDTH-1:0] read_word_offset_{i} = read_addr_{i}[OFFSET_WIDTH-1:OFFSET_WIDTH-WORD_OFFSET_WIDTH];\n"
            verilog += "\n"

        # Write port address decoding
        verilog += "    // Address decoding - write port\n"
        verilog += "    wire [TAG_WIDTH-1:0] write_tag = write_addr[ADDR_WIDTH-1:ADDR_WIDTH-TAG_WIDTH];\n"
        verilog += "    wire [INDEX_WIDTH-1:0] write_index = write_addr[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH];\n"
        if self.words_per_line > 1:
            verilog += "    wire [WORD_OFFSET_WIDTH-1:0] write_word_offset = write_addr[OFFSET_WIDTH-1:OFFSET_WIDTH-WORD_OFFSET_WIDTH];\n"
        verilog += "\n"

        return verilog

    def _generate_hit_logic(self) -> str:
        """Generate cache hit detection logic for reads and writes."""
        verilog = "    // Hit detection - read ports\n"

        for i in range(self.num_read_ports):
            if self.associativity == 1:
                verilog += f"    wire read_hit_{i} = valid_array[read_index_{i}] && (tag_array[read_index_{i}] == read_tag_{i});\n"
            else:
                verilog += f"    wire [{self.associativity-1}:0] read_way_hit_{i};\n"
                for way in range(self.associativity):
                    verilog += f"    assign read_way_hit_{i}[{way}] = valid_array[read_index_{i}][{way}] && (tag_array[read_index_{i}][{way}] == read_tag_{i});\n"
                verilog += f"    wire read_hit_{i} = |read_way_hit_{i};\n"
                way_bits = (self.associativity - 1).bit_length()
                verilog += f"    reg [{way_bits-1}:0] read_hit_way_{i};\n"
                verilog += f"    always @* begin\n"
                verilog += f"        read_hit_way_{i} = 0;\n"
                for way in range(self.associativity):
                    verilog += f"        if (read_way_hit_{i}[{way}]) read_hit_way_{i} = {way};\n"
                verilog += f"    end\n"
            verilog += "\n"

        # Write port hit detection
        verilog += "    // Hit detection - write port\n"
        if self.associativity == 1:
            verilog += "    wire write_hit = valid_array[write_index] && (tag_array[write_index] == write_tag);\n"
            # Also need pending_write_hit for checking during WRITE_THROUGH state
            verilog += "    wire pending_write_hit = valid_array[pending_index] && (tag_array[pending_index] == pending_tag);\n"
        else:
            verilog += f"    wire [{self.associativity-1}:0] write_way_hit;\n"
            for way in range(self.associativity):
                verilog += f"    assign write_way_hit[{way}] = valid_array[write_index][{way}] && (tag_array[write_index][{way}] == write_tag);\n"
            verilog += "    wire write_hit = |write_way_hit;\n"
            way_bits = (self.associativity - 1).bit_length()
            verilog += f"    reg [{way_bits-1}:0] write_hit_way;\n"
            verilog += "    always @* begin\n"
            verilog += "        write_hit_way = 0;\n"
            for way in range(self.associativity):
                verilog += f"        if (write_way_hit[{way}]) write_hit_way = {way};\n"
            verilog += "    end\n"
            # Also need pending_write_hit for checking during WRITE_THROUGH state
            verilog += f"    wire [{self.associativity-1}:0] pending_way_hit;\n"
            for way in range(self.associativity):
                verilog += f"    assign pending_way_hit[{way}] = valid_array[pending_index][{way}] && (tag_array[pending_index][{way}] == pending_tag);\n"
            verilog += "    wire pending_write_hit = |pending_way_hit;\n"
            verilog += f"    reg [{way_bits-1}:0] pending_hit_way;\n"
            verilog += "    always @* begin\n"
            verilog += "        pending_hit_way = 0;\n"
            for way in range(self.associativity):
                verilog += f"        if (pending_way_hit[{way}]) pending_hit_way = {way};\n"
            verilog += "    end\n"
        verilog += "\n"

        return verilog

    def _generate_read_logic(self) -> str:
        """Generate read data selection logic."""
        verilog = "    // Read data selection\n"

        for i in range(self.num_read_ports):
            verilog += f"    reg [DATA_WIDTH-1:0] cache_read_data_{i};\n"
            verilog += f"    always @* begin\n"

            if self.associativity == 1:
                if self.words_per_line > 1:
                    verilog += f"        cache_read_data_{i} = data_array[read_index_{i}][read_word_offset_{i}*DATA_WIDTH +: DATA_WIDTH];\n"
                else:
                    verilog += f"        cache_read_data_{i} = data_array[read_index_{i}];\n"
            else:
                if self.words_per_line > 1:
                    verilog += f"        cache_read_data_{i} = data_array[read_index_{i}][read_hit_way_{i}][read_word_offset_{i}*DATA_WIDTH +: DATA_WIDTH];\n"
                else:
                    verilog += f"        cache_read_data_{i} = data_array[read_index_{i}][read_hit_way_{i}];\n"

            verilog += f"    end\n"

            # Output assignment with optional write-read forwarding
            if self.write_read_fwd:
                verilog += f"\n    // Write-read forwarding for port {i}\n"
                verilog += f"    wire fwd_match_{i} = write_req && (write_addr == read_addr_{i});\n"
                verilog += f"    always @* begin\n"
                verilog += f"        // During READ_UPDATE, output refill data directly\n"
                verilog += f"        if (state == READ_UPDATE) begin\n"
                verilog += f"            read_data_{i} = refill_data;\n"
                verilog += f"            read_valid_{i} = 1'b1;\n"
                verilog += f"        end else if (fwd_match_{i}) begin\n"
                verilog += f"            read_data_{i} = write_data;\n"
                verilog += f"            read_valid_{i} = read_req_{i};\n"
                verilog += f"        end else begin\n"
                verilog += f"            read_data_{i} = cache_read_data_{i};\n"
                verilog += f"            read_valid_{i} = read_req_{i} && read_hit_{i};\n"
                verilog += f"        end\n"
                verilog += f"    end\n\n"
            else:
                verilog += f"    always @* begin\n"
                verilog += f"        // During READ_UPDATE, output refill data directly\n"
                verilog += f"        if (state == READ_UPDATE) begin\n"
                verilog += f"            read_data_{i} = refill_data;\n"
                verilog += f"            read_valid_{i} = 1'b1;\n"
                verilog += f"        end else begin\n"
                verilog += f"            read_data_{i} = cache_read_data_{i};\n"
                verilog += f"            read_valid_{i} = read_req_{i} && read_hit_{i};\n"
                verilog += f"        end\n"
                verilog += f"    end\n\n"

        return verilog

    def _generate_write_logic(self) -> str:
        """Generate write port logic with byte enables and write-through."""
        verilog = "    // Write data with byte enables (uses pending values for WRITE_THROUGH state)\n"
        verilog += "    reg [DATA_WIDTH-1:0] merged_write_data;\n"
        verilog += "    reg [DATA_WIDTH-1:0] pending_current_data;\n\n"

        verilog += "    always @* begin\n"
        # Get current data from cache using pending_index (for WRITE_THROUGH state)
        if self.associativity == 1:
            if self.words_per_line > 1:
                verilog += "        pending_current_data = data_array[pending_index][pending_word_offset*DATA_WIDTH +: DATA_WIDTH];\n"
            else:
                verilog += "        pending_current_data = data_array[pending_index];\n"
        else:
            if self.words_per_line > 1:
                verilog += "        pending_current_data = data_array[pending_index][pending_hit_way][pending_word_offset*DATA_WIDTH +: DATA_WIDTH];\n"
            else:
                verilog += "        pending_current_data = data_array[pending_index][pending_hit_way];\n"

        # Merge with pending byte enables and pending write data
        verilog += "        merged_write_data = pending_current_data;\n"
        for byte_idx in range(self.byte_enable_width):
            verilog += f"        if (pending_byte_enable[{byte_idx}]) merged_write_data[{(byte_idx+1)*8-1}:{byte_idx*8}] = pending_write_data[{(byte_idx+1)*8-1}:{byte_idx*8}];\n"
        verilog += "    end\n\n"

        return verilog

    def _generate_fsm(self) -> str:
        """Generate FSM for handling read misses and write-through operations."""
        verilog = "    // FSM states\n"
        verilog += "    localparam IDLE = 3'b000;\n"
        verilog += "    localparam READ_REFILL = 3'b001;\n"
        verilog += "    localparam READ_UPDATE = 3'b010;\n"
        verilog += "    localparam WRITE_THROUGH = 3'b011;\n"
        verilog += "    localparam WRITE_WAIT = 3'b100;\n"
        if self.write_allocate:
            verilog += "    localparam WRITE_ALLOC_REFILL = 3'b101;\n"
            verilog += "    localparam WRITE_ALLOC_UPDATE = 3'b110;\n"
        verilog += "\n"

        verilog += "    reg [2:0] state, next_state;\n"
        verilog += "    reg [ADDR_WIDTH-1:0] miss_addr;\n"
        verilog += "    reg [INDEX_WIDTH-1:0] pending_index;\n"
        verilog += "    reg [TAG_WIDTH-1:0] pending_tag;\n"
        verilog += "    reg [DATA_WIDTH-1:0] pending_write_data;\n"
        verilog += f"    reg [BYTE_ENABLE_WIDTH-1:0] pending_byte_enable;\n"

        if self.words_per_line > 1:
            word_cnt_bits = max(1, (self.words_per_line - 1).bit_length())
            verilog += f"    reg [{word_cnt_bits-1}:0] refill_word_cnt;\n"
            verilog += "    reg [DATA_WIDTH*WORDS_PER_LINE-1:0] refill_line_data;\n"
            verilog += f"    reg [WORD_OFFSET_WIDTH-1:0] pending_word_offset;\n"

        if self.associativity > 1:
            way_bits = (self.associativity - 1).bit_length()
            verilog += f"    reg [{way_bits-1}:0] refill_way;\n"

        verilog += "\n"

        # Miss detection
        verilog += "    // Miss detection\n"
        verilog += "    wire read_miss = "
        miss_conditions = [f"(read_req_{i} && !read_hit_{i})" for i in range(self.num_read_ports)]
        verilog += " || ".join(miss_conditions) + ";\n"

        verilog += "    reg [ADDR_WIDTH-1:0] miss_addr_comb;\n"
        verilog += "    always @* begin\n"
        verilog += f"        miss_addr_comb = read_addr_0;\n"
        for i in range(self.num_read_ports):
            verilog += f"        if (read_req_{i} && !read_hit_{i}) miss_addr_comb = read_addr_{i};\n"
        verilog += "    end\n\n"

        # Control signals
        verilog += "    // Control signals\n"
        verilog += "    assign idle = (state == IDLE);\n"
        # Complete should be false when there's a read miss that hasn't been serviced
        # - IDLE with no pending read miss: complete
        # - READ_REFILL/READ_UPDATE: not complete until refill done
        # - WRITE_WAIT completing without pending read miss: complete
        # Note: WRITE_WAIT (not WRITE_THROUGH) checks completion to allow arbiter grant_reg to be set
        verilog += "    assign complete = (state == IDLE && !read_miss) ||\n"
        verilog += "                       (state == READ_UPDATE) ||\n"
        verilog += "                       ((state == WRITE_WAIT) && write_through_complete && !read_miss);\n\n"

        # FSM state register
        verilog += "    // FSM state register\n"
        verilog += "    always @(posedge clk) begin\n"
        verilog += "        if (reset) begin\n"
        verilog += "            state <= IDLE;\n"
        verilog += "            miss_addr <= 0;\n"
        verilog += "            pending_index <= 0;\n"
        verilog += "            pending_tag <= 0;\n"
        verilog += "            pending_write_data <= 0;\n"
        verilog += "            pending_byte_enable <= 0;\n"
        if self.words_per_line > 1:
            verilog += "            refill_word_cnt <= 0;\n"
            verilog += "            refill_line_data <= 0;\n"
            verilog += "            pending_word_offset <= 0;\n"
        verilog += "        end else begin\n"
        verilog += "            state <= next_state;\n"
        verilog += "\n"
        verilog += "            // Capture miss address on read miss\n"
        verilog += "            if (state == IDLE && read_miss) begin\n"
        verilog += "                miss_addr <= miss_addr_comb;\n"
        verilog += "                pending_index <= miss_addr_comb[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH];\n"
        verilog += "                pending_tag <= miss_addr_comb[ADDR_WIDTH-1:ADDR_WIDTH-TAG_WIDTH];\n"
        verilog += "            end\n"
        verilog += "\n"
        verilog += "            // Capture write data\n"
        verilog += "            if (state == IDLE && write_req) begin\n"
        verilog += "                pending_write_data <= write_data;\n"
        verilog += "                pending_byte_enable <= write_byte_enable;\n"
        verilog += "                pending_index <= write_index;\n"
        verilog += "                pending_tag <= write_tag;\n"
        if self.words_per_line > 1:
            verilog += "                pending_word_offset <= write_word_offset;\n"
        verilog += "            end\n"

        if self.words_per_line > 1:
            verilog += "\n            // Accumulate refill data\n"
            verilog += "            if (state == READ_REFILL && refill_valid) begin\n"
            verilog += "                refill_line_data[refill_word_cnt*DATA_WIDTH +: DATA_WIDTH] <= refill_data;\n"
            verilog += "                refill_word_cnt <= refill_word_cnt + 1;\n"
            verilog += "            end\n"
            verilog += "            if (state == READ_UPDATE) refill_word_cnt <= 0;\n"

        verilog += "        end\n"
        verilog += "    end\n\n"

        # FSM next state logic
        verilog += "    // FSM next state logic\n"
        verilog += "    always @* begin\n"
        verilog += "        next_state = state;\n"
        verilog += "        refill_req = 1'b0;\n"
        verilog += "        refill_addr = miss_addr;\n"
        verilog += "        write_through_req = 1'b0;\n"
        verilog += "        write_through_addr = write_addr;\n"
        verilog += "        write_through_data = write_data;\n"
        verilog += "        write_through_byte_enable = write_byte_enable;\n"
        verilog += "        write_complete = 1'b0;\n"
        verilog += "\n"
        verilog += "        case (state)\n"
        verilog += "            IDLE: begin\n"
        verilog += "                // Priority: writes before reads (to avoid stale data)\n"
        verilog += "                if (write_req) begin\n"
        verilog += "                    next_state = WRITE_THROUGH;\n"
        verilog += "                end else if (read_miss) begin\n"
        verilog += "                    next_state = READ_REFILL;\n"
        verilog += "                end\n"
        verilog += "            end\n"
        verilog += "\n"
        verilog += "            READ_REFILL: begin\n"
        verilog += "                refill_req = 1'b1;\n"
        if self.words_per_line > 1:
            verilog += "                refill_addr = {pending_tag, pending_index, refill_word_cnt, {(OFFSET_WIDTH-WORD_OFFSET_WIDTH){1'b0}}};\n"
            verilog += f"                if (refill_valid && refill_word_cnt == WORDS_PER_LINE-1) next_state = READ_UPDATE;\n"
        else:
            verilog += "                if (refill_valid) next_state = READ_UPDATE;\n"
        verilog += "            end\n"
        verilog += "\n"
        verilog += "            READ_UPDATE: begin\n"
        verilog += "                next_state = IDLE;\n"
        verilog += "            end\n"
        verilog += "\n"
        verilog += "            WRITE_THROUGH: begin\n"
        verilog += "                // First cycle: assert request and transition to WRITE_WAIT\n"
        verilog += "                // This allows arbiter grant_reg to be set before checking completion\n"
        verilog += "                write_through_req = 1'b1;\n"
        verilog += "                write_through_addr = {pending_tag, pending_index, "
        if self.words_per_line > 1:
            verilog += "pending_word_offset, "
        verilog += "{(OFFSET_WIDTH"
        if self.words_per_line > 1:
            verilog += "-WORD_OFFSET_WIDTH"
        verilog += "){1'b0}}};\n"
        verilog += "                write_through_data = pending_write_data;\n"
        verilog += "                write_through_byte_enable = pending_byte_enable;\n"
        verilog += "                next_state = WRITE_WAIT;\n"
        verilog += "            end\n"
        verilog += "\n"
        verilog += "            WRITE_WAIT: begin\n"
        verilog += "                // Wait for write acknowledgment from memory\n"
        verilog += "                write_through_req = 1'b1;\n"
        verilog += "                write_through_addr = {pending_tag, pending_index, "
        if self.words_per_line > 1:
            verilog += "pending_word_offset, "
        verilog += "{(OFFSET_WIDTH"
        if self.words_per_line > 1:
            verilog += "-WORD_OFFSET_WIDTH"
        verilog += "){1'b0}}};\n"
        verilog += "                write_through_data = pending_write_data;\n"
        verilog += "                write_through_byte_enable = pending_byte_enable;\n"
        verilog += "                if (write_through_complete) begin\n"
        verilog += "                    write_complete = 1'b1;\n"
        verilog += "                    next_state = IDLE;\n"
        verilog += "                end\n"
        verilog += "            end\n"
        verilog += "\n"
        verilog += "            default: next_state = IDLE;\n"
        verilog += "        endcase\n"
        verilog += "    end\n\n"

        # Cache update logic
        verilog += "    // Cache update on refill complete and write hit\n"
        verilog += "    integer init_i;\n"
        if self.associativity > 1:
            verilog += "    integer init_j;\n"
        verilog += "    always @(posedge clk) begin\n"
        verilog += "        if (reset) begin\n"
        if self.associativity == 1:
            verilog += "            for (init_i = 0; init_i < NUM_ROWS; init_i = init_i + 1) begin\n"
            verilog += "                valid_array[init_i] <= 1'b0;\n"
            verilog += "            end\n"
        else:
            verilog += "            for (init_i = 0; init_i < NUM_ROWS; init_i = init_i + 1) begin\n"
            verilog += "                for (init_j = 0; init_j < ASSOCIATIVITY; init_j = init_j + 1) begin\n"
            verilog += "                    valid_array[init_i][init_j] <= 1'b0;\n"
            verilog += "                end\n"
            verilog += "            end\n"

        verilog += "        end else begin\n"
        verilog += "            // Update cache on read refill complete\n"
        verilog += "            if (state == READ_UPDATE) begin\n"
        if self.associativity == 1:
            verilog += "                valid_array[pending_index] <= 1'b1;\n"
            verilog += "                tag_array[pending_index] <= pending_tag;\n"
            if self.words_per_line > 1:
                verilog += "                data_array[pending_index] <= refill_line_data;\n"
            else:
                verilog += "                data_array[pending_index] <= refill_data;\n"
        else:
            verilog += "                valid_array[pending_index][refill_way] <= 1'b1;\n"
            verilog += "                tag_array[pending_index][refill_way] <= pending_tag;\n"
            if self.words_per_line > 1:
                verilog += "                data_array[pending_index][refill_way] <= refill_line_data;\n"
            else:
                verilog += "                data_array[pending_index][refill_way] <= refill_data;\n"

        verilog += "            end\n\n"

        # Update cache on write hit (use pending_write_hit since write_addr has moved on in the pipeline)
        # Note: Use WRITE_WAIT state since completion is checked there (after arbiter grant_reg is set)
        verilog += "            // Update cache on write hit (write-through also updates cache)\n"
        verilog += "            if (state == WRITE_WAIT && write_through_complete && pending_write_hit) begin\n"
        if self.associativity == 1:
            if self.words_per_line > 1:
                verilog += "                data_array[pending_index][pending_word_offset*DATA_WIDTH +: DATA_WIDTH] <= merged_write_data;\n"
            else:
                verilog += "                data_array[pending_index] <= merged_write_data;\n"
        else:
            if self.words_per_line > 1:
                verilog += "                data_array[pending_index][pending_hit_way][pending_word_offset*DATA_WIDTH +: DATA_WIDTH] <= merged_write_data;\n"
            else:
                verilog += "                data_array[pending_index][pending_hit_way] <= merged_write_data;\n"
        verilog += "            end\n"

        verilog += "        end\n"
        verilog += "    end\n\n"

        return verilog

    def _generate_replacement_logic(self) -> str:
        """Generate replacement policy logic for set-associative caches."""
        if self.associativity == 1:
            return ""

        verilog = "    // Replacement policy logic\n"

        if self.replacement_policy == 'lru':
            verilog += "    // LRU replacement\n"
            verilog += "    integer lru_init_i;\n"
            verilog += "    always @(posedge clk) begin\n"
            verilog += "        if (reset) begin\n"
            verilog += "            for (lru_init_i = 0; lru_init_i < NUM_ROWS; lru_init_i = lru_init_i + 1) begin\n"
            verilog += "                lru_array[lru_init_i] <= 0;\n"
            verilog += "            end\n"
            verilog += "            refill_way <= 0;\n"
            verilog += "        end else begin\n"
            # Update LRU on read hit
            for i in range(self.num_read_ports):
                verilog += f"            if (read_hit_{i}) begin\n"
                verilog += f"                lru_array[read_index_{i}] <= read_hit_way_{i};\n"
                verilog += f"            end\n"
            # Update LRU on write hit
            verilog += "            if (write_req && write_hit) begin\n"
            verilog += "                lru_array[write_index] <= write_hit_way;\n"
            verilog += "            end\n"
            # Select victim way on miss
            verilog += "            if (state == IDLE && read_miss) begin\n"
            verilog += "                refill_way <= 0;\n"
            for way in range(self.associativity):
                verilog += f"                if (!valid_array[miss_addr_comb[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH]][{way}]) refill_way <= {way};\n"
            verilog += "                else refill_way <= lru_array[miss_addr_comb[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH]] ^ 1;\n"
            verilog += "            end\n"
            verilog += "        end\n"
            verilog += "    end\n\n"

        elif self.replacement_policy == 'random':
            verilog += "    // Random replacement using LFSR\n"
            verilog += "    reg [7:0] lfsr;\n"
            verilog += "    always @(posedge clk) begin\n"
            verilog += "        if (reset) begin\n"
            verilog += "            lfsr <= 8'hA5;\n"
            verilog += "            refill_way <= 0;\n"
            verilog += "        end else begin\n"
            verilog += "            lfsr <= {lfsr[6:0], lfsr[7] ^ lfsr[5] ^ lfsr[4] ^ lfsr[3]};\n"
            verilog += "            if (state == IDLE && read_miss) begin\n"
            way_bits = (self.associativity - 1).bit_length()
            verilog += f"                refill_way <= lfsr[{way_bits-1}:0];\n"
            verilog += "            end\n"
            verilog += "        end\n"
            verilog += "    end\n\n"

        return verilog

    def get_port_connections(self,
                            read_addrs: List[str],
                            read_reqs: List[str],
                            read_datas: List[str],
                            read_valids: List[str],
                            write_addr: str,
                            write_data: str,
                            write_byte_enable: str,
                            write_req: str,
                            write_complete: str,
                            refill_addr: str,
                            refill_req: str,
                            refill_data: str,
                            refill_valid: str,
                            write_through_addr: str,
                            write_through_data: str,
                            write_through_byte_enable: str,
                            write_through_req: str,
                            write_through_complete: str,
                            idle: str,
                            complete: str) -> str:
        """Generate instantiation with port connections."""
        connections = [
            "    .clk(clk)",
            "    .reset(reset)"
        ]

        for i in range(self.num_read_ports):
            connections.append(f"    .read_addr_{i}({read_addrs[i]})")
            connections.append(f"    .read_req_{i}({read_reqs[i]})")
            connections.append(f"    .read_data_{i}({read_datas[i]})")
            connections.append(f"    .read_valid_{i}({read_valids[i]})")

        connections.append(f"    .write_addr({write_addr})")
        connections.append(f"    .write_data({write_data})")
        connections.append(f"    .write_byte_enable({write_byte_enable})")
        connections.append(f"    .write_req({write_req})")
        connections.append(f"    .write_complete({write_complete})")

        connections.append(f"    .refill_addr({refill_addr})")
        connections.append(f"    .refill_req({refill_req})")
        connections.append(f"    .refill_data({refill_data})")
        connections.append(f"    .refill_valid({refill_valid})")

        connections.append(f"    .write_through_addr({write_through_addr})")
        connections.append(f"    .write_through_data({write_through_data})")
        connections.append(f"    .write_through_byte_enable({write_through_byte_enable})")
        connections.append(f"    .write_through_req({write_through_req})")
        connections.append(f"    .write_through_complete({write_through_complete})")

        connections.append(f"    .idle({idle})")
        connections.append(f"    .complete({complete})")

        return f"{self.name} {self.name}_inst(\n" + ",\n".join(connections) + "\n);"


@dataclass
class TLBModuleGenerator:
    """Generate parameterized TLB Verilog module with multi-level tag matching.

    This generates a TLB implementation that:
    - Stores entries with depth-aware tags (VPN fields at each level)
    - Performs multi-level tag matching
    - Supports fill at multiple depths during PTW
    - Includes PTW FSM for serialized memory access on miss
    """

    name: str = 'tlb'
    num_entries: int = 64
    associativity: int = 4
    num_levels: int = 2              # Number of page table levels
    vpn_widths: List[int] = field(default_factory=lambda: [10, 10])
    pte_width: int = 32
    replacement_policy: str = 'lru'
    has_flush: bool = True

    def __post_init__(self):
        """Calculate derived parameters."""
        self.total_tag_width = sum(self.vpn_widths)
        self.depth_width = max(1, (self.num_levels).bit_length())
        self.num_sets = self.num_entries // self.associativity
        self.index_width = max(1, (self.num_sets - 1).bit_length())
        self.way_bits = max(1, (self.associativity - 1).bit_length())

    def generate_module(self) -> str:
        """Generate complete Verilog module for the TLB."""
        verilog = self._generate_module_header()
        verilog += self._generate_parameters()
        verilog += self._generate_storage_arrays()
        verilog += self._generate_tag_extraction()
        verilog += self._generate_match_logic()
        verilog += self._generate_read_logic()
        verilog += self._generate_ptw_fsm()
        verilog += self._generate_update_logic()
        verilog += self._generate_replacement_logic()
        verilog += "endmodule\n"
        return verilog

    def _generate_module_header(self) -> str:
        """Generate module declaration with ports."""
        verilog = f"module {self.name} #(\n"
        verilog += f"    parameter NUM_ENTRIES = {self.num_entries},\n"
        verilog += f"    parameter ASSOCIATIVITY = {self.associativity},\n"
        verilog += f"    parameter NUM_LEVELS = {self.num_levels},\n"
        verilog += f"    parameter PTE_WIDTH = {self.pte_width},\n"
        verilog += f"    parameter TOTAL_TAG_WIDTH = {self.total_tag_width}\n"
        verilog += ")(\n"
        verilog += "    input  wire clk,\n"
        verilog += "    input  wire reset,\n"

        # VPN inputs (for lookup)
        verilog += "\n    // VPN inputs for lookup\n"
        for i, width in enumerate(self.vpn_widths):
            verilog += f"    input  wire [{width-1}:0] vpn{i},\n"

        # Per-depth outputs (hit and data)
        verilog += "\n    // Per-depth lookup results\n"
        for depth in range(1, self.num_levels + 1):
            verilog += f"    output reg hit_depth{depth},\n"
            verilog += f"    output reg [PTE_WIDTH-1:0] data_depth{depth},\n"

        # PTW interface
        verilog += "\n    // PTW interface (for refill)\n"
        verilog += f"    input  wire [{self.pte_width-1}:0] ptw_pte_data,\n"
        verilog += f"    input  wire [{self.depth_width-1}:0] ptw_depth,\n"
        verilog += "    input  wire ptw_valid,\n"
        verilog += "    output reg ptw_miss,\n"

        # Control signals
        verilog += "\n    // Control signals\n"
        verilog += "    input  wire lookup_req,\n"
        verilog += "    output reg idle,\n"
        verilog += "    output reg complete,\n"

        # Flush
        if self.has_flush:
            verilog += "\n    // Flush (invalidate all entries)\n"
            verilog += "    input  wire flush\n"
        else:
            # Remove trailing comma from last port
            verilog = verilog.rstrip(",\n") + "\n"

        verilog += ");\n\n"
        return verilog

    def _generate_parameters(self) -> str:
        """Generate local parameters."""
        verilog = "    // Derived parameters\n"
        verilog += f"    localparam NUM_SETS = {self.num_sets};\n"
        verilog += f"    localparam INDEX_WIDTH = {self.index_width};\n"
        verilog += f"    localparam DEPTH_WIDTH = {self.depth_width};\n"
        verilog += f"    localparam WAY_BITS = {self.way_bits};\n"

        # VPN field widths as parameters
        for i, width in enumerate(self.vpn_widths):
            verilog += f"    localparam VPN{i}_WIDTH = {width};\n"

        verilog += "\n"
        return verilog

    def _generate_storage_arrays(self) -> str:
        """Generate TLB entry storage arrays."""
        verilog = "    // TLB entry storage (per set, per way)\n"
        verilog += f"    reg valid_array [0:NUM_SETS-1][0:ASSOCIATIVITY-1];\n"
        verilog += f"    reg [DEPTH_WIDTH-1:0] depth_array [0:NUM_SETS-1][0:ASSOCIATIVITY-1];\n"

        # Per-level VPN storage
        for i, width in enumerate(self.vpn_widths):
            verilog += f"    reg [VPN{i}_WIDTH-1:0] vpn{i}_array [0:NUM_SETS-1][0:ASSOCIATIVITY-1];\n"

        verilog += f"    reg [PTE_WIDTH-1:0] pte_array [0:NUM_SETS-1][0:ASSOCIATIVITY-1];\n"

        if self.replacement_policy == 'lru':
            verilog += f"    reg [WAY_BITS-1:0] lru_array [0:NUM_SETS-1];\n"

        verilog += "\n"
        return verilog

    def _generate_tag_extraction(self) -> str:
        """Generate index extraction from VPNs."""
        verilog = "    // Index extraction (from lowest VPN bits)\n"
        verilog += f"    wire [INDEX_WIDTH-1:0] lookup_index = vpn0[INDEX_WIDTH-1:0];\n"
        verilog += "\n"
        return verilog

    def _generate_match_logic(self) -> str:
        """Generate multi-level tag matching logic."""
        verilog = "    // Multi-level tag matching\n"

        # Per-way, per-depth matching
        for way in range(self.associativity):
            verilog += f"\n    // Way {way} matching\n"

            # Check each VPN level match
            for lvl in range(self.num_levels):
                verilog += f"    wire vpn{lvl}_match_w{way} = (vpn{lvl}_array[lookup_index][{way}] == vpn{lvl});\n"

            # Per-depth hit signals (depth D requires matching VPNs 0..D-1)
            for depth in range(1, self.num_levels + 1):
                match_terms = [f"vpn{lvl}_match_w{way}" for lvl in range(self.num_levels - depth, self.num_levels)]
                match_expr = " && ".join(match_terms) if match_terms else "1'b1"
                verilog += f"    wire depth{depth}_match_w{way} = valid_array[lookup_index][{way}] && "
                verilog += f"(depth_array[lookup_index][{way}] == {depth}) && {match_expr};\n"

        verilog += "\n"

        # Aggregate hits per depth
        for depth in range(1, self.num_levels + 1):
            hit_terms = [f"depth{depth}_match_w{way}" for way in range(self.associativity)]
            verilog += f"    wire any_hit_depth{depth} = " + " || ".join(hit_terms) + ";\n"

        # Overall hit
        all_hit_terms = [f"any_hit_depth{d}" for d in range(1, self.num_levels + 1)]
        verilog += f"    wire any_hit = " + " || ".join(all_hit_terms) + ";\n\n"

        return verilog

    def _generate_read_logic(self) -> str:
        """Generate read data selection logic."""
        verilog = "    // Hit way selection per depth\n"

        for depth in range(1, self.num_levels + 1):
            verilog += f"    reg [WAY_BITS-1:0] hit_way_depth{depth};\n"

        verilog += "\n    always @* begin\n"

        for depth in range(1, self.num_levels + 1):
            verilog += f"        hit_way_depth{depth} = 0;\n"
            for way in range(self.associativity):
                verilog += f"        if (depth{depth}_match_w{way}) hit_way_depth{depth} = {way};\n"

        verilog += "    end\n\n"

        # Output hit and data per depth
        verilog += "    // Output hit and data per depth\n"
        verilog += "    always @* begin\n"

        for depth in range(1, self.num_levels + 1):
            verilog += f"        hit_depth{depth} = lookup_req && any_hit_depth{depth};\n"
            verilog += f"        data_depth{depth} = pte_array[lookup_index][hit_way_depth{depth}];\n"

        verilog += "        ptw_miss = lookup_req && !any_hit;\n"
        verilog += "        idle = 1'b1;  // TLB is always ready\n"
        verilog += "        complete = lookup_req && any_hit;\n"
        verilog += "    end\n\n"

        return verilog

    def _generate_ptw_fsm(self) -> str:
        """Generate PTW FSM for handling TLB misses."""
        # For now, PTW is handled externally. TLB just accepts updates.
        verilog = "    // PTW FSM - handled externally, TLB accepts updates via ptw_valid\n"
        verilog += "\n"
        return verilog

    def _generate_update_logic(self) -> str:
        """Generate TLB update logic (on PTW completion)."""
        verilog = "    // TLB update on PTW completion or flush\n"
        verilog += "    reg [WAY_BITS-1:0] update_way;\n"
        verilog += "    integer init_i, init_j;\n\n"

        verilog += "    always @(posedge clk) begin\n"
        if self.has_flush:
            verilog += "        if (reset || flush) begin\n"
        else:
            verilog += "        if (reset) begin\n"

        verilog += "            for (init_i = 0; init_i < NUM_SETS; init_i = init_i + 1) begin\n"
        verilog += "                for (init_j = 0; init_j < ASSOCIATIVITY; init_j = init_j + 1) begin\n"
        verilog += "                    valid_array[init_i][init_j] <= 1'b0;\n"
        verilog += "                end\n"
        verilog += "            end\n"
        verilog += "        end else if (ptw_valid) begin\n"
        verilog += "            valid_array[lookup_index][update_way] <= 1'b1;\n"
        verilog += "            depth_array[lookup_index][update_way] <= ptw_depth;\n"

        for i in range(self.num_levels):
            verilog += f"            vpn{i}_array[lookup_index][update_way] <= vpn{i};\n"

        verilog += "            pte_array[lookup_index][update_way] <= ptw_pte_data;\n"
        verilog += "        end\n"
        verilog += "    end\n\n"

        return verilog

    def _generate_replacement_logic(self) -> str:
        """Generate replacement policy logic."""
        if self.associativity == 1:
            return "    // Direct-mapped: update_way always 0\n    always @* update_way = 0;\n\n"

        verilog = "    // LRU replacement\n"
        verilog += "    integer lru_init_i;\n"
        verilog += "    always @(posedge clk) begin\n"
        verilog += "        if (reset) begin\n"
        verilog += "            for (lru_init_i = 0; lru_init_i < NUM_SETS; lru_init_i = lru_init_i + 1) begin\n"
        verilog += "                lru_array[lru_init_i] <= 0;\n"
        verilog += "            end\n"
        verilog += "            update_way <= 0;\n"
        verilog += "        end else begin\n"

        # Update LRU on hit
        verilog += "            if (lookup_req && any_hit) begin\n"
        for depth in range(1, self.num_levels + 1):
            verilog += f"                if (any_hit_depth{depth}) lru_array[lookup_index] <= hit_way_depth{depth};\n"
        verilog += "            end\n"

        # Select victim way on miss
        verilog += "            if (lookup_req && !any_hit) begin\n"
        verilog += "                update_way <= 0;\n"
        for way in range(self.associativity):
            verilog += f"                if (!valid_array[lookup_index][{way}]) update_way <= {way};\n"
        verilog += "                else update_way <= lru_array[lookup_index] ^ 1;\n"
        verilog += "            end\n"
        verilog += "        end\n"
        verilog += "    end\n\n"

        return verilog

    def get_port_connections(self, **kwargs) -> str:
        """Generate instantiation with port connections."""
        connections = [
            "    .clk(clk)",
            "    .reset(reset)"
        ]

        # VPN inputs
        for i in range(self.num_levels):
            vpn_signal = kwargs.get(f'vpn{i}', f'vpn{i}')
            connections.append(f"    .vpn{i}({vpn_signal})")

        # Per-depth outputs
        for depth in range(1, self.num_levels + 1):
            hit_signal = kwargs.get(f'hit_depth{depth}', f'hit_depth{depth}')
            data_signal = kwargs.get(f'data_depth{depth}', f'data_depth{depth}')
            connections.append(f"    .hit_depth{depth}({hit_signal})")
            connections.append(f"    .data_depth{depth}({data_signal})")

        # PTW interface
        connections.append(f"    .ptw_pte_data({kwargs.get('ptw_pte_data', 'ptw_pte_data')})")
        connections.append(f"    .ptw_depth({kwargs.get('ptw_depth', 'ptw_depth')})")
        connections.append(f"    .ptw_valid({kwargs.get('ptw_valid', 'ptw_valid')})")
        connections.append(f"    .ptw_miss({kwargs.get('ptw_miss', 'ptw_miss')})")

        # Control
        connections.append(f"    .lookup_req({kwargs.get('lookup_req', 'lookup_req')})")
        connections.append(f"    .idle({kwargs.get('idle', 'idle')})")
        connections.append(f"    .complete({kwargs.get('complete', 'complete')})")

        if self.has_flush:
            connections.append(f"    .flush({kwargs.get('flush', 'flush')})")

        return f"{self.name} {self.name}_inst(\n" + ",\n".join(connections) + "\n);"


@dataclass
class InstructionBufferGenerator:
    """Generate parameterized instruction buffer Verilog module.

    This generates a complete instruction buffer (prefetch buffer) including:
    - Circular FIFO buffer storing fetched instruction bytes
    - Fetch FSM that reads fetch_width bits from memory per cycle
    - Byte-level read pointer advanced by decoded instruction width
    - Multi-offset output alignment logic (one port per PC+N access)
    - Valid signaling when sufficient bytes are buffered
    - Flush + redirect_addr support for branch mispredictions
    """

    name: str
    fetch_width: int = 32           # bits fetched per cycle from memory
    buffer_size: int = 4            # number of fetch_width entries in FIFO
    address_width: int = 32
    data_width: int = 32            # output instruction width in bits
    has_flush: bool = False
    output_offsets: List[int] = field(default_factory=list)  # byte offsets for output ports

    def __post_init__(self):
        """Calculate derived parameters."""
        self.fetch_bytes = self.fetch_width // 8
        self.buffer_capacity_bytes = self.buffer_size * self.fetch_bytes
        if self.buffer_capacity_bytes & (self.buffer_capacity_bytes - 1):
            raise ValueError(
                f"Buffer capacity {self.buffer_capacity_bytes} bytes "
                f"(buffer_size={self.buffer_size} * fetch_bytes={self.fetch_bytes}) "
                f"must be a power of 2 for efficient circular buffer indexing")
        self.ptr_width = (self.buffer_capacity_bytes - 1).bit_length()
        self.data_bytes = self.data_width // 8
        if not self.output_offsets:
            self.output_offsets = [0]

    def generate_module(self) -> str:
        """Generate complete Verilog module for the instruction buffer."""
        verilog = self._generate_module_header()
        verilog += self._generate_parameters()
        verilog += self._generate_storage()
        verilog += self._generate_output_logic()
        verilog += self._generate_fetch_fsm()
        verilog += self._generate_flush_logic()
        verilog += "endmodule\n"
        return verilog

    def _generate_module_header(self) -> str:
        """Generate module declaration with ports."""
        verilog = f"module {self.name} #(\n"
        verilog += f"    parameter FETCH_WIDTH = {self.fetch_width},\n"
        verilog += f"    parameter BUFFER_SIZE = {self.buffer_size},\n"
        verilog += f"    parameter ADDR_WIDTH = {self.address_width},\n"
        verilog += f"    parameter DATA_WIDTH = {self.data_width}\n"
        verilog += ")(\n"
        verilog += "    input  wire clk,\n"
        verilog += "    input  wire reset,\n"
        verilog += "\n    // Fetch interface to backing memory\n"
        verilog += "    output reg [ADDR_WIDTH-1:0] fetch_addr,\n"
        verilog += "    output reg fetch_req,\n"
        verilog += f"    input  wire [FETCH_WIDTH-1:0] fetch_data,\n"
        verilog += "    input  wire fetch_valid,\n"

        # Generate one output port per byte offset
        verilog += "\n    // Instruction output ports (one per PC+N access)\n"
        for i, offset in enumerate(self.output_offsets):
            verilog += f"    output wire [DATA_WIDTH-1:0] out_data_{i},  // byte offset {offset}\n"
            verilog += f"    output wire out_valid_{i},\n"

        verilog += "\n    // Consume interface (from decode)\n"
        consume_width = max((self.fetch_bytes - 1).bit_length(), 1)
        verilog += f"    input  wire [{consume_width}:0] consume_bytes,\n"
        verilog += "    input  wire consume_valid,\n"
        verilog += "\n    // Reset address (initial fetch address, e.g., reset PC)\n"
        verilog += "    input  wire [ADDR_WIDTH-1:0] reset_addr"
        if self.has_flush:
            verilog += ",\n\n    // Flush + redirect control (e.g., branch misprediction)\n"
            verilog += "    input  wire flush,\n"
            verilog += "    input  wire [ADDR_WIDTH-1:0] redirect_addr"
        verilog += "\n);\n\n"
        return verilog

    def _generate_parameters(self) -> str:
        """Generate local parameters."""
        verilog = "    // Derived parameters\n"
        verilog += f"    localparam FETCH_BYTES = FETCH_WIDTH / 8;\n"
        verilog += f"    localparam BUF_BYTES = BUFFER_SIZE * FETCH_BYTES;\n"
        verilog += f"    localparam PTR_WIDTH = {self.ptr_width};\n"
        verilog += f"    localparam DATA_BYTES = DATA_WIDTH / 8;\n"
        max_offset = max(self.output_offsets) if self.output_offsets else 0
        verilog += f"    localparam MAX_OFFSET = {max_offset};\n\n"
        return verilog

    def _generate_storage(self) -> str:
        """Generate buffer storage and pointers."""
        verilog = "    // Buffer storage (byte-addressable circular buffer)\n"
        verilog += "    reg [7:0] buffer [0:BUF_BYTES-1];\n"
        verilog += "    reg [PTR_WIDTH:0] wr_ptr;  // Write pointer (byte offset)\n"
        verilog += "    reg [PTR_WIDTH:0] rd_ptr;  // Read pointer (byte offset)\n"
        verilog += "    reg [PTR_WIDTH:0] count;   // Number of valid bytes in buffer\n\n"

        verilog += "    // Buffer occupancy\n"
        verilog += "    wire buf_full  = (count + FETCH_BYTES > BUF_BYTES);\n"
        max_offset = max(self.output_offsets) if self.output_offsets else 0
        min_bytes_needed = max_offset + self.data_bytes
        verilog += f"    wire buf_has_data = (count >= {min_bytes_needed});  // need up to offset {max_offset} + DATA_BYTES\n\n"
        return verilog

    def _generate_output_logic(self) -> str:
        """Generate output alignment logic for each byte offset.

        For each output port at offset N, reads DATA_BYTES from the circular
        buffer starting at (rd_ptr + N), handling wrap-around.
        """
        verilog = "    // Output alignment - multi-offset output ports\n"
        verilog += "    // Each port reads DATA_BYTES starting at rd_ptr + byte_offset\n"
        verilog += "    genvar gi;\n"

        for i, offset in enumerate(self.output_offsets):
            verilog += f"\n    // Output port {i}: byte offset {offset} from rd_ptr\n"
            verilog += "    generate\n"
            verilog += f"        for (gi = 0; gi < DATA_BYTES; gi = gi + 1) begin : gen_out_{i}\n"
            verilog += f"            wire [PTR_WIDTH:0] idx_{i} = (rd_ptr + {offset} + gi) & (BUF_BYTES-1);\n"
            verilog += f"            assign out_data_{i}[gi*8 +: 8] = buffer[idx_{i}];\n"
            verilog += "        end\n"
            verilog += "    endgenerate\n"
            verilog += f"    assign out_valid_{i} = buf_has_data;\n"

        verilog += "\n"
        return verilog

    def _generate_fetch_fsm(self) -> str:
        """Generate the fetch and consume state machine.

        Flush logic is integrated here (as a priority branch) to avoid
        dual-always-block races on shared registers.
        """
        verilog = "    // Fetch and consume logic\n"
        verilog += "    integer i;\n"
        verilog += "    always @(posedge clk) begin\n"
        verilog += "        if (reset) begin\n"
        verilog += "            wr_ptr <= 0;\n"
        verilog += "            rd_ptr <= 0;\n"
        verilog += "            count  <= 0;\n"
        verilog += "            fetch_addr <= reset_addr;\n"
        verilog += "            fetch_req <= 1'b1;  // Start fetching immediately\n"

        # Flush takes priority over normal operation (only when decode is valid)
        if self.has_flush:
            verilog += "        end else if (flush && buf_has_data) begin\n"
            verilog += "            // Flush: clear buffer and redirect fetch to new address\n"
            verilog += "            wr_ptr <= 0;\n"
            verilog += "            rd_ptr <= 0;\n"
            verilog += "            count  <= 0;\n"
            verilog += "            fetch_addr <= redirect_addr;\n"
            verilog += "            fetch_req <= 1'b1;\n"

        verilog += "        end else begin\n"

        # Handle consume (decode advances read pointer)
        verilog += "            // Consume: decode tells us how many bytes it used\n"
        verilog += "            if (consume_valid && buf_has_data) begin\n"
        verilog += "                rd_ptr <= (rd_ptr + consume_bytes) & (BUF_BYTES-1);\n"
        verilog += "                count  <= count - consume_bytes;\n"
        verilog += "            end\n\n"

        # Handle fetch (write new data into buffer)
        verilog += "            // Fetch: write incoming data into buffer\n"
        verilog += "            // Gate with !buf_full to prevent overflow when fetch_req\n"
        verilog += "            // was set before count increased on a prior cycle.\n"
        verilog += "            if (fetch_valid && fetch_req && !buf_full) begin\n"
        verilog += "                for (i = 0; i < FETCH_BYTES; i = i + 1) begin\n"
        verilog += "                    buffer[(wr_ptr + i) & (BUF_BYTES-1)] <= fetch_data[i*8 +: 8];\n"
        verilog += "                end\n"
        verilog += "                wr_ptr <= (wr_ptr + FETCH_BYTES) & (BUF_BYTES-1);\n"
        verilog += "                count  <= count + FETCH_BYTES"
        # Account for simultaneous consume
        verilog += "\n                           - ((consume_valid && buf_has_data) ? consume_bytes : 0);\n"
        verilog += "                fetch_addr <= fetch_addr + FETCH_BYTES;\n"
        verilog += "            end\n\n"

        # Fetch request logic
        verilog += "            // Request next fetch when buffer has space\n"
        verilog += "            fetch_req  <= !buf_full;\n"

        verilog += "        end\n"
        verilog += "    end\n\n"
        return verilog

    def _generate_flush_logic(self) -> str:
        """Flush logic is now integrated into _generate_fetch_fsm as a priority branch."""
        return ""

    def get_port_connections(self,
                             fetch_addr: str,
                             fetch_req: str,
                             fetch_data: str,
                             fetch_valid: str,
                             out_datas: Optional[List[str]] = None,
                             out_valids: Optional[List[str]] = None,
                             out_data: Optional[str] = None,
                             out_valid: Optional[str] = None,
                             consume_bytes: str = '',
                             consume_valid: str = '',
                             reset_addr: Optional[str] = None,
                             flush_signal: Optional[str] = None,
                             redirect_addr: Optional[str] = None) -> str:
        """Generate instantiation with port connections.

        Args:
            fetch_addr: Fetch address signal name
            fetch_req: Fetch request signal name
            fetch_data: Fetch data signal name
            fetch_valid: Fetch valid signal name
            out_datas: List of output data signal names (one per offset port)
            out_valids: List of output valid signal names (one per offset port)
            out_data: Legacy single output data signal name (used if out_datas not provided)
            out_valid: Legacy single output valid signal name (used if out_valids not provided)
            consume_bytes: Consume byte count signal name
            consume_valid: Consume valid signal name
            reset_addr: Optional reset address signal name (initial fetch address)
            flush_signal: Optional flush signal name
            redirect_addr: Optional redirect address signal name
        """
        connections = [
            "    .clk(clk)",
            "    .reset(reset)"
        ]

        # Fetch interface
        connections.append(f"    .fetch_addr({fetch_addr})")
        connections.append(f"    .fetch_req({fetch_req})")
        connections.append(f"    .fetch_data({fetch_data})")
        connections.append(f"    .fetch_valid({fetch_valid})")

        # Output interface - multi-port or legacy single-port
        if out_datas and out_valids:
            for i in range(len(out_datas)):
                connections.append(f"    .out_data_{i}({out_datas[i]})")
                connections.append(f"    .out_valid_{i}({out_valids[i]})")
        else:
            # Legacy single-port fallback
            data_name = out_data if out_data else f"{self.name}_data_0"
            valid_name = out_valid if out_valid else f"{self.name}_valid_0"
            connections.append(f"    .out_data_0({data_name})")
            connections.append(f"    .out_valid_0({valid_name})")

        # Consume interface
        connections.append(f"    .consume_bytes({consume_bytes})")
        connections.append(f"    .consume_valid({consume_valid})")

        # Reset address (initial fetch address)
        reset_addr_expr = reset_addr if reset_addr is not None else f"{self.address_width}'d0"
        connections.append(f"    .reset_addr({reset_addr_expr})")

        # Flush + redirect
        if self.has_flush:
            flush_expr = flush_signal if flush_signal is not None else "1'b0"
            connections.append(f"    .flush({flush_expr})")
            redirect_expr = redirect_addr if redirect_addr is not None else f"{self.address_width}'d0"
            connections.append(f"    .redirect_addr({redirect_expr})")

        return f"{self.name} {self.name}_inst(\n" + ",\n".join(connections) + "\n);"




@dataclass
class BranchTargetBufferGenerator:
    """Generate parameterized Branch Target Buffer Verilog module.

    This generates a complete BTB implementation including:
    - Tag array for PC matching
    - Target address storage
    - Taken/not-taken prediction bits
    - Valid bit tracking
    - Configurable entry count and associativity
    - Synchronous update interface
    - Optional dual-port lookup for Execute stage misprediction detection
    """

    name: str
    num_entries: int = 64
    associativity: int = 1       # 1 = direct-mapped
    pc_width: int = 32
    target_width: int = 32
    dual_port: bool = False      # Enable second lookup port for Execute stage

    def __post_init__(self):
        """Calculate derived parameters."""
        self.num_sets = self.num_entries // self.associativity
        self.index_width = max(1, (self.num_sets - 1).bit_length())
        # Tag is upper bits of PC (excluding index and 2 LSBs for word alignment)
        self.tag_width = self.pc_width - self.index_width - 2

    def generate_module(self) -> str:
        """Generate complete Verilog module for the BTB."""
        verilog = self._generate_module_header()
        verilog += self._generate_storage_arrays()
        verilog += self._generate_address_decoding()
        verilog += self._generate_lookup_logic()
        verilog += self._generate_update_logic()
        verilog += "endmodule\n"
        return verilog

    def _generate_module_header(self) -> str:
        """Generate module declaration with ports."""
        verilog = f"module {self.name} #(\n"
        verilog += f"    parameter NUM_ENTRIES = {self.num_entries},\n"
        verilog += f"    parameter ASSOCIATIVITY = {self.associativity},\n"
        verilog += f"    parameter PC_WIDTH = {self.pc_width},\n"
        verilog += f"    parameter TARGET_WIDTH = {self.target_width}\n"
        verilog += ")(\n"
        verilog += "    input  wire clk,\n"
        verilog += "    input  wire reset,\n"
        verilog += "\n    // Lookup interface (Fetch stage)\n"
        verilog += "    input  wire [PC_WIDTH-1:0] lookup_pc,\n"
        verilog += "    output reg  hit,\n"
        verilog += "    output reg  [TARGET_WIDTH-1:0] predicted_target,\n"
        verilog += "    output reg  predicted_taken,\n"

        if self.dual_port:
            verilog += "\n    // Execute stage lookup interface (for misprediction detection)\n"
            verilog += "    input  wire [PC_WIDTH-1:0] execute_lookup_pc,\n"
            verilog += "    output reg  execute_hit,\n"
            verilog += "    output reg  execute_predicted_taken,\n"

        verilog += "\n    // Update interface (Execute stage)\n"
        verilog += "    input  wire update_enable,\n"
        verilog += "    input  wire [PC_WIDTH-1:0] update_pc,\n"
        verilog += "    input  wire [TARGET_WIDTH-1:0] update_target,\n"
        verilog += "    input  wire update_taken\n"
        verilog += ");\n\n"
        return verilog

    def _generate_storage_arrays(self) -> str:
        """Generate tag, target, taken, and valid arrays."""
        verilog = "    // Derived parameters\n"
        verilog += f"    localparam NUM_SETS = NUM_ENTRIES / ASSOCIATIVITY;\n"
        verilog += f"    localparam INDEX_WIDTH = {self.index_width};\n"
        verilog += f"    localparam TAG_WIDTH = PC_WIDTH - INDEX_WIDTH - 2;\n\n"
        verilog += "    // Storage arrays\n"

        if self.associativity == 1:
            # Direct-mapped BTB
            verilog += "    reg [TAG_WIDTH-1:0] tag_array [0:NUM_SETS-1];\n"
            verilog += "    reg [TARGET_WIDTH-1:0] target_array [0:NUM_SETS-1];\n"
            verilog += "    reg taken_array [0:NUM_SETS-1];\n"
            verilog += "    reg valid_array [0:NUM_SETS-1];\n"

            # Add initial block to prevent X values before first reset
            verilog += "\n    // Initial block to prevent X values during pre-reset simulation\n"
            verilog += "    initial begin : init_arrays\n"
            verilog += "        integer i;\n"
            verilog += "        for (i = 0; i < NUM_SETS; i = i + 1) begin\n"
            verilog += "            valid_array[i] = 1'b0;\n"
            verilog += "            taken_array[i] = 1'b0;\n"
            verilog += f"            tag_array[i] = {self.tag_width}'b0;\n"
            verilog += f"            target_array[i] = {self.target_width}'d0;\n"
            verilog += "        end\n"
            verilog += "    end\n"
        else:
            # Set-associative BTB
            verilog += f"    reg [TAG_WIDTH-1:0] tag_array [0:NUM_SETS-1][0:ASSOCIATIVITY-1];\n"
            verilog += f"    reg [TARGET_WIDTH-1:0] target_array [0:NUM_SETS-1][0:ASSOCIATIVITY-1];\n"
            verilog += f"    reg taken_array [0:NUM_SETS-1][0:ASSOCIATIVITY-1];\n"
            verilog += f"    reg valid_array [0:NUM_SETS-1][0:ASSOCIATIVITY-1];\n"
            # Simple round-robin replacement
            verilog += f"    reg [{(self.associativity - 1).bit_length()-1}:0] replace_way [0:NUM_SETS-1];\n"

            # Add initial block to prevent X values before first reset
            verilog += "\n    // Initial block to prevent X values during pre-reset simulation\n"
            verilog += "    initial begin : init_arrays\n"
            verilog += "        integer i, w;\n"
            verilog += "        for (i = 0; i < NUM_SETS; i = i + 1) begin\n"
            verilog += "            replace_way[i] = 0;\n"
            verilog += "            for (w = 0; w < ASSOCIATIVITY; w = w + 1) begin\n"
            verilog += "                valid_array[i][w] = 1'b0;\n"
            verilog += "                taken_array[i][w] = 1'b0;\n"
            verilog += f"                tag_array[i][w] = {self.tag_width}'b0;\n"
            verilog += f"                target_array[i][w] = {self.target_width}'d0;\n"
            verilog += "            end\n"
            verilog += "        end\n"
            verilog += "    end\n"

        verilog += "\n"
        return verilog

    def _generate_address_decoding(self) -> str:
        """Generate address field extraction for lookup and update."""
        verilog = "    // Address decoding - Fetch stage lookup\n"
        verilog += "    wire [TAG_WIDTH-1:0] lookup_tag = lookup_pc[PC_WIDTH-1:INDEX_WIDTH+2];\n"
        verilog += "    wire [INDEX_WIDTH-1:0] lookup_index = lookup_pc[INDEX_WIDTH+1:2];\n\n"

        if self.dual_port:
            verilog += "    // Address decoding - Execute stage lookup\n"
            verilog += "    wire [TAG_WIDTH-1:0] execute_lookup_tag = execute_lookup_pc[PC_WIDTH-1:INDEX_WIDTH+2];\n"
            verilog += "    wire [INDEX_WIDTH-1:0] execute_lookup_index = execute_lookup_pc[INDEX_WIDTH+1:2];\n\n"

        verilog += "    // Address decoding - update\n"
        verilog += "    wire [TAG_WIDTH-1:0] update_tag = update_pc[PC_WIDTH-1:INDEX_WIDTH+2];\n"
        verilog += "    wire [INDEX_WIDTH-1:0] update_index = update_pc[INDEX_WIDTH+1:2];\n\n"
        return verilog

    def _generate_lookup_logic(self) -> str:
        """Generate combinational lookup logic."""
        verilog = "    // Fetch stage lookup logic (combinational)\n"
        verilog += "    always @* begin\n"

        if self.associativity == 1:
            # Direct-mapped lookup
            verilog += "        hit = valid_array[lookup_index] && (tag_array[lookup_index] == lookup_tag);\n"
            verilog += "        predicted_target = target_array[lookup_index];\n"
            verilog += "        predicted_taken = taken_array[lookup_index];\n"
        else:
            # Set-associative lookup
            verilog += "        hit = 1'b0;\n"
            verilog += f"        predicted_target = {self.target_width}'d0;\n"
            verilog += "        predicted_taken = 1'b0;\n"
            verilog += "        begin : lookup_ways\n"
            verilog += "            integer way;\n"
            verilog += "            for (way = 0; way < ASSOCIATIVITY; way = way + 1) begin\n"
            verilog += "                if (valid_array[lookup_index][way] && (tag_array[lookup_index][way] == lookup_tag)) begin\n"
            verilog += "                    hit = 1'b1;\n"
            verilog += "                    predicted_target = target_array[lookup_index][way];\n"
            verilog += "                    predicted_taken = taken_array[lookup_index][way];\n"
            verilog += "                end\n"
            verilog += "            end\n"
            verilog += "        end\n"

        verilog += "    end\n\n"

        # Add Execute stage lookup if dual_port is enabled
        if self.dual_port:
            verilog += "    // Execute stage lookup logic (for misprediction detection)\n"
            verilog += "    always @* begin\n"
            if self.associativity == 1:
                verilog += "        execute_hit = valid_array[execute_lookup_index] && (tag_array[execute_lookup_index] == execute_lookup_tag);\n"
                verilog += "        execute_predicted_taken = taken_array[execute_lookup_index];\n"
            else:
                verilog += "        execute_hit = 1'b0;\n"
                verilog += "        execute_predicted_taken = 1'b0;\n"
                verilog += "        begin : execute_lookup_ways\n"
                verilog += "            integer way;\n"
                verilog += "            for (way = 0; way < ASSOCIATIVITY; way = way + 1) begin\n"
                verilog += "                if (valid_array[execute_lookup_index][way] && (tag_array[execute_lookup_index][way] == execute_lookup_tag)) begin\n"
                verilog += "                    execute_hit = 1'b1;\n"
                verilog += "                    execute_predicted_taken = taken_array[execute_lookup_index][way];\n"
                verilog += "                end\n"
                verilog += "            end\n"
                verilog += "        end\n"
            verilog += "    end\n\n"

        return verilog

    def _generate_update_logic(self) -> str:
        """Generate synchronous update logic."""
        verilog = "    // Update logic (synchronous)\n"

        if self.associativity == 1:
            # Direct-mapped update
            verilog += "    always @(posedge clk) begin\n"
            verilog += "        if (reset) begin\n"
            verilog += "            // Reset all arrays to prevent X propagation\n"
            verilog += "            begin : reset_btb\n"
            verilog += "                integer i;\n"
            verilog += "                for (i = 0; i < NUM_SETS; i = i + 1) begin\n"
            verilog += "                    valid_array[i] <= 1'b0;\n"
            verilog += "                    taken_array[i] <= 1'b0;\n"
            verilog += f"                    tag_array[i] <= {self.tag_width}'b0;\n"
            verilog += f"                    target_array[i] <= {self.target_width}'d0;\n"
            verilog += "                end\n"
            verilog += "            end\n"
            verilog += "        end else if (update_enable) begin\n"
            verilog += "            tag_array[update_index] <= update_tag;\n"
            verilog += "            target_array[update_index] <= update_target;\n"
            verilog += "            taken_array[update_index] <= update_taken;\n"
            verilog += "            valid_array[update_index] <= 1'b1;\n"
            verilog += "        end\n"
            verilog += "    end\n\n"
        else:
            # Set-associative update with round-robin replacement
            way_width = max(1, (self.associativity - 1).bit_length())
            verilog += f"    reg [{way_width-1}:0] victim_way;\n"
            verilog += f"    reg found_match;\n\n"
            verilog += "    always @(posedge clk) begin\n"
            verilog += "        if (reset) begin\n"
            verilog += "            begin : reset_btb\n"
            verilog += "                integer i, w;\n"
            verilog += "                for (i = 0; i < NUM_SETS; i = i + 1) begin\n"
            verilog += "                    replace_way[i] <= 0;\n"
            verilog += "                    for (w = 0; w < ASSOCIATIVITY; w = w + 1) begin\n"
            verilog += "                        valid_array[i][w] <= 1'b0;\n"
            verilog += "                        taken_array[i][w] <= 1'b0;\n"
            verilog += f"                        tag_array[i][w] <= {self.tag_width}'b0;\n"
            verilog += f"                        target_array[i][w] <= {self.target_width}'d0;\n"
            verilog += "                    end\n"
            verilog += "                end\n"
            verilog += "            end\n"
            verilog += "        end else if (update_enable) begin\n"
            verilog += "            // Check for existing entry to update\n"
            verilog += "            found_match = 1'b0;\n"
            verilog += "            victim_way = replace_way[update_index];\n"
            verilog += "            begin : find_match\n"
            verilog += "                integer w;\n"
            verilog += "                for (w = 0; w < ASSOCIATIVITY; w = w + 1) begin\n"
            verilog += "                    if (valid_array[update_index][w] && (tag_array[update_index][w] == update_tag)) begin\n"
            verilog += "                        found_match = 1'b1;\n"
            verilog += f"                        victim_way = w[{way_width-1}:0];\n"
            verilog += "                    end\n"
            verilog += "                end\n"
            verilog += "            end\n"
            verilog += "            // Update the entry\n"
            verilog += "            tag_array[update_index][victim_way] <= update_tag;\n"
            verilog += "            target_array[update_index][victim_way] <= update_target;\n"
            verilog += "            taken_array[update_index][victim_way] <= update_taken;\n"
            verilog += "            valid_array[update_index][victim_way] <= 1'b1;\n"
            verilog += "            // Advance replacement pointer if not updating existing entry\n"
            verilog += "            if (!found_match) begin\n"
            verilog += "                replace_way[update_index] <= (replace_way[update_index] + 1) % ASSOCIATIVITY;\n"
            verilog += "            end\n"
            verilog += "        end\n"
            verilog += "    end\n\n"

        return verilog

    def get_port_connections(self,
                            lookup_pc: str,
                            hit: str,
                            predicted_target: str,
                            predicted_taken: str,
                            update_enable: str,
                            update_pc: str,
                            update_target: str,
                            update_taken: str,
                            execute_lookup_pc: str = None,
                            execute_hit: str = None,
                            execute_predicted_taken: str = None) -> str:
        """Generate instantiation with port connections.

        Args:
            lookup_pc: Fetch stage PC for lookup
            hit: BTB hit output signal
            predicted_target: Predicted branch target output
            predicted_taken: Predicted taken bit output
            update_enable: Update enable signal
            update_pc: PC to update
            update_target: Target address to store
            update_taken: Taken bit to store
            execute_lookup_pc: Execute stage PC for dual-port lookup (optional)
            execute_hit: Execute stage hit output (optional)
            execute_predicted_taken: Execute stage predicted taken output (optional)
        """
        connections = [
            "    .clk(clk)",
            "    .reset(reset)",
            f"    .lookup_pc({lookup_pc})",
            f"    .hit({hit})",
            f"    .predicted_target({predicted_target})",
            f"    .predicted_taken({predicted_taken})",
            f"    .update_enable({update_enable})",
            f"    .update_pc({update_pc})",
            f"    .update_target({update_target})",
            f"    .update_taken({update_taken})"
        ]

        # Add dual-port connections if enabled
        if self.dual_port and execute_lookup_pc:
            connections.append(f"    .execute_lookup_pc({execute_lookup_pc})")
        if self.dual_port and execute_hit:
            connections.append(f"    .execute_hit({execute_hit})")
        if self.dual_port and execute_predicted_taken:
            connections.append(f"    .execute_predicted_taken({execute_predicted_taken})")

        return f"{self.name} {self.name}_inst(\n" + ",\n".join(connections) + "\n);"




@dataclass
class RegisterRenamerGenerator:
    """Generate Verilog for register renaming hardware.

    This generates a complete register renaming unit including:
    - Speculative rename table (RAT): maps architectural -> physical registers,
      updated at Decode on allocation
    - Committed rename table (C-RAT): maps architectural -> physical registers,
      updated at Writeback on commit
    - Free list: tracks available physical registers
    - Allocation logic: assigns new physical registers for writes (at Decode)
    - Lookup logic: returns physical register for reads (at Decode)
    - Commit logic: updates committed RAT and tracks committed free-list state
    - Flush recovery: restores speculative RAT and free-list head from committed
      state on branch misprediction

    For in-order pipelines with speculative Decode-stage allocation.
    """

    name: str
    num_arch_regs: int = 32       # Number of architectural registers (e.g., 32 for RISC-V)
    num_phys_regs: int = 64       # Number of physical registers
    num_read_ports: int = 2       # Number of simultaneous read lookups
    num_write_ports: int = 1      # Number of simultaneous allocations
    arch_reg_width: int = 5       # Bits to address architectural registers (log2(32) = 5)

    def __post_init__(self):
        """Calculate derived parameters."""
        import math
        if self.num_phys_regs <= self.num_arch_regs:
            raise ValueError(
                f"num_phys_regs ({self.num_phys_regs}) must be greater than "
                f"num_arch_regs ({self.num_arch_regs}) to build a valid free list"
            )
        self.phys_reg_width = math.ceil(math.log2(self.num_phys_regs)) if self.num_phys_regs > 1 else 1

    def generate_module(self) -> str:
        """Generate complete Verilog module for register renaming unit."""
        verilog = self._generate_module_header()
        verilog += self._generate_rename_table()
        verilog += self._generate_free_list()
        verilog += self._generate_lookup_logic()
        verilog += self._generate_allocation_logic()
        verilog += "endmodule\n"
        return verilog

    def _generate_module_header(self) -> str:
        """Generate module declaration with ports."""
        verilog = f"// Register Renaming Unit: {self.num_arch_regs} arch regs -> {self.num_phys_regs} phys regs\n"
        verilog += f"// Speculative allocation at Decode, committed RAT for flush recovery\n"
        verilog += f"module {self.name} (\n"
        verilog += "    input  wire clk,\n"
        verilog += "    input  wire reset,\n"
        verilog += "    input  wire stall,\n"
        verilog += "    input  wire flush,\n"
        verilog += "\n"

        # Read ports (lookups for source registers)
        for i in range(self.num_read_ports):
            verilog += f"    // Read port {i} (source register lookup at Decode)\n"
            verilog += f"    input  wire [{self.arch_reg_width-1}:0] read_arch_{i},\n"
            verilog += f"    input  wire read_valid_{i},\n"
            verilog += f"    output wire [{self.phys_reg_width-1}:0] read_phys_{i},\n"
            verilog += "\n"

        # Write ports (allocations for destination registers at Decode)
        for i in range(self.num_write_ports):
            verilog += f"    // Write port {i} (destination register allocation at Decode)\n"
            verilog += f"    input  wire [{self.arch_reg_width-1}:0] write_arch_{i},\n"
            verilog += f"    input  wire write_valid_{i},\n"
            verilog += f"    output wire [{self.phys_reg_width-1}:0] write_phys_{i},\n"
            verilog += f"    output wire [{self.phys_reg_width-1}:0] write_old_phys_{i},\n"
            verilog += "\n"

        # Commit ports (at Writeback - updates committed RAT)
        for i in range(self.num_write_ports):
            verilog += f"    // Commit port {i} (Writeback-stage committed RAT update)\n"
            verilog += f"    input  wire [{self.arch_reg_width-1}:0] commit_arch_{i},\n"
            verilog += f"    input  wire [{self.phys_reg_width-1}:0] commit_phys_{i},\n"
            verilog += f"    input  wire commit_valid_{i},\n"
            verilog += "\n"

        # Free port (for register reclamation at Writeback)
        verilog += "    // Free port (register reclamation at Writeback)\n"
        verilog += f"    input  wire [{self.phys_reg_width-1}:0] free_phys,\n"
        verilog += "    input  wire free_valid,\n"
        verilog += "\n"

        # Status outputs
        verilog += "    // Status\n"
        verilog += "    output wire free_list_empty,\n"
        verilog += f"    output wire [{self.phys_reg_width}:0] free_count\n"
        verilog += ");\n\n"

        return verilog

    def _generate_rename_table(self) -> str:
        """Generate speculative and committed rename table (RAT) storage."""
        verilog = "    // Speculative Rename Table (RAT): updated at Decode on allocation\n"
        verilog += f"    reg [{self.phys_reg_width-1}:0] rename_table [0:{self.num_arch_regs-1}];\n"
        verilog += "\n"
        verilog += "    // Committed Rename Table (C-RAT): updated at Writeback on commit\n"
        verilog += f"    reg [{self.phys_reg_width-1}:0] committed_rat [0:{self.num_arch_regs-1}];\n"
        verilog += "\n"

        # Initialization - architectural reg N maps to physical reg N initially
        verilog += "    // Initialize both rename tables: arch[i] -> phys[i]\n"
        verilog += "    integer init_i;\n"
        verilog += "    initial begin\n"
        verilog += f"        for (init_i = 0; init_i < {self.num_arch_regs}; init_i = init_i + 1) begin\n"
        verilog += f"            rename_table[init_i] = init_i[{self.phys_reg_width-1}:0];\n"
        verilog += f"            committed_rat[init_i] = init_i[{self.phys_reg_width-1}:0];\n"
        verilog += "        end\n"
        verilog += "    end\n\n"

        return verilog

    def _generate_free_list(self) -> str:
        """Generate free list storage and logic."""
        verilog = "    // Free List: FIFO of available physical registers\n"
        extra_regs = self.num_phys_regs - self.num_arch_regs

        verilog += f"    reg [{self.phys_reg_width-1}:0] free_list [0:{self.num_phys_regs-1}];\n"
        verilog += f"    reg [{self.phys_reg_width}:0] free_head;  // Points to next free register (advances at Decode)\n"
        verilog += f"    reg [{self.phys_reg_width}:0] free_tail;  // Points to next insertion point (advances at Writeback)\n"
        verilog += f"    reg [{self.phys_reg_width}:0] free_cnt;   // Number of free registers\n"
        verilog += "\n"
        verilog += "    // Committed free-list head: tracks how far free_head has advanced\n"
        verilog += "    // for committed instructions only; used for flush recovery\n"
        verilog += f"    reg [{self.phys_reg_width}:0] committed_free_head;\n"
        verilog += f"    reg [{self.phys_reg_width}:0] committed_free_cnt;\n"
        verilog += "\n"

        # Initialize free list with extra physical registers
        verilog += "    // Initialize free list with extra physical registers\n"
        verilog += "    integer fl_init_i;\n"
        verilog += "    initial begin\n"
        verilog += f"        free_head = 0;\n"
        verilog += f"        free_tail = {extra_regs};\n"
        verilog += f"        free_cnt = {extra_regs};\n"
        verilog += f"        committed_free_head = 0;\n"
        verilog += f"        committed_free_cnt = {extra_regs};\n"
        verilog += f"        for (fl_init_i = 0; fl_init_i < {extra_regs}; fl_init_i = fl_init_i + 1) begin\n"
        verilog += f"            free_list[fl_init_i] = {self.num_arch_regs} + fl_init_i;\n"
        verilog += "        end\n"
        verilog += "    end\n\n"

        verilog += "    assign free_list_empty = (free_cnt == 0);\n"
        verilog += "    assign free_count = free_cnt;\n\n"

        return verilog

    def _generate_lookup_logic(self) -> str:
        """Generate combinational lookup logic for read ports."""
        verilog = "    // Read port lookup logic (combinational, from speculative RAT)\n"

        for i in range(self.num_read_ports):
            # Architectural register 0 always maps to physical register 0 (x0 = 0 in RISC-V)
            verilog += f"    assign read_phys_{i} = (read_arch_{i} == 0) ? {self.phys_reg_width}'d0 : rename_table[read_arch_{i}];\n"

        verilog += "\n"
        return verilog

    def _generate_allocation_logic(self) -> str:
        """Generate allocation and commit logic with flush recovery."""
        verilog = "    // Allocation logic for destination registers (at Decode)\n"
        extra_regs = self.num_phys_regs - self.num_arch_regs

        for i in range(self.num_write_ports):
            # Each port reads from a distinct free list position (free_head + i)
            if i == 0:
                verilog += f"    wire [{self.phys_reg_width-1}:0] alloc_phys_{i} = free_list[free_head];\n"
            else:
                verilog += f"    wire [{self.phys_reg_width-1}:0] alloc_phys_{i} = free_list[(free_head + {i}) % {self.num_phys_regs}];\n"
            verilog += f"    assign write_phys_{i} = (write_arch_{i} == 0) ? {self.phys_reg_width}'d0 : alloc_phys_{i};\n"
            verilog += f"    assign write_old_phys_{i} = rename_table[write_arch_{i}];\n"

        verilog += "\n"

        for i in range(self.num_write_ports):
            verilog += f"    wire do_alloc_{i} = write_valid_{i} && write_arch_{i} != 0 && !free_list_empty;\n"
            verilog += f"    wire do_commit_{i} = commit_valid_{i} && commit_arch_{i} != 0;\n"

        verilog += "\n"

        # Main sequential logic
        verilog += "    // Sequential logic: allocation (Decode), commit (Writeback), flush recovery\n"
        verilog += "    always @(posedge clk) begin\n"
        verilog += "        if (reset) begin\n"
        verilog += "            // Reset both RATs to identity mapping\n"
        verilog += f"            for (init_i = 0; init_i < {self.num_arch_regs}; init_i = init_i + 1) begin\n"
        verilog += f"                rename_table[init_i] <= init_i[{self.phys_reg_width-1}:0];\n"
        verilog += f"                committed_rat[init_i] <= init_i[{self.phys_reg_width-1}:0];\n"
        verilog += "            end\n"
        verilog += "            // Reset free list\n"
        verilog += f"            free_head <= 0;\n"
        verilog += f"            free_tail <= {extra_regs};\n"
        verilog += f"            free_cnt <= {extra_regs};\n"
        verilog += f"            committed_free_head <= 0;\n"
        verilog += f"            committed_free_cnt <= {extra_regs};\n"
        verilog += f"            for (fl_init_i = 0; fl_init_i < {extra_regs}; fl_init_i = fl_init_i + 1) begin\n"
        verilog += f"                free_list[fl_init_i] <= {self.num_arch_regs} + fl_init_i;\n"
        verilog += "            end\n"

        verilog += "        end else if (flush) begin\n"
        verilog += "            // FLUSH: no allocation for the flushed Decode instruction.\n"
        verilog += "            // In an in-order pipeline with branch resolution at Execute,\n"
        verilog += "            // only the current Decode instruction is wrong-path, and the\n"
        verilog += "            // flush path already prevents its allocation. In-flight\n"
        verilog += "            // instructions at Execute/Memory/Writeback continue and will\n"
        verilog += "            // commit, so their speculative RAT entries and free-list\n"
        verilog += "            // consumption are valid. Do NOT restore free_head or RAT.\n"
        verilog += "\n"

        # Committed RAT update still applies for this cycle's WB commit
        verilog += "            // Committed RAT update (Writeback commit during flush cycle)\n"
        for i in range(self.num_write_ports):
            verilog += f"            if (do_commit_{i}) begin\n"
            verilog += f"                committed_rat[commit_arch_{i}] <= commit_phys_{i};\n"
            verilog += f"            end\n"

        # Aggregate commit count for single free list head/cnt update
        commit_sum = " + ".join(f"do_commit_{i}" for i in range(self.num_write_ports))
        verilog += f"            committed_free_head <= (committed_free_head + ({commit_sum})) % {self.num_phys_regs};\n"
        verilog += f"            committed_free_cnt <= committed_free_cnt - ({commit_sum}) + free_valid;\n"

        verilog += "            // Free port still operates during flush\n"
        verilog += "            if (free_valid) begin\n"
        verilog += "                free_list[free_tail] <= free_phys;\n"
        verilog += f"                free_tail <= (free_tail + 1) % {self.num_phys_regs};\n"
        verilog += "            end\n"
        verilog += "            // Update free count (free only, no allocation during flush)\n"
        verilog += "            free_cnt <= free_cnt + free_valid;\n"

        verilog += "        end else begin\n"
        verilog += "            // NORMAL OPERATION\n"

        # Speculative allocation at Decode
        verilog += "            // Speculative RAT update (Decode-stage allocation)\n"
        verilog += "            if (!stall) begin\n"
        for i in range(self.num_write_ports):
            verilog += f"                if (do_alloc_{i}) begin\n"
            verilog += f"                    rename_table[write_arch_{i}] <= alloc_phys_{i};\n"
            verilog += f"                end\n"
        # Aggregate allocation count for single free_head update
        alloc_sum = " + ".join(f"do_alloc_{i}" for i in range(self.num_write_ports))
        verilog += f"                free_head <= (free_head + ({alloc_sum})) % {self.num_phys_regs};\n"
        verilog += "            end\n"

        # Committed RAT update at Writeback
        verilog += "            // Committed RAT update (Writeback-stage commit)\n"
        for i in range(self.num_write_ports):
            verilog += f"            if (do_commit_{i}) begin\n"
            verilog += f"                committed_rat[commit_arch_{i}] <= commit_phys_{i};\n"
            verilog += f"            end\n"

        # Aggregate commit count for single committed free list head/cnt update
        commit_sum = " + ".join(f"do_commit_{i}" for i in range(self.num_write_ports))
        verilog += f"            committed_free_head <= (committed_free_head + ({commit_sum})) % {self.num_phys_regs};\n"
        verilog += f"            committed_free_cnt <= committed_free_cnt - ({commit_sum}) + free_valid;\n"

        # Free port
        verilog += "            // Free port: return old physical register to free list (at Writeback)\n"
        verilog += "            if (free_valid) begin\n"
        verilog += "                free_list[free_tail] <= free_phys;\n"
        verilog += f"                free_tail <= (free_tail + 1) % {self.num_phys_regs};\n"
        verilog += "            end\n"

        # Net free_cnt update (alloc at Decode, free at Writeback)
        alloc_cnt = " + ".join(f"(!stall && do_alloc_{i})" for i in range(self.num_write_ports))
        verilog += f"            // Net free count update (alloc at Decode, free at Writeback)\n"
        verilog += f"            free_cnt <= free_cnt - ({alloc_cnt}) + free_valid;\n"

        verilog += "        end\n"
        verilog += "    end\n\n"

        return verilog

    def get_port_connections(self,
                            read_archs: List[str],
                            read_valids: List[str],
                            read_phys: List[str],
                            write_archs: List[str],
                            write_valids: List[str],
                            write_phys: List[str],
                            write_old_phys: List[str],
                            commit_archs: List[str] = None,
                            commit_phys: List[str] = None,
                            commit_valids: List[str] = None,
                            free_phys: str = "0",
                            free_valid: str = "1'b0",
                            stall: str = "1'b0",
                            flush: str = "1'b0") -> str:
        """Generate instantiation with port connections."""
        if commit_archs is None:
            commit_archs = ["0"] * self.num_write_ports
        if commit_phys is None:
            commit_phys = ["0"] * self.num_write_ports
        if commit_valids is None:
            commit_valids = ["1'b0"] * self.num_write_ports

        connections = [
            "    .clk(clk)",
            "    .reset(reset)",
            f"    .stall({stall})",
            f"    .flush({flush})"
        ]

        for i in range(self.num_read_ports):
            connections.append(f"    .read_arch_{i}({read_archs[i]})")
            connections.append(f"    .read_valid_{i}({read_valids[i]})")
            connections.append(f"    .read_phys_{i}({read_phys[i]})")

        for i in range(self.num_write_ports):
            connections.append(f"    .write_arch_{i}({write_archs[i]})")
            connections.append(f"    .write_valid_{i}({write_valids[i]})")
            connections.append(f"    .write_phys_{i}({write_phys[i]})")
            connections.append(f"    .write_old_phys_{i}({write_old_phys[i]})")

        for i in range(self.num_write_ports):
            connections.append(f"    .commit_arch_{i}({commit_archs[i]})")
            connections.append(f"    .commit_phys_{i}({commit_phys[i]})")
            connections.append(f"    .commit_valid_{i}({commit_valids[i]})")

        connections.append(f"    .free_phys({free_phys})")
        connections.append(f"    .free_valid({free_valid})")
        connections.append("    .free_list_empty()")
        connections.append("    .free_count()")

        inst_name = f"{self.name}_inst"
        return f"{self.name} {inst_name}(\n" + ",\n".join(connections) + "\n);"


def create_module_generator_from_node(node_data: Dict):
    """
    Create appropriate module generator from node data.

    Useful for generating modules from ResourceGraph nodes.
    """
    node_type = node_data.get('type')

    if node_type == 'multiplexer':
        operation = node_data.get('operation', 'binary_select')
        if operation == 'one_hot_select':
            select_type = 'one_hot'
        elif operation == 'priority_select':
            select_type = 'priority'
        else:
            select_type = 'binary'

        return MuxGenerator(
            name=node_data.get('name', 'mux'),
            num_inputs=node_data.get('num_inputs', 2),
            # Check both data_width and bit_width for mux width
            data_width=node_data.get('data_width', node_data.get('bit_width', 32)),
            select_type=select_type,
            has_default=node_data.get('has_default', False)
        )

    elif node_type in ['uarch_counter', 'serialization_counter', 'memory_port_counter', 'memory_access_counter']:
        return CounterGenerator(
            name=node_data.get('name', 'counter'),
            width=node_data.get('width', node_data.get('bit_width', 32)),
            max_value=node_data.get('max_value', node_data.get('max_count')),
            has_enable=True,
            has_reset_value=True
        )

    elif node_type in ['hazard_detection_unit', 'hazard_detector']:
        return HazardDetectorGenerator(
            name=node_data.get('name', 'hazard_detector'),
            num_sources=node_data.get('num_sources', 2),
            num_destinations=node_data.get('num_destinations', 2),
            address_width=node_data.get('address_width', 5)
        )

    elif node_type == 'read_only_cache':
        return ReadOnlyCacheGenerator(
            name=node_data.get('name', 'cache'),
            num_read_ports=node_data.get('num_read_ports', 1),
            block_size=node_data.get('block_size', 32),
            associativity=node_data.get('associativity', 1),
            num_rows=node_data.get('num_rows', 64),
            address_width=node_data.get('address_width', 32),
            data_width=node_data.get('data_width', 32),
            replacement_policy=node_data.get('replacement_policy', 'lru'),
            has_flush=node_data.get('has_flush_input', False)
        )

    elif node_type == 'read_write_cache':
        return ReadWriteCacheGenerator(
            name=node_data.get('name', 'cache'),
            num_read_ports=node_data.get('num_read_ports', 1),
            num_write_ports=node_data.get('num_write_ports', 1),
            block_size=node_data.get('block_size', 32),
            associativity=node_data.get('associativity', 1),
            num_rows=node_data.get('num_rows', 64),
            address_width=node_data.get('address_width', 32),
            data_width=node_data.get('data_width', 32),
            replacement_policy=node_data.get('replacement_policy', 'lru'),
            write_allocate=node_data.get('write_allocate', False),
            write_read_fwd=node_data.get('write_read_fwd', False)
        )

    elif node_type == 'tlb_cache':
        return TLBModuleGenerator(
            name=node_data.get('name', 'tlb'),
            num_entries=node_data.get('num_entries', 64),
            associativity=node_data.get('associativity', 4),
            num_levels=node_data.get('num_levels', 2),
            vpn_widths=node_data.get('vpn_widths', [10, 10]),
            pte_width=node_data.get('pte_width', 32),
            replacement_policy=node_data.get('replacement_policy', 'lru'),
            has_flush=node_data.get('has_flush_input', True)
        )

    elif node_type == 'instruction_buffer':
        return InstructionBufferGenerator(
            name=node_data.get('name', 'ibuf'),
            fetch_width=node_data.get('fetch_width', 32),
            buffer_size=node_data.get('buffer_size', 4),
            address_width=node_data.get('address_width', 32),
            data_width=node_data.get('data_width', 32),
            has_flush=node_data.get('has_flush_input', False),
            output_offsets=node_data.get('output_offsets', [0])
        )

    elif node_type == 'btb_storage':
        return BranchTargetBufferGenerator(
            name=node_data.get('name', 'btb'),
            num_entries=node_data.get('num_entries', 64),
            associativity=node_data.get('associativity', 1),
            pc_width=node_data.get('pc_width', 32),
            target_width=node_data.get('target_width', 32),
            dual_port=node_data.get('dual_port', False)
        )

    elif node_type == 'renamer':
        return RegisterRenamerGenerator(
            name=node_data.get('name', 'renamer'),
            num_arch_regs=node_data.get('num_arch_regs', 32),
            num_phys_regs=node_data.get('num_physical_regs', 64),
            num_read_ports=node_data.get('num_reads', 2),
            num_write_ports=node_data.get('num_writes', 1),
            arch_reg_width=node_data.get('arch_reg_width', 5)
        )

    else:
        raise ValueError(f"Unknown module type: {node_type}")
