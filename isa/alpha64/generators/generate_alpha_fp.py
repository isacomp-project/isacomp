#!/usr/bin/env python3
"""
Generate Alpha64 IEEE floating-point instruction specifications.

Alpha FP Encoding:
- Opcode 0x16 (22) for FP operate instructions
- Opcode 0x22 (34) for LDS (load single)
- Opcode 0x23 (35) for LDT (load double)
- Opcode 0x26 (38) for STS (store single)
- Opcode 0x27 (39) for STT (store double)

Function field (bits 15:5):
- fphi (bits 15:11): qualifier/rounding mode
- fplo (bits 10:5): operation code

IEEE Operations (fplo values):
- ADDS=0x00, SUBS=0x01, MULS=0x02, DIVS=0x03
- ADDT=0x20, SUBT=0x21, MULT=0x22, DIVT=0x23
- CMPTEQ=0x25, CMPTLT=0x26, CMPTLE=0x27, CMPTUN=0x24
- CVTQS=0x3C, CVTQT=0x3E, CVTTS=0x2C, CVTTQ=0x2F

Alpha Rounding Modes (fphi[1:0]):
- 00 = Chopped (toward zero) -> canonical RTZ (001)
- 01 = Minus infinity -> canonical RDN (010)
- 10 = Normal (round nearest) -> canonical RNE (000)
- 11 = Dynamic (use FPCR) -> read from FPCR[60:58]
"""

import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'f')

# Common header for all FP instructions
HEADER = '''isa_state pc[63:0];
var instr[31:0];
isa_state rf[63:0][4:0];       // Integer register file
isa_state frf[63:0][4:0];      // FP register file (64-bit)
isa_state fpcr[63:0];          // FP control register
isa_state imem[31:0][13:0];
mem dmem[13:0];
'''

# Rounding mode mapping - use simple form for parser compatibility
# For now, use RNE (round nearest even) as default - most common mode
# Alpha normally uses fphi[1:0] == 10 for IEEE default rounding
RM_MAPPING = '''// Use round-to-nearest-even (RNE) as the default IEEE 754 mode
// Alpha fphi[1:0]: 00=RTZ, 01=RDN, 10=RNE, 11=dynamic
// Most Alpha code uses RNE (fphi[1:0]==10), so we default to that
rm = 3'b000;   // RNE = canonical IEEE 754 round-to-nearest-even
'''

def generate_arithmetic_single(name, fplo, intrinsic, description):
    """Generate single-precision arithmetic instruction."""
    fplo_bin = f"6'b{fplo:06b}"
    return f'''// Alpha64 - {name.upper()} ({description}, IEEE single-precision)
// Opcode: 0x16, Function: fphi << 5 | 0x{fplo:02X}
// Format: {name.upper()} Fa, Fb, Fc

{HEADER}
var fa[4:0];
var fb[4:0];
var fc[4:0];
var fphi[4:0];
var fplo[5:0];
var f1[31:0];
var f2[31:0];
var rm[2:0];
var result[31:0];

instr = imem[pc];
assume instr[31:26] == 22;     // Opcode 0x16 = FP operate
fphi = instr[15:11];
fplo = instr[10:5];
assume fplo == {fplo_bin};      // {name.upper()} function code = 0x{fplo:02X}

fa = instr[25:21];
fb = instr[20:16];
fc = instr[4:0];

// Read single-precision operands (low 32 bits of FP register)
f1 = frf[fa][31:0];
f2 = frf[fb][31:0];

{RM_MAPPING}
// Perform FP operation
result = {intrinsic}(f1, f2, rm);

// Write result to FP register (NaN-boxed in upper bits)
frf[fc] when (fc != 31) = {{{{32{{1'b1}}}}, result}};
pc = pc + 4;
'''

def generate_arithmetic_double(name, fplo, intrinsic, description):
    """Generate double-precision arithmetic instruction."""
    fplo_bin = f"6'b{fplo:06b}"
    return f'''// Alpha64 - {name.upper()} ({description}, IEEE double-precision)
// Opcode: 0x16, Function: fphi << 5 | 0x{fplo:02X}
// Format: {name.upper()} Fa, Fb, Fc

{HEADER}
var fa[4:0];
var fb[4:0];
var fc[4:0];
var fphi[4:0];
var fplo[5:0];
var f1[63:0];
var f2[63:0];
var rm[2:0];
var result[63:0];

instr = imem[pc];
assume instr[31:26] == 22;     // Opcode 0x16 = FP operate
fphi = instr[15:11];
fplo = instr[10:5];
assume fplo == {fplo_bin};      // {name.upper()} function code = 0x{fplo:02X}

fa = instr[25:21];
fb = instr[20:16];
fc = instr[4:0];

// Read double-precision operands
f1 = frf[fa];
f2 = frf[fb];

{RM_MAPPING}
// Perform FP operation
result = {intrinsic}_d(f1, f2, rm);

// Write result to FP register
frf[fc] when (fc != 31) = result;
pc = pc + 4;
'''

