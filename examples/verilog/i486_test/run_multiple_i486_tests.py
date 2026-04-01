#!/usr/bin/env python3
"""Run multiple i486/80386 tests with automatic ISA file discovery."""

import subprocess
import sys
import csv
from pathlib import Path

# Get project root and script directory
script_dir = Path(__file__).parent
project_root = script_dir.parent.parent

# Test file base path (80386 tests work for i486)
TEST_BASE = "isa/i486/tests/v1_ex_real_mode"

# Mnemonic aliases (x86 has many synonyms)
MNEM_ALIASES = {
    'jnbe': 'ja', 'jnae': 'jb', 'jae': 'jnb',
    'jnl': 'jge', 'jnle': 'jg', 'jnge': 'jl', 'jng': 'jle',
    'jc': 'jb', 'jnc': 'jnb', 'je': 'jz', 'jne': 'jnz',
    'jpe': 'jp', 'jpo': 'jnp',
    'setnbe': 'seta', 'setnae': 'setb', 'setae': 'setnb',
    'setnl': 'setge', 'setnle': 'setg', 'setnge': 'setl', 'setng': 'setle',
    'setc': 'setb', 'setnc': 'setnb', 'sete': 'setz', 'setne': 'setnz',
    'loopz': 'loope', 'loopnz': 'loopne',
    'sal': 'shl',
}

