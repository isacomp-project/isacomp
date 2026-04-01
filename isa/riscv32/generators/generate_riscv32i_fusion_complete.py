#!/usr/bin/env python3
"""
Generate complete RV32I processor with macro-op fusion optimizations.

This extends generate_riscv32i_complete.py by adding macro-op fusion candidates
from the Celio et al. paper "The Renewed Case for the Reduced Instruction Set
Computer: Avoiding ISA Bloat with Macro-Op Fusion for RISC-V" (2016).

Fusion candidates for RV32I:
  1. LUI + ADDI     — Load 32-bit immediate
  2. AUIPC + ADDI   — Load PC-relative address
  3. AUIPC + JALR   — Long PC-relative call/jump
  4. LUI + JALR     — Long absolute call/jump
  5. AUIPC + LW     — PC-relative global load (LW for RV32)
  6. AUIPC + SW     — PC-relative global store (SW for RV32)
  7. LUI + LW       — Absolute address load
  8. SLLI + ADD     — Load effective address / scaled index
  9. ADD + LW       — Register-indexed load
 10. SLT + BNE     — Compare-and-branch
 11. SLTI + BNE    — Compare-immediate-and-branch
 12. ADD + SW      — Post-compute indexed store

Note: SLLI+SRLI (zero-extend 32->64) is RV64-specific and excluded for RV32I.
Note: SLLI+ADD+LW (triple fusion) is excluded; the 2-op SLLI+ADD is included.

Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.
Supports --engine python (default) or --engine rust to use the Rust isacomp_core backend.
"""
import sys
import os
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

# Engine selection — set by main() before use.
_engine = 'python'

def _init_engine(engine):
    """Initialize the engine-specific imports."""
    global _engine, merge_instructions, MemoryAccessTransform, MemoryAccessTransformSpec
    global MemoryExternalizationSpec, apply_memory_externalization
    _engine = engine

    if engine == 'rust':
        try:
            import isacomp_core as _rc
        except ImportError:
            print("Error: isacomp_core not found. Build it with:")
            print("  cd rust_core && maturin develop")
            sys.exit(1)

        merge_instructions = _rc.merge_instructions

        class _RustMemoryAccessTransformSpec:
            def __init__(self, memory, strategy, current_width, target_width, direction='forward', **kwargs):
                self._inner = _rc.MemoryAccessTransformSpec(
                    memory, strategy, current_width, target_width, direction
                )
                self.memory = memory
                self.strategy = strategy
                self.current_width = current_width
                self.target_width = target_width
                self.direction = direction
                self.endianness = kwargs.get('endianness', 'little')
                self.alignment = kwargs.get('alignment', 'port_width')

        class _RustMemoryAccessTransform:
            def __init__(self, graph):
                self._graph = graph

            def apply_transformation(self, spec, dry_run=False):
                inner_spec = spec._inner if hasattr(spec, '_inner') else spec
                transform = _rc.MemoryAccessTransform(self._graph)
                result = transform.apply_transformation(inner_spec, dry_run)
                updated = transform.get_graph()
                result['graph'] = updated
                return result

        MemoryAccessTransformSpec = _RustMemoryAccessTransformSpec
        MemoryAccessTransform = _RustMemoryAccessTransform
        apply_memory_externalization = _rc.apply_memory_externalization

        _rc._VerilogGenerator = _rc.VerilogGenerator
        print(f"  Using Rust engine (isacomp_core)")
    else:
        from core.graph_merger import merge_instructions as _mi
        from opt.memory.memory_access_transform import MemoryAccessTransform as _mat, MemoryAccessTransformSpec as _mats
        from opt.memory.memory_externalization import MemoryExternalizationSpec as _mes, apply_memory_externalization as _ame

        merge_instructions = _mi
        MemoryAccessTransform = _mat
        MemoryAccessTransformSpec = _mats
        MemoryExternalizationSpec = _mes
        apply_memory_externalization = _ame

        print(f"  Using Python engine")

from backends.vhdl.test_generator import generate_vhdl_test_runner_tb, generate_vhdl_test_script

# Test list for RV32I
RV32I_TESTS = [
    "add", "addi", "and", "andi", "auipc", "beq", "bge", "bgeu", "blt", "bltu",
    "bne", "jal", "jalr", "lb", "lbu", "lh", "lhu", "lui", "lw", "or", "ori",
    "sb", "sh", "sll", "slli", "slt", "slti", "sltiu", "sltu", "sra", "srai",
    "srl", "srli", "sub", "sw", "xor", "xori"
]