def generate_unary_single(name, fplo, intrinsic, description):
    """Generate single-precision unary instruction (e.g., sqrt)."""
    fplo_bin = f"6'b{fplo:06b}"
    return f'''// Alpha64 - {name.upper()} ({description}, IEEE single-precision)
// Opcode: 0x16, Function: fphi << 5 | 0x{fplo:02X}
// Format: {name.upper()} Fb, Fc (Fa ignored)

{HEADER}
var fb[4:0];
var fc[4:0];
var fphi[4:0];
var fplo[5:0];
var f1[31:0];
var rm[2:0];
var result[31:0];

instr = imem[pc];
assume instr[31:26] == 22;     // Opcode 0x16 = FP operate
fphi = instr[15:11];
fplo = instr[10:5];
assume fplo == {fplo_bin};      // {name.upper()} function code = 0x{fplo:02X}

fb = instr[20:16];
fc = instr[4:0];

// Read single-precision operand
f1 = frf[fb][31:0];

{RM_MAPPING}
// Perform FP operation
result = {intrinsic}(f1, rm);

// Write result to FP register
frf[fc] when (fc != 31) = {{{{32{{1'b1}}}}, result}};
pc = pc + 4;
'''

def generate_unary_double(name, fplo, intrinsic, description):
    """Generate double-precision unary instruction."""
    fplo_bin = f"6'b{fplo:06b}"
    return f'''// Alpha64 - {name.upper()} ({description}, IEEE double-precision)
// Opcode: 0x16, Function: fphi << 5 | 0x{fplo:02X}
// Format: {name.upper()} Fb, Fc (Fa ignored)

{HEADER}
var fb[4:0];
var fc[4:0];
var fphi[4:0];
var fplo[5:0];
var f1[63:0];
var rm[2:0];
var result[63:0];

instr = imem[pc];
assume instr[31:26] == 22;     // Opcode 0x16 = FP operate
fphi = instr[15:11];
fplo = instr[10:5];
assume fplo == {fplo_bin};      // {name.upper()} function code = 0x{fplo:02X}

fb = instr[20:16];
fc = instr[4:0];

// Read double-precision operand
f1 = frf[fb];

{RM_MAPPING}
// Perform FP operation
result = {intrinsic}_d(f1, rm);

// Write result to FP register
frf[fc] when (fc != 31) = result;
pc = pc + 4;
'''

def generate_compare_double(name, fplo, intrinsic, description):
    """Generate double-precision comparison instruction."""
    fplo_bin = f"6'b{fplo:06b}"
    return f'''// Alpha64 - {name.upper()} ({description}, IEEE double-precision)
// Opcode: 0x16, Function: fphi << 5 | 0x{fplo:02X}
// Format: {name.upper()} Fa, Fb, Fc
// Result: Fc = 2.0 if true, 0.0 if false (canonical Alpha FP compare result)

{HEADER}
var fa[4:0];
var fb[4:0];
var fc[4:0];
var fphi[4:0];
var fplo[5:0];
var f1[63:0];
var f2[63:0];
var cmp_result[0:0];
var result[63:0];

instr = imem[pc];
assume instr[31:26] == 22;     // Opcode 0x16 = FP operate
fphi = instr[15:11];
fplo = instr[10:5];
assume fplo == {fplo_bin};      // {name.upper()} function code = 0x{fplo:02X}

fa = instr[25:21];
fb = instr[20:16];
fc = instr[4:0];

// Read double-precision operands
f1 = frf[fa];
f2 = frf[fb];

// Perform FP comparison
cmp_result = {intrinsic}_d(f1, f2);

// Alpha returns 2.0 (0x4000000000000000) for true, 0.0 for false
result = cmp_result ? 64'h4000000000000000 : 64'h0000000000000000;

// Write result to FP register
frf[fc] when (fc != 31) = result;
pc = pc + 4;
'''

