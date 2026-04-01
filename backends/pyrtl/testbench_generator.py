"""
PyRTL Testbench Generator for ISAComp

This module generates PyRTL simulation testbenches for ISAComp-generated processors.
Generates complete Python files with design code at top and testbench at bottom.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
import pyrtl

from .code_emitter import emit_pyrtl_code


@dataclass
class PyRTLTestbenchConfig:
    """Configuration for PyRTL testbench generation."""
    module_name: str = "processor"
    clock_frequency_mhz: float = 100.0  # Clock frequency in MHz
    timeout_cycles: int = 10000

    # Memory configuration
    imem_size: int = 4096  # Number of words
    imem_width: int = 32   # Bits per word
    dmem_size: int = 4096
    dmem_width: int = 32

    # Register file
    rf_size: int = 32
    rf_width: int = 32

    # Architecture
    arch: str = 'riscv32'  # 'riscv32', 'riscv64', 'mips32'

    # Testbench options
    trace_filename: Optional[str] = "trace.vcd"
    print_debug: bool = True


class PyRTLTestbenchGenerator:
    """Generate PyRTL simulation testbenches."""

    def __init__(self, block: pyrtl.Block, config: PyRTLTestbenchConfig):
        """
        Initialize testbench generator.

        Args:
            block: The PyRTL block to simulate
            config: Testbench configuration
        """
        self.block = block
        self.config = config
        self.sim = None

        # Architecture-specific settings
        self.arch_config = self._get_arch_config()

    def _get_arch_config(self) -> Dict:
        """Get architecture-specific configuration."""
        configs = {
            'mips32': {
                'data_width': 32,
                'testnum_reg': 2,      # $2 ($v0) holds test number
                'test_dir': 'isa/mips32/mips-tests/isa',
                'test_prefix': 'mips32-isacomp-',
            },
            'riscv32': {
                'data_width': 32,
                'testnum_reg': 28,     # x28 holds test number
                'test_dir': 'isa/riscv32/riscv-tests/isa',
                'test_prefix': 'rv32ui-isacomp-',
            },
            'riscv64': {
                'data_width': 64,
                'testnum_reg': 28,     # x28 holds test number
                'test_dir': 'isa/riscv64/riscv-tests/isa',
                'test_prefix': 'rv64ui-isacomp-',
            },
        }
        return configs.get(self.config.arch, configs['riscv32'])

    def load_program(self, program_data: List[int], mem_name: str = 'imem'):
        """
        Load program data into instruction memory.

        Args:
            program_data: List of instruction words
            mem_name: Name of the instruction memory
        """
        if not self.sim:
            raise RuntimeError("Simulation not created yet. Call create_simulation() first.")

        # Find the memory block
        for mem in self.block.mem_set:
            if mem.name == mem_name:
                # Load program data into memory
                for addr, data in enumerate(program_data):
                    if addr < len(self.sim.inspect_mem(mem)):
                        self.sim.inspect_mem(mem)[addr] = data
                break

    def create_simulation(self, tracer: Optional[pyrtl.SimulationTrace] = None, use_fast_sim: bool = True) -> pyrtl.Simulation:
        """
        Create a PyRTL simulation for the design.

        Args:
            tracer: Optional simulation trace for waveform generation
            use_fast_sim: If True, use FastSimulation for better performance (default: True)

        Returns:
            PyRTL Simulation object (FastSimulation if use_fast_sim=True)
        """
        # Create simulation with the block - use FastSimulation for performance
        if use_fast_sim:
            self.sim = pyrtl.FastSimulation(tracer=tracer, block=self.block)
        else:
            self.sim = pyrtl.Simulation(tracer=tracer, block=self.block)
        return self.sim

    def run_simulation(self, num_cycles: Optional[int] = None,
                      stop_condition: Optional[callable] = None,
                      use_fast_sim: bool = True) -> pyrtl.SimulationTrace:
        """
        Run the simulation.

        Args:
            num_cycles: Number of cycles to simulate (default: use config timeout)
            stop_condition: Optional function(sim) that returns True to stop
            use_fast_sim: If True, use FastSimulation for better performance (default: True)

        Returns:
            SimulationTrace with results
        """
        if not self.sim:
            raise RuntimeError("Simulation not created. Call create_simulation() first.")

        if num_cycles is None:
            num_cycles = self.config.timeout_cycles

        # Create tracer if configured
        tracer = None
        if self.config.trace_filename:
            tracer = pyrtl.SimulationTrace()
            if use_fast_sim:
                self.sim = pyrtl.FastSimulation(tracer=tracer, block=self.block)
            else:
                self.sim = pyrtl.Simulation(tracer=tracer, block=self.block)

        # Run simulation
        cycle = 0
        while cycle < num_cycles:
            # Step simulation
            self.sim.step({})

            # Check stop condition
            if stop_condition and stop_condition(self.sim):
                if self.config.print_debug:
                    print(f"Simulation stopped at cycle {cycle} due to stop condition")
                break

            cycle += 1

        if cycle >= num_cycles:
            print(f"Simulation timeout after {num_cycles} cycles")

        # Save trace if configured
        if self.config.trace_filename and tracer:
            with open(self.config.trace_filename, 'w') as f:
                tracer.print_vcd(f)
            print(f"Waveform saved to {self.config.trace_filename}")

        return tracer

    def inspect_signal(self, signal_name: str):
        """
        Inspect the current value of a signal.

        Args:
            signal_name: Name of the signal to inspect

        Returns:
            Current value of the signal
        """
        if not self.sim:
            raise RuntimeError("Simulation not running")

        return self.sim.inspect(signal_name)

    def inspect_memory(self, mem_name: str) -> Dict[int, int]:
        """
        Inspect the contents of a memory.

        Args:
            mem_name: Name of the memory to inspect

        Returns:
            Dictionary mapping addresses to values
        """
        if not self.sim:
            raise RuntimeError("Simulation not running")

        # Find memory by name
        for mem in self.block.mem_set:
            if mem.name == mem_name:
                return self.sim.inspect_mem(mem)

        return {}

    def _detect_pipelined_signals(self) -> dict:
        """
        Detect if this is a pipelined design and find relevant signals.

        Returns:
            Dictionary with 'is_pipelined', 'exec_pc', 'exec_valid' keys
        """
        result = {'is_pipelined': False, 'exec_pc': None, 'exec_valid': None}

        # Check for pipelined design signals in the block's wire names
        wire_names = [w.name for w in self.block.wirevector_set]

        # Look for Execute stage validity signal
        # Handle combined stage names like PIPE_ExecuteMemoryWriteback_* for 2/3-stage pipelines
        for name in wire_names:
            if name.startswith('PIPE_Execute') and 'valid_PIPE' in name:
                result['exec_valid'] = name
                result['is_pipelined'] = True
                break

        # Look for Execute stage PC signal
        # Pattern: PIPE_Execute*_pc_rd_PIPE or PIPE_Execute*_PIPE_Decode_pc_rd_PIPE_PIPE
        for name in wire_names:
            if name.startswith('PIPE_Execute') and 'pc_rd' in name and '_PIPE' in name:
                result['exec_pc'] = name
                break

        return result

    def generate_testbench_code(self) -> str:
        """
        Generate Python testbench code as a string.

        Returns:
            Python source code for the testbench
        """
        cfg = self.arch_config
        width = cfg['data_width']

        # Detect if this is a pipelined design
        pipeline_info = self._detect_pipelined_signals()
        is_pipelined = pipeline_info['is_pipelined']
        exec_pc_signal = pipeline_info.get('exec_pc', 'PIPE_Execute_PIPE_Decode_pc_rd_PIPE_PIPE')
        exec_valid_signal = pipeline_info.get('exec_valid', 'PIPE_Execute_valid_PIPE')

        testbench = f'''

# ============================================================================
# Testbench Code
# ============================================================================

def load_hex_file(filename):
    """Load an Intel HEX file and return memory dictionary (addr -> word)."""
    memory = {{}}
    base_address = 0

    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith(':'):
                continue

            byte_count = int(line[1:3], 16)
            address = int(line[3:7], 16)
            record_type = int(line[7:9], 16)

            if record_type == 0:  # Data record
                for i in range(byte_count):
                    byte_val = int(line[9 + i*2:11 + i*2], 16)
                    memory[base_address + address + i] = byte_val
            elif record_type == 1:  # End of file
                break
            elif record_type == 2:  # Extended segment address
                base_address = int(line[9:13], 16) << 4
            elif record_type == 4:  # Extended linear address
                base_address = int(line[9:13], 16) << 16

    if not memory:
        return {{}}

    min_addr = min(memory.keys())
    max_addr = max(memory.keys())

    # Return raw bytes for flexible word assembly
    return memory


def assemble_words(byte_mem, word_size=4):
    """Assemble bytes into words of specified size (4 or 8 bytes)."""
    if not byte_mem:
        return {{}}

    min_addr = min(byte_mem.keys())
    max_addr = max(byte_mem.keys())

    words = {{}}
    for addr in range(min_addr, max_addr + 1, word_size):
        word = 0
        for i in range(word_size):
            if addr + i in byte_mem:
                word |= byte_mem[addr + i] << (i * 8)
        words[addr] = word

    return words


def run_test(byte_mem, max_cycles={self.config.timeout_cycles}, pass_addr=None, fail_addr=None, verbose=False):
    """
    Run a test program on the processor.

    Args:
        byte_mem: Dictionary mapping byte addresses to byte values (from load_hex_file)
        max_cycles: Maximum simulation cycles
        pass_addr: Address indicating test passed
        fail_addr: Address indicating test failed
        verbose: Enable verbose output

    Returns:
        Tuple of (success: bool, result_message: str)
    """
    # Create the design
    block = create_{self.config.module_name}()

    # Create simulation
    sim = pyrtl.FastSimulation(block=block)

    # Find memories
    imem = None
    dmem = None
    rf_mem = None
    for mem_name, mem in block.memblock_by_name.items():
        if 'imem' in mem_name.lower():
            imem = mem
        elif 'dmem' in mem_name.lower():
            dmem = mem
        elif 'rf' in mem_name.lower():
            rf_mem = mem

    # Load program into imem (always 32-bit words for instructions)
    # Memory is indexed by byte address (lower bits of PC)
    if imem:
        mem_dict = sim.inspect_mem(imem)
        imem_words = assemble_words(byte_mem, word_size=4)
        for addr, word in sorted(imem_words.items()):
            mem_dict[addr] = word
        if verbose:
            print(f"  Loaded {{len(imem_words)}} words into imem")

    # Load program into dmem (word size depends on architecture)
    # Memory is word-addressed: dmem[addr >> log2(word_bytes)]
    if dmem:
        mem_dict = sim.inspect_mem(dmem)
        dmem_word_bytes = dmem.bitwidth // 8  # 4 for 32-bit, 8 for 64-bit
        addr_shift = 3 if dmem_word_bytes == 8 else 2  # >> 3 for 64-bit, >> 2 for 32-bit
        dmem_words = assemble_words(byte_mem, word_size=dmem_word_bytes)
        for addr, word in sorted(dmem_words.items()):
            word_addr = addr >> addr_shift
            mem_dict[word_addr] = word
        if verbose:
            print(f"  Loaded {{len(dmem_words)}} words into dmem ({{dmem_word_bytes*8}}-bit, word-addressed)")

    if verbose:
        print(f"  Running simulation (max {{max_cycles}} cycles)...")

    last_pc = 0
    same_pc_count = 0

    # Check if this is a pipelined design by looking for Execute stage signals
    # Handle combined stage names like PIPE_ExecuteMemoryWriteback_* for 2/3-stage pipelines
    is_pipelined = False
    exec_pc_signal = None
    exec_valid_signal = None
    for wire in block.wirevector_set:
        # Match validity: PIPE_Execute*_valid_PIPE (handles Execute, ExecuteMemory, ExecuteMemoryWriteback, etc.)
        if wire.name.startswith('PIPE_Execute') and 'valid_PIPE' in wire.name:
            exec_valid_signal = wire.name
            is_pipelined = True
        # Match PC: PIPE_Execute*_pc_rd_PIPE or PIPE_Execute*_PIPE_Decode_pc_rd_PIPE_PIPE
        if wire.name.startswith('PIPE_Execute') and 'pc_rd' in wire.name and '_PIPE' in wire.name:
            exec_pc_signal = wire.name

    for cycle in range(max_cycles):
        sim.step({{}})

        try:
            pc = sim.inspect('pc')

            # For pipelined designs, check Execute stage PC with validity
            # This prevents false positives from speculatively fetched instructions
            if is_pipelined and exec_pc_signal and exec_valid_signal:
                try:
                    exec_pc = sim.inspect(exec_pc_signal)
                    exec_valid = sim.inspect(exec_valid_signal)
                    if exec_valid:
                        if pass_addr and exec_pc == pass_addr:
                            return True, f"PASS (reached pass address {{exec_pc:#x}})"
                        if fail_addr and exec_pc == fail_addr:
                            if rf_mem:
                                rf = sim.inspect_mem(rf_mem)
                                testnum = rf.get({cfg['testnum_reg']}, 0)
                                return False, f"FAIL at test {{testnum}} (PC={{exec_pc:#x}})"
                            return False, f"FAIL (reached fail address {{exec_pc:#x}})"
                except:
                    pass  # Fall back to Fetch PC if Execute signals not available
            else:
                # Non-pipelined: check Fetch PC directly
                if pass_addr and pc == pass_addr:
                    return True, f"PASS (reached pass address {{pc:#x}})"
                if fail_addr and pc == fail_addr:
                    if rf_mem:
                        rf = sim.inspect_mem(rf_mem)
                        testnum = rf.get({cfg['testnum_reg']}, 0)
                        return False, f"FAIL at test {{testnum}} (PC={{pc:#x}})"
                    return False, f"FAIL (reached fail address {{pc:#x}})"

            # Detect stuck PC
            if pc == last_pc:
                same_pc_count += 1
                if same_pc_count > 10:
                    break
            else:
                same_pc_count = 0
                last_pc = pc
        except:
            pass

    # Check final state
    final_pc = 0
    try:
        final_pc = sim.inspect('pc')
    except:
        pass

    # Check register file for pass indicator
    if rf_mem:
        rf = sim.inspect_mem(rf_mem)
        x31 = rf.get(31, 0)
        if x31 == 1:
            return True, f"PASS (x31=1, PC={{final_pc:#x}})"

    return False, f"TIMEOUT (final PC={{final_pc:#x}})"


def main():
    """Run tests from command line."""
    import sys
    import os
    import glob

    # Parse arguments
    if len(sys.argv) < 2:
        print("Usage: python {{sys.argv[0]}} <test.hex> [--max-cycles N] [--verbose]")
        print("       python {{sys.argv[0]}} --all [--max-cycles N] [--verbose]")
        return 1

    max_cycles = {self.config.timeout_cycles}
    verbose = '--verbose' in sys.argv or '-v' in sys.argv

    if '--max-cycles' in sys.argv:
        idx = sys.argv.index('--max-cycles')
        if idx + 1 < len(sys.argv):
            max_cycles = int(sys.argv[idx + 1])

    if sys.argv[1] == '--all':
        # Run all tests
        script_dir = os.path.dirname(os.path.abspath(__file__))
        test_dir = os.path.join(script_dir, '..', '..', '{cfg['test_dir']}')
        test_files = sorted(glob.glob(os.path.join(test_dir, '{cfg['test_prefix']}*.hex')))

        if not test_files:
            print(f"No test files found in {{test_dir}}")
            return 1

        print(f"Found {{len(test_files)}} tests")
        print()

        passed = 0
        failed = 0

        for test_file in test_files:
            test_name = os.path.basename(test_file).replace('{cfg['test_prefix']}', '').replace('.hex', '')

            program = load_hex_file(test_file)
            if not program:
                print(f"{{test_name}}: SKIP (empty)")
                continue

            # Load pass/fail addresses
            addr_file = test_file.replace('.hex', '.addrs')
            pass_addr = None
            fail_addr = None
            if os.path.exists(addr_file):
                with open(addr_file) as f:
                    parts = f.read().strip().split()
                    if len(parts) >= 2:
                        pass_addr = int(parts[0], 16)
                        fail_addr = int(parts[1], 16)

            # Reset PyRTL for each test
            pyrtl.reset_working_block()

            try:
                success, result = run_test(program, max_cycles, pass_addr, fail_addr, verbose)
                if success:
                    print(f"{{test_name}}: PASS")
                    passed += 1
                else:
                    print(f"{{test_name}}: FAIL - {{result}}")
                    failed += 1
            except Exception as e:
                print(f"{{test_name}}: ERROR - {{e}}")
                failed += 1

        print()
        print("=" * 60)
        print(f"Results: {{passed}}/{{passed+failed}} tests passed")
        print("=" * 60)

        return 0 if failed == 0 else 1

    else:
        # Run single test
        test_file = sys.argv[1]
        program = load_hex_file(test_file)

        if not program:
            print(f"Error: Could not load program from {{test_file}}")
            return 1

        # Load pass/fail addresses
        addr_file = test_file.replace('.hex', '.addrs')
        pass_addr = None
        fail_addr = None
        if os.path.exists(addr_file):
            with open(addr_file) as f:
                parts = f.read().strip().split()
                if len(parts) >= 2:
                    pass_addr = int(parts[0], 16)
                    fail_addr = int(parts[1], 16)

        success, result = run_test(program, max_cycles, pass_addr, fail_addr, verbose)
        print(f"Result: {{result}}")
        return 0 if success else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
'''
        return testbench

    def generate_complete_file(self) -> str:
        """
        Generate complete Python file with design code at top and testbench at bottom.

        Returns:
            Complete Python source code
        """
        # Generate design code using the code emitter
        design_code = emit_pyrtl_code(self.block, self.config.module_name)

        # Generate testbench code
        testbench_code = self.generate_testbench_code()

        # Combine them
        return design_code + testbench_code

    def generate_test_runner(self, instructions: list) -> str:
        """Generate bash test runner script."""
        cfg = self.arch_config
        tests_str = ' '.join(instructions)

        script = f"""#!/bin/bash

