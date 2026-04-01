#!/usr/bin/env python3
"""
Complete PDP-11/70 ISA Generator with All Addressing Modes

The PDP-11 has 8 addressing modes:
  0: Register         Rn          - operand is in register
  1: Register Deferred @Rn        - register contains address
  2: Autoincrement    (Rn)+       - register contains address, then increment
  3: Autoincrement Deferred @(Rn)+ - register contains pointer to address
  4: Autodecrement    -(Rn)       - decrement register, then use as address
  5: Autodecrement Deferred @-(Rn) - decrement, then use as pointer to address
  6: Index            X(Rn)       - address is register + offset word
  7: Index Deferred   @X(Rn)      - pointer is register + offset word

Special cases with R7 (PC):
  Mode 2, R7: Immediate #n        - value follows instruction
  Mode 3, R7: Absolute @#addr     - address follows instruction
  Mode 6, R7: Relative addr       - PC-relative offset
  Mode 7, R7: Relative Deferred @addr - PC-relative pointer
"""

import os
import sys

# Common header for all ISA files
COMMON_HEADER = '''isa_state pc[15:0];
var instr[15:0];
isa_state rf[15:0][2:0];  // 8 registers, R7 is PC
isa_state umem[7:0][15:0];      // Byte-addressable memory
isa_state flag_N[0:0];
isa_state flag_Z[0:0];
isa_state flag_V[0:0];
isa_state flag_C[0:0];
'''

SYSTEM_HEADER = '''isa_state pc[15:0];
var instr[15:0];
isa_state rf[15:0][2:0];
isa_state umem[7:0][15:0];
isa_state flag_N[0:0];
isa_state flag_Z[0:0];
isa_state flag_V[0:0];
isa_state flag_C[0:0];
isa_state halted[0:0];
isa_state waiting[0:0];
isa_state priority[2:0];
'''

FETCH_INSTR = '''
// Fetch instruction (little-endian)
var instr_lo[7:0];
var instr_hi[7:0];
instr_lo = umem[pc];
instr_hi = umem[pc + 1];
instr = {instr_hi, instr_lo};
'''


def generate_double_op_rr(name, opcode_hi, operation, flags, is_byte=False):
    """Generate register-to-register double operand instruction"""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'
    sign_bit = '7' if is_byte else '15'

    content = f'''// PDP-11 {name}{b} instruction - Register to Register
// Opcode: {opcode_hi:02o}xxxx, src mode 0, dst mode 0

{COMMON_HEADER}
var src_reg[2:0];
var dst_reg[2:0];
var src_val[{width}];
var dst_val[{width}];
var result[{width}];

{FETCH_INSTR}

assume instr[15:12] == 0b{opcode_hi:04b};  // {name}{b} opcode
assume instr[11:9] == 0b000;    // Source mode 0 (register)
assume instr[5:3] == 0b000;     // Dest mode 0 (register)

src_reg = instr[8:6];
dst_reg = instr[2:0];

pc = pc + 2;

'''
    if is_byte:
        content += f'''src_val = rf[src_reg][7:0];
dst_val = rf[dst_reg][7:0];

{operation}

// Sign-extend byte result to word for register destination
var extended[15:0];
extended = result[7] ? {{8'hFF, result}} : {{8'h00, result}};
rf[dst_reg] when (dst_reg != 7) = extended;

'''
    else:
        content += f'''src_val = src_reg == 7 ? pc : rf[src_reg];
dst_val = dst_reg == 7 ? pc : rf[dst_reg];

{operation}

rf[dst_reg] when (dst_reg != 7) = result;
pc when (dst_reg == 7) = result;

'''
    content += flags
    return content


def generate_double_op_imm_r(name, opcode_hi, operation, flags, is_byte=False):
    """Generate immediate-to-register double operand instruction"""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'

    content = f'''// PDP-11 {name}{b} instruction - Immediate to Register
// Source: mode 2, reg 7 (PC) = immediate

{COMMON_HEADER}
var dst_reg[2:0];
var src_val[{width}];
var dst_val[{width}];
var result[{width}];
var imm_lo[7:0];
var imm_hi[7:0];

{FETCH_INSTR}

assume instr[15:12] == 0b{opcode_hi:04b};  // {name}{b} opcode
assume instr[11:9] == 0b010;    // Source mode 2 (autoincrement)
assume instr[8:6] == 0b111;     // Source reg 7 (PC) = immediate
assume instr[5:3] == 0b000;     // Dest mode 0 (register)

dst_reg = instr[2:0];

pc = pc + 2;

// Fetch immediate value
imm_lo = umem[pc];
imm_hi = umem[pc + 1];
pc = pc + 2;

'''
    if is_byte:
        content += f'''src_val = imm_lo;
dst_val = rf[dst_reg][7:0];

{operation}

var extended[15:0];
extended = result[7] ? {{8'hFF, result}} : {{8'h00, result}};
rf[dst_reg] when (dst_reg != 7) = extended;

'''
    else:
        content += f'''src_val = {{imm_hi, imm_lo}};
dst_val = dst_reg == 7 ? pc : rf[dst_reg];

{operation}

rf[dst_reg] when (dst_reg != 7) = result;
pc when (dst_reg == 7) = result;

'''
    content += flags
    return content


def generate_double_op_r_d(name, opcode_hi, operation, flags, is_byte=False):
    """Generate register to deferred (store through pointer)"""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'

    content = f'''// PDP-11 {name}{b} instruction - Register to Deferred
// Store to memory via register pointer

{COMMON_HEADER}
var src_reg[2:0];
var dst_reg[2:0];
var src_val[{width}];
var dst_addr[15:0];
var dst_val[{width}];
var result[{width}];

{FETCH_INSTR}

assume instr[15:12] == 0b{opcode_hi:04b};  // {name}{b} opcode
assume instr[11:9] == 0b000;    // Source mode 0 (register)
assume instr[5:3] == 0b001;     // Dest mode 1 (register deferred)

src_reg = instr[8:6];
dst_reg = instr[2:0];

pc = pc + 2;

dst_addr = dst_reg == 7 ? pc : rf[dst_reg];

'''
    if is_byte:
        content += f'''src_val = rf[src_reg][7:0];
dst_val = umem[dst_addr];

{operation}

umem[dst_addr] = result;

'''
    else:
        content += f'''src_val = src_reg == 7 ? pc : rf[src_reg];

var dst_lo[7:0];
var dst_hi[7:0];
dst_lo = umem[dst_addr];
dst_hi = umem[dst_addr + 1];
dst_val = {{dst_hi, dst_lo}};

{operation}

umem[dst_addr] = result[7:0];
umem[dst_addr + 1] = result[15:8];

'''
    content += flags
    return content


def generate_double_op_d_r(name, opcode_hi, operation, flags, is_byte=False):
    """Generate deferred to register (load through pointer)"""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'

    content = f'''// PDP-11 {name}{b} instruction - Deferred to Register
// Load from memory via register pointer

{COMMON_HEADER}
var src_reg[2:0];
var dst_reg[2:0];
var src_addr[15:0];
var src_val[{width}];
var dst_val[{width}];
var result[{width}];

{FETCH_INSTR}

assume instr[15:12] == 0b{opcode_hi:04b};  // {name}{b} opcode
assume instr[11:9] == 0b001;    // Source mode 1 (register deferred)
assume instr[5:3] == 0b000;     // Dest mode 0 (register)

src_reg = instr[8:6];
dst_reg = instr[2:0];

pc = pc + 2;

src_addr = src_reg == 7 ? pc : rf[src_reg];

'''
    if is_byte:
        content += f'''src_val = umem[src_addr];
dst_val = rf[dst_reg][7:0];

{operation}

var extended[15:0];
extended = result[7] ? {{8'hFF, result}} : {{8'h00, result}};
rf[dst_reg] when (dst_reg != 7) = extended;

'''
    else:
        content += f'''var src_lo[7:0];
var src_hi[7:0];
src_lo = umem[src_addr];
src_hi = umem[src_addr + 1];
src_val = {{src_hi, src_lo}};
dst_val = dst_reg == 7 ? pc : rf[dst_reg];

{operation}

rf[dst_reg] when (dst_reg != 7) = result;
pc when (dst_reg == 7) = result;

'''
    content += flags
    return content


def generate_double_op_idx_r(name, opcode_hi, operation, flags, is_byte=False):
    """Generate indexed to register"""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'

    content = f'''// PDP-11 {name}{b} instruction - Indexed to Register
// Source: base + offset, Dest: register

{COMMON_HEADER}
var src_reg[2:0];
var dst_reg[2:0];
var offset[15:0];
var base_addr[15:0];
var src_addr[15:0];
var src_val[{width}];
var dst_val[{width}];
var result[{width}];
var off_lo[7:0];
var off_hi[7:0];

{FETCH_INSTR}

assume instr[15:12] == 0b{opcode_hi:04b};  // {name}{b} opcode
assume instr[11:9] == 0b110;    // Source mode 6 (indexed)
assume instr[5:3] == 0b000;     // Dest mode 0 (register)

src_reg = instr[8:6];
dst_reg = instr[2:0];

pc = pc + 2;

// Fetch offset
off_lo = umem[pc];
off_hi = umem[pc + 1];
offset = {{off_hi, off_lo}};
pc = pc + 2;

base_addr = src_reg == 7 ? pc : rf[src_reg];
src_addr = base_addr + offset;

'''
    if is_byte:
        content += f'''src_val = umem[src_addr];
dst_val = rf[dst_reg][7:0];

{operation}

var extended[15:0];
extended = result[7] ? {{8'hFF, result}} : {{8'h00, result}};
rf[dst_reg] when (dst_reg != 7) = extended;

'''
    else:
        content += f'''var src_lo[7:0];
var src_hi[7:0];
src_lo = umem[src_addr];
src_hi = umem[src_addr + 1];
src_val = {{src_hi, src_lo}};
dst_val = dst_reg == 7 ? pc : rf[dst_reg];

{operation}

rf[dst_reg] when (dst_reg != 7) = result;
pc when (dst_reg == 7) = result;

'''
    content += flags
    return content


def generate_double_op_r_idx(name, opcode_hi, operation, flags, is_byte=False):
    """Generate register to indexed"""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'

    content = f'''// PDP-11 {name}{b} instruction - Register to Indexed
// Source: register, Dest: base + offset

{COMMON_HEADER}
var src_reg[2:0];
var dst_reg[2:0];
var src_val[{width}];
var offset[15:0];
var base_addr[15:0];
var dst_addr[15:0];
var dst_val[{width}];
var result[{width}];
var off_lo[7:0];
var off_hi[7:0];

{FETCH_INSTR}

assume instr[15:12] == 0b{opcode_hi:04b};  // {name}{b} opcode
assume instr[11:9] == 0b000;    // Source mode 0 (register)
assume instr[5:3] == 0b110;     // Dest mode 6 (indexed)

src_reg = instr[8:6];
dst_reg = instr[2:0];

pc = pc + 2;

// Fetch offset
off_lo = umem[pc];
off_hi = umem[pc + 1];
offset = {{off_hi, off_lo}};
pc = pc + 2;

base_addr = dst_reg == 7 ? pc : rf[dst_reg];
dst_addr = base_addr + offset;

'''
    if is_byte:
        content += f'''src_val = rf[src_reg][7:0];
dst_val = umem[dst_addr];

{operation}

umem[dst_addr] = result;

'''
    else:
        content += f'''src_val = src_reg == 7 ? pc : rf[src_reg];

var dst_lo[7:0];
var dst_hi[7:0];
dst_lo = umem[dst_addr];
dst_hi = umem[dst_addr + 1];
dst_val = {{dst_hi, dst_lo}};

{operation}

umem[dst_addr] = result[7:0];
umem[dst_addr + 1] = result[15:8];

'''
    content += flags
    return content


def generate_double_op_ai_r(name, opcode_hi, operation, flags, is_byte=False):
    """Generate autoincrement to register"""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'
    # PDP-11 byte-mode rule: R6 (SP) always steps by 2, others by 1
    inc = '((src_reg == 6) ? 2 : 1)' if is_byte else '2'

    content = f'''// PDP-11 {name}{b} instruction - Autoincrement to Register
// Source: (Rn)+, Dest: register

{COMMON_HEADER}
var src_reg[2:0];
var dst_reg[2:0];
var src_addr[15:0];
var src_val[{width}];
var dst_val[{width}];
var result[{width}];

{FETCH_INSTR}

assume instr[15:12] == 0b{opcode_hi:04b};  // {name}{b} opcode
assume instr[11:9] == 0b010;    // Source mode 2 (autoincrement)
assume instr[8:6] != 0b111;     // Source reg != 7 (not immediate)
assume instr[5:3] == 0b000;     // Dest mode 0 (register)

src_reg = instr[8:6];
dst_reg = instr[2:0];

pc = pc + 2;

src_addr = rf[src_reg];
rf[src_reg] when (src_reg != 7) = rf[src_reg] + {inc};

'''
    if is_byte:
        content += f'''src_val = umem[src_addr];
dst_val = rf[dst_reg][7:0];

{operation}

var extended[15:0];
extended = result[7] ? {{8'hFF, result}} : {{8'h00, result}};
rf[dst_reg] when (dst_reg != 7) = extended;

'''
    else:
        content += f'''var src_lo[7:0];
var src_hi[7:0];
src_lo = umem[src_addr];
src_hi = umem[src_addr + 1];
src_val = {{src_hi, src_lo}};
dst_val = dst_reg == 7 ? pc : rf[dst_reg];

{operation}

rf[dst_reg] when (dst_reg != 7) = result;
pc when (dst_reg == 7) = result;

'''
    content += flags
    return content


