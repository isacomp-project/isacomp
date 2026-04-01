#!/usr/bin/env python3
"""
Simple MicroVAX Assembler for ISA testing.

This assembler supports the simplified 32-bit fixed-width MicroVAX encoding
used in our ISA spec. It produces hex files suitable for simulation.

Usage:
    python mvax_asm.py input.S -o output.hex
"""

import re
import sys
import argparse
from pathlib import Path

# Opcode definitions (124 instructions)
OPCODES = {
    # Control
    'halt':   0x00,
    'nop':    0x01,
    'rei':    0x02,
    'bpt':    0x03,
    'ret':    0x04,
    'rsb':    0x05,
    'index':  0x0A,

    # Branches - basic
    'brb':    0x11,
    'bneq':   0x12,
    'beql':   0x13,
    'blss':   0x14,
    'bgeq':   0x15,
    'bgtr':   0x16,
    'bleq':   0x17,
    'blssu':  0x18,
    'bgequ':  0x19,
    'jmp':    0x1A,
    'bgtru':  0x1B,
    'blequ':  0x1C,
    'bvs':    0x1D,
    'bvc':    0x1E,
    'jsb':    0x20,
    'brw':    0x31,

    # ACB and move address
    'movzwl': 0x3C,
    'acbw':   0x3D,
    'movaw':  0x3E,
    'pushaw': 0x3F,

    # Shifts
    'ashl':   0x78,
    'ashli':  0x79,
    'shrli':  0x7A,
    'shrai':  0x7B,
    'emul':   0x7C,
    'ediv':   0x7D,

    # Byte arithmetic
    'addb2':  0x80,
    'addb3':  0x81,
    'subb2':  0x82,
    'subb3':  0x83,
    'divl2':  0x86,
    'divl3':  0x87,
    'andl2':  0x88,
    'andl3':  0x89,
    'mnegb':  0x8E,
    'caseb':  0x8F,
    'cmpb':   0x90,
    'cmpl':   0x91,
    'tstb':   0x93,
    'clrb':   0x94,
    'tstl':   0x95,
    'incb':   0x96,
    'decb':   0x97,
    'cvtbw':  0x99,
    'movb':   0x9A,
    'movzbl': 0x9B,
    'rotl':   0x9C,
    'movzbw': 0x9D,
    'acbb':   0x9E,
    'movab':  0x9F,

    # Word arithmetic
    'addw2':  0xA0,
    'addw3':  0xA1,
    'subw2':  0xA2,
    'subw3':  0xA3,
    'mnegw':  0xAE,
    'casew':  0xAF,
    'movw':   0xB0,
    'cmpw':   0xB1,
    'tstw':   0xB3,
    'clrw':   0xB4,
    'incw':   0xB6,
    'decw':   0xB7,
    'bispsw': 0xB8,
    'bicpsw': 0xB9,

    # Longword arithmetic
    'addl2':  0xC0,
    'addl3':  0xC1,
    'subl2':  0xC2,
    'subl3':  0xC3,
    'addli':  0xC4,
    'subli':  0xC5,
    'mull2':  0xC6,
    'mull3':  0xC7,
    'bisl2':  0xC8,
    'bisl3':  0xC9,
    'bicl2':  0xCA,
    'bicl3':  0xCB,
    'xorl2':  0xCC,
    'xorl3':  0xCD,
    'mnegl':  0xCE,
    'mcoml':  0xCF,
    'movl':   0xD0,
    'movli':  0xD1,
    'clrl':   0xD4,
    'incl':   0xD6,
    'decl':   0xD7,
    'popl':   0xD8,
    'adwc':   0xD9,
    'sbwc':   0xDA,
    'pushal': 0xDB,
    'movpsl': 0xDC,
    'pushl':  0xDD,
    'moval':  0xDE,
    'pushab': 0xDF,

    # Load/Store and bit operations
    'ldl':    0xE0,
    'bbs':    0xE1,
    'bbss':   0xE2,
    'bbc':    0xE3,
    'bbcs':   0xE4,
    'bbsc':   0xE5,
    'bbcc':   0xE6,
    'stl':    0xE8,
    'ffs':    0xEB,
    'ffc':    0xEC,
    'extv':   0xEE,
    'extzv':  0xEF,
    'insv':   0xF0,

    # Loop control
    'acbl':   0xF1,
    'aoblss': 0xF2,
    'aobleq': 0xF3,
    'sobgeq': 0xF4,
    'sobgtr': 0xF5,
    'cvtlb':  0xF6,
    'cvtbl':  0xF7,
    'cvtwl':  0xF8,
    'calls':  0xFB,
    'casel':  0xFC,
    'illegal': 0xFF,
}

