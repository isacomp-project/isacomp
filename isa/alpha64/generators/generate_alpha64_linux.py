#!/usr/bin/env python3
"""
Generate Linux-capable Alpha64 processor with:
- All user-mode integer instructions with virtual memory (ITB/DTB)
- PALcode/privileged instructions
- IEEE floating-point support

This processor includes all components needed to boot Linux:
- User-mode instructions with ITB/DTB translation (8-entry TLBs)
- Privileged PAL instructions for system calls and exception handling
- Full floating-point support (single and double precision)
- TLB miss exception handling (traps to PALcode)

Supports Verilog backend.
"""
import sys
import os
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
from opt.memory.memory_externalization import apply_memory_externalization, MemoryExternalizationSpec
from backends.verilog import VerilogGenerator

# Alpha64 base user-mode instructions (without VM translation)
# These work with physical addresses - VM support to be added later
ALPHA_USER_INSTRUCTIONS = [
    # Arithmetic (16)
    'addl', 'addq', 'subl', 'subq', 'mull', 'mulq', 'umulh',
    's4addl', 's4addq', 's4subl', 's4subq',
    's8addl', 's8addq', 's8subl', 's8subq',

    # Logical (7)
    'and', 'bis', 'xor', 'bic', 'ornot', 'eqv',
    'amask',

    # Shifts (3)
    'sll', 'srl', 'sra',

    # Sign extension (2)
    'sextb', 'sextw',

    # Comparisons (6)
    'cmpeq', 'cmplt', 'cmple', 'cmpult', 'cmpule', 'cmpbge',

    # Conditional moves (8)
    'cmoveq', 'cmovne', 'cmovlt', 'cmovle', 'cmovgt', 'cmovge',
    'cmovlbs', 'cmovlbc',

    # Branches (8)
    'beq', 'bne', 'blt', 'ble', 'bgt', 'bge', 'blbs', 'blbc',

    # Jumps (6)
    'br', 'bsr', 'jmp', 'jsr', 'jsr_coroutine', 'ret',

    # Load address (2)
    'lda', 'ldah',

    # Loads (7)
    'ldl', 'ldq', 'ldq_u', 'ldbu', 'ldwu', 'ldl_l', 'ldq_l',

    # Stores (7)
    'stl', 'stq', 'stq_u', 'stb', 'stw', 'stl_c', 'stq_c',

    # Byte manipulation - extract (7)
    'extbl', 'extwl', 'extll', 'extql', 'extwh', 'extlh', 'extqh',

    # Byte manipulation - insert (7)
    'insbl', 'inswl', 'insll', 'insql', 'inswh', 'inslh', 'insqh',

    # Byte manipulation - mask (7)
    'mskbl', 'mskwl', 'mskll', 'mskql', 'mskwh', 'msklh', 'mskqh',

    # Byte manipulation - zap (2)
    'zap', 'zapnot',

    # Byte manipulation - other (4)
    'unpkbl', 'unpkbw', 'pklb', 'pkwb',

    # Count/population (3)
    'ctpop', 'ctlz', 'cttz',

    # Min/Max (8)
    'minsb8', 'minsw4', 'minub8', 'minuw4',
    'maxsb8', 'maxsw4', 'maxub8', 'maxuw4',

    # Permute (1)
    'perr',

    # Memory barriers (4)
    'mb', 'wmb', 'trapb', 'excb',

    # Misc system (2)
    'implver', 'rpcc',

    # Fault handler (fires on ITB miss/ACV when no instruction decodes)
    'itb_fault_handler',
]

# PALcode/privileged instructions (only valid in PAL mode)
ALPHA_PAL_INSTRUCTIONS = [
    # System call entry
    'call_pal',

    # Hardware memory access (bypasses translation)
    'hw_ld', 'hw_st',

    # Internal processor register access
    'hw_mfpr', 'hw_mtpr',

    # Return from exception/interrupt
    'hw_rei',

    # NOTE: interrupt handling is included as an aspect in each VM instruction
    # (aspects/interrupt.isa), so it is merged naturally with all instructions.
]

# Alpha IEEE floating-point instructions
ALPHA_FP_INSTRUCTIONS = [
    # Single precision arithmetic (4)
    'adds', 'subs', 'muls', 'divs',

    # Double precision arithmetic (4)
    'addt', 'subt', 'mult', 'divt',

    # Square root (2)
    'sqrts', 'sqrtt',

    # Comparisons (3)
    'cmpteq', 'cmptlt', 'cmptle',

    # Conversions (4)
    'cvtts', 'cvttq', 'cvtqs', 'cvtqt',

    # Sign operations (3)
    'cpys', 'cpysn', 'cpyse',

    # Load/Store (4)
    'lds', 'ldt', 'sts', 'stt',

    # FPCR access (2)
    'mf_fpcr', 'mt_fpcr',

    # Integer-FP moves (2)
    'ftoit', 'itoft',
]

