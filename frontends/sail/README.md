# SAIL Integration for isacomp

This directory contains all SAIL-related code for loading RISC-V instruction semantics from the official RISC-V SAIL specification.

## Directory Structure

```
sail/
├── sail-riscv/              # Official RISC-V SAIL specification (git submodule)
│   └── model/
│       └── riscv.sail_project
│
└── ocaml_sail_extractor/    # OCaml tool to extract SAIL → ResourceGraph
    ├── sail_to_rgraph.ml    # Main extractor (OCaml)
    ├── sail_loader.py       # Python API for loading SAIL instructions
    ├── dune                 # Build configuration
    ├── Makefile             # Convenience build targets
    ├── README.md            # Detailed extractor documentation
    └── docs/
        └── VERIFICATION.md  # Test results
```

## Quick Start

### 1. Build the Extractor

```bash
cd ocaml_sail_extractor
make build
```

This requires:
- OCaml >= 4.14
- opam (OCaml package manager)
- SAIL >= 0.18
- dune >= 3.0
- z3 (SMT solver)

See `ocaml_sail_extractor/README.md` for installation instructions.

### 2. Extract RISC-V Instructions

```bash
cd ocaml_sail_extractor
make extract-riscv
```

This extracts all 347 instruction patterns to `/tmp/riscv_instructions.json`

### 3. Use in Python

```python
# From isacomp root directory
from sail.ocaml_sail_extractor.sail_loader import SAILInstructionLoader

loader = SAILInstructionLoader()

# Load an instruction pattern
rtype = loader.load_instruction_pattern('RTYPE')
print(f"RTYPE: {len(rtype.nodes)} nodes, {len(rtype.edges)} edges")

# List all available patterns
patterns = loader.list_available_patterns()
print(f"Available: {len(patterns)} patterns")
```

### 4. Command-Line Interface

```bash
# From isacomp root directory

# List all patterns
python3 sail/ocaml_sail_extractor/sail_loader.py --list

# Show pattern info
python3 sail/ocaml_sail_extractor/sail_loader.py --info RTYPE

# Load a specific pattern
python3 sail/ocaml_sail_extractor/sail_loader.py RTYPE
```

## Available Instruction Patterns

### Base Integer (RV32I)

| Pattern | Nodes | Edges | Coverage |
|---------|-------|-------|----------|
| RTYPE | 77 | 74 | ADD, SUB, AND, OR, XOR, SLT, SLTU, SLL, SRL, SRA |
| ITYPE | 41 | 36 | ADDI, ANDI, ORI, XORI, SLTI, SLTIU |
| SHIFTIOP | 26 | 21 | SLLI, SRLI, SRAI |
| UTYPE | 18 | 13 | LUI, AUIPC |
| JAL | 19 | 13 | JAL |
| JALR | 28 | 19 | JALR |
| BTYPE | 44 | 40 | BEQ, BNE, BLT, BGE, BLTU, BGEU |
| LOAD | 25 | 18 | LB, LH, LW, LBU, LHU |
| STORE | 31 | 24 | SB, SH, SW |

**Total: 35 base instructions covered by 9 patterns**

### Extensions

The extractor also provides 347 total patterns including:

- **M Extension**: Multiply/Divide (MUL, DIV, REM, etc.)
- **A Extension**: Atomic operations (LR, SC, AMO*)
- **F/D Extensions**: Floating point (single and double precision)
- **V Extension**: Vector operations
- **C Extension**: Compressed 16-bit instructions
- **B Extension**: Bit manipulation
- **K Extension**: Cryptography
- **Privileged**: CSR, system calls, traps

## How It Works

```
SAIL Specification (sail-riscv)
         ↓
   [OCaml Extractor]
   sail_to_rgraph.exe
   (uses libsail)
         ↓
   JSON (nodes & edges)
   /tmp/riscv_instructions.json
         ↓
   [Python Loader]
   sail_loader.py
         ↓
   ResourceGraph
         ↓
   isacomp pipeline
```

### Pattern-Based Extraction

SAIL uses **pattern-based** instruction encoding, where one `execute` clause handles multiple related instructions:

```sail
function clause execute (RTYPE(rs2, rs1, rd, op)) = {
  let rs1_val = X(rs1);
  let rs2_val = X(rs2);
  let result : xlenbits = match op {
    RISCV_ADD  => rs1_val + rs2_val,
    RISCV_SUB  => rs1_val - rs2_val,
    RISCV_AND  => rs1_val & rs2_val,
    // ... etc for all R-type operations
  };
  X(rd) = result;
  RETIRE_SUCCESS
}
```

The extractor produces one ResourceGraph per pattern, capturing the full semantics including all variants.

## Integration with isacomp

### Loading Instructions

```python
from sail.sail_loader import SAILInstructionLoader
from backends.verilog import generate_verilog

loader = SAILInstructionLoader()

# Load pattern
graph = loader.load_instruction_pattern('ITYPE')

# Use with isacomp
verilog = generate_verilog(graph, module_name="itype_alu")
```

### Caching

The loader caches extracted instructions by default:

```python
# First call: extracts from SAIL (slow, ~60 seconds)
loader.load_instruction_pattern('RTYPE')

# Subsequent calls: use cached JSON (fast, <1 second)
loader.load_instruction_pattern('ITYPE')

# Force re-extraction
loader.extract_all_instructions(force_rebuild=True)
```

## Verification

All SAIL-extracted patterns have been verified to:

1. ✅ Load successfully into isacomp's ResourceGraph format
2. ✅ Capture equivalent semantics to hand-written .isa files
3. ✅ Include full formal specification detail from sail-riscv

See `ocaml_sail_extractor/docs/VERIFICATION.md` for detailed test results.

## Documentation

- **Installation**: `ocaml_sail_extractor/README.md` (Section: Installation)
- **Build System**: `ocaml_sail_extractor/Makefile` (run `make help`)
- **Python API**: Docstrings in `sail_loader.py`
- **Verification**: `ocaml_sail_extractor/docs/VERIFICATION.md`

## Dependencies

### OCaml Tools (for building)

```bash
# Install via opam
opam install sail dune

# Or use Makefile
cd ocaml_sail_extractor
make deps
```

### Python (for using)

No additional Python dependencies beyond isacomp's existing requirements.

## Troubleshooting

### Build fails with "sail not found"

```bash
cd ocaml_sail_extractor
make deps
```

### Extraction fails with "No such file or directory: .../smt.sail"

Check that SAIL is properly installed:

```bash
opam list | grep sail
# Should show: sail.0.18 or similar
```

### z3 errors during type checking

Install z3 SMT solver:

```bash
# Ubuntu/Debian
sudo apt-get install z3

# macOS
brew install z3
```

## References

- **SAIL Language**: https://github.com/rems-project/sail
- **sail-riscv**: https://github.com/riscv/sail-riscv
- **SAIL Manual**: https://alasdair.github.io/manual.html
- **isacomp**: ../README.md