# Complete RV32I instruction set (37 instructions total, excluding system/CSR)
INSTRUCTIONS = [
    # Arithmetic (5)
    'add', 'addi', 'sub', 'lui', 'auipc',

    # Logical (6)
    'and', 'andi', 'or', 'ori', 'xor', 'xori',

    # Shifts (6)
    'sll', 'slli', 'srl', 'srli', 'sra', 'srai',

    # Compare (4)
    'slt', 'slti', 'sltu', 'sltiu',

    # Branches (6)
    'beq', 'bne', 'blt', 'bltu', 'bge', 'bgeu',

    # Jumps (2)
    'jal', 'jalr',

    # Loads (5)
    'lw', 'lh', 'lhu', 'lb', 'lbu',

    # Stores (3)
    'sw', 'sh', 'sb',
]


# ============================================================================
# Fusion candidate definitions for RV32I
# ============================================================================

def get_fusion_candidates(isa_dir='isa/riscv32'):
    """Return the list of FusionCandidate specs for RV32I macro-op fusion.

    These are the instruction pairs from the Celio et al. whitepaper that
    are applicable to RV32I. Each candidate specifies:
      - The two instructions to fuse
      - Which register field in instr1 is the producer (written to rf)
      - Which register field in instr2 is the consumer (read from rf)
    The MacroOpFusion pass will automatically:
      - Forward the producer's value directly to the consumer (bypassing rf)
      - Enforce destructive destination (rd2 == rd1) when instr2 writes rf
      - Add decode eligibility assumptions
      - Eliminate instr1's intermediate rf and pc writes
    """
    from opt.macro_op_fusion import FusionCandidate

    candidates = [
        # 1. LUI + ADDI — Load 32-bit immediate
        #    lui rd, imm20; addi rd, rd, imm12
        FusionCandidate(
            name='lui_addi',
            instr1_name='lui',
            instr1_file=f'{isa_dir}/lui.isa',
            instr2_name='addi',
            instr2_file=f'{isa_dir}/addi.isa',
            producer_write='rd',
            consumer_read='rs1',
        ),

        # 2. AUIPC + ADDI — Load PC-relative address
        #    auipc rd, imm20; addi rd, rd, imm12
        FusionCandidate(
            name='auipc_addi',
            instr1_name='auipc',
            instr1_file=f'{isa_dir}/auipc.isa',
            instr2_name='addi',
            instr2_file=f'{isa_dir}/addi.isa',
            producer_write='rd',
            consumer_read='rs1',
        ),

        # 3. AUIPC + JALR — Long PC-relative call/jump
        #    auipc rd, imm20; jalr rd, rd, imm12
        #    Converts indirect jump to direct PC-relative jump
        FusionCandidate(
            name='auipc_jalr',
            instr1_name='auipc',
            instr1_file=f'{isa_dir}/auipc.isa',
            instr2_name='jalr',
            instr2_file=f'{isa_dir}/jalr.isa',
            producer_write='rd',
            consumer_read='rs1',
        ),

        # 4. LUI + JALR — Long absolute call/jump
        #    lui rd, imm20; jalr rd, rd, imm12
        FusionCandidate(
            name='lui_jalr',
            instr1_name='lui',
            instr1_file=f'{isa_dir}/lui.isa',
            instr2_name='jalr',
            instr2_file=f'{isa_dir}/jalr.isa',
            producer_write='rd',
            consumer_read='rs1',
        ),

        # 5. AUIPC + LW — PC-relative global load (LW for RV32)
        #    auipc rd, imm20; lw rd, imm12(rd)
        FusionCandidate(
            name='auipc_lw',
            instr1_name='auipc',
            instr1_file=f'{isa_dir}/auipc.isa',
            instr2_name='lw',
            instr2_file=f'{isa_dir}/lw.isa',
            producer_write='rd',
            consumer_read='rs1',
        ),

        # 6. AUIPC + SW — PC-relative global store (SW for RV32)
        #    auipc rt, imm20; sw rs2, imm12(rt)
        #    Note: store has no rd, so rt (auipc.rd) is dead after fusion
        FusionCandidate(
            name='auipc_sw',
            instr1_name='auipc',
            instr1_file=f'{isa_dir}/auipc.isa',
            instr2_name='sw',
            instr2_file=f'{isa_dir}/sw.isa',
            producer_write='rd',
            consumer_read='rs1',
        ),

        # 7. LUI + LW — Absolute address load
        #    lui rd, imm20; lw rd, imm12(rd)
        FusionCandidate(
            name='lui_lw',
            instr1_name='lui',
            instr1_file=f'{isa_dir}/lui.isa',
            instr2_name='lw',
            instr2_file=f'{isa_dir}/lw.isa',
            producer_write='rd',
            consumer_read='rs1',
        ),

        # 8. SLLI + ADD — Load effective address / scaled index
        #    slli rt, rs1, shamt; add rd, rt, rs2
        #    Highest impact: 4-6% on SPECInt2006
        FusionCandidate(
            name='slli_add',
            instr1_name='slli',
            instr1_file=f'{isa_dir}/slli.isa',
            instr2_name='add',
            instr2_file=f'{isa_dir}/add.isa',
            producer_write='rd',
            consumer_read='rs1',
        ),

        # 9. ADD + LW — Register-indexed load
        #    add rt, rs1, rs2; lw rd, 0(rt)
        FusionCandidate(
            name='add_lw',
            instr1_name='add',
            instr1_file=f'{isa_dir}/add.isa',
            instr2_name='lw',
            instr2_file=f'{isa_dir}/lw.isa',
            producer_write='rd',
            consumer_read='rs1',
        ),

        # 10. SLT + BNE — Compare-and-branch
        #     slt rt, rs1, rs2; bne rt, x0, offset
        #     Fuses to: branch if rs1 < rs2 (signed)
        FusionCandidate(
            name='slt_bne',
            instr1_name='slt',
            instr1_file=f'{isa_dir}/slt.isa',
            instr2_name='bne',
            instr2_file=f'{isa_dir}/bne.isa',
            producer_write='rd',
            consumer_read='rs1',
        ),

        # 11. SLTI + BNE — Compare-immediate-and-branch
        #     slti rt, rs1, imm12; bne rt, x0, offset
        #     Common in loop bound checks
        FusionCandidate(
            name='slti_bne',
            instr1_name='slti',
            instr1_file=f'{isa_dir}/slti.isa',
            instr2_name='bne',
            instr2_file=f'{isa_dir}/bne.isa',
            producer_write='rd',
            consumer_read='rs1',
        ),

        # 12. ADD + SW — Post-compute indexed store
        #     add rt, rs1, rs2; sw rv, 0(rt)
        #     rt is dead after the store (store doesn't write rf)
        FusionCandidate(
            name='add_sw',
            instr1_name='add',
            instr1_file=f'{isa_dir}/add.isa',
            instr2_name='sw',
            instr2_file=f'{isa_dir}/sw.isa',
            producer_write='rd',
            consumer_read='rs1',
        ),
    ]

    return candidates


