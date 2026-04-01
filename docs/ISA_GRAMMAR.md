# ISAComp `.isa` File Grammar Specification

This document defines the formal grammar for ISAComp's `.isa` instruction
specification language. All `.isa` files **must** conform to this grammar.
The parser (`isa_parser.py`) is the reference implementation.

## Preprocessing

Before parsing, `.isa` files are run through the C preprocessor (`cpp -P`).
This provides:

- `#include "file.isa"` for file inclusion
- `#define` / `#ifdef` / `#endif` for conditional compilation
- Standard C preprocessing (macro expansion, comments)

The parser also accepts `//` line comments natively.

## Grammar (EBNF)

### Program Structure

```ebnf
program         = { statement } ;

statement       = state_decl
                | mem_decl
                | var_decl
                | fp_var_decl
                | assume_stmt
                | assignment
                | if_stmt
                | for_stmt
                | case_stmt
                | flush_stmt
                | aspect_decl
                | use_stmt
                ;
```

### Declarations

```ebnf
(* Architectural state: registers, flags, PC, register files *)
state_decl      = [ modifier ] "isa_state" [ "cam" ] IDENT
                  ( cam_dims | reg_dims )
                  [ alias_clause ]
                  ";" ;

modifier        = "ext" [ "push" ]
                | "sensitive"
                ;

(* Regular register dimensions: bit-width, then optional array index *)
reg_dims        = bit_range { bit_range } ;

(* CAM dimensions: tag_width @ ways sets *)
cam_dims        = bit_range "@" bracket_dim bracket_dim ;

alias_clause    = "of" expression ;

(* Memory with width inferred from usage *)
mem_decl        = "mem" IDENT bit_range ";" ;

(* Local (temporary) variable — not architecturally visible *)
var_decl        = "var" IDENT bit_range ";" ;

(* Floating-point typed variable *)
fp_var_decl     = fp_type IDENT { "," IDENT } ";" ;

fp_type         = "fp16" | "fp32" | "fp64" | "fp128"
                | "fp16_res" | "fp32_res" | "fp64_res" | "fp128_res"
                | "fpcmp_res"
                ;
```

### Statements

```ebnf
(* Opcode constraint for instruction decoding *)
assume_stmt     = "assume" expression ";" ;

(* Assignment with optional write-enable guard *)
assignment      = lvalue [ "when" "(" expression ")" ] "=" expression ";" ;

lvalue          = expression ;   (* must resolve to a writable target *)

(* If/else — bodies are brace-delimited blocks of statements *)
if_stmt         = "if" "(" expression ")" block [ "else" block ] ;

block           = "{" { statement } "}" ;

(* Compile-time for loop (always fully unrolled) *)
for_stmt        = "for" "(" IDENT ";" integer ";" cmp_op expression ";"
                  inc_op integer ")" block ;

cmp_op          = "<" | ">" ;
inc_op          = "+" | "-" ;

(* Case statement — arms are value : assignment pairs *)
case_stmt       = "case" "(" expression ")" "{" { case_arm } "}" ;

case_arm        = expression ":" assignment ;

(* Cache flush signal *)
flush_stmt      = "flush" IDENT ";" ;

(* Aspect (modular extension) inclusion *)
aspect_decl     = "aspect" file_path [ "gates" gated_list ] ";" ;

file_path       = IDENT { ( "." | "/" ) IDENT } ;

gated_list      = gated_state { "," gated_state } ;
gated_state     = IDENT [ ":" INTEGER ] ;

(* Orthogon use — invokes an orthogon at this point in sequential flow *)
use_stmt        = "use" IDENT "(" expression ")" ";" ;
```

### Expressions

Operator precedence from lowest to highest:

