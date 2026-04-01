#!/usr/bin/env python3
"""
Generate JSON for the AES_BLOCK child ILA.

This represents the middle layer between the parent AES ILA and the aes128 function child.
Based on the C++ code in imdb/ILA_AES/src/aes_child.cc
"""

import json


def create_aes_block_json():
    """
    Create the AES_BLOCK child ILA JSON.

    States:
    - rd_data: 128-bit (read data buffer)
    - enc_data: 128-bit (encrypted data buffer)
    - byte_cnt: 4-bit (byte counter)
    - blk_cnt: 16-bit (block counter)

    Instructions:
    - LOAD: Read data byte-by-byte from memory
    - OPERATE: Call aes128 function and XOR result with plaintext
    - STORE: Write encrypted data byte-by-byte to memory
    """

    expr_id = 0
    expressions = []

    def add_expr(expr):
        nonlocal expr_id
        expressions.append(expr)
        result = expr_id
        expr_id += 1
        return result

    # Constants
    const_0 = add_expr({'o': 'const', 'v': 0, 'w': 4})
    const_1 = add_expr({'o': 'const', 'v': 1, 'w': 4})
    const_15 = add_expr({'o': 'const', 'v': 15, 'w': 4})
    const_16 = add_expr({'o': 'const', 'v': 16, 'w': 16})
    const_0_2bit = add_expr({'o': 'const', 'v': 0, 'w': 2})
    const_1_2bit = add_expr({'o': 'const', 'v': 1, 'w': 2})
    const_2_2bit = add_expr({'o': 'const', 'v': 2, 'w': 2})
    const_3_2bit = add_expr({'o': 'const', 'v': 3, 'w': 2})

    # States (will be added to top-level 's' array)
    state_rd_data = add_expr({'o': 'state', 'n': 'rd_data', 'w': 128})
    state_enc_data = add_expr({'o': 'state', 'n': 'enc_data', 'w': 128})
    state_byte_cnt = add_expr({'o': 'state', 'n': 'byte_cnt', 'w': 4})
    state_blk_cnt = add_expr({'o': 'state', 'n': 'blk_cnt', 'w': 16})

    # Parent states (referenced from parent)
    state_aes_status = add_expr({'o': 'state', 'n': 'aes_status', 'w': 2})
    state_aes_address = add_expr({'o': 'state', 'n': 'aes_address', 'w': 16})
    state_aes_length = add_expr({'o': 'state', 'n': 'aes_length', 'w': 16})
    state_aes_counter = add_expr({'o': 'state', 'n': 'aes_counter', 'w': 128})
    state_aes_key = add_expr({'o': 'state', 'n': 'aes_key', 'w': 128})
    state_XRAM = add_expr({'o': 'state', 'n': 'XRAM', 'w': 8})  # Memory

    # Child ILA function inputs/outputs for aes128
    state_plaintext = add_expr({'o': 'state', 'n': 'plaintext', 'w': 128})
    state_key_in = add_expr({'o': 'state', 'n': 'key_in', 'w': 128})
    state_ciphertext = add_expr({'o': 'state', 'n': 'ciphertext', 'w': 128})

    # ===== LOAD Instruction =====
    # Decode: aes_status == 1
    load_decode = add_expr({'o': 'op', 'c': 13, 'a': [state_aes_status, const_1_2bit]})  # EQ

    # Updates for LOAD:
    # byte_cnt <= byte_cnt + 1
    load_byte_cnt_update = add_expr({'o': 'op', 'c': 1, 'a': [state_byte_cnt, const_1]})  # ADD

    # rd_data <= slice_update(rd_data, byte_cnt, XRAM[address + blk_cnt + byte_cnt])
    # This is complex - for now use a placeholder that reads from memory
    # address + blk_cnt
    addr_plus_blk = add_expr({'o': 'op', 'c': 1, 'a': [state_aes_address, state_blk_cnt]})
    # (address + blk_cnt) + zext(byte_cnt, 16)
    byte_cnt_zext = add_expr({'o': 'op', 'c': 24, 'a': [state_byte_cnt], 'w': 16})  # ZEXT
    mem_addr = add_expr({'o': 'op', 'c': 1, 'a': [addr_plus_blk, byte_cnt_zext]})
    # XRAM[mem_addr]
    mem_read = add_expr({'o': 'op', 'c': 33, 'a': [state_XRAM, mem_addr]})  # LOAD
    # Simplified: just assign the read value (full slice_update logic is complex)
    load_rd_data_update = mem_read

    # aes_status <= (byte_cnt == 15) ? 2 : aes_status
    byte_cnt_eq_15 = add_expr({'o': 'op', 'c': 13, 'a': [state_byte_cnt, const_15]})
    load_status_update = add_expr({'o': 'op', 'c': 19, 'a': [byte_cnt_eq_15, const_2_2bit, state_aes_status]})  # ITE

    load_instr = {
        'n': 'LOAD',
        'd': load_decode,
        'u': {
            'byte_cnt': load_byte_cnt_update,
            'rd_data': load_rd_data_update,
            'aes_status': load_status_update
        }
    }

    # ===== OPERATE Instruction =====
    # Decode: aes_status == 2
    operate_decode = add_expr({'o': 'op', 'c': 13, 'a': [state_aes_status, const_2_2bit]})

    # Updates for OPERATE:
    # plaintext <= aes_counter + zext(blk_cnt, 128)
    blk_cnt_zext_128 = add_expr({'o': 'op', 'c': 24, 'a': [state_blk_cnt], 'w': 128})
    enc_ctr = add_expr({'o': 'op', 'c': 1, 'a': [state_aes_counter, blk_cnt_zext_128]})
    operate_plaintext_update = enc_ctr

    # key_in <= aes_key
    operate_key_update = state_aes_key

    # enc_data <= aes128(enc_ctr, aes_key) ^ rd_data
    # aes128 function call - will be represented as function_application
    aes128_func = add_expr({'o': 'function_application', 'n': 'aes128', 'a': [enc_ctr, state_aes_key]})
    operate_enc_data_update = add_expr({'o': 'op', 'c': 7, 'a': [aes128_func, state_rd_data]})  # XOR

    # aes_status <= 3
    operate_status_update = const_3_2bit

    operate_instr = {
        'n': 'OPERATE',
        'd': operate_decode,
        'u': {
            'plaintext': operate_plaintext_update,
            'key_in': operate_key_update,
            'enc_data': operate_enc_data_update,
            'aes_status': operate_status_update
        }
    }

    # ===== STORE Instruction =====
    # Decode: aes_status == 3
    store_decode = add_expr({'o': 'op', 'c': 13, 'a': [state_aes_status, const_3_2bit]})

    # Updates for STORE:
    # byte_cnt <= byte_cnt + 1
    store_byte_cnt_update = add_expr({'o': 'op', 'c': 1, 'a': [state_byte_cnt, const_1]})

    # blk_cnt <= (byte_cnt == 15) ? ((blk_cnt + 16 < length) ? blk_cnt + 16 : blk_cnt) : blk_cnt
    blk_cnt_plus_16 = add_expr({'o': 'op', 'c': 1, 'a': [state_blk_cnt, const_16]})
    blk_plus_16_lt_len = add_expr({'o': 'op', 'c': 14, 'a': [blk_cnt_plus_16, state_aes_length]})  # ULT
    inner_ite = add_expr({'o': 'op', 'c': 19, 'a': [blk_plus_16_lt_len, blk_cnt_plus_16, state_blk_cnt]})
    store_blk_cnt_update = add_expr({'o': 'op', 'c': 19, 'a': [byte_cnt_eq_15, inner_ite, state_blk_cnt]})

    # aes_status <= (byte_cnt == 15) ? ((blk_cnt + 16 < length) ? 1 : 0) : aes_status
    status_inner_ite = add_expr({'o': 'op', 'c': 19, 'a': [blk_plus_16_lt_len, const_1_2bit, const_0_2bit]})
    store_status_update = add_expr({'o': 'op', 'c': 19, 'a': [byte_cnt_eq_15, status_inner_ite, state_aes_status]})

    # XRAM[address + blk_cnt + byte_cnt] <= slice_read(enc_data, byte_cnt)
    # Simplified memory write
    store_mem_addr = add_expr({'o': 'op', 'c': 1, 'a': [addr_plus_blk, byte_cnt_zext]})
    # Extract byte from enc_data - simplified
    enc_data_byte = add_expr({'o': 'op', 'c': 33, 'a': [state_enc_data, state_byte_cnt]})  # Simplified
    store_xram_update = add_expr({'o': 'op', 'c': 34, 'a': [state_XRAM, store_mem_addr, enc_data_byte]})  # STORE

    store_instr = {
        'n': 'STORE',
        'd': store_decode,
        'u': {
            'byte_cnt': store_byte_cnt_update,
            'blk_cnt': store_blk_cnt_update,
            'aes_status': store_status_update,
            'XRAM': store_xram_update
        }
    }

    # Build the complete JSON
    aes_block_json = {
        'a': expressions,
        'f': [
            {'n': 'aes128', 'r': {'w': 128}, 'd': [{'w': 128}, {'w': 128}]}
        ],
        't': {
            'n': 'AES_BLOCK',
            's': [state_rd_data, state_enc_data, state_byte_cnt, state_blk_cnt,
                  state_plaintext, state_key_in, state_ciphertext],
            'instr': [load_instr, operate_instr, store_instr]
        }
    }

    return aes_block_json


def main():
    print("Generating AES_BLOCK child ILA JSON...")

    aes_block_json = create_aes_block_json()

    output_file = "test_data/aes_block_child.json"
    with open(output_file, 'w') as f:
        json.dump(aes_block_json, f, indent=2)

    print(f"✓ Generated {output_file}")
    print(f"  Expressions: {len(aes_block_json['a'])}")
    print(f"  Instructions: {len(aes_block_json['t']['instr'])}")
    print(f"  States: {len(aes_block_json['t']['s'])}")

    for instr in aes_block_json['t']['instr']:
        print(f"    - {instr['n']}: updates {list(instr['u'].keys())}")


if __name__ == '__main__':
    main()