def generate_load_single():
    """Generate LDS (load S_floating)."""
    return f'''// Alpha64 - LDS (Load S_floating, IEEE single-precision)
// Opcode: 0x22 (34)
// Format: LDS Fa, disp(Rb)

{HEADER}
var fa[4:0];
var rb[4:0];
var disp[15:0];
var addr[63:0];
var data[31:0];

instr = imem[pc];
assume instr[31:26] == 34;     // Opcode 0x22 = LDS

fa = instr[25:21];
rb = instr[20:16];
disp = instr[15:0];

// Compute effective address
addr = rf[rb] + {{{{48{{disp[15]}}}}, disp}};

// Load 32-bit value from memory
data = dmem[addr][31:0];

// Write to FP register (NaN-boxed in upper bits)
frf[fa] when (fa != 31) = {{{{32{{1'b1}}}}, data}};
pc = pc + 4;
'''

def generate_load_double():
    """Generate LDT (load T_floating)."""
    return f'''// Alpha64 - LDT (Load T_floating, IEEE double-precision)
// Opcode: 0x23 (35)
// Format: LDT Fa, disp(Rb)

{HEADER}
var fa[4:0];
var rb[4:0];
var disp[15:0];
var addr[63:0];
var data[63:0];

instr = imem[pc];
assume instr[31:26] == 35;     // Opcode 0x23 = LDT

fa = instr[25:21];
rb = instr[20:16];
disp = instr[15:0];

// Compute effective address
addr = rf[rb] + {{{{48{{disp[15]}}}}, disp}};

// Load 64-bit value from memory
data = dmem[addr];

// Write to FP register
frf[fa] when (fa != 31) = data;
pc = pc + 4;
'''

def generate_store_single():
    """Generate STS (store S_floating)."""
    return f'''// Alpha64 - STS (Store S_floating, IEEE single-precision)
// Opcode: 0x26 (38)
// Format: STS Fa, disp(Rb)

{HEADER}
var fa[4:0];
var rb[4:0];
var disp[15:0];
var addr[63:0];
var data[31:0];

instr = imem[pc];
assume instr[31:26] == 38;     // Opcode 0x26 = STS

fa = instr[25:21];
rb = instr[20:16];
disp = instr[15:0];

// Compute effective address
addr = rf[rb] + {{{{48{{disp[15]}}}}, disp}};

// Read low 32 bits from FP register
data = frf[fa][31:0];

// Store 32-bit value to memory
dmem[addr] = {{{{32{{1'b0}}}}, data}};
pc = pc + 4;
'''

def generate_store_double():
    """Generate STT (store T_floating)."""
    return f'''// Alpha64 - STT (Store T_floating, IEEE double-precision)
// Opcode: 0x27 (39)
// Format: STT Fa, disp(Rb)

{HEADER}
var fa[4:0];
var rb[4:0];
var disp[15:0];
var addr[63:0];
var data[63:0];

instr = imem[pc];
assume instr[31:26] == 39;     // Opcode 0x27 = STT

fa = instr[25:21];
rb = instr[20:16];
disp = instr[15:0];

// Compute effective address
addr = rf[rb] + {{{{48{{disp[15]}}}}, disp}};

// Read from FP register
data = frf[fa];

// Store 64-bit value to memory
dmem[addr] = data;
pc = pc + 4;
'''

def generate_cvt_ts():
    """Generate CVTTS (convert T_floating to S_floating)."""
    return f'''// Alpha64 - CVTTS (Convert T_floating to S_floating)
// Opcode: 0x16, Function: fphi << 5 | 0x2C
// Format: CVTTS Fb, Fc (Fa ignored)

{HEADER}
var fb[4:0];
var fc[4:0];
var fphi[4:0];
var fplo[5:0];
var f1[63:0];
var rm[2:0];
var result[31:0];

instr = imem[pc];
assume instr[31:26] == 22;     // Opcode 0x16 = FP operate
fphi = instr[15:11];
fplo = instr[10:5];
assume fplo == 6'b101100;      // CVTTS function code = 0x2C

fb = instr[20:16];
fc = instr[4:0];

// Read double-precision operand
f1 = frf[fb];

{RM_MAPPING}
// Convert double to single
result = fp_cvt_s_d(f1, rm);

// Write result to FP register (NaN-boxed)
frf[fc] when (fc != 31) = {{{{32{{1'b1}}}}, result}};
pc = pc + 4;
'''