| Prec | Category       | Operators                                 | Assoc |
|------|----------------|-------------------------------------------|-------|
| 1    | Ternary        | `? :`                                     | Right |
| 2    | Logical OR     | `\|\|`                                    | Left  |
| 3    | Logical AND    | `&&`                                      | Left  |
| 4    | Bitwise OR     | `\|`                                      | Left  |
| 5    | Bitwise XOR    | `^`                                       | Left  |
| 6    | Bitwise AND    | `&`                                       | Left  |
| 7    | Equality       | `==` `!=`                                 | Left  |
| 8    | Comparison     | `<` `>` `<=` `>=` `<s` `>s` `<=s` `>=s`  | Left  |
| 9    | Shift          | `<<` `>>` `>>>`                           | Left  |
| 10   | Additive       | `+` `-`                                   | Left  |
| 11   | Multiplicative | `*` `/` `/s` `%` `%s`                    | Left  |
| 12   | Unary          | `~` `-` `!` (prefix `\|` `&` `^` reduce) | Right |
| 13   | Postfix        | `[i]` `[h:l]` `@[k]`                     | Left  |
| 14   | Primary        | literals, identifiers, calls, `{}`        | —     |

```ebnf
expression      = ternary_expr ;

ternary_expr    = logical_or [ "?" logical_or ":" ternary_expr ] ;

logical_or      = logical_and  { "||" logical_and } ;
logical_and     = bitwise_or   { "&&" bitwise_or } ;
bitwise_or      = bitwise_xor  { "|" bitwise_xor } ;
bitwise_xor     = bitwise_and  { "^" bitwise_and } ;
bitwise_and     = equality     { "&" equality } ;
equality        = comparison   { ( "==" | "!=" ) comparison } ;
comparison      = shift        { cmp_operator shift } ;
shift           = additive     { ( "<<" | ">>" | ">>>" ) additive } ;
additive        = multiplicative { ( "+" | "-" ) multiplicative } ;
multiplicative  = unary        { ( "*" | "/" | "/s" | "%" | "%s" ) unary } ;

cmp_operator    = "<" | ">" | "<=" | ">=" | "<s" | ">s" | "<=s" | ">=s" ;

unary           = ( "~" | "-" | "!" ) unary         (* standard unary *)
                | ( "|" | "&" | "^" ) unary          (* reduction operators *)
                | postfix
                ;

postfix         = primary { postfix_op } ;

postfix_op      = "[" expression "]"                  (* array access *)
                | "[" expression ":" expression "]"   (* bit slice *)
                | "@" "[" expression "]"              (* CAM lookup *)
                ;

primary         = INTEGER
                | HEX_LITERAL                         (* 0xNN *)
                | VERILOG_HEX                         (* W'hDD *)
                | VERILOG_BIN                         (* W'bDD *)
                | VERILOG_DEC                         (* W'dDD *)
                | BINARY_WILDCARD                     (* 0b01** *)
                | IDENT [ "(" arg_list ")" ]          (* variable or function call *)
                | "(" expression ")"                  (* grouping *)
                | "{" concat_or_repeat "}"            (* concatenation / repetition *)
                | builtin_call
                | fp_call
                ;

concat_or_repeat = INTEGER "{" expression "}"         (* repetition: {N{expr}} *)
                 | expression { "," expression }      (* concatenation: {a, b} *)
                 ;

builtin_call    = ( "ctz" | "clz" ) "(" expression ")" ;

fp_call         = FP_INTRINSIC "(" arg_list ")" ;

(* FP_INTRINSIC is any name registered in fp_intrinsics.py.
   Single-precision: fp_add  fp_sub  fp_mul  fp_div  fp_sqrt
                     fp_fmadd  fp_fmsub  fp_fnmadd  fp_fnmsub
                     fp_sgnj  fp_sgnjn  fp_sgnjx
                     fp_min  fp_max
                     fp_eq  fp_lt  fp_le  fp_class
                     fp_cvt_w_s  fp_cvt_wu_s  fp_cvt_s_w  fp_cvt_s_wu
                     fp_cvt_l_s  fp_cvt_lu_s  fp_cvt_s_l  fp_cvt_s_lu
   Double-precision: fp_add_d  fp_sub_d  fp_mul_d  fp_div_d  fp_sqrt_d
                     fp_fmadd_d  fp_fmsub_d  fp_fnmadd_d  fp_fnmsub_d
                     fp_min_d  fp_max_d
                     fp_eq_d  fp_lt_d  fp_le_d  fp_class_d
                     fp_cvt_w_d  fp_cvt_wu_d  fp_cvt_d_w  fp_cvt_d_wu
                     fp_cvt_l_d  fp_cvt_lu_d  fp_cvt_d_l  fp_cvt_d_lu
                     fp_cvt_s_d  fp_cvt_d_s
   Most intrinsics take an optional trailing rounding-mode argument
   (3-bit value: 000=RNE, 001=RTZ, 010=RDN, 011=RUP, 100=RMM). *)

arg_list        = expression { "," expression } ;
```