# Direct opcode to ISA mappings for tricky cases
DIRECT_MAPPINGS = {
    # Segment push/pop
    '06': 'push_es', '07': 'pop_es',
    '0E': 'push_cs',
    '16': 'push_ss', '17': 'pop_ss',
    '1E': 'push_ds', '1F': 'pop_ds',
    '0FA0': 'push_fs', '0FA1': 'pop_fs',
    '0FA8': 'push_gs', '0FA9': 'pop_gs',

    # INC/DEC short forms (40-4F) - 16-bit and 32-bit
    **{f'4{i:X}': 'inc_r16_short' for i in range(8)},
    **{f'4{i:X}': 'dec_r16_short' for i in range(8, 16)},
    **{f'664{i:X}': 'inc_r32_short_66' for i in range(8)},
    **{f'664{i:X}': 'dec_r32_short_66' for i in range(8, 16)},

    # PUSH/POP short forms (50-5F) - 16-bit and 32-bit
    **{f'5{i:X}': 'push_r16' for i in range(8)},
    **{f'5{i:X}': 'pop_r16' for i in range(8, 16)},
    **{f'665{i:X}': 'push_r32_66' for i in range(8)},
    **{f'665{i:X}': 'pop_r32_66' for i in range(8, 16)},

    # XCHG AX,r16 (90-97) and EAX,r32 (66 90-97)
    '90': 'nop',
    **{f'9{i:X}': 'xchg_ax_r16' for i in range(1, 8)},
    **{f'669{i:X}': 'xchg_eax_r32_66' for i in range(1, 8)},

    # MOV r8,imm8 (B0-B7)
    **{f'B{i:X}': 'mov_r8_imm8' for i in range(8)},

    # MOV r16/32,imm16/32 (B8-BF)
    **{f'B{i:X}': 'mov_r16_imm' for i in range(8, 16)},
    **{f'66B{i:X}': 'mov_r32_imm32_66' for i in range(8, 16)},

    # 32-bit ALU operations (66 prefix) - use _66 ISA files
    '6601': 'add_rm32_r32_66', '6603': 'add_r32_rm32_66', '6605': 'add_eax_imm32',
    '6609': 'or_rm32_r32_66', '660B': 'or_r32_rm32_66', '660D': 'or_eax_imm32_66',
    '6611': 'adc_rm32_r32_66', '6613': 'adc_r32_rm32_66', '6615': 'adc_eax_imm32_66',
    '6619': 'sbb_rm32_r32_66', '661B': 'sbb_r32_rm32_66', '661D': 'sbb_eax_imm32_66',
    '6621': 'and_rm32_r32_66', '6623': 'and_r32_rm32_66', '6625': 'and_eax_imm32_66',
    '6629': 'sub_rm32_r32_66', '662B': 'sub_r32_rm32_66', '662D': 'sub_eax_imm32_66',
    '6631': 'xor_rm32_r32_66', '6633': 'xor_r32_rm32_66', '6635': 'xor_eax_imm32_66',
    '6639': 'cmp_rm32_r32_66', '663B': 'cmp_r32_rm32_66', '663D': 'cmp_eax_imm32_66',
    '6685': 'test_rm32_r32_66', '6687': 'xchg_r32_rm32_66',
    '6689': 'mov_rm32_r32_66', '668B': 'mov_r32_rm32_66', '668D': 'lea_r32_m',

    # 32-bit segment push/pop (66 prefix) - use _66 ISA files
    '6606': 'push_es_66', '6607': 'pop_es_66',
    '660E': 'push_cs_66',
    '6616': 'push_ss_66', '6617': 'pop_ss_66',
    '661E': 'push_ds_66', '661F': 'pop_ds_66',

    # 32-bit sign extension
    '6698': 'cwde', '6699': 'cdq',

    # 32-bit string operations
    '66A5': 'movsd', '66A7': 'cmpsd',
    '66AB': 'stosd', '66AD': 'lodsd', '66AF': 'scasd',

    # 32-bit conditional jumps (66 0F 8x) - use 66-prefixed versions
    **{f'660F8{i:X}': f'{["jo","jno","jb","jnb","jz","jnz","jbe","ja","js","jns","jp","jnp","jl","jge","jle","jg"][i]}_near_66' for i in range(16)},

    # 32-bit SETcc (66 0F 9x) - same as 16-bit, operates on r/m8
    **{f'660F9{i:X}': f'{["seto","setno","setb","setnb","setz","setnz","setbe","seta","sets","setns","setp","setnp","setl","setge","setle","setg"][i]}_rm8' for i in range(16)},

    # Group opcodes with sub-fields (0FBA.4-7 for BT/BTS/BTR/BTC)
    '0FBA.4': 'bt_rm32_imm8', '0FBA.5': 'bts_rm32_imm8',
    '0FBA.6': 'btr_rm32_imm8', '0FBA.7': 'btc_rm32_imm8',

    # Conditional jumps - near forms (0F 8x)
    '0F80': 'jo_near', '0F81': 'jno_near',
    '0F82': 'jb_near', '0F83': 'jnb_near',
    '0F84': 'jz_near', '0F85': 'jnz_near',
    '0F86': 'jbe_near', '0F87': 'ja_near',
    '0F88': 'js_near', '0F89': 'jns_near',
    '0F8A': 'jp_near', '0F8B': 'jnp_near',
    '0F8C': 'jl_near', '0F8D': 'jge_near',
    '0F8E': 'jle_near', '0F8F': 'jg_near',

    # SETcc (0F 9x)
    '0F90': 'seto_rm8', '0F91': 'setno_rm8',
    '0F92': 'setb_rm8', '0F93': 'setnb_rm8',
    '0F94': 'setz_rm8', '0F95': 'setnz_rm8',
    '0F96': 'setbe_rm8', '0F97': 'seta_rm8',
    '0F98': 'sets_rm8', '0F99': 'setns_rm8',
    '0F9A': 'setp_rm8', '0F9B': 'setnp_rm8',
    '0F9C': 'setl_rm8', '0F9D': 'setge_rm8',
    '0F9E': 'setle_rm8', '0F9F': 'setg_rm8',

    # SHLD/SHRD (real mode uses 16-bit by default)
    '0FA4': 'shld_rm16_r16_imm8', '0FA5': 'shld_rm16_r16_cl',
    '0FAC': 'shrd_rm16_r16_imm8', '0FAD': 'shrd_rm16_r16_cl',

    # BT/BTS/BTR/BTC with register
    '0FA3': 'bt_rm32_r32', '0FAB': 'bts_rm32_r32',
    '0FB3': 'btr_rm32_r32', '0FBB': 'btc_rm32_r32',

    # MOVZX/MOVSX (real mode uses 16-bit dest by default)
    '0FB6': 'movzx_r32_rm8', '0FB7': 'movzx_r32_rm16',
    '0FBE': 'movsx_r16_rm8', '0FBF': 'movsx_r32_rm16',

    # BSWAP (0FC8-0FCF)
    **{f'0FC{i:X}': 'bswap_r32' for i in range(8, 16)},

    # CMOVcc (0F4x) - if available
    '0F40': 'cmovo_r32_rm32', '0F41': 'cmovno_r32_rm32',
    '0F42': 'cmovb_r32_rm32', '0F43': 'cmovnb_r32_rm32',
    '0F44': 'cmovz_r32_rm32', '0F45': 'cmovnz_r32_rm32',
    '0F46': 'cmovbe_r32_rm32', '0F47': 'cmova_r32_rm32',
    '0F48': 'cmovs_r32_rm32', '0F49': 'cmovns_r32_rm32',
    '0F4A': 'cmovp_r32_rm32', '0F4B': 'cmovnp_r32_rm32',
    '0F4C': 'cmovl_r32_rm32', '0F4D': 'cmovge_r32_rm32',
    '0F4E': 'cmovle_r32_rm32', '0F4F': 'cmovg_r32_rm32',

    # Accumulator immediate forms (ax, imm16)
    # Base ALU opcodes (00-3F) - 16-bit default operand size
    # ADD
    '00': 'add_rm8_r8', '01': 'add_rm16_r16', '02': 'add_r8_rm8', '03': 'add_r16_rm16',
    '04': 'add_al_imm8', '05': 'add_ax_imm16',
    # OR
    '08': 'or_rm8_r8', '09': 'or_rm16_r16', '0A': 'or_r8_rm8', '0B': 'or_r16_rm16',
    '0C': 'or_al_imm8', '0D': 'or_ax_imm16',
    # ADC
    '10': 'adc_rm8_r8', '11': 'adc_rm16_r16', '12': 'adc_r8_rm8', '13': 'adc_r16_rm16',
    '14': 'adc_al_imm8', '15': 'adc_ax_imm16',
    # SBB
    '18': 'sbb_rm8_r8', '19': 'sbb_rm16_r16', '1A': 'sbb_r8_rm8', '1B': 'sbb_r16_rm16',
    '1C': 'sbb_al_imm8', '1D': 'sbb_ax_imm16',
    # AND
    '20': 'and_rm8_r8', '21': 'and_rm16_r16', '22': 'and_r8_rm8', '23': 'and_r16_rm16',
    '24': 'and_al_imm8', '25': 'and_ax_imm16',
    # SUB
    '28': 'sub_rm8_r8', '29': 'sub_rm16_r16', '2A': 'sub_r8_rm8', '2B': 'sub_r16_rm16',
    '2C': 'sub_al_imm8', '2D': 'sub_ax_imm16',
    # XOR
    '30': 'xor_rm8_r8', '31': 'xor_rm16_r16', '32': 'xor_r8_rm8', '33': 'xor_r16_rm16',
    '34': 'xor_al_imm8', '35': 'xor_ax_imm16',
    # CMP
    '38': 'cmp_rm8_r8', '39': 'cmp_rm16_r16', '3A': 'cmp_r8_rm8', '3B': 'cmp_r16_rm16',
    '3C': 'cmp_al_imm8', '3D': 'cmp_ax_imm16',

    # More base opcodes (84-8F)
    '84': 'test_rm8_r8', '85': 'test_rm16_r16',
    '86': 'xchg_r8_rm8', '87': 'xchg_r16_rm16',
    '88': 'mov_rm8_r8', '89': 'mov_rm16_r16',
    '8A': 'mov_r8_rm8', '8B': 'mov_r16_rm16',

    # Short conditional jumps (70-7F)
    '70': 'jo_rel8', '71': 'jno_rel8', '72': 'jb_rel8', '73': 'jnb_rel8',
    '74': 'jz_rel8', '75': 'jnz_rel8', '76': 'jbe_rel8', '77': 'ja_rel8',
    '78': 'js_rel8', '79': 'jns_rel8', '7A': 'jp_rel8', '7B': 'jnp_rel8',
    '7C': 'jl_rel8', '7D': 'jge_rel8', '7E': 'jle_rel8', '7F': 'jg_rel8',

    # String operations (A4-AF)
    'A4': 'movsb', 'A5': 'movsw', 'A6': 'cmpsb', 'A7': 'cmpsw',
    'A8': 'test_al_imm8', 'A9': 'test_ax_imm16',
    'AA': 'stosb', 'AB': 'stosw', 'AC': 'lodsb', 'AD': 'lodsw',
    'AE': 'scasb', 'AF': 'scasw',

    # I/O with DX (EC-EF)
    'EC': 'in_al_dx', 'ED': 'in_ax_dx', 'EE': 'out_dx_al', 'EF': 'out_dx_ax',

    # Jump/Loop (E0-EB)
    'E0': 'loopne', 'E1': 'loope', 'E2': 'loop', 'E3': 'jcxz',
    'E9': 'jmp_near', 'EB': 'jmp_rel8',

    # RET (C2-C3, CA-CB)
    'C2': 'ret_near_imm16',

    # PUSHA/POPA
    '60': 'pusha', '61': 'popa',
    '6660': 'pushad_66', '6661': 'popad_66',

    # BOUND
    '62': 'bound_r16_m16',

    # Group 1: 80.x, 81.x, 82.x, 83.x (ADD/OR/ADC/SBB/AND/SUB/XOR/CMP)
    **{f'80.{i}': ['add_rm8_imm8', 'or_rm8_imm8', 'adc_rm8_imm8', 'sbb_rm8_imm8',
                   'and_rm8_imm8', 'sub_rm8_imm8', 'xor_rm8_imm8', 'cmp_rm8_imm8'][i] for i in range(8)},
    **{f'81.{i}': ['add_rm16_imm16', 'or_rm16_imm16', 'adc_rm16_imm16', 'sbb_rm16_imm16',
                   'and_rm16_imm16', 'sub_rm16_imm16', 'xor_rm16_imm16', 'cmp_rm16_imm16'][i] for i in range(8)},
    **{f'82.{i}': ['add_rm8_imm8', 'or_rm8_imm8', 'adc_rm8_imm8', 'sbb_rm8_imm8',
                   'and_rm8_imm8', 'sub_rm8_imm8', 'xor_rm8_imm8', 'cmp_rm8_imm8'][i] for i in range(8)},
    **{f'83.{i}': ['add_rm16_imm8', 'or_rm16_imm8', 'adc_rm16_imm8', 'sbb_rm16_imm8',
                   'and_rm16_imm8', 'sub_rm16_imm8', 'xor_rm16_imm8', 'cmp_rm16_imm8'][i] for i in range(8)},

    # Group 1 32-bit: 6681.x, 6683.x (with 66 prefix)
    **{f'6681.{i}': ['add_rm32_imm32_66', 'or_rm32_imm32_66', 'adc_rm32_imm32_66', 'sbb_rm32_imm32_66',
                     'and_rm32_imm32_66', 'sub_rm32_imm32_66', 'xor_rm32_imm32_66', 'cmp_rm32_imm32_66'][i] for i in range(8)},
    **{f'6683.{i}': ['add_rm32_imm8_66', 'or_rm32_imm8_66', 'adc_rm32_imm8_66', 'sbb_rm32_imm8_66',
                     'and_rm32_imm8_66', 'sub_rm32_imm8_66', 'xor_rm32_imm8_66', 'cmp_rm32_imm8_66'][i] for i in range(8)},

    # Group 2: C0.x, C1.x (shifts with imm8)
    **{f'C0.{i}': ['rol_rm8_imm8', 'ror_rm8_imm8', 'rcl_rm8_imm8', 'rcr_rm8_imm8',
                   'shl_rm8_imm8', 'shr_rm8_imm8', 'shl_rm8_imm8', 'sar_rm8_imm8'][i] for i in range(8)},
    **{f'C1.{i}': ['rol_rm16_imm8', 'ror_rm16_imm8', 'rcl_rm16_imm8', 'rcr_rm16_imm8',
                   'shl_rm16_imm8', 'shr_rm16_imm8', 'shl_rm16_imm8', 'sar_rm16_imm8'][i] for i in range(8)},
    **{f'66C1.{i}': ['rol_rm32_imm8_66', 'ror_rm32_imm8_66', 'rcl_rm32_imm8_66', 'rcr_rm32_imm8_66',
                     'shl_rm32_imm8_66', 'shr_rm32_imm8_66', 'shl_rm32_imm8_66', 'sar_rm32_imm8_66'][i] for i in range(8)},

    # Group 2: D0.x, D1.x (shifts by 1)
    **{f'D0.{i}': ['rol_rm8_1', 'ror_rm8_1', 'rcl_rm8_1', 'rcr_rm8_1',
                   'shl_rm8_1', 'shr_rm8_1', 'shl_rm8_1', 'sar_rm8_1'][i] for i in range(8)},
    **{f'D1.{i}': ['rol_rm16_1', 'ror_rm16_1', 'rcl_rm16_1', 'rcr_rm16_1',
                   'shl_rm16_1', 'shr_rm16_1', 'shl_rm16_1', 'sar_rm16_1'][i] for i in range(8)},
    **{f'66D1.{i}': ['rol_rm32_1_66', 'ror_rm32_1_66', 'rcl_rm32_1_66', 'rcr_rm32_1_66',
                     'shl_rm32_1_66', 'shr_rm32_1_66', 'shl_rm32_1_66', 'sar_rm32_1_66'][i] for i in range(8)},

    # Group 2: D2.x, D3.x (shifts by CL)
    **{f'D2.{i}': ['rol_rm8_cl', 'ror_rm8_cl', 'rcl_rm8_cl', 'rcr_rm8_cl',
                   'shl_rm8_cl', 'shr_rm8_cl', 'shl_rm8_cl', 'sar_rm8_cl'][i] for i in range(8)},
    **{f'D3.{i}': ['rol_rm16_cl', 'ror_rm16_cl', 'rcl_rm16_cl', 'rcr_rm16_cl',
                   'shl_rm16_cl', 'shr_rm16_cl', 'shl_rm16_cl', 'sar_rm16_cl'][i] for i in range(8)},
    **{f'66D3.{i}': ['rol_rm32_cl_66', 'ror_rm32_cl_66', 'rcl_rm32_cl_66', 'rcr_rm32_cl_66',
                     'shl_rm32_cl_66', 'shr_rm32_cl_66', 'shl_rm32_cl_66', 'sar_rm32_cl_66'][i] for i in range(8)},

    # Group 3: F6.x (8-bit), F7.x (16-bit)
    **{f'F6.{i}': ['test_rm8_imm8', 'test_rm8_imm8', 'not_rm8', 'neg_rm8',
                   'mul_rm8', 'imul_rm8', 'div_rm8', 'idiv_rm8'][i] for i in range(8)},
    **{f'F7.{i}': ['test_rm16_imm16', 'test_rm16_imm16', 'not_rm16', 'neg_rm16',
                   'mul_rm16', 'imul_rm16', 'div_rm16', 'idiv_rm16'][i] for i in range(8)},
    **{f'66F7.{i}': ['test_rm32_imm32_66', 'test_rm32_imm32_66', 'not_rm32_66', 'neg_rm32_66',
                     'mul_rm32_66', 'imul_rm32_66', 'div_rm32_66', 'idiv_rm32_66'][i] for i in range(8)},

    # Group 4/5: FE.x (INC/DEC rm8), FF.x (INC/DEC/CALL/JMP/PUSH rm16)
    'FE.0': 'inc_rm8', 'FE.1': 'dec_rm8',
    **{f'FF.{i}': ['inc_rm16', 'dec_rm16', 'call_rm16', 'call_m16_16',
                   'jmp_rm16', 'jmp_m16_16', 'push_rm16'][i] for i in range(7)},

    # Load far pointer: LSS, LFS, LGS
    '0FB2': 'lss_r16_m16', '0FB4': 'lfs_r16_m16', '0FB5': 'lgs_r16_m16',

    # More 66-prefixed conversions
    '66A1': 'mov_eax_moffs32', '66A3': 'mov_moffs32_eax',

    # Additional base opcodes
    '68': 'push_imm16', '6668': 'push_imm32_66',
    '69': 'imul_r16_rm16_imm16', '6669': 'imul_r32_rm32_imm32_66',
    '6A': 'push_imm8', '666A': 'push_imm8_66',
    '6B': 'imul_r16_rm16_imm8', '666B': 'imul_r32_rm32_imm8_66',
    '8C': 'mov_rm16_sreg', '668C': 'mov_rm32_sreg',
    '8D': 'lea_r16_m', '668D': 'lea_r32_m',
    '8E': 'mov_sreg_rm16', '668E': 'mov_sreg_rm32',
    '8F': 'pop_rm16', '668F': 'pop_rm32',
    '9A': 'call_far', '669A': 'call_far',
    'A0': 'mov_al_moffs8', 'A1': 'mov_ax_moffs16',
    'A2': 'mov_moffs8_al', 'A3': 'mov_moffs16_ax',
    'C3': 'ret_near', '66C3': 'ret_near_66',
    'C4': 'les_r16_m16', '66C4': 'les_r32_m32',
    'C5': 'lds_r16_m16', '66C5': 'lds_r32_m32',
    'C6': 'mov_rm8_imm8', 'C7': 'mov_rm16_imm16', '66C7': 'mov_rm32_imm32',
    'CA': 'ret_far_imm16', '66CA': 'ret_far_imm16_66',
    'CB': 'ret_far', '66CB': 'ret_far_66',
    'D6': 'salc',
    'E4': 'in_al_imm8', 'E5': 'in_ax_imm8', '66E5': 'in_eax_imm8',
    'E6': 'out_imm8_al', 'E7': 'out_imm8_ax', '66E7': 'out_imm8_eax',
    'E8': 'call_near', '66E8': 'call_near_66',
    'EA': 'jmp_far', '66EA': 'jmp_far_66',

    # 66-prefix: BOUND, PUSH/POP
    '6662': 'bound_r32_m32_66',

    # 66-prefix: More two-byte opcodes (0F xx) - use _66 ISA files
    '660FA0': 'push_fs_66', '660FA1': 'pop_fs_66',
    '660FA3': 'bt_rm32_r32_66', '660FA4': 'shld_rm32_r32_imm8_66', '660FA5': 'shld_rm32_r32_cl_66',
    '660FA8': 'push_gs_66', '660FA9': 'pop_gs_66',
    '660FAB': 'bts_rm32_r32_66', '660FAC': 'shrd_rm32_r32_imm8_66', '660FAD': 'shrd_rm32_r32_cl_66',
    '660FAF': 'imul_r32_rm32_66',
    '660FB2': 'lss_r32_m32', '660FB3': 'btr_rm32_r32_66',
    '660FB4': 'lfs_r32_m32', '660FB5': 'lgs_r32_m32',
    '660FB6': 'movzx_r32_rm8_66', '660FB7': 'movzx_r32_rm16_66',
    '660FBA.4': 'bt_rm32_imm8_66', '660FBA.5': 'bts_rm32_imm8_66',
    '660FBA.6': 'btr_rm32_imm8_66', '660FBA.7': 'btc_rm32_imm8_66',
    '660FBB': 'btc_rm32_r32_66',
    '660FBC': 'bsf_r32_rm32_66', '660FBD': 'bsr_r32_rm32_66',
    '660FBE': 'movsx_r32_rm8_66', '660FBF': 'movsx_r32_rm16_66',

    # 66-prefix: conditional short jumps - use _66 ISA files
    **{f'6670': 'jo_rel8_66', '6671': 'jno_rel8_66', '6672': 'jb_rel8_66', '6673': 'jnb_rel8_66',
       '6674': 'jz_rel8_66', '6675': 'jnz_rel8_66', '6676': 'jbe_rel8_66', '6677': 'ja_rel8_66',
       '6678': 'js_rel8_66', '6679': 'jns_rel8_66', '667A': 'jp_rel8_66', '667B': 'jnp_rel8_66',
       '667C': 'jl_rel8_66', '667D': 'jge_rel8_66', '667E': 'jle_rel8_66', '667F': 'jg_rel8_66'},

    # 66-prefix: loops and misc
    '666D': 'insd', '666F': 'outsd',
    '66C2': 'ret_near_imm16_66',
    '66C8': 'enter_66', '66C9': 'leave_66',
    '66CF': 'iretd',
    '66E0': 'loopne_66', '66E1': 'loope_66', '66E2': 'loop_66', '66E3': 'jecxz_66',
    '66E9': 'jmp_near_66', '66EB': 'jmp_rel8_66',
    '66ED': 'in_eax_dx', '66EF': 'out_dx_eax',
}

