#!/usr/bin/env python3
"""Generate all missing MMIX instructions."""

import os

MMIX_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def write_isa(name, content):
    path = os.path.join(MMIX_DIR, f"{name}.isa")
    with open(path, 'w') as f:
        f.write(content)
    print(f"Created {name}.isa")

# SUBUI - Subtract Unsigned Immediate
write_isa('subui', '''// MMIX SUBUI - Subtract Unsigned Immediate (no overflow trap)
// SUBUI $X,$Y,Z: $X = $Y - Z (unsigned, no overflow)
// Opcode: 0x27

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_ext[63:0];
var result[63:0];

instr = umem[pc];
assume instr[31:24] == 0x27;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_ext = {56'b0, z};
result = y_val - z_ext;

rf[x] = result;
pc = pc + 4;
''')

# NEGU - Negate Unsigned
write_isa('negu', '''// MMIX NEGU - Negate Unsigned (no overflow trap)
// NEGU $X,Y,$Z: $X = Y - $Z (unsigned, no overflow)
// Opcode: 0x36

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_ext[63:0];
var z_val[63:0];
var result[63:0];

instr = umem[pc];
assume instr[31:24] == 0x36;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_ext = {56'b0, y};
z_val = rf[z];
result = y_ext - z_val;

rf[x] = result;
pc = pc + 4;
''')

# NEGUI - Negate Unsigned Immediate
write_isa('negui', '''// MMIX NEGUI - Negate Unsigned Immediate (no overflow trap)
// NEGUI $X,Y,Z: $X = Y - Z (unsigned, no overflow)
// Opcode: 0x37

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_ext[63:0];
var z_ext[63:0];
var result[63:0];

instr = umem[pc];
assume instr[31:24] == 0x37;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_ext = {56'b0, y};
z_ext = {56'b0, z};
result = y_ext - z_ext;

rf[x] = result;
pc = pc + 4;
''')

# Scaled address instructions
scaled_ops = [
    ('2addu', 0x28, 1),
    ('2addui', 0x29, 1),
    ('4addu', 0x2A, 2),
    ('4addui', 0x2B, 2),
    ('8addu', 0x2C, 3),
    ('8addui', 0x2D, 3),
    ('16addu', 0x2E, 4),
    ('16addui', 0x2F, 4),
]

for name, opcode, shift in scaled_ops:
    is_imm = name.endswith('i')
    mult = 2 ** shift
    if is_imm:
        write_isa(name, f'''// MMIX {name.upper()} - {mult}x Add Unsigned Immediate
// {name.upper()} $X,$Y,Z: $X = ($Y << {shift}) + Z
// Opcode: 0x{opcode:02X}

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var y_shifted[63:0];
var z_ext[63:0];
var result[63:0];

instr = umem[pc];
assume instr[31:24] == 0x{opcode:02X};

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
y_shifted = y_val << {shift};
z_ext = {{56'b0, z}};
result = y_shifted + z_ext;

rf[x] = result;
pc = pc + 4;
''')
    else:
        write_isa(name, f'''// MMIX {name.upper()} - {mult}x Add Unsigned
// {name.upper()} $X,$Y,$Z: $X = ($Y << {shift}) + $Z
// Opcode: 0x{opcode:02X}

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var y_shifted[63:0];
var z_val[63:0];
var result[63:0];

instr = umem[pc];
assume instr[31:24] == 0x{opcode:02X};

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
y_shifted = y_val << {shift};
z_val = rf[z];
result = y_shifted + z_val;

rf[x] = result;
pc = pc + 4;
''')

# BNP - Branch if Not Positive (forward)
write_isa('bnp', '''// MMIX BNP - Branch if Not Positive (forward)
// BNP $X,YZ: if $X <= 0, PC = PC + 4*YZ
// Opcode: 0x46

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var yz[15:0];
var x_val[63:0];
var offset[63:0];
var target[63:0];
var cond[0:0];
var is_neg[0:0];
var is_zero[0:0];

instr = umem[pc];
assume instr[31:24] == 0x46;

x = instr[23:16];
yz = instr[15:0];

x_val = rf[x];
offset = {46'b0, yz, 2'b0};
target = pc + offset;

is_neg = x_val[63];
is_zero = x_val == 0;
cond = is_neg | is_zero;

pc = cond ? target : pc + 4;
''')