def generate_double_op_ad_r(name, opcode_hi, operation, flags, is_byte=False):
    """Generate autodecrement to register"""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'
    # PDP-11 byte-mode rule: R6 (SP) always steps by 2, others by 1
    dec = '((src_reg == 6) ? 2 : 1)' if is_byte else '2'

    content = f'''// PDP-11 {name}{b} instruction - Autodecrement to Register
// Source: -(Rn), Dest: register

{COMMON_HEADER}
var src_reg[2:0];
var dst_reg[2:0];
var src_addr[15:0];
var src_val[{width}];
var dst_val[{width}];
var result[{width}];

{FETCH_INSTR}

assume instr[15:12] == 0b{opcode_hi:04b};  // {name}{b} opcode
assume instr[11:9] == 0b100;    // Source mode 4 (autodecrement)
assume instr[5:3] == 0b000;     // Dest mode 0 (register)

src_reg = instr[8:6];
dst_reg = instr[2:0];

pc = pc + 2;

// Decrement first, then use as address
src_addr = rf[src_reg] - {dec};
rf[src_reg] when (src_reg != 7) = src_addr;

'''
    if is_byte:
        content += f'''src_val = umem[src_addr];
dst_val = rf[dst_reg][7:0];

{operation}

var extended[15:0];
extended = result[7] ? {{8'hFF, result}} : {{8'h00, result}};
rf[dst_reg] when (dst_reg != 7) = extended;

'''
    else:
        content += f'''var src_lo[7:0];
var src_hi[7:0];
src_lo = umem[src_addr];
src_hi = umem[src_addr + 1];
src_val = {{src_hi, src_lo}};
dst_val = dst_reg == 7 ? pc : rf[dst_reg];

{operation}

rf[dst_reg] when (dst_reg != 7) = result;
pc when (dst_reg == 7) = result;

'''
    content += flags
    return content


def generate_double_op_aid_r(name, opcode_hi, operation, flags, is_byte=False):
    """Generate autoincrement deferred to register (mode 3)"""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'

    content = f'''// PDP-11 {name}{b} instruction - Autoincrement Deferred to Register
// Source: @(Rn)+, Dest: register

{COMMON_HEADER}
var src_reg[2:0];
var dst_reg[2:0];
var ptr_addr[15:0];
var src_addr[15:0];
var src_val[{width}];
var dst_val[{width}];
var result[{width}];
var ptr_lo[7:0];
var ptr_hi[7:0];

{FETCH_INSTR}

assume instr[15:12] == 0b{opcode_hi:04b};  // {name}{b} opcode
assume instr[11:9] == 0b011;    // Source mode 3 (autoincrement deferred)
assume instr[5:3] == 0b000;     // Dest mode 0 (register)

src_reg = instr[8:6];
dst_reg = instr[2:0];

pc = pc + 2;

// Get pointer address, increment by 2 (always word for pointer)
ptr_addr = rf[src_reg];
rf[src_reg] when (src_reg != 7) = rf[src_reg] + 2;

// Fetch actual address from pointer
ptr_lo = umem[ptr_addr];
ptr_hi = umem[ptr_addr + 1];
src_addr = {{ptr_hi, ptr_lo}};

'''
    if is_byte:
        content += f'''src_val = umem[src_addr];
dst_val = rf[dst_reg][7:0];

{operation}

var extended[15:0];
extended = result[7] ? {{8'hFF, result}} : {{8'h00, result}};
rf[dst_reg] when (dst_reg != 7) = extended;

'''
    else:
        content += f'''var src_lo[7:0];
var src_hi[7:0];
src_lo = umem[src_addr];
src_hi = umem[src_addr + 1];
src_val = {{src_hi, src_lo}};
dst_val = dst_reg == 7 ? pc : rf[dst_reg];

{operation}

rf[dst_reg] when (dst_reg != 7) = result;
pc when (dst_reg == 7) = result;

'''
    content += flags
    return content


def generate_double_op_add_r(name, opcode_hi, operation, flags, is_byte=False):
    """Generate autodecrement deferred to register (mode 5)"""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'

    content = f'''// PDP-11 {name}{b} instruction - Autodecrement Deferred to Register
// Source: @-(Rn), Dest: register

{COMMON_HEADER}
var src_reg[2:0];
var dst_reg[2:0];
var ptr_addr[15:0];
var src_addr[15:0];
var src_val[{width}];
var dst_val[{width}];
var result[{width}];
var ptr_lo[7:0];
var ptr_hi[7:0];

{FETCH_INSTR}

assume instr[15:12] == 0b{opcode_hi:04b};  // {name}{b} opcode
assume instr[11:9] == 0b101;    // Source mode 5 (autodecrement deferred)
assume instr[5:3] == 0b000;     // Dest mode 0 (register)

src_reg = instr[8:6];
dst_reg = instr[2:0];

pc = pc + 2;

// Decrement by 2 (always word for pointer), get pointer address
ptr_addr = rf[src_reg] - 2;
rf[src_reg] when (src_reg != 7) = ptr_addr;

// Fetch actual address from pointer
ptr_lo = umem[ptr_addr];
ptr_hi = umem[ptr_addr + 1];
src_addr = {{ptr_hi, ptr_lo}};

'''
    if is_byte:
        content += f'''src_val = umem[src_addr];
dst_val = rf[dst_reg][7:0];

{operation}

var extended[15:0];
extended = result[7] ? {{8'hFF, result}} : {{8'h00, result}};
rf[dst_reg] when (dst_reg != 7) = extended;

'''
    else:
        content += f'''var src_lo[7:0];
var src_hi[7:0];
src_lo = umem[src_addr];
src_hi = umem[src_addr + 1];
src_val = {{src_hi, src_lo}};
dst_val = dst_reg == 7 ? pc : rf[dst_reg];

{operation}

rf[dst_reg] when (dst_reg != 7) = result;
pc when (dst_reg == 7) = result;

'''
    content += flags
    return content


def generate_double_op_idxd_r(name, opcode_hi, operation, flags, is_byte=False):
    """Generate index deferred to register (mode 7)"""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'

    content = f'''// PDP-11 {name}{b} instruction - Index Deferred to Register
// Source: @X(Rn), Dest: register

{COMMON_HEADER}
var src_reg[2:0];
var dst_reg[2:0];
var offset[15:0];
var base_addr[15:0];
var ptr_addr[15:0];
var src_addr[15:0];
var src_val[{width}];
var dst_val[{width}];
var result[{width}];
var off_lo[7:0];
var off_hi[7:0];
var ptr_lo[7:0];
var ptr_hi[7:0];

{FETCH_INSTR}

assume instr[15:12] == 0b{opcode_hi:04b};  // {name}{b} opcode
assume instr[11:9] == 0b111;    // Source mode 7 (index deferred)
assume instr[5:3] == 0b000;     // Dest mode 0 (register)

src_reg = instr[8:6];
dst_reg = instr[2:0];

pc = pc + 2;

// Fetch offset
off_lo = umem[pc];
off_hi = umem[pc + 1];
offset = {{off_hi, off_lo}};
pc = pc + 2;

// Calculate pointer address
base_addr = src_reg == 7 ? pc : rf[src_reg];
ptr_addr = base_addr + offset;

// Fetch actual address from pointer
ptr_lo = umem[ptr_addr];
ptr_hi = umem[ptr_addr + 1];
src_addr = {{ptr_hi, ptr_lo}};

'''
    if is_byte:
        content += f'''src_val = umem[src_addr];
dst_val = rf[dst_reg][7:0];

{operation}

var extended[15:0];
extended = result[7] ? {{8'hFF, result}} : {{8'h00, result}};
rf[dst_reg] when (dst_reg != 7) = extended;

'''
    else:
        content += f'''var src_lo[7:0];
var src_hi[7:0];
src_lo = umem[src_addr];
src_hi = umem[src_addr + 1];
src_val = {{src_hi, src_lo}};
dst_val = dst_reg == 7 ? pc : rf[dst_reg];

{operation}

rf[dst_reg] when (dst_reg != 7) = result;
pc when (dst_reg == 7) = result;

'''
    content += flags
    return content


##############################################################################
# Generic addressing mode helpers for complete ISA coverage
##############################################################################

# Mode name mapping for file naming
SRC_MODE_NAMES = {
    0: 'r', 1: 'd', 2: 'ai', 3: 'aid', 4: 'ad', 5: 'add', 6: 'idx', 7: 'idxd',
}
DST_MODE_NAMES = {
    0: 'r', 1: 'd', 2: 'ai', 3: 'aid', 4: 'ad', 5: 'add', 6: 'idx', 7: 'idxd',
}
MODE_DESCRIPTIONS = {
    0: 'Register', 1: 'Register Deferred', 2: 'Autoincrement',
    3: 'Autoincrement Deferred', 4: 'Autodecrement',
    5: 'Autodecrement Deferred', 6: 'Indexed', 7: 'Index Deferred',
}


def _gen_src_fetch(src_mode, is_byte):
    """Generate source operand fetch code and variable declarations.

    Returns (extra_vars, assume_lines, fetch_code) where:
    - extra_vars: list of variable declaration strings
    - assume_lines: list of assume constraint strings
    - fetch_code: string of code to fetch src_val
    """
    width = '7:0' if is_byte else '15:0'
    # PDP-11 byte-mode rule: R6 (SP) and R7 (PC) always step by 2, others by 1
    src_inc = '((src_reg == 6) ? 2 : 1)' if is_byte else '2'
    extra_vars = []
    assumes = []
    code = ''

    if src_mode == 0:  # Register
        assumes.append('assume instr[11:9] == 0b000;    // Source mode 0 (register)')
        if is_byte:
            code = 'src_val = rf[src_reg][7:0];\n'
        else:
            code = 'src_val = src_reg == 7 ? pc : rf[src_reg];\n'

    elif src_mode == 1:  # Register deferred
        extra_vars.append('var src_addr[15:0];')
        assumes.append('assume instr[11:9] == 0b001;    // Source mode 1 (register deferred)')
        code = 'src_addr = src_reg == 7 ? pc : rf[src_reg];\n'
        if is_byte:
            code += 'src_val = umem[src_addr];\n'
        else:
            extra_vars.extend(['var src_lo[7:0];', 'var src_hi[7:0];'])
            code += 'src_lo = umem[src_addr];\nsrc_hi = umem[src_addr + 1];\nsrc_val = {src_hi, src_lo};\n'

    elif src_mode == 2:  # Autoincrement (non-PC)
        extra_vars.append('var src_addr[15:0];')
        assumes.append('assume instr[11:9] == 0b010;    // Source mode 2 (autoincrement)')
        assumes.append('assume instr[8:6] != 0b111;     // Source reg != 7 (not immediate)')
        code = f'src_addr = rf[src_reg];\nrf[src_reg] = rf[src_reg] + {src_inc};\n'
        if is_byte:
            code += 'src_val = umem[src_addr];\n'
        else:
            extra_vars.extend(['var src_lo[7:0];', 'var src_hi[7:0];'])
            code += 'src_lo = umem[src_addr];\nsrc_hi = umem[src_addr + 1];\nsrc_val = {src_hi, src_lo};\n'

    elif src_mode == 3:  # Autoincrement deferred
        extra_vars.extend(['var ptr_addr[15:0];', 'var src_addr[15:0];', 'var ptr_lo[7:0];', 'var ptr_hi[7:0];'])
        assumes.append('assume instr[11:9] == 0b011;    // Source mode 3 (autoincrement deferred)')
        code = '// Get pointer address, increment by 2 (always word for pointer)\n'
        code += 'ptr_addr = rf[src_reg];\nrf[src_reg] when (src_reg != 7) = rf[src_reg] + 2;\n'
        code += '// Fetch actual address from pointer\n'
        code += 'ptr_lo = umem[ptr_addr];\nptr_hi = umem[ptr_addr + 1];\nsrc_addr = {ptr_hi, ptr_lo};\n'
        if is_byte:
            code += 'src_val = umem[src_addr];\n'
        else:
            extra_vars.extend(['var src_lo[7:0];', 'var src_hi[7:0];'])
            code += 'src_lo = umem[src_addr];\nsrc_hi = umem[src_addr + 1];\nsrc_val = {src_hi, src_lo};\n'

    elif src_mode == 4:  # Autodecrement
        extra_vars.append('var src_addr[15:0];')
        assumes.append('assume instr[11:9] == 0b100;    // Source mode 4 (autodecrement)')
        code = f'// Decrement first, then use as address\nsrc_addr = rf[src_reg] - {src_inc};\nrf[src_reg] when (src_reg != 7) = src_addr;\n'
        if is_byte:
            code += 'src_val = umem[src_addr];\n'
        else:
            extra_vars.extend(['var src_lo[7:0];', 'var src_hi[7:0];'])
            code += 'src_lo = umem[src_addr];\nsrc_hi = umem[src_addr + 1];\nsrc_val = {src_hi, src_lo};\n'

    elif src_mode == 5:  # Autodecrement deferred
        extra_vars.extend(['var ptr_addr[15:0];', 'var src_addr[15:0];', 'var ptr_lo[7:0];', 'var ptr_hi[7:0];'])
        assumes.append('assume instr[11:9] == 0b101;    // Source mode 5 (autodecrement deferred)')
        code = '// Decrement by 2 (always word for pointer), get pointer address\n'
        code += 'ptr_addr = rf[src_reg] - 2;\nrf[src_reg] when (src_reg != 7) = ptr_addr;\n'
        code += '// Fetch actual address from pointer\n'
        code += 'ptr_lo = umem[ptr_addr];\nptr_hi = umem[ptr_addr + 1];\nsrc_addr = {ptr_hi, ptr_lo};\n'
        if is_byte:
            code += 'src_val = umem[src_addr];\n'
        else:
            extra_vars.extend(['var src_lo[7:0];', 'var src_hi[7:0];'])
            code += 'src_lo = umem[src_addr];\nsrc_hi = umem[src_addr + 1];\nsrc_val = {src_hi, src_lo};\n'

    elif src_mode == 6:  # Index
        extra_vars.extend(['var src_offset[15:0];', 'var base_addr[15:0];', 'var src_addr[15:0];',
                          'var soff_lo[7:0];', 'var soff_hi[7:0];'])
        assumes.append('assume instr[11:9] == 0b110;    // Source mode 6 (indexed)')
        code = '// Fetch source offset\nsoff_lo = umem[pc];\nsoff_hi = umem[pc + 1];\nsrc_offset = {soff_hi, soff_lo};\npc = pc + 2;\n'
        code += 'base_addr = src_reg == 7 ? pc : rf[src_reg];\nsrc_addr = base_addr + src_offset;\n'
        if is_byte:
            code += 'src_val = umem[src_addr];\n'
        else:
            extra_vars.extend(['var src_lo[7:0];', 'var src_hi[7:0];'])
            code += 'src_lo = umem[src_addr];\nsrc_hi = umem[src_addr + 1];\nsrc_val = {src_hi, src_lo};\n'

    elif src_mode == 7:  # Index deferred
        extra_vars.extend(['var src_offset[15:0];', 'var base_addr[15:0];',
                          'var ptr_addr[15:0];', 'var src_addr[15:0];',
                          'var soff_lo[7:0];', 'var soff_hi[7:0];',
                          'var ptr_lo[7:0];', 'var ptr_hi[7:0];'])
        assumes.append('assume instr[11:9] == 0b111;    // Source mode 7 (index deferred)')
        code = '// Fetch source offset\nsoff_lo = umem[pc];\nsoff_hi = umem[pc + 1];\nsrc_offset = {soff_hi, soff_lo};\npc = pc + 2;\n'
        code += '// Calculate pointer address\nbase_addr = src_reg == 7 ? pc : rf[src_reg];\nptr_addr = base_addr + src_offset;\n'
        code += '// Fetch actual address from pointer\nptr_lo = umem[ptr_addr];\nptr_hi = umem[ptr_addr + 1];\nsrc_addr = {ptr_hi, ptr_lo};\n'
        if is_byte:
            code += 'src_val = umem[src_addr];\n'
        else:
            extra_vars.extend(['var src_lo[7:0];', 'var src_hi[7:0];'])
            code += 'src_lo = umem[src_addr];\nsrc_hi = umem[src_addr + 1];\nsrc_val = {src_hi, src_lo};\n'

    return extra_vars, assumes, code


