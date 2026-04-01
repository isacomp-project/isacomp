#!/usr/bin/env python3
"""
Generate SHA-1 test vectors using Python's hashlib.
"""

import hashlib
import sys

def sha1_hash(data_bytes):
    """Calculate SHA-1 hash of data."""
    return hashlib.sha1(data_bytes).digest()

def bytes_to_hex(data):
    """Convert bytes to hex string."""
    return data.hex()

def pad_message(message_bytes):
    """
    Pad message according to SHA-1 specification.
    Returns a list of 512-bit (64-byte) blocks.
    """
    msg_len = len(message_bytes)
    msg_bit_len = msg_len * 8

    # Append 0x80 byte
    padded = bytearray(message_bytes)
    padded.append(0x80)

    # Append zeros until length ≡ 448 (mod 512) bits = 56 (mod 64) bytes
    while len(padded) % 64 != 56:
        padded.append(0)

    # Append original length as 64-bit big-endian integer
    padded.extend(msg_bit_len.to_bytes(8, 'big'))

    # Split into 512-bit blocks
    blocks = []
    for i in range(0, len(padded), 64):
        block = padded[i:i+64]
        blocks.append(block)

    return blocks

def main():
    print("Generating SHA-1 Test Vectors")
    print("=" * 80)

    vectors = []

    # Test 1: Empty string
    message = b""
    blocks = pad_message(message)
    digest = sha1_hash(message)
    vectors.append(("Empty string", message, blocks, digest))

    # Test 2: "abc"
    message = b"abc"
    blocks = pad_message(message)
    digest = sha1_hash(message)
    vectors.append(("abc", message, blocks, digest))

    # Test 3: "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"
    message = b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"
    blocks = pad_message(message)
    digest = sha1_hash(message)
    vectors.append(("NIST test vector", message, blocks, digest))

    # Test 4: "The quick brown fox jumps over the lazy dog"
    message = b"The quick brown fox jumps over the lazy dog"
    blocks = pad_message(message)
    digest = sha1_hash(message)
    vectors.append(("Quick brown fox", message, blocks, digest))

    # Test 5: All zeros (one block)
    message = b"\x00" * 55  # Fits in one block after padding
    blocks = pad_message(message)
    digest = sha1_hash(message)
    vectors.append(("55 zero bytes", message, blocks, digest))

    # Test 6: All ones
    message = b"\xff" * 55
    blocks = pad_message(message)
    digest = sha1_hash(message)
    vectors.append(("55 0xFF bytes", message, blocks, digest))

    # Test 7: Sequential pattern
    message = bytes(range(55))
    blocks = pad_message(message)
    digest = sha1_hash(message)
    vectors.append(("Sequential 0-54", message, blocks, digest))

    # Print vectors
    print("\nGenerated Test Vectors:")
    print("=" * 80)

    for i, (name, msg, blks, dig) in enumerate(vectors, 1):
        print(f"\nTest {i}: {name}")
        print(f"  Message: {bytes_to_hex(msg)[:60]}{'...' if len(msg) > 30 else ''}")
        print(f"  Message length: {len(msg)} bytes")
        print(f"  Number of blocks: {len(blks)}")
        if len(blks) > 0:
            # Show first block in 512-bit format
            block_hex = bytes_to_hex(blks[0])
            print(f"  First block (512 bits):")
            print(f"    {block_hex}")
        print(f"  Expected digest (160 bits):")
        print(f"    {bytes_to_hex(dig)}")

    # Save to file
    with open('sha1_test_vectors.txt', 'w') as f:
        for i, (name, msg, blks, dig) in enumerate(vectors, 1):
            f.write(f"{i}|{name}|{bytes_to_hex(msg)}|")
            for j, blk in enumerate(blks):
                f.write(f"{bytes_to_hex(blk)}")
                if j < len(blks) - 1:
                    f.write(";")
            f.write(f"|{bytes_to_hex(dig)}\n")

    print("\n" + "=" * 80)
    print(f"✓ Generated {len(vectors)} test vectors")
    print("✓ Saved to sha1_test_vectors.txt")

    # Generate Verilog snippet for testbench
    print("\n" + "=" * 80)
    print("Verilog testbench code snippets:")
    print("=" * 80)

    for i, (name, msg, blks, dig) in enumerate(vectors, 1):
        if len(blks) == 1:  # Only show single-block examples for brevity
            block_hex = bytes_to_hex(blks[0])
            digest_hex = bytes_to_hex(dig)
            print(f"""
// Test {i}: {name}
test_block = 512'h{block_hex};
expected_digest = 160'h{digest_hex};
run_test("{name}");
""")

    return 0

if __name__ == '__main__':
    sys.exit(main())