# BNPB - Branch if Not Positive (backward)
write_isa('bnpb', '''// MMIX BNPB - Branch if Not Positive (backward)
// BNPB $X,YZ: if $X <= 0, PC = PC - 4*YZ
// Opcode: 0x47

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var yz[15:0];
var x_val[63:0];
var offset[63:0];
var target[63:0];
var cond[0:0];
var is_neg[0:0];
var is_zero[0:0];

instr = umem[pc];
assume instr[31:24] == 0x47;

x = instr[23:16];
yz = instr[15:0];

x_val = rf[x];
offset = {46'b0, yz, 2'b0};
target = pc - offset;

is_neg = x_val[63];
is_zero = x_val == 0;
cond = is_neg | is_zero;

pc = cond ? target : pc + 4;
''')

# PBNP - Probable Branch if Not Positive (forward)
write_isa('pbnp', '''// MMIX PBNP - Probable Branch if Not Positive (forward)
// PBNP $X,YZ: if $X <= 0, PC = PC + 4*YZ (hint: likely)
// Opcode: 0x56

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var yz[15:0];
var x_val[63:0];
var offset[63:0];
var target[63:0];
var cond[0:0];
var is_neg[0:0];
var is_zero[0:0];

instr = umem[pc];
assume instr[31:24] == 0x56;

x = instr[23:16];
yz = instr[15:0];

x_val = rf[x];
offset = {46'b0, yz, 2'b0};
target = pc + offset;

is_neg = x_val[63];
is_zero = x_val == 0;
cond = is_neg | is_zero;

pc = cond ? target : pc + 4;
''')

# PBNPB - Probable Branch if Not Positive (backward)
write_isa('pbnpb', '''// MMIX PBNPB - Probable Branch if Not Positive (backward)
// PBNPB $X,YZ: if $X <= 0, PC = PC - 4*YZ (hint: likely)
// Opcode: 0x57

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var yz[15:0];
var x_val[63:0];
var offset[63:0];
var target[63:0];
var cond[0:0];
var is_neg[0:0];
var is_zero[0:0];

instr = umem[pc];
assume instr[31:24] == 0x57;

x = instr[23:16];
yz = instr[15:0];

x_val = rf[x];
offset = {46'b0, yz, 2'b0};
target = pc - offset;

is_neg = x_val[63];
is_zero = x_val == 0;
cond = is_neg | is_zero;

pc = cond ? target : pc + 4;
''')

# CSNP - Conditional Set if Not Positive
write_isa('csnp', '''// MMIX CSNP - Conditional Set if Not Positive
// CSNP $X,$Y,$Z: if $Y <= 0, $X = $Z
// Opcode: 0x6C

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var x_val[63:0];
var y_val[63:0];
var z_val[63:0];
var cond[0:0];
var is_neg[0:0];
var is_zero[0:0];
var result[63:0];

instr = umem[pc];
assume instr[31:24] == 0x6C;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

x_val = rf[x];
y_val = rf[y];
z_val = rf[z];

is_neg = y_val[63];
is_zero = y_val == 0;
cond = is_neg | is_zero;
result = cond ? z_val : x_val;

rf[x] = result;
pc = pc + 4;
''')

# CSNPI - Conditional Set if Not Positive Immediate
write_isa('csnpi', '''// MMIX CSNPI - Conditional Set if Not Positive Immediate
// CSNPI $X,$Y,Z: if $Y <= 0, $X = Z
// Opcode: 0x6D

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var x_val[63:0];
var y_val[63:0];
var z_ext[63:0];
var cond[0:0];
var is_neg[0:0];
var is_zero[0:0];
var result[63:0];

instr = umem[pc];
assume instr[31:24] == 0x6D;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

x_val = rf[x];
y_val = rf[y];
z_ext = {56'b0, z};

is_neg = y_val[63];
is_zero = y_val == 0;
cond = is_neg | is_zero;
result = cond ? z_ext : x_val;

rf[x] = result;
pc = pc + 4;
''')