def generate_cvt_qs():
    """Generate CVTQS (convert quadword to S_floating)."""
    return f'''// Alpha64 - CVTQS (Convert Quadword to S_floating)
// Opcode: 0x16, Function: fphi << 5 | 0x3C
// Format: CVTQS Fb, Fc (Fa ignored)

{HEADER}
var fb[4:0];
var fc[4:0];
var fphi[4:0];
var fplo[5:0];
var f1[63:0];
var rm[2:0];
var result[31:0];

instr = imem[pc];
assume instr[31:26] == 22;     // Opcode 0x16 = FP operate
fphi = instr[15:11];
fplo = instr[10:5];
assume fplo == 6'b111100;      // CVTQS function code = 0x3C

fb = instr[20:16];
fc = instr[4:0];

// Read quadword (integer in FP register)
f1 = frf[fb];

{RM_MAPPING}
// Convert signed int64 to single
result = fp_cvt_s_l(f1, rm);

// Write result to FP register (NaN-boxed)
frf[fc] when (fc != 31) = {{{{32{{1'b1}}}}, result}};
pc = pc + 4;
'''

def generate_cvt_qt():
    """Generate CVTQT (convert quadword to T_floating)."""
    return f'''// Alpha64 - CVTQT (Convert Quadword to T_floating)
// Opcode: 0x16, Function: fphi << 5 | 0x3E
// Format: CVTQT Fb, Fc (Fa ignored)

{HEADER}
var fb[4:0];
var fc[4:0];
var fphi[4:0];
var fplo[5:0];
var f1[63:0];
var rm[2:0];
var result[63:0];

instr = imem[pc];
assume instr[31:26] == 22;     // Opcode 0x16 = FP operate
fphi = instr[15:11];
fplo = instr[10:5];
assume fplo == 6'b111110;      // CVTQT function code = 0x3E

fb = instr[20:16];
fc = instr[4:0];

// Read quadword (integer in FP register)
f1 = frf[fb];

{RM_MAPPING}
// Convert signed int64 to double
result = fp_cvt_d_l(f1, rm);

// Write result to FP register
frf[fc] when (fc != 31) = result;
pc = pc + 4;
'''

def generate_cvt_tq():
    """Generate CVTTQ (convert T_floating to quadword)."""
    return f'''// Alpha64 - CVTTQ (Convert T_floating to Quadword)
// Opcode: 0x16, Function: fphi << 5 | 0x2F
// Format: CVTTQ Fb, Fc (Fa ignored)

{HEADER}
var fb[4:0];
var fc[4:0];
var fphi[4:0];
var fplo[5:0];
var f1[63:0];
var rm[2:0];
var result[63:0];

instr = imem[pc];
assume instr[31:26] == 22;     // Opcode 0x16 = FP operate
fphi = instr[15:11];
fplo = instr[10:5];
assume fplo == 6'b101111;      // CVTTQ function code = 0x2F

fb = instr[20:16];
fc = instr[4:0];

// Read double-precision operand
f1 = frf[fb];

{RM_MAPPING}
// Convert double to signed int64
result = fp_cvt_l_d(f1, rm);

// Write result to FP register
frf[fc] when (fc != 31) = result;
pc = pc + 4;
'''

def generate_cpys():
    """Generate CPYS (copy sign)."""
    return f'''// Alpha64 - CPYS (Copy Sign)
// Opcode: 0x17, Function: 0x020
// Format: CPYS Fa, Fb, Fc
// Fc = sign(Fa) | exponent+mantissa(Fb)

{HEADER}
var fa[4:0];
var fb[4:0];
var fc[4:0];
var f1[63:0];
var f2[63:0];
var result[63:0];

instr = imem[pc];
assume instr[31:26] == 23;     // Opcode 0x17 = FP operate (branch format)
assume instr[15:5] == 11'h020; // CPYS function code

fa = instr[25:21];
fb = instr[20:16];
fc = instr[4:0];

f1 = frf[fa];
f2 = frf[fb];

// Copy sign from Fa, rest from Fb
result = {{f1[63], f2[62:0]}};

frf[fc] when (fc != 31) = result;
pc = pc + 4;
'''

def generate_cpysn():
    """Generate CPYSN (copy sign negated)."""
    return f'''// Alpha64 - CPYSN (Copy Sign Negated)
// Opcode: 0x17, Function: 0x021
// Format: CPYSN Fa, Fb, Fc
// Fc = ~sign(Fa) | exponent+mantissa(Fb)

{HEADER}
var fa[4:0];
var fb[4:0];
var fc[4:0];
var f1[63:0];
var f2[63:0];
var result[63:0];

instr = imem[pc];
assume instr[31:26] == 23;     // Opcode 0x17 = FP operate (branch format)
assume instr[15:5] == 11'h021; // CPYSN function code

fa = instr[25:21];
fb = instr[20:16];
fc = instr[4:0];

f1 = frf[fa];
f2 = frf[fb];

// Copy negated sign from Fa, rest from Fb
result = {{~f1[63], f2[62:0]}};

frf[fc] when (fc != 31) = result;
pc = pc + 4;
'''