# ============================================================================
# Import shared functions from generate_riscv32i_complete
# ============================================================================

# We import the backend generation functions from the base script.
# This avoids duplicating ~1000 lines of Verilog/VHDL/PyRTL/etc. generation code.
from generate_riscv32i_complete import (
    apply_memory_transform as _apply_memory_transform_base,
    generate_verilog,
    generate_externalized_memory_testbench,
    generate_vhdl,
    generate_pyrtl,
    generate_hardcaml,
    generate_chisel_output,
    generate_rtlil,
    generate_circt,
    generate_clash,
)


def apply_memory_transform(merged_graph):
    """Apply port width setting for word-addressed unified memory.

    Returns the (possibly new) graph object.
    """
    # Delegate to the base script's implementation
    return _apply_memory_transform_base(merged_graph)


def apply_fusion_pass(merged_graph, candidates, verbose=True):
    """Apply macro-op fusion to the merged graph.

    For each fusion candidate, the MacroOpFusion pass:
    1. Parses both instruction ISA files
    2. Composes the two graphs (prefix, forward, eliminate, adjust PC)
    3. Adds decode eligibility assumptions
    4. Produces a fused ResourceGraph

    The fused graphs are then merged into the existing merged_graph alongside
    the unfused instructions, so the processor can execute either the fused
    macro-op (when decode conditions are met) or fall back to single instructions.

    Returns:
        The merged graph (with fusion instructions added), and a list of
        FusionResult objects for reporting.
    """
    from opt.macro_op_fusion import MacroOpFusion, apply_macro_op_fusion

    if verbose:
        print(f"\n  Applying {len(candidates)} fusion candidates...")

    results = apply_macro_op_fusion(candidates)

    successful = [r for r in results if r.fused_graph is not None]
    failed = len(candidates) - len(successful)

    if verbose:
        print(f"\n  Fusion results: {len(successful)} succeeded, {failed} failed")
        for r in successful:
            print(f"    {r.candidate.name}: {len(r.fused_graph.nodes)} nodes, "
                  f"{len(r.fused_graph.edges)} edges, "
                  f"destructive={r.instr2_has_rd}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Generate complete RV32I processor with macro-op fusion from ISA definitions'
    )
    parser.add_argument(
        '--backend', '-b',
        choices=['verilog', 'vhdl', 'pyrtl', 'circt', 'clash', 'hardcaml', 'chisel', 'rtlil'],
        default='verilog',
        help='Output backend (default: verilog)'
    )
    parser.add_argument(
        '--no-verify',
        action='store_true',
        help='Skip GHDL compilation verification for VHDL backend'
    )
    parser.add_argument(
        '--output-dir', '-o',
        help='Output directory (default: <backend>/riscv32i_fusion_complete)'
    )
    parser.add_argument(
        '--externalize-memory',
        action='store_true',
        help='Externalize unified memory (umem) with valid-ready handshake ports'
    )
    parser.add_argument(
        '--engine', '-e',
        choices=['python', 'rust'],
        default='python',
        help='Backend engine: python (default) or rust (uses isacomp_core)'
    )
    parser.add_argument(
        '--no-fusion',
        action='store_true',
        help='Skip macro-op fusion (generate base RV32I only, for A/B comparison)'
    )
    parser.add_argument(
        '--fusions',
        nargs='*',
        default=None,
        help='Specific fusion names to include (default: all). '
             'Example: --fusions lui_addi auipc_jalr slli_add'
    )
    args = parser.parse_args()

    # Initialize engine-specific imports
    _init_engine(args.engine)

    # Also initialize the base script's engine (it uses module-level globals)
    import generate_riscv32i_complete as base_gen
    base_gen._init_engine(args.engine)

    module_name = 'riscv32i_fusion_complete'
    if args.output_dir:
        output_dir = args.output_dir
    elif args.backend == 'circt':
        output_dir = 'examples/verilog/circt_riscv32i_fusion'
    elif args.backend == 'pyrtl':
        output_dir = 'examples/pyrtl/riscv32i_fusion_complete'
    elif args.backend == 'clash':
        output_dir = 'examples/clash/riscv32i_fusion_complete'
    elif args.backend == 'hardcaml':
        output_dir = 'examples/hardcaml/riscv32i_fusion_complete'
    elif args.backend == 'chisel':
        output_dir = 'examples/chisel/riscv32i_fusion_complete'
    elif args.backend == 'rtlil':
        output_dir = 'examples/rtlil/riscv32i_fusion_complete'
    elif args.backend == 'verilog':
        output_dir = f'examples/verilog/riscv32i_fusion_complete'
    else:
        output_dir = f'{args.backend}/riscv32i_fusion_complete'

    fusion_label = "WITHOUT" if args.no_fusion else "WITH"

    print("=" * 70)
    print(f"RV32I Processor Generator {fusion_label} Macro-Op Fusion")
    print(f"  ({args.backend.upper()} backend, {args.engine} engine)")
    print("=" * 70)
    print(f"\nBase ISA: {len(INSTRUCTIONS)} RV32I instructions")
    print(f"Instructions: {', '.join(INSTRUCTIONS)}")

    # ========================================================================
    # Step 1: Build fused instruction graphs (if fusion enabled)
    # ========================================================================
    fusion_results = []
    fused_graphs = {}
    if not args.no_fusion:
        print("\n" + "=" * 70)
        print("Step 1: Building fused instruction graphs...")
        print("=" * 70)

        candidates = get_fusion_candidates()

        # Filter to specific fusions if --fusions was provided
        if args.fusions is not None:
            requested = set(args.fusions)
            candidates = [c for c in candidates if c.name in requested]
            skipped = requested - {c.name for c in candidates}
            if skipped:
                print(f"  WARNING: Unknown fusion names (skipped): {', '.join(skipped)}")
            print(f"  Selected {len(candidates)} fusion candidate(s): "
                  f"{', '.join(c.name for c in candidates)}")

        fusion_results = apply_fusion_pass(None, candidates)

        # Collect successful fused graphs and build fusion_pairs mapping
        fusion_pairs = {}
        for r in fusion_results:
            if r.fused_graph is not None:
                fused_graphs[r.candidate.name] = r.fused_graph
                fusion_pairs[r.candidate.name] = r.candidate.instr1_name

        successful = [r for r in fusion_results if r.fused_graph is not None]
        print(f"\n  Fusion summary:")
        print(f"    Candidates attempted: {len(candidates)}")
        print(f"    Successfully fused:   {len(successful)}")
        for r in successful:
            c = r.candidate
            dest_info = "destructive (rd2==rd1)" if r.instr2_has_rd else "dead rd (store/branch)"
            print(f"      {c.name}: {c.instr1_name}+{c.instr2_name} → {dest_info}")
    else:
        print("\n" + "=" * 70)
        print("Step 1: Macro-op fusion SKIPPED (--no-fusion)")
        print("=" * 70)

    # ========================================================================
    # Step 2: Parse and merge all instructions (base + fused)
    # ========================================================================
    print("\n" + "=" * 70)
    print("Step 2: Parsing and merging ISA files...")
    print("=" * 70)
    isa_files = {instr: f"isa/riscv32/{instr}.isa" for instr in INSTRUCTIONS}

    try:
        if fused_graphs:
            from opt.macro_op_fusion import merge_instructions_with_fusion
            print(f"  Merging {len(INSTRUCTIONS)} base instructions + "
                  f"{len(fused_graphs)} fused macro-ops...")
            merged_graph = merge_instructions_with_fusion(
                isa_files, fused_graphs=fused_graphs,
                fusion_pairs=fusion_pairs)
        else:
            merged_graph = merge_instructions(isa_files)
        print(f"  Merged graph: {len(merged_graph.nodes)} nodes, {len(merged_graph.edges)} edges")
    except Exception as e:
        print(f"  Error merging instructions: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # ========================================================================
    # Step 3: Apply memory transformations
    # ========================================================================
    print("\n" + "=" * 70)
    print("Step 3: Applying memory port width transformation...")
    print("=" * 70)
    merged_graph = apply_memory_transform(merged_graph)

    # Step 3b: Apply memory externalization if requested
    if args.externalize_memory:
        print("\n" + "=" * 70)
        print("Step 3b: Applying memory externalization...")
        print("=" * 70)

        spec = MemoryExternalizationSpec(
            memory_name='umem',
            create_read_port=True,
            create_write_port=True,
            variable_latency=True
        )
        if apply_memory_externalization(merged_graph, spec):
            print("  Memory externalization applied successfully")
            if not args.output_dir:
                output_dir = f'examples/verilog/riscv32i_fusion_complete_ext' if args.backend == 'verilog' else f'{args.backend}/riscv32i_fusion_complete_ext'
        else:
            print("  Warning: Memory externalization failed")

    # ========================================================================
    # Step 4: Generate RTL
    # ========================================================================
    print("\n" + "=" * 70)
    print(f"Step 4: Generating {args.backend.upper()} RTL and testbench...")
    print("=" * 70)
    print(f"  Output directory: {output_dir}")

    try:
        if args.backend == 'verilog':
            files = generate_verilog(merged_graph, module_name, output_dir)
        elif args.backend == 'vhdl':
            files = generate_vhdl(merged_graph, module_name, output_dir,
                                  verify=not args.no_verify)
        elif args.backend == 'pyrtl':
            files = generate_pyrtl(merged_graph, module_name, output_dir)
        elif args.backend == 'circt':
            files = generate_circt(merged_graph, module_name, output_dir)
        elif args.backend == 'clash':
            files = generate_clash(merged_graph, module_name, output_dir)
        elif args.backend == 'hardcaml':
            files = generate_hardcaml(merged_graph, module_name, output_dir)
        elif args.backend == 'chisel':
            files = generate_chisel_output(merged_graph, module_name, output_dir)
        elif args.backend == 'rtlil':
            files = generate_rtlil(merged_graph, module_name, output_dir)

        print(f"\n  Generated files:")
        for key, path in files.items():
            if hasattr(path, 'stat'):
                file_size = path.stat().st_size if path.exists() else 0
                print(f"    {key.upper()}: {path} ({file_size:,} bytes)")
            else:
                print(f"    {key.upper()}: {path}")

    except Exception as e:
        print(f"  Error generating {args.backend.upper()}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # ========================================================================
    # Summary
    # ========================================================================
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"  RV32I processor {fusion_label.lower()} macro-op fusion")
    print(f"  {len(INSTRUCTIONS)} base instructions")
    successful_fusions = [r for r in fusion_results if r.fused_graph is not None]
    if successful_fusions:
        print(f"  {len(successful_fusions)} fused macro-ops:")
        for r in successful_fusions:
            print(f"    - {r.candidate.name} ({r.candidate.instr1_name}+{r.candidate.instr2_name})")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Backend: {args.backend.upper()}")
    print(f"  Output: {output_dir}/")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