# ZSNP - Zero or Set if Not Positive
write_isa('zsnp', '''// MMIX ZSNP - Zero or Set if Not Positive
// ZSNP $X,$Y,$Z: $X = ($Y <= 0) ? $Z : 0
// Opcode: 0x7C

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_val[63:0];
var cond[0:0];
var is_neg[0:0];
var is_zero[0:0];
var result[63:0];

instr = umem[pc];
assume instr[31:24] == 0x7C;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_val = rf[z];

is_neg = y_val[63];
is_zero = y_val == 0;
cond = is_neg | is_zero;
result = cond ? z_val : 64'b0;

rf[x] = result;
pc = pc + 4;
''')

# ZSNPI - Zero or Set if Not Positive Immediate
write_isa('zsnpi', '''// MMIX ZSNPI - Zero or Set if Not Positive Immediate
// ZSNPI $X,$Y,Z: $X = ($Y <= 0) ? Z : 0
// Opcode: 0x7D

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_ext[63:0];
var cond[0:0];
var is_neg[0:0];
var is_zero[0:0];
var result[63:0];

instr = umem[pc];
assume instr[31:24] == 0x7D;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_ext = {56'b0, z};

is_neg = y_val[63];
is_zero = y_val == 0;
cond = is_neg | is_zero;
result = cond ? z_ext : 64'b0;

rf[x] = result;
pc = pc + 4;
''')

# LDOU - Load Octa Unsigned (same as LDO for 64-bit)
write_isa('ldou', '''// MMIX LDOU - Load Octa Unsigned
// LDOU $X,$Y,$Z: $X = M8[$Y + $Z]
// Opcode: 0x8E

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_val[63:0];
var addr[63:0];
var data[63:0];

instr = umem[pc];
assume instr[31:24] == 0x8E;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_val = rf[z];
addr = y_val + z_val;
data = umem[addr];

rf[x] = data;
pc = pc + 4;
''')

# LDOUI - Load Octa Unsigned Immediate
write_isa('ldoui', '''// MMIX LDOUI - Load Octa Unsigned Immediate
// LDOUI $X,$Y,Z: $X = M8[$Y + Z]
// Opcode: 0x8F

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_ext[63:0];
var addr[63:0];
var data[63:0];

instr = umem[pc];
assume instr[31:24] == 0x8F;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_ext = {56'b0, z};
addr = y_val + z_ext;
data = umem[addr];

rf[x] = data;
pc = pc + 4;
''')

# LDSF - Load Short Float
write_isa('ldsf', '''// MMIX LDSF - Load Short Float
// LDSF $X,$Y,$Z: $X = (float)M4[$Y + $Z]
// Opcode: 0x90
// Note: Loads 32-bit float and converts to 64-bit

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_val[63:0];
var addr[63:0];
var word[63:0];
var data[31:0];
var result[63:0];

instr = umem[pc];
assume instr[31:24] == 0x90;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_val = rf[z];
addr = y_val + z_val;
word = umem[addr];
data = word[31:0];
// Sign extend for now (proper FP conversion would need FPU)
result = {32'b0, data};

rf[x] = result;
pc = pc + 4;
''')

# LDSFI - Load Short Float Immediate
write_isa('ldsfi', '''// MMIX LDSFI - Load Short Float Immediate
// LDSFI $X,$Y,Z: $X = (float)M4[$Y + Z]
// Opcode: 0x91

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_ext[63:0];
var addr[63:0];
var word[63:0];
var data[31:0];
var result[63:0];

instr = umem[pc];
assume instr[31:24] == 0x91;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_ext = {56'b0, z};
addr = y_val + z_ext;
word = umem[addr];
data = word[31:0];
result = {32'b0, data};

rf[x] = result;
pc = pc + 4;
''')