# Generate 67-prefix mappings (address size override - use same ISA files)
# 67 prefix changes addressing mode but instruction logic is same
_67_BASE_MAPPINGS = {
    # 8-bit operations with 32-bit addressing - use _67 ISA files
    '00': 'add_rm8_r8_67', '02': 'add_r8_rm8_67',
    '08': 'or_rm8_r8_67', '0A': 'or_r8_rm8_67',
    '10': 'adc_rm8_r8_67', '12': 'adc_r8_rm8_67',
    '18': 'sbb_rm8_r8_67', '1A': 'sbb_r8_rm8_67',
    '20': 'and_rm8_r8_67', '22': 'and_r8_rm8_67',
    '28': 'sub_rm8_r8_67', '2A': 'sub_r8_rm8_67',
    '30': 'xor_rm8_r8_67', '32': 'xor_r8_rm8_67',
    '38': 'cmp_rm8_r8_67', '3A': 'cmp_r8_rm8_67',
    # 16-bit operations with 32-bit addressing - use _67 ISA files
    '01': 'add_rm16_r16_67', '03': 'add_r16_rm16_67',
    '09': 'or_rm16_r16_67', '0B': 'or_r16_rm16_67',
    '11': 'adc_rm16_r16_67', '13': 'adc_r16_rm16_67',
    '19': 'sbb_rm16_r16_67', '1B': 'sbb_r16_rm16_67',
    '21': 'and_rm16_r16_67', '23': 'and_r16_rm16_67',
    '29': 'sub_rm16_r16_67', '2B': 'sub_r16_rm16_67',
    '31': 'xor_rm16_r16_67', '33': 'xor_r16_rm16_67',
    '39': 'cmp_rm16_r16_67', '3B': 'cmp_r16_rm16_67',
    '62': 'bound_r16_m16',
    '69': 'imul_r16_rm16_imm16', '6B': 'imul_r16_rm16_imm8',
    '6C': 'insb', '6D': 'insw', '6E': 'outsb', '6F': 'outsw',
    '84': 'test_rm8_r8_67', '85': 'test_rm16_r16_67',
    '86': 'xchg_rm8_r8_67', '87': 'xchg_rm16_r16_67',
    '88': 'mov_rm8_r8_67', '89': 'mov_rm16_r16_67',
    '8A': 'mov_r8_rm8_67', '8B': 'mov_r16_rm16_67',
    '8C': 'mov_rm16_sreg_67', '8D': 'lea_r16_m_67',
    '8E': 'mov_sreg_rm16_67', '8F': 'pop_rm16_67',
    'A0': 'mov_al_moffs8', 'A1': 'mov_ax_moffs16',
    'A2': 'mov_moffs8_al', 'A3': 'mov_moffs16_ax',
    'A4': 'movsb_67', 'A5': 'movsw_67', 'A6': 'cmpsb_67', 'A7': 'cmpsw_67',
    'AA': 'stosb_67', 'AB': 'stosw_67', 'AC': 'lodsb_67', 'AD': 'lodsw_67',
    'AE': 'scasb_67', 'AF': 'scasw_67',
    'C4': 'les_r16_m16_67', 'C5': 'lds_r16_m16_67',
    'C6': 'mov_rm8_imm8_67', 'C7': 'mov_rm16_imm16_67',
    'D7': 'xlat',
    'E0': 'loopne_67', 'E1': 'loope_67', 'E2': 'loop_67', 'E3': 'jcxz_67',
}

