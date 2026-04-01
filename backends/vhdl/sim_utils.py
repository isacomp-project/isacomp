"""
VHDL simulation utilities for ISAComp.

Provides helper functions for compiling and running VHDL simulations with GHDL.
"""

from pathlib import Path
from typing import Optional, List, Tuple
import subprocess


def compile_vhdl(vhdl_files: List[Path],
                 work_dir: Optional[Path] = None,
                 std: str = "08") -> Tuple[bool, str]:
    """
    Compile VHDL files with GHDL.

    Args:
        vhdl_files: List of VHDL files to compile
        work_dir: Working directory for compilation (default: current)
        std: VHDL standard (default: "08" for VHDL-2008)

    Returns:
        (success, error_message)
    """
    if work_dir:
        work_dir.mkdir(parents=True, exist_ok=True)

    for vhdl_file in vhdl_files:
        cmd = ['ghdl', '-a', f'--std={std}', str(vhdl_file)]
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return False, f"Compilation failed for {vhdl_file.name}:\n{result.stderr}"

    return True, ""


def elaborate_vhdl(entity_name: str,
                   work_dir: Optional[Path] = None,
                   std: str = "08") -> Tuple[bool, str]:
    """
    Elaborate VHDL entity with GHDL.

    Args:
        entity_name: Top-level entity name
        work_dir: Working directory (default: current)
        std: VHDL standard (default: "08" for VHDL-2008)

    Returns:
        (success, error_message)
    """
    cmd = ['ghdl', '-e', f'--std={std}', entity_name]
    result = subprocess.run(
        cmd,
        cwd=work_dir,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        return False, f"Elaboration failed:\n{result.stderr}"

    return True, ""


def run_vhdl_simulation(entity_name: str,
                        work_dir: Optional[Path] = None,
                        std: str = "08",
                        stop_time: Optional[str] = None,
                        vcd_file: Optional[Path] = None,
                        wave_opt_file: Optional[Path] = None) -> Tuple[bool, str, str]:
    """
    Run VHDL simulation with GHDL.

    Args:
        entity_name: Top-level entity name
        work_dir: Working directory (default: current)
        std: VHDL standard (default: "08" for VHDL-2008)
        stop_time: Simulation stop time (e.g., "10us", "1ms")
        vcd_file: Path to VCD output file (enables waveform generation)
        wave_opt_file: Path to wave options file for GHW format

    Returns:
        (success, stdout, stderr)
    """
    cmd = ['ghdl', '-r', f'--std={std}', entity_name]

    if stop_time:
        cmd.append(f'--stop-time={stop_time}')

    if vcd_file:
        cmd.append(f'--vcd={vcd_file}')

    if wave_opt_file:
        cmd.append(f'--wave={wave_opt_file}')

    result = subprocess.run(
        cmd,
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=60  # 60 second timeout
    )

    success = result.returncode == 0
    return success, result.stdout, result.stderr


def compile_elaborate_and_run(vhdl_files: List[Path],
                               entity_name: str,
                               work_dir: Optional[Path] = None,
                               std: str = "08",
                               stop_time: Optional[str] = None,
                               vcd_file: Optional[Path] = None) -> Tuple[bool, str]:
    """
    Compile, elaborate, and run VHDL simulation in one step.

    Args:
        vhdl_files: List of VHDL files to compile
        entity_name: Top-level entity name
        work_dir: Working directory (default: current)
        std: VHDL standard (default: "08" for VHDL-2008)
        stop_time: Simulation stop time (e.g., "10us", "1ms")
        vcd_file: Path to VCD output file (enables waveform generation)

    Returns:
        (success, message)
    """
    # Compile
    success, error = compile_vhdl(vhdl_files, work_dir, std)
    if not success:
        return False, error

    # Elaborate
    success, error = elaborate_vhdl(entity_name, work_dir, std)
    if not success:
        return False, error

    # Run
    success, stdout, stderr = run_vhdl_simulation(
        entity_name, work_dir, std, stop_time, vcd_file
    )

    if not success:
        return False, f"Simulation failed:\n{stderr}"

    return True, stdout + "\n" + stderr