def _gen_dst_fetch(dst_mode, is_byte):
    """Generate destination operand fetch code and variable declarations.

    Returns (extra_vars, assume_lines, fetch_code) for reading the dst value.
    """
    width = '7:0' if is_byte else '15:0'
    # PDP-11 byte-mode rule: R6 (SP) and R7 (PC) always step by 2, others by 1
    dst_inc = '((dst_reg == 6) ? 2 : 1)' if is_byte else '2'
    extra_vars = []
    assumes = []
    code = ''

    if dst_mode == 0:  # Register
        assumes.append('assume instr[5:3] == 0b000;     // Dest mode 0 (register)')
        if is_byte:
            code = 'dst_val = rf[dst_reg][7:0];\n'
        else:
            code = 'dst_val = dst_reg == 7 ? pc : rf[dst_reg];\n'

    elif dst_mode == 1:  # Register deferred
        extra_vars.append('var dst_addr[15:0];')
        assumes.append('assume instr[5:3] == 0b001;     // Dest mode 1 (register deferred)')
        code = 'dst_addr = dst_reg == 7 ? pc : rf[dst_reg];\n'
        if is_byte:
            code += 'dst_val = umem[dst_addr];\n'
        else:
            extra_vars.extend(['var dst_lo[7:0];', 'var dst_hi[7:0];'])
            code += 'dst_lo = umem[dst_addr];\ndst_hi = umem[dst_addr + 1];\ndst_val = {dst_hi, dst_lo};\n'

    elif dst_mode == 2:  # Autoincrement
        extra_vars.append('var dst_addr[15:0];')
        assumes.append('assume instr[5:3] == 0b010;     // Dest mode 2 (autoincrement)')
        code = f'dst_addr = rf[dst_reg];\nrf[dst_reg] when (dst_reg != 7) = rf[dst_reg] + {dst_inc};\n'
        if is_byte:
            code += 'dst_val = umem[dst_addr];\n'
        else:
            extra_vars.extend(['var dst_lo[7:0];', 'var dst_hi[7:0];'])
            code += 'dst_lo = umem[dst_addr];\ndst_hi = umem[dst_addr + 1];\ndst_val = {dst_hi, dst_lo};\n'

    elif dst_mode == 3:  # Autoincrement deferred
        extra_vars.extend(['var dptr_addr[15:0];', 'var dst_addr[15:0];', 'var dptr_lo[7:0];', 'var dptr_hi[7:0];'])
        assumes.append('assume instr[5:3] == 0b011;     // Dest mode 3 (autoincrement deferred)')
        code = 'dptr_addr = rf[dst_reg];\nrf[dst_reg] when (dst_reg != 7) = rf[dst_reg] + 2;\n'
        code += 'dptr_lo = umem[dptr_addr];\ndptr_hi = umem[dptr_addr + 1];\ndst_addr = {dptr_hi, dptr_lo};\n'
        if is_byte:
            code += 'dst_val = umem[dst_addr];\n'
        else:
            extra_vars.extend(['var dst_lo[7:0];', 'var dst_hi[7:0];'])
            code += 'dst_lo = umem[dst_addr];\ndst_hi = umem[dst_addr + 1];\ndst_val = {dst_hi, dst_lo};\n'

    elif dst_mode == 4:  # Autodecrement
        extra_vars.append('var dst_addr[15:0];')
        assumes.append('assume instr[5:3] == 0b100;     // Dest mode 4 (autodecrement)')
        code = f'dst_addr = rf[dst_reg] - {dst_inc};\nrf[dst_reg] when (dst_reg != 7) = dst_addr;\n'
        if is_byte:
            code += 'dst_val = umem[dst_addr];\n'
        else:
            extra_vars.extend(['var dst_lo[7:0];', 'var dst_hi[7:0];'])
            code += 'dst_lo = umem[dst_addr];\ndst_hi = umem[dst_addr + 1];\ndst_val = {dst_hi, dst_lo};\n'

    elif dst_mode == 5:  # Autodecrement deferred
        extra_vars.extend(['var dptr_addr[15:0];', 'var dst_addr[15:0];', 'var dptr_lo[7:0];', 'var dptr_hi[7:0];'])
        assumes.append('assume instr[5:3] == 0b101;     // Dest mode 5 (autodecrement deferred)')
        code = 'dptr_addr = rf[dst_reg] - 2;\nrf[dst_reg] when (dst_reg != 7) = dptr_addr;\n'
        code += 'dptr_lo = umem[dptr_addr];\ndptr_hi = umem[dptr_addr + 1];\ndst_addr = {dptr_hi, dptr_lo};\n'
        if is_byte:
            code += 'dst_val = umem[dst_addr];\n'
        else:
            extra_vars.extend(['var dst_lo[7:0];', 'var dst_hi[7:0];'])
            code += 'dst_lo = umem[dst_addr];\ndst_hi = umem[dst_addr + 1];\ndst_val = {dst_hi, dst_lo};\n'

    elif dst_mode == 6:  # Index
        extra_vars.extend(['var dst_offset[15:0];', 'var dst_base[15:0];', 'var dst_addr[15:0];',
                          'var doff_lo[7:0];', 'var doff_hi[7:0];'])
        assumes.append('assume instr[5:3] == 0b110;     // Dest mode 6 (indexed)')
        code = '// Fetch destination offset\ndoff_lo = umem[pc];\ndoff_hi = umem[pc + 1];\ndst_offset = {doff_hi, doff_lo};\npc = pc + 2;\n'
        code += 'dst_base = dst_reg == 7 ? pc : rf[dst_reg];\ndst_addr = dst_base + dst_offset;\n'
        if is_byte:
            code += 'dst_val = umem[dst_addr];\n'
        else:
            extra_vars.extend(['var dst_lo[7:0];', 'var dst_hi[7:0];'])
            code += 'dst_lo = umem[dst_addr];\ndst_hi = umem[dst_addr + 1];\ndst_val = {dst_hi, dst_lo};\n'

    elif dst_mode == 7:  # Index deferred
        extra_vars.extend(['var dst_offset[15:0];', 'var dst_base[15:0];',
                          'var dptr_addr[15:0];', 'var dst_addr[15:0];',
                          'var doff_lo[7:0];', 'var doff_hi[7:0];',
                          'var dptr_lo[7:0];', 'var dptr_hi[7:0];'])
        assumes.append('assume instr[5:3] == 0b111;     // Dest mode 7 (index deferred)')
        code = '// Fetch destination offset\ndoff_lo = umem[pc];\ndoff_hi = umem[pc + 1];\ndst_offset = {doff_hi, doff_lo};\npc = pc + 2;\n'
        code += 'dst_base = dst_reg == 7 ? pc : rf[dst_reg];\ndptr_addr = dst_base + dst_offset;\n'
        code += '// Fetch actual address from pointer\ndptr_lo = umem[dptr_addr];\ndptr_hi = umem[dptr_addr + 1];\ndst_addr = {dptr_hi, dptr_lo};\n'
        if is_byte:
            code += 'dst_val = umem[dst_addr];\n'
        else:
            extra_vars.extend(['var dst_lo[7:0];', 'var dst_hi[7:0];'])
            code += 'dst_lo = umem[dst_addr];\ndst_hi = umem[dst_addr + 1];\ndst_val = {dst_hi, dst_lo};\n'

    return extra_vars, assumes, code


def _gen_dst_write(dst_mode, is_byte):
    """Generate destination write-back code."""
    if dst_mode == 0:  # Register
        if is_byte:
            return ('var extended[15:0];\n'
                    'extended = result[7] ? {8\'hFF, result} : {8\'h00, result};\n'
                    'rf[dst_reg] when (dst_reg != 7) = extended;\n')
        else:
            return ('rf[dst_reg] when (dst_reg != 7) = result;\n'
                    'pc when (dst_reg == 7) = result;\n')
    else:  # All memory modes use dst_addr
        if is_byte:
            return 'umem[dst_addr] = result;\n'
        else:
            return ('umem[dst_addr] = result[7:0];\n'
                    'umem[dst_addr + 1] = result[15:8];\n')


def generate_double_op_generic(name, opcode_hi, src_mode, dst_mode, operation, flags, is_byte=False):
    """Generic double-operand instruction generator for any src/dst mode combination."""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'
    src_desc = MODE_DESCRIPTIONS[src_mode]
    dst_desc = MODE_DESCRIPTIONS[dst_mode]

    src_vars, src_assumes, src_fetch = _gen_src_fetch(src_mode, is_byte)
    dst_vars, dst_assumes, dst_fetch = _gen_dst_fetch(dst_mode, is_byte)
    dst_write = _gen_dst_write(dst_mode, is_byte)

    # Collect all variable declarations (deduplicate)
    all_vars = ['var src_reg[2:0];', 'var dst_reg[2:0];',
                f'var src_val[{width}];', f'var dst_val[{width}];', f'var result[{width}];']
    seen = set(all_vars)
    for v in src_vars + dst_vars:
        if v not in seen:
            all_vars.append(v)
            seen.add(v)

    vars_str = '\n'.join(all_vars)
    opcode_assume = f'assume instr[15:12] == 0b{opcode_hi:04b};  // {name}{b} opcode'
    assumes_str = '\n'.join([opcode_assume] + src_assumes + dst_assumes)

    content = f'''// PDP-11 {name}{b} instruction - {src_desc} to {dst_desc}
// Source: mode {src_mode}, Dest: mode {dst_mode}

{COMMON_HEADER}
{vars_str}

{FETCH_INSTR}

{assumes_str}

src_reg = instr[8:6];
dst_reg = instr[2:0];

pc = pc + 2;

// Fetch source operand
{src_fetch}
// Fetch destination operand
{dst_fetch}
{operation}

// Write result
{dst_write}
{flags}'''
    return content