# Add 67-prefix mappings
for op, isa in _67_BASE_MAPPINGS.items():
    DIRECT_MAPPINGS[f'67{op}'] = isa

# 67-prefix group opcodes
for i in range(8):
    DIRECT_MAPPINGS[f'6780.{i}'] = ['add_rm8_imm8', 'or_rm8_imm8', 'adc_rm8_imm8', 'sbb_rm8_imm8',
                                     'and_rm8_imm8', 'sub_rm8_imm8', 'xor_rm8_imm8', 'cmp_rm8_imm8'][i]
    DIRECT_MAPPINGS[f'6781.{i}'] = ['add_rm16_imm16', 'or_rm16_imm16', 'adc_rm16_imm16', 'sbb_rm16_imm16',
                                     'and_rm16_imm16', 'sub_rm16_imm16', 'xor_rm16_imm16', 'cmp_rm16_imm16'][i]
    DIRECT_MAPPINGS[f'6782.{i}'] = ['add_rm8_imm8', 'or_rm8_imm8', 'adc_rm8_imm8', 'sbb_rm8_imm8',
                                     'and_rm8_imm8', 'sub_rm8_imm8', 'xor_rm8_imm8', 'cmp_rm8_imm8'][i]
    DIRECT_MAPPINGS[f'6783.{i}'] = ['add_rm16_imm8', 'or_rm16_imm8', 'adc_rm16_imm8', 'sbb_rm16_imm8',
                                     'and_rm16_imm8', 'sub_rm16_imm8', 'xor_rm16_imm8', 'cmp_rm16_imm8'][i]
    DIRECT_MAPPINGS[f'67C0.{i}'] = ['rol_rm8_imm8_67', 'ror_rm8_imm8_67', 'rcl_rm8_imm8_67', 'rcr_rm8_imm8_67',
                                     'shl_rm8_imm8_67', 'shr_rm8_imm8_67', 'shl_rm8_imm8_67', 'sar_rm8_imm8_67'][i]
    DIRECT_MAPPINGS[f'67C1.{i}'] = ['rol_rm16_imm8_67', 'ror_rm16_imm8_67', 'rcl_rm16_imm8_67', 'rcr_rm16_imm8_67',
                                     'shl_rm16_imm8_67', 'shr_rm16_imm8_67', 'shl_rm16_imm8_67', 'sar_rm16_imm8_67'][i]
    DIRECT_MAPPINGS[f'67D0.{i}'] = ['rol_rm8_1_67', 'ror_rm8_1_67', 'rcl_rm8_1_67', 'rcr_rm8_1_67',
                                     'shl_rm8_1_67', 'shr_rm8_1_67', 'shl_rm8_1_67', 'sar_rm8_1_67'][i]
    DIRECT_MAPPINGS[f'67D1.{i}'] = ['rol_rm16_1_67', 'ror_rm16_1_67', 'rcl_rm16_1_67', 'rcr_rm16_1_67',
                                     'shl_rm16_1_67', 'shr_rm16_1_67', 'shl_rm16_1_67', 'sar_rm16_1_67'][i]
    DIRECT_MAPPINGS[f'67D2.{i}'] = ['rol_rm8_cl_67', 'ror_rm8_cl_67', 'rcl_rm8_cl_67', 'rcr_rm8_cl_67',
                                     'shl_rm8_cl_67', 'shr_rm8_cl_67', 'shl_rm8_cl_67', 'sar_rm8_cl_67'][i]
    DIRECT_MAPPINGS[f'67D3.{i}'] = ['rol_rm16_cl_67', 'ror_rm16_cl_67', 'rcl_rm16_cl_67', 'rcr_rm16_cl_67',
                                     'shl_rm16_cl_67', 'shr_rm16_cl_67', 'shl_rm16_cl_67', 'sar_rm16_cl_67'][i]
    DIRECT_MAPPINGS[f'67F6.{i}'] = ['test_rm8_imm8_67', 'test_rm8_imm8_67', 'not_rm8_67', 'neg_rm8_67',
                                     'mul_rm8_67', 'imul_rm8_67', 'div_rm8_67', 'idiv_rm8_67'][i]
    DIRECT_MAPPINGS[f'67F7.{i}'] = ['test_rm16_imm16_67', 'test_rm16_imm16_67', 'not_rm16_67', 'neg_rm16_67',
                                     'mul_rm16_67', 'imul_rm16_67', 'div_rm16_67', 'idiv_rm16_67'][i]