def generate_cpyse():
    """Generate CPYSE (copy sign and exponent)."""
    return f'''// Alpha64 - CPYSE (Copy Sign and Exponent)
// Opcode: 0x17, Function: 0x022
// Format: CPYSE Fa, Fb, Fc
// Fc = sign+exponent(Fa) | mantissa(Fb)

{HEADER}
var fa[4:0];
var fb[4:0];
var fc[4:0];
var f1[63:0];
var f2[63:0];
var result[63:0];

instr = imem[pc];
assume instr[31:26] == 23;     // Opcode 0x17 = FP operate (branch format)
assume instr[15:5] == 11'h022; // CPYSE function code

fa = instr[25:21];
fb = instr[20:16];
fc = instr[4:0];

f1 = frf[fa];
f2 = frf[fb];

// Copy sign+exponent from Fa, mantissa from Fb
result = {{f1[63:52], f2[51:0]}};

frf[fc] when (fc != 31) = result;
pc = pc + 4;
'''

def generate_mf_fpcr():
    """Generate MF_FPCR (move from FPCR)."""
    return f'''// Alpha64 - MF_FPCR (Move from FPCR)
// Opcode: 0x17, Function: 0x025
// Format: MF_FPCR Fa, Fb, Fc (Fa=Fb=Fc)

{HEADER}
var fa[4:0];
var fc[4:0];

instr = imem[pc];
assume instr[31:26] == 23;     // Opcode 0x17 = FP operate
assume instr[15:5] == 11'h025; // MF_FPCR function code

fa = instr[25:21];
fc = instr[4:0];

// Copy FPCR to FP register
frf[fc] when (fc != 31) = fpcr;
pc = pc + 4;
'''

def generate_mt_fpcr():
    """Generate MT_FPCR (move to FPCR)."""
    return f'''// Alpha64 - MT_FPCR (Move to FPCR)
// Opcode: 0x17, Function: 0x024
// Format: MT_FPCR Fa, Fb, Fc (Fa=Fb=Fc)

{HEADER}
var fa[4:0];

instr = imem[pc];
assume instr[31:26] == 23;     // Opcode 0x17 = FP operate
assume instr[15:5] == 11'h024; // MT_FPCR function code

fa = instr[25:21];

// Copy FP register to FPCR
fpcr = frf[fa];
pc = pc + 4;
'''

def generate_ftoit():
    """Generate FTOIT (FP to integer, move bits)."""
    return f'''// Alpha64 - FTOIT (Floating to Integer, move bits)
// Opcode: 0x1C, Function: 0x70
// Format: FTOIT Fa, Rc
// Moves 64 bits from FP register to integer register

{HEADER}
var fa[4:0];
var rc[4:0];

instr = imem[pc];
assume instr[31:26] == 28;     // Opcode 0x1C
assume instr[15:5] == 11'h070; // FTOIT function code

fa = instr[25:21];
rc = instr[4:0];

// Move bits from FP to integer register
rf[rc] when (rc != 31) = frf[fa];
pc = pc + 4;
'''

def generate_itoft():
    """Generate ITOFT (integer to FP, move bits)."""
    return f'''// Alpha64 - ITOFT (Integer to Floating, move bits)
// Opcode: 0x14, Function: 0x24
// Format: ITOFT Ra, Fc
// Moves 64 bits from integer register to FP register

{HEADER}
var ra[4:0];
var fc[4:0];

instr = imem[pc];
assume instr[31:26] == 20;     // Opcode 0x14
assume instr[15:5] == 11'h024; // ITOFT function code

ra = instr[25:21];
fc = instr[4:0];

// Move bits from integer to FP register
frf[fc] when (fc != 31) = rf[ra];
pc = pc + 4;
'''