# Test all {self.config.arch.upper()} instructions using PyRTL
# This uses the ISAComp-generated processor

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/../../.."
TEST_DIR="$REPO_ROOT/{cfg['test_dir']}"

# Check if testbench exists
if [ ! -f "$SCRIPT_DIR/{self.config.module_name}_tb.py" ]; then
    echo "ERROR: Testbench not found at $SCRIPT_DIR/{self.config.module_name}_tb.py"
    echo "Run the appropriate generator with --backend pyrtl"
    exit 1
fi

# Activate virtual environment if available
if [ -f "$REPO_ROOT/venv/bin/activate" ]; then
    source "$REPO_ROOT/venv/bin/activate"
fi

echo "Running PyRTL tests..."
cd "$SCRIPT_DIR"

TESTS="{tests_str}"

PASS=0
FAIL=0
SKIP=0

for test in $TESTS; do
    echo -n "Testing $test... "

    HEX_FILE="$TEST_DIR/{cfg['test_prefix']}$test.hex"
    ADDR_FILE="$TEST_DIR/{cfg['test_prefix']}$test.addrs"

    if [ ! -f "$HEX_FILE" ]; then
        echo "SKIP (no hex file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    if [ ! -f "$ADDR_FILE" ]; then
        echo "SKIP (no addr file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    # Run test using the Python testbench
    RESULT=$(timeout 60 python3 {self.config.module_name}_tb.py "$HEX_FILE" 2>&1)
    EXIT_CODE=$?

    if echo "$RESULT" | grep -q "PASS"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif [ $EXIT_CODE -eq 124 ]; then
        echo "TIMEOUT"
        FAIL=$((FAIL + 1))
    else
        echo "FAIL"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
