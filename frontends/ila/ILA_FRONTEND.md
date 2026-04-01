# ILA Frontend

Frontend for parsing ILA (Instruction-Level Abstraction) models into isacomp's ResourceGraph format.

ILA is a formal model for hardware/software interfaces developed at Princeton University. Models are defined using the [ILAng](https://github.com/PrincetonUniversity/ILAng) C++ API. The [IMDb repository](https://github.com/PrincetonUniversity/IMDb) contains models for accelerators (AES, SHA), processor cores (RISC-V Pico/Piccolo/Rocket), and communication interfaces.

## Usage

### Parsing pre-exported JSON

```python
from core.resource_graph import ResourceGraph

graph = ResourceGraph.from_ila_json_file('model.json')
```

### Exporting from ILA models (requires ILAng)

```bash
# Generate full ILA models (Pico, Piccolo, Rocket)
./generate_ila_models.sh

# Extract individual instruction JSON files
./extract_all_individual_instructions.sh

# Files land in test_data/riscv/
```

To extract a single instruction:

```bash
python3 extract_instruction.py test_data/riscv/pico_full.json --list
python3 extract_instruction.py test_data/riscv/pico_full.json \
    --instruction ADD --output my_add.json
```

### Running tests

```bash
make test          # or ./run_tests.sh or python3 run_all_tests.py
make test-basic
make test-realistic
```

## Architecture

```
ILA Model (C++)  ->  ILAng Export  ->  JSON  ->  ila_parser_real.py  ->  ResourceGraph
```

ILAng has built-in JSON serialization (`IlaSerDesMngr::SerToFile()`), so no C++ binding is needed.

### Core files

- `ila_parser_real.py` -- Main parser for ILAng JSON format
- `ila_opcodes.py` -- ILAng operation code mappings
- `ila_transformations.py` -- Transforms ILA patterns to structural representations
- `accelerator_verilog_generator.py` -- Generate Verilog from ILA resource graphs
- `ila_to_isa_transform.py` -- Convert ILA register representation to ISA format
- `extract_instruction.py` -- Extract individual instructions from full ILA JSON

## ILA JSON format

### Top-level structure

```json
{
  "a": [...],          // AST array (shared expression DAG, referenced by ID)
  "f": null,           // Function definitions (if any)
  "t": {
    "n": "riscv",      // Model name
    "s": [9, 11, ...], // State variable IDs (into AST array)
    "i": [],           // Input variable IDs
    "v": 19,           // Valid expression ID
    "instr": [...],    // Instructions (decode + update functions)
    "c": [...]         // Child ILAs (hierarchical models)
  }
}
```

### Instruction structure

Each instruction is self-contained:

```json
{
  "n": "ADD",           // Instruction name
  "d": 2864,            // Decode expression ID (when does this execute?)
  "u": {                // Updates: state_name -> expression_id
    "pc": 2849,
    "x0": 2866,
    ...
  }
}
```

### Expression DAG

The `"a"` array is a directed acyclic graph where nodes are expressions (identified by `"i": id`) and edges are argument references (`"a": [arg_ids]`). Sub-expressions are shared across instructions -- a full Pico model has 3,877 expressions for 37 instructions, but extracting a single ADD instruction needs only 335 (91% reduction).

### Instruction extraction

Individual instructions can be extracted from full models:

```bash
python3 extract_instruction.py pico_full.json --all output_dir/
```

Size ranges: simple instructions (LUI, AUIPC) ~140 expressions / 19KB, ALU (ADD, SUB) ~335 / 44KB, stores (SW, SH, SB) ~400 / 42KB.

## Hierarchical ILA support

Complex accelerators use hierarchical ILAs where a parent ILA has child ILAs representing sub-operations. Children appear in the `"c"` field:

```json
{
  "t": {
    "n": "parent_ila",
    "s": [1, 2, 3],
    "instr": [...],
    "c": [{
      "n": "child_ila",
      "s": [4, 5],
      "f": 2,            // Fetch expression (parent state driving child)
      "v": 10,           // Valid condition
      "instr": [...],
      "c": []            // Recursive nesting supported
    }]
  }
}
```

Example -- AES accelerator from IMDb:

```
Parent ILA (aes_top)
+-- States: status, address, length, counter, key, xram
+-- Instructions: WRITE_KEY, WRITE_ADDRESS, START_ENCRYPT, ...
+-- Child ILA (AES_BLOCK) - Triggered by START_ENCRYPT
    +-- States: rd_data, enc_data, byte_cnt, blk_cnt
    +-- Instructions: LOAD, OPERATE, STORE
    +-- Child ILA (AES_128) - Function-level model
        +-- Instructions: AddRoundKey, IntermediateRound, FinalRound
```

The parser recursively processes child ILAs and integrates them into the graph. Each node carries `ila_name` metadata indicating which ILA level it belongs to.

## Building ILA models from IMDb

### Prerequisites

- C++ compiler (GCC 9+ or Clang 10+), CMake 3.9.6+, Z3 SMT solver (`sudo apt-get install z3`)

### Setup

ILAng is cloned and built in `ILAng/`, IMDb models are in `imdb/`, and patches have been applied. To rebuild from scratch:

```bash
cd ILAng && rm -rf build && mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release && make -j$(nproc)
```

### Generation pipeline

```
riscvIla.cc + export_pico.cc  ->  g++ -lilang -lz3  ->  ./export_pico  ->  pico_full.json
```

All three models (Pico, Piccolo, Rocket) implement the full RV32I base integer instruction set (37 instructions). They differ in register file modeling and memory organization but are functionally equivalent.

### AES accelerator

The AES ILA model is at https://github.com/yuex1994/ILA_AES. Clone it into `imdb/ILA_AES/`, build with CMake, and export using `ExportIlaPortable()`. See `generate_aes_verilog.py` and `aes_128_with_lut_example.cc` for examples. The S-box LUT optimization patch (`ilang_aes_lut_optimization.patch`) replaces 256-entry nested ITEs with memory-based lookups, reducing expression count by 99%.

## Patches applied

Patches are in `patches/` and as `*.patch` files in this directory.

**ILAng build fixes** (`ilang_build_fix.patch`): Added missing `<cstdint>` header, disabled `-Werror` for GCC 13+.

**IMDb model fixes** (`imdb_complete_fix.patch`): Added `model.SetValid(BoolConst(true))` required for JSON export in modern ILAng. Applied to Pico, Piccolo, and Rocket.

**Opcode mapping fix** (`patches/001-fix-ilang-opcode-mapping.patch`): Corrected off-by-one in ILAng opcode enum mapping. Discovered via SMT equivalence checking.

## Troubleshooting

| Error | Fix |
|-------|-----|
| `libilang.so not found` | `export LD_LIBRARY_PATH=$PWD/ILAng/build/src:$LD_LIBRARY_PATH` |
| `z3 not found` | `sudo apt-get install z3 libz3-dev` |
| `SetValid not called` | Apply `imdb_complete_fix.patch` |
| `Instruction 'XXX' not found` | Names are UPPERCASE (ADD, not add). Use `--list` to see available. |

## References

- [ILAng](https://github.com/PrincetonUniversity/ILAng) -- ILA language compiler and library
- [Princeton IMDb](https://github.com/PrincetonUniversity/IMDb) -- ILA model database
- [ILA Paper](https://doi.org/10.1145/3293454) -- "Instruction-Level Abstraction (ILA): A Uniform Specification for SoC Verification" (TODAES 2019)