### Dimension Specifications

```ebnf
bit_range       = "[" INTEGER ":" INTEGER "]" ;

bracket_dim     = "[" [ INTEGER ":" INTEGER ] "]" ;   (* empty [] = 1 entry *)
```

### Lexical Elements

```ebnf
INTEGER         = DIGIT { DIGIT } ;
HEX_LITERAL     = "0x" HEX_DIGIT { HEX_DIGIT } ;
VERILOG_HEX     = INTEGER "'h" HEX_DIGIT { HEX_DIGIT } ;
VERILOG_BIN     = INTEGER "'b" BIN_DIGIT { BIN_DIGIT } ;
VERILOG_DEC     = INTEGER "'d" DIGIT { DIGIT } ;
BINARY_WILDCARD = "0b" ( BIN_DIGIT | "*" ) { BIN_DIGIT | "*" } ;
IDENT           = ( LETTER | "_" ) { LETTER | DIGIT | "_" } ;

COMMENT         = "//" { any character except newline } ;
```

## AST Node Types (Canonical)

Every expression parsed by the parser produces a dictionary with a `'type'`
key. These are the **only** valid AST node types:

| AST `type`           | Required Keys                                        | Description                       |
|----------------------|------------------------------------------------------|-----------------------------------|
| `literal`            | `value`                                              | Plain integer (e.g. `42`, `0xFF`) |
| `sized_literal`      | `value`, `width`, `format`                           | Sized literal (`W'bDD`, `W'hDD`, `W'dDD`). `format` is `'bin'`, `'hex'`, or `'dec'`. |
| `binary_wildcard`    | `pattern`, `width`, `fixed_value`, `wildcard_positions`, `original` | Wildcard pattern (e.g. `0b01**`) |
| `identifier`         | `name`                                               | Variable / state name             |
| `binary_op`          | `operator`, `left`, `right`                          | Binary operation                  |
| `unary_op`           | `operator`, `operand`                                | Unary prefix operation            |
| `reduction_op`       | `operator`, `operand`                                | Bitwise reduction (`\|x`, `&x`, `^x`) |
| `ternary_op`         | `condition`, `if_true`, `if_false`                   | Ternary `cond ? a : b`           |
| `array_access`       | `target`, `index`                                    | Array read/write (`rf[rs1]`)      |
| `bit_slice`          | `target`, `range` (tuple: high, low)                 | Bit extraction (`x[7:0]`)        |
| `concatenation`      | `parts`                                              | Bit concatenation (`{a, b}`)      |
| `repetition`         | `count`, `expression`                                | Bit replication (`{N{expr}}`)     |
| `function_call`      | `name`, `args`                                       | Builtin call (`ctz`, `clz`)       |
| `fp_intrinsic_call`  | `intrinsic`, `operands`, `rounding_mode`             | FP intrinsic (e.g. `fp_add`)      |
| `cam_lookup`         | `target`, `key`, `set_index?`, `cam_name?`, `cam_info?` | CAM associative lookup         |

### Key Naming Conventions

- **`target`** is used consistently for the base object being accessed
  (array access, bit slice, CAM lookup).
- **`parts`** is used for the sub-expressions in a concatenation.
- **`if_true` / `if_false`** are used for ternary branches (never
  `true_expr`/`false_expr` or `true_value`/`false_value`).