echo "================================"

# Exit with error if any tests failed or no tests passed
if [ $FAIL -gt 0 ]; then
    echo "FAILED: $FAIL test(s) failed"
    exit 1
fi

if [ $PASS -eq 0 ]; then
    echo "FAILED: No tests passed (all skipped)"
    exit 1
fi

echo "SUCCESS: All $PASS tests passed"
exit 0
"""
        return script

    def write_files(self, output_dir: Path, instructions: list) -> Dict[str, str]:
        """
        Write testbench and test runner files.

        Args:
            output_dir: Directory to write files to
            instructions: List of instruction names for the test runner

        Returns:
            Dictionary of generated file paths
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        files = {}

        # Write complete testbench file (design + testbench)
        tb_file = output_dir / f"{self.config.module_name}_tb.py"
        tb_content = self.generate_complete_file()
        with open(tb_file, 'w') as f:
            f.write(tb_content)
        tb_file.chmod(0o755)
        files['testbench'] = str(tb_file)

        # Write test runner
        runner_file = output_dir / 'run_all_tests.sh'
        runner_content = self.generate_test_runner(instructions)
        with open(runner_file, 'w') as f:
            f.write(runner_content)
        runner_file.chmod(0o755)
        files['test_runner'] = str(runner_file)

        return files