def generate_single_op_generic(name, opcode_pattern, dst_mode, operation, flags, is_byte=False):
    """Generic single-operand instruction generator for any dst mode."""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'
    dst_desc = MODE_DESCRIPTIONS[dst_mode]

    dst_vars, dst_assumes, dst_fetch = _gen_dst_fetch(dst_mode, is_byte)
    dst_write = _gen_dst_write(dst_mode, is_byte)

    # For single-operand, the 'dst_reg' field is instr[2:0] and mode is instr[5:3]
    # We reuse _gen_dst_fetch which uses dst_reg for the register field
    all_vars = ['var dst_reg[2:0];', f'var dst_val[{width}];', f'var result[{width}];']
    seen = set(all_vars)
    for v in dst_vars:
        if v not in seen:
            all_vars.append(v)
            seen.add(v)

    vars_str = '\n'.join(all_vars)
    opcode_assume = f'assume instr[15:6] == {opcode_pattern};  // {name}{b} opcode'
    assumes_str = '\n'.join([opcode_assume] + dst_assumes)

    content = f'''// PDP-11 {name}{b} instruction - {dst_desc} mode
// Dest: mode {dst_mode}

{COMMON_HEADER}
{vars_str}

{FETCH_INSTR}

{assumes_str}

dst_reg = instr[2:0];

pc = pc + 2;

// Fetch destination operand
{dst_fetch}
{operation}

// Write result
{dst_write}
{flags}'''
    return content


def generate_imm_generic(name, opcode_hi, dst_mode, operation, flags, is_byte=False):
    """Generate immediate source (mode 2/R7) to any dst mode."""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'
    dst_desc = MODE_DESCRIPTIONS[dst_mode]

    dst_vars, dst_assumes, dst_fetch = _gen_dst_fetch(dst_mode, is_byte)
    dst_write = _gen_dst_write(dst_mode, is_byte)

    all_vars = ['var dst_reg[2:0];', f'var src_val[{width}];', f'var dst_val[{width}];',
                f'var result[{width}];', 'var imm_lo[7:0];', 'var imm_hi[7:0];']
    seen = set(all_vars)
    for v in dst_vars:
        if v not in seen:
            all_vars.append(v)
            seen.add(v)

    vars_str = '\n'.join(all_vars)
    opcode_assume = f'assume instr[15:12] == 0b{opcode_hi:04b};  // {name}{b} opcode'
    src_assumes = ['assume instr[11:9] == 0b010;    // Source mode 2 (autoincrement)',
                   'assume instr[8:6] == 0b111;     // Source reg 7 (PC) = immediate']
    assumes_str = '\n'.join([opcode_assume] + src_assumes + dst_assumes)

    if is_byte:
        src_fetch = 'imm_lo = umem[pc];\nimm_hi = umem[pc + 1];\npc = pc + 2;\nsrc_val = imm_lo;\n'
    else:
        src_fetch = 'imm_lo = umem[pc];\nimm_hi = umem[pc + 1];\npc = pc + 2;\nsrc_val = {imm_hi, imm_lo};\n'

    content = f'''// PDP-11 {name}{b} instruction - Immediate to {dst_desc}
// Source: immediate (#n), Dest: mode {dst_mode}

{COMMON_HEADER}
{vars_str}

{FETCH_INSTR}

{assumes_str}

dst_reg = instr[2:0];

pc = pc + 2;

// Fetch immediate value
{src_fetch}
// Fetch destination operand
{dst_fetch}
{operation}

// Write result
{dst_write}
{flags}'''
    return content


def generate_single_op_r(name, opcode_pattern, operation, flags, is_byte=False):
    """Generate single operand register mode instruction"""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'

    content = f'''// PDP-11 {name}{b} instruction - Register mode

{COMMON_HEADER}
var dst_reg[2:0];
var dst_val[{width}];
var result[{width}];

{FETCH_INSTR}

assume instr[15:6] == {opcode_pattern};  // {name}{b} opcode
assume instr[5:3] == 0b000;          // Mode 0 (register)

dst_reg = instr[2:0];

pc = pc + 2;

'''
    if is_byte:
        content += f'''dst_val = rf[dst_reg][7:0];

{operation}

var extended[15:0];
extended = result[7] ? {{8'hFF, result}} : {{8'h00, result}};
rf[dst_reg] when (dst_reg != 7) = extended;

'''
    else:
        content += f'''dst_val = dst_reg == 7 ? pc : rf[dst_reg];

{operation}

rf[dst_reg] when (dst_reg != 7) = result;
pc when (dst_reg == 7) = result;

'''
    content += flags
    return content


def generate_single_op_d(name, opcode_pattern, operation, flags, is_byte=False):
    """Generate single operand deferred mode instruction"""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'

    content = f'''// PDP-11 {name}{b} instruction - Deferred mode

{COMMON_HEADER}
var dst_reg[2:0];
var dst_addr[15:0];
var dst_val[{width}];
var result[{width}];

{FETCH_INSTR}

assume instr[15:6] == {opcode_pattern};  // {name}{b} opcode
assume instr[5:3] == 0b001;          // Mode 1 (register deferred)

dst_reg = instr[2:0];

pc = pc + 2;

dst_addr = dst_reg == 7 ? pc : rf[dst_reg];

'''
    if is_byte:
        content += f'''dst_val = umem[dst_addr];

{operation}

umem[dst_addr] = result;

'''
    else:
        content += f'''var dst_lo[7:0];
var dst_hi[7:0];
dst_lo = umem[dst_addr];
dst_hi = umem[dst_addr + 1];
dst_val = {{dst_hi, dst_lo}};

{operation}

umem[dst_addr] = result[7:0];
umem[dst_addr + 1] = result[15:8];

'''
    content += flags
    return content


def generate_single_op_idx(name, opcode_pattern, operation, flags, is_byte=False):
    """Generate single operand indexed mode instruction"""
    b = 'B' if is_byte else ''
    width = '7:0' if is_byte else '15:0'

    content = f'''// PDP-11 {name}{b} instruction - Indexed mode

{COMMON_HEADER}
var dst_reg[2:0];
var offset[15:0];
var base_addr[15:0];
var dst_addr[15:0];
var dst_val[{width}];
var result[{width}];
var off_lo[7:0];
var off_hi[7:0];

{FETCH_INSTR}

assume instr[15:6] == {opcode_pattern};  // {name}{b} opcode
assume instr[5:3] == 0b110;          // Mode 6 (indexed)

dst_reg = instr[2:0];

pc = pc + 2;

// Fetch offset
off_lo = umem[pc];
off_hi = umem[pc + 1];
offset = {{off_hi, off_lo}};
pc = pc + 2;

base_addr = dst_reg == 7 ? pc : rf[dst_reg];
dst_addr = base_addr + offset;

'''
    if is_byte:
        content += f'''dst_val = umem[dst_addr];

{operation}

umem[dst_addr] = result;

'''
    else:
        content += f'''var dst_lo[7:0];
var dst_hi[7:0];
dst_lo = umem[dst_addr];
dst_hi = umem[dst_addr + 1];
dst_val = {{dst_hi, dst_lo}};

{operation}

umem[dst_addr] = result[7:0];
umem[dst_addr + 1] = result[15:8];

'''
    content += flags
    return content


