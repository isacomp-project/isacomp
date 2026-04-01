# SAIL to ResourceGraph Extractor

OCaml-based tool to extract instruction semantics from RISC-V SAIL specifications and convert them to isacomp's ResourceGraph format.

## Overview

This tool bridges the gap between:
- **sail-riscv**: Official RISC-V specification in SAIL
- **isacomp**: Python-based microarchitecture compiler using ResourceGraph

### Architecture

```
SAIL Specification (.sail)
         ↓
   [OCaml Extractor]
   (using libsail)
         ↓
   JSON (nodes & edges)
         ↓
  [Python Loader]
  (sail_loader.py)
         ↓
  ResourceGraph
         ↓
  isacomp pipeline
```

## Installation

### Prerequisites

1. **OCaml and opam** (installed ✓)
2. **SAIL** (installed ✓)
3. **dune** (installed ✓)

### Build

```bash
cd ocaml_sail_extractor
dune build
```

This creates: `_build/default/sail_to_rgraph.exe`

## Usage

### Command Line

#### OCaml Extractor (Step 1: SAIL → JSON)

```bash
./sail_to_rgraph.exe <input.sail> <output.json>
```

Example:
```bash
./sail_to_rgraph.exe ../sail/sail-riscv/model/extensions/I/base_insts.sail add.json
```

### Programmatic (Python)

```python
from frontends.sail.ocaml_sail_extractor import SAILInstructionLoader

loader = SAILInstructionLoader()
graph = loader.load_instruction_pattern('RTYPE')

# Now use with isacomp
from backends.verilog import generate_verilog
verilog = generate_verilog(graph, module_name="my_instruction")
```

## How It Works

### OCaml Extractor (`sail_to_rgraph.ml`)

1. **Parses SAIL** using `libsail` (SAIL's OCaml library)
2. **Walks the typed AST** using pattern matching on SAIL expression types
3. **Extracts semantics**:
   - Operations: `+`, `-`, `*`, etc.
   - Variables: intermediate values
   - Array accesses: `X[rd]`, `IMEM[PC]`
   - Bit slices: `instr[31:25]`
   - Assignments: `PC := PC + 4`
4. **Outputs JSON** matching ResourceGraph format

### Python Loader (`sail_loader.py`)

1. **Calls OCaml extractor** as subprocess (with caching)
2. **Parses JSON** output
3. **Post-processes**: remaps IDs, fixes bit-slices, converts edge types
4. **Returns** ResourceGraph via `ResourceGraph.from_json()`

## Supported SAIL Constructs

### ✅ Implemented

- **Binary operations**: `add_bits`, `sub_bits`, arithmetic
- **Variables**: identifier references
- **Literals**: integers, hex, binary
- **Assignments**: `:=` operator
- **Let bindings**: `let x = expr in body`
- **Conditionals**: `if-then-else`
- **Field access**: struct/record fields
- **Vectors/Lists**: array literals
- **Function calls**: general function application

### 🚧 Partial Support

- **Array access**: read/write operations (needs bounds info)
- **Bit slicing**: extraction (needs width inference)

### ⏳ TODO

- **Pattern matching**: SAIL's powerful pattern dispatch
- **Union types**: instruction type unions
- **Mapping clauses**: encoding/decoding
- **Built-in functions**: `sign_extend`, `zero_extend`, etc.
- **Type inference**: full SAIL type system

## Working with sail-riscv

To use with real RISC-V instructions from sail-riscv:

### Option 1: Extract full project

```bash
# sail-riscv uses a .sail_project file listing all dependencies
# You'll need to point to the project file or include all dependencies

# Example: Extract with project context
./sail_to_rgraph.exe \
  ../sail/sail-riscv/model/extensions/I/base_insts.sail \
  base_insts.json
```

**Note**: Currently this will fail because base_insts.sail depends on:
- Core prelude files
- Type definitions (xlenbits, regidx, etc.)
- Helper functions

### Option 2: Standalone instruction functions

Create simplified SAIL functions for specific instructions:

```sail
/* test_add.sail - Standalone ADD semantics */

val test_add : (bits(32), bits(32)) -> bits(32)

function test_add(rs1_val, rs2_val) = {
  let result = rs1_val + rs2_val;
  result
}
```

Then extract:
```bash
./sail_to_rgraph.exe test_add.sail test_add.json
```

### Option 3: Use sail-riscv as library (Future Work)

Modify extractor to:
1. Load sail-riscv's .sail_project
2. Extract per-instruction semantics from `execute()` clauses
3. Handle union dispatch and pattern matching

## JSON Format

The OCaml extractor outputs:

```json
{
  "nodes": [
    {
      "id": "n0",
      "data": {
        "type": "var",
        "display_name": "rs1_val",
        "operator": null,
        "value": null,
        "bit_width": null,
        "is_arch_state": false,
        "is_memory": false,
        "array_size": null
      }
    },
    {
      "id": "n2",
      "data": {
        "type": "operation",
        "display_name": "rs1_val + rs2_val",
        "operator": "+",
        ...
      }
    }
  ],
  "edges": [
    {
      "id": "e0",
      "source": "n0",
      "target": "n2",
      "data": {"type": "operand"}
    }
  ]
}
```

## Files

- **`sail_to_rgraph.ml`**: OCaml extractor (main logic)
- **`dune`**: Build configuration
- **`dune-project`**: Project metadata
- **`sail_loader.py`**: Python loader (JSON → ResourceGraph with post-processing)
- **`__init__.py`**: Package init, exports `SAILInstructionLoader`
- **`README.md`**: This file

## Development

### Adding Support for New SAIL Constructs

1. **Identify the AST pattern** in `~/.opam/default/lib/libsail/Ast.mli`
2. **Add pattern match** in `visit_exp` or `visit_lexp`
3. **Create ResourceGraph nodes/edges** for the construct
4. **Test** with a minimal SAIL example

Example:
```ocaml
(* In visit_exp: *)
| E_vector_append (left, right) ->
    let left_node = visit_exp builder left in
    let right_node = visit_exp builder right in
    let concat_node = make_node ~display_name:(Some "concat") "concat" in
    let concat_node = add_node builder concat_node in
    connect builder left_node concat_node "left";
    connect builder right_node concat_node "right";
    concat_node
```

### Debugging

Run with backtrace:
```bash
OCAMLRUNPARAM=b ./sail_to_rgraph.exe input.sail output.json
```

### Testing

Create minimal SAIL test cases in `ocaml_sail_extractor/tests/`:

```sail
/* tests/test_arithmetic.sail */
function test_add(a : bits(32), b : bits(32)) -> bits(32) = a + b
function test_sub(a : bits(32), b : bits(32)) -> bits(32) = a - b
```

## Status

- OCaml extractor compiles and runs against full sail-riscv
- 352 instruction patterns extracted from sail-riscv
- Python loader post-processes JSON into ResourceGraph
- RV32I (37 tests), RV32F (10 tests), RV32D (9 tests) all passing
- System-level instruction support (CSR, privilege, MMU) in progress

## References

- **SAIL Language**: https://github.com/rems-project/sail
- **sail-riscv**: https://github.com/riscv/sail-riscv
- **SAIL Manual**: https://alasdair.github.io/manual.html
- **isacomp**: ../README.md (parent directory)