# 67-prefix SETcc - use _67 ISA files for 32-bit addressing
for i in range(16):
    cond = ['o','no','b','nb','z','nz','be','a','s','ns','p','np','l','ge','le','g'][i]
    DIRECT_MAPPINGS[f'670F9{i:X}'] = f'set{cond}_rm8_67'

# 67-prefix two-byte opcodes - use _67 ISA files for 32-bit addressing
DIRECT_MAPPINGS.update({
    '670FA3': 'bt_rm16_r16_67', '670FA4': 'shld_rm16_r16_imm8_67', '670FA5': 'shld_rm16_r16_cl_67',
    '670FAB': 'bts_rm16_r16_67', '670FAC': 'shrd_rm16_r16_imm8_67', '670FAD': 'shrd_rm16_r16_cl_67',
    '670FAF': 'imul_r16_rm16_67',
    '670FB2': 'lss_r16_m16', '670FB3': 'btr_rm16_r16_67',
    '670FB4': 'lfs_r16_m16', '670FB5': 'lgs_r16_m16',
    '670FB6': 'movzx_r16_rm8_67', '670FB7': 'movzx_r16_rm16',
    '670FBA.4': 'bt_rm16_imm8', '670FBA.5': 'bts_rm16_imm8',
    '670FBA.6': 'btr_rm16_imm8', '670FBA.7': 'btc_rm16_imm8',
    '670FBB': 'btc_rm16_r16_67',
    '670FBC': 'bsf_r16_rm16_67', '670FBD': 'bsr_r16_rm16_67',
    '670FBE': 'movsx_r16_rm8_67', '670FBF': 'movsx_r16_rm16',
})

