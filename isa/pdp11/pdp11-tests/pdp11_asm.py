#!/usr/bin/env python3
"""
Simple PDP-11 Assembler for Test Generation

This assembler supports a subset of PDP-11 instructions sufficient
for generating test programs. It outputs hex files compatible with
the test infrastructure.

Usage: python3 pdp11_asm.py input.s output.hex
"""

import re
import sys
from typing import Dict, List, Tuple, Optional

class PDP11Assembler:
    """Simple two-pass PDP-11 assembler"""

    # Register names
    REGS = {
        'r0': 0, 'r1': 1, 'r2': 2, 'r3': 3,
        'r4': 4, 'r5': 5, 'r6': 6, 'sp': 6, 'r7': 7, 'pc': 7
    }

    # Double operand instructions: opcode in bits 15:12
    DOUBLE_OPS = {
        'mov':  0o01, 'movb': 0o11,
        'cmp':  0o02, 'cmpb': 0o12,
        'bit':  0o03, 'bitb': 0o13,
        'bic':  0o04, 'bicb': 0o14,
        'bis':  0o05, 'bisb': 0o15,
        'add':  0o06,
        'sub':  0o16,
    }

    # Single operand instructions: opcode in bits 15:6
    SINGLE_OPS = {
        'clr':  0o0050, 'clrb': 0o1050,
        'com':  0o0051, 'comb': 0o1051,
        'inc':  0o0052, 'incb': 0o1052,
        'dec':  0o0053, 'decb': 0o1053,
        'neg':  0o0054, 'negb': 0o1054,
        'adc':  0o0055, 'adcb': 0o1055,
        'sbc':  0o0056, 'sbcb': 0o1056,
        'tst':  0o0057, 'tstb': 0o1057,
        'ror':  0o0060, 'rorb': 0o1060,
        'rol':  0o0061, 'rolb': 0o1061,
        'asr':  0o0062, 'asrb': 0o1062,
        'asl':  0o0063, 'aslb': 0o1063,
        'swab': 0o0003,
        'sxt':  0o0067,
        'jmp':  0o0001,
    }

    # Branch instructions: high byte of opcode (shifted << 8 when assembled)
    # PDP-11 branch format: bits 15-8 = opcode, bits 7-0 = signed offset
    BRANCHES = {
        'br':   0x01,  # 000400
        'bne':  0x02,  # 001000
        'beq':  0x03,  # 001400
        'bge':  0x04,  # 002000
        'blt':  0x05,  # 002400
        'bgt':  0x06,  # 003000
        'ble':  0x07,  # 003400
        'bpl':  0x80,  # 100000
        'bmi':  0x81,  # 100400
        'bhi':  0x82,  # 101000
        'blos': 0x83,  # 101400
        'bvc':  0x84,  # 102000
        'bvs':  0x85,  # 102400
        'bcc':  0x86, 'bhis': 0x86,  # 103000
        'bcs':  0x87, 'blo': 0x87,   # 103400
    }

    # Condition code operations
    CC_OPS = {
        'clc': 0o000241, 'clv': 0o000242, 'clz': 0o000244, 'cln': 0o000250,
        'sec': 0o000261, 'sev': 0o000262, 'sez': 0o000264, 'sen': 0o000270,
        'ccc': 0o000257, 'scc': 0o000277,
        'nop': 0o000240,
        'halt': 0o000000,
    }

    # EIS instructions
    EIS_OPS = {
        'mul': 0o070,
        'div': 0o071,
        'ash': 0o072,
        'ashc': 0o073,
    }
    # XOR is handled separately due to different operand order

    # JSR/RTS
    JSR_OP = 0o004
    RTS_OP = 0o00020
    SOB_OP = 0o077

    def __init__(self):
        self.labels: Dict[str, int] = {}
        self.code: List[int] = []  # List of words
        self.pc = 0
        self.origin = 0

    def parse_number(self, s: str) -> int:
        """Parse a number in various formats"""
        s = s.strip()
        if s.startswith('$'):
            s = s[1:]
        if s.startswith('#'):
            s = s[1:]
        if s.startswith('0x') or s.startswith('0X'):
            return int(s, 16)
        if s.startswith('0o') or s.startswith('0O'):
            return int(s, 8)
        if s.startswith('0b') or s.startswith('0B'):
            return int(s, 2)
        if s.startswith("'") and s.endswith("'") and len(s) == 3:
            return ord(s[1])
        # Octal if starts with 0
        if s.startswith('0') and len(s) > 1 and s[1:].isdigit():
            return int(s, 8)
        return int(s)

    def parse_operand(self, op: str) -> Tuple[int, int, Optional[int]]:
        """
        Parse operand and return (mode, reg, extra_word).
        Returns mode (3 bits), register (3 bits), and optional extra word.
        """
        op = op.strip()

        # Immediate: #n or $n (may be a label)
        if op.startswith('#') or op.startswith('$'):
            inner = op[1:].strip()
            if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', inner):
                # Label reference as immediate value - needs absolute address
                return (2, 7, ('imm_label', inner))
            val = self.parse_number(inner)
            return (2, 7, val)  # Mode 2, PC = immediate

        # Register deferred: (Rn) or @Rn
        if op.startswith('@'):
            inner = op[1:]
            if inner.lower() in self.REGS:
                return (1, self.REGS[inner.lower()], None)
            # @#addr - Absolute addressing (autoincrement deferred with PC, mode 3 reg 7)
            if inner.startswith('#'):
                val = inner[1:]
                if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', val):
                    return (3, 7, val)  # Label - resolve later
                return (3, 7, self.parse_number(val))
            # @(Rn)+ - autoincrement deferred (mode 3)
            m_ai = re.match(r'\((\w+)\)\+', inner, re.I)
            if m_ai:
                reg = m_ai.group(1).lower()
                if reg in self.REGS:
                    return (3, self.REGS[reg], None)
            raise ValueError(f"Unknown operand: {op}")

        if op.startswith('(') and op.endswith(')'):
            inner = op[1:-1].lower()
            if inner in self.REGS:
                return (1, self.REGS[inner], None)
            raise ValueError(f"Unknown operand: {op}")

        # Autoincrement: (Rn)+
        m = re.match(r'\((\w+)\)\+', op, re.I)
        if m:
            reg = m.group(1).lower()
            if reg in self.REGS:
                return (2, self.REGS[reg], None)
            raise ValueError(f"Unknown register: {reg}")

        # Autodecrement: -(Rn)
        m = re.match(r'-\((\w+)\)', op, re.I)
        if m:
            reg = m.group(1).lower()
            if reg in self.REGS:
                return (4, self.REGS[reg], None)
            raise ValueError(f"Unknown register: {reg}")

        # Plain register
        if op.lower() in self.REGS:
            return (0, self.REGS[op.lower()], None)

        # Indexed mode: X(Rn) where X is a number or label
        m = re.match(r'([a-zA-Z_][a-zA-Z0-9_]*|\-?[0-9][0-9a-fA-FxXoObB]*)\((\w+)\)', op, re.I)
        if m:
            offset_str = m.group(1)
            reg = m.group(2).lower()
            if reg in self.REGS:
                if re.match(r'^[a-zA-Z_]', offset_str):
                    # Label offset
                    return (6, self.REGS[reg], offset_str)
                else:
                    offset = self.parse_number(offset_str)
                    return (6, self.REGS[reg], offset)
            raise ValueError(f"Unknown register in indexed mode: {reg}")

        # Label reference (will need to be resolved later)
        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', op):
            # Treat as absolute address
            return (6, 7, op)  # Indexed mode with PC = relative

        raise ValueError(f"Unknown operand: {op}")

    def encode_double_op(self, opcode: int, src: str, dst: str) -> List[int]:
        """Encode double operand instruction"""
        src_mode, src_reg, src_extra = self.parse_operand(src)
        dst_mode, dst_reg, dst_extra = self.parse_operand(dst)

        instr = (opcode << 12) | (src_mode << 9) | (src_reg << 6) | (dst_mode << 3) | dst_reg
        words = [instr]

        if src_extra is not None:
            if isinstance(src_extra, str):
                # Label - will resolve later (PC-relative)
                words.append(src_extra)
            elif isinstance(src_extra, tuple):
                # Tagged label (e.g., ('imm_label', name))
                words.append(src_extra)
            else:
                words.append(src_extra & 0xFFFF)

        if dst_extra is not None:
            if isinstance(dst_extra, str):
                words.append(dst_extra)
            elif isinstance(dst_extra, tuple):
                words.append(dst_extra)
            else:
                words.append(dst_extra & 0xFFFF)

        return words

    def encode_single_op(self, opcode: int, dst: str) -> List[int]:
        """Encode single operand instruction"""
        dst_mode, dst_reg, dst_extra = self.parse_operand(dst)

        instr = (opcode << 6) | (dst_mode << 3) | dst_reg
        words = [instr]

        if dst_extra is not None:
            if isinstance(dst_extra, str):
                words.append(dst_extra)
            elif isinstance(dst_extra, tuple):
                words.append(dst_extra)
            else:
                words.append(dst_extra & 0xFFFF)

        return words

    def encode_branch(self, opcode: int, target: str) -> List[int]:
        """Encode branch instruction"""
        # Branch offset will be resolved in second pass
        return [(opcode << 8) | 0, target]  # Placeholder

    def encode_eis(self, opcode: int, src: str, dst: str) -> List[int]:
        """Encode EIS instruction (MUL, DIV, ASH, ASHC)"""
        src_mode, src_reg, src_extra = self.parse_operand(src)
        # dst is always a register for EIS
        if dst.lower() not in self.REGS:
            raise ValueError(f"EIS destination must be register: {dst}")
        dst_reg = self.REGS[dst.lower()]

        instr = (opcode << 9) | (dst_reg << 6) | (src_mode << 3) | src_reg
        words = [instr]

        if src_extra is not None:
            if isinstance(src_extra, str):
                words.append(src_extra)
            elif isinstance(src_extra, tuple):
                words.append(src_extra)
            else:
                words.append(src_extra & 0xFFFF)

        return words

    def encode_xor(self, src: str, dst: str) -> List[int]:
        """Encode XOR instruction: XOR Rn, dst (src is the register)"""
        # For XOR, syntax is XOR Rn, dst where Rn is in bits 8:6
        if src.lower() not in self.REGS:
            raise ValueError(f"XOR source must be register: {src}")
        src_reg = self.REGS[src.lower()]

        dst_mode, dst_reg, dst_extra = self.parse_operand(dst)

        instr = (0o074 << 9) | (src_reg << 6) | (dst_mode << 3) | dst_reg
        words = [instr]

        if dst_extra is not None:
            if isinstance(dst_extra, str):
                words.append(dst_extra)
            elif isinstance(dst_extra, tuple):
                words.append(dst_extra)
            else:
                words.append(dst_extra & 0xFFFF)

        return words

    def encode_jsr(self, link: str, dst: str) -> List[int]:
        """Encode JSR instruction"""
        if link.lower() not in self.REGS:
            raise ValueError(f"JSR link must be register: {link}")
        link_reg = self.REGS[link.lower()]

        dst_mode, dst_reg, dst_extra = self.parse_operand(dst)

        instr = (self.JSR_OP << 9) | (link_reg << 6) | (dst_mode << 3) | dst_reg
        words = [instr]

        if dst_extra is not None:
            if isinstance(dst_extra, str):
                words.append(dst_extra)
            elif isinstance(dst_extra, tuple):
                words.append(dst_extra)
            else:
                words.append(dst_extra & 0xFFFF)

        return words

    def encode_rts(self, link: str) -> List[int]:
        """Encode RTS instruction"""
        if link.lower() not in self.REGS:
            raise ValueError(f"RTS link must be register: {link}")
        link_reg = self.REGS[link.lower()]
        return [(self.RTS_OP << 3) | link_reg]

    def encode_sob(self, reg: str, target: str) -> List[int]:
        """Encode SOB instruction"""
        if reg.lower() not in self.REGS:
            raise ValueError(f"SOB register invalid: {reg}")
        reg_num = self.REGS[reg.lower()]
        # Offset will be resolved in second pass
        return [(self.SOB_OP << 9) | (reg_num << 6) | 0, ('sob', target)]

    def first_pass(self, lines: List[str]):
        """First pass: collect labels and calculate addresses"""
        self.pc = self.origin
        self.labels = {}

        for line in lines:
            # Remove comments
            if ';' in line:
                line = line[:line.index(';')]
            if '//' in line:
                line = line[:line.index('//')]
            line = line.strip()
            if not line:
                continue

            # Check for label
            if ':' in line:
                label, rest = line.split(':', 1)
                label = label.strip()
                if label:
                    self.labels[label] = self.pc
                line = rest.strip()
                if not line:
                    continue

            # Check for directives
            if line.startswith('.'):
                parts = line.split(None, 1)
                directive = parts[0].lower()
                if directive == '.org' or directive == '.=':
                    val = self.parse_number(parts[1])
                    self.pc = val
                    continue
                if directive == '.word':
                    words = parts[1].split(',')
                    self.pc += len(words) * 2
                    continue
                if directive == '.byte':
                    bytes_list = parts[1].split(',')
                    self.pc += len(bytes_list)
                    if self.pc % 2 == 1:
                        self.pc += 1  # Align
                    continue
                if directive in ['.text', '.data', '.globl', '.end']:
                    continue
                continue

            # Parse instruction to determine size
            parts = line.split(None, 1)
            mnemonic = parts[0].lower()
            operands = parts[1] if len(parts) > 1 else ''

            if mnemonic in self.CC_OPS:
                self.pc += 2
            elif mnemonic in self.DOUBLE_OPS:
                ops = [o.strip() for o in operands.split(',')]
                words = self.encode_double_op(self.DOUBLE_OPS[mnemonic], ops[0], ops[1])
                self.pc += len([w for w in words if not isinstance(w, str)]) * 2
                # Count extra words
                for w in words:
                    if isinstance(w, str):
                        self.pc += 2
            elif mnemonic in self.SINGLE_OPS:
                words = self.encode_single_op(self.SINGLE_OPS[mnemonic], operands.strip())
                self.pc += len([w for w in words if not isinstance(w, str)]) * 2
                for w in words:
                    if isinstance(w, str):
                        self.pc += 2
            elif mnemonic in self.BRANCHES:
                self.pc += 2
            elif mnemonic in self.EIS_OPS:
                ops = [o.strip() for o in operands.split(',')]
                words = self.encode_eis(self.EIS_OPS[mnemonic], ops[0], ops[1])
                self.pc += len([w for w in words if not isinstance(w, str)]) * 2
                for w in words:
                    if isinstance(w, str):
                        self.pc += 2
            elif mnemonic == 'xor':
                ops = [o.strip() for o in operands.split(',')]
                words = self.encode_xor(ops[0], ops[1])
                self.pc += len([w for w in words if not isinstance(w, str)]) * 2
                for w in words:
                    if isinstance(w, str):
                        self.pc += 2
            elif mnemonic == 'jsr':
                ops = [o.strip() for o in operands.split(',')]
                words = self.encode_jsr(ops[0], ops[1])
                self.pc += len([w for w in words if not isinstance(w, str)]) * 2
                for w in words:
                    if isinstance(w, str):
                        self.pc += 2
            elif mnemonic == 'rts':
                self.pc += 2
            elif mnemonic == 'sob':
                self.pc += 2

    def second_pass(self, lines: List[str]) -> bytes:
        """Second pass: generate code"""
        self.pc = self.origin
        result = bytearray()

        # Pad to origin
        while len(result) < self.origin:
            result.append(0)

        for line in lines:
            # Remove comments
            if ';' in line:
                line = line[:line.index(';')]
            if '//' in line:
                line = line[:line.index('//')]
            line = line.strip()
            if not line:
                continue

            # Check for label
            if ':' in line:
                _, rest = line.split(':', 1)
                line = rest.strip()
                if not line:
                    continue

            # Check for directives
            if line.startswith('.'):
                parts = line.split(None, 1)
                directive = parts[0].lower()
                if directive == '.org' or directive == '.=':
                    val = self.parse_number(parts[1])
                    while len(result) < val:
                        result.append(0)
                    self.pc = val
                    continue
                if directive == '.word':
                    words = parts[1].split(',')
                    for w in words:
                        w = w.strip()
                        if w in self.labels:
                            val = self.labels[w]
                        else:
                            val = self.parse_number(w)
                        result.append(val & 0xFF)
                        result.append((val >> 8) & 0xFF)
                        self.pc += 2
                    continue
                if directive == '.byte':
                    bytes_list = parts[1].split(',')
                    for b in bytes_list:
                        b = b.strip()
                        val = self.parse_number(b)
                        result.append(val & 0xFF)
                        self.pc += 1
                    if self.pc % 2 == 1:
                        result.append(0)
                        self.pc += 1
                    continue
                if directive in ['.text', '.data', '.globl', '.end']:
                    continue
                continue

            # Parse instruction
            parts = line.split(None, 1)
            mnemonic = parts[0].lower()
            operands = parts[1] if len(parts) > 1 else ''

            words = []

            if mnemonic in self.CC_OPS:
                words = [self.CC_OPS[mnemonic]]
            elif mnemonic in self.DOUBLE_OPS:
                ops = [o.strip() for o in operands.split(',')]
                words = self.encode_double_op(self.DOUBLE_OPS[mnemonic], ops[0], ops[1])
            elif mnemonic in self.SINGLE_OPS:
                words = self.encode_single_op(self.SINGLE_OPS[mnemonic], operands.strip())
            elif mnemonic in self.BRANCHES:
                target = operands.strip()
                if target in self.labels:
                    target_addr = self.labels[target]
                else:
                    target_addr = self.parse_number(target)
                # Calculate offset: (target - (pc + 2)) / 2
                offset = (target_addr - (self.pc + 2)) // 2
                if offset < -128 or offset > 127:
                    raise ValueError(f"Branch offset out of range: {offset}")
                instr = (self.BRANCHES[mnemonic] << 8) | (offset & 0xFF)
                words = [instr]
            elif mnemonic in self.EIS_OPS:
                ops = [o.strip() for o in operands.split(',')]
                words = self.encode_eis(self.EIS_OPS[mnemonic], ops[0], ops[1])
            elif mnemonic == 'xor':
                ops = [o.strip() for o in operands.split(',')]
                words = self.encode_xor(ops[0], ops[1])
            elif mnemonic == 'jsr':
                ops = [o.strip() for o in operands.split(',')]
                words = self.encode_jsr(ops[0], ops[1])
            elif mnemonic == 'rts':
                words = self.encode_rts(operands.strip())
            elif mnemonic == 'sob':
                ops = [o.strip() for o in operands.split(',')]
                reg = ops[0]
                target = ops[1]
                if target in self.labels:
                    target_addr = self.labels[target]
                else:
                    target_addr = self.parse_number(target)
                # SOB offset is positive, backward branch
                offset = (self.pc + 2 - target_addr) // 2
                if offset < 0 or offset > 63:
                    raise ValueError(f"SOB offset out of range: {offset}")
                reg_num = self.REGS[reg.lower()]
                instr = (self.SOB_OP << 9) | (reg_num << 6) | offset
                words = [instr]
            else:
                raise ValueError(f"Unknown mnemonic: {mnemonic}")

            # Emit words
            for w in words:
                if isinstance(w, str):
                    # Label reference - compute PC-relative offset
                    # After this word is fetched, PC points to next word
                    if w in self.labels:
                        target_addr = self.labels[w]
                    else:
                        target_addr = self.parse_number(w)
                    # For mode 6/7 (indexed), the offset is relative to PC after fetch
                    # PC will be at self.pc + 2 after this word is fetched
                    offset = target_addr - (self.pc + 2)
                    result.append(offset & 0xFF)
                    result.append((offset >> 8) & 0xFF)
                    self.pc += 2
                elif isinstance(w, tuple):
                    if w[0] == 'imm_label':
                        # Immediate label - emit absolute address
                        label = w[1]
                        if label in self.labels:
                            addr = self.labels[label]
                        else:
                            raise ValueError(f"Undefined label: {label}")
                        result.append(addr & 0xFF)
                        result.append((addr >> 8) & 0xFF)
                        self.pc += 2
                    # else: SOB with label - already handled above
                else:
                    result.append(w & 0xFF)
                    result.append((w >> 8) & 0xFF)
                    self.pc += 2

        return bytes(result)

    def assemble(self, source: str) -> bytes:
        """Assemble source code to binary"""
        lines = source.split('\n')
        self.first_pass(lines)
        return self.second_pass(lines)

    def to_hex(self, binary: bytes) -> str:
        """Convert binary to hex file format (one byte per line)"""
        lines = []
        for b in binary:
            lines.append(f"{b:02X}")
        return '\n'.join(lines) + '\n'


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} input.s output.hex")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    with open(input_file, 'r') as f:
        source = f.read()

    asm = PDP11Assembler()
    try:
        binary = asm.assemble(source)
        hex_output = asm.to_hex(binary)

        with open(output_file, 'w') as f:
            f.write(hex_output)

        print(f"Assembled {len(binary)} bytes to {output_file}")
        print(f"Labels: {asm.labels}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
