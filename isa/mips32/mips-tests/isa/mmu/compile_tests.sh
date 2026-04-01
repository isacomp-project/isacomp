#!/bin/bash
# Compile MIPS32 MMU tests

# Check for MIPS cross-compiler
MIPS_GCC=${MIPS_GCC:-mips-linux-gnu-gcc}
MIPS_OBJCOPY=${MIPS_OBJCOPY:-mips-linux-gnu-objcopy}
MIPS_NM=${MIPS_NM:-mips-linux-gnu-nm}

if ! command -v $MIPS_GCC &> /dev/null; then
    echo "ERROR: $MIPS_GCC not found. Install with: apt install gcc-mips-linux-gnu"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Common flags for MIPS32 little-endian
CFLAGS="-EL -mips32 -nostdlib -nostartfiles -static -mno-abicalls -fno-pic -mabi=32"
LDFLAGS="-T../linker.ld"

# Tests to compile
# Original tests + new translation verification tests
TESTS="cp0 tlbwi tlbp mult llsc branch linux_boot_demo uart_test translation_verify translation_multi translation_oddeven translation_subword translation_kseg"

PASS=0
FAIL=0

for test in $TESTS; do
    echo -n "Compiling $test... "

    if [ ! -f "${test}.S" ]; then
        echo "SKIP (no source)"
        continue
    fi

    # Compile to ELF
    $MIPS_GCC $CFLAGS $LDFLAGS -o mips32-mmu-${test}.elf ${test}.S -I. -I..
    if [ $? -ne 0 ]; then
        echo "FAIL (compile)"
        FAIL=$((FAIL + 1))
        continue
    fi

    # Convert to Intel HEX
    $MIPS_OBJCOPY -O ihex mips32-mmu-${test}.elf mips32-mmu-${test}.hex
    if [ $? -ne 0 ]; then
        echo "FAIL (objcopy)"
        FAIL=$((FAIL + 1))
        continue
    fi

    # Extract pass/fail addresses
    PASS_ADDR=$($MIPS_NM mips32-mmu-${test}.elf | grep " pass$" | awk '{print $1}')
    FAIL_ADDR=$($MIPS_NM mips32-mmu-${test}.elf | grep " fail$" | awk '{print $1}')

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        echo "FAIL (symbols)"
        FAIL=$((FAIL + 1))
        continue
    fi

    echo "$PASS_ADDR $FAIL_ADDR" > mips32-mmu-${test}.addrs

    echo "OK (pass=0x$PASS_ADDR fail=0x$FAIL_ADDR)"
    PASS=$((PASS + 1))
done

echo ""
echo "================================"
echo "Compiled: $PASS succeeded, $FAIL failed"
echo "================================"
