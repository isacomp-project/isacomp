"""
VHDL module generators for specialized hardware components.

This module provides classes to generate parameterized VHDL code for
common hardware components like multiplexers, counters, and hazard
detection units.
"""

import re
from typing import List, Dict, Optional
from dataclasses import dataclass


def sanitize_vhdl_identifier(name: str) -> str:
    """
    Sanitize a string to be a valid VHDL identifier.

    VHDL identifiers must:
    - Start with a letter
    - Contain only letters, digits, and underscores
    - Not have consecutive underscores
    - Not end with an underscore
    """
    # Replace brackets and special characters
    result = name.replace('[', '_').replace(']', '_')
    result = result.replace('{', '_').replace('}', '_')
    result = result.replace('(', '_').replace(')', '_')
    result = result.replace('+', 'plus').replace('-', 'minus')
    result = result.replace('*', 'mult').replace('/', 'div')
    result = result.replace(':', '_').replace('.', '_')
    result = result.replace('<', 'lt').replace('>', 'gt')
    result = result.replace('=', 'eq').replace('!', 'not')
    result = result.replace(',', '_').replace(' ', '_')
    result = result.replace("'", '_')

    # Replace any other non-alphanumeric characters
    result = re.sub(r'[^a-zA-Z0-9_]', '_', result)

    # Collapse multiple underscores
    result = re.sub(r'_+', '_', result)

    # Remove leading underscores
    result = result.lstrip('_')

    # Remove trailing underscores
    result = result.rstrip('_')

    # Ensure starts with a letter
    if result and not result[0].isalpha():
        result = 'n_' + result

    return result if result else 'unnamed'