# Pseudo-instructions to exclude (gem5-specific, not real Alpha)
EXCLUDED_INSTRUCTIONS = {
    'initparam', 'm5a_getid', 'm5a_old', 'm5readfile', 'm5panic',
    'quiesce', 'quiesceTime',
}


def apply_memory_transform(merged_graph):
    """Apply port width setting for 64-bit word-addressed unified memory."""
    mem_node = merged_graph.nodes.get('umem')
    if mem_node:
        access_widths = mem_node.data.get('access_widths', [64])
        max_width = max(access_widths) if access_widths else 64
        print(f"  umem access widths: {access_widths}, max: {max_width}")

        # Apply set_port_width transformation for sub-quadword access
        # This generates byte-enable and data-positioning logic for
        # stores (stb=8, stw=16, stl=32) and loads (ldbu=8, ldwu=16, ldl=32)
        # on the 64-bit memory bus. Alpha is little-endian.
        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory='umem',
            strategy='set_port_width',
            current_width=max_width,
            target_width=64,  # 64-bit quadword-addressed memory
            direction='forward',
            endianness='little',  # Alpha is little-endian
            alignment='port_width'  # Aligned accesses only
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed umem: added {len(result.get('nodes_added', []))} byte mux nodes")
        else:
            print(f"  Skipped umem: {result.get('reason', 'unknown')}")
    else:
        print("  No umem node found, skipping memory transform")