# LDHT - Load High Tetra
write_isa('ldht', '''// MMIX LDHT - Load High Tetra
// LDHT $X,$Y,$Z: $X = M4[$Y + $Z] << 32
// Opcode: 0x92

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_val[63:0];
var addr[63:0];
var word[63:0];
var data[31:0];
var result[63:0];

instr = umem[pc];
assume instr[31:24] == 0x92;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_val = rf[z];
addr = y_val + z_val;
word = umem[addr];
data = word[31:0];
result = {data, 32'b0};

rf[x] = result;
pc = pc + 4;
''')

# LDHTI - Load High Tetra Immediate
write_isa('ldhti', '''// MMIX LDHTI - Load High Tetra Immediate
// LDHTI $X,$Y,Z: $X = M4[$Y + Z] << 32
// Opcode: 0x93

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_ext[63:0];
var addr[63:0];
var word[63:0];
var data[31:0];
var result[63:0];

instr = umem[pc];
assume instr[31:24] == 0x93;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_ext = {56'b0, z};
addr = y_val + z_ext;
word = umem[addr];
data = word[31:0];
result = {data, 32'b0};

rf[x] = result;
pc = pc + 4;
''')

# CSWAP - Compare and Swap
write_isa('cswap', '''// MMIX CSWAP - Compare and Swap
// CSWAP $X,$Y,$Z: if M8[$Y+$Z] == rP, M8[$Y+$Z] = $X, $X = 1, else $X = 0, rP = M8[$Y+$Z]
// Opcode: 0x94
// Note: Simplified - just does atomic compare-swap with rP

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];
isa_state rP[63:0];

var x[7:0];
var y[7:0];
var z[7:0];
var x_val[63:0];
var y_val[63:0];
var z_val[63:0];
var addr[63:0];
var mem_val[63:0];
var cond[0:0];

instr = umem[pc];
assume instr[31:24] == 0x94;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

x_val = rf[x];
y_val = rf[y];
z_val = rf[z];
addr = y_val + z_val;
mem_val = umem[addr];

cond = mem_val == rP;

umem[addr] = cond ? x_val : mem_val;
rf[x] = cond ? 64'b1 : 64'b0;
rP = cond ? rP : mem_val;
pc = pc + 4;
''')

# CSWAPI - Compare and Swap Immediate
write_isa('cswapi', '''// MMIX CSWAPI - Compare and Swap Immediate
// CSWAPI $X,$Y,Z: if M8[$Y+Z] == rP, M8[$Y+Z] = $X, $X = 1, else $X = 0, rP = M8[$Y+Z]
// Opcode: 0x95

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];
isa_state rP[63:0];

var x[7:0];
var y[7:0];
var z[7:0];
var x_val[63:0];
var y_val[63:0];
var z_ext[63:0];
var addr[63:0];
var mem_val[63:0];
var cond[0:0];

instr = umem[pc];
assume instr[31:24] == 0x95;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

x_val = rf[x];
y_val = rf[y];
z_ext = {56'b0, z};
addr = y_val + z_ext;
mem_val = umem[addr];

cond = mem_val == rP;

umem[addr] = cond ? x_val : mem_val;
rf[x] = cond ? 64'b1 : 64'b0;
rP = cond ? rP : mem_val;
pc = pc + 4;
''')

# LDUNC - Load Uncached (same as LDO for simple model)
write_isa('ldunc', '''// MMIX LDUNC - Load Octa Uncached
// LDUNC $X,$Y,$Z: $X = M8[$Y + $Z] (bypasses cache)
// Opcode: 0x96

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_val[63:0];
var addr[63:0];
var data[63:0];

instr = umem[pc];
assume instr[31:24] == 0x96;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_val = rf[z];
addr = y_val + z_val;
data = umem[addr];

rf[x] = data;
pc = pc + 4;
''')

# LDUNCI - Load Uncached Immediate
write_isa('ldunci', '''// MMIX LDUNCI - Load Octa Uncached Immediate
// LDUNCI $X,$Y,Z: $X = M8[$Y + Z] (bypasses cache)
// Opcode: 0x97

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_ext[63:0];
var addr[63:0];
var data[63:0];

instr = umem[pc];
assume instr[31:24] == 0x97;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_ext = {56'b0, z};
addr = y_val + z_ext;
data = umem[addr];

rf[x] = data;
pc = pc + 4;
''')

