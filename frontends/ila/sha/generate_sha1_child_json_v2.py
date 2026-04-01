#!/usr/bin/env python3
"""
Generate SHA-1 child ILA JSON with proper message schedule expansion.
This version implements W[0..79] properly.
"""

import json

# ILAng operation codes (from ila_opcodes.py)
OP_AND = 4
OP_OR = 5
OP_XOR = 6
OP_NOT = 2  # Logical NOT (!)
OP_COMPL = 3  # Bitwise complement (~)
OP_LSHL = 7  # Shift left
OP_LSHR = 9
OP_ADD = 10
OP_EQ = 13
OP_GT = 15
# Note: No OP_ULE - we synthesize a <= b as !(a > b)
OP_CONCAT = 20
OP_EXTRACT = 21
OP_ITE = 26


class SHA1ChildJSONGenerator:
    def __init__(self):
        self.next_id = 1000
        self.exprs = []
        self.state_map = {}
        self.state_ids = []  # Track state IDs for the 's' list

    def alloc_id(self):
        id_val = self.next_id
        self.next_id += 1
        return id_val

    def const(self, value, width):
        """Create constant"""
        expr_id = self.alloc_id()
        self.exprs.append({
            "i": expr_id,
            "s": {"u": 2, "w": width},
            "u": 2,
            "v": {"v": value}
        })
        return expr_id

    def state(self, name, width):
        """Create state"""
        state_id = self.alloc_id()
        self.exprs.append({
            "i": state_id,
            "n": name,
            "s": {"u": 2, "w": width},
            "u": 1
        })
        self.state_map[name] = state_id
        self.state_ids.append(state_id)  # Track for 's' list
        return state_id

    def input_state(self, name, width):
        """Create input state"""
        input_id = self.alloc_id()
        self.exprs.append({
            "i": input_id,
            "n": name,
            "s": {"u": 2, "w": width},
            "u": 1  # Input states are type 1 like regular states
        })
        self.state_map[name] = input_id
        self.state_ids.append(input_id)  # Track for 's' list
        return input_id

    def op(self, opcode, args, params=None):
        """Create operation"""
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

    def concat(self, a, b):
        return self.op(OP_CONCAT, [a, b])

    def eq(self, a, b):
        return self.op(OP_EQ, [a, b])

    def and_op(self, a, b):
        return self.op(OP_AND, [a, b])

    def or_op(self, a, b):
        return self.op(OP_OR, [a, b])

    def xor(self, a, b):
        return self.op(OP_XOR, [a, b])

    def not_op(self, a):
        return self.op(OP_NOT, [a])

    def add(self, a, b):
        return self.op(OP_ADD, [a, b])

    def gt(self, a, b):
        return self.op(OP_GT, [a, b])

    def ule(self, a, b):
        # ULE (a <= b) = !(a > b)  -- ILAng doesn't have <=, synthesize it
        return self.not_op(self.op(OP_GT, [a, b]))

    def lshl(self, a, b):
        return self.op(OP_LSHL, [a, b])  # Shift left

    def lshr(self, a, b):
        return self.op(OP_LSHR, [a, b])

    def ite(self, cond, true_val, false_val):
        return self.op(OP_ITE, [cond, true_val, false_val])

    def rotl(self, x, n, width=32):
        """Rotate left: (x << n) | (x >> (32-n))"""
        shift_left = self.const(n, width)
        shift_right = self.const(width - n, width)
        left = self.lshl(x, shift_left)
        right = self.lshr(x, shift_right)
        return self.or_op(left, right)

    def ch(self, x, y, z):
        """Ch(x,y,z) = (x & y) | (~x & z)"""
        xy = self.and_op(x, y)
        not_x = self.op(OP_COMPL, [x])  # Bitwise complement ~
        not_x_z = self.and_op(not_x, z)
        return self.or_op(xy, not_x_z)

    def parity(self, x, y, z):
        """Parity(x,y,z) = x ^ y ^ z"""
        xy = self.xor(x, y)
        return self.xor(xy, z)

    def maj(self, x, y, z):
        """Maj(x,y,z) = (x & y) | (x & z) | (y & z)"""
        xy = self.and_op(x, y)
        xz = self.and_op(x, z)
        yz = self.and_op(y, z)
        xy_xz = self.or_op(xy, xz)
        return self.or_op(xy_xz, yz)

    def select_w(self, W_array, round_ctr, round_num):
        """Select W[round_num] using ITE chain"""
        # W[round_num] is selected when round == round_num + 1
        # (since round 1 uses W[0], round 2 uses W[1], etc.)
        round_const = self.const(round_num + 1, 7)
        is_this_round = self.eq(round_ctr, round_const)
        return is_this_round, W_array[round_num]

    def create_w_selector(self, W_array, round_ctr, start_idx, end_idx, round_offset):
        """Create ITE chain to select W[start_idx..end_idx] based on round

        Args:
            W_array: Array of W state IDs
            round_ctr: Round counter state ID
            start_idx: First W index to select from
            end_idx: Last W index to select from
            round_offset: Round number when start_idx should be selected
                         (e.g., 65 means W[start_idx] is used in round 65)
        """
        # Build ITE chain: cond ? W[i] : (next_ite)
        result = W_array[end_idx]  # Default to last one

        for i in range(end_idx - 1, start_idx - 1, -1):
            # W[i] should be selected when round == round_offset + (i - start_idx)
            round_for_w_i = round_offset + (i - start_idx)
            round_const = self.const(round_for_w_i, 8)
            is_this_round = self.eq(round_ctr, round_const)
            result = self.ite(is_this_round, W_array[i], result)

        return result

    def generate(self):
        print("Generating SHA-1 child ILA JSON with proper message schedule...")

        # Create states
        print("Creating states...")

        # Input: 512-bit block (16 x 32-bit words)
        block = [self.input_state(f"block_{i}", 32) for i in range(16)]

        # Input: Previous hash state (5 x 32-bit words)
        H0_in = self.input_state("H0_in", 32)
        H1_in = self.input_state("H1_in", 32)
        H2_in = self.input_state("H2_in", 32)
        H3_in = self.input_state("H3_in", 32)
        H4_in = self.input_state("H4_in", 32)

        # Working variables
        a = self.state("a", 32)
        b = self.state("b", 32)
        c = self.state("c", 32)
        d = self.state("d", 32)
        e = self.state("e", 32)

        # Message schedule W[0..79]
        W = [self.state(f"W_{i}", 32) for i in range(80)]

        # Round counter (need 8 bits for 0-146)
        round_ctr = self.state("round", 8)

        # Output hash state
        H0_out = self.state("H0_out", 32)
        H1_out = self.state("H1_out", 32)
        H2_out = self.state("H2_out", 32)
        H3_out = self.state("H3_out", 32)
        H4_out = self.state("H4_out", 32)

        print(f"  Created {len([e for e in self.exprs if e.get('u') == 1])} states")

        # Create constants (8-bit for round counter)
        print("Creating constants...")
        const_0 = self.const(0, 8)
        const_1 = self.const(1, 8)
        const_16 = self.const(16, 8)
        const_20 = self.const(20, 8)
        const_40 = self.const(40, 8)
        const_60 = self.const(60, 8)
        const_80 = self.const(80, 8)
        const_81 = self.const(81, 8)

        # K constants
        k_0_19 = self.const(0x5A827999, 32)
        k_20_39 = self.const(0x6ED9EBA1, 32)
        k_40_59 = self.const(0x8F1BBCDC, 32)
        k_60_79 = self.const(0xCA62C1D6, 32)

        print("Creating instruction decode conditions and updates...")

        # Instruction 1: InitRound (round == 0)
        # Initialize working vars and W[0..15] from block
        init_decode = self.eq(round_ctr, const_0)
        init_updates = {
            "a": H0_in,
            "b": H1_in,
            "c": H2_in,
            "d": H3_in,
            "e": H4_in,
            "round": self.add(round_ctr, const_1)
        }
        # Initialize W[0..15] from block
        for i in range(16):
            init_updates[f"W_{i}"] = block[i]

        # Instruction 2: ExpandSchedule (1 <= round <= 64)
        # Compute W[16..79] incrementally
        expand_cond1 = self.gt(round_ctr, const_0)
        expand_cond2 = self.ule(round_ctr, self.const(64, 8))
        expand_decode = self.and_op(expand_cond1, expand_cond2)

        expand_updates = {"round": self.add(round_ctr, const_1)}

        # For each W[16..79], compute when round == i-15
        # W[i] = ROTL((W[i-3] ^ W[i-8] ^ W[i-14] ^ W[i-16]), 1)
        for i in range(16, 80):
            round_for_this_w = self.const(i - 15, 8)
            should_update = self.eq(round_ctr, round_for_this_w)

            # Compute new W value
            w_i_3 = W[i - 3]
            w_i_8 = W[i - 8]
            w_i_14 = W[i - 14]
            w_i_16 = W[i - 16]

            xor1 = self.xor(w_i_3, w_i_8)
            xor2 = self.xor(xor1, w_i_14)
            xor3 = self.xor(xor2, w_i_16)
            rotated = self.rotl(xor3, 1, 32)

            # Update W[i] conditionally
            expand_updates[f"W_{i}"] = self.ite(should_update, rotated, W[i])

        # Round instructions helper
        def create_round_updates(f_func, k_const, start_round, end_round):
            """Create update expressions for a round using W selector"""
            # Select appropriate W based on current round
            # Round 65 uses W[0], round 66 uses W[1], etc.
            w_idx_start = start_round - 65
            w_idx_end = end_round - 65
            w_value = self.create_w_selector(W, round_ctr, w_idx_start, w_idx_end, start_round)

            rotl_a_5 = self.rotl(a, 5, 32)
            sum1 = self.add(rotl_a_5, f_func)
            sum2 = self.add(sum1, e)
            sum3 = self.add(sum2, k_const)
            temp = self.add(sum3, w_value)

            return {
                "a": temp,
                "b": a,
                "c": self.rotl(b, 30, 32),
                "d": c,
                "e": d,
                "round": self.add(round_ctr, const_1)
            }

        # Rounds 65-84 (SHA rounds 1-20): Ch function
        cond1 = self.gt(round_ctr, self.const(64, 8))
        cond2 = self.ule(round_ctr, self.const(84, 8))
        decode_65_84 = self.and_op(cond1, cond2)
        f_ch = self.ch(b, c, d)
        round_65_84_updates = create_round_updates(f_ch, k_0_19, 65, 84)

        # Rounds 85-104 (SHA rounds 21-40): Parity function
        cond1 = self.gt(round_ctr, self.const(84, 8))
        cond2 = self.ule(round_ctr, self.const(104, 8))
        decode_85_104 = self.and_op(cond1, cond2)
        f_par1 = self.parity(b, c, d)
        round_85_104_updates = create_round_updates(f_par1, k_20_39, 85, 104)

        # Rounds 105-124 (SHA rounds 41-60): Maj function
        cond1 = self.gt(round_ctr, self.const(104, 8))
        cond2 = self.ule(round_ctr, self.const(124, 8))
        decode_105_124 = self.and_op(cond1, cond2)
        f_maj = self.maj(b, c, d)
        round_105_124_updates = create_round_updates(f_maj, k_40_59, 105, 124)

        # Rounds 125-144 (SHA rounds 61-80): Parity function again
        cond1 = self.gt(round_ctr, self.const(124, 8))
        cond2 = self.ule(round_ctr, self.const(144, 8))
        decode_125_144 = self.and_op(cond1, cond2)
        f_par2 = self.parity(b, c, d)
        round_125_144_updates = create_round_updates(f_par2, k_60_79, 125, 144)

        # Instruction 7: Finalize (round == 145)
        final_decode = self.eq(round_ctr, self.const(145, 8))
        final_updates = {
            "H0_out": self.add(H0_in, a),
            "H1_out": self.add(H1_in, b),
            "H2_out": self.add(H2_in, c),
            "H3_out": self.add(H3_in, d),
            "H4_out": self.add(H4_in, e),
            "round": self.add(round_ctr, const_1)
        }

        print(f"  Total expressions: {len(self.exprs)}")

        # Build JSON structure
        result = {
            "a": self.exprs,
            "t": {
                "n": "sha1_compress",
                "s": self.state_ids,  # Add state list
                "instr": [
                    {"n": "InitRound", "d": init_decode, "u": init_updates},
                    {"n": "ExpandSchedule", "d": expand_decode, "u": expand_updates},
                    {"n": "Round_1_20", "d": decode_65_84, "u": round_65_84_updates},
                    {"n": "Round_21_40", "d": decode_85_104, "u": round_85_104_updates},
                    {"n": "Round_41_60", "d": decode_105_124, "u": round_105_124_updates},
                    {"n": "Round_61_80", "d": decode_125_144, "u": round_125_144_updates},
                    {"n": "Finalize", "d": final_decode, "u": final_updates}
                ]
            }
        }

        return result


def main():
    gen = SHA1ChildJSONGenerator()
    ila_json = gen.generate()

    output_file = "test_data/sha1_function.json"

    with open(output_file, 'w') as f:
        json.dump(ila_json, f, indent=2)

    print(f"\n✓ Saved SHA-1 child ILA to {output_file}")
    print(f"  States: {len([e for e in ila_json['a'] if e.get('u') == 1])}")
    print(f"  Expressions: {len(ila_json['a'])}")
    print(f"  Instructions: {len(ila_json['t']['instr'])}")


if __name__ == "__main__":
    main()
