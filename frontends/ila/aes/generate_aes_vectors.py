#!/usr/bin/env python3
"""
Generate random AES-128 test vectors using OpenSSL.
"""

import subprocess
import sys

def aes_encrypt(plaintext_hex, key_hex):
    """
    Encrypt using OpenSSL command line.
    Returns ciphertext as hex string.
    """
    # OpenSSL expects hex input without '0x' prefix
    cmd = [
        'openssl', 'enc', '-aes-128-ecb',
        '-K', key_hex,
        '-nosalt',
        '-nopad',
        '-in', '/dev/stdin',
        '-out', '/dev/stdout'
    ]

    # Convert hex string to bytes
    plaintext_bytes = bytes.fromhex(plaintext_hex)

    result = subprocess.run(
        cmd,
        input=plaintext_bytes,
        capture_output=True
    )

    if result.returncode != 0:
        print(f"Error: {result.stderr.decode()}", file=sys.stderr)
        return None

    # Convert output bytes to hex string
    return result.stdout.hex()

def main():
    print("Generating AES-128 Test Vectors using OpenSSL")
    print("=" * 80)

    vectors = []

    # Test 1: NIST FIPS 197 Appendix B
    plaintext = '3243f6a8885a308d313198a2e0370734'
    key = '2b7e151628aed2a6abf7158809cf4f3c'
    ciphertext = aes_encrypt(plaintext, key)
    vectors.append(("NIST FIPS 197 Appendix B", plaintext, key, ciphertext))

    # Test 2: All zeros
    plaintext = '00000000000000000000000000000000'
    key = '00000000000000000000000000000000'
    ciphertext = aes_encrypt(plaintext, key)
    vectors.append(("All zeros", plaintext, key, ciphertext))

    # Test 3: All ones
    plaintext = 'ffffffffffffffffffffffffffffffff'
    key = 'ffffffffffffffffffffffffffffffff'
    ciphertext = aes_encrypt(plaintext, key)
    vectors.append(("All ones", plaintext, key, ciphertext))

    # Test 4: Sequential pattern
    plaintext = '00112233445566778899aabbccddeeff'
    key = '000102030405060708090a0b0c0d0e0f'
    ciphertext = aes_encrypt(plaintext, key)
    vectors.append(("Sequential pattern", plaintext, key, ciphertext))

    # Test 5: Random hex pattern
    plaintext = 'deadbeefcafebabe0123456789abcdef'
    key = '0f0e0d0c0b0a09080706050403020100'
    ciphertext = aes_encrypt(plaintext, key)
    vectors.append(("Random hex pattern", plaintext, key, ciphertext))

    # Test 6: Single bit set in plaintext
    plaintext = '80000000000000000000000000000000'
    key = '00000000000000000000000000000000'
    ciphertext = aes_encrypt(plaintext, key)
    vectors.append(("Single bit plaintext", plaintext, key, ciphertext))

    # Test 7: Single bit set in key
    plaintext = '00000000000000000000000000000000'
    key = '80000000000000000000000000000000'
    ciphertext = aes_encrypt(plaintext, key)
    vectors.append(("Single bit key", plaintext, key, ciphertext))

    # Test 8: ASCII "Hello, AES-128!!" (hex encoded)
    plaintext = '48656c6c6f2c204145532d31323821'  # "Hello, AES-128!!" (15 bytes)
    plaintext = plaintext + '21'  # Pad to 16 bytes with '!'
    key = '4d7953656372657442657931323334'  # "MySecretKey1234" (15 bytes)
    key = key + '35'  # Pad to 16 bytes with '5'
    ciphertext = aes_encrypt(plaintext, key)
    vectors.append(("ASCII text", plaintext, key, ciphertext))

    # Print vectors
    print("\nGenerated Test Vectors:")
    print("=" * 80)
    for i, (name, pt, k, ct) in enumerate(vectors, 1):
        print(f"\nTest {i}: {name}")
        print(f"  Plaintext:  128'h{pt}")
        print(f"  Key:        128'h{k}")
        print(f"  Ciphertext: 128'h{ct}")

    # Save to file for testbench generation
    with open('aes_test_vectors.txt', 'w') as f:
        for i, (name, pt, k, ct) in enumerate(vectors, 1):
            f.write(f"{i}|{name}|{pt}|{k}|{ct}\n")

    print("\n" + "=" * 80)
    print(f"✓ Generated {len(vectors)} test vectors")
    print("✓ Saved to aes_test_vectors.txt")

    return 0

if __name__ == '__main__':
    sys.exit(main())