# LDVTS - Load Virtual Translation Status
write_isa('ldvts', '''// MMIX LDVTS - Load Virtual Translation Status
// LDVTS $X,$Y,$Z: $X = virtual translation status for $Y+$Z
// Opcode: 0x98
// Note: Simplified - returns 0 (no virtual memory in simple model)

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];

instr = umem[pc];
assume instr[31:24] == 0x98;

x = instr[23:16];

rf[x] = 64'b0;
pc = pc + 4;
''')

# LDVTSI - Load Virtual Translation Status Immediate
write_isa('ldvtsi', '''// MMIX LDVTSI - Load Virtual Translation Status Immediate
// LDVTSI $X,$Y,Z: $X = virtual translation status for $Y+Z
// Opcode: 0x99
// Note: Simplified - returns 0 (no virtual memory in simple model)

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];

instr = umem[pc];
assume instr[31:24] == 0x99;

x = instr[23:16];

rf[x] = 64'b0;
pc = pc + 4;
''')

# PRELD - Preload Data (hint, no-op in simple model)
write_isa('preld', '''// MMIX PRELD - Preload Data
// PRELD X,$Y,$Z: hint to preload X+1 bytes at $Y+$Z
// Opcode: 0x9A
// Note: No-op in simple model (cache hint)

isa_state pc[63:0];
var instr[31:0];
mem umem[14:0];

instr = umem[pc];
assume instr[31:24] == 0x9A;

pc = pc + 4;
''')

# PRELDI - Preload Data Immediate
write_isa('preldi', '''// MMIX PRELDI - Preload Data Immediate
// PRELDI X,$Y,Z: hint to preload X+1 bytes at $Y+Z
// Opcode: 0x9B
// Note: No-op in simple model (cache hint)

isa_state pc[63:0];
var instr[31:0];
mem umem[14:0];

instr = umem[pc];
assume instr[31:24] == 0x9B;

pc = pc + 4;
''')

# PREGO - Preload for GO (hint, no-op in simple model)
write_isa('prego', '''// MMIX PREGO - Preload for GO
// PREGO X,$Y,$Z: hint to preload instructions at $Y+$Z
// Opcode: 0x9C
// Note: No-op in simple model (cache hint)

isa_state pc[63:0];
var instr[31:0];
mem umem[14:0];

instr = umem[pc];
assume instr[31:24] == 0x9C;

pc = pc + 4;
''')

# PREGOI - Preload for GO Immediate
write_isa('pregoi', '''// MMIX PREGOI - Preload for GO Immediate
// PREGOI X,$Y,Z: hint to preload instructions at $Y+Z
// Opcode: 0x9D
// Note: No-op in simple model (cache hint)

isa_state pc[63:0];
var instr[31:0];
mem umem[14:0];

instr = umem[pc];
assume instr[31:24] == 0x9D;

pc = pc + 4;
''')

# Store unsigned variants (same as signed for stores)
store_unsigned = [
    ('stbu', 0xA2, 'Byte'),
    ('stbui', 0xA3, 'Byte'),
    ('stwu', 0xA6, 'Wyde'),
    ('stwui', 0xA7, 'Wyde'),
    ('sttu', 0xAA, 'Tetra'),
    ('sttui', 0xAB, 'Tetra'),
    ('stou', 0xAE, 'Octa'),
    ('stoui', 0xAF, 'Octa'),
]