def generate_verilog(merged_graph, module_name, output_dir):
    """Generate Verilog output using VerilogGenerator directly."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    generator = VerilogGenerator(merged_graph, module_name)
    verilog_code = generator.generate()

    # Interrupt handling is now included as an aspect in each VM instruction
    # (aspects/interrupt.isa), so no post-processing is needed.

    rtl_file = output_path / f"{module_name}.v"
    rtl_file.write_text(verilog_code)
    print(f"  Generated: {rtl_file}")

    files = {'rtl': rtl_file}

    # Generate memory wrappers if externalized
    if generator.externalized_memories:
        for mem_name in generator.externalized_memories:
            wrapper_code = generator.generate_memory_wrapper(mem_name)
            if wrapper_code:
                wrapper_file = output_path / f"{mem_name}_memory.v"
                wrapper_file.write_text(wrapper_code)
                files[f'{mem_name}_wrapper'] = wrapper_file
                print(f"  Generated: {wrapper_file}")

    return files


def main():
    parser = argparse.ArgumentParser(
        description='Generate Linux-capable Alpha64 processor from ISA definitions'
    )
    parser.add_argument(
        '--output-dir', '-o',
        default='examples/verilog/alpha64',
        help='Output directory (default: examples/verilog/alpha64)'
    )
    parser.add_argument(
        '--module-name', '-m',
        default='alpha64_linux',
        help='Module name (default: alpha64_linux)'
    )
    parser.add_argument(
        '--no-pal',
        action='store_true',
        help='Exclude PAL instructions (for testing)'
    )
    parser.add_argument(
        '--no-fp',
        action='store_true',
        help='Exclude FP instructions'
    )
    parser.add_argument(
        '--no-vm',
        action='store_true',
        help='Use physical addressing instead of virtual memory (ITB/DTB)'
    )
    parser.add_argument(
        '--no-externalize',
        action='store_true',
        help='Do not externalize memory (for small simulations with internal arrays)'
    )
    args = parser.parse_args()

    module_name = args.module_name
    output_dir = args.output_dir
    externalize = not args.no_externalize

    # Build instruction lists
    user_instructions = [i for i in ALPHA_USER_INSTRUCTIONS if i not in EXCLUDED_INSTRUCTIONS]
    pal_instructions = [] if args.no_pal else [i for i in ALPHA_PAL_INSTRUCTIONS if i not in EXCLUDED_INSTRUCTIONS]
    fp_instructions = [] if args.no_fp else [i for i in ALPHA_FP_INSTRUCTIONS if i not in EXCLUDED_INSTRUCTIONS]

    total_instructions = len(user_instructions) + len(pal_instructions) + len(fp_instructions)
    use_vm = not args.no_vm

    print("=" * 70)
    print("Alpha64 Linux-Capable Processor Generator")
    print("=" * 70)
    print(f"\nGenerating Alpha64 processor with {total_instructions} instructions...")
    print(f"  User:       {len(user_instructions)} instructions (integer/memory)")
    print(f"  PAL:        {len(pal_instructions)} instructions (privileged)")
    print(f"  FP:         {len(fp_instructions)} instructions (IEEE 754)")
    print(f"  VM:         {'enabled (ITB/DTB)' if use_vm else 'disabled (physical addressing)'}")
    print(f"  Externalize: {'enabled' if externalize else 'disabled (internal arrays)'}")

    # Step 1: Parse and merge ISA files
    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)

    # Map instruction names to file paths
    isa_files = {}
    missing = []

    # User instructions (isa/alpha64/vm/ for VM mode, isa/alpha64/ for physical)
    user_base = "isa/alpha64/vm" if use_vm else "isa/alpha64"
    for instr in user_instructions:
        path = f"{user_base}/{instr}.isa"
        if os.path.exists(path):
            isa_files[instr] = path
        else:
            # Fall back to base isa/alpha64/ if VM file doesn't exist
            fallback = f"isa/alpha64/{instr}.isa"
            if os.path.exists(fallback):
                isa_files[instr] = fallback
            else:
                missing.append(instr)

    # PAL instructions (isa/alpha64/pal/)
    for instr in pal_instructions:
        path = f"isa/alpha64/pal/{instr}.isa"
        if os.path.exists(path):
            isa_files[f"pal_{instr}"] = path
        else:
            missing.append(f"pal:{instr}")

    # FP instructions (isa/alpha64/f/, with VM versions in isa/alpha64/vm/)
    # VM versions include ITB translation and interrupt handling aspects
    for instr in fp_instructions:
        # Check for VM version first (has ITB + interrupt aspects)
        if use_vm:
            vm_path = f"isa/alpha64/vm/{instr}.isa"
            if os.path.exists(vm_path):
                isa_files[f"fp_{instr}"] = vm_path
                continue
        # Fall back to standard FP path (no VM translation)
        path = f"isa/alpha64/f/{instr}.isa"
        if os.path.exists(path):
            isa_files[f"fp_{instr}"] = path
        else:
            missing.append(f"fp:{instr}")

    if missing:
        print(f"  Warning: Missing ISA files for: {missing}")

    print(f"  Found {len(isa_files)} ISA files")

    try:
        merged_graph = merge_instructions(isa_files)
        print(f"  Successfully merged {len(isa_files)} instructions")
        print(f"  Merged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")
    except Exception as e:
        print(f"  Error merging instructions: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Step 2: Apply memory transformations
    print("\n" + "=" * 70)
    print("Step 2: Checking memory access widths...")
    print("=" * 70)
    apply_memory_transform(merged_graph)

    # Step 2b: Externalize unified memory for Linux boot
    if externalize:
        print("\n" + "=" * 70)
        print("Step 2b: Applying memory externalization...")
        print("=" * 70)

        # Externalize umem (unified memory - read + write)
        umem_spec = MemoryExternalizationSpec(
            memory_name='umem',
            create_read_port=True,
            create_write_port=True,
            variable_latency=True
        )
        apply_memory_externalization(merged_graph, umem_spec)

    # Step 3: Mark FP div/sqrt as multi-cycle
    print("\n" + "=" * 70)
    print("Step 3: Marking FP div/sqrt as multi-cycle...")
    print("=" * 70)
    for op_id in ['fp_div(f1, f2)', 'fp_div_d(f1, f2)', 'fp_sqrt(f1)', 'fp_sqrt_d(f1)']:
        if op_id in merged_graph.nodes:
            node = merged_graph.nodes[op_id]
            node.data['multi_cycle'] = True
            node.data['latency_cycles'] = 10
            print(f"  Marked {op_id} as multi-cycle (10 cycles)")

    # Step 4: Generate RTL
    print("\n" + "=" * 70)
    print("Step 4: Generating Verilog RTL and testbench...")
    print("=" * 70)
    print(f"  Output directory: {output_dir}")

    try:
        files = generate_verilog(merged_graph, module_name, output_dir)

        print(f"\n  Generated files:")
        for key, path in files.items():
            if hasattr(path, 'stat'):
                file_size = path.stat().st_size if path.exists() else 0
                print(f"    {key.upper()}: {path} ({file_size:,} bytes)")
            else:
                print(f"    {key.upper()}: {path}")

    except Exception as e:
        print(f"  Error generating Verilog: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"  Successfully generated Linux-capable Alpha64 processor")
    print(f"  {len(user_instructions)} user instructions")
    print(f"  {len(pal_instructions)} PAL instructions (privileged)")
    print(f"  {len(fp_instructions)} FP instructions (IEEE 754)")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Output: {output_dir}/")

    print("\nKey features for Linux boot:")
    print("  - PALcode support (CALL_PAL, HW_REI)")
    print("  - Privileged register access (HW_MFPR, HW_MTPR)")
    print("  - Physical memory access (HW_LD, HW_ST)")
    print("  - IEEE 754 floating-point (single & double)")
    print("  - All user-mode integer/logical/memory operations")
    if use_vm:
        print("  - Virtual memory (ITB/DTB) with 8-entry TLBs")
        print("  - TLB miss exceptions trap to PALcode handlers")

    print("\nArchitectural state:")
    print("  - 32 general-purpose registers (r0-r31, r31=zero)")
    print("  - 32 floating-point registers (f0-f31)")
    print("  - 64-bit program counter")
    print("  - PAL mode flag and PAL base register")
    print("  - 24 PAL scratch registers (pt0-pt23)")
    print("  - Internal processor registers (IPRs)")
    if use_vm:
        print("  - ITB: 8-entry instruction TLB (tag, PTE, valid)")
        print("  - DTB: 8-entry data TLB (tag, PTE, valid)")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