@dataclass
class VHDLMuxGenerator:
    """Generate VHDL for multiplexer modules."""

    name: str
    num_inputs: int
    data_width: int = 32
    select_type: str = 'binary'  # 'binary', 'one_hot', or 'priority'
    has_default: bool = False  # For priority muxes with default value

    def generate_module(self) -> str:
        """Generate complete VHDL entity and architecture for the multiplexer."""
        if self.select_type == 'one_hot':
            return self._generate_one_hot_mux()
        elif self.select_type == 'priority':
            return self._generate_priority_mux()
        else:
            return self._generate_binary_mux()

    def _generate_binary_mux(self) -> str:
        """Generate binary-encoded multiplexer."""
        select_width = (self.num_inputs - 1).bit_length() if self.num_inputs > 1 else 1

        vhdl = "library IEEE;\n"
        vhdl += "use IEEE.std_logic_1164.all;\n"
        vhdl += "use IEEE.numeric_std.all;\n\n"

        # Entity declaration
        vhdl += f"entity {self.name} is\n"
        vhdl += "    port (\n"

        # Input ports
        for i in range(self.num_inputs):
            vhdl += f"        in_{i} : in std_logic_vector({self.data_width-1} downto 0);\n"

        # Select signal
        vhdl += f"        sel : in std_logic_vector({select_width-1} downto 0);\n"

        # Output port
        vhdl += f"        output : out std_logic_vector({self.data_width-1} downto 0)\n"
        vhdl += "    );\n"
        vhdl += f"end entity {self.name};\n\n"

        # Architecture
        vhdl += f"architecture rtl of {self.name} is\n"
        vhdl += "begin\n"

        # Build sensitivity list for VHDL-93 compatibility
        sensitivity_list = ["sel"] + [f"in_{i}" for i in range(self.num_inputs)]
        vhdl += f"    process({', '.join(sensitivity_list)})\n"
        vhdl += "    begin\n"
        vhdl += "        case sel is\n"

        for i in range(self.num_inputs):
            if select_width > 1:
                vhdl += f"            when \"{format(i, f'0{select_width}b')}\" =>\n"
            else:
                vhdl += f"            when \"{i}\" =>\n"
            vhdl += f"                output <= in_{i};\n"

        vhdl += f"            when others =>\n"
        vhdl += f"                output <= (others => '0');\n"
        vhdl += "        end case;\n"
        vhdl += "    end process;\n"
        vhdl += f"end architecture rtl;\n"

        return vhdl

    def _generate_one_hot_mux(self) -> str:
        """Generate one-hot encoded multiplexer."""
        vhdl = "library IEEE;\n"
        vhdl += "use IEEE.std_logic_1164.all;\n"
        vhdl += "use IEEE.numeric_std.all;\n\n"

        # Entity declaration
        vhdl += f"entity {self.name} is\n"
        vhdl += "    port (\n"

        # Input ports
        for i in range(self.num_inputs):
            vhdl += f"        in_{i} : in std_logic_vector({self.data_width-1} downto 0);\n"

        # One-hot select signals
        for i in range(self.num_inputs):
            vhdl += f"        sel_{i} : in std_logic;\n"

        # Output port
        vhdl += f"        output : out std_logic_vector({self.data_width-1} downto 0)\n"
        vhdl += "    );\n"
        vhdl += f"end entity {self.name};\n\n"

        # Architecture
        vhdl += f"architecture rtl of {self.name} is\n"
        vhdl += "begin\n"

        # Build sensitivity list for VHDL-93 compatibility
        sensitivity_list = [f"in_{i}" for i in range(self.num_inputs)] + [f"sel_{i}" for i in range(self.num_inputs)]
        vhdl += f"    process({', '.join(sensitivity_list)})\n"
        vhdl += f"        variable temp : std_logic_vector({self.data_width-1} downto 0);\n"
        vhdl += "    begin\n"
        vhdl += f"        temp := (others => '0');\n"

        # OR-based mux logic using if-then to accumulate
        for i in range(self.num_inputs):
            vhdl += f"        if sel_{i} = '1' then\n"
            vhdl += f"            temp := temp or in_{i};\n"
            vhdl += "        end if;\n"

        vhdl += "        output <= temp;\n"
        vhdl += "    end process;\n"
        vhdl += f"end architecture rtl;\n"

        return vhdl

    def _generate_priority_mux(self) -> str:
        """Generate priority-encoded multiplexer with optional default value."""
        vhdl = "library IEEE;\n"
        vhdl += "use IEEE.std_logic_1164.all;\n"
        vhdl += "use IEEE.numeric_std.all;\n\n"

        # Entity declaration
        vhdl += f"entity {self.name} is\n"
        vhdl += "    port (\n"

        # Input ports
        for i in range(self.num_inputs):
            vhdl += f"        in_{i} : in std_logic_vector({self.data_width-1} downto 0);\n"

        # Priority select signals
        for i in range(self.num_inputs):
            vhdl += f"        sel_{i} : in std_logic;\n"

        # Optional default input
        if self.has_default:
            vhdl += f"        default_in : in std_logic_vector({self.data_width-1} downto 0);\n"

        # Output port
        vhdl += f"        output : out std_logic_vector({self.data_width-1} downto 0)\n"
        vhdl += "    );\n"
        vhdl += f"end entity {self.name};\n\n"

        # Architecture
        vhdl += f"architecture rtl of {self.name} is\n"
        vhdl += "begin\n"

        # Build sensitivity list for VHDL-93 compatibility
        sensitivity_list = [f"in_{i}" for i in range(self.num_inputs)] + [f"sel_{i}" for i in range(self.num_inputs)]
        if self.has_default:
            sensitivity_list.append("default_in")
        vhdl += f"    process({', '.join(sensitivity_list)})\n"
        vhdl += "    begin\n"

        # Handle case with no inputs (only default)
        if self.num_inputs == 0:
            if self.has_default:
                vhdl += "        output <= default_in;\n"
            else:
                vhdl += f"        output <= (others => '0');\n"
        else:
            # Priority-based mux using if-elsif chain
            for i in range(self.num_inputs):
                if i == 0:
                    vhdl += f"        if sel_{i} = '1' then\n"
                else:
                    vhdl += f"        elsif sel_{i} = '1' then\n"
                vhdl += f"            output <= in_{i};\n"

            # Default case
            vhdl += "        else\n"
            if self.has_default:
                vhdl += "            output <= default_in;\n"
            else:
                vhdl += f"            output <= (others => '0');\n"
            vhdl += "        end if;\n"

        vhdl += "    end process;\n"
        vhdl += f"end architecture rtl;\n"

        return vhdl

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
            connections.append(f"        in_{i} => {sig}")

        if self.select_type in ['one_hot', 'priority']:
            # select_signal should be a list of individual select signals
            if isinstance(select_signal, list):
                for i, sel_sig in enumerate(select_signal):
                    connections.append(f"        sel_{i} => {sel_sig}")
            else:
                # Fallback: assume it's a vector signal
                for i in range(self.num_inputs):
                    connections.append(f"        sel_{i} => {select_signal}({i})")
        else:
            connections.append(f"        sel => {select_signal}")

        # Add default input port for priority muxes with default
        if self.select_type == 'priority' and self.has_default and default_signal:
            connections.append(f"        default_in => {default_signal}")

        connections.append(f"        output => {output_signal}")

        return f"{self.name}_inst : entity work.{self.name}\n    port map (\n" + ",\n".join(connections) + "\n    );"