- **`sized_literal`** unifies the old `binary_literal`, `decimal_literal`,
  `verilog_hex_literal`, and `verilog_dec_literal` types.

## Semantics Overview

### Execution Model

Statements execute **sequentially** within an instruction. Each `.isa` file
describes one instruction's complete datapath from fetch through writeback.
The sequential order determines data dependencies.

### Architectural State vs. Variables

- **`isa_state`** declares persistent, architecturally-visible state (PC,
  register files, flags, memory). Writes to `isa_state` produce hardware
  register updates.
- **`var`** declares a temporary wire/signal. Variables exist only within
  the instruction and are optimized away if unused.
- **`mem`** declares a memory whose data width is inferred from access
  patterns.

### Conditional Writes (`when`)

```
rf[rd] when (rd != 0) = result;
```

The `when` clause gates the write-enable. If the condition is false, the
target retains its previous value. This is the primary mechanism for
conditional register updates.

### Assume (Decode Constraints)

```
assume instr[6:0] == 0b0110011;
```

`assume` statements constrain instruction fields to specific values. During
graph merging, these constraints form the instruction decode tree.

### For Loops

For loops are **always unrolled at parse time**. The loop variable is
substituted as a literal into each iteration's body. This is used for
vector/SIMD operations and multi-word memory accesses.

### Aspects

```
aspect interrupts.isa gates pc, dmem;
```

Aspects are modular extensions (e.g., interrupt handling, MMU) that can
conditionally override specified architectural state. The `gates` clause
lists which state the aspect is allowed to modify.

## Examples

### Minimal Instruction (RISC-V ADD)

```
isa_state pc[31:0];
var instr[31:0];
isa_state rf[31:0][4:0];
mem umem[12:0];

var rs1[4:0];
var rs2[4:0];
var rd[4:0];
var r1[31:0];
var r2[31:0];
var res[31:0];

instr = umem[pc];
assume instr[6:0] == 0b0110011;
assume instr[14:12] == 0x0;
assume instr[31:25] == 0x00;
pc = pc + 4;

rs1 = instr[19:15];
rs2 = instr[24:20];
rd = instr[11:7];

r1 = rf[rs1];
r2 = rf[rs2];

res = r1 + r2;

rf[rd] when (rd != 0) = res;
```

### Sign Extension with Concatenation

```
var imm[12:0] = {instr[31], instr[7], instr[30:25], instr[11:8], 1'b0};
var sign_ext_imm[31:0] = {{19{imm[12]}}, imm};
```

### Conditional Write with Complex Guard

```
mepc when (exception_taken & delegate_to_mmode) = pc;
sepc when (exception_taken & delegate_to_smode) = pc;
```

---

## Orthogon File Grammar

Orthogon files define a **dimension of variation** that can be factored out
of multiple instructions. Each orthogon lives in its own `.isa` file and is
invoked via `use` statements in instruction files.

Orthogons are distinct from aspects:
- **Aspects** cross-cut instructions (one aspect applies to all instructions)
  and use priority-override semantics.
- **Orthogons** factor within instructions (many instructions share the same
  orthogon) and use mux-select semantics.
- Aspects cannot include orthogons, and orthogons cannot include aspects.

### Orthogon File Structure

```ebnf
orthogon_file   = "orthogon" IDENT "{" orthogon_body "}" ;

orthogon_body   = selector_decl
                  [ uses_block ]
                  provides_block
                  [ writes_block ]
                  { variant_decl }
                  ;

(* The mux select signal — its value picks the active variant *)
selector_decl   = "selector" IDENT bit_range ";" ;

(* State the orthogon reads. Must exist in the host instruction. *)
uses_block      = "uses" "{" { state_decl } "}" ;

(* Named output values the orthogon computes for the host. *)
provides_block  = "provides" "{" { IDENT bit_range ";" } "}" ;

(* State the orthogon modifies as a side effect (read-write). *)
writes_block    = "writes" "{" { state_decl } "}" ;

(* Each variant: a named implementation for one selector value. *)
variant_decl    = "variant" IDENT ":" expression "{" { statement } "}" ;
```