# 6766-prefix (both operand and address size) - 32-bit operations with 32-bit addressing
_6766_BASE = {
    '01': 'add_rm32_r32_6766', '03': 'add_r32_rm32_6766',
    '09': 'or_rm32_r32_6766', '0B': 'or_r32_rm32_6766',
    '11': 'adc_rm32_r32_6766', '13': 'adc_r32_rm32_6766',
    '19': 'sbb_rm32_r32_6766', '1B': 'sbb_r32_rm32_6766',
    '21': 'and_rm32_r32_6766', '23': 'and_r32_rm32_6766',
    '29': 'sub_rm32_r32_6766', '2B': 'sub_r32_rm32_6766',
    '31': 'xor_rm32_r32_6766', '33': 'xor_r32_rm32_6766',
    '39': 'cmp_rm32_r32_6766', '3B': 'cmp_r32_rm32_6766',
    '62': 'bound_r32_m32',
    '69': 'imul_r32_rm32_imm32', '6B': 'imul_r32_rm32_imm8',
    '6D': 'insd', '6F': 'outsd',
    '85': 'test_rm32_r32', '87': 'xchg_r32_rm32',
    '89': 'mov_rm32_r32', '8B': 'mov_r32_rm32',
    '8C': 'mov_rm32_sreg', '8D': 'lea_r32_m',
    '8E': 'mov_sreg_rm32', '8F': 'pop_rm32',
    'A1': 'mov_eax_moffs32', 'A3': 'mov_moffs32_eax',
    'A5': 'movsd', 'A7': 'cmpsd',
    'AB': 'stosd', 'AD': 'lodsd', 'AF': 'scasd',
    'C4': 'les_r32_m32', 'C5': 'lds_r32_m32', 'C7': 'mov_rm32_imm32',
    'E0': 'loopne', 'E1': 'loope', 'E2': 'loop', 'E3': 'jecxz',
}
for op, isa in _6766_BASE.items():
    DIRECT_MAPPINGS[f'6766{op}'] = isa

