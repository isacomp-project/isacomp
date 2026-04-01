# Zarf (H-Machine) ISA Specification for isacomp

This directory contains the isacomp specification for the Zarf ISA, a lazy
functional machine designed to execute programs compiled from functional
languages with lazy evaluation semantics.

## Architecture Overview

Zarf is a **continuation-based, stack-and-heap machine** that implements:
- Lazy evaluation through thunks
- First-class functions (closures)
- Algebraic data types (constructors)
- Pattern matching

### Key Characteristics
- **Word size**: 32 bits
- **Instructions**: 6 core opcodes (including builtin)
- **Built-in operations**: 18 primitives
- **Execution model**: Continuation-passing style

## Directory Structure

```
zarf/
├── README.md               # This file
├── common/
│   ├── state.isa          # Machine state declarations
│   └── info_table.isa     # Info table field extraction
├── aspects/
│   ├── source_decode.isa  # Operand source decoding
│   ├── arg_decode.isa     # Argument word decoding
│   ├── cont_push_case.isa # Push case continuation
│   ├── cont_push_apply.isa# Push apply continuation
│   ├── cont_push_update.isa# Push update continuation
│   ├── cont_push_eval.isa # Push eval continuation
│   ├── cont_pop.isa       # Pop and dispatch continuation
│   ├── heap_alloc.isa     # Heap allocation
│   └── thunk_enter.isa    # Thunk entry
├── instructions/
│   ├── apply.isa          # Opcode 0x1 - Create thunk/apply
│   ├── return.isa         # Opcode 0x2 - Return value
│   ├── case.isa           # Opcode 0x3 - Pattern matching
│   ├── pattern_literal.isa# Opcode 0x4 - Match integer
│   ├── pattern_cons.isa   # Opcode 0x5 - Match constructor
│   └── builtin.isa        # Opcode 0x6 - Built-in primitive
└── builtins/
    ├── error.isa          # 0x00 - Runtime error
    ├── add.isa            # 0x01 - Addition
    ├── sub.isa            # 0x02 - Subtraction
    ├── mult.isa           # 0x03 - Multiplication
    ├── div.isa            # 0x04 - Division
    ├── eq.isa             # 0x05 - Equality
    ├── leq.isa            # 0x06 - Less than or equal
    ├── and.isa            # 0x07 - Bitwise AND
    ├── or.isa             # 0x08 - Bitwise OR
    ├── nand.isa           # 0x09 - Bitwise NAND
    ├── nor.isa            # 0x0A - Bitwise NOR
    ├── xor.isa            # 0x0B - Bitwise XOR
    ├── sll.isa            # 0x0C - Shift left logical
    ├── srl.isa            # 0x0D - Shift right logical
    ├── sra.isa            # 0x0E - Shift right arithmetic
    ├── lt.isa             # 0x0F - Less than
    ├── neg.isa            # 0x12 - Negation
    ├── getint.isa         # 0x80 - Read integer from input
    └── putint.isa         # 0x81 - Write integer to output
```

## Instruction Encoding

### Instruction Word Format (32 bits)
```
[31:29] opcode   - 3 bits (0-5 valid)
[28:19] n        - 10 bits (argument count or skip count)
[18:16] source   - 3 bits (operand source type)
[15:0]  index    - 16 bits (operand index/value)
```

### Opcodes
| Opcode | Binary | Name             | Description                    |
|--------|--------|------------------|--------------------------------|
| 0x1    | 001    | apply            | Create thunk or apply function |
| 0x2    | 010    | return           | Return value from function     |
| 0x3    | 011    | case             | Begin pattern matching         |
| 0x4    | 100    | pattern_literal  | Match integer literal          |
| 0x5    | 101    | pattern_cons     | Match constructor              |
| 0x6    | 110    | builtin          | Execute built-in primitive     |

### Source Types
| Source | Value | Description                          |
|--------|-------|--------------------------------------|
| arg    | 0x0   | Function argument from env_args      |
| freevar| 0x1   | Free variable from env_clo           |
| local  | 0x2   | Local variable from stack            |
| self   | 0x3   | Reserved                             |
| literal| 0x4   | Immediate integer constant           |
| caseVal| 0x5   | Currently scrutinized value          |
| caseFld| 0x6   | Field of scrutinized constructor     |
| itable | 0x7   | Function/info table index            |

### Argument Word Format (follows apply instruction)
```
[31:29] source   - 3 bits (operand source type)
[28:0]  index    - 29 bits (operand index/value)
```

## Memory Layout

### Instruction Memory (imem)
- 32K words (15-bit addressing)
- Contains info tables and function code
- Read-only after program loading

### Heap Memory (heap)
- 1M words (20-bit addressing)
- Contains thunks, closures, constructors
- Managed by free pointer (fp)

### Continuation Stack (cstack)
- 1M words (20-bit addressing)
- Contains continuation frames (5 words each)
- Managed by continuation stack pointer (csp)

### Local Stack (lstack)
- 1M words (20-bit addressing)
- Contains local variables
- Managed by local stack pointer (lsp)

## Continuation Types

| Type | Code | Purpose                              |
|------|------|--------------------------------------|
| Case | 00   | Resume pattern matching              |
| Apply| 01   | Apply excess arguments               |
| Update| 10  | Overwrite thunk with result          |
| Eval | 11   | Continue primitive operation         |

### Continuation Frame Format (5 words)
```
Word 0: [31:30]=type, [29:0]=saved_pc
Word 1: context-specific (env_clo, excess_args_addr, thunk_addr, pending_op)
Word 2: context-specific (env_args, excess_count, reserved, partial_result)
Word 3: [19:0]=saved_lsp
Word 4: [19:0]=saved_lb
```

## Heap Object Formats

### Thunk (unevaluated)
```
Word 0: [31]=0, [30:0]=function_address
Word 1..n: arguments
```

### Constructor / Evaluated Thunk
```
Word 0: [31]=1, [30:16]=arity, [15:0]=tag
Word 1..n: fields / evaluated value
```

## External I/O

- `io_in[31:0]`: External input signal (for getint)
- `io_in_ready[0:0]`: Input available signal
- `io_out[31:0]`: External output signal (for putint)
- `io_out_valid[0:0]`: Output written signal

## Usage

To use this ISA specification with isacomp:

```bash
# Parse and validate
python isacomp/isa_parser.py isacomp/isa/zarf/instructions/apply.isa

# Generate Verilog (when supported)
python isacomp/verilog_generator.py isacomp/isa/zarf/
```