# Register aliases
REGISTERS = {
    'r0': 0, 'r1': 1, 'r2': 2, 'r3': 3,
    'r4': 4, 'r5': 5, 'r6': 6, 'r7': 7,
    'r8': 8, 'r9': 9, 'r10': 10, 'r11': 11,
    'ap': 12, 'r12': 12,
    'fp': 13, 'r13': 13,
    'sp': 14, 'r14': 14,
    'pc': 15, 'r15': 15,
}


class MicroVAXAssembler:
    def __init__(self):
        self.labels = {}
        self.instructions = []
        self.current_addr = 0
        self.pending_labels = []  # Labels to resolve after first pass

    def parse_register(self, s):
        """Parse a register operand."""
        s = s.strip().lower()
        if s in REGISTERS:
            return REGISTERS[s]
        raise ValueError(f"Unknown register: {s}")

    def parse_immediate(self, s):
        """Parse an immediate value."""
        s = s.strip()
        if s.startswith('#'):
            s = s[1:]
        s = s.strip()

        # Handle expressions like "pass - ." for relative branches
        if '-' in s and '.' in s:
            return None  # Will be resolved later

        # Handle hex
        if s.startswith('0x') or s.startswith('0X'):
            return int(s, 16)
        # Handle binary
        if s.startswith('0b') or s.startswith('0B'):
            return int(s, 2)
        # Handle negative
        if s.startswith('-'):
            return -int(s[1:])
        # Default decimal
        return int(s)

    def encode_instruction(self, mnemonic, operands, addr):
        """Encode a single instruction to a 32-bit word."""
        mnem = mnemonic.lower()
        if mnem not in OPCODES:
            raise ValueError(f"Unknown instruction: {mnemonic}")

        opcode = OPCODES[mnem]

        # NOP - no operands
        if mnem == 'nop':
            return (opcode << 24)

        # RSB - no operands (return from subroutine)
        if mnem == 'rsb':
            return (opcode << 24)

        # Single-operand instructions: INCL, DECL, CLRL
        if mnem in ('incl', 'decl', 'clrl'):
            dst = self.parse_register(operands[0])
            return (opcode << 24) | (dst << 20)

        # 2-operand register instructions: ADDL2, SUBL2, etc.
        if mnem in ('addl2', 'subl2', 'mull2', 'andl2', 'bisl2', 'bicl2', 'xorl2'):
            src = self.parse_register(operands[0])
            dst = self.parse_register(operands[1])
            return (opcode << 24) | (src << 20) | (dst << 16)

        # 2-operand with different dest: MOVL, MNEGL, MCOML, TSTL
        if mnem in ('movl', 'mnegl', 'mcoml', 'tstl'):
            src = self.parse_register(operands[0])
            dst = self.parse_register(operands[1])
            return (opcode << 24) | (src << 20) | (dst << 16)

        # 3-operand register instructions: ADDL3, SUBL3, etc.
        if mnem in ('addl3', 'subl3', 'mull3', 'andl3', 'bisl3', 'bicl3', 'xorl3', 'cmpl'):
            src1 = self.parse_register(operands[0])
            src2 = self.parse_register(operands[1])
            dst = self.parse_register(operands[2])
            return (opcode << 24) | (src1 << 20) | (src2 << 16) | (dst << 12)

        # Immediate instructions: MOVLI, ADDLI, SUBLI
        if mnem in ('movli', 'addli', 'subli'):
            imm = self.parse_immediate(operands[0])
            dst = self.parse_register(operands[1])
            if imm is None:
                raise ValueError(f"Cannot resolve immediate in {mnemonic}")
            return (opcode << 24) | (dst << 20) | (imm & 0xFFFFF)

        # Shift immediate: ASHLI, SHRLI, SHRAI
        if mnem in ('ashli', 'shrli', 'shrai'):
            shamt = self.parse_immediate(operands[0])
            src = self.parse_register(operands[1])
            dst = self.parse_register(operands[2])
            return (opcode << 24) | (src << 20) | (dst << 16) | ((shamt & 0x1F) << 11)

        # Shift register: ASHL, ROTL
        if mnem in ('ashl', 'rotl'):
            cnt = self.parse_register(operands[0])
            src = self.parse_register(operands[1])
            dst = self.parse_register(operands[2])
            return (opcode << 24) | (cnt << 20) | (src << 16) | (dst << 12)

        # Load: LDL base(offset), dst -> LDL offset(base), dst
        if mnem == 'ldl':
            # Parse base(offset) or offset(base)
            match = re.match(r'(\d+)\s*\(\s*(\w+)\s*\)', operands[0])
            if match:
                offset = int(match.group(1))
                base = self.parse_register(match.group(2))
            else:
                base = self.parse_register(operands[0])
                offset = self.parse_immediate(operands[1]) if len(operands) > 1 else 0
            dst = self.parse_register(operands[-1]) if len(operands) > 1 else self.parse_register(operands[1])
            return (opcode << 24) | (base << 20) | (dst << 16) | (offset & 0xFFFF)

        # Store: STL src, base, offset
        if mnem == 'stl':
            src = self.parse_register(operands[0])
            # Parse base(offset) format
            match = re.match(r'(\d+)\s*\(\s*(\w+)\s*\)', operands[1])
            if match:
                offset = int(match.group(1))
                base = self.parse_register(match.group(2))
            else:
                base = self.parse_register(operands[1])
                offset = self.parse_immediate(operands[2]) if len(operands) > 2 else 0
            return (opcode << 24) | (src << 20) | (base << 16) | (offset & 0xFFFF)

        # Unconditional branch: BRB displacement
        if mnem == 'brb':
            target = operands[0].strip()
            if target in self.labels:
                disp = self.labels[target] - addr
            else:
                disp = self.parse_immediate(target)
                if disp is None:
                    # Label not yet resolved
                    self.pending_labels.append((addr, mnem, operands))
                    disp = 0
            return (opcode << 24) | (disp & 0xFFFFFF)

        # JSB displacement (like BRB but pushes return address)
        if mnem == 'jsb':
            target = operands[0].strip()
            if target in self.labels:
                disp = self.labels[target] - addr
            else:
                disp = self.parse_immediate(target)
                if disp is None:
                    self.pending_labels.append((addr, mnem, operands))
                    disp = 0
            return (opcode << 24) | (disp & 0xFFFFFF)

        # Conditional branches: BEQL, BNEQ, etc.
        if mnem in ('beql', 'bneq', 'blss', 'bgeq', 'bgtr', 'bleq', 'blssu', 'bgequ', 'bgtru', 'blequ'):
            src1 = self.parse_register(operands[0])
            src2 = self.parse_register(operands[1])
            target = operands[2].strip()
            if target in self.labels:
                disp = self.labels[target] - addr
            else:
                disp = self.parse_immediate(target)
                if disp is None:
                    self.pending_labels.append((addr, mnem, operands))
                    disp = 0
            return (opcode << 24) | (src1 << 20) | (src2 << 16) | (disp & 0xFFFF)

        # Condition code branches: BVS, BVC
        if mnem in ('bvs', 'bvc'):
            target = operands[0].strip()
            if target in self.labels:
                disp = self.labels[target] - addr
            else:
                disp = self.parse_immediate(target)
                if disp is None:
                    self.pending_labels.append((addr, mnem, operands))
                    disp = 0
            return (opcode << 24) | (disp & 0xFFFF)

        # Division: DIVL2, DIVL3
        if mnem in ('divl2',):
            src = self.parse_register(operands[0])
            dst = self.parse_register(operands[1])
            return (opcode << 24) | (src << 20) | (dst << 16)

        if mnem in ('divl3',):
            src1 = self.parse_register(operands[0])
            src2 = self.parse_register(operands[1])
            dst = self.parse_register(operands[2])
            return (opcode << 24) | (src1 << 20) | (src2 << 16) | (dst << 12)

        # Stack operations: PUSHL, POPL
        if mnem == 'pushl':
            src = self.parse_register(operands[0])
            return (opcode << 24) | (src << 20)

        if mnem == 'popl':
            dst = self.parse_register(operands[0])
            return (opcode << 24) | (dst << 20)

        # JMP - indirect jump through register
        if mnem == 'jmp':
            target_reg = self.parse_register(operands[0])
            return (opcode << 24) | (target_reg << 20)

        # HALT, ILLEGAL - no operands
        if mnem in ('halt', 'illegal'):
            return (opcode << 24)

        # SOBGTR, SOBGEQ - subtract one and branch
        if mnem in ('sobgtr', 'sobgeq'):
            idx_reg = self.parse_register(operands[0])
            target = operands[1].strip()
            if target in self.labels:
                disp = self.labels[target] - addr
            else:
                disp = self.parse_immediate(target)
                if disp is None:
                    self.pending_labels.append((addr, mnem, operands))
                    disp = 0
            return (opcode << 24) | (idx_reg << 20) | (disp & 0xFFFF)

        # AOBLEQ, AOBLSS - add one and branch
        if mnem in ('aobleq', 'aoblss'):
            limit_reg = self.parse_register(operands[0])
            idx_reg = self.parse_register(operands[1])
            target = operands[2].strip()
            if target in self.labels:
                disp = self.labels[target] - addr
            else:
                disp = self.parse_immediate(target)
                if disp is None:
                    self.pending_labels.append((addr, mnem, operands))
                    disp = 0
            return (opcode << 24) | (limit_reg << 20) | (idx_reg << 16) | (disp & 0xFFF)

        # Conversion instructions: CVTBL, CVTLB, CVTWL
        if mnem in ('cvtbl', 'cvtlb', 'cvtwl'):
            src = self.parse_register(operands[0])
            dst = self.parse_register(operands[1])
            return (opcode << 24) | (src << 20) | (dst << 16)

        # Bit branch: BBS, BBC
        if mnem in ('bbs', 'bbc'):
            pos = self.parse_register(operands[0])
            base = self.parse_register(operands[1])
            target = operands[2].strip()
            if target in self.labels:
                disp = self.labels[target] - addr
            else:
                disp = self.parse_immediate(target)
                if disp is None:
                    self.pending_labels.append((addr, mnem, operands))
                    disp = 0
            return (opcode << 24) | (pos << 20) | (base << 16) | (disp & 0xFFF)

        # Bit test and modify: BBSS, BBCS, BBSC, BBCC
        if mnem in ('bbss', 'bbcs', 'bbsc', 'bbcc'):
            pos = self.parse_register(operands[0])
            base = self.parse_register(operands[1])
            target = operands[2].strip()
            if target in self.labels:
                disp = self.labels[target] - addr
            else:
                disp = self.parse_immediate(target)
                if disp is None:
                    self.pending_labels.append((addr, mnem, operands))
                    disp = 0
            return (opcode << 24) | (pos << 20) | (base << 16) | (disp & 0xFFFF)

        # Byte 2-operand: ADDB2, SUBB2, etc.
        if mnem in ('addb2', 'subb2'):
            src = self.parse_register(operands[0])
            dst = self.parse_register(operands[1])
            return (opcode << 24) | (src << 20) | (dst << 16)

        # Byte 3-operand: ADDB3, SUBB3
        if mnem in ('addb3', 'subb3'):
            src1 = self.parse_register(operands[0])
            src2 = self.parse_register(operands[1])
            dst = self.parse_register(operands[2])
            return (opcode << 24) | (src1 << 20) | (src2 << 16) | (dst << 12)

        # Word 2-operand: ADDW2, SUBW2, etc.
        if mnem in ('addw2', 'subw2'):
            src = self.parse_register(operands[0])
            dst = self.parse_register(operands[1])
            return (opcode << 24) | (src << 20) | (dst << 16)

        # Word 3-operand: ADDW3, SUBW3
        if mnem in ('addw3', 'subw3'):
            src1 = self.parse_register(operands[0])
            src2 = self.parse_register(operands[1])
            dst = self.parse_register(operands[2])
            return (opcode << 24) | (src1 << 20) | (src2 << 16) | (dst << 12)

        # Single-operand byte/word: INCB, DECB, CLRB, INCW, DECW, CLRW
        if mnem in ('incb', 'decb', 'clrb', 'incw', 'decw', 'clrw'):
            dst = self.parse_register(operands[0])
            return (opcode << 24) | (dst << 20)

        # 2-operand byte/word: MOVB, MOVW, TSTB, TSTW, MNEGB, MNEGW
        if mnem in ('movb', 'movw', 'tstb', 'tstw', 'mnegb', 'mnegw'):
            src = self.parse_register(operands[0])
            dst = self.parse_register(operands[1])
            return (opcode << 24) | (src << 20) | (dst << 16)

        # Compare byte/word: CMPB, CMPW
        if mnem in ('cmpb', 'cmpw'):
            src1 = self.parse_register(operands[0])
            src2 = self.parse_register(operands[1])
            dst = self.parse_register(operands[2])
            return (opcode << 24) | (src1 << 20) | (src2 << 16) | (dst << 12)

        # Zero-extend moves: MOVZBL, MOVZWL, MOVZBW
        if mnem in ('movzbl', 'movzwl', 'movzbw', 'cvtbw'):
            src = self.parse_register(operands[0])
            dst = self.parse_register(operands[1])
            return (opcode << 24) | (src << 20) | (dst << 16)

        # RET - no operands (return from procedure)
        if mnem == 'ret':
            return (opcode << 24)

        # CALLS - procedure call
        if mnem == 'calls':
            nargs = self.parse_immediate(operands[0])
            target_reg = self.parse_register(operands[1])
            return (opcode << 24) | ((nargs & 0xF) << 20) | (target_reg << 16)

        # BRW - branch word
        if mnem == 'brw':
            target = operands[0].strip()
            if target in self.labels:
                disp = self.labels[target] - addr
            else:
                disp = self.parse_immediate(target)
                if disp is None:
                    self.pending_labels.append((addr, mnem, operands))
                    disp = 0
            return (opcode << 24) | (disp & 0xFFFFFF)

        # EMUL - extended multiply
        if mnem == 'emul':
            src1 = self.parse_register(operands[0])
            src2 = self.parse_register(operands[1])
            dst = self.parse_register(operands[2])
            dst_hi = self.parse_register(operands[3])
            return (opcode << 24) | (src1 << 20) | (src2 << 16) | (dst << 12) | (dst_hi << 8)

        # EDIV - extended divide
        if mnem == 'ediv':
            divisor = self.parse_register(operands[0])
            dividend = self.parse_register(operands[1])
            quo = self.parse_register(operands[2])
            rem = self.parse_register(operands[3])
            return (opcode << 24) | (divisor << 20) | (dividend << 16) | (quo << 12) | (rem << 8)

        # FFS, FFC - find first set/clear
        if mnem in ('ffs', 'ffc'):
            src = self.parse_register(operands[0])
            dst = self.parse_register(operands[1])
            return (opcode << 24) | (src << 20) | (dst << 16)

        # EXTV, EXTZV - extract field
        if mnem in ('extv', 'extzv'):
            pos = self.parse_register(operands[0])
            size = self.parse_register(operands[1])
            base = self.parse_register(operands[2])
            dst = self.parse_register(operands[3])
            return (opcode << 24) | (pos << 20) | (size << 16) | (base << 12) | (dst << 8)

        # INSV - insert field
        if mnem == 'insv':
            src = self.parse_register(operands[0])
            pos = self.parse_register(operands[1])
            size = self.parse_register(operands[2])
            dst = self.parse_register(operands[3])
            return (opcode << 24) | (src << 20) | (pos << 16) | (size << 12) | (dst << 8)

        # INDEX - array index
        if mnem == 'index':
            subscript = self.parse_register(operands[0])
            size = self.parse_register(operands[1])
            base = self.parse_register(operands[2])
            dst = self.parse_register(operands[3])
            return (opcode << 24) | (subscript << 20) | (size << 16) | (base << 12) | (dst << 8)

        # CASEL - case dispatch
        if mnem == 'casel':
            selector = self.parse_register(operands[0])
            base = self.parse_register(operands[1])
            limit = self.parse_register(operands[2])
            return (opcode << 24) | (selector << 20) | (base << 16) | (limit << 12)

        # CASEB, CASEW - case byte/word
        if mnem in ('caseb', 'casew'):
            selector = self.parse_register(operands[0])
            base = self.parse_register(operands[1])
            limit = self.parse_immediate(operands[2])
            return (opcode << 24) | (selector << 20) | (base << 16) | ((limit & 0xFF) << 8)

        # ACB - Add Compare and Branch
        if mnem in ('acbb', 'acbw', 'acbl'):
            limit_reg = self.parse_register(operands[0])
            index_reg = self.parse_register(operands[1])
            add_val = self.parse_immediate(operands[2])
            target = operands[3].strip()
            if target in self.labels:
                disp = self.labels[target] - addr
            else:
                disp = self.parse_immediate(target)
                if disp is None:
                    self.pending_labels.append((addr, mnem, operands))
                    disp = 0
            return (opcode << 24) | (limit_reg << 20) | (index_reg << 16) | ((add_val & 0xFF) << 8) | (disp & 0xFF)

        # Move address: MOVAB, MOVAW, MOVAL
        if mnem in ('movab', 'movaw', 'moval'):
            base = self.parse_register(operands[0])
            dst = self.parse_register(operands[1])
            offset = self.parse_immediate(operands[2]) if len(operands) > 2 else 0
            return (opcode << 24) | (base << 20) | (dst << 16) | (offset & 0xFFFF)

        # Push address: PUSHAB, PUSHAW, PUSHAL
        if mnem in ('pushab', 'pushaw', 'pushal'):
            base = self.parse_register(operands[0])
            offset = self.parse_immediate(operands[1]) if len(operands) > 1 else 0
            return (opcode << 24) | (base << 20) | (offset & 0xFFFF)

        # Arithmetic with carry: ADWC, SBWC
        if mnem in ('adwc', 'sbwc'):
            src = self.parse_register(operands[0])
            dst = self.parse_register(operands[1])
            return (opcode << 24) | (src << 20) | (dst << 16)

        # Processor status: MOVPSL
        if mnem == 'movpsl':
            dst = self.parse_register(operands[0])
            return (opcode << 24) | (dst << 20)

        # BISPSW, BICPSW - bit set/clear in PSW
        if mnem in ('bispsw', 'bicpsw'):
            mask = self.parse_immediate(operands[0])
            return (opcode << 24) | ((mask & 0xFF) << 16)

        # REI - return from exception/interrupt
        if mnem == 'rei':
            return (opcode << 24)

        # BPT - breakpoint trap
        if mnem == 'bpt':
            return (opcode << 24)

        raise ValueError(f"Unhandled instruction: {mnemonic}")

    def first_pass(self, lines):
        """First pass: collect labels and their addresses."""
        addr = 0
        for line in lines:
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith('#') or line.startswith('//'):
                continue

            # Check for labels
            if ':' in line:
                label, rest = line.split(':', 1)
                label = label.strip()
                self.labels[label] = addr
                line = rest.strip()
                if not line:
                    continue

            # Check for directives
            if line.startswith('.'):
                parts = line.split()
                directive = parts[0].lower()
                if directive == '.word':
                    # Count number of words
                    for _ in parts[1:]:
                        addr += 4
                elif directive in ('.text', '.data', '.align', '.globl', '.global'):
                    pass  # Ignore these directives
                continue

            # Regular instruction
            if line:
                addr += 4

    def second_pass(self, lines):
        """Second pass: generate code."""
        addr = 0
        code = []

        for line in lines:
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith('#') or line.startswith('//'):
                continue

            # Skip labels (already processed)
            if ':' in line:
                _, line = line.split(':', 1)
                line = line.strip()
                if not line:
                    continue

            # Handle directives
            if line.startswith('.'):
                parts = line.split(None, 1)
                directive = parts[0].lower()
                if directive == '.word':
                    # Emit raw words
                    words_str = parts[1] if len(parts) > 1 else ''
                    for word_str in words_str.split(','):
                        word_str = word_str.strip()
                        if word_str:
                            word = self.parse_immediate(word_str)
                            if word is not None:
                                code.append((addr, word & 0xFFFFFFFF))
                                addr += 4
                continue

            # Parse instruction
            parts = re.split(r'[\s,]+', line, 1)
            mnemonic = parts[0].lower()
            operands = []
            if len(parts) > 1:
                # Split operands by comma, but preserve parentheses content
                op_str = parts[1]
                operands = [o.strip() for o in re.split(r',(?![^()]*\))', op_str)]

            word = self.encode_instruction(mnemonic, operands, addr)
            code.append((addr, word))
            addr += 4

        return code

    def assemble(self, text):
        """Assemble the given text."""
        lines = text.split('\n')
        self.first_pass(lines)
        return self.second_pass(lines)


def main():
    parser = argparse.ArgumentParser(description='MicroVAX Assembler')
    parser.add_argument('input', help='Input assembly file')
    parser.add_argument('-o', '--output', help='Output hex file')
    parser.add_argument('-b', '--binary', action='store_true',
                       help='Output binary instead of hex')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Verbose output')
    args = parser.parse_args()

    # Read input
    with open(args.input, 'r') as f:
        text = f.read()

    # Assemble
    asm = MicroVAXAssembler()
    try:
        code = asm.assemble(text)
    except Exception as e:
        print(f"Assembly error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"Labels: {asm.labels}")
        for addr, word in code:
            print(f"  {addr:04x}: {word:08x}")

    # Determine output file
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = Path(args.input).with_suffix('.hex')

    # Write output
    with open(out_path, 'w') as f:
        for addr, word in code:
            # Write in Verilog $readmemh format (address @XX followed by data)
            # Write words in big-endian format
            f.write(f"{word:08X}\n")

    if args.verbose:
        print(f"Wrote {len(code)} words to {out_path}")


if __name__ == '__main__':
    main()