@dataclass
class VHDLCounterGenerator:
    """Generate VHDL for counter modules."""

    name: str
    width: int = 32
    max_value: Optional[int] = None
    has_enable: bool = True
    has_reset_value: bool = True
    count_direction: str = 'up'  # 'up' or 'down'

    def generate_module(self) -> str:
        """Generate complete VHDL entity and architecture for the counter."""
        vhdl = "library IEEE;\n"
        vhdl += "use IEEE.std_logic_1164.all;\n"
        vhdl += "use IEEE.numeric_std.all;\n\n"

        # Entity declaration
        vhdl += f"entity {self.name} is\n"
        vhdl += "    port (\n"
        vhdl += "        clk : in std_logic;\n"
        vhdl += "        reset : in std_logic;\n"

        if self.has_reset_value:
            vhdl += f"        reset_value : in std_logic_vector({self.width-1} downto 0);\n"

        if self.has_enable:
            vhdl += "        enable : in std_logic;\n"

        vhdl += f"        count : out std_logic_vector({self.width-1} downto 0)\n"
        vhdl += "    );\n"
        vhdl += f"end entity {self.name};\n\n"

        # Architecture
        vhdl += f"architecture rtl of {self.name} is\n"
        vhdl += f"    signal count_reg : unsigned({self.width-1} downto 0);\n"
        vhdl += "begin\n"
        vhdl += "    count <= std_logic_vector(count_reg);\n\n"

        # Counter logic
        vhdl += "    process(clk)\n"
        vhdl += "    begin\n"
        vhdl += "        if rising_edge(clk) then\n"
        vhdl += "            if reset = '1' then\n"

        if self.has_reset_value:
            vhdl += "                count_reg <= unsigned(reset_value);\n"
        else:
            vhdl += f"                count_reg <= (others => '0');\n"

        if self.has_enable:
            vhdl += "            elsif enable = '1' then\n"
        else:
            vhdl += "            else\n"

        # Count operation
        if self.max_value is not None:
            if self.count_direction == 'up':
                vhdl += f"                if count_reg >= {self.max_value} then\n"
                vhdl += f"                    count_reg <= (others => '0');\n"
                vhdl += "                else\n"
                vhdl += "                    count_reg <= count_reg + 1;\n"
                vhdl += "                end if;\n"
            else:  # down
                vhdl += f"                if count_reg = 0 then\n"
                vhdl += f"                    count_reg <= to_unsigned({self.max_value}, {self.width});\n"
                vhdl += "                else\n"
                vhdl += "                    count_reg <= count_reg - 1;\n"
                vhdl += "                end if;\n"
        else:
            if self.count_direction == 'up':
                vhdl += "                count_reg <= count_reg + 1;\n"
            else:  # down
                vhdl += "                count_reg <= count_reg - 1;\n"

        vhdl += "            end if;\n"
        vhdl += "        end if;\n"
        vhdl += "    end process;\n"
        vhdl += f"end architecture rtl;\n"

        return vhdl

    def get_port_connections(self, enable_signal: Optional[str] = None,
                            reset_value_signal: Optional[str] = None,
                            output_signal: str = "count_out") -> str:
        """Generate instantiation with port connections."""
        connections = [
            "        clk => clk",
            "        reset => reset"
        ]

        if self.has_reset_value and reset_value_signal:
            connections.append(f"        reset_value => {reset_value_signal}")

        if self.has_enable and enable_signal:
            connections.append(f"        enable => {enable_signal}")

        connections.append(f"        count => {output_signal}")

        return f"{self.name}_inst : entity work.{self.name}\n    port map (\n" + ",\n".join(connections) + "\n    );"