for name, opcode, size in store_unsigned:
    is_imm = name.endswith('i')
    if size == 'Byte':
        bits = '[7:0]'
    elif size == 'Wyde':
        bits = '[15:0]'
    elif size == 'Tetra':
        bits = '[31:0]'
    else:
        bits = '[63:0]'

    if is_imm:
        write_isa(name, f'''// MMIX {name.upper()} - Store {size} Unsigned Immediate
// {name.upper()} $X,$Y,Z: M{bits}[$Y + Z] = $X{bits}
// Opcode: 0x{opcode:02X}

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var x_val[63:0];
var y_val[63:0];
var z_ext[63:0];
var addr[63:0];

instr = umem[pc];
assume instr[31:24] == 0x{opcode:02X};

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

x_val = rf[x];
y_val = rf[y];
z_ext = {{56'b0, z}};
addr = y_val + z_ext;

umem[addr] = x_val;
pc = pc + 4;
''')
    else:
        write_isa(name, f'''// MMIX {name.upper()} - Store {size} Unsigned
// {name.upper()} $X,$Y,$Z: M{bits}[$Y + $Z] = $X{bits}
// Opcode: 0x{opcode:02X}

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var x_val[63:0];
var y_val[63:0];
var z_val[63:0];
var addr[63:0];

instr = umem[pc];
assume instr[31:24] == 0x{opcode:02X};

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

x_val = rf[x];
y_val = rf[y];
z_val = rf[z];
addr = y_val + z_val;

umem[addr] = x_val;
pc = pc + 4;
''')

# STSF - Store Short Float
write_isa('stsf', '''// MMIX STSF - Store Short Float
// STSF $X,$Y,$Z: M4[$Y + $Z] = (short float)$X
// Opcode: 0xB0

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var x_val[63:0];
var y_val[63:0];
var z_val[63:0];
var addr[63:0];

instr = umem[pc];
assume instr[31:24] == 0xB0;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

x_val = rf[x];
y_val = rf[y];
z_val = rf[z];
addr = y_val + z_val;

umem[addr] = {32'b0, x_val[31:0]};
pc = pc + 4;
''')

# STSFI - Store Short Float Immediate
write_isa('stsfi', '''// MMIX STSFI - Store Short Float Immediate
// STSFI $X,$Y,Z: M4[$Y + Z] = (short float)$X
// Opcode: 0xB1

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var x_val[63:0];
var y_val[63:0];
var z_ext[63:0];
var addr[63:0];

instr = umem[pc];
assume instr[31:24] == 0xB1;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

x_val = rf[x];
y_val = rf[y];
z_ext = {56'b0, z};
addr = y_val + z_ext;

umem[addr] = {32'b0, x_val[31:0]};
pc = pc + 4;
''')

# STHT - Store High Tetra
write_isa('stht', '''// MMIX STHT - Store High Tetra
// STHT $X,$Y,$Z: M4[$Y + $Z] = $X >> 32
// Opcode: 0xB2

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var x_val[63:0];
var y_val[63:0];
var z_val[63:0];
var addr[63:0];

instr = umem[pc];
assume instr[31:24] == 0xB2;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

x_val = rf[x];
y_val = rf[y];
z_val = rf[z];
addr = y_val + z_val;

umem[addr] = {32'b0, x_val[63:32]};
pc = pc + 4;
''')

# STHTI - Store High Tetra Immediate
write_isa('sthti', '''// MMIX STHTI - Store High Tetra Immediate
// STHTI $X,$Y,Z: M4[$Y + Z] = $X >> 32
// Opcode: 0xB3

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var x_val[63:0];
var y_val[63:0];
var z_ext[63:0];
var addr[63:0];

instr = umem[pc];
assume instr[31:24] == 0xB3;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

x_val = rf[x];
y_val = rf[y];
z_ext = {56'b0, z};
addr = y_val + z_ext;

umem[addr] = {32'b0, x_val[63:32]};
pc = pc + 4;
''')

# STCO - Store Constant Octa
write_isa('stco', '''// MMIX STCO - Store Constant Octa
// STCO X,$Y,$Z: M8[$Y + $Z] = X
// Opcode: 0xB4

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_val[63:0];
var addr[63:0];
var x_ext[63:0];

instr = umem[pc];
assume instr[31:24] == 0xB4;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_val = rf[z];
addr = y_val + z_val;
x_ext = {56'b0, x};

umem[addr] = x_ext;
pc = pc + 4;
''')

# STCOI - Store Constant Octa Immediate
write_isa('stcoi', '''// MMIX STCOI - Store Constant Octa Immediate
// STCOI X,$Y,Z: M8[$Y + Z] = X
// Opcode: 0xB5

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_ext[63:0];
var addr[63:0];
var x_ext[63:0];

instr = umem[pc];
assume instr[31:24] == 0xB5;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_ext = {56'b0, z};
addr = y_val + z_ext;
x_ext = {56'b0, x};

umem[addr] = x_ext;
pc = pc + 4;
''')