### Use Statement (in instruction files)

```ebnf
use_stmt        = "use" IDENT "(" expression ")" ";" ;
```

The identifier names the orthogon. The expression is bound to the orthogon's
selector signal.

### Semantics

**Selector**: A signal whose value determines which variant is active. The
selector expression at the `use` site becomes the mux select input in
hardware. Variant match conditions must be non-overlapping.

**`uses`**: Architectural state the orthogon reads (read-only from the
orthogon's perspective). At the use site, the compiler verifies each `uses`
name exists in the host instruction with matching width. The orthogon sees
the current intermediate value at the point of invocation.

**`provides`**: Named output values the orthogon computes. Every variant
must assign to every `provides` value. At the use site, these are injected
as `var` declarations into the host instruction's scope. In the compiled
graph, each becomes a mux node with the selector as its select input.

**`writes`**: Architectural state the orthogon modifies as a side effect
(e.g., advancing PC past operand bytes). The orthogon can both read and
write these. Every variant must produce a final value for each `writes`
state. At the use site, this creates an intermediate value — subsequent host
reads see the post-orthogon value. The host can further modify these states
after the `use`.

**Variants**: Each variant declares a selector match condition and a body of
ISA statements. Local `var` declarations are scoped to the variant. The body
uses the same statement grammar as regular `.isa` files (assignments,
if/case, etc.), except `assume`, `aspect`, and `use` are not allowed inside
variants.

### Compilation

When the compiler processes `use orthogon_name(selector_expr);`:

1. Each variant's body is expanded into a subgraph, with node IDs prefixed
   by `{orthogon_name}_{variant_name}_` to avoid collisions.
2. For each `provides` output, a mux node is created with `selector_expr`
   as the select input and each variant's assignment as a data input.
3. For each `writes` state, a mux node is created similarly. The mux output
   becomes the new intermediate value for that state.
4. The `provides` values are injected as variables into the host scope.

When the graph merger merges multiple instructions that `use` the same
orthogon with the same selector expression, the orthogon's mux trees are
recognized as structurally identical and shared — eliminating the
duplication that currently plagues ISAs with complex addressing modes.

### Orthogon Example (6502 Addressing Modes)

```
orthogon addr_mode {
    selector sel[3:0];

    uses {
        isa_state mainmem[7:0][15:0];
        isa_state X[7:0];
        isa_state Y[7:0];
    }

    provides {
        data[7:0];
        eff_addr[15:0];
    }

    writes {
        isa_state pc[15:0];
    }

    variant imm : sel == 4'd0 {
        var imm_val[7:0];
        imm_val = mainmem[pc];
        pc = pc + 1;
        data = imm_val;
        eff_addr = 16'h0000;
    }

    variant abs : sel == 4'd2 {
        var lo[7:0];
        var hi[7:0];
        lo = mainmem[pc];
        pc = pc + 1;
        hi = mainmem[pc];
        pc = pc + 1;
        eff_addr = {hi, lo};
        data = mainmem[eff_addr];
    }
}
```

### Use Site Example

```
// adc.isa — single file for all ADC addressing mode variants
isa_state pc[15:0];
isa_state A[7:0];
isa_state mainmem[7:0][15:0];
// ... flag declarations ...

var instr[7:0];
instr = mainmem[pc];
assume instr[1:0] == 2'b01;       // group 1 (ALU ops)
assume instr[7:5] == 3'b011;      // ADC family
pc = pc + 1;

var addr_sel[3:0];
addr_sel = {1'b0, instr[4:2]};    // bits [4:2] encode addressing mode

use addr_mode(addr_sel);           // data and eff_addr now in scope

var result[8:0];
result = A + data + flag_C;        // ADC logic written ONCE
flag_N = result[7];
flag_Z = result[7:0] == 0 ? 1'b1 : 1'b0;
flag_C = result[8];
flag_V = (result[7] ^ A[7]) & (result[7] ^ data[7]);
A = result[7:0];
```