@dataclass
class VHDLHazardDetectorGenerator:
    """Generate VHDL for pipeline hazard detection units."""

    name: str
    num_sources: int = 2
    num_destinations: int = 1
    address_width: int = 5  # Register file address width

    def generate_module(self) -> str:
        """Generate complete VHDL entity and architecture for hazard detection."""
        vhdl = "library IEEE;\n"
        vhdl += "use IEEE.std_logic_1164.all;\n"
        vhdl += "use IEEE.numeric_std.all;\n\n"

        # Entity declaration
        vhdl += f"entity {self.name} is\n"
        vhdl += "    port (\n"

        # Source register inputs (from decode stage)
        for i in range(self.num_sources):
            vhdl += f"        src_{i}_addr : in std_logic_vector({self.address_width-1} downto 0);\n"
            vhdl += f"        src_{i}_valid : in std_logic;\n"

        # Destination register inputs (from execute/memory/writeback stages)
        for i in range(self.num_destinations):
            vhdl += f"        dest_{i}_addr : in std_logic_vector({self.address_width-1} downto 0);\n"
            vhdl += f"        dest_{i}_valid : in std_logic;\n"
            vhdl += f"        dest_{i}_ready : in std_logic;\n"

        # Hazard detection outputs
        vhdl += "        stall : out std_logic;\n"
        vhdl += "        flush : out std_logic"

        # Forward control outputs
        for i in range(self.num_sources):
            vhdl += ";\n"
            vhdl += f"        forward_src_{i} : out std_logic_vector({self.num_destinations-1} downto 0)"

        vhdl += "\n    );\n"
        vhdl += f"end entity {self.name};\n\n"

        # Architecture
        vhdl += f"architecture rtl of {self.name} is\n"
        vhdl += "begin\n"

        # Build sensitivity list for VHDL-93 compatibility
        sensitivity_list = []
        for i in range(self.num_sources):
            sensitivity_list.extend([f"src_{i}_addr", f"src_{i}_valid"])
        for i in range(self.num_destinations):
            sensitivity_list.extend([f"dest_{i}_addr", f"dest_{i}_valid", f"dest_{i}_ready"])

        vhdl += f"    process({', '.join(sensitivity_list)})\n"
        vhdl += "    begin\n"
        vhdl += "        stall <= '0';\n"
        vhdl += "        flush <= '0';\n"

        for i in range(self.num_sources):
            vhdl += f"        forward_src_{i} <= (others => '0');\n"

        vhdl += "\n"

        # Check for hazards
        for src_idx in range(self.num_sources):
            vhdl += f"        -- Check source {src_idx} for hazards\n"
            vhdl += f"        if src_{src_idx}_valid = '1' then\n"

            for dest_idx in range(self.num_destinations):
                vhdl += f"            if dest_{dest_idx}_valid = '1' and " \
                       f"src_{src_idx}_addr = dest_{dest_idx}_addr then\n"
                vhdl += f"                if dest_{dest_idx}_ready = '1' then\n"
                vhdl += f"                    -- Forward from destination {dest_idx}\n"
                vhdl += f"                    forward_src_{src_idx}({dest_idx}) <= '1';\n"
                vhdl += "                else\n"
                vhdl += "                    -- Data not ready - stall pipeline\n"
                vhdl += "                    stall <= '1';\n"
                vhdl += "                end if;\n"
                vhdl += "            end if;\n"

            vhdl += "        end if;\n\n"

        vhdl += "    end process;\n"
        vhdl += f"end architecture rtl;\n"

        return vhdl

    def get_port_connections(self, src_addrs: List[str], src_valids: List[str],
                            dest_addrs: List[str], dest_valids: List[str],
                            dest_readys: List[str],
                            stall_signal: str = "stall",
                            flush_signal: str = "flush",
                            forward_signals: List[str] = None) -> str:
        """Generate instantiation with port connections."""
        connections = []

        for i, (addr, valid) in enumerate(zip(src_addrs, src_valids)):
            connections.append(f"        src_{i}_addr => {addr}")
            connections.append(f"        src_{i}_valid => {valid}")

        for i, (addr, valid, ready) in enumerate(zip(dest_addrs, dest_valids, dest_readys)):
            connections.append(f"        dest_{i}_addr => {addr}")
            connections.append(f"        dest_{i}_valid => {valid}")
            connections.append(f"        dest_{i}_ready => {ready}")

        connections.append(f"        stall => {stall_signal}")
        connections.append(f"        flush => {flush_signal}")

        if forward_signals:
            for i, sig in enumerate(forward_signals):
                connections.append(f"        forward_src_{i} => {sig}")

        return f"{self.name}_inst : entity work.{self.name}\n    port map (\n" + ",\n".join(connections) + "\n    );"


