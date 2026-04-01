#!/usr/bin/env python3
"""
Generate full SHA parent ILA with child function call in START_SHA instruction.
This creates the hierarchical ILA structure that can be inlined.
"""

import json

# ILAng operation codes
OP_AND = 4
OP_OR = 5
OP_EQ = 13
OP_ULT = 16  # Unsigned less than
OP_UGT = 17  # Unsigned greater than
OP_CONCAT = 20
OP_EXTRACT = 21
OP_ITE = 26
OP_LOAD = 18
OP_STORE = 19
OP_APP_FUNC = 24

# SHA register addresses
SHA_RD_ADDR = 0xFF00
SHA_WR_ADDR = 0xFF02
SHA_LEN = 0xFF04
SHA_START = 0xFF06

# SHA-1 initial hash values (FIPS 180-4)
H_INIT = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0]

CMD_READ = 1
CMD_WRITE = 2
SHA_STATE_IDLE = 0


class SHAFullGenerator:
    def __init__(self):
        self.next_id = 1000
        self.exprs = []
        self.state_map = {}
        self.state_ids = []
        
    def alloc_id(self):
        id_val = self.next_id
        self.next_id += 1
        return id_val
    
    def const(self, value, width):
        expr_id = self.alloc_id()
        self.exprs.append({
            "i": expr_id,
            "s": {"u": 2, "w": width},
            "u": 2,
            "v": {"v": value}
        })
        return expr_id
    
    def input_state(self, name, width):
        input_id = self.alloc_id()
        self.exprs.append({
            "i": input_id,
            "n": name,
            "s": {"u": 2, "w": width},
            "u": 1
        })
        self.state_map[name] = input_id
        self.state_ids.append(input_id)
        return input_id
    
    def state(self, name, width):
        state_id = self.alloc_id()
        self.exprs.append({
            "i": state_id,
            "n": name,
            "s": {"u": 2, "w": width},
            "u": 1
        })
        self.state_map[name] = state_id
        self.state_ids.append(state_id)
        return state_id
    
    def mem_state(self, name, addr_width, data_width):
        mem_id = self.alloc_id()
        self.exprs.append({
            "i": mem_id,
            "n": name,
            "s": {"u": 3, "a": addr_width, "d": data_width},
            "u": 1
        })
        self.state_map[name] = mem_id
        self.state_ids.append(mem_id)
        return mem_id
    
    def op(self, opcode, args, params=None):
        expr_id = self.alloc_id()
        self.exprs.append({
            "a": args,
            "i": expr_id,
            "o": opcode,
            "p": params if params else [],
            "u": 3
        })
        return expr_id
    
    def extract(self, expr, high, low):
        return self.op(OP_EXTRACT, [expr], [high, low])
    
    def concat(self, *args):
        if len(args) == 0:
            raise ValueError("concat requires at least one argument")
        if len(args) == 1:
            return args[0]
        result = args[0]
        for arg in args[1:]:
            result = self.op(OP_CONCAT, [result, arg])
        return result
    
    def eq(self, a, b):
        return self.op(OP_EQ, [a, b])
    
    def and_op(self, a, b):
        return self.op(OP_AND, [a, b])
    
    def or_op(self, a, b):
        return self.op(OP_OR, [a, b])

    def ult(self, a, b):
        """Unsigned less than"""
        return self.op(OP_ULT, [a, b])

    def ugt(self, a, b):
        """Unsigned greater than"""
        return self.op(OP_UGT, [a, b])

    def uge(self, a, b):
        """Unsigned greater or equal (implemented as a >= b ≡ (a == b) || (a > b))"""
        return self.or_op(self.eq(a, b), self.ugt(a, b))

    def ult_or_eq(self, a, b):
        """Unsigned less than or equal (implemented as a <= b ≡ (a == b) || (a < b))"""
        return self.or_op(self.eq(a, b), self.ult(a, b))
    
    def ite(self, cond, true_val, false_val):
        return self.op(OP_ITE, [cond, true_val, false_val])
    
    def load(self, mem, addr):
        return self.op(OP_LOAD, [mem, addr])
    
    def store(self, mem, addr, data):
        return self.op(OP_STORE, [mem, addr, data])
    
    def declare_func(self, name, ret_width):
        """Declare a function (for child ILA)"""
        func_id = self.alloc_id()
        self.exprs.append({
            "i": func_id,
            "n": name,
            "s": {"u": 2, "w": ret_width},  # Return sort
            "u": 5  # Function type
        })
        return func_id
    
    def apply_func(self, func_id, *args):
        """Apply function with arguments"""
        app_id = self.alloc_id()
        self.exprs.append({
            "a": [func_id] + list(args),
            "i": app_id,
            "o": OP_APP_FUNC,
            "u": 3
        })
        return app_id
    
    def slice_read(self, reg, cmdaddr, base_addr, num_bytes, data_width):
        if num_bytes == 2:
            byte0_cond = self.eq(cmdaddr, self.const(base_addr, 16))
            byte1_cond = self.eq(cmdaddr, self.const(base_addr + 1, 16))
            byte0 = self.extract(reg, 7, 0)
            byte1 = self.extract(reg, 15, 8)
            return self.ite(byte0_cond, byte0, self.ite(byte1_cond, byte1, self.const(0, data_width)))
        return self.extract(reg, data_width - 1, 0)
    
    def generate(self):
        print("Generating full SHA parent ILA with child function call...")
        
        # Create I/O interface
        cmd = self.input_state("cmd", 2)
        cmdaddr = self.input_state("cmdaddr", 16)
        cmddata = self.input_state("cmddata", 8)
        
        # Create architectural state
        dataout = self.state("dataout", 8)
        state = self.state("sha_state", 3)
        rdaddr = self.state("sha_rdaddr", 16)
        wraddr = self.state("sha_wraddr", 16)
        oplen = self.state("sha_len", 16)
        xram = self.mem_state("XRAM", 16, 8)
        
        # Create constants
        const_1_cmd = self.const(CMD_READ, 2)
        const_2_cmd = self.const(CMD_WRITE, 2)
        const_1_data = self.const(1, 8)
        const_idle = self.const(SHA_STATE_IDLE, 3)
        const_active = self.const(1, 3)
        
        # Address constants
        sha_rd_addr = self.const(SHA_RD_ADDR, 16)
        sha_rd_addr_plus1 = self.const(SHA_RD_ADDR + 1, 16)
        sha_rd_addr_plus2 = self.const(SHA_RD_ADDR + 2, 16)
        sha_wr_addr = self.const(SHA_WR_ADDR, 16)
        sha_wr_addr_plus1 = self.const(SHA_WR_ADDR + 1, 16)
        sha_wr_addr_plus2 = self.const(SHA_WR_ADDR + 2, 16)
        sha_len = self.const(SHA_LEN, 16)
        sha_len_plus1 = self.const(SHA_LEN + 1, 16)
        sha_len_plus2 = self.const(SHA_LEN + 2, 16)
        sha_start = self.const(SHA_START, 16)
        
        # Fetch and valid
        fetch_expr = self.concat(cmd, cmdaddr, cmddata)
        valid_expr = self.or_op(self.eq(cmd, const_1_cmd), self.eq(cmd, const_2_cmd))
        
        is_status_idle = self.eq(state, const_idle)
        
        print("Creating instructions...")
        instructions = []
        
        # Instructions 1-6: Register read/write (same as parent-only version)
        # WRITE_RD_ADDR
        wr_rdaddr_decode = self.and_op(
            self.and_op(self.eq(cmd, const_2_cmd), self.uge(cmdaddr, sha_rd_addr)),
            self.ugt(sha_rd_addr_plus2, cmdaddr)
        )
        is_high_byte = self.eq(cmdaddr, sha_rd_addr_plus1)
        is_low_byte = self.eq(cmdaddr, sha_rd_addr)
        high_byte = self.ite(is_high_byte, cmddata, self.extract(rdaddr, 15, 8))
        low_byte = self.ite(is_low_byte, cmddata, self.extract(rdaddr, 7, 0))
        new_rdaddr = self.concat(high_byte, low_byte)
        rdaddr_update = self.ite(is_status_idle, new_rdaddr, rdaddr)
        instructions.append({"n": "WRITE_RD_ADDR", "d": wr_rdaddr_decode, "u": {"sha_rdaddr": rdaddr_update}})
        
        # WRITE_WR_ADDR
        wr_wraddr_decode = self.and_op(
            self.and_op(self.eq(cmd, const_2_cmd), self.uge(cmdaddr, sha_wr_addr)),
            self.ugt(sha_wr_addr_plus2, cmdaddr)
        )
        is_high_byte_wr = self.eq(cmdaddr, sha_wr_addr_plus1)
        is_low_byte_wr = self.eq(cmdaddr, sha_wr_addr)
        high_byte_wr = self.ite(is_high_byte_wr, cmddata, self.extract(wraddr, 15, 8))
        low_byte_wr = self.ite(is_low_byte_wr, cmddata, self.extract(wraddr, 7, 0))
        new_wraddr = self.concat(high_byte_wr, low_byte_wr)
        wraddr_update = self.ite(is_status_idle, new_wraddr, wraddr)
        instructions.append({"n": "WRITE_WR_ADDR", "d": wr_wraddr_decode, "u": {"sha_wraddr": wraddr_update}})
        
        # WRITE_LEN
        wr_len_decode = self.and_op(
            self.and_op(self.eq(cmd, const_2_cmd), self.uge(cmdaddr, sha_len)),
            self.ugt(sha_len_plus2, cmdaddr)
        )
        is_high_byte_len = self.eq(cmdaddr, sha_len_plus1)
        is_low_byte_len = self.eq(cmdaddr, sha_len)
        high_byte_len = self.ite(is_high_byte_len, cmddata, self.extract(oplen, 15, 8))
        low_byte_len = self.ite(is_low_byte_len, cmddata, self.extract(oplen, 7, 0))
        new_oplen = self.concat(high_byte_len, low_byte_len)
        oplen_update = self.ite(is_status_idle, new_oplen, oplen)
        instructions.append({"n": "WRITE_LEN", "d": wr_len_decode, "u": {"sha_len": oplen_update}})
        
        # READ_RD_ADDR, READ_WR_ADDR, READ_LEN
        rd_rdaddr_decode = self.and_op(
            self.and_op(self.eq(cmd, const_1_cmd), self.uge(cmdaddr, sha_rd_addr)),
            self.ugt(sha_rd_addr_plus2, cmdaddr)
        )
        dataout_rdaddr = self.slice_read(rdaddr, cmdaddr, SHA_RD_ADDR, 2, 8)
        instructions.append({"n": "READ_RD_ADDR", "d": rd_rdaddr_decode, "u": {"dataout": dataout_rdaddr}})
        
        rd_wraddr_decode = self.and_op(
            self.and_op(self.eq(cmd, const_1_cmd), self.uge(cmdaddr, sha_wr_addr)),
            self.ugt(sha_wr_addr_plus2, cmdaddr)
        )
        dataout_wraddr = self.slice_read(wraddr, cmdaddr, SHA_WR_ADDR, 2, 8)
        instructions.append({"n": "READ_WR_ADDR", "d": rd_wraddr_decode, "u": {"dataout": dataout_wraddr}})
        
        rd_len_decode = self.and_op(
            self.and_op(self.eq(cmd, const_1_cmd), self.uge(cmdaddr, sha_len)),
            self.ugt(sha_len_plus2, cmdaddr)
        )
        dataout_len = self.slice_read(oplen, cmdaddr, SHA_LEN, 2, 8)
        instructions.append({"n": "READ_LEN", "d": rd_len_decode, "u": {"dataout": dataout_len}})
        
        # Instruction 7: START_SHA with child function call
        print("Creating START_SHA with child function call...")
        start_decode = self.and_op(
            self.and_op(self.eq(cmd, const_2_cmd), self.eq(cmdaddr, sha_start)),
            self.eq(cmddata, const_1_data)
        )
        
        # Load 64 bytes (512 bits) from XRAM starting at rdaddr
        # Build 16 x 32-bit words for block input
        block_words = []
        for i in range(16):
            # Each 32-bit word is 4 bytes (big-endian)
            offset_base = i * 4
            byte0 = self.load(xram, self.const(offset_base + 0, 16))
            byte1 = self.load(xram, self.const(offset_base + 1, 16))
            byte2 = self.load(xram, self.const(offset_base + 2, 16))
            byte3 = self.load(xram, self.const(offset_base + 3, 16))
            word = self.concat(byte0, byte1, byte2, byte3)
            block_words.append(word)
        
        # SHA-1 initial hash values as constants
        h_init = [self.const(h, 32) for h in H_INIT]
        
        # Declare child function: sha1_compress returns 160-bit hash
        sha1_func = self.declare_func("sha1_compress", 160)
        
        # Apply function: sha1_compress(block[0..15], H[0..4])
        # Function takes 21 arguments: 16 block words + 5 hash words
        hash_result = self.apply_func(sha1_func, *(block_words + h_init))
        
        # Extract 5 x 32-bit words from 160-bit result
        h0_out = self.extract(hash_result, 159, 128)
        h1_out = self.extract(hash_result, 127, 96)
        h2_out = self.extract(hash_result, 95, 64)
        h3_out = self.extract(hash_result, 63, 32)
        h4_out = self.extract(hash_result, 31, 0)
        
        # Store results to XRAM at wraddr
        # Store as 20 bytes (5 x 32-bit words, big-endian)
        xram_updated = xram
        for i, h_word in enumerate([h0_out, h1_out, h2_out, h3_out, h4_out]):
            offset_base = i * 4
            byte0 = self.extract(h_word, 31, 24)
            byte1 = self.extract(h_word, 23, 16)
            byte2 = self.extract(h_word, 15, 8)
            byte3 = self.extract(h_word, 7, 0)
            
            xram_updated = self.store(xram_updated, self.const(offset_base + 0, 16), byte0)
            xram_updated = self.store(xram_updated, self.const(offset_base + 1, 16), byte1)
            xram_updated = self.store(xram_updated, self.const(offset_base + 2, 16), byte2)
            xram_updated = self.store(xram_updated, self.const(offset_base + 3, 16), byte3)
        
        state_update = self.ite(is_status_idle, const_active, state)
        
        instructions.append({
            "n": "START_SHA",
            "d": start_decode,
            "u": {
                "sha_state": state_update,
                "XRAM": xram_updated
            }
        })
        
        print(f"  Created {len(instructions)} instructions")
        print(f"  Total expressions: {len(self.exprs)}")
        
        # Build JSON structure
        result = {
            "a": self.exprs,
            "t": {
                "n": "SHA",
                "s": self.state_ids,
                "f": fetch_expr,
                "v": valid_expr,
                "instr": instructions
            }
        }
        
        return result


def main():
    gen = SHAFullGenerator()
    parent_json = gen.generate()
    
    # Load child ILA
    with open("test_data/sha1_function.json") as f:
        child_json = json.load(f)
    
    # Create combined structure with child reference
    combined = {
        "a": parent_json['a'],
        "t": parent_json['t'],
        "c": [{
            "a": child_json['a'],
            "t": child_json['t']
        }]
    }
    
    output_file = "test_data/sha_full.json"
    with open(output_file, 'w') as f:
        json.dump(combined, f, indent=2)
    
    print(f"\n✓ Saved full SHA parent+child to {output_file}")
    print(f"  Parent expressions: {len(parent_json['a'])}")
    print(f"  Parent instructions: {len(parent_json['t']['instr'])}")
    print(f"  Child expressions: {len(child_json['a'])}")
    print(f"  Child instructions: {len(child_json['t']['instr'])}")


if __name__ == "__main__":
    main()
