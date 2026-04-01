#!/usr/bin/env python3
"""
Simple assembler for the AT&T Hobbit (ATT92010) microprocessor.

Supports the subset of the instruction set modeled by the isacomp .isa files:
one-parcel (2-byte) and three-parcel (6-byte) encodings with stack-offset
word addressing mode.

Assembly syntax (AT&T style):
    ADD   R8, R12          ; add stack[SP+8] to stack[SP+12], result in R12
    ADD3  R8, R12          ; add stack[SP+8] + stack[SP+12], result in Acc (R4)
    ADD   $5, R8           ; add immediate 5 to stack[SP+8]
    MOV   R8, R12          ; move stack[SP+8] to stack[SP+12]
    MOV   $0, R8           ; move immediate 0 to stack[SP+8]
    CMPEQ $0, R8           ; compare immediate 0 == stack[SP+8], set PSW.F
    CMPGT R8, R12          ; compare stack[SP+8] >s stack[SP+12], set PSW.F
    JMP   label            ; unconditional PC-relative jump
    JMPTY label            ; jump if PSW.F==1, predict taken
    JMPFN label            ; jump if PSW.F==0, predict not taken
    CALL  label            ; call subroutine
    ENTER R-N              ; allocate N bytes of stack frame (negative offset)
    RETURN RN              ; return, deallocate N bytes
    CATCH RN               ; refill stack cache
    POPN  RN               ; pop N entries
    NOP                    ; no operation
    TESTC                  ; PSW.F = PSW.C; PSW.C = 0
    TESTV                  ; PSW.F = PSW.V; PSW.V = 0
    CLRE                   ; clear PSW enter guard bit

Stack offsets: R0=SP+0 (PC save area), R4=SP+4 (accumulator), R8, R12, ...
               Rn means SP + n (must be word-aligned, i.e., multiple of 4)

Usage:
    python3 hobbit_asm.py input.s -o output.hex
    python3 hobbit_asm.py input.s -o output.hex --base 0x1000
"""

import sys
import argparse
import re
from pathlib import Path


