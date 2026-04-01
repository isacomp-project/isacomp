"""
Clash Testbench Infrastructure for ISAComp

Copies the canonical gen_tb.py and run_all_tests.sh to the output directory.
gen_tb.py parses Clash-generated Verilog to auto-detect state register layout,
pipeline signals, and module name - no substitution needed.
"""

import os
import shutil
from pathlib import Path
from typing import Dict, Optional


_BACKEND_DIR = Path(__file__).parent


def copy_test_infrastructure(output_dir: str) -> Dict[str, str]:
    """Copy gen_tb.py and run_all_tests.sh to the output directory.

    These scripts auto-detect everything from the generated Verilog,
    so no module-name substitution is needed (unlike hardcaml).

    Args:
        output_dir: Directory to copy files into

    Returns:
        Dictionary mapping file type to path
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    files = {}
    for name in ['gen_tb.py', 'run_all_tests.sh']:
        src = _BACKEND_DIR / name
        dst = output_path / name
        if src.exists():
            shutil.copy2(src, dst)
            os.chmod(dst, 0o755)
            files[name] = str(dst)

    return files


# Keep backwards-compatible alias used by generate_riscv32i_complete.py
def generate_clash_testbench(
    clash_file: str,
    module_name: str,
    arch: str,
    instructions,
    output_dir: Optional[str] = None
) -> Dict[str, str]:
    """Copy test infrastructure to the output directory.

    Args are kept for API compatibility but gen_tb.py auto-detects
    everything from the Verilog file at runtime.
    """
    if output_dir is None:
        output_dir = str(Path(clash_file).parent)

    return copy_test_infrastructure(output_dir)
