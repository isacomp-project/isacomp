#!/bin/bash

# Compile all MIPS32 ISA tests

TESTS="add addi addiu addu and andi beq bne j jal jalr jr lb lbu lh lhu lui lw nor or ori sb sh sll sllv slt slti sltiu sltu sra srav srl srlv sub subu sw xor xori"

for test in $TESTS; do
    echo -n "Compiling $test... "

    if [ ! -f "$test.S" ]; then
        echo "SKIP (no source)"
        continue
    fi

    # Compile (--build-id=none prevents .note section from occupying address 0)
    # Use -EL for little-endian (matches our Verilog memory layout)
    mips-linux-gnu-gcc -EL -mno-abicalls -fno-pic -march=mips32 -nostdlib -Wl,--build-id=none -T linker.ld -I. "$test.S" -o "$test.elf" 2>&1
    if [ $? -ne 0 ]; then
        echo "COMPILE FAILED"
        continue
    fi

    # Convert to Intel HEX
    mips-linux-gnu-objcopy -O ihex "$test.elf" "mips32-isacomp-$test.hex"
    if [ $? -ne 0 ]; then
        echo "HEX CONVERT FAILED"
        continue
    fi

    # Get pass/fail addresses
    PASS_ADDR=$(mips-linux-gnu-nm "$test.elf" | grep ' pass$' | awk '{print $1}')
    FAIL_ADDR=$(mips-linux-gnu-nm "$test.elf" | grep ' fail$' | awk '{print $1}')

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        echo "ADDR EXTRACT FAILED"
        continue
    fi

    echo "$PASS_ADDR $FAIL_ADDR" > "mips32-isacomp-$test.addrs"
    echo "OK (pass=$PASS_ADDR fail=$FAIL_ADDR)"
done

echo ""
echo "Done. Run tests with: cd ../examples/verilog/mips32_complete && ./run_mips_tests.sh"