def generate_pyrtl_testbench(block: pyrtl.Block,
                             config: Optional[PyRTLTestbenchConfig] = None,
                             program_data: Optional[List[int]] = None) -> PyRTLTestbenchGenerator:
    """
    Generate a PyRTL testbench for the given block.

    Args:
        block: PyRTL block to simulate
        config: Optional testbench configuration
        program_data: Optional program data to load into instruction memory

    Returns:
        PyRTLTestbenchGenerator configured and ready to simulate
    """
    if config is None:
        config = PyRTLTestbenchConfig()

    tb = PyRTLTestbenchGenerator(block, config)
    tb.create_simulation()

    # Load program if provided
    if program_data:
        tb.load_program(program_data)

    return tb


def generate_pyrtl_testbench_files(block: pyrtl.Block,
                                   module_name: str,
                                   output_dir: Path,
                                   config: Optional[PyRTLTestbenchConfig] = None,
                                   instructions: Optional[List[str]] = None,
                                   arch: str = 'riscv32') -> Dict[str, Path]:
    """
    Generate PyRTL design and testbench Python files.

    Args:
        block: PyRTL block containing the design
        module_name: Name of the module
        output_dir: Directory to write output files
        config: Optional testbench configuration
        instructions: List of instruction names for the test runner
        arch: Architecture type ('riscv32', 'riscv64', 'mips32')

    Returns:
        Dictionary with paths to generated files
    """
    if config is None:
        config = PyRTLTestbenchConfig(module_name=module_name, arch=arch)

    tb_gen = PyRTLTestbenchGenerator(block, config)

    if instructions is None:
        instructions = []

    return tb_gen.write_files(output_dir, instructions)