def generate_module_library() -> str:
    """Generate a complete VHDL file with all common module types."""
    vhdl = "-- Auto-generated VHDL module library\n"
    vhdl += "-- Contains: MUX, Counter, ALU, Hazard Detector\n\n"

    # Generate a 4-input mux
    mux4 = VHDLMuxGenerator(name="mux_4to1", num_inputs=4, data_width=32)
    vhdl += mux4.generate_module() + "\n"

    # Generate an 8-input mux
    mux8 = VHDLMuxGenerator(name="mux_8to1", num_inputs=8, data_width=32)
    vhdl += mux8.generate_module() + "\n"

    # Generate a counter
    counter = VHDLCounterGenerator(name="counter_32b", width=32)
    vhdl += counter.generate_module() + "\n"

    # Generate hazard detector
    hazard = VHDLHazardDetectorGenerator(name="hazard_detector", num_sources=2, num_destinations=2)
    vhdl += hazard.generate_module() + "\n"

    return vhdl


def create_module_generator_from_node(node_data: Dict):
    """
    Create appropriate module generator from node data.

    Useful for generating modules from ResourceGraph nodes.
    Names are automatically sanitized to be valid VHDL identifiers.
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

        return VHDLMuxGenerator(
            name=sanitize_vhdl_identifier(node_data.get('name', 'mux')),
            num_inputs=node_data.get('num_inputs', 2),
            data_width=node_data.get('data_width', node_data.get('bit_width', 32)),
            select_type=select_type,
            has_default=node_data.get('has_default', False)
        )

    elif node_type in ['uarch_counter', 'serialization_counter', 'memory_port_counter', 'memory_access_counter']:
        return VHDLCounterGenerator(
            name=sanitize_vhdl_identifier(node_data.get('name', 'counter')),
            width=node_data.get('width', node_data.get('bit_width', 32)),
            max_value=node_data.get('max_value', node_data.get('max_count')),
            has_enable=True,
            has_reset_value=True
        )

    elif node_type in ['hazard_detection_unit', 'hazard_detector']:
        return VHDLHazardDetectorGenerator(
            name=sanitize_vhdl_identifier(node_data.get('name', 'hazard_detector')),
            num_sources=node_data.get('num_sources', 2),
            num_destinations=node_data.get('num_destinations', 2),
            address_width=node_data.get('address_width', 5)
        )

    else:
        raise ValueError(f"Unknown module type: {node_type}")


if __name__ == "__main__":
    # Example usage
    print("=== Generating VHDL Module Library ===\n")
    library = generate_module_library()

    with open("vhdl_modules.vhd", "w") as f:
        f.write(library)

    print("Generated vhdl_modules.vhd")

    # Example of generating individual modules
    print("\n=== Example: 2-input MUX ===")
    mux2 = VHDLMuxGenerator(name="data_mux", num_inputs=2, data_width=32)
    print(mux2.generate_module())

    print("\n=== Example: One-hot MUX ===")
    mux_oh = VHDLMuxGenerator(name="onehot_mux", num_inputs=3, data_width=32, select_type='one_hot')
    print(mux_oh.generate_module())