# 6766-prefix group opcodes
for i in range(8):
    DIRECT_MAPPINGS[f'676681.{i}'] = ['add_rm32_imm32_6766', 'or_rm32_imm32_6766', 'adc_rm32_imm32_6766', 'sbb_rm32_imm32_6766',
                                       'and_rm32_imm32_6766', 'sub_rm32_imm32_6766', 'xor_rm32_imm32_6766', 'cmp_rm32_imm32_6766'][i]
    DIRECT_MAPPINGS[f'676683.{i}'] = ['add_rm32_imm8_6766', 'or_rm32_imm8_6766', 'adc_rm32_imm8_6766', 'sbb_rm32_imm8_6766',
                                       'and_rm32_imm8_6766', 'sub_rm32_imm8_6766', 'xor_rm32_imm8_6766', 'cmp_rm32_imm8_6766'][i]
    DIRECT_MAPPINGS[f'6766C1.{i}'] = ['rol_rm32_imm8_6766', 'ror_rm32_imm8_6766', 'rcl_rm32_imm8_6766', 'rcr_rm32_imm8_6766',
                                       'shl_rm32_imm8_6766', 'shr_rm32_imm8_6766', 'shl_rm32_imm8_6766', 'sar_rm32_imm8_6766'][i]
    DIRECT_MAPPINGS[f'6766D1.{i}'] = ['rol_rm32_1_6766', 'ror_rm32_1_6766', 'rcl_rm32_1_6766', 'rcr_rm32_1_6766',
                                       'shl_rm32_1_6766', 'shr_rm32_1_6766', 'shl_rm32_1_6766', 'sar_rm32_1_6766'][i]
    DIRECT_MAPPINGS[f'6766D3.{i}'] = ['rol_rm32_cl_6766', 'ror_rm32_cl_6766', 'rcl_rm32_cl_6766', 'rcr_rm32_cl_6766',
                                       'shl_rm32_cl_6766', 'shr_rm32_cl_6766', 'shl_rm32_cl_6766', 'sar_rm32_cl_6766'][i]
    DIRECT_MAPPINGS[f'6766F7.{i}'] = ['test_rm32_imm32_6766', 'test_rm32_imm32_6766', 'not_rm32_6766', 'neg_rm32_6766',
                                       'mul_rm32_6766', 'imul_rm32_6766', 'div_rm32_6766', 'idiv_rm32_6766'][i]