# STUNC - Store Uncached
write_isa('stunc', '''// MMIX STUNC - Store Octa Uncached
// STUNC $X,$Y,$Z: M8[$Y + $Z] = $X (bypasses cache)
// Opcode: 0xB6

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var x_val[63:0];
var y_val[63:0];
var z_val[63:0];
var addr[63:0];

instr = umem[pc];
assume instr[31:24] == 0xB6;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

x_val = rf[x];
y_val = rf[y];
z_val = rf[z];
addr = y_val + z_val;

umem[addr] = x_val;
pc = pc + 4;
''')

# STUNCI - Store Uncached Immediate
write_isa('stunci', '''// MMIX STUNCI - Store Octa Uncached Immediate
// STUNCI $X,$Y,Z: M8[$Y + Z] = $X (bypasses cache)
// Opcode: 0xB7

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var x_val[63:0];
var y_val[63:0];
var z_ext[63:0];
var addr[63:0];

instr = umem[pc];
assume instr[31:24] == 0xB7;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

x_val = rf[x];
y_val = rf[y];
z_ext = {56'b0, z};
addr = y_val + z_ext;

umem[addr] = x_val;
pc = pc + 4;
''')

# SYNCD - Synchronize Data
write_isa('syncd', '''// MMIX SYNCD - Synchronize Data
// SYNCD X,$Y,$Z: ensure X+1 bytes at $Y+$Z are written to memory
// Opcode: 0xB8
// Note: No-op in simple model (cache sync)

isa_state pc[63:0];
var instr[31:0];
mem umem[14:0];

instr = umem[pc];
assume instr[31:24] == 0xB8;

pc = pc + 4;
''')

# SYNCDI - Synchronize Data Immediate
write_isa('syncdi', '''// MMIX SYNCDI - Synchronize Data Immediate
// SYNCDI X,$Y,Z: ensure X+1 bytes at $Y+Z are written to memory
// Opcode: 0xB9
// Note: No-op in simple model (cache sync)

isa_state pc[63:0];
var instr[31:0];
mem umem[14:0];

instr = umem[pc];
assume instr[31:24] == 0xB9;

pc = pc + 4;
''')

# PREST - Prestore Data
write_isa('prest', '''// MMIX PREST - Prestore Data
// PREST X,$Y,$Z: hint that X+1 bytes at $Y+$Z will be stored
// Opcode: 0xBA
// Note: No-op in simple model (cache hint)

isa_state pc[63:0];
var instr[31:0];
mem umem[14:0];

instr = umem[pc];
assume instr[31:24] == 0xBA;

pc = pc + 4;
''')

# PRESTI - Prestore Data Immediate
write_isa('presti', '''// MMIX PRESTI - Prestore Data Immediate
// PRESTI X,$Y,Z: hint that X+1 bytes at $Y+Z will be stored
// Opcode: 0xBB
// Note: No-op in simple model (cache hint)

isa_state pc[63:0];
var instr[31:0];
mem umem[14:0];

instr = umem[pc];
assume instr[31:24] == 0xBB;

pc = pc + 4;
''')

# SYNCID - Synchronize Instructions and Data
write_isa('syncid', '''// MMIX SYNCID - Synchronize Instructions and Data
// SYNCID X,$Y,$Z: ensure instructions and data at $Y+$Z are coherent
// Opcode: 0xBC
// Note: No-op in simple model

isa_state pc[63:0];
var instr[31:0];
mem umem[14:0];

instr = umem[pc];
assume instr[31:24] == 0xBC;

pc = pc + 4;
''')

# SYNCIDI - Synchronize Instructions and Data Immediate
write_isa('syncidi', '''// MMIX SYNCIDI - Synchronize Instructions and Data Immediate
// SYNCIDI X,$Y,Z: ensure instructions and data at $Y+Z are coherent
// Opcode: 0xBD
// Note: No-op in simple model

isa_state pc[63:0];
var instr[31:0];
mem umem[14:0];

instr = umem[pc];
assume instr[31:24] == 0xBD;

pc = pc + 4;
''')

