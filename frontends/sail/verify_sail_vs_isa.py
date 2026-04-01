#!/usr/bin/env python3
"""Verify SAIL instruction patterns against .isa files using SMT."""

import sys
import argparse
from pathlib import Path
# Add isacomp3 root to path (frontends/sail -> root is 2 levels up)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.resource_graph import ResourceGraph
from verif.smt.smt_verification import verify_optimization
from frontends.sail.ocaml_sail_extractor.sail_loader import SAILInstructionLoader
import json

def verify_instruction(sail_pattern, isa_file, solver='z3', regenerate_json=False, json_path=None):
    """Verify SAIL pattern against .isa file.

    Args:
        sail_pattern: SAIL pattern name (e.g., 'RTYPE', 'ITYPE')
        isa_file: Path to .isa file
        solver: SMT solver to use ('z3' or 'cvc5')
        regenerate_json: If True, force re-extraction from SAIL (ignore cache)
        json_path: Path to SAIL JSON cache (defaults to /tmp/riscv_instructions.json)

    Returns:
        bool: True if verification passed, False otherwise
    """
    print(f"\n{'='*60}")
    print(f"Verifying: {sail_pattern} vs {isa_file} (solver: {solver})")
    if regenerate_json:
        print(f"  JSON regeneration: FORCED (cache will be ignored)")
    else:
        print(f"  JSON regeneration: CACHED (reuse existing if available)")
    print(f"{'='*60}\n")

    # Load SAIL pattern
    loader = SAILInstructionLoader()
    print(f"Loading SAIL pattern: {sail_pattern}...")

    # Extract SAIL instructions with control over caching
    # If regenerate_json=True, this will re-extract from SAIL even if cache exists
    # If regenerate_json=False (default), this will use cache if available
    try:
        if regenerate_json:
            # Force rebuild - ignore cache and re-extract from SAIL
            loader.extract_all_instructions(output_path=json_path, force_rebuild=True)

        # Load the pattern (will use cache from above extraction or existing cache)
        sail_graph = loader.load_instruction_pattern(sail_pattern, cache_path=json_path)
        print(f"  Loaded: {len(sail_graph.nodes)} nodes, {len(sail_graph.edges)} edges")
    except Exception as e:
        print(f"  ERROR loading SAIL: {e}")
        return False

    # Load .isa file
    print(f"\nLoading .isa file: {isa_file}...")
    try:
        isa_graph = ResourceGraph.from_isa_file(isa_file)
        print(f"  Loaded: {len(isa_graph.nodes)} nodes, {len(isa_graph.edges)} edges")
    except Exception as e:
        print(f"  ERROR loading .isa: {e}")
        return False

    # Run verification
    print(f"\nGenerating SMT formulas and verifying...")
    try:
        is_equivalent, output = verify_optimization(sail_graph, isa_graph, isa_file_path=isa_file, solver=solver)

        print(f"\n{'='*60}")
        if is_equivalent:
            print(f"✅ VERIFICATION PASSED: Graphs are equivalent!")
        else:
            print(f"❌ VERIFICATION FAILED: Graphs are NOT equivalent")
        print(f"{'='*60}\n")

        print("Solver output:")
        print(output[:500] if len(output) > 500 else output)

        return is_equivalent

    except Exception as e:
        print(f"\n❌ VERIFICATION ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Verify SAIL instruction patterns against .isa files using SMT',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use cached SAIL extraction (fast)
  %(prog)s RTYPE riscv32/add.isa

  # Force fresh SAIL extraction
  %(prog)s RTYPE riscv32/add.isa --regenerate-json

  # Use a custom JSON cache path
  %(prog)s RTYPE riscv32/add.isa --json-path /tmp/my_sail.json

  # Use cvc5 instead of z3
  %(prog)s RTYPE riscv32/add.isa --solver cvc5
        """
    )

    parser.add_argument(
        'sail_pattern',
        help='SAIL pattern name (e.g., RTYPE, ITYPE, BTYPE, LOAD, STORE, JAL, JALR)'
    )
    parser.add_argument(
        'isa_file',
        help='Path to .isa file to verify against'
    )
    parser.add_argument(
        '--solver',
        choices=['z3', 'cvc5'],
        default='z3',
        help='SMT solver to use (default: z3)'
    )
    parser.add_argument(
        '--regenerate-json', '--force-rebuild', '--no-cache',
        action='store_true',
        dest='regenerate_json',
        help='Force re-extraction from SAIL, ignoring any cached JSON. '
             'Useful for testing if non-determinism is caused by stale cache.'
    )
    parser.add_argument(
        '--json-path',
        default=None,
        help='Path to SAIL JSON cache file (default: /tmp/riscv_instructions.json)'
    )

    args = parser.parse_args()

    success = verify_instruction(
        args.sail_pattern,
        args.isa_file,
        solver=args.solver,
        regenerate_json=args.regenerate_json,
        json_path=args.json_path
    )
    sys.exit(0 if success else 1)