def generate_sqrts():
    """Generate SQRTS (square root single)."""
    return f'''// Alpha64 - SQRTS (Square Root S_floating)
// Opcode: 0x14, Function: fphi << 5 | 0x0B
// Format: SQRTS Fb, Fc (Fa ignored)

{HEADER}
var fb[4:0];
var fc[4:0];
var fphi[4:0];
var fplo[5:0];
var f1[31:0];
var rm[2:0];
var result[31:0];

instr = imem[pc];
assume instr[31:26] == 20;     // Opcode 0x14 = FP operate
fphi = instr[15:11];
fplo = instr[10:5];
assume fplo == 6'b001011;      // SQRTS function code = 0x0B

fb = instr[20:16];
fc = instr[4:0];

f1 = frf[fb][31:0];

{RM_MAPPING}
result = fp_sqrt(f1, rm);

frf[fc] when (fc != 31) = {{{{32{{1'b1}}}}, result}};
pc = pc + 4;
'''

def generate_sqrtt():
    """Generate SQRTT (square root double)."""
    return f'''// Alpha64 - SQRTT (Square Root T_floating)
// Opcode: 0x14, Function: fphi << 5 | 0x2B
// Format: SQRTT Fb, Fc (Fa ignored)

{HEADER}
var fb[4:0];
var fc[4:0];
var fphi[4:0];
var fplo[5:0];
var f1[63:0];
var rm[2:0];
var result[63:0];

instr = imem[pc];
assume instr[31:26] == 20;     // Opcode 0x14 = FP operate
fphi = instr[15:11];
fplo = instr[10:5];
assume fplo == 6'b101011;      // SQRTT function code = 0x2B

fb = instr[20:16];
fc = instr[4:0];

f1 = frf[fb];

{RM_MAPPING}
result = fp_sqrt_d(f1, rm);

frf[fc] when (fc != 31) = result;
pc = pc + 4;
'''

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    instructions = []

    # Single-precision arithmetic
    instructions.append(('adds', generate_arithmetic_single('adds', 0x00, 'fp_add', 'Add S_floating')))
    instructions.append(('subs', generate_arithmetic_single('subs', 0x01, 'fp_sub', 'Subtract S_floating')))
    instructions.append(('muls', generate_arithmetic_single('muls', 0x02, 'fp_mul', 'Multiply S_floating')))
    instructions.append(('divs', generate_arithmetic_single('divs', 0x03, 'fp_div', 'Divide S_floating')))

    # Double-precision arithmetic
    instructions.append(('addt', generate_arithmetic_double('addt', 0x20, 'fp_add', 'Add T_floating')))
    instructions.append(('subt', generate_arithmetic_double('subt', 0x21, 'fp_sub', 'Subtract T_floating')))
    instructions.append(('mult', generate_arithmetic_double('mult', 0x22, 'fp_mul', 'Multiply T_floating')))
    instructions.append(('divt', generate_arithmetic_double('divt', 0x23, 'fp_div', 'Divide T_floating')))

    # Comparisons (double-precision, result in FP format)
    instructions.append(('cmpteq', generate_compare_double('cmpteq', 0x25, 'fp_eq', 'Compare T_floating Equal')))
    instructions.append(('cmptlt', generate_compare_double('cmptlt', 0x26, 'fp_lt', 'Compare T_floating Less Than')))
    instructions.append(('cmptle', generate_compare_double('cmptle', 0x27, 'fp_le', 'Compare T_floating Less Equal')))

    # Load/Store
    instructions.append(('lds', generate_load_single()))
    instructions.append(('ldt', generate_load_double()))
    instructions.append(('sts', generate_store_single()))
    instructions.append(('stt', generate_store_double()))

    # Conversions
    instructions.append(('cvtts', generate_cvt_ts()))
    instructions.append(('cvtqs', generate_cvt_qs()))
    instructions.append(('cvtqt', generate_cvt_qt()))
    instructions.append(('cvttq', generate_cvt_tq()))

    # Sign manipulation
    instructions.append(('cpys', generate_cpys()))
    instructions.append(('cpysn', generate_cpysn()))
    instructions.append(('cpyse', generate_cpyse()))

    # FPCR access
    instructions.append(('mf_fpcr', generate_mf_fpcr()))
    instructions.append(('mt_fpcr', generate_mt_fpcr()))

    # Integer/FP moves
    instructions.append(('ftoit', generate_ftoit()))
    instructions.append(('itoft', generate_itoft()))

    # Square root
    instructions.append(('sqrts', generate_sqrts()))
    instructions.append(('sqrtt', generate_sqrtt()))

    # Write all files
    for name, content in instructions:
        filepath = os.path.join(OUTPUT_DIR, f'{name}.isa')
        with open(filepath, 'w') as f:
            f.write(content)
        print(f'Generated {filepath}')

    print(f'\nTotal: {len(instructions)} Alpha FP instructions generated')

if __name__ == '__main__':
    main()