# NXOR - Logical Equivalence (NOT XOR)
write_isa('nxor', '''// MMIX NXOR - Logical Equivalence
// NXOR $X,$Y,$Z: $X = ~($Y ^ $Z)
// Opcode: 0xCE

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_val[63:0];
var result[63:0];

instr = umem[pc];
assume instr[31:24] == 0xCE;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_val = rf[z];
result = ~(y_val ^ z_val);

rf[x] = result;
pc = pc + 4;
''')

# NXORI - Logical Equivalence Immediate
write_isa('nxori', '''// MMIX NXORI - Logical Equivalence Immediate
// NXORI $X,$Y,Z: $X = ~($Y ^ Z)
// Opcode: 0xCF

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_ext[63:0];
var result[63:0];

instr = umem[pc];
assume instr[31:24] == 0xCF;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_ext = {56'b0, z};
result = ~(y_val ^ z_ext);

rf[x] = result;
pc = pc + 4;
''')

# FCMPE - Floating Compare with Epsilon
write_isa('fcmpe', '''// MMIX FCMPE - Floating Compare with Epsilon
// FCMPE $X,$Y,$Z: $X = fp_cmp_epsilon($Y, $Z, rE)
// Opcode: 0x10
// Note: Simplified - same as FCMP for now

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_val[63:0];
var result[63:0];
var y_neg[0:0];
var z_neg[0:0];
var y_gt_z[0:0];
var y_lt_z[0:0];

instr = umem[pc];
assume instr[31:24] == 0x10;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_val = rf[z];

// Simplified comparison (not true epsilon comparison)
y_neg = y_val[63];
z_neg = z_val[63];
y_gt_z = (y_val > z_val);
y_lt_z = (y_val < z_val);

result = y_gt_z ? 64'd1 : (y_lt_z ? 64'hFFFFFFFFFFFFFFFF : 64'd0);

rf[x] = result;
pc = pc + 4;
''')

# FEQLE - Floating Equal with Epsilon
write_isa('feqle', '''// MMIX FEQLE - Floating Equal with Epsilon
// FEQLE $X,$Y,$Z: $X = (|$Y - $Z| <= rE) ? 1 : 0
// Opcode: 0x12
// Note: Simplified - same as FEQL for now

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_val[63:0];
var result[63:0];
var eq[0:0];

instr = umem[pc];
assume instr[31:24] == 0x12;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_val = rf[z];

// Simplified - exact equality
eq = y_val == z_val;
result = eq ? 64'd1 : 64'd0;

rf[x] = result;
pc = pc + 4;
''')

# FUNE - Floating Unordered with Epsilon
write_isa('fune', '''// MMIX FUNE - Floating Unordered with Epsilon
// FUNE $X,$Y,$Z: $X = (unordered($Y, $Z, rE)) ? 1 : 0
// Opcode: 0x13
// Note: Simplified - same as FUN for now

isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][7:0];
mem umem[14:0];

var x[7:0];
var y[7:0];
var z[7:0];
var y_val[63:0];
var z_val[63:0];
var result[63:0];
var y_is_nan[0:0];
var z_is_nan[0:0];
var unordered[0:0];

instr = umem[pc];
assume instr[31:24] == 0x13;

x = instr[23:16];
y = instr[15:8];
z = instr[7:0];

y_val = rf[y];
z_val = rf[z];

// Check for NaN (exponent all 1s, non-zero mantissa)
y_is_nan = (y_val[62:52] == 11'h7FF) & (y_val[51:0] != 52'b0);
z_is_nan = (z_val[62:52] == 11'h7FF) & (z_val[51:0] != 52'b0);
unordered = y_is_nan | z_is_nan;
result = unordered ? 64'd1 : 64'd0;

rf[x] = result;
pc = pc + 4;
''')

print("\nAll missing instructions generated!")
print(f"Total new files: {len([f for f in os.listdir(MMIX_DIR) if f.endswith('.isa')])}")
