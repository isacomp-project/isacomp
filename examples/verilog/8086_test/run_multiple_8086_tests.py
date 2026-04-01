#!/usr/bin/env python3
"""Run multiple 8086 JSON tests to validate Verilog generator."""

import subprocess
import sys
from pathlib import Path

# Get project root and script directory
script_dir = Path(__file__).parent
project_root = script_dir.parent.parent

# List of (ISA file, test file) pairs to test
test_cases = [
    # Arithmetic instructions (ADD)
    ("isa/8086/add_r8h_r8l.isa", "isa/8086/tests/v1/00.json.gz", "ADD r8h, r8l"),
    ("isa/8086/add_r16_r16_parameterized.isa", "isa/8086/tests/v1/01.json.gz", "ADD r16, r16"),
    ("isa/8086/add_al_imm8.isa", "isa/8086/tests/v1/04.json.gz", "ADD AL, imm"),
    ("isa/8086/add_r8l_r8l.isa", "isa/8086/tests/v1/00.json.gz", "ADD r8l, r8l"),
    ("isa/8086/add_r8h_r8h.isa", "isa/8086/tests/v1/00.json.gz", "ADD r8h, r8h"),
    ("isa/8086/add_r8l_r8h.isa", "isa/8086/tests/v1/00.json.gz", "ADD r8l, r8h"),
    ("isa/8086/add_ax_imm16.isa", "isa/8086/tests/v1/05.json.gz", "ADD AX, imm"),

    # Logical instructions (OR)
    ("isa/8086/or_r16_r16.isa", "isa/8086/tests/v1/09.json.gz", "OR r16, r16"),
    ("isa/8086/or_al_imm8.isa", "isa/8086/tests/v1/0C.json.gz", "OR AL, imm"),
    ("isa/8086/or_r8l_r8l.isa", "isa/8086/tests/v1/08.json.gz", "OR r8l, r8l"),
    ("isa/8086/or_r8h_r8h.isa", "isa/8086/tests/v1/08.json.gz", "OR r8h, r8h"),
    ("isa/8086/or_r8h_r8l.isa", "isa/8086/tests/v1/08.json.gz", "OR r8h, r8l"),

    # Logical instructions (AND)
    ("isa/8086/and_r8h_r8l.isa", "isa/8086/tests/v1/20.json.gz", "AND r8h, r8l"),
    ("isa/8086/and_r16_r16.isa", "isa/8086/tests/v1/21.json.gz", "AND r16, r16"),
    ("isa/8086/and_al_imm8.isa", "isa/8086/tests/v1/24.json.gz", "AND AL, imm"),
    ("isa/8086/and_r8l_r8l.isa", "isa/8086/tests/v1/20.json.gz", "AND r8l, r8l"),
    ("isa/8086/and_r8h_r8h.isa", "isa/8086/tests/v1/20.json.gz", "AND r8h, r8h"),

    # Logical instructions (XOR)
    ("isa/8086/xor_r8h_r8h.isa", "isa/8086/tests/v1/30.json.gz", "XOR r8h, r8h"),
    ("isa/8086/xor_r16_r16.isa", "isa/8086/tests/v1/31.json.gz", "XOR r16, r16"),
    ("isa/8086/xor_r8l_r8l.isa", "isa/8086/tests/v1/30.json.gz", "XOR r8l, r8l"),
    ("isa/8086/xor_r8h_r8l.isa", "isa/8086/tests/v1/30.json.gz", "XOR r8h, r8l"),
    ("isa/8086/xor_r8l_r8h.isa", "isa/8086/tests/v1/30.json.gz", "XOR r8l, r8h"),

    # Add with carry (ADC)
    ("isa/8086/adc_r8h_r8h.isa", "isa/8086/tests/v1/10.json.gz", "ADC r8h, r8h"),
    ("isa/8086/adc_al_imm8.isa", "isa/8086/tests/v1/14.json.gz", "ADC AL, imm"),
    ("isa/8086/adc_ax_imm16.isa", "isa/8086/tests/v1/15.json.gz", "ADC AX, imm"),
    ("isa/8086/adc_r8l_r8l.isa", "isa/8086/tests/v1/10.json.gz", "ADC r8l, r8l"),
    ("isa/8086/adc_r8h_r8l.isa", "isa/8086/tests/v1/10.json.gz", "ADC r8h, r8l"),

    # Subtract with borrow (SBB)
    ("isa/8086/sbb_r8l_r8l.isa", "isa/8086/tests/v1/18.json.gz", "SBB r8l, r8l"),
    ("isa/8086/sbb_r8h_r8h.isa", "isa/8086/tests/v1/18.json.gz", "SBB r8h, r8h"),
    ("isa/8086/sbb_r8h_r8l.isa", "isa/8086/tests/v1/18.json.gz", "SBB r8h, r8l"),
    ("isa/8086/sbb_r8l_r8h.isa", "isa/8086/tests/v1/18.json.gz", "SBB r8l, r8h"),

    # Subtraction (SUB)
    ("isa/8086/sub_r8l_r8l.isa", "isa/8086/tests/v1/28.json.gz", "SUB r8l, r8l"),
    ("isa/8086/sub_r16_r16.isa", "isa/8086/tests/v1/29.json.gz", "SUB r16, r16"),
    ("isa/8086/sub_al_imm8.isa", "isa/8086/tests/v1/2C.json.gz", "SUB AL, imm"),
    ("isa/8086/sub_r8h_r8l.isa", "isa/8086/tests/v1/28.json.gz", "SUB r8h, r8l"),
    ("isa/8086/sub_r8l_r8h.isa", "isa/8086/tests/v1/28.json.gz", "SUB r8l, r8h"),

    # Comparison (CMP)
    ("isa/8086/cmp_r8l_r8l.isa", "isa/8086/tests/v1/38.json.gz", "CMP r8l, r8l"),
    ("isa/8086/cmp_r16_r16.isa", "isa/8086/tests/v1/39.json.gz", "CMP r16, r16"),
    ("isa/8086/cmp_al_imm8.isa", "isa/8086/tests/v1/3C.json.gz", "CMP AL, imm"),
    ("isa/8086/cmp_r8h_r8h.isa", "isa/8086/tests/v1/38.json.gz", "CMP r8h, r8h"),
    ("isa/8086/cmp_r8h_r8l.isa", "isa/8086/tests/v1/38.json.gz", "CMP r8h, r8l"),
    ("isa/8086/cmp_r8l_r8h.isa", "isa/8086/tests/v1/38.json.gz", "CMP r8l, r8h"),
    ("isa/8086/cmp_ax_imm16.isa", "isa/8086/tests/v1/3D.json.gz", "CMP AX, imm"),

    # Increment (INC)
    ("isa/8086/inc_ax.isa", "isa/8086/tests/v1/40.json.gz", "INC AX"),
    ("isa/8086/inc_r16.isa", "isa/8086/tests/v1/40.json.gz", "INC r16"),
    ("isa/8086/inc_al.isa", "isa/8086/tests/v1/FE.0.json.gz", "INC AL"),

    # Decrement (DEC)
    ("isa/8086/dec_ax.isa", "isa/8086/tests/v1/48.json.gz", "DEC AX"),
    ("isa/8086/dec_r16.isa", "isa/8086/tests/v1/48.json.gz", "DEC r16"),
    ("isa/8086/dec_al.isa", "isa/8086/tests/v1/FE.1.json.gz", "DEC AL"),

    # Test
    ("isa/8086/test_al_imm8.isa", "isa/8086/tests/v1/A8.json.gz", "TEST AL, imm"),
    ("isa/8086/test_ax_imm16.isa", "isa/8086/tests/v1/A9.json.gz", "TEST AX, imm"),
    ("isa/8086/test_r8l_r8l.isa", "isa/8086/tests/v1/84.json.gz", "TEST r8l, r8l"),

    # Move (MOV)
    ("isa/8086/mov_r8l_r8l.isa", "isa/8086/tests/v1/88.json.gz", "MOV r8l, r8l"),
    ("isa/8086/mov_r16_r16.isa", "isa/8086/tests/v1/89.json.gz", "MOV r16, r16"),
    ("isa/8086/mov_al_imm.isa", "isa/8086/tests/v1/B0.json.gz", "MOV AL, imm"),
    ("isa/8086/mov_r8h_r8h.isa", "isa/8086/tests/v1/88.json.gz", "MOV r8h, r8h"),
    ("isa/8086/mov_r8h_r8l.isa", "isa/8086/tests/v1/88.json.gz", "MOV r8h, r8l"),

    # BCD instructions
    ("isa/8086/aaa.isa", "isa/8086/tests/v1/37.json.gz", "AAA"),
    ("isa/8086/aas.isa", "isa/8086/tests/v1/3F.json.gz", "AAS"),
    ("isa/8086/daa.isa", "isa/8086/tests/v1/27.json.gz", "DAA"),
    ("isa/8086/das.isa", "isa/8086/tests/v1/2F.json.gz", "DAS"),
    ("isa/8086/aam.isa", "isa/8086/tests/v1/D4.json.gz", "AAM"),
    ("isa/8086/aad.isa", "isa/8086/tests/v1/D5.json.gz", "AAD"),

    # Special instructions
    ("isa/8086/nop.isa", "isa/8086/tests/v1/90.json.gz", "NOP"),
    ("isa/8086/cbw.isa", "isa/8086/tests/v1/98.json.gz", "CBW"),
    ("isa/8086/cwd.isa", "isa/8086/tests/v1/99.json.gz", "CWD"),
    ("isa/8086/clc.isa", "isa/8086/tests/v1/F8.json.gz", "CLC"),
    ("isa/8086/stc.isa", "isa/8086/tests/v1/F9.json.gz", "STC"),
    ("isa/8086/cmc.isa", "isa/8086/tests/v1/F5.json.gz", "CMC"),
    ("isa/8086/cld.isa", "isa/8086/tests/v1/FC.json.gz", "CLD"),
    ("isa/8086/std.isa", "isa/8086/tests/v1/FD.json.gz", "STD"),
    ("isa/8086/cli.isa", "isa/8086/tests/v1/FA.json.gz", "CLI"),
    ("isa/8086/sti.isa", "isa/8086/tests/v1/FB.json.gz", "STI"),
    # ("isa/8086/hlt.isa", "isa/8086/tests/v1/F4.json.gz", "HLT"),  # No test file available
    ("isa/8086/lahf.isa", "isa/8086/tests/v1/9F.json.gz", "LAHF"),
    ("isa/8086/sahf.isa", "isa/8086/tests/v1/9E.json.gz", "SAHF"),

    # Conditional jumps
    ("isa/8086/jz.isa", "isa/8086/tests/v1/74.json.gz", "JZ"),
    ("isa/8086/jnz.isa", "isa/8086/tests/v1/75.json.gz", "JNZ"),
    ("isa/8086/jc.isa", "isa/8086/tests/v1/72.json.gz", "JC"),
    ("isa/8086/jnc.isa", "isa/8086/tests/v1/73.json.gz", "JNC"),
    ("isa/8086/jo.isa", "isa/8086/tests/v1/70.json.gz", "JO"),
    ("isa/8086/jno.isa", "isa/8086/tests/v1/71.json.gz", "JNO"),
    ("isa/8086/js.isa", "isa/8086/tests/v1/78.json.gz", "JS"),
    ("isa/8086/jp.isa", "isa/8086/tests/v1/7A.json.gz", "JP"),
    ("isa/8086/jnp.isa", "isa/8086/tests/v1/7B.json.gz", "JNP"),
    ("isa/8086/jl.isa", "isa/8086/tests/v1/7C.json.gz", "JL"),
    ("isa/8086/jge.isa", "isa/8086/tests/v1/7D.json.gz", "JGE"),
    ("isa/8086/jle.isa", "isa/8086/tests/v1/7E.json.gz", "JLE"),
    ("isa/8086/jg.isa", "isa/8086/tests/v1/7F.json.gz", "JG"),
    ("isa/8086/jbe.isa", "isa/8086/tests/v1/76.json.gz", "JBE"),
    ("isa/8086/ja.isa", "isa/8086/tests/v1/77.json.gz", "JA"),
    ("isa/8086/jcxz.isa", "isa/8086/tests/v1/E3.json.gz", "JCXZ"),
    ("isa/8086/jmp_short.isa", "isa/8086/tests/v1/EB.json.gz", "JMP short"),

    # Stack operations
    ("isa/8086/push_r16.isa", "isa/8086/tests/v1/50.json.gz", "PUSH AX"),
    ("isa/8086/pop_r16.isa", "isa/8086/tests/v1/58.json.gz", "POP AX"),
    ("isa/8086/pushf.isa", "isa/8086/tests/v1/9C.json.gz", "PUSHF"),
    ("isa/8086/popf.isa", "isa/8086/tests/v1/9D.json.gz", "POPF"),

    # String operations
    ("isa/8086/movsb.isa", "isa/8086/tests/v1/A4.json.gz", "MOVSB"),
    ("isa/8086/movsw.isa", "isa/8086/tests/v1/A5.json.gz", "MOVSW"),
    ("isa/8086/cmpsb.isa", "isa/8086/tests/v1/A6.json.gz", "CMPSB"),
    ("isa/8086/cmpsw.isa", "isa/8086/tests/v1/A7.json.gz", "CMPSW"),
    ("isa/8086/stosb.isa", "isa/8086/tests/v1/AA.json.gz", "STOSB"),
    ("isa/8086/stosw.isa", "isa/8086/tests/v1/AB.json.gz", "STOSW"),
    ("isa/8086/lodsb.isa", "isa/8086/tests/v1/AC.json.gz", "LODSB"),
    ("isa/8086/lodsw.isa", "isa/8086/tests/v1/AD.json.gz", "LODSW"),
    ("isa/8086/scasb.isa", "isa/8086/tests/v1/AE.json.gz", "SCASB"),
    ("isa/8086/scasw.isa", "isa/8086/tests/v1/AF.json.gz", "SCASW"),

    # Loop instructions
    ("isa/8086/loopne.isa", "isa/8086/tests/v1/E0.json.gz", "LOOPNE"),
    ("isa/8086/loope.isa", "isa/8086/tests/v1/E1.json.gz", "LOOPE"),
    ("isa/8086/loop.isa", "isa/8086/tests/v1/E2.json.gz", "LOOP"),

    # Load effective address
    ("isa/8086/lea_ax_bx_si.isa", "isa/8086/tests/v1/8D.json.gz", "LEA AX, [BX+SI]"),

    # Return instructions
    ("isa/8086/ret_near.isa", "isa/8086/tests/v1/C3.json.gz", "RET near"),
    ("isa/8086/ret_far.isa", "isa/8086/tests/v1/CB.json.gz", "RET far"),

    # Shifts and rotates (by 1)
    ("isa/8086/rol_al_1.isa", "isa/8086/tests/v1/D0.0.json.gz", "ROL AL, 1"),
    ("isa/8086/ror_al_1.isa", "isa/8086/tests/v1/D0.1.json.gz", "ROR AL, 1"),
    ("isa/8086/rcl_al_1.isa", "isa/8086/tests/v1/D0.2.json.gz", "RCL AL, 1"),
    ("isa/8086/rcr_al_1.isa", "isa/8086/tests/v1/D0.3.json.gz", "RCR AL, 1"),
    ("isa/8086/shl_al_1.isa", "isa/8086/tests/v1/D0.4.json.gz", "SHL AL, 1"),
    ("isa/8086/shr_al_1.isa", "isa/8086/tests/v1/D0.5.json.gz", "SHR AL, 1"),
    ("isa/8086/sar_al_1.isa", "isa/8086/tests/v1/D0.7.json.gz", "SAR AL, 1"),

    # Shifts and rotates (by CL)
    ("isa/8086/rol_al_cl.isa", "isa/8086/tests/v1/D2.0.json.gz", "ROL AL, CL"),
    ("isa/8086/ror_al_cl.isa", "isa/8086/tests/v1/D2.1.json.gz", "ROR AL, CL"),
    ("isa/8086/rcl_al_cl.isa", "isa/8086/tests/v1/D2.2.json.gz", "RCL AL, CL"),
    ("isa/8086/rcr_al_cl.isa", "isa/8086/tests/v1/D2.3.json.gz", "RCR AL, CL"),
    ("isa/8086/shl_al_cl.isa", "isa/8086/tests/v1/D2.4.json.gz", "SHL AL, CL"),
    ("isa/8086/shr_al_cl.isa", "isa/8086/tests/v1/D2.5.json.gz", "SHR AL, CL"),
    ("isa/8086/sar_al_cl.isa", "isa/8086/tests/v1/D2.7.json.gz", "SAR AL, CL"),

    # Multiply and divide
    ("isa/8086/mul_al_bl.isa", "isa/8086/tests/v1/F6.4.json.gz", "MUL AL, BL"),
    ("isa/8086/imul_al_bl.isa", "isa/8086/tests/v1/F6.5.json.gz", "IMUL AL, BL"),
    ("isa/8086/div_al_bl.isa", "isa/8086/tests/v1/F6.6.json.gz", "DIV AL, BL"),
    ("isa/8086/idiv_al_bl.isa", "isa/8086/tests/v1/F6.7.json.gz", "IDIV AL, BL"),

    # Unary operations
    ("isa/8086/not_al.isa", "isa/8086/tests/v1/F6.2.json.gz", "NOT AL"),
    ("isa/8086/neg_al.isa", "isa/8086/tests/v1/F6.3.json.gz", "NEG AL"),

    # I/O operations
    ("isa/8086/in_al_imm.isa", "isa/8086/tests/v1/E4.json.gz", "IN AL, imm"),
    ("isa/8086/in_ax_imm.isa", "isa/8086/tests/v1/E5.json.gz", "IN AX, imm"),
    ("isa/8086/out_imm_al.isa", "isa/8086/tests/v1/E6.json.gz", "OUT imm, AL"),
    ("isa/8086/out_imm_ax.isa", "isa/8086/tests/v1/E7.json.gz", "OUT imm, AX"),
    ("isa/8086/in_al_dx.isa", "isa/8086/tests/v1/EC.json.gz", "IN AL, DX"),
    ("isa/8086/in_ax_dx.isa", "isa/8086/tests/v1/ED.json.gz", "IN AX, DX"),
    ("isa/8086/out_dx_al.isa", "isa/8086/tests/v1/EE.json.gz", "OUT DX, AL"),
    ("isa/8086/out_dx_ax.isa", "isa/8086/tests/v1/EF.json.gz", "OUT DX, AX"),

    # Translate
    ("isa/8086/xlat.isa", "isa/8086/tests/v1/D7.json.gz", "XLAT"),

    # Interrupt return
    ("isa/8086/iret.isa", "isa/8086/tests/v1/CF.json.gz", "IRET"),

    # Additional ALU variants
    ("isa/8086/adc_r16_r16.isa", "isa/8086/tests/v1/11.json.gz", "ADC r16, r16"),
    ("isa/8086/adc_r8l_r8h.isa", "isa/8086/tests/v1/10.json.gz", "ADC r8l, r8h"),
    ("isa/8086/sbb_r16_r16.isa", "isa/8086/tests/v1/19.json.gz", "SBB r16, r16"),
    ("isa/8086/sbb_al_imm8.isa", "isa/8086/tests/v1/1C.json.gz", "SBB AL, imm"),
    ("isa/8086/sbb_ax_imm16.isa", "isa/8086/tests/v1/1D.json.gz", "SBB AX, imm"),
    ("isa/8086/and_ax_imm16.isa", "isa/8086/tests/v1/25.json.gz", "AND AX, imm"),
    ("isa/8086/and_r8l_r8h.isa", "isa/8086/tests/v1/20.json.gz", "AND r8l, r8h"),
    ("isa/8086/sub_ax_imm16.isa", "isa/8086/tests/v1/2D.json.gz", "SUB AX, imm"),
    ("isa/8086/sub_r8h_r8h.isa", "isa/8086/tests/v1/28.json.gz", "SUB r8h, r8h"),
    ("isa/8086/or_ax_imm16.isa", "isa/8086/tests/v1/0D.json.gz", "OR AX, imm"),
    ("isa/8086/or_r8l_r8h.isa", "isa/8086/tests/v1/08.json.gz", "OR r8l, r8h"),
    ("isa/8086/xor_al_imm8.isa", "isa/8086/tests/v1/34.json.gz", "XOR AL, imm"),
    ("isa/8086/xor_ax_imm16.isa", "isa/8086/tests/v1/35.json.gz", "XOR AX, imm"),

    # Additional MOV variants
    ("isa/8086/mov_r16_imm.isa", "isa/8086/tests/v1/B8.json.gz", "MOV AX, imm16"),
    ("isa/8086/mov_r8l_imm.isa", "isa/8086/tests/v1/B0.json.gz", "MOV AL, imm8"),

    # MOV immediate to low byte registers (B1-B3)
    ("isa/8086/mov_r8l_imm.isa", "isa/8086/tests/v1/B1.json.gz", "MOV CL, imm8"),
    ("isa/8086/mov_r8l_imm.isa", "isa/8086/tests/v1/B2.json.gz", "MOV DL, imm8"),
    ("isa/8086/mov_r8l_imm.isa", "isa/8086/tests/v1/B3.json.gz", "MOV BL, imm8"),

    # MOV immediate to high byte registers (B4-B7)
    ("isa/8086/mov_r8h_imm.isa", "isa/8086/tests/v1/B4.json.gz", "MOV AH, imm8"),
    ("isa/8086/mov_r8h_imm.isa", "isa/8086/tests/v1/B5.json.gz", "MOV CH, imm8"),
    ("isa/8086/mov_r8h_imm.isa", "isa/8086/tests/v1/B6.json.gz", "MOV DH, imm8"),
    ("isa/8086/mov_r8h_imm.isa", "isa/8086/tests/v1/B7.json.gz", "MOV BH, imm8"),

    # MOV immediate to 16-bit registers (B9-BF)
    ("isa/8086/mov_r16_imm.isa", "isa/8086/tests/v1/B9.json.gz", "MOV CX, imm16"),
    ("isa/8086/mov_r16_imm.isa", "isa/8086/tests/v1/BA.json.gz", "MOV DX, imm16"),
    ("isa/8086/mov_r16_imm.isa", "isa/8086/tests/v1/BB.json.gz", "MOV BX, imm16"),
    ("isa/8086/mov_r16_imm.isa", "isa/8086/tests/v1/BC.json.gz", "MOV SP, imm16"),
    ("isa/8086/mov_r16_imm.isa", "isa/8086/tests/v1/BD.json.gz", "MOV BP, imm16"),
    ("isa/8086/mov_r16_imm.isa", "isa/8086/tests/v1/BE.json.gz", "MOV SI, imm16"),
    ("isa/8086/mov_r16_imm.isa", "isa/8086/tests/v1/BF.json.gz", "MOV DI, imm16"),
    ("isa/8086/mov_r8l_r8h.isa", "isa/8086/tests/v1/88.json.gz", "MOV r8l, r8h"),

    # Additional TEST variants
    ("isa/8086/test_al_bl.isa", "isa/8086/tests/v1/84.json.gz", "TEST AL, BL"),
    ("isa/8086/test_ax_bx.isa", "isa/8086/tests/v1/85.json.gz", "TEST AX, BX"),

    # XCHG (Exchange)
    ("isa/8086/xchg_ax_r16.isa", "isa/8086/tests/v1/90.json.gz", "XCHG AX, r16"),
    ("isa/8086/xchg_r16_r16.isa", "isa/8086/tests/v1/87.json.gz", "XCHG r16, r16"),
    ("isa/8086/xchg_r8h_r8h.isa", "isa/8086/tests/v1/86.json.gz", "XCHG r8h, r8h"),
    ("isa/8086/xchg_r8l_r8h.isa", "isa/8086/tests/v1/86.json.gz", "XCHG r8l, r8h"),
    ("isa/8086/xchg_r8l_r8l.isa", "isa/8086/tests/v1/86.json.gz", "XCHG r8l, r8l"),

    # Call and interrupts
    ("isa/8086/call_near.isa", "isa/8086/tests/v1/E8.json.gz", "CALL near"),
    ("isa/8086/call_far.isa", "isa/8086/tests/v1/9A.json.gz", "CALL far"),
    ("isa/8086/int.isa", "isa/8086/tests/v1/CD.json.gz", "INT"),
    ("isa/8086/into.isa", "isa/8086/tests/v1/CE.json.gz", "INTO"),

    # Load far pointer
    ("isa/8086/lds_bx_mem.isa", "isa/8086/tests/v1/C4.json.gz", "LDS BX, mem"),
    ("isa/8086/les_bx_mem.isa", "isa/8086/tests/v1/C5.json.gz", "LES BX, mem"),

    # Memory indirect addressing - ADD
    ("isa/8086/add_mem_indirect_r16.isa", "isa/8086/tests/v1/01.json.gz", "ADD [mem], r16"),
    ("isa/8086/add_r16_mem_indirect.isa", "isa/8086/tests/v1/03.json.gz", "ADD r16, [mem]"),
    ("isa/8086/add_mem_indirect_r8l.isa", "isa/8086/tests/v1/00.json.gz", "ADD [mem], r8l"),
    ("isa/8086/add_r8l_mem_indirect.isa", "isa/8086/tests/v1/02.json.gz", "ADD r8l, [mem]"),
    ("isa/8086/add_mem_indirect_r8h.isa", "isa/8086/tests/v1/00.json.gz", "ADD [mem], r8h"),
    ("isa/8086/add_r8h_mem_indirect.isa", "isa/8086/tests/v1/02.json.gz", "ADD r8h, [mem]"),

    # Memory indirect addressing - OR
    ("isa/8086/or_mem_indirect_r16.isa", "isa/8086/tests/v1/09.json.gz", "OR [mem], r16"),
    ("isa/8086/or_r16_mem_indirect.isa", "isa/8086/tests/v1/0B.json.gz", "OR r16, [mem]"),
    ("isa/8086/or_mem_indirect_r8l.isa", "isa/8086/tests/v1/08.json.gz", "OR [mem], r8l"),
    ("isa/8086/or_r8l_mem_indirect.isa", "isa/8086/tests/v1/0A.json.gz", "OR r8l, [mem]"),
    ("isa/8086/or_mem_indirect_r8h.isa", "isa/8086/tests/v1/08.json.gz", "OR [mem], r8h"),
    ("isa/8086/or_r8h_mem_indirect.isa", "isa/8086/tests/v1/0A.json.gz", "OR r8h, [mem]"),

    # Memory indirect addressing - ADC
    ("isa/8086/adc_mem_indirect_r16.isa", "isa/8086/tests/v1/11.json.gz", "ADC [mem], r16"),
    ("isa/8086/adc_r16_mem_indirect.isa", "isa/8086/tests/v1/13.json.gz", "ADC r16, [mem]"),
    ("isa/8086/adc_mem_indirect_r8l.isa", "isa/8086/tests/v1/10.json.gz", "ADC [mem], r8l"),
    ("isa/8086/adc_r8l_mem_indirect.isa", "isa/8086/tests/v1/12.json.gz", "ADC r8l, [mem]"),
    ("isa/8086/adc_mem_indirect_r8h.isa", "isa/8086/tests/v1/10.json.gz", "ADC [mem], r8h"),
    ("isa/8086/adc_r8h_mem_indirect.isa", "isa/8086/tests/v1/12.json.gz", "ADC r8h, [mem]"),

    # Memory indirect addressing - SBB
    ("isa/8086/sbb_mem_indirect_r16.isa", "isa/8086/tests/v1/19.json.gz", "SBB [mem], r16"),
    ("isa/8086/sbb_r16_mem_indirect.isa", "isa/8086/tests/v1/1B.json.gz", "SBB r16, [mem]"),
    ("isa/8086/sbb_mem_indirect_r8l.isa", "isa/8086/tests/v1/18.json.gz", "SBB [mem], r8l"),
    ("isa/8086/sbb_r8l_mem_indirect.isa", "isa/8086/tests/v1/1A.json.gz", "SBB r8l, [mem]"),
    ("isa/8086/sbb_mem_indirect_r8h.isa", "isa/8086/tests/v1/18.json.gz", "SBB [mem], r8h"),
    ("isa/8086/sbb_r8h_mem_indirect.isa", "isa/8086/tests/v1/1A.json.gz", "SBB r8h, [mem]"),

    # Memory indirect addressing - AND
    ("isa/8086/and_mem_indirect_r16.isa", "isa/8086/tests/v1/21.json.gz", "AND [mem], r16"),
    ("isa/8086/and_r16_mem_indirect.isa", "isa/8086/tests/v1/23.json.gz", "AND r16, [mem]"),
    ("isa/8086/and_mem_indirect_r8l.isa", "isa/8086/tests/v1/20.json.gz", "AND [mem], r8l"),
    ("isa/8086/and_r8l_mem_indirect.isa", "isa/8086/tests/v1/22.json.gz", "AND r8l, [mem]"),
    ("isa/8086/and_mem_indirect_r8h.isa", "isa/8086/tests/v1/20.json.gz", "AND [mem], r8h"),
    ("isa/8086/and_r8h_mem_indirect.isa", "isa/8086/tests/v1/22.json.gz", "AND r8h, [mem]"),

    # Memory indirect addressing - SUB
    ("isa/8086/sub_mem_indirect_r16.isa", "isa/8086/tests/v1/29.json.gz", "SUB [mem], r16"),
    ("isa/8086/sub_r16_mem_indirect.isa", "isa/8086/tests/v1/2B.json.gz", "SUB r16, [mem]"),
    ("isa/8086/sub_mem_indirect_r8l.isa", "isa/8086/tests/v1/28.json.gz", "SUB [mem], r8l"),
    ("isa/8086/sub_r8l_mem_indirect.isa", "isa/8086/tests/v1/2A.json.gz", "SUB r8l, [mem]"),
    ("isa/8086/sub_mem_indirect_r8h.isa", "isa/8086/tests/v1/28.json.gz", "SUB [mem], r8h"),
    ("isa/8086/sub_r8h_mem_indirect.isa", "isa/8086/tests/v1/2A.json.gz", "SUB r8h, [mem]"),

    # Memory indirect addressing - XOR
    ("isa/8086/xor_mem_indirect_r16.isa", "isa/8086/tests/v1/31.json.gz", "XOR [mem], r16"),
    ("isa/8086/xor_r16_mem_indirect.isa", "isa/8086/tests/v1/33.json.gz", "XOR r16, [mem]"),
    ("isa/8086/xor_mem_indirect_r8l.isa", "isa/8086/tests/v1/30.json.gz", "XOR [mem], r8l"),
    ("isa/8086/xor_r8l_mem_indirect.isa", "isa/8086/tests/v1/32.json.gz", "XOR r8l, [mem]"),
    ("isa/8086/xor_mem_indirect_r8h.isa", "isa/8086/tests/v1/30.json.gz", "XOR [mem], r8h"),
    ("isa/8086/xor_r8h_mem_indirect.isa", "isa/8086/tests/v1/32.json.gz", "XOR r8h, [mem]"),

    # Memory indirect addressing - CMP
    ("isa/8086/cmp_mem_indirect_r16.isa", "isa/8086/tests/v1/39.json.gz", "CMP [mem], r16"),
    ("isa/8086/cmp_r16_mem_indirect.isa", "isa/8086/tests/v1/3B.json.gz", "CMP r16, [mem]"),
    ("isa/8086/cmp_mem_indirect_r8l.isa", "isa/8086/tests/v1/38.json.gz", "CMP [mem], r8l"),
    ("isa/8086/cmp_r8l_mem_indirect.isa", "isa/8086/tests/v1/3A.json.gz", "CMP r8l, [mem]"),
    ("isa/8086/cmp_mem_indirect_r8h.isa", "isa/8086/tests/v1/38.json.gz", "CMP [mem], r8h"),
    ("isa/8086/cmp_r8h_mem_indirect.isa", "isa/8086/tests/v1/3A.json.gz", "CMP r8h, [mem]"),

    # Memory indirect addressing - MOV
    ("isa/8086/mov_mem_indirect_r16.isa", "isa/8086/tests/v1/89.json.gz", "MOV [mem], r16"),
    ("isa/8086/mov_r16_mem_indirect.isa", "isa/8086/tests/v1/8B.json.gz", "MOV r16, [mem]"),
    ("isa/8086/mov_mem_indirect_r8l.isa", "isa/8086/tests/v1/88.json.gz", "MOV [mem], r8l"),
    ("isa/8086/mov_r8l_mem_indirect.isa", "isa/8086/tests/v1/8A.json.gz", "MOV r8l, [mem]"),
    ("isa/8086/mov_mem_indirect_r8h.isa", "isa/8086/tests/v1/88.json.gz", "MOV [mem], r8h"),
    ("isa/8086/mov_r8h_mem_indirect.isa", "isa/8086/tests/v1/8A.json.gz", "MOV r8h, [mem]"),

    # Additional LEA variant and WAIT
    ("isa/8086/lea_bx_si_disp.isa", "isa/8086/tests/v1/8D.json.gz", "LEA BX, [SI+disp]"),
    # ("isa/8086/wait.isa", "isa/8086/tests/v1/9B.json.gz", "WAIT"),  # No test file available

    # Segment register operations
    ("isa/8086/push_es.isa", "isa/8086/tests/v1/06.json.gz", "PUSH ES"),
    ("isa/8086/pop_es.isa", "isa/8086/tests/v1/07.json.gz", "POP ES"),
    ("isa/8086/push_cs.isa", "isa/8086/tests/v1/0E.json.gz", "PUSH CS"),
    ("isa/8086/push_ss.isa", "isa/8086/tests/v1/16.json.gz", "PUSH SS"),
    ("isa/8086/pop_ss.isa", "isa/8086/tests/v1/17.json.gz", "POP SS"),
    ("isa/8086/push_ds.isa", "isa/8086/tests/v1/1E.json.gz", "PUSH DS"),
    ("isa/8086/pop_ds.isa", "isa/8086/tests/v1/1F.json.gz", "POP DS"),

    # INC/DEC register variants
    ("isa/8086/inc_r16_short.isa", "isa/8086/tests/v1/41.json.gz", "INC CX"),
    ("isa/8086/inc_r16_short.isa", "isa/8086/tests/v1/42.json.gz", "INC DX"),
    ("isa/8086/inc_r16_short.isa", "isa/8086/tests/v1/43.json.gz", "INC BX"),
    ("isa/8086/inc_r16_short.isa", "isa/8086/tests/v1/44.json.gz", "INC SP"),
    ("isa/8086/inc_r16_short.isa", "isa/8086/tests/v1/45.json.gz", "INC BP"),
    ("isa/8086/inc_r16_short.isa", "isa/8086/tests/v1/46.json.gz", "INC SI"),
    ("isa/8086/inc_r16_short.isa", "isa/8086/tests/v1/47.json.gz", "INC DI"),
    ("isa/8086/dec_r16_short.isa", "isa/8086/tests/v1/49.json.gz", "DEC CX"),
    ("isa/8086/dec_r16_short.isa", "isa/8086/tests/v1/4A.json.gz", "DEC DX"),
    ("isa/8086/dec_r16_short.isa", "isa/8086/tests/v1/4B.json.gz", "DEC BX"),
    ("isa/8086/dec_r16_short.isa", "isa/8086/tests/v1/4C.json.gz", "DEC SP"),
    ("isa/8086/dec_r16_short.isa", "isa/8086/tests/v1/4D.json.gz", "DEC BP"),
    ("isa/8086/dec_r16_short.isa", "isa/8086/tests/v1/4E.json.gz", "DEC SI"),
    ("isa/8086/dec_r16_short.isa", "isa/8086/tests/v1/4F.json.gz", "DEC DI"),

    # PUSH/POP register variants
    ("isa/8086/push_r16.isa", "isa/8086/tests/v1/51.json.gz", "PUSH CX"),
    ("isa/8086/push_r16.isa", "isa/8086/tests/v1/52.json.gz", "PUSH DX"),
    ("isa/8086/push_r16.isa", "isa/8086/tests/v1/53.json.gz", "PUSH BX"),
    ("isa/8086/push_r16.isa", "isa/8086/tests/v1/54.json.gz", "PUSH SP"),
    ("isa/8086/push_r16.isa", "isa/8086/tests/v1/55.json.gz", "PUSH BP"),
    ("isa/8086/push_r16.isa", "isa/8086/tests/v1/56.json.gz", "PUSH SI"),
    ("isa/8086/push_r16.isa", "isa/8086/tests/v1/57.json.gz", "PUSH DI"),
    ("isa/8086/pop_r16.isa", "isa/8086/tests/v1/59.json.gz", "POP CX"),
    ("isa/8086/pop_r16.isa", "isa/8086/tests/v1/5A.json.gz", "POP DX"),
    ("isa/8086/pop_r16.isa", "isa/8086/tests/v1/5B.json.gz", "POP BX"),
    ("isa/8086/pop_r16.isa", "isa/8086/tests/v1/5C.json.gz", "POP SP"),
    ("isa/8086/pop_r16.isa", "isa/8086/tests/v1/5D.json.gz", "POP BP"),
    ("isa/8086/pop_r16.isa", "isa/8086/tests/v1/5E.json.gz", "POP SI"),
    ("isa/8086/pop_r16.isa", "isa/8086/tests/v1/5F.json.gz", "POP DI"),

    # REP prefix variants - use base opcode file, test selection logic will pick REP-prefixed tests
    ("isa/8086/repne_scasb.isa", "isa/8086/tests/v1/AE.json.gz", "REPNE SCASB"),
    ("isa/8086/rep_movsb.isa", "isa/8086/tests/v1/A4.json.gz", "REP MOVSB"),
    ("isa/8086/rep_movsw.isa", "isa/8086/tests/v1/A5.json.gz", "REP MOVSW"),
    ("isa/8086/repe_cmpsb.isa", "isa/8086/tests/v1/A6.json.gz", "REPE CMPSB"),
    ("isa/8086/rep_stosb.isa", "isa/8086/tests/v1/AA.json.gz", "REP STOSB"),
    ("isa/8086/rep_stosw.isa", "isa/8086/tests/v1/AB.json.gz", "REP STOSW"),
    ("isa/8086/rep_lodsb.isa", "isa/8086/tests/v1/AC.json.gz", "REP LODSB"),
    ("isa/8086/rep_lodsw.isa", "isa/8086/tests/v1/AD.json.gz", "REP LODSW"),

    # Immediate group instructions - 80.x (r/m8, imm8)
    ("isa/8086/add_rm8_imm8.isa", "isa/8086/tests/v1/80.0.json.gz", "ADD r/m8, imm8"),
    ("isa/8086/or_rm8_imm8.isa", "isa/8086/tests/v1/80.1.json.gz", "OR r/m8, imm8"),
    ("isa/8086/adc_rm8_imm8.isa", "isa/8086/tests/v1/80.2.json.gz", "ADC r/m8, imm8"),
    ("isa/8086/sbb_rm8_imm8.isa", "isa/8086/tests/v1/80.3.json.gz", "SBB r/m8, imm8"),
    ("isa/8086/and_rm8_imm8.isa", "isa/8086/tests/v1/80.4.json.gz", "AND r/m8, imm8"),
    ("isa/8086/sub_rm8_imm8.isa", "isa/8086/tests/v1/80.5.json.gz", "SUB r/m8, imm8"),
    ("isa/8086/xor_rm8_imm8.isa", "isa/8086/tests/v1/80.6.json.gz", "XOR r/m8, imm8"),
    ("isa/8086/cmp_rm8_imm8.isa", "isa/8086/tests/v1/80.7.json.gz", "CMP r/m8, imm8"),

    # Immediate group instructions - 81.x (r/m16, imm16)
    ("isa/8086/add_rm16_imm16.isa", "isa/8086/tests/v1/81.0.json.gz", "ADD r/m16, imm16"),
    ("isa/8086/or_rm16_imm16.isa", "isa/8086/tests/v1/81.1.json.gz", "OR r/m16, imm16"),
    ("isa/8086/adc_rm16_imm16.isa", "isa/8086/tests/v1/81.2.json.gz", "ADC r/m16, imm16"),
    ("isa/8086/sbb_rm16_imm16.isa", "isa/8086/tests/v1/81.3.json.gz", "SBB r/m16, imm16"),
    ("isa/8086/and_rm16_imm16.isa", "isa/8086/tests/v1/81.4.json.gz", "AND r/m16, imm16"),
    ("isa/8086/sub_rm16_imm16.isa", "isa/8086/tests/v1/81.5.json.gz", "SUB r/m16, imm16"),
    ("isa/8086/xor_rm16_imm16.isa", "isa/8086/tests/v1/81.6.json.gz", "XOR r/m16, imm16"),
    ("isa/8086/cmp_rm16_imm16.isa", "isa/8086/tests/v1/81.7.json.gz", "CMP r/m16, imm16"),

    # Immediate group instructions - 82.x (r/m8, imm8 - alias of 80.x)
    ("isa/8086/add_rm8_imm8.isa", "isa/8086/tests/v1/82.0.json.gz", "ADD r/m8, imm8"),
    ("isa/8086/or_rm8_imm8.isa", "isa/8086/tests/v1/82.1.json.gz", "OR r/m8, imm8"),
    ("isa/8086/adc_rm8_imm8.isa", "isa/8086/tests/v1/82.2.json.gz", "ADC r/m8, imm8"),
    ("isa/8086/sbb_rm8_imm8.isa", "isa/8086/tests/v1/82.3.json.gz", "SBB r/m8, imm8"),
    ("isa/8086/and_rm8_imm8.isa", "isa/8086/tests/v1/82.4.json.gz", "AND r/m8, imm8"),
    ("isa/8086/sub_rm8_imm8.isa", "isa/8086/tests/v1/82.5.json.gz", "SUB r/m8, imm8"),
    ("isa/8086/xor_rm8_imm8.isa", "isa/8086/tests/v1/82.6.json.gz", "XOR r/m8, imm8"),
    ("isa/8086/cmp_rm8_imm8.isa", "isa/8086/tests/v1/82.7.json.gz", "CMP r/m8, imm8"),

    # Immediate group instructions - 83.x (r/m16, imm8 sign-extended)
    ("isa/8086/add_rm16_imm16_se.isa", "isa/8086/tests/v1/83.0.json.gz", "ADD r/m16, imm8se"),
    ("isa/8086/or_rm16_imm16_se.isa", "isa/8086/tests/v1/83.1.json.gz", "OR r/m16, imm8se"),
    ("isa/8086/adc_rm16_imm16_se.isa", "isa/8086/tests/v1/83.2.json.gz", "ADC r/m16, imm8se"),
    ("isa/8086/sbb_rm16_imm16_se.isa", "isa/8086/tests/v1/83.3.json.gz", "SBB r/m16, imm8se"),
    ("isa/8086/and_rm16_imm16_se.isa", "isa/8086/tests/v1/83.4.json.gz", "AND r/m16, imm8se"),
    ("isa/8086/sub_rm16_imm16_se.isa", "isa/8086/tests/v1/83.5.json.gz", "SUB r/m16, imm8se"),
    ("isa/8086/xor_rm16_imm16_se.isa", "isa/8086/tests/v1/83.6.json.gz", "XOR r/m16, imm8se"),
    ("isa/8086/cmp_rm16_imm16_se.isa", "isa/8086/tests/v1/83.7.json.gz", "CMP r/m16, imm8se"),
]

def main():
    print("=" * 70)
    print("Running Multiple 8086 JSON Tests")
    print("=" * 70)

    passed = 0
    failed = 0
    errors = []

    for isa_file, test_file, description in test_cases:
        print(f"\nTesting: {description}")
        print(f"  ISA: {isa_file}")
        print(f"  Test: {test_file}")

        try:
            result = subprocess.run(
                ["python3", str(script_dir / "run_8086_json_test.py"), isa_file, test_file],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=project_root
            )

            if "TEST PASSED" in result.stdout:
                print("  ✅ PASSED")
                passed += 1
            else:
                print("  ❌ FAILED")
                failed += 1
                errors.append((description, result.stdout + result.stderr))
        except subprocess.TimeoutExpired:
            print("  ❌ TIMEOUT")
            failed += 1
            errors.append((description, "Test timed out after 30 seconds"))
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            failed += 1
            errors.append((description, str(e)))

    print("\n" + "=" * 70)
    print(f"SUMMARY: {passed} passed, {failed} failed out of {passed + failed} tests")
    print("=" * 70)

    if errors:
        print("\nFailed tests:")
        for desc, output in errors:
            print(f"\n{desc}:")
            print(output[:500])  # Show first 500 chars of output

    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()