# 6766-prefix two-byte opcodes - use _6766 ISA files
DIRECT_MAPPINGS.update({
    '67660FA3': 'bt_rm32_r32_6766', '67660FA4': 'shld_rm32_r32_imm8_6766', '67660FA5': 'shld_rm32_r32_cl_6766',
    '67660FAB': 'bts_rm32_r32_6766', '67660FAC': 'shrd_rm32_r32_imm8_6766', '67660FAD': 'shrd_rm32_r32_cl_6766',
    '67660FAF': 'imul_r32_rm32_6766',
    '67660FB2': 'lss_r32_m32', '67660FB3': 'btr_rm32_r32_6766',
    '67660FB4': 'lfs_r32_m32', '67660FB5': 'lgs_r32_m32',
    '67660FB6': 'movzx_r32_rm8_6766', '67660FB7': 'movzx_r32_rm16_6766',
    '67660FBA.4': 'bt_rm32_imm8_6766', '67660FBA.5': 'bts_rm32_imm8_6766',
    '67660FBA.6': 'btr_rm32_imm8_6766', '67660FBA.7': 'btc_rm32_imm8_6766',
    '67660FBB': 'btc_rm32_r32_6766',
    '67660FBC': 'bsf_r32_rm32_6766', '67660FBD': 'bsr_r32_rm32_6766',
    '67660FBE': 'movsx_r32_rm8_6766', '67660FBF': 'movsx_r32_rm16_6766',
})


def load_opcode_info():
    """Load opcode information from CSV."""
    csv_path = project_root / "isa/i486/tests/80386.csv"
    opcode_info = {}
    with open(csv_path, 'r') as f:
        for row in csv.DictReader(f):
            op = row['op']
            mnem = row['mnemonic'].lower()
            op1 = row.get('op1', '').lower().strip()
            op2 = row.get('op2', '').lower().strip()
            if mnem:
                opcode_info[op] = (mnem, op1, op2)
    return opcode_info


def find_isa_file(opcode, mnemonic, op1, op2, isa_files):
    """Find ISA file for given opcode."""
    # Check direct mapping first
    if opcode in DIRECT_MAPPINGS:
        isa_name = DIRECT_MAPPINGS[opcode]
        if isa_name in isa_files:
            return isa_files[isa_name]

    # Resolve mnemonic aliases
    m = mnemonic.lower()
    if m in MNEM_ALIASES:
        m = MNEM_ALIASES[m]

    # Normalize operands
    def norm(op):
        op = op.lower().replace('/', '_').replace(' ', '_')
        subs = {
            'r_m8': 'rm8', 'r_m16': 'rm16', 'r_m32': 'rm32',
            'r_m16_32': 'rm32', 'r16_32': 'r32',
            'imm16_32': 'imm32',
        }
        return subs.get(op, op)

    op1_n = norm(op1) if op1 else ''
    op2_n = norm(op2) if op2 else ''

    # Build candidates
    candidates = []
    if op1_n and op2_n:
        candidates.extend([
            f"{m}_{op1_n}_{op2_n}",
            f"{m}_{op2_n}_{op1_n}",
            f"{m}_{op1_n}",
        ])
    elif op1_n:
        candidates.append(f"{m}_{op1_n}")
    candidates.append(m)

    # Also try _near suffix for jumps
    if m.startswith('j') and len(m) <= 4:
        candidates.append(f"{m}_near")
        candidates.insert(0, f"{m}_near")

    for c in candidates:
        if c in isa_files:
            return isa_files[c]

    return None


def discover_tests():
    """Automatically discover all available test cases."""
    isa_dir = project_root / "isa/i486"
    test_dir = project_root / TEST_BASE

    # Get all ISA files
    isa_files = {f.stem: f"isa/i486/{f.name}" for f in isa_dir.glob("*.isa")}

    # Get all test files
    test_files = sorted(test_dir.glob("*.MOO.gz"))

    # Load opcode info
    opcode_info = load_opcode_info()

    # Match tests to ISA files
    tests = []
    for test_path in test_files:
        opcode = test_path.stem.replace('.MOO', '')
        test_rel = f"{TEST_BASE}/{test_path.name}"

        if opcode in opcode_info:
            mnemonic, op1, op2 = opcode_info[opcode]
        else:
            mnemonic, op1, op2 = '', '', ''

        isa_path = find_isa_file(opcode, mnemonic, op1, op2, isa_files)

        if isa_path:
            desc = f"{mnemonic.upper()}" if mnemonic else opcode
            if op1:
                desc += f" {op1}"
            if op2:
                desc += f", {op2}"
            tests.append((isa_path, test_rel, desc.strip()))

    return tests


def main():
    print("=" * 70)
    print("Running Multiple i486/80386 Tests (Auto-Discovery)")
    print("=" * 70)

    # Discover all available tests
    test_cases = discover_tests()
    print(f"Discovered {len(test_cases)} test cases\n")

    passed = 0
    failed = 0
    skipped = 0
    errors = []

    for isa_file, test_file, description in test_cases:
        print(f"\nTesting: {description}")
        print(f"  ISA: {isa_file}")
        print(f"  Test: {test_file}")

        # Check if files exist
        isa_path = project_root / isa_file
        test_path = project_root / test_file

        if not isa_path.exists():
            print(f"  SKIPPED (ISA file not found)")
            skipped += 1
            continue

        if not test_path.exists():
            print(f"  SKIPPED (Test file not found)")
            skipped += 1
            continue

        try:
            result = subprocess.run(
                ["python3", str(script_dir / "run_i486_json_test.py"), isa_file, test_file],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=project_root
            )

            if "TEST PASSED" in result.stdout or "PASSED TEST" in result.stdout:
                print("  PASSED")
                passed += 1
            else:
                print("  FAILED")
                failed += 1
                errors.append((description, result.stdout[-1000:] + result.stderr[-500:]))
        except subprocess.TimeoutExpired:
            print("  TIMEOUT")
            failed += 1
            errors.append((description, "Test timed out after 60 seconds"))
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1
            errors.append((description, str(e)))

    print("\n" + "=" * 70)
    print(f"SUMMARY: {passed} passed, {failed} failed, {skipped} skipped")
    print("=" * 70)

    if errors and len(errors) <= 10:
        print("\nFailed tests:")
        for desc, output in errors:
            print(f"\n{desc}:")
            print(output[:500])

    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()