def generate_all_instructions(output_dir):
    """Generate all PDP-11 instruction files"""

    os.makedirs(output_dir, exist_ok=True)
    files_created = []

    # ===== DOUBLE OPERAND INSTRUCTIONS =====

    # Operations for MOV-like (result = src, don't need dst_val for operation)
    mov_op = 'result = src_val;'
    mov_flags = '''flag_N = result[15];
flag_Z = result == 0 ? 1'b1 : 1'b0;
flag_V = 0;
'''
    mov_flags_byte = '''flag_N = result[7];
flag_Z = result == 0 ? 1'b1 : 1'b0;
flag_V = 0;
'''

    # CMP doesn't write result, just sets flags
    cmp_op = '''var diff[16:0];
diff = {1'b0, src_val} - {1'b0, dst_val};
result = diff[15:0];'''
    cmp_flags = '''flag_N = result[15];
flag_Z = result == 0 ? 1'b1 : 1'b0;
flag_V = (src_val[15] != dst_val[15]) && (result[15] != src_val[15]) ? 1'b1 : 1'b0;
flag_C = diff[16];
'''

    cmp_op_byte = '''var diff[8:0];
diff = {1'b0, src_val} - {1'b0, dst_val};
result = diff[7:0];'''
    cmp_flags_byte = '''flag_N = result[7];
flag_Z = result == 0 ? 1'b1 : 1'b0;
flag_V = (src_val[7] != dst_val[7]) && (result[7] != src_val[7]) ? 1'b1 : 1'b0;
flag_C = diff[8];
'''

    add_op = '''var sum[16:0];
sum = {1'b0, src_val} + {1'b0, dst_val};
result = sum[15:0];'''
    add_flags = '''flag_N = result[15];
flag_Z = result == 0 ? 1'b1 : 1'b0;
flag_V = (src_val[15] == dst_val[15]) && (result[15] != src_val[15]) ? 1'b1 : 1'b0;
flag_C = sum[16];
'''

    sub_op = '''var diff[16:0];
diff = {1'b0, dst_val} - {1'b0, src_val};
result = diff[15:0];'''
    sub_flags = '''flag_N = result[15];
flag_Z = result == 0 ? 1'b1 : 1'b0;
flag_V = (dst_val[15] != src_val[15]) && (result[15] != dst_val[15]) ? 1'b1 : 1'b0;
flag_C = diff[16];
'''

    bit_op = 'result = src_val & dst_val;'
    bit_flags = '''flag_N = result[15];
flag_Z = result == 0 ? 1'b1 : 1'b0;
flag_V = 0;
'''
    bit_flags_byte = '''flag_N = result[7];
flag_Z = result == 0 ? 1'b1 : 1'b0;
flag_V = 0;
'''

    bic_op = 'result = dst_val & ~src_val;'
    bis_op = 'result = dst_val | src_val;'

    # Double operand instruction definitions
    # (name, opcode_hi, op, flags, has_byte_variant)
    double_ops = [
        ('mov', 0b0001, mov_op, mov_flags, True, mov_flags_byte),
        ('cmp', 0b0010, cmp_op, cmp_flags, True, cmp_flags_byte),
        ('add', 0b0110, add_op, add_flags, False, None),
        ('sub', 0b1110, sub_op, sub_flags, False, None),
        ('bit', 0b0011, bit_op, bit_flags, True, bit_flags_byte),
        ('bic', 0b0100, bic_op, bit_flags, True, bit_flags_byte),
        ('bis', 0b0101, bis_op, bit_flags, True, bit_flags_byte),
    ]

    # ---- Generate all src x dst mode combinations using generic generators ----
    # All 8 source modes x 8 destination modes = 64 combinations per instruction
    # Plus immediate (mode 2/R7) variants for each dst mode

    for name, opcode, op, flags, has_byte, byte_flags in double_ops:
        for src_mode in range(8):
            for dst_mode in range(8):
                # Determine file suffix
                src_name = SRC_MODE_NAMES[src_mode]
                dst_name = DST_MODE_NAMES[dst_mode]
                if src_mode == 0 and dst_mode == 0:
                    suffix = 'rr'
                else:
                    suffix = f'{src_name}_{dst_name}'

                filename = f"{name}_{suffix}.isa"
                content = generate_double_op_generic(name.upper(), opcode, src_mode, dst_mode,
                                                     op, flags, is_byte=False)

                # For CMP and BIT, remove the write to destination (they only set flags)
                if name in ('cmp', 'bit'):
                    content = content.replace('// Write result\nrf[dst_reg] when (dst_reg != 7) = result;\npc when (dst_reg == 7) = result;\n', '// Write result\n')
                    content = content.replace('// Write result\numem[dst_addr] = result[7:0];\numem[dst_addr + 1] = result[15:8];\n', '// Write result\n')
                    content = content.replace('// Write result\numem[dst_addr] = result;\n', '// Write result\n')
                    content = content.replace('// Write result\nvar extended[15:0];\nextended = result[7] ? {8\'hFF, result} : {8\'h00, result};\nrf[dst_reg] when (dst_reg != 7) = extended;\n', '// Write result\n')

                filepath = os.path.join(output_dir, filename)
                with open(filepath, 'w') as f:
                    f.write(content)
                files_created.append(filename)

                # Byte version
                if has_byte:
                    byte_opcode = opcode | 0b1000  # Set bit 15
                    filename = f"{name}b_{suffix}.isa"

                    byte_op = op.replace('[15:0]', '[7:0]').replace('[16:0]', '[8:0]')
                    content = generate_double_op_generic(name.upper(), byte_opcode, src_mode, dst_mode,
                                                         byte_op, byte_flags, is_byte=True)

                    if name in ('cmp', 'bit'):
                        content = content.replace('// Write result\nrf[dst_reg] when (dst_reg != 7) = result;\npc when (dst_reg == 7) = result;\n', '// Write result\n')
                        content = content.replace('// Write result\numem[dst_addr] = result[7:0];\numem[dst_addr + 1] = result[15:8];\n', '// Write result\n')
                        content = content.replace('// Write result\numem[dst_addr] = result;\n', '// Write result\n')
                        content = content.replace('// Write result\nvar extended[15:0];\nextended = result[7] ? {8\'hFF, result} : {8\'h00, result};\nrf[dst_reg] when (dst_reg != 7) = extended;\n', '// Write result\n')

                    filepath = os.path.join(output_dir, filename)
                    with open(filepath, 'w') as f:
                        f.write(content)
                    files_created.append(filename)

        # Also generate immediate (mode 2, R7) to each dst mode
        for dst_mode in range(8):
            dst_name = DST_MODE_NAMES[dst_mode]
            suffix = f'imm_{dst_name}'
            filename = f"{name}_{suffix}.isa"
            content = generate_imm_generic(name.upper(), opcode, dst_mode, op, flags, is_byte=False)

            if name in ('cmp', 'bit'):
                content = content.replace('// Write result\nrf[dst_reg] when (dst_reg != 7) = result;\npc when (dst_reg == 7) = result;\n', '// Write result\n')
                content = content.replace('// Write result\numem[dst_addr] = result[7:0];\numem[dst_addr + 1] = result[15:8];\n', '// Write result\n')
                content = content.replace('// Write result\numem[dst_addr] = result;\n', '// Write result\n')
                content = content.replace('// Write result\nvar extended[15:0];\nextended = result[7] ? {8\'hFF, result} : {8\'h00, result};\nrf[dst_reg] when (dst_reg != 7) = extended;\n', '// Write result\n')

            filepath = os.path.join(output_dir, filename)
            with open(filepath, 'w') as f:
                f.write(content)
            files_created.append(filename)

            if has_byte:
                byte_opcode = opcode | 0b1000
                filename = f"{name}b_{suffix}.isa"
                byte_op = op.replace('[15:0]', '[7:0]').replace('[16:0]', '[8:0]')
                content = generate_imm_generic(name.upper(), byte_opcode, dst_mode,
                                               byte_op, byte_flags, is_byte=True)

                if name in ('cmp', 'bit'):
                    content = content.replace('// Write result\nrf[dst_reg] when (dst_reg != 7) = result;\npc when (dst_reg == 7) = result;\n', '// Write result\n')
                    content = content.replace('// Write result\numem[dst_addr] = result[7:0];\numem[dst_addr + 1] = result[15:8];\n', '// Write result\n')
                    content = content.replace('// Write result\numem[dst_addr] = result;\n', '// Write result\n')
                    content = content.replace('// Write result\nvar extended[15:0];\nextended = result[7] ? {8\'hFF, result} : {8\'h00, result};\nrf[dst_reg] when (dst_reg != 7) = extended;\n', '// Write result\n')

                filepath = os.path.join(output_dir, filename)
                with open(filepath, 'w') as f:
                    f.write(content)
                files_created.append(filename)

    # ===== SINGLE OPERAND INSTRUCTIONS =====

    single_ops_word = [
        ('clr', '0b0000101000', 'result = 0;', 'flag_N = 0;\nflag_Z = 1;\nflag_V = 0;\nflag_C = 0;'),
        ('com', '0b0000101001', 'result = ~dst_val;', 'flag_N = result[15];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = 0;\nflag_C = 1;'),
        ('inc', '0b0000101010', 'result = dst_val + 1;', 'flag_N = result[15];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = dst_val == 16\'h7FFF ? 1\'b1 : 1\'b0;'),
        ('dec', '0b0000101011', 'result = dst_val - 1;', 'flag_N = result[15];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = dst_val == 16\'h8000 ? 1\'b1 : 1\'b0;'),
        ('neg', '0b0000101100', 'result = 0 - dst_val;', 'flag_N = result[15];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = result == 16\'h8000 ? 1\'b1 : 1\'b0;\nflag_C = result != 0 ? 1\'b1 : 1\'b0;'),
        ('tst', '0b0000101111', 'result = dst_val;', 'flag_N = result[15];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = 0;\nflag_C = 0;'),
        ('asr', '0b0000110010', 'result = {dst_val[15], dst_val[15:1]};', 'flag_C = dst_val[0];\nflag_N = result[15];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = result[15] ^ dst_val[0];'),
        ('asl', '0b0000110011', 'result = {dst_val[14:0], 1\'b0};', 'flag_C = dst_val[15];\nflag_N = result[15];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = result[15] ^ dst_val[15];'),
        ('ror', '0b0000110000', 'result = {flag_C, dst_val[15:1]};', 'flag_C = dst_val[0];\nflag_N = result[15];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = result[15] ^ dst_val[0];'),
        ('rol', '0b0000110001', 'result = {dst_val[14:0], flag_C};', 'flag_C = dst_val[15];\nflag_N = result[15];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = result[15] ^ dst_val[15];'),
        ('adc', '0b0000101101', 'var sum[16:0];\nsum = {1\'b0, dst_val} + {16\'b0, flag_C};\nresult = sum[15:0];', 'flag_N = result[15];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = dst_val == 16\'h7FFF && flag_C ? 1\'b1 : 1\'b0;\nflag_C = sum[16];'),
        ('sbc', '0b0000101110', 'var diff[16:0];\ndiff = {1\'b0, dst_val} - {16\'b0, flag_C};\nresult = diff[15:0];', 'flag_N = result[15];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = dst_val == 16\'h8000 && flag_C ? 1\'b1 : 1\'b0;\nflag_C = diff[16];'),
        ('sxt', '0b0000110111', 'result = flag_N ? 16\'hFFFF : 16\'h0000;', 'flag_Z = flag_N == 0 ? 1\'b1 : 1\'b0;\nflag_V = 0;'),
        ('swab', '0b0000000011', 'result = {dst_val[7:0], dst_val[15:8]};', 'flag_N = result[7];\nflag_Z = result[7:0] == 0 ? 1\'b1 : 1\'b0;\nflag_V = 0;\nflag_C = 0;'),
    ]

    single_ops_byte = [
        ('clrb', '0b1000101000', 'result = 0;', 'flag_N = 0;\nflag_Z = 1;\nflag_V = 0;\nflag_C = 0;'),
        ('comb', '0b1000101001', 'result = ~dst_val;', 'flag_N = result[7];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = 0;\nflag_C = 1;'),
        ('incb', '0b1000101010', 'result = dst_val + 1;', 'flag_N = result[7];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = dst_val == 8\'h7F ? 1\'b1 : 1\'b0;'),
        ('decb', '0b1000101011', 'result = dst_val - 1;', 'flag_N = result[7];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = dst_val == 8\'h80 ? 1\'b1 : 1\'b0;'),
        ('negb', '0b1000101100', 'result = 0 - dst_val;', 'flag_N = result[7];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = result == 8\'h80 ? 1\'b1 : 1\'b0;\nflag_C = result != 0 ? 1\'b1 : 1\'b0;'),
        ('tstb', '0b1000101111', 'result = dst_val;', 'flag_N = result[7];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = 0;\nflag_C = 0;'),
        ('asrb', '0b1000110010', 'result = {dst_val[7], dst_val[7:1]};', 'flag_C = dst_val[0];\nflag_N = result[7];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = result[7] ^ dst_val[0];'),
        ('aslb', '0b1000110011', 'result = {dst_val[6:0], 1\'b0};', 'flag_C = dst_val[7];\nflag_N = result[7];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = result[7] ^ dst_val[7];'),
        ('rorb', '0b1000110000', 'result = {flag_C, dst_val[7:1]};', 'flag_C = dst_val[0];\nflag_N = result[7];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = result[7] ^ dst_val[0];'),
        ('rolb', '0b1000110001', 'result = {dst_val[6:0], flag_C};', 'flag_C = dst_val[7];\nflag_N = result[7];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = result[7] ^ dst_val[7];'),
        ('adcb', '0b1000101101', 'var sum[8:0];\nsum = {1\'b0, dst_val} + {8\'b0, flag_C};\nresult = sum[7:0];', 'flag_N = result[7];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = dst_val == 8\'h7F && flag_C ? 1\'b1 : 1\'b0;\nflag_C = sum[8];'),
        ('sbcb', '0b1000101110', 'var diff[8:0];\ndiff = {1\'b0, dst_val} - {8\'b0, flag_C};\nresult = diff[7:0];', 'flag_N = result[7];\nflag_Z = result == 0 ? 1\'b1 : 1\'b0;\nflag_V = dst_val == 8\'h80 && flag_C ? 1\'b1 : 1\'b0;\nflag_C = diff[8];'),
    ]

    # ---- Generate all 8 addressing modes for single-operand instructions ----
    single_mode_all = [
        ('r', 0), ('d', 1), ('ai', 2), ('aid', 3),
        ('ad', 4), ('add', 5), ('idx', 6), ('idxd', 7),
    ]

    for name, opcode, op, flags in single_ops_word:
        for suffix, mode in single_mode_all:
            filename = f"{name}_{suffix}.isa"
            content = generate_single_op_generic(name.upper(), opcode, mode, op, flags, is_byte=False)

            # TST doesn't write result
            if name == 'tst':
                content = content.replace('// Write result\nrf[dst_reg] when (dst_reg != 7) = result;\npc when (dst_reg == 7) = result;\n', '// Write result\n')
                content = content.replace('// Write result\numem[dst_addr] = result[7:0];\numem[dst_addr + 1] = result[15:8];\n', '// Write result\n')

            filepath = os.path.join(output_dir, filename)
            with open(filepath, 'w') as f:
                f.write(content)
            files_created.append(filename)

    for name, opcode, op, flags in single_ops_byte:
        for suffix, mode in single_mode_all:
            filename = f"{name}_{suffix}.isa"
            content = generate_single_op_generic(name.upper(), opcode, mode, op, flags, is_byte=True)

            if name == 'tstb':
                content = content.replace('// Write result\numem[dst_addr] = result;\n', '// Write result\n')
                content = content.replace('// Write result\nvar extended[15:0];\nextended = result[7] ? {8\'hFF, result} : {8\'h00, result};\nrf[dst_reg] when (dst_reg != 7) = extended;\n', '// Write result\n')

            filepath = os.path.join(output_dir, filename)
            with open(filepath, 'w') as f:
                f.write(content)
            files_created.append(filename)

    # ===== BRANCH INSTRUCTIONS =====

    branches = [
        ('br', '0b00000001', "1'b1"),
        ('bne', '0b00000010', 'flag_Z == 0'),
        ('beq', '0b00000011', 'flag_Z == 1'),
        ('bge', '0b00000100', 'flag_N == flag_V'),
        ('blt', '0b00000101', 'flag_N != flag_V'),
        ('bgt', '0b00000110', '(flag_Z == 0) && (flag_N == flag_V)'),
        ('ble', '0b00000111', '(flag_Z == 1) || (flag_N != flag_V)'),
        ('bpl', '0b10000000', 'flag_N == 0'),
        ('bmi', '0b10000001', 'flag_N == 1'),
        ('bhi', '0b10000010', '(flag_C == 0) && (flag_Z == 0)'),
        ('blos', '0b10000011', '(flag_C == 1) || (flag_Z == 1)'),
        ('bvc', '0b10000100', 'flag_V == 0'),
        ('bvs', '0b10000101', 'flag_V == 1'),
        ('bcc', '0b10000110', 'flag_C == 0'),
        ('bcs', '0b10000111', 'flag_C == 1'),
    ]

    for name, opcode, condition in branches:
        content = f'''// PDP-11 {name.upper()} instruction

{COMMON_HEADER}
var offset[7:0];
var sign_ext[15:0];
var target[15:0];

{FETCH_INSTR}

assume instr[15:8] == {opcode};

offset = instr[7:0];
pc = pc + 2;

// Sign-extend 8-bit offset and multiply by 2
sign_ext = offset[7] ? {{8'hFF, offset}} : {{8'h00, offset}};
target = pc + (sign_ext << 1);

// Conditional branch (use ternary to avoid generator bug with 'when' on flags)
pc = ({condition}) ? target : pc;
'''
        filename = f"{name}.isa"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w') as f:
            f.write(content)
        files_created.append(filename)

    # ===== EIS INSTRUCTIONS =====
    # EIS instructions use the dst field (bits 5:0) as the SOURCE operand
    # and the register field (bits 8:6) as the destination register
    # Format: opcode[15:9], Rn[8:6], src_mode[5:3], src_reg[2:0]

    # EIS source modes: all 8 modes + immediate
    eis_modes = [
        (0, 'rr', '0b000', 'Register', False),
        (1, 'd_r', '0b001', 'Register Deferred', False),
        (2, 'ai_r', '0b010', 'Autoincrement', False),
        (3, 'aid_r', '0b011', 'Autoincrement Deferred', False),
        (4, 'ad_r', '0b100', 'Autodecrement', False),
        (5, 'add_r', '0b101', 'Autodecrement Deferred', False),
        (6, 'idx_r', '0b110', 'Indexed', False),
        (7, 'idxd_r', '0b111', 'Index Deferred', False),
        (2, 'imm_r', '0b010', 'Immediate', True),  # mode 2 + R7
    ]

    for src_mode, mode_suffix, mode_bits, mode_desc, is_imm in eis_modes:
        # Build source operand fetch based on mode
        if is_imm:
            src_extra_vars = 'var imm_lo[7:0];\nvar imm_hi[7:0];'
            src_assumes = 'assume instr[5:3] == 0b010;       // Source mode 2 (autoincrement)\nassume instr[2:0] == 0b111;       // Source reg 7 (PC) = immediate'
            src_fetch = 'imm_lo = umem[pc];\nimm_hi = umem[pc + 1];\nsrc_val = {imm_hi, imm_lo};\npc = pc + 2;'
            src_reg_decode = ''
        elif src_mode == 0:
            src_extra_vars = ''
            src_assumes = f'assume instr[5:3] == {mode_bits};       // Source mode {src_mode} ({mode_desc})'
            src_fetch = 'src_val = src_reg == 7 ? pc : rf[src_reg];'
            src_reg_decode = 'src_reg = instr[2:0];  // Source register\n'
        elif src_mode == 1:
            src_extra_vars = 'var src_addr[15:0];\nvar s_lo[7:0];\nvar s_hi[7:0];'
            src_assumes = f'assume instr[5:3] == {mode_bits};       // Source mode {src_mode} ({mode_desc})'
            src_fetch = 'src_addr = src_reg == 7 ? pc : rf[src_reg];\ns_lo = umem[src_addr];\ns_hi = umem[src_addr + 1];\nsrc_val = {s_hi, s_lo};'
            src_reg_decode = 'src_reg = instr[2:0];\n'
        elif src_mode == 2:
            src_extra_vars = 'var src_addr[15:0];\nvar s_lo[7:0];\nvar s_hi[7:0];'
            src_assumes = f'assume instr[5:3] == {mode_bits};       // Source mode {src_mode} ({mode_desc})\nassume instr[2:0] != 0b111;       // Source reg != 7'
            src_fetch = 'src_addr = rf[src_reg];\nrf[src_reg] = rf[src_reg] + 2;\ns_lo = umem[src_addr];\ns_hi = umem[src_addr + 1];\nsrc_val = {s_hi, s_lo};'
            src_reg_decode = 'src_reg = instr[2:0];\n'
        elif src_mode == 3:
            src_extra_vars = 'var eis_ptr_addr[15:0];\nvar src_addr[15:0];\nvar ep_lo[7:0];\nvar ep_hi[7:0];\nvar s_lo[7:0];\nvar s_hi[7:0];'
            src_assumes = f'assume instr[5:3] == {mode_bits};       // Source mode {src_mode} ({mode_desc})'
            src_fetch = 'eis_ptr_addr = rf[src_reg];\nrf[src_reg] when (src_reg != 7) = rf[src_reg] + 2;\nep_lo = umem[eis_ptr_addr];\nep_hi = umem[eis_ptr_addr + 1];\nsrc_addr = {ep_hi, ep_lo};\ns_lo = umem[src_addr];\ns_hi = umem[src_addr + 1];\nsrc_val = {s_hi, s_lo};'
            src_reg_decode = 'src_reg = instr[2:0];\n'
        elif src_mode == 4:
            src_extra_vars = 'var src_addr[15:0];\nvar s_lo[7:0];\nvar s_hi[7:0];'
            src_assumes = f'assume instr[5:3] == {mode_bits};       // Source mode {src_mode} ({mode_desc})'
            src_fetch = 'src_addr = rf[src_reg] - 2;\nrf[src_reg] when (src_reg != 7) = src_addr;\ns_lo = umem[src_addr];\ns_hi = umem[src_addr + 1];\nsrc_val = {s_hi, s_lo};'
            src_reg_decode = 'src_reg = instr[2:0];\n'
        elif src_mode == 5:
            src_extra_vars = 'var eis_ptr_addr[15:0];\nvar src_addr[15:0];\nvar ep_lo[7:0];\nvar ep_hi[7:0];\nvar s_lo[7:0];\nvar s_hi[7:0];'
            src_assumes = f'assume instr[5:3] == {mode_bits};       // Source mode {src_mode} ({mode_desc})'
            src_fetch = 'eis_ptr_addr = rf[src_reg] - 2;\nrf[src_reg] when (src_reg != 7) = eis_ptr_addr;\nep_lo = umem[eis_ptr_addr];\nep_hi = umem[eis_ptr_addr + 1];\nsrc_addr = {ep_hi, ep_lo};\ns_lo = umem[src_addr];\ns_hi = umem[src_addr + 1];\nsrc_val = {s_hi, s_lo};'
            src_reg_decode = 'src_reg = instr[2:0];\n'
        elif src_mode == 6:
            src_extra_vars = 'var eis_offset[15:0];\nvar eis_base[15:0];\nvar src_addr[15:0];\nvar eo_lo[7:0];\nvar eo_hi[7:0];\nvar s_lo[7:0];\nvar s_hi[7:0];'
            src_assumes = f'assume instr[5:3] == {mode_bits};       // Source mode {src_mode} ({mode_desc})'
            src_fetch = 'eo_lo = umem[pc];\neo_hi = umem[pc + 1];\neis_offset = {eo_hi, eo_lo};\npc = pc + 2;\neis_base = src_reg == 7 ? pc : rf[src_reg];\nsrc_addr = eis_base + eis_offset;\ns_lo = umem[src_addr];\ns_hi = umem[src_addr + 1];\nsrc_val = {s_hi, s_lo};'
            src_reg_decode = 'src_reg = instr[2:0];\n'
        elif src_mode == 7:
            src_extra_vars = 'var eis_offset[15:0];\nvar eis_base[15:0];\nvar eis_ptr_addr[15:0];\nvar src_addr[15:0];\nvar eo_lo[7:0];\nvar eo_hi[7:0];\nvar ep_lo[7:0];\nvar ep_hi[7:0];\nvar s_lo[7:0];\nvar s_hi[7:0];'
            src_assumes = f'assume instr[5:3] == {mode_bits};       // Source mode {src_mode} ({mode_desc})'
            src_fetch = 'eo_lo = umem[pc];\neo_hi = umem[pc + 1];\neis_offset = {eo_hi, eo_lo};\npc = pc + 2;\neis_base = src_reg == 7 ? pc : rf[src_reg];\neis_ptr_addr = eis_base + eis_offset;\nep_lo = umem[eis_ptr_addr];\nep_hi = umem[eis_ptr_addr + 1];\nsrc_addr = {ep_hi, ep_lo};\ns_lo = umem[src_addr];\ns_hi = umem[src_addr + 1];\nsrc_val = {s_hi, s_lo};'
            src_reg_decode = 'src_reg = instr[2:0];\n'

        # MUL
        content = f'''// PDP-11 MUL instruction - {mode_desc}
// MUL src, Rn: Rn:Rn|1 = Rn * src (signed)

{COMMON_HEADER}
var src_reg[2:0];
var dst_reg[2:0];
var src_val[15:0];
var multiplicand[15:0];
var result[31:0];
{src_extra_vars}

{FETCH_INSTR}

assume instr[15:9] == 0b0111000;  // MUL opcode (070)
{src_assumes}

dst_reg = instr[8:6];  // Destination register
{src_reg_decode}
pc = pc + 2;

// Fetch source operand
{src_fetch}

multiplicand = dst_reg == 7 ? pc : rf[dst_reg];

// Simplified multiplication
result = src_val * multiplicand;

// Store: high word in Rn, low word in Rn|1
rf[dst_reg] when (dst_reg != 7) = result[31:16];
rf[dst_reg | 1] when ((dst_reg | 1) != 7) = result[15:0];

flag_N = result[31];
flag_Z = result == 0 ? 1'b1 : 1'b0;
flag_V = 0;
flag_C = (result[31:16] != 0) && (result[31:16] != 16'hFFFF) ? 1'b1 : 1'b0;
'''
        filepath = os.path.join(output_dir, f"mul_{mode_suffix}.isa")
        with open(filepath, 'w') as f:
            f.write(content)
        files_created.append(f"mul_{mode_suffix}.isa")

        # DIV
        content = f'''// PDP-11 DIV instruction - {mode_desc}
// DIV src, Rn: Rn = Rn:Rn|1 / src, Rn|1 = remainder

{COMMON_HEADER}
var src_reg[2:0];
var dst_reg[2:0];
var src_val[15:0];
var dividend_hi[15:0];
var dividend_lo[15:0];
var dividend[31:0];
var quotient[15:0];
var remainder[15:0];
{src_extra_vars}

{FETCH_INSTR}

assume instr[15:9] == 0b0111001;  // DIV opcode (071)
{src_assumes}

dst_reg = instr[8:6];  // Destination register
{src_reg_decode}
pc = pc + 2;

// Fetch source operand
{src_fetch}

dividend_hi = dst_reg == 7 ? pc : rf[dst_reg];
dividend_lo = rf[dst_reg | 1];
dividend = {{dividend_hi, dividend_lo}};

// Simplified division
quotient = dividend / {{16'b0, src_val}};
remainder = dividend - (quotient * {{16'b0, src_val}});

rf[dst_reg] when (dst_reg != 7) = quotient;
rf[dst_reg | 1] when ((dst_reg | 1) != 7) = remainder;

flag_N = quotient[15];
flag_Z = quotient == 0 ? 1'b1 : 1'b0;
flag_V = src_val == 0 ? 1'b1 : 1'b0;
flag_C = 0;
'''
        filepath = os.path.join(output_dir, f"div_{mode_suffix}.isa")
        with open(filepath, 'w') as f:
            f.write(content)
        files_created.append(f"div_{mode_suffix}.isa")

        # ASH
        content = f'''// PDP-11 ASH instruction - {mode_desc}
// ASH src, Rn: shift Rn by src[5:0]

{COMMON_HEADER}
var src_reg[2:0];
var dst_reg[2:0];
var src_val[15:0];
var operand[15:0];
var shift_right[0:0];
var neg_count[5:0];
var result[15:0];
{src_extra_vars}

{FETCH_INSTR}

assume instr[15:9] == 0b0111010;  // ASH opcode (072)
{src_assumes}

dst_reg = instr[8:6];  // Destination register
{src_reg_decode}
pc = pc + 2;

// Fetch source operand
{src_fetch}

operand = dst_reg == 7 ? pc : rf[dst_reg];
shift_right = src_val[5];
neg_count = ~src_val[5:0] + 1;

// Variable arithmetic shift using 6-bit signed shift count
result = shift_right ? (operand >>> neg_count[4:0]) : (operand << src_val[4:0]);

rf[dst_reg] when (dst_reg != 7) = result;

flag_N = result[15];
flag_Z = result == 0 ? 1'b1 : 1'b0;
flag_V = operand[15] != result[15] ? 1'b1 : 1'b0;
flag_C = shift_right ? operand[0] : operand[15];
'''
        filepath = os.path.join(output_dir, f"ash_{mode_suffix}.isa")
        with open(filepath, 'w') as f:
            f.write(content)
        files_created.append(f"ash_{mode_suffix}.isa")

        # ASHC
        content = f'''// PDP-11 ASHC instruction - {mode_desc}
// ASHC src, Rn: shift Rn:Rn|1 by src[5:0]

{COMMON_HEADER}
var src_reg[2:0];
var dst_reg[2:0];
var src_val[15:0];
var operand_hi[15:0];
var operand_lo[15:0];
var operand[31:0];
var shift_right[0:0];
var neg_count[5:0];
var result[31:0];
{src_extra_vars}

{FETCH_INSTR}

assume instr[15:9] == 0b0111011;  // ASHC opcode (073)
{src_assumes}

dst_reg = instr[8:6];  // Destination register
{src_reg_decode}
pc = pc + 2;

// Fetch source operand
{src_fetch}

operand_hi = dst_reg == 7 ? pc : rf[dst_reg];
operand_lo = rf[dst_reg | 1];
operand = {{operand_hi, operand_lo}};
shift_right = src_val[5];
neg_count = ~src_val[5:0] + 1;

// Variable arithmetic shift using 6-bit signed shift count
result = shift_right ? (operand >>> neg_count[4:0]) : (operand << src_val[4:0]);

rf[dst_reg] when (dst_reg != 7) = result[31:16];
rf[dst_reg | 1] when ((dst_reg | 1) != 7) = result[15:0];

flag_N = result[31];
flag_Z = result == 0 ? 1'b1 : 1'b0;
flag_V = operand[31] != result[31] ? 1'b1 : 1'b0;
flag_C = shift_right ? operand[0] : operand[31];
'''
        filepath = os.path.join(output_dir, f"ashc_{mode_suffix}.isa")
        with open(filepath, 'w') as f:
            f.write(content)
        files_created.append(f"ashc_{mode_suffix}.isa")

    # XOR - all 8 destination modes
    # XOR has source always in register (Rn), dst can be any mode
    xor_op = 'result = src_val ^ dst_val;'
    xor_flags = '''flag_N = result[15];
flag_Z = result == 0 ? 1'b1 : 1'b0;
flag_V = 0;
'''
    for dst_mode in range(8):
        dst_name = DST_MODE_NAMES[dst_mode]
        if dst_mode == 0:
            suffix = 'rr'
        else:
            suffix = f'r_{dst_name}'

        dst_vars, dst_assumes, dst_fetch = _gen_dst_fetch(dst_mode, is_byte=False)
        dst_write = _gen_dst_write(dst_mode, is_byte=False)

        all_vars = ['var src_reg[2:0];', 'var dst_reg[2:0];',
                    'var src_val[15:0];', 'var dst_val[15:0];', 'var result[15:0];']
        seen = set(all_vars)
        for v in dst_vars:
            if v not in seen:
                all_vars.append(v)
                seen.add(v)

        vars_str = '\n'.join(all_vars)
        assumes_str = '\n'.join(['assume instr[15:9] == 0b0111100;  // XOR opcode (074)'] + dst_assumes)

        content = f'''// PDP-11 XOR instruction - Register to {MODE_DESCRIPTIONS[dst_mode]}
// XOR Rn, dst: dst = Rn XOR dst

{COMMON_HEADER}
{vars_str}

{FETCH_INSTR}

{assumes_str}

src_reg = instr[8:6];
dst_reg = instr[2:0];

pc = pc + 2;

src_val = src_reg == 7 ? pc : rf[src_reg];

// Fetch destination operand
{dst_fetch}
{xor_op}

// Write result
{dst_write}
{xor_flags}'''
        filename = f"xor_{suffix}.isa"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w') as f:
            f.write(content)
        files_created.append(filename)

    # ===== JUMP INSTRUCTIONS =====

    # JMP - all valid addressing modes (modes 1-7, mode 0 is illegal)
    jmp_modes = [
        (1, 'd', '0b001', 'Register Deferred'),
        (2, 'ai', '0b010', 'Autoincrement'),
        (3, 'aid', '0b011', 'Autoincrement Deferred'),
        (4, 'ad', '0b100', 'Autodecrement'),
        (5, 'add', '0b101', 'Autodecrement Deferred'),
        (6, 'idx', '0b110', 'Indexed'),
        (7, 'idxd', '0b111', 'Index Deferred'),
    ]

    for mode_num, mode_suffix, mode_bits, mode_desc in jmp_modes:
        if mode_num == 1:  # Register deferred - simple case
            content = f'''// PDP-11 JMP instruction - {mode_desc} mode

{COMMON_HEADER}
var dst_reg[2:0];
var target[15:0];

{FETCH_INSTR}

assume instr[15:6] == 0b0000000001;  // JMP opcode
assume instr[5:3] == {mode_bits};      // Mode {mode_num} ({mode_desc})

dst_reg = instr[2:0];

pc = pc + 2;

target = dst_reg == 7 ? pc : rf[dst_reg];
pc = target;
'''
        elif mode_num == 2:  # Autoincrement - use register value, then increment
            content = f'''// PDP-11 JMP instruction - {mode_desc} mode

{COMMON_HEADER}
var dst_reg[2:0];
var target[15:0];

{FETCH_INSTR}

assume instr[15:6] == 0b0000000001;  // JMP opcode
assume instr[5:3] == {mode_bits};      // Mode {mode_num} ({mode_desc})

dst_reg = instr[2:0];

pc = pc + 2;

target = rf[dst_reg];
rf[dst_reg] when (dst_reg != 7) = rf[dst_reg] + 2;
pc = target;
'''
        elif mode_num == 3:  # Autoincrement deferred
            content = f'''// PDP-11 JMP instruction - {mode_desc} mode

{COMMON_HEADER}
var dst_reg[2:0];
var ptr_addr[15:0];
var target[15:0];
var ptr_lo[7:0];
var ptr_hi[7:0];

{FETCH_INSTR}

assume instr[15:6] == 0b0000000001;  // JMP opcode
assume instr[5:3] == {mode_bits};      // Mode {mode_num} ({mode_desc})

dst_reg = instr[2:0];

pc = pc + 2;

ptr_addr = rf[dst_reg];
rf[dst_reg] when (dst_reg != 7) = rf[dst_reg] + 2;

ptr_lo = umem[ptr_addr];
ptr_hi = umem[ptr_addr + 1];
target = {{ptr_hi, ptr_lo}};
pc = target;
'''
        elif mode_num == 4:  # Autodecrement
            content = f'''// PDP-11 JMP instruction - {mode_desc} mode

{COMMON_HEADER}
var dst_reg[2:0];
var target[15:0];

{FETCH_INSTR}

assume instr[15:6] == 0b0000000001;  // JMP opcode
assume instr[5:3] == {mode_bits};      // Mode {mode_num} ({mode_desc})

dst_reg = instr[2:0];

pc = pc + 2;

target = rf[dst_reg] - 2;
rf[dst_reg] when (dst_reg != 7) = target;
pc = target;
'''
        elif mode_num == 5:  # Autodecrement deferred
            content = f'''// PDP-11 JMP instruction - {mode_desc} mode

{COMMON_HEADER}
var dst_reg[2:0];
var ptr_addr[15:0];
var target[15:0];
var ptr_lo[7:0];
var ptr_hi[7:0];

{FETCH_INSTR}

assume instr[15:6] == 0b0000000001;  // JMP opcode
assume instr[5:3] == {mode_bits};      // Mode {mode_num} ({mode_desc})

dst_reg = instr[2:0];

pc = pc + 2;

ptr_addr = rf[dst_reg] - 2;
rf[dst_reg] when (dst_reg != 7) = ptr_addr;

ptr_lo = umem[ptr_addr];
ptr_hi = umem[ptr_addr + 1];
target = {{ptr_hi, ptr_lo}};
pc = target;
'''
        elif mode_num == 6:  # Index
            content = f'''// PDP-11 JMP instruction - {mode_desc} mode

{COMMON_HEADER}
var dst_reg[2:0];
var offset[15:0];
var base_addr[15:0];
var target[15:0];
var off_lo[7:0];
var off_hi[7:0];

{FETCH_INSTR}

assume instr[15:6] == 0b0000000001;  // JMP opcode
assume instr[5:3] == {mode_bits};      // Mode {mode_num} ({mode_desc})

dst_reg = instr[2:0];

pc = pc + 2;

off_lo = umem[pc];
off_hi = umem[pc + 1];
offset = {{off_hi, off_lo}};
pc = pc + 2;

base_addr = dst_reg == 7 ? pc : rf[dst_reg];
target = base_addr + offset;
pc = target;
'''
        elif mode_num == 7:  # Index deferred
            content = f'''// PDP-11 JMP instruction - {mode_desc} mode

{COMMON_HEADER}
var dst_reg[2:0];
var offset[15:0];
var base_addr[15:0];
var ptr_addr[15:0];
var target[15:0];
var off_lo[7:0];
var off_hi[7:0];
var ptr_lo[7:0];
var ptr_hi[7:0];

{FETCH_INSTR}

assume instr[15:6] == 0b0000000001;  // JMP opcode
assume instr[5:3] == {mode_bits};      // Mode {mode_num} ({mode_desc})

dst_reg = instr[2:0];

pc = pc + 2;

off_lo = umem[pc];
off_hi = umem[pc + 1];
offset = {{off_hi, off_lo}};
pc = pc + 2;

base_addr = dst_reg == 7 ? pc : rf[dst_reg];
ptr_addr = base_addr + offset;

ptr_lo = umem[ptr_addr];
ptr_hi = umem[ptr_addr + 1];
target = {{ptr_hi, ptr_lo}};
pc = target;
'''

        filename = f"jmp_{mode_suffix}.isa"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w') as f:
            f.write(content)
        files_created.append(filename)

    # JSR - all valid addressing modes (modes 1-7, mode 0 is illegal)
    # JSR format: opcode[15:9]=0000100, link_reg[8:6], mode[5:3], reg[2:0]
    for mode_num, mode_suffix, mode_bits, mode_desc in jmp_modes:
        # Build target computation based on mode
        if mode_num == 1:  # Register deferred
            target_vars = 'var target[15:0];'
            target_code = 'target = rf[addr_reg];'
        elif mode_num == 2:  # Autoincrement
            target_vars = 'var target[15:0];'
            target_code = 'target = rf[addr_reg];\nrf[addr_reg] when (addr_reg != 7) = rf[addr_reg] + 2;'
        elif mode_num == 3:  # Autoincrement deferred
            target_vars = 'var ptr_addr[15:0];\nvar target[15:0];\nvar ptr_lo[7:0];\nvar ptr_hi[7:0];'
            target_code = 'ptr_addr = rf[addr_reg];\nrf[addr_reg] when (addr_reg != 7) = rf[addr_reg] + 2;\nptr_lo = umem[ptr_addr];\nptr_hi = umem[ptr_addr + 1];\ntarget = {ptr_hi, ptr_lo};'
        elif mode_num == 4:  # Autodecrement
            target_vars = 'var target[15:0];'
            target_code = 'target = rf[addr_reg] - 2;\nrf[addr_reg] when (addr_reg != 7) = target;'
        elif mode_num == 5:  # Autodecrement deferred
            target_vars = 'var ptr_addr[15:0];\nvar target[15:0];\nvar ptr_lo[7:0];\nvar ptr_hi[7:0];'
            target_code = 'ptr_addr = rf[addr_reg] - 2;\nrf[addr_reg] when (addr_reg != 7) = ptr_addr;\nptr_lo = umem[ptr_addr];\nptr_hi = umem[ptr_addr + 1];\ntarget = {ptr_hi, ptr_lo};'
        elif mode_num == 6:  # Index
            target_vars = 'var offset[15:0];\nvar base_addr[15:0];\nvar target[15:0];\nvar off_lo[7:0];\nvar off_hi[7:0];'
            target_code = 'off_lo = umem[pc];\noff_hi = umem[pc + 1];\noffset = {off_hi, off_lo};\npc = pc + 2;\nbase_addr = addr_reg == 7 ? pc : rf[addr_reg];\ntarget = base_addr + offset;'
        elif mode_num == 7:  # Index deferred
            target_vars = 'var offset[15:0];\nvar base_addr[15:0];\nvar ptr_addr[15:0];\nvar target[15:0];\nvar off_lo[7:0];\nvar off_hi[7:0];\nvar ptr_lo[7:0];\nvar ptr_hi[7:0];'
            target_code = 'off_lo = umem[pc];\noff_hi = umem[pc + 1];\noffset = {off_hi, off_lo};\npc = pc + 2;\nbase_addr = addr_reg == 7 ? pc : rf[addr_reg];\nptr_addr = base_addr + offset;\nptr_lo = umem[ptr_addr];\nptr_hi = umem[ptr_addr + 1];\ntarget = {ptr_hi, ptr_lo};'

        content = f'''// PDP-11 JSR instruction - {mode_desc} mode
// JSR Rn, dst: push Rn, Rn = PC, PC = dst

{COMMON_HEADER}
var link_reg[2:0];
var addr_reg[2:0];
var sp[15:0];
var saved_link[15:0];
{target_vars}

{FETCH_INSTR}

assume instr[15:9] == 0b0000100;  // JSR opcode
assume instr[5:3] == {mode_bits};   // Mode {mode_num} ({mode_desc})

link_reg = instr[8:6];
addr_reg = instr[2:0];

pc = pc + 2;

// Compute target address
{target_code}

// Save link register to stack (push)
sp = rf[6] - 2;
rf[6] = sp;
saved_link = link_reg == 7 ? pc : rf[link_reg];
umem[sp] = saved_link[7:0];
umem[sp + 1] = saved_link[15:8];

// Link register gets return address
rf[link_reg] when (link_reg != 7) = pc;

// Jump to target
pc = target;
'''
        filename = f"jsr_{mode_suffix}.isa"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w') as f:
            f.write(content)
        files_created.append(filename)

    # RTS
    content = f'''// PDP-11 RTS instruction
// RTS Rn: PC = Rn, Rn = (SP)+

{COMMON_HEADER}
var link_reg[2:0];
var sp[15:0];
var saved_link[15:0];
var link_lo[7:0];
var link_hi[7:0];

{FETCH_INSTR}

assume instr[15:3] == 0b0000000010000;  // RTS opcode

link_reg = instr[2:0];

// PC = link register
var new_pc[15:0];
new_pc = link_reg == 7 ? pc : rf[link_reg];

pc = pc + 2;

// Pop saved link from stack
sp = rf[6];
link_lo = umem[sp];
link_hi = umem[sp + 1];
saved_link = {{link_hi, link_lo}};
rf[6] = sp + 2;

// Restore link register
rf[link_reg] when (link_reg != 7) = saved_link;

pc = new_pc;
'''
    filepath = os.path.join(output_dir, "rts.isa")
    with open(filepath, 'w') as f:
        f.write(content)
    files_created.append("rts.isa")

    # SOB
    content = f'''// PDP-11 SOB instruction
// SOB Rn, offset: Rn = Rn - 1; if Rn != 0, PC = PC - 2*offset

{COMMON_HEADER}
var reg_num[2:0];
var offset[5:0];
var reg_val[15:0];
var result[15:0];
var target[15:0];

{FETCH_INSTR}

assume instr[15:9] == 0b0111111;  // SOB opcode (077)

reg_num = instr[8:6];
offset = instr[5:0];

pc = pc + 2;

reg_val = rf[reg_num];
result = reg_val - 1;
rf[reg_num] = result;

// Branch backward if result != 0
target = pc - ({{10'b0, offset}} << 1);
pc = (result != 0) ? target : pc;
'''
    filepath = os.path.join(output_dir, "sob.isa")
    with open(filepath, 'w') as f:
        f.write(content)
    files_created.append("sob.isa")

    # ===== SYSTEM INSTRUCTIONS =====

    # NOP
    content = f'''// PDP-11 NOP instruction

{COMMON_HEADER}
{FETCH_INSTR}

assume instr[15:0] == 16'b0000000010100000;  // NOP = 000240 octal

pc = pc + 2;
'''
    filepath = os.path.join(output_dir, "nop.isa")
    with open(filepath, 'w') as f:
        f.write(content)
    files_created.append("nop.isa")

    # HALT
    content = f'''// PDP-11 HALT instruction

{SYSTEM_HEADER}
{FETCH_INSTR}

assume instr[15:0] == 16'b0000000000000000;  // HALT = 000000

pc = pc + 2;
halted = 1;
'''
    filepath = os.path.join(output_dir, "halt.isa")
    with open(filepath, 'w') as f:
        f.write(content)
    files_created.append("halt.isa")

    # WAIT
    content = f'''// PDP-11 WAIT instruction

{SYSTEM_HEADER}
{FETCH_INSTR}

assume instr[15:0] == 16'b0000000000000001;  // WAIT = 000001

pc = pc + 2;
waiting = 1;
'''
    filepath = os.path.join(output_dir, "wait.isa")
    with open(filepath, 'w') as f:
        f.write(content)
    files_created.append("wait.isa")

    # RESET
    content = f'''// PDP-11 RESET instruction

{SYSTEM_HEADER}
{FETCH_INSTR}

assume instr[15:0] == 16'b0000000000000101;  // RESET = 000005

pc = pc + 2;
'''
    filepath = os.path.join(output_dir, "reset.isa")
    with open(filepath, 'w') as f:
        f.write(content)
    files_created.append("reset.isa")

    # RTI
    content = f'''// PDP-11 RTI instruction

{COMMON_HEADER}
var sp[15:0];
var new_pc[15:0];
var new_psw[15:0];
var pc_lo[7:0];
var pc_hi[7:0];
var psw_lo[7:0];
var psw_hi[7:0];

{FETCH_INSTR}

assume instr[15:0] == 16'b0000000000000010;  // RTI = 000002

// Pop PC
sp = rf[6];
pc_lo = umem[sp];
pc_hi = umem[sp + 1];
new_pc = {{pc_hi, pc_lo}};
rf[6] = sp + 2;

// Pop PSW
sp = rf[6];
psw_lo = umem[sp];
psw_hi = umem[sp + 1];
new_psw = {{psw_hi, psw_lo}};
rf[6] = sp + 2;

pc = new_pc;
flag_N = new_psw[3];
flag_Z = new_psw[2];
flag_V = new_psw[1];
flag_C = new_psw[0];
'''
    filepath = os.path.join(output_dir, "rti.isa")
    with open(filepath, 'w') as f:
        f.write(content)
    files_created.append("rti.isa")

    # RTT
    content = f'''// PDP-11 RTT instruction

{COMMON_HEADER}
var sp[15:0];
var new_pc[15:0];
var new_psw[15:0];
var pc_lo[7:0];
var pc_hi[7:0];
var psw_lo[7:0];
var psw_hi[7:0];

{FETCH_INSTR}

assume instr[15:0] == 16'b0000000000000110;  // RTT = 000006

sp = rf[6];
pc_lo = umem[sp];
pc_hi = umem[sp + 1];
new_pc = {{pc_hi, pc_lo}};
rf[6] = sp + 2;

sp = rf[6];
psw_lo = umem[sp];
psw_hi = umem[sp + 1];
new_psw = {{psw_hi, psw_lo}};
rf[6] = sp + 2;

pc = new_pc;
flag_N = new_psw[3];
flag_Z = new_psw[2];
flag_V = new_psw[1];
flag_C = new_psw[0];
'''
    filepath = os.path.join(output_dir, "rtt.isa")
    with open(filepath, 'w') as f:
        f.write(content)
    files_created.append("rtt.isa")

    # ===== TRAP INSTRUCTIONS =====

    traps = [
        ('bpt', '16\'b0000000000000011', '14'),
        ('iot', '16\'b0000000000000100', '20'),
    ]

    for name, opcode, vector in traps:
        content = f'''// PDP-11 {name.upper()} instruction

{COMMON_HEADER}
var sp[15:0];
var psw[15:0];
var new_pc[15:0];
var vec_lo[7:0];
var vec_hi[7:0];

{FETCH_INSTR}

assume instr[15:0] == {opcode};

pc = pc + 2;

psw = {{12'b0, flag_N, flag_Z, flag_V, flag_C}};

// Push PSW
sp = rf[6] - 2;
rf[6] = sp;
umem[sp] = psw[7:0];
umem[sp + 1] = psw[15:8];

// Push PC
sp = rf[6] - 2;
rf[6] = sp;
umem[sp] = pc[7:0];
umem[sp + 1] = pc[15:8];

// Load new PC from vector
vec_lo = umem[16'd{int(vector, 8)}];
vec_hi = umem[16'd{int(vector, 8)} + 1];
new_pc = {{vec_hi, vec_lo}};
pc = new_pc;
'''
        filename = f"{name}.isa"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w') as f:
            f.write(content)
        files_created.append(filename)

    # EMT and TRAP
    for name, opcode_hi, vector in [('emt', '0b10001000', '30'), ('trap', '0b10001001', '34')]:
        content = f'''// PDP-11 {name.upper()} instruction

{COMMON_HEADER}
var sp[15:0];
var psw[15:0];
var new_pc[15:0];
var trap_num[7:0];
var vec_lo[7:0];
var vec_hi[7:0];

{FETCH_INSTR}

assume instr[15:8] == {opcode_hi};

trap_num = instr[7:0];
pc = pc + 2;

psw = {{12'b0, flag_N, flag_Z, flag_V, flag_C}};

sp = rf[6] - 2;
rf[6] = sp;
umem[sp] = psw[7:0];
umem[sp + 1] = psw[15:8];

sp = rf[6] - 2;
rf[6] = sp;
umem[sp] = pc[7:0];
umem[sp + 1] = pc[15:8];

vec_lo = umem[16'd{int(vector, 8)}];
vec_hi = umem[16'd{int(vector, 8)} + 1];
new_pc = {{vec_hi, vec_lo}};
pc = new_pc;
'''
        filename = f"{name}.isa"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w') as f:
            f.write(content)
        files_created.append(filename)

    # MARK
    content = f'''// PDP-11 MARK instruction

{COMMON_HEADER}
var n[5:0];
var sp[15:0];
var r5_lo[7:0];
var r5_hi[7:0];
var r5_val[15:0];

{FETCH_INSTR}

assume instr[15:6] == 0b0000110100;  // MARK opcode

n = instr[5:0];
pc = pc + 2;

sp = pc + ({{10'b0, n}} << 1);
rf[6] = sp;

pc = rf[5];

r5_lo = umem[sp];
r5_hi = umem[sp + 1];
r5_val = {{r5_hi, r5_lo}};
rf[5] = r5_val;
rf[6] = sp + 2;
'''
    filepath = os.path.join(output_dir, "mark.isa")
    with open(filepath, 'w') as f:
        f.write(content)
    files_created.append("mark.isa")

    # ===== CONDITION CODE INSTRUCTIONS =====

    cc_ops = [
        ('clc', '16\'b0000000010100001', 'flag_C = 0;'),
        ('clv', '16\'b0000000010100010', 'flag_V = 0;'),
        ('clz', '16\'b0000000010100100', 'flag_Z = 0;'),
        ('cln', '16\'b0000000010101000', 'flag_N = 0;'),
        ('sec', '16\'b0000000010110001', 'flag_C = 1;'),
        ('sev', '16\'b0000000010110010', 'flag_V = 1;'),
        ('sez', '16\'b0000000010110100', 'flag_Z = 1;'),
        ('sen', '16\'b0000000010111000', 'flag_N = 1;'),
        ('ccc', '16\'b0000000010101111', 'flag_C = 0;\nflag_V = 0;\nflag_Z = 0;\nflag_N = 0;'),
        ('scc', '16\'b0000000010111111', 'flag_C = 1;\nflag_V = 1;\nflag_Z = 1;\nflag_N = 1;'),
    ]

    for name, opcode, operation in cc_ops:
        content = f'''// PDP-11 {name.upper()} instruction

{COMMON_HEADER}
{FETCH_INSTR}

assume instr[15:0] == {opcode};

pc = pc + 2;
{operation}
'''
        filename = f"{name}.isa"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w') as f:
            f.write(content)
        files_created.append(filename)

    # ===== MEMORY MANAGEMENT =====

    # MFPI
    content = f'''// PDP-11 MFPI instruction

{COMMON_HEADER}
var src_reg[2:0];
var src_val[15:0];
var sp[15:0];

{FETCH_INSTR}

assume instr[15:6] == 0b0000110101;  // MFPI opcode 0065
assume instr[5:3] == 0b000;          // Register mode

src_reg = instr[2:0];
src_val = src_reg == 7 ? pc : rf[src_reg];

pc = pc + 2;

sp = rf[6] - 2;
rf[6] = sp;
umem[sp] = src_val[7:0];
umem[sp + 1] = src_val[15:8];

flag_N = src_val[15];
flag_Z = src_val == 0 ? 1'b1 : 1'b0;
flag_V = 0;
'''
    filepath = os.path.join(output_dir, "mfpi.isa")
    with open(filepath, 'w') as f:
        f.write(content)
    files_created.append("mfpi.isa")

    # MFPD
    content = f'''// PDP-11 MFPD instruction

{COMMON_HEADER}
var src_reg[2:0];
var src_val[15:0];
var sp[15:0];

{FETCH_INSTR}

assume instr[15:6] == 0b1000110101;  // MFPD opcode 1065
assume instr[5:3] == 0b000;

src_reg = instr[2:0];
src_val = src_reg == 7 ? pc : rf[src_reg];

pc = pc + 2;

sp = rf[6] - 2;
rf[6] = sp;
umem[sp] = src_val[7:0];
umem[sp + 1] = src_val[15:8];

flag_N = src_val[15];
flag_Z = src_val == 0 ? 1'b1 : 1'b0;
flag_V = 0;
'''
    filepath = os.path.join(output_dir, "mfpd.isa")
    with open(filepath, 'w') as f:
        f.write(content)
    files_created.append("mfpd.isa")

    # MTPI
    content = f'''// PDP-11 MTPI instruction

{COMMON_HEADER}
var dst_reg[2:0];
var sp[15:0];
var src_val[15:0];
var src_lo[7:0];
var src_hi[7:0];

{FETCH_INSTR}

assume instr[15:6] == 0b0000110110;  // MTPI opcode 0066
assume instr[5:3] == 0b000;

dst_reg = instr[2:0];

pc = pc + 2;

sp = rf[6];
src_lo = umem[sp];
src_hi = umem[sp + 1];
src_val = {{src_hi, src_lo}};
rf[6] = sp + 2;

rf[dst_reg] when (dst_reg != 7) = src_val;

flag_N = src_val[15];
flag_Z = src_val == 0 ? 1'b1 : 1'b0;
flag_V = 0;
'''
    filepath = os.path.join(output_dir, "mtpi.isa")
    with open(filepath, 'w') as f:
        f.write(content)
    files_created.append("mtpi.isa")

    # MTPD
    content = f'''// PDP-11 MTPD instruction

{COMMON_HEADER}
var dst_reg[2:0];
var sp[15:0];
var src_val[15:0];
var src_lo[7:0];
var src_hi[7:0];

{FETCH_INSTR}

assume instr[15:6] == 0b1000110110;  // MTPD opcode 1066
assume instr[5:3] == 0b000;

dst_reg = instr[2:0];

pc = pc + 2;

sp = rf[6];
src_lo = umem[sp];
src_hi = umem[sp + 1];
src_val = {{src_hi, src_lo}};
rf[6] = sp + 2;

rf[dst_reg] when (dst_reg != 7) = src_val;

flag_N = src_val[15];
flag_Z = src_val == 0 ? 1'b1 : 1'b0;
flag_V = 0;
'''
    filepath = os.path.join(output_dir, "mtpd.isa")
    with open(filepath, 'w') as f:
        f.write(content)
    files_created.append("mtpd.isa")

    # MFPS
    content = f'''// PDP-11 MFPS instruction

{COMMON_HEADER}
var dst_reg[2:0];
var psw[7:0];
var extended[15:0];

{FETCH_INSTR}

assume instr[15:6] == 0b1000110111;  // MFPS opcode 1067
assume instr[5:3] == 0b000;

dst_reg = instr[2:0];

pc = pc + 2;

psw = {{4'b0, flag_N, flag_Z, flag_V, flag_C}};
extended = psw[7] ? {{8'hFF, psw}} : {{8'h00, psw}};
rf[dst_reg] when (dst_reg != 7) = extended;

flag_N = psw[7];
flag_Z = psw == 0 ? 1'b1 : 1'b0;
flag_V = 0;
'''
    filepath = os.path.join(output_dir, "mfps.isa")
    with open(filepath, 'w') as f:
        f.write(content)
    files_created.append("mfps.isa")

    # MTPS
    content = f'''// PDP-11 MTPS instruction

{COMMON_HEADER}
var src_reg[2:0];
var src_val[7:0];

{FETCH_INSTR}

assume instr[15:6] == 0b1000110100;  // MTPS opcode 1064
assume instr[5:3] == 0b000;

src_reg = instr[2:0];

pc = pc + 2;

src_val = rf[src_reg][7:0];

flag_N = src_val[3];
flag_Z = src_val[2];
flag_V = src_val[1];
flag_C = src_val[0];
'''
    filepath = os.path.join(output_dir, "mtps.isa")
    with open(filepath, 'w') as f:
        f.write(content)
    files_created.append("mtps.isa")

    # SPL
    content = f'''// PDP-11 SPL instruction

{SYSTEM_HEADER}
var new_priority[2:0];

{FETCH_INSTR}

assume instr[15:3] == 0b0000000010011;  // SPL opcode 00023x

new_priority = instr[2:0];

pc = pc + 2;

priority = new_priority;
'''
    filepath = os.path.join(output_dir, "spl.isa")
    with open(filepath, 'w') as f:
        f.write(content)
    files_created.append("spl.isa")

    return files_created


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.dirname(script_dir)

    print(f"Generating PDP-11/70 ISA files in {output_dir}")

    # Remove old generated files first
    import glob as g
    old_files = g.glob(os.path.join(output_dir, '*.isa'))
    for f in old_files:
        os.remove(f)
    print(f"Removed {len(old_files)} old ISA files")

    files = generate_all_instructions(output_dir)

    print(f"\nGenerated {len(files)} ISA files")
    return 0


if __name__ == '__main__':
    sys.exit(main())
