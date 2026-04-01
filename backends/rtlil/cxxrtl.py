"""
CXXRTL conversion utilities.

Uses Yosys to convert RTLIL to CXXRTL C++ simulation code, and provides
helpers for compiling and running CXXRTL simulations.
"""

import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict


def rtlil_to_cxxrtl(il_path: str, cc_path: str,
                    optimize: int = 3, debug: int = 4,
                    namespace: str = "cxxrtl_design") -> bool:
    """Convert an RTLIL .il file to CXXRTL C++ using Yosys.

    Args:
        il_path: Path to input .il file.
        cc_path: Path to output .cc file.
        optimize: CXXRTL optimization level (0-6, default 3).
            Levels 4+ remove public wires not marked (* keep *),
            which can strip signals needed for testbench access.
        debug: CXXRTL debug level (0-4, default 4).
        namespace: C++ namespace for generated code.

    Returns:
        True on success, raises RuntimeError on failure.
    """
    yosys = shutil.which("yosys")
    if not yosys:
        raise RuntimeError("yosys not found in PATH")

    # Use proc and memory_collect but skip opt to preserve
    # memories and state marked with (* keep *) attributes.
    # CXXRTL's own -O level handles optimization at the C++ level.
    script = (
        f"read_ilang {il_path}; "
        f"proc; memory_collect; "
        f"write_cxxrtl -O{optimize} -g{debug} -namespace {namespace} {cc_path}"
    )

    result = subprocess.run(
        [yosys, "-p", script],
        capture_output=True, text=True, timeout=120,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Yosys CXXRTL conversion failed:\n{result.stderr[-2000:]}"
        )

    return True


def rtlil_to_verilog(il_path: str, v_path: str) -> bool:
    """Convert an RTLIL .il file to Verilog using Yosys (for verification).

    Args:
        il_path: Path to input .il file.
        v_path: Path to output .v file.

    Returns:
        True on success, raises RuntimeError on failure.
    """
    yosys = shutil.which("yosys")
    if not yosys:
        raise RuntimeError("yosys not found in PATH")

    script = (
        f"read_ilang {il_path}; "
        f"proc; opt; memory_collect; "
        f"write_verilog {v_path}"
    )

    result = subprocess.run(
        [yosys, "-p", script],
        capture_output=True, text=True, timeout=120,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Yosys Verilog conversion failed:\n{result.stderr[-2000:]}"
        )

    return True


def find_cxxrtl_include() -> str:
    """Find the CXXRTL include directory for compilation.

    Returns:
        Path to the directory containing backends/cxxrtl/cxxrtl.h
    """
    # Try common locations
    candidates = [
        Path("/usr/share/yosys/include"),
        Path("/usr/local/share/yosys/include"),
    ]

    # Try yosys-config if available
    yosys_config = shutil.which("yosys-config")
    if yosys_config:
        try:
            result = subprocess.run(
                [yosys_config, "--datdir"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                datdir = Path(result.stdout.strip()) / "include"
                candidates.insert(0, datdir)
        except Exception:
            pass  # yosys-config not found or failed; fall through to other candidates

    for p in candidates:
        if (p / "backends" / "cxxrtl" / "cxxrtl.h").exists():
            return str(p)

    raise RuntimeError(
        "Cannot find CXXRTL headers. Install yosys-dev or set YOSYS_DATDIR."
    )


def compile_cxxrtl(cc_path: str, driver_path: str, output_path: str,
                   extra_flags: Optional[list] = None) -> bool:
    """Compile a CXXRTL design with a driver program.

    Args:
        cc_path: Path to generated CXXRTL .cc file.
        driver_path: Path to the C++ driver/testbench.
        output_path: Path for the compiled binary.
        extra_flags: Additional compiler flags.

    Returns:
        True on success, raises RuntimeError on failure.
    """
    include_dir = find_cxxrtl_include()

    cxx = shutil.which("g++") or shutil.which("clang++")
    if not cxx:
        raise RuntimeError("No C++ compiler found (need g++ or clang++)")

    flags = [
        cxx,
        "-std=c++14",
        "-O2",
        f"-I{include_dir}",
        f"-include", cc_path,
        driver_path,
        "-o", output_path,
    ]

    if extra_flags:
        flags.extend(extra_flags)

    result = subprocess.run(
        flags, capture_output=True, text=True, timeout=300,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"CXXRTL compilation failed:\n{result.stderr[-2000:]}"
        )

    return True