class HobbitAssembler:
    """Assembler for ATT92010 Hobbit one-parcel and three-parcel instructions."""

    def __init__(self, base_addr=0):
        self.base_addr = base_addr
        self.labels = {}
        self.code = []  # list of (addr, bytes_list, source_line)
        self.pc = base_addr

    def _parse_reg(self, s):
        """Parse a stack offset register like R4, R8, R12, R-16, etc.
        Returns the byte offset (must be word-aligned)."""
        s = s.strip()
        m = re.match(r'^R(-?\d+)$', s, re.IGNORECASE)
        if not m:
            raise ValueError(f"Invalid register/offset: {s}")
        val = int(m.group(1))
        return val

    def _parse_stk5(self, s):
        """Parse a 5-bit word-aligned stack offset (R0..R124).
        Returns the 5-bit field value (offset / 4)."""
        offset = self._parse_reg(s)
        if offset < 0 or offset > 124 or offset % 4 != 0:
            raise ValueError(f"Stack offset {offset} out of range for 5-bit field (0..124, word-aligned)")
        return offset // 4

    def _parse_imm5(self, s):
        """Parse a 5-bit signed immediate ($-16..$15)."""
        s = s.strip()
        if not s.startswith('$'):
            raise ValueError(f"Expected immediate (starting with $): {s}")
        val = int(s[1:], 0)
        if val < -16 or val > 15:
            raise ValueError(f"Immediate {val} out of range for 5-bit signed (-16..15)")
        return val & 0x1F

    def _parse_uimm5(self, s):
        """Parse a 5-bit unsigned immediate ($0..$31)."""
        s = s.strip()
        if not s.startswith('$'):
            raise ValueError(f"Expected immediate: {s}")
        val = int(s[1:], 0)
        if val < 0 or val > 31:
            raise ValueError(f"Immediate {val} out of range for 5-bit unsigned (0..31)")
        return val & 0x1F

    def _parse_stk8(self, s):
        """Parse an 8-bit stack offset for ENTER/RETURN/CATCH/POPN.
        For ENTER: the offset is negative, left-padded with ones, *16
        For RETURN/CATCH/POPN: zero-extended, *16"""
        offset = self._parse_reg(s)
        return offset

    def _encode_one_parcel(self, opcode5, src5, dst5):
        """Encode a one-parcel (2-byte) instruction.
        Format: 0 | opcode[4:0] | src[4:0] | dst[4:0]
        Bit 15 = 0."""
        word = ((opcode5 & 0x1F) << 10) | ((src5 & 0x1F) << 5) | (dst5 & 0x1F)
        return [(word >> 8) & 0xFF, word & 0xFF]

    def _encode_one_parcel_niladic(self, subcode):
        """Encode a niladic one-parcel instruction.
        Format: 0 | 0x0B[4:0] | subcode[9:0]
        opcode = 0x0B for niladic type."""
        word = (0x0B << 10) | (subcode & 0x3FF)
        return [(word >> 8) & 0xFF, word & 0xFF]

    def _encode_one_parcel_stack(self, subcode2, offset8):
        """Encode a stack one-parcel instruction (ENTER/CATCH/RETURN/POPN).
        Format: 0 | 0x02[4:0] | subcode[1:0] | offset[7:0]"""
        word = (0x02 << 10) | ((subcode2 & 0x3) << 8) | (offset8 & 0xFF)
        return [(word >> 8) & 0xFF, word & 0xFF]

    def _encode_one_parcel_flow(self, opcode5, offset10):
        """Encode a one-parcel flow instruction (JMP/CALL with PC-relative offset).
        Format: 0 | opcode[4:0] | offset[9:0]
        The 10-bit offset is sign-extended and multiplied by 2."""
        word = ((opcode5 & 0x1F) << 10) | (offset10 & 0x3FF)
        return [(word >> 8) & 0xFF, word & 0xFF]

    def _encode_three_parcel(self, opcode6, smode, dmode, src16, dst16):
        """Encode a three-parcel (6-byte) instruction.
        Parcel 0: 10 | opcode[5:0] | smode[3:0] | dmode[3:0]
        Parcel 1: source[15:0]
        Parcel 2: destination[15:0]"""
        p0 = (0b10 << 14) | ((opcode6 & 0x3F) << 8) | ((smode & 0xF) << 4) | (dmode & 0xF)
        p1 = src16 & 0xFFFF
        p2 = dst16 & 0xFFFF
        return [
            (p0 >> 8) & 0xFF, p0 & 0xFF,
            (p1 >> 8) & 0xFF, p1 & 0xFF,
            (p2 >> 8) & 0xFF, p2 & 0xFF,
        ]

    def _calc_pcrel10(self, target_addr, instr_addr):
        """Calculate 10-bit PC-relative offset for one-parcel flow instructions.
        offset = (target - pc) / 2, must fit in 10-bit signed."""
        diff = target_addr - instr_addr
        if diff % 2 != 0:
            raise ValueError(f"PC-relative offset {diff} not parcel-aligned")
        field = diff // 2
        if field < -512 or field > 511:
            raise ValueError(f"PC-relative offset {diff} out of range for 10-bit field")
        return field & 0x3FF

    def assemble_line(self, line, pass_num):
        """Assemble a single line. pass_num: 1 = collect labels, 2 = emit code."""
        # Strip comments
        line = re.sub(r';.*$', '', line).strip()
        if not line:
            return

        # Label?
        m = re.match(r'^(\w+):(.*)$', line)
        if m:
            label = m.group(1)
            if pass_num == 1:
                self.labels[label] = self.pc
            line = m.group(2).strip()
            if not line:
                return

        # Parse mnemonic and operands
        parts = line.split(None, 1)
        mnem = parts[0].upper()
        operands = parts[1].strip() if len(parts) > 1 else ''
        ops = [o.strip() for o in operands.split(',')] if operands else []

        size = self._get_instruction_size(mnem, ops)

        if pass_num == 2:
            encoded = self._encode_instruction(mnem, ops)
            self.code.append((self.pc, encoded, line))

        self.pc += size

    def _get_instruction_size(self, mnem, ops):
        """Return instruction size in bytes."""
        # Niladic instructions (2 bytes)
        if mnem in ('NOP', 'TESTC', 'TESTV', 'CLRE', 'FLUSHI', 'FLUSHP',
                     'KRET', 'CRET'):
            return 2
        # Stack instructions (2 bytes)
        if mnem in ('ENTER', 'RETURN', 'CATCH', 'POPN'):
            return 2
        # Flow control with PC-relative (2 bytes for short form)
        if mnem in ('JMP', 'JMPFN', 'JMPFY', 'JMPTN', 'JMPTY', 'CALL'):
            return 2
        # One-parcel ALU (2 bytes) - when both operands are small
        if mnem in ('ADD', 'ADD3', 'MOV', 'MOVA', 'AND', 'AND3',
                     'CMPEQ', 'CMPGT', 'SHL3', 'SHR3') and len(ops) == 2:
            # Check if operands fit in one-parcel
            try:
                src = ops[0].strip()
                dst = ops[1].strip()
                if src.startswith('$'):
                    self._parse_imm5(src)
                    self._parse_stk5(dst)
                    return 2
                elif src.upper().startswith('R') and dst.upper().startswith('R'):
                    self._parse_stk5(src)
                    self._parse_stk5(dst)
                    return 2
            except ValueError:
                pass
            # Fall through to 6-byte encoding
            return 6
        # Three-parcel general (6 bytes) for everything else
        if mnem in ('SUB', 'SUB3', 'MUL', 'MUL3', 'DIV', 'DIV3',
                     'REM', 'REM3', 'UDIV', 'UREM', 'OR', 'OR3',
                     'XOR', 'XOR3', 'SHL', 'SHR', 'USHR', 'USHR3',
                     'CMPHI', 'ADDI', 'ANDI', 'ORI', 'DQM',
                     'TADD', 'TSUB', 'LDRAA'):
            return 6
        # KCALL one-parcel (2 bytes)
        if mnem == 'KCALL':
            return 2
        # Default for unknown
        return 6

    def _encode_instruction(self, mnem, ops):
        """Encode an instruction into bytes."""
        # === Niladic ===
        if mnem == 'NOP':
            return self._encode_one_parcel_niladic(0x100)  # instr[9:7]=0b010
        if mnem == 'TESTV':
            return self._encode_one_parcel_niladic(0x080)  # instr[9:7]=0b001, instr[6:3]=0b0000
        if mnem == 'TESTC':
            return self._encode_one_parcel_niladic(0x240)  # instr[9:6]=0b1001
        if mnem == 'CLRE':
            return self._encode_one_parcel_niladic(0x00A)
        if mnem == 'FLUSHI':
            return self._encode_one_parcel_niladic(0x003)
        if mnem == 'FLUSHP':
            return self._encode_one_parcel_niladic(0x004)
        if mnem == 'KRET':
            return self._encode_one_parcel_niladic(0x041)  # subcode 001_0000000_001
        if mnem == 'CRET':
            return self._encode_one_parcel_niladic(0x005)

        # === Stack frame instructions ===
        if mnem == 'ENTER':
            offset = self._parse_reg(ops[0])
            # Must be negative, quad-aligned
            if offset >= 0:
                raise ValueError("ENTER offset must be negative")
            # Encode: left-pad ones, divide by 16
            raw = (-offset) // 16
            if raw < 1 or raw > 255:
                raise ValueError(f"ENTER offset {offset} out of range")
            return self._encode_one_parcel_stack(0b00, raw & 0xFF)

        if mnem == 'RETURN':
            offset = self._parse_reg(ops[0])
            if offset < 0:
                raise ValueError("RETURN offset must be non-negative")
            raw = offset // 16
            return self._encode_one_parcel_stack(0b10, raw & 0xFF)

        if mnem == 'CATCH':
            offset = self._parse_reg(ops[0])
            raw = offset // 16
            return self._encode_one_parcel_stack(0b01, raw & 0xFF)

        if mnem == 'POPN':
            offset = self._parse_reg(ops[0])
            raw = offset // 16
            return self._encode_one_parcel_stack(0b11, raw & 0xFF)

        # === Flow control ===
        flow_opcodes = {
            'JMP': 0x03, 'JMPFN': 0x04, 'JMPFY': 0x05,
            'JMPTN': 0x06, 'JMPTY': 0x07, 'CALL': 0x01,
        }
        if mnem in flow_opcodes:
            target_label = ops[0].strip()
            if target_label in self.labels:
                offset10 = self._calc_pcrel10(self.labels[target_label], self.pc)
            else:
                # Try numeric
                target = int(target_label, 0)
                offset10 = self._calc_pcrel10(target, self.pc)
            return self._encode_one_parcel_flow(flow_opcodes[mnem], offset10)

        # === KCALL ===
        if mnem == 'KCALL':
            src = ops[0].strip()
            if src.startswith('$'):
                val = int(src[1:], 0)
                # Zero-extend, divide by 4
                field = val // 4
                return self._encode_one_parcel_flow(0x00, field & 0x3FF)
            raise ValueError("KCALL requires immediate operand")

        # === One-parcel dyadic/monadic ===
        one_parcel_opcodes_ss = {
            'ADD': 0x16, 'ADD3': 0x17, 'MOV': 0x18, 'AND': 0x0F,
            'CMPGT': 0x11, 'MOVA': 0x1D,
        }
        one_parcel_opcodes_cs = {
            'ADD': 0x14, 'ADD3': 0x15, 'MOV': 0x1C, 'AND3': 0x0E,
            'CMPEQ': 0x10, 'CMPGT': 0x12, 'SHL3': 0x1E, 'SHR3': 0x1F,
        }

        if len(ops) == 2:
            src_s = ops[0].strip()
            dst_s = ops[1].strip()

            # Try immediate, stack (one-parcel)
            if src_s.startswith('$') and mnem in one_parcel_opcodes_cs:
                try:
                    if mnem in ('SHL3', 'SHR3'):
                        imm = self._parse_uimm5(src_s)
                    else:
                        imm = self._parse_imm5(src_s)
                    stk = self._parse_stk5(dst_s)
                    return self._encode_one_parcel(one_parcel_opcodes_cs[mnem], imm, stk)
                except ValueError:
                    pass  # fall through to 3-parcel

            # Try stack, stack (one-parcel)
            if not src_s.startswith('$') and mnem in one_parcel_opcodes_ss:
                try:
                    src5 = self._parse_stk5(src_s)
                    dst5 = self._parse_stk5(dst_s)
                    return self._encode_one_parcel(one_parcel_opcodes_ss[mnem], src5, dst5)
                except ValueError:
                    pass  # fall through to 3-parcel

        # === Three-parcel general ===
        three_parcel_opcodes = {
            'ADD': 0x23, 'ADD3': 0x33, 'SUB': 0x20, 'SUB3': 0x30,
            'MUL': 0x26, 'MUL3': 0x36, 'DIV': 0x27, 'DIV3': 0x37,
            'REM': 0x25, 'REM3': 0x35, 'UDIV': 0x2F, 'UREM': 0x05,
            'AND': 0x22, 'AND3': 0x32, 'OR': 0x21, 'OR3': 0x31,
            'XOR': 0x24, 'XOR3': 0x34,
            'SHL': 0x2E, 'SHL3': 0x3E, 'SHR': 0x2C, 'SHR3': 0x3C,
            'USHR': 0x2D, 'USHR3': 0x3D,
            'CMPEQ': 0x1F, 'CMPGT': 0x1D, 'CMPHI': 0x1E,
            'ADDI': 0x03, 'ANDI': 0x02, 'ORI': 0x01,
            'MOV': 0x06, 'MOVA': 0x04, 'DQM': 0x07,
            'TADD': 0x0C, 'TSUB': 0x0D,
        }

        if mnem in three_parcel_opcodes and len(ops) == 2:
            src_s = ops[0].strip()
            dst_s = ops[1].strip()

            # Determine mode and value for src
            if src_s.startswith('$'):
                smode = 0xF  # immediate
                src_val = int(src_s[1:], 0) & 0xFFFF
            else:
                smode = 0xD  # word stack offset
                src_val = self._parse_reg(src_s) & 0xFFFF

            # Determine mode and value for dst
            if dst_s.startswith('$'):
                raise ValueError(f"Destination cannot be immediate for {mnem}")
            dmode = 0xD  # word stack offset
            dst_val = self._parse_reg(dst_s) & 0xFFFF

            return self._encode_three_parcel(
                three_parcel_opcodes[mnem], smode, dmode, src_val, dst_val)

        raise ValueError(f"Cannot encode: {mnem} {', '.join(ops)}")

    def assemble(self, source):
        """Two-pass assembly of source text."""
        lines = source.split('\n')

        # Pass 1: collect labels
        self.pc = self.base_addr
        for i, line in enumerate(lines, 1):
            try:
                self.assemble_line(line, pass_num=1)
            except Exception as e:
                print(f"Pass 1, line {i}: {e}", file=sys.stderr)
                print(f"  {line}", file=sys.stderr)

        # Pass 2: emit code
        self.pc = self.base_addr
        self.code = []
        for i, line in enumerate(lines, 1):
            try:
                self.assemble_line(line, pass_num=2)
            except Exception as e:
                print(f"Pass 2, line {i}: {e}", file=sys.stderr)
                print(f"  {line}", file=sys.stderr)
                sys.exit(1)

    def write_hex(self, filename):
        """Write assembled code as Verilog $readmemh hex file.
        Each line is one 32-bit word (big-endian, matching Hobbit text ordering)."""
        if not self.code:
            return

        # Flatten all bytes
        all_bytes = bytearray()
        min_addr = self.code[0][0]
        for addr, bytelist, _ in self.code:
            # Pad if needed
            while min_addr + len(all_bytes) < addr:
                all_bytes.append(0)
            all_bytes.extend(bytelist)

        with open(filename, 'w') as f:
            f.write(f"// Hobbit assembled code, base=0x{min_addr:08X}\n")
            f.write(f"// {len(all_bytes)} bytes, {len(self.code)} instructions\n")
            # Write as 16-bit parcels (Hobbit's native instruction unit)
            for i in range(0, len(all_bytes), 2):
                if i + 1 < len(all_bytes):
                    word = (all_bytes[i] << 8) | all_bytes[i + 1]
                else:
                    word = all_bytes[i] << 8
                f.write(f"{word:04X}\n")

    def write_binary(self, filename):
        """Write raw binary output."""
        all_bytes = bytearray()
        if self.code:
            min_addr = self.code[0][0]
            for addr, bytelist, _ in self.code:
                while min_addr + len(all_bytes) < addr:
                    all_bytes.append(0)
                all_bytes.extend(bytelist)
        with open(filename, 'wb') as f:
            f.write(all_bytes)

    def print_listing(self, f=sys.stdout):
        """Print assembly listing."""
        for addr, bytelist, source in self.code:
            hexbytes = ' '.join(f'{b:02X}' for b in bytelist)
            f.write(f"  {addr:08X}:  {hexbytes:<20s}  {source}\n")


def main():
    parser = argparse.ArgumentParser(description='AT&T Hobbit (ATT92010) Assembler')
    parser.add_argument('input', help='Assembly source file (.s)')
    parser.add_argument('-o', '--output', help='Output hex file (default: stdout listing)')
    parser.add_argument('--base', type=lambda x: int(x, 0), default=0,
                        help='Base address (default: 0)')
    parser.add_argument('--binary', action='store_true',
                        help='Output raw binary instead of hex')
    parser.add_argument('-l', '--listing', action='store_true',
                        help='Print assembly listing')
    args = parser.parse_args()

    source = Path(args.input).read_text()
    asm = HobbitAssembler(base_addr=args.base)
    asm.assemble(source)

    if args.listing or not args.output:
        print(f"Labels: {asm.labels}")
        asm.print_listing()

    if args.output:
        if args.binary:
            asm.write_binary(args.output)
        else:
            asm.write_hex(args.output)
        print(f"Written to {args.output}")


if __name__ == "__main__":
    main()
