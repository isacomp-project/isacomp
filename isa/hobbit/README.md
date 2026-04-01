# AT&T Hobbit (ATT92010) ISA Specification

## Architecture Overview

The AT&T Hobbit (ATT92010) is a 32-bit microprocessor derived from AT&T Bell
Laboratories' CRISP (C-language Reduced Instruction Set Processor) architecture.
It is a "2½ address memory-to-memory machine" with no user-visible general-purpose
registers, using a hardware-managed stack cache instead.

## Key Features

- **Word size**: 32 bits
- **Data types**: Signed/unsigned bytes (8-bit), half-words (16-bit), words (32-bit)
- **Endianness**: Selectable big-endian or little-endian per mode
- **Stack cache**: 64 entries x 32 bits (256 bytes), circular buffer
- **No general-purpose registers**: Stack cache maps top of stack into fast storage
- **Variable-length instructions**: 2, 6, or 10 bytes (1, 3, or 5 16-bit parcels)
- **Instruction format**: `instruction src, dst` (src is first operand)
- **2½-address mode**: Instructions with `3` suffix store result in accumulator (top of stack)

## Architectural State

| Register | Width | Description |
|----------|-------|-------------|
| PC       | 32-bit (bit 0 always 0) | Program counter |
| SP       | 28-bit (quad-aligned) | Stack pointer (top of stack) |
| MSP      | 28-bit (quad-aligned) | Maximum stack pointer (above highest cached entry) |
| ISP      | 28-bit (quad-aligned) | Interrupt stack pointer |
| PSW      | 32-bit | Program status word |
| CONFIG   | 32-bit | Configuration register |
| SHAD     | 28-bit (quad-aligned) | Shadow register (copy of CSP) |
| VB       | 28-bit (quad-aligned) | Vector base |
| STB      | 32-bit | Segment table base |
| FAULT    | 32-bit | Fault register |
| TIMER1   | 32-bit | Timer 1 |
| TIMER2   | 32-bit | Timer 2 |

## PSW Bits

| Bit | Name | Description |
|-----|------|-------------|
| 16  | V/P  | Virtual/Physical addressing mode |
| 15  | UL   | User little-endian |
| 14:12 | IPL | Interrupt priority level |
| 11  | E    | Enter guard |
| 10  | EL   | Execution level (0=kernel, 1=user) |
| 9   | CSP  | Current stack pointer (0=ISP, 1=SP) |
| 8   | TBB  | Trace basic block |
| 7   | TI   | Trace instruction |
| 6   | V    | Overflow |
| 5   | C    | Carry |
| 4   | F    | Flag (set by CMP, TADD, TSUB, TESTC, TESTV) |
| 3:0 | -    | Reserved |

## Stack Cache Model

The stack cache is accessed via stack-offset addressing: `CSP + offset`. The
accumulator is the word at `CSP + 4` (i.e., one word above the current stack
pointer). In these ISA specifications, the stack cache is modeled as memory and
accessed via computed addresses from SP.

## Addressing Modes

| Code | Mode | Description |
|------|------|-------------|
| 0x0  | *$addr:B | Byte absolute |
| 0x1  | *$addr:UB | Unsigned byte absolute |
| 0x2  | *$addr:H | Half-word absolute |
| 0x3  | *$addr:UH | Unsigned half-word absolute |
| 0x4  | Roffset:B | Byte stack offset |
| 0x5  | Roffset:UB | Unsigned byte stack offset |
| 0x6  | Roffset:H | Half-word stack offset |
| 0x7  | Roffset:UH | Unsigned half-word stack offset |
| 0x8  | *Roffset:B | Byte stack offset indirect |
| 0x9  | *Roffset:UB | Unsigned byte stack offset indirect |
| 0xA  | *Roffset:H | Half-word stack offset indirect |
| 0xB  | *Roffset:UH | Unsigned half-word stack offset indirect |
| 0xC  | *$addr:W | Word absolute |
| 0xD  | Roffset:W | Word stack offset |
| 0xE  | *Roffset:W | Word stack offset indirect |
| 0xF  | $data | Immediate |

## Instruction Encoding

### One-Parcel (2 bytes)
- Bit 15 = 0
- Encodes zero, one, or two operand instructions with 5-bit fields
- 5-bit stack offsets are zero-extended and multiplied by 4

### Three-Parcel (6 bytes)
- Bits 15:14 = 10
- Bits 13:8 = opcode
- Bits 7:4 = source mode, Bits 3:0 = destination mode (dyadic)
- 16-bit source/destination fields sign-extended to 32 bits

### Five-Parcel (10 bytes)
- Bits 15:14 = 11
- Same opcode/mode layout as three-parcel
- Full 32-bit source and destination fields

## Instruction Set Summary

| Instruction | Type | Description |
|-------------|------|-------------|
| ADD[3] | Arithmetic | Add |
| ADDI | Arithmetic | Add interlocked (atomic) |
| AND[3] | Logical | Bitwise AND |
| ANDI | Logical | Bitwise AND interlocked |
| CALL | Control | Call subroutine |
| CATCH | Control | Fill stack cache |
| CLRE | Other | Clear PSW enter guard bit |
| CMPEQ | Compare | Equality comparison |
| CMPGT | Compare | Signed greater than |
| CMPHI | Compare | Unsigned greater than (high) |
| CPU | Other | Register access escape prefix |
| CRET | Control | Context return from kernel |
| DIV[3] | Arithmetic | Signed divide |
| DQM | Move | Double/quad-word move |
| ENTER | Control | Enter subroutine (allocate frame) |
| FLUSHD | Other | Flush data cache |
| FLUSHDCE | Other | Flush data cache entry |
| FLUSHI | Other | Flush decoded instruction cache |
| FLUSHP | Other | Flush prefetch buffer |
| FLUSHPBE | Other | Flush prefetch buffer entry |
| FLUSHPTE | Other | Flush page table entry from TLBs |
| JMP | Control | Unconditional jump |
| JMPFN/JMPFY | Control | Jump if flag false (not-taken/taken hint) |
| JMPTN/JMPTY | Control | Jump if flag true (not-taken/taken hint) |
| KCALL | Control | Kernel call |
| KRET | Control | Kernel return |
| LDRAA | Move | Load relative address into accumulator |
| MOV | Move | Move data |
| MOVA | Move | Move address |
| MUL[3] | Arithmetic | Multiply |
| NOP | Other | No operation |
| OR[3] | Logical | Bitwise OR |
| ORI | Logical | Bitwise OR interlocked |
| POPN | Control | Free n entries from stack |
| REM[3] | Arithmetic | Signed remainder |
| RETURN | Control | Return from subroutine |
| SHL[3] | Shift | Shift left |
| SHR[3] | Shift | Arithmetic shift right |
| SUB[3] | Arithmetic | Subtract |
| TADD | Tagged | Tagged addition |
| TESTC | Other | Test PSW carry, copy to flag |
| TESTV | Other | Test PSW overflow, copy to flag |
| TSUB | Tagged | Tagged subtraction |
| UDIV | Arithmetic | Unsigned divide |
| UREM | Arithmetic | Unsigned remainder |
| USHR[3] | Shift | Logical shift right |
| XOR[3] | Logical | Bitwise exclusive OR |

## ISA Specification Notes

These `.isa` files model the Hobbit using stack-offset word addressing mode
(mode 0xD) for simplicity, which is the most commonly used mode. Each
instruction file models one specific encoding variant. The stack cache is
represented as regular memory accessed via SP-relative addresses.

