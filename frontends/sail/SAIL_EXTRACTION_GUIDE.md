# SAIL Extraction Guide with Function Inlining

This guide explains how to re-extract RISC-V SAIL patterns with the new function inlining support.

## Overview

The OCaml SAIL extractor (commit `ce0faa3`) now supports proper function inlining during extraction. This eliminates the need for semantic modeling hacks in the SMT verification layer.

## Prerequisites

1. **SAIL Compiler**: Version 0.20 or later
   ```bash
   opam install sail
   ```

2. **OCaml Build Tools**: dune, opam
   ```bash
   opam install dune
   ```

3. **sail-riscv Source**: RISC-V formal specification
   ```bash
   cd <ISACOMP_ROOT>
   git clone https://github.com/riscv/sail-riscv.git
   ```

## Build the Extractor

```bash
cd <ISACOMP_ROOT>/sail/ocaml_sail_extractor

# Source opam environment
. ~/.opam/opam-init/init.sh

# Build the extractor
dune build

# The binary is at: _build/default/sail_to_rgraph.exe
```

## Extract RISC-V Instructions

### Quick Method: Extract Base Integer Instructions

This extracts RV32I base instructions (ADD, SUB, AND, OR, etc.) with helper functions:

```bash
cd <ISACOMP_ROOT>/sail/ocaml_sail_extractor

# Source opam environment
. ~/.opam/opam-init/init.sh

# Extract with function inlining
./_build/default/sail_to_rgraph.exe \
    <ISACOMP_ROOT>/sail-riscv/model/extensions/I/base_insts.sail \
    rtype_inlined.json \
    --per-instruction \
    --deps-file deps.txt

# The deps.txt file should list core dependencies (see below)
```

### Create deps.txt File

The `deps.txt` file lists SAIL files that must be loaded before extracting instructions. These provide type definitions, register declarations, and helper functions.

**Required core files** (in order):
```
# Core types and utilities
sail-riscv/model/prelude.sail
sail-riscv/model/core/types.sail
sail-riscv/model/core/arithmetic.sail

# Register file and memory
sail-riscv/model/core/regs.sail
sail-riscv/model/core/mem.sail

# Instruction decode
sail-riscv/model/decode/*.sail

# Extension types (if needed)
sail-riscv/model/extensions/I/I_types.sail
```

**Note**: The exact file list depends on sail-riscv version. Check the repository's build configuration for the canonical list.

### Extract with Real Fetch Function (Optional)

To inline the real SAIL `fetch()` function instead of using synthetic `instr = imem[pc]`:

```bash
./_build/default/sail_to_rgraph.exe \
    sail-riscv/model/extensions/I/base_insts.sail \
    rtype_with_fetch.json \
    --per-instruction \
    --use-real-fetch \
    --deps-file deps.txt
```

**Warning**: Real fetch includes address translation and exception handling, making graphs much larger. Only use for testing fetch semantics.

## Verify Function Inlining Works

After extraction, verify that `wX_bits` was properly inlined:

```python
import json

# Load extracted JSON
data = json.load(open('rtype_inlined.json'))

# Check RTYPE instruction
rtype = data.get('RTYPE', {})
print(f"RTYPE has {len(rtype['nodes'])} nodes")

# Check for wX_bits operation nodes (should be NONE)
wX_bits_ops = [n for n in rtype['nodes']
               if n.get('data', {}).get('operator') == 'wX_bits']
print(f"wX_bits operation nodes: {len(wX_bits_ops)}")

# Should see conditional/comparison nodes instead
conditionals = [n for n in rtype['nodes']
                if n.get('data', {}).get('type') in ['conditional', 'multiplexer', 'comparison']]
print(f"Conditional/comparison nodes: {len(conditionals)}")

# Check helper functions were extracted
print(f"Helper functions: {[k for k in data.keys() if k.startswith('_')]}")
```

**Expected output**:
```
RTYPE has 150+ nodes  (more than before due to inlining)
wX_bits operation nodes: 0  (NONE - it's inlined!)
Conditional/comparison nodes: 5+  (x0 check is explicit)
Helper functions: ['_wX', '_wX_bits', '_rX', '_rX_bits', '_fetch']
```

## Test Verification

After re-extraction, test that SMT verification still works:

```bash
python3 verify_sail_vs_isa.py RTYPE riscv32/add.isa
```

**Expected result**: `✅ VERIFICATION PASSED: Graphs are equivalent! (unsat)`

## Update Cached Files

Once verified, update the cached JSON files:

```bash
# Back up old extraction
mv sail/ocaml_sail_extractor/rtype_multiplexer.json \
   sail/ocaml_sail_extractor/rtype_multiplexer_old.json

# Copy new extraction
cp sail/ocaml_sail_extractor/rtype_inlined.json \
   sail/ocaml_sail_extractor/rtype_multiplexer.json

# Test again to confirm
python3 verify_sail_vs_isa.py RTYPE riscv32/add.isa
```

## Remove Backward Compatibility Code

After all cached files are re-extracted and verified:

1. Remove wX_bits fallback from `smt_verification.py` (lines 1614-1666)
2. Test all verification scripts pass
3. Commit the cleanup

```bash
# Remove the backward compatibility block
vim smt_verification.py  # Delete lines 1614-1666

# Test everything still works
python3 verify_sail_vs_isa.py RTYPE riscv32/add.isa
python3 verify_sail_instruction.py

# Commit
git add smt_verification.py
git commit -m "Remove wX_bits SMT fallback after re-extraction with inlining"
git push
```

## Troubleshooting

### "unknown constant" errors during extraction

**Problem**: SAIL can't find type/function definitions.

**Solution**: Add missing dependency files to `deps.txt`. Common missing files:
- `model/core/prelude_mem.sail` (memory types)
- `model/core/prelude_mem_addrtype.sail` (address types)
- `model/core/extensions.sail` (extension checking)

### Extractor crashes with "Fatal_error"

**Problem**: SAIL type checking failed.

**Solutions**:
1. Use `--per-instruction` flag (skips full type checking)
2. Check SAIL version matches sail-riscv requirements
3. Use `--deps` to list dependencies explicitly

### Inlining didn't work (still see wX_bits operators)

**Problem**: Helper function graph not found during extraction.

**Debug**:
1. Check `_wX` and `_wX_bits` are in output JSON
2. Verify helper extraction happens in "Second pass" (check console output)
3. Check builder is created with `create_with_helpers` (line 1261 in sail_to_rgraph.ml)

### Graph is too large after inlining

**Expected**: Inlining increases node count (RTYPE: ~93 nodes → ~150+ nodes)

**If excessive** (>500 nodes for single instruction):
- Don't use `--use-real-fetch` (fetch inlining adds 100+ nodes)
- Check for recursive inlining (shouldn't happen but investigate)
- Verify only target functions are inlined (wX, wX_bits, rX, rX_bits)

## Architecture Notes

### How Inlining Works

1. **Second pass** (lines 1417-1438 in sail_to_rgraph.ml):
   - Extract helper functions (wX, wX_bits, rX, etc.) into `helper_graphs_tbl`
   - Store as `{"wX": graph, "wX_bits": graph, ...}`

2. **Third pass** (lines 1440-1447):
   - Process each `execute` clause (one per instruction)
   - Create builder with: `create_with_helpers helper_graphs`

3. **During expression visiting** (lines 682-700):
   - When encountering `E_app(wX_bits, [rd, value])`
   - Look up `wX_bits` in builder.helper_graphs
   - Call `inline_function_call(graph, params, args)`
   - Clone function body with fresh IDs
   - Redirect parameter edges to argument nodes
   - Return inlined result node

4. **Result**:
   - Instead of `operation(wX_bits)` node
   - Get explicit: `comparison(r != 0)` → `conditional(if)` → `array_write(X[r] = v)`

### Parameter Mapping

Functions and their parameters (defined in sail_to_rgraph.ml:675-680):

```ocaml
| ("wX", ["r"; "v"])           (* r: regno, v: xlenbits *)
| ("wX_bits", ["r"; "width"])  (* r: regidx, width: unused *)
| ("rX", ["r"])                (* r: regno *)
| ("rX_bits", ["r"])           (* r: regidx *)
```

These parameter names must match the SAIL function signatures in `sail-riscv/model/core/regs.sail`.

## References

- OCaml extractor: `sail/ocaml_sail_extractor/sail_to_rgraph.ml`
- Python loader: `sail/ocaml_sail_extractor/sail_loader.py`
- SMT verification: `smt_verification.py`
- Verification script: `verify_sail_vs_isa.py`
- Implementation doc: `FUNCTION_INLINING_STATUS.md`
- sail-riscv repo: https://github.com/riscv/sail-riscv
- SAIL docs: https://github.com/rems-project/sail

## Quick Reference Commands

```bash
# Build extractor
cd sail/ocaml_sail_extractor && . ~/.opam/opam-init/init.sh && dune build

# Extract with inlining
./_build/default/sail_to_rgraph.exe input.sail output.json --per-instruction

# Verify extraction
python3 verify_sail_vs_isa.py PATTERN file.isa

# Check for inlining
python3 -c "import json; d=json.load(open('output.json')); print([k for k in d if k.startswith('_')])"
```

