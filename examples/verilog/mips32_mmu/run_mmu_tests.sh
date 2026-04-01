#!/bin/bash

# Test all MIPS32 MMU instructions using the single-cycle processor
# Supports both iverilog and verilator simulators

SIMULATOR=${SIMULATOR:-iverilog}

echo "MIPS32 MMU Test Suite"
echo "====================="
echo "Simulator: $SIMULATOR"
echo ""

# Compile testbench
echo "Compiling testbench..."

if [ "$SIMULATOR" = "verilator" ]; then
    if [ ! -f "test_simple" ] || [ "mips32_mmu.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
        verilator --timing --exe --binary \
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \
            -o test_simple mips32_mmu.v simple_tb.sv
        if [ $? -ne 0 ]; then
            echo "ERROR: Verilator compilation failed!"
            exit 1
        fi
        mv obj_dir/test_simple . 2>/dev/null || true
    fi
    TEST_CMD="./test_simple"
else
    if [ ! -f "test_simple" ] || [ "mips32_mmu.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
        iverilog -g2012 -o test_simple mips32_mmu.v simple_tb.sv
        if [ $? -ne 0 ]; then
            echo "ERROR: Icarus Verilog compilation failed!"
            exit 1
        fi
    fi
    TEST_CMD="vvp test_simple"
fi

# Create empty rf.hex (register file starts at zero)
python3 -c "
with open('rf.hex', 'w') as f:
    for i in range(32):
        f.write('00000000\n')
"

# Create TLB memory files with complex page table setup for thorough testing
# Each TLB entry maps 8KB (2 x 4KB pages)
# EntryHi: [31:13]=VPN2, [7:0]=ASID
# EntryLo: [25:6]=PFN, [5:3]=C (cache coherency), [2]=D (dirty/writable), [1]=V (valid), [0]=G (global)
#
# TLB Configuration:
# ==================
# Entries 0-7:   Identity mapping, Global (G=1) - essential for test code execution
# Entries 8-11:  Non-identity mapping (VPN2 -> PFN+16), Global - tests address translation
# Entries 12-15: Different cache coherency values (C=0,1,2,3), Global
# Entries 16-19: ASID-specific (ASID=0, G=0) - tests ASID matching
# Entries 20-23: Large offset mapping (VPN2 -> PFN+64), Global - tests large translations
# Entries 24-27: Read-only pages (D=0), Global - tests write protection
# Entries 28-30: Invalid odd page (V=0 in Lo1) - tests TLB invalid exceptions
# Entry 31:      High address mapping (VPN2=0x1000 -> PFN=0), Global - tests high kuseg
#
python3 -c "
# Complex TLB page table configuration
tlb_hi = []
tlb_lo0 = []
tlb_lo1 = []

for i in range(32):
    if i < 8:
        # Entries 0-7: Identity mapping, Global
        # VPN2=i, ASID=0, maps to PFN=i*2 and i*2+1
        vpn2 = i
        asid = 0
        pfn0 = i * 2
        pfn1 = i * 2 + 1
        c = 0  # Uncached
        d = 1  # Writable
        v = 1  # Valid
        g = 1  # Global

    elif i < 12:
        # Entries 8-11: Non-identity mapping with +16 page offset
        # VPN2=i maps to PFN=(i+16)*2 and (i+16)*2+1
        vpn2 = i
        asid = 0
        pfn0 = (i + 16) * 2  # Offset by 16 8KB regions = 128KB
        pfn1 = (i + 16) * 2 + 1
        c = 0
        d = 1
        v = 1
        g = 1

    elif i < 16:
        # Entries 12-15: Different cache coherency values
        # VPN2=i, varying C field (0-3)
        vpn2 = i
        asid = 0
        pfn0 = i * 2
        pfn1 = i * 2 + 1
        c = i - 12  # C = 0, 1, 2, 3
        d = 1
        v = 1
        g = 1

    elif i < 20:
        # Entries 16-19: ASID-specific (not global)
        # Only matches when cp0_entryhi ASID = 0
        vpn2 = i
        asid = 0  # Match ASID 0
        pfn0 = i * 2
        pfn1 = i * 2 + 1
        c = 0
        d = 1
        v = 1
        g = 0  # NOT global - requires ASID match

    elif i < 24:
        # Entries 20-23: Large offset mapping (+64 pages = 512KB offset)
        vpn2 = i
        asid = 0
        pfn0 = (i + 64) * 2
        pfn1 = (i + 64) * 2 + 1
        c = 0
        d = 1
        v = 1
        g = 1

    elif i < 28:
        # Entries 24-27: Read-only pages (D=0)
        # Tests TLB Modified exception on write attempts
        vpn2 = i
        asid = 0
        pfn0 = i * 2
        pfn1 = i * 2 + 1
        c = 0
        d = 0  # NOT dirty/writable
        v = 1
        g = 1

    elif i < 31:
        # Entries 28-30: Invalid odd page (tests TLB Invalid exception)
        vpn2 = i
        asid = 0
        pfn0 = i * 2
        pfn1 = i * 2 + 1
        c = 0
        d = 1
        v = 1  # Even page valid
        g = 1
        # Mark odd page as invalid below

    else:
        # Entry 31: High kuseg address mapping
        # Maps VPN2=0x1000 (virtual 0x02000000-0x02001FFF) to physical 0
        vpn2 = 0x1000  # Virtual address 32MB into kuseg
        asid = 0
        pfn0 = 0
        pfn1 = 1
        c = 0
        d = 1
        v = 1
        g = 1

    # Build EntryHi: VPN2[31:13], ASID[7:0]
    entry_hi = (vpn2 << 13) | asid

    # Build EntryLo0: PFN[25:6], C[5:3], D[2], V[1], G[0]
    entry_lo0 = (pfn0 << 6) | (c << 3) | (d << 2) | (v << 1) | g

    # Build EntryLo1: same structure
    if 28 <= i < 31:
        # Invalid odd page for entries 28-30
        entry_lo1 = (pfn1 << 6) | (c << 3) | (d << 2) | (0 << 1) | g  # V=0
    else:
        entry_lo1 = (pfn1 << 6) | (c << 3) | (d << 2) | (v << 1) | g

    tlb_hi.append(entry_hi)
    tlb_lo0.append(entry_lo0)
    tlb_lo1.append(entry_lo1)

# Write files
with open('tlb_hi.hex', 'w') as f:
    for val in tlb_hi:
        f.write(f'{val:08x}\n')

with open('tlb_lo0.hex', 'w') as f:
    for val in tlb_lo0:
        f.write(f'{val:08x}\n')

with open('tlb_lo1.hex', 'w') as f:
    for val in tlb_lo1:
        f.write(f'{val:08x}\n')

# Write CAM arrays for CAM-based TLB lookup
# tlb_vpn2[i] = tlb_hi[i][31:13] = VPN2 (19 bits)
# tlb_asid[i] = tlb_hi[i][7:0] = ASID (8 bits)
with open('tlb_vpn2.hex', 'w') as f:
    for val in tlb_hi:
        vpn2 = (val >> 13) & 0x7FFFF  # 19 bits
        f.write(f'{vpn2:05x}\n')

with open('tlb_asid.hex', 'w') as f:
    for val in tlb_hi:
        asid = val & 0xFF  # 8 bits
        f.write(f'{asid:02x}\n')

# Write separate field arrays for fetch without TLBR conflicts
# PFN0 from lo0[25:6], PFN1 from lo1[25:6]
with open('tlb_pfn0.hex', 'w') as f:
    for val in tlb_lo0:
        pfn = (val >> 6) & 0xFFFFF  # 20 bits
        f.write(f'{pfn:05x}\n')

with open('tlb_pfn1.hex', 'w') as f:
    for val in tlb_lo1:
        pfn = (val >> 6) & 0xFFFFF  # 20 bits
        f.write(f'{pfn:05x}\n')

# V0 from lo0[1], V1 from lo1[1]
with open('tlb_v0.hex', 'w') as f:
    for val in tlb_lo0:
        v = (val >> 1) & 1
        f.write(f'{v:x}\n')

with open('tlb_v1.hex', 'w') as f:
    for val in tlb_lo1:
        v = (val >> 1) & 1
        f.write(f'{v:x}\n')

# D0 from lo0[2], D1 from lo1[2]
with open('tlb_d0.hex', 'w') as f:
    for val in tlb_lo0:
        d = (val >> 2) & 1
        f.write(f'{d:x}\n')

with open('tlb_d1.hex', 'w') as f:
    for val in tlb_lo1:
        d = (val >> 2) & 1
        f.write(f'{d:x}\n')

# Global = lo0[0] & lo1[0]
with open('tlb_g.hex', 'w') as f:
    for i in range(len(tlb_lo0)):
        g = (tlb_lo0[i] & 1) & (tlb_lo1[i] & 1)
        f.write(f'{g:x}\n')

# Print summary for debugging
print('TLB Configuration Summary:')
print('Entry | VPN2    | ASID | PFN0  | PFN1  | C | D | V0 | V1 | G | Description')
print('-' * 85)
for i in range(32):
    hi = tlb_hi[i]
    lo0 = tlb_lo0[i]
    lo1 = tlb_lo1[i]
    vpn2 = hi >> 13
    asid = hi & 0xFF
    pfn0 = lo0 >> 6
    pfn1 = lo1 >> 6
    c = (lo0 >> 3) & 0x7
    d = (lo0 >> 2) & 1
    v0 = (lo0 >> 1) & 1
    v1 = (lo1 >> 1) & 1
    g = lo0 & 1

    if i < 8:
        desc = 'Identity, Global'
    elif i < 12:
        desc = 'Non-identity (+16 pages)'
    elif i < 16:
        desc = f'Cache C={c}'
    elif i < 20:
        desc = 'ASID-specific (G=0)'
    elif i < 24:
        desc = 'Large offset (+64 pages)'
    elif i < 28:
        desc = 'Read-only (D=0)'
    elif i < 31:
        desc = 'Invalid odd page (V1=0)'
    else:
        desc = 'High kuseg mapping'

    print(f'{i:5} | {vpn2:05x}   | {asid:4} | {pfn0:5} | {pfn1:5} | {c} | {d} | {v0:2} | {v1:2} | {g} | {desc}')
"

# MMU-specific tests (includes new translation verification tests)
MMU_TESTS="cp0 tlbwi tlbp mult llsc branch linux_boot_demo uart_test translation_verify translation_multi translation_oddeven translation_subword translation_kseg"

# Base instruction tests (reuse from mips32_complete)
BASE_TESTS="add addi addiu addu and andi beq bne j jal jalr jr lb lbu lh lhu lui lw nor or ori sb sh sll sllv slt slti sltiu sltu sra srav srl srlv sub subu sw xor xori"

PASS=0
FAIL=0
SKIP=0
FAILED_TESTS=""

# Run MMU-specific tests
echo ""
echo "Running MMU-specific tests..."
for test in $MMU_TESTS; do
    echo -n "Testing $test... "

    TEST_BASE="../../../isa/mips32/mips-tests/isa/mmu/mips32-mmu-$test"

    if [ ! -f "$TEST_BASE.hex" ]; then
        echo "SKIP (no hex file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    if [ ! -f "$TEST_BASE.addrs" ]; then
        echo "SKIP (no addrs file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    # Get pass/fail addresses
    read PASS_ADDR FAIL_ADDR < "$TEST_BASE.addrs"

    # Tests that run from kseg0 (need empty TLB or manage their own TLB)
    # Translation tests run from kseg0 to avoid TLB dependency for instruction fetch
    if [ "$test" = "tlbwi" ] || [ "$test" = "tlbp" ] || [ "$test" = "linux_boot_demo" ] || \
       [ "$test" = "translation_verify" ] || [ "$test" = "translation_multi" ] || \
       [ "$test" = "translation_oddeven" ] || [ "$test" = "translation_subword" ] || \
       [ "$test" = "translation_kseg" ]; then
        # Run from kseg0 - add 0x80000000 offset to addresses
        PASS_ADDR=$(printf '%08x' $((0x$PASS_ADDR + 0x80000000)))
        FAIL_ADDR=$(printf '%08x' $((0x$FAIL_ADDR + 0x80000000)))
        RESET_PC="80000000"
        # Use empty TLB for these tests
        python3 -c "
for name in ['tlb_hi.hex', 'tlb_lo0.hex', 'tlb_lo1.hex']:
    with open(name, 'w') as f:
        for i in range(32):
            f.write('00000000\n')
"
    else
        # Run from kuseg with complex TLB - regenerate for each test
        RESET_PC="0"
        python3 -c "
# Regenerate complex TLB configuration (same as initial setup)
tlb_hi = []
tlb_lo0 = []
tlb_lo1 = []

for i in range(32):
    if i < 8:
        vpn2, asid, pfn0, pfn1, c, d, v, g = i, 0, i*2, i*2+1, 0, 1, 1, 1
    elif i < 12:
        vpn2, asid, pfn0, pfn1, c, d, v, g = i, 0, (i+16)*2, (i+16)*2+1, 0, 1, 1, 1
    elif i < 16:
        vpn2, asid, pfn0, pfn1, c, d, v, g = i, 0, i*2, i*2+1, i-12, 1, 1, 1
    elif i < 20:
        vpn2, asid, pfn0, pfn1, c, d, v, g = i, 0, i*2, i*2+1, 0, 1, 1, 0
    elif i < 24:
        vpn2, asid, pfn0, pfn1, c, d, v, g = i, 0, (i+64)*2, (i+64)*2+1, 0, 1, 1, 1
    elif i < 28:
        vpn2, asid, pfn0, pfn1, c, d, v, g = i, 0, i*2, i*2+1, 0, 0, 1, 1
    elif i < 31:
        vpn2, asid, pfn0, pfn1, c, d, v, g = i, 0, i*2, i*2+1, 0, 1, 1, 1
    else:
        vpn2, asid, pfn0, pfn1, c, d, v, g = 0x1000, 0, 0, 1, 0, 1, 1, 1

    entry_hi = (vpn2 << 13) | asid
    entry_lo0 = (pfn0 << 6) | (c << 3) | (d << 2) | (v << 1) | g
    v1 = 0 if 28 <= i < 31 else v
    entry_lo1 = (pfn1 << 6) | (c << 3) | (d << 2) | (v1 << 1) | g

    tlb_hi.append(entry_hi)
    tlb_lo0.append(entry_lo0)
    tlb_lo1.append(entry_lo1)

with open('tlb_hi.hex', 'w') as f:
    for val in tlb_hi: f.write(f'{val:08x}\n')
with open('tlb_lo0.hex', 'w') as f:
    for val in tlb_lo0: f.write(f'{val:08x}\n')
with open('tlb_lo1.hex', 'w') as f:
    for val in tlb_lo1: f.write(f'{val:08x}\n')
"
    fi

    # Convert Intel HEX to umem.hex (strip kseg0 bits for physical address)
    python3 -c "
import sys
data = {}
ext_addr = 0  # Extended address from type 04 records
with open('$TEST_BASE.hex', 'r') as f:
    for line in f:
        line = line.strip()
        if not line.startswith(':'):
            continue
        byte_count = int(line[1:3], 16)
        address = int(line[3:7], 16)
        record_type = int(line[7:9], 16)
        if record_type == 0:
            full_addr = ext_addr + address
            # Convert kseg0/kseg1 address to physical (strip top 3 bits)
            if full_addr >= 0x80000000 and full_addr < 0xC0000000:
                phys_addr = full_addr & 0x1FFFFFFF
            else:
                phys_addr = full_addr
            for i in range(byte_count):
                byte_val = int(line[9+i*2:11+i*2], 16)
                data[phys_addr + i] = byte_val
        elif record_type == 1:
            break
        elif record_type == 4:
            # Extended linear address record
            ext_addr = int(line[9:13], 16) << 16

if not data:
    sys.exit(1)

# Write umem - unified memory (little-endian, larger for MMU tests)
with open('umem.hex', 'w') as f:
    for word_idx in range(262144):  # 1MB
        word = 0
        addr = word_idx * 4
        word = data.get(addr, 0) | (data.get(addr+1, 0) << 8) | (data.get(addr+2, 0) << 16) | (data.get(addr+3, 0) << 24)
        f.write(f'{word:08x}\n')
"

    # Run test with configured reset PC
    RESULT=$(timeout 10 $TEST_CMD +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR +reset_pc=$RESET_PC 2>&1)
    EXIT_CODE=$?

    if echo "$RESULT" | grep -q "TEST PASSED"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif echo "$RESULT" | grep -q "TEST FAILED"; then
        echo "FAIL"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
    elif [ $EXIT_CODE -eq 124 ]; then
        echo "TIMEOUT"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
    else
        echo "ERROR"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
    fi
done

# Also run base tests (from mips32_complete test suite)
echo ""
echo "Running base instruction tests..."
for test in $BASE_TESTS; do
    echo -n "Testing $test... "

    TEST_BASE="../../../isa/mips32/mips-tests/isa/mips32-isacomp-$test"

    if [ ! -f "$TEST_BASE.hex" ]; then
        echo "SKIP (no hex file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    if [ ! -f "$TEST_BASE.addrs" ]; then
        echo "SKIP (no addrs file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    # Get pass/fail addresses (used directly with PC starting at 0)
    read PASS_ADDR FAIL_ADDR < "$TEST_BASE.addrs"

    # Regenerate complex TLB configuration for base tests (kuseg needs TLB)
    python3 -c "
tlb_hi = []
tlb_lo0 = []
tlb_lo1 = []

for i in range(32):
    if i < 8:
        vpn2, asid, pfn0, pfn1, c, d, v, g = i, 0, i*2, i*2+1, 0, 1, 1, 1
    elif i < 12:
        vpn2, asid, pfn0, pfn1, c, d, v, g = i, 0, (i+16)*2, (i+16)*2+1, 0, 1, 1, 1
    elif i < 16:
        vpn2, asid, pfn0, pfn1, c, d, v, g = i, 0, i*2, i*2+1, i-12, 1, 1, 1
    elif i < 20:
        vpn2, asid, pfn0, pfn1, c, d, v, g = i, 0, i*2, i*2+1, 0, 1, 1, 0
    elif i < 24:
        vpn2, asid, pfn0, pfn1, c, d, v, g = i, 0, (i+64)*2, (i+64)*2+1, 0, 1, 1, 1
    elif i < 28:
        vpn2, asid, pfn0, pfn1, c, d, v, g = i, 0, i*2, i*2+1, 0, 0, 1, 1
    elif i < 31:
        vpn2, asid, pfn0, pfn1, c, d, v, g = i, 0, i*2, i*2+1, 0, 1, 1, 1
    else:
        vpn2, asid, pfn0, pfn1, c, d, v, g = 0x1000, 0, 0, 1, 0, 1, 1, 1

    entry_hi = (vpn2 << 13) | asid
    entry_lo0 = (pfn0 << 6) | (c << 3) | (d << 2) | (v << 1) | g
    v1 = 0 if 28 <= i < 31 else v
    entry_lo1 = (pfn1 << 6) | (c << 3) | (d << 2) | (v1 << 1) | g

    tlb_hi.append(entry_hi)
    tlb_lo0.append(entry_lo0)
    tlb_lo1.append(entry_lo1)

with open('tlb_hi.hex', 'w') as f:
    for val in tlb_hi: f.write(f'{val:08x}\n')
with open('tlb_lo0.hex', 'w') as f:
    for val in tlb_lo0: f.write(f'{val:08x}\n')
with open('tlb_lo1.hex', 'w') as f:
    for val in tlb_lo1: f.write(f'{val:08x}\n')
with open('tlb_vpn2.hex', 'w') as f:
    for val in tlb_hi: f.write(f'{(val >> 13) & 0x7FFFF:05x}\n')
with open('tlb_asid.hex', 'w') as f:
    for val in tlb_hi: f.write(f'{val & 0xFF:02x}\n')
with open('tlb_pfn0.hex', 'w') as f:
    for val in tlb_lo0: f.write(f'{(val >> 6) & 0xFFFFF:05x}\n')
with open('tlb_pfn1.hex', 'w') as f:
    for val in tlb_lo1: f.write(f'{(val >> 6) & 0xFFFFF:05x}\n')
with open('tlb_v0.hex', 'w') as f:
    for val in tlb_lo0: f.write(f'{(val >> 1) & 1:x}\n')
with open('tlb_v1.hex', 'w') as f:
    for val in tlb_lo1: f.write(f'{(val >> 1) & 1:x}\n')
with open('tlb_d0.hex', 'w') as f:
    for val in tlb_lo0: f.write(f'{(val >> 2) & 1:x}\n')
with open('tlb_d1.hex', 'w') as f:
    for val in tlb_lo1: f.write(f'{(val >> 2) & 1:x}\n')
with open('tlb_g.hex', 'w') as f:
    for i in range(len(tlb_lo0)): f.write(f'{(tlb_lo0[i] & 1) & (tlb_lo1[i] & 1):x}\n')
"

    python3 -c "
import sys
data = {}
with open('$TEST_BASE.hex', 'r') as f:
    for line in f:
        line = line.strip()
        if not line.startswith(':'):
            continue
        byte_count = int(line[1:3], 16)
        address = int(line[3:7], 16)
        record_type = int(line[7:9], 16)
        if record_type == 0:
            for i in range(byte_count):
                byte_val = int(line[9+i*2:11+i*2], 16)
                data[address + i] = byte_val
        elif record_type == 1:
            break

if not data:
    sys.exit(1)

with open('umem.hex', 'w') as f:
    # Use sparse format: @address value
    # Only write non-zero entries for much faster loading
    words = {}
    for byte_addr, byte_val in data.items():
        word_addr = byte_addr // 4
        byte_pos = byte_addr % 4
        if word_addr not in words:
            words[word_addr] = 0
        words[word_addr] |= byte_val << (byte_pos * 8)
    for word_addr in sorted(words.keys()):
        f.write(f'@{word_addr:05x} {words[word_addr]:08x}\n')
"

    # Determine whether to run from kseg0 or kuseg
    # jal/jalr tests expect kuseg return addresses, so run them from kuseg
    if [ "$test" = "jal" ] || [ "$test" = "jalr" ]; then
        # Run from kuseg (PC=0) - tests expect kuseg addresses
        RESULT=$(timeout 10 $TEST_CMD +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR +reset_pc=0 2>&1)
    else
        # Run from kseg0 (PC=0x80000000) - avoids TLB lookup for instruction fetch
        PASS_ADDR_KSEG0=$(printf '%08x' $((0x$PASS_ADDR + 0x80000000)))
        FAIL_ADDR_KSEG0=$(printf '%08x' $((0x$FAIL_ADDR + 0x80000000)))
        RESULT=$(timeout 10 $TEST_CMD +pass_addr=$PASS_ADDR_KSEG0 +fail_addr=$FAIL_ADDR_KSEG0 +reset_pc=80000000 2>&1)
    fi
    EXIT_CODE=$?

    if echo "$RESULT" | grep -q "TEST PASSED"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif echo "$RESULT" | grep -q "TEST FAILED"; then
        echo "FAIL"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
    elif [ $EXIT_CODE -eq 124 ]; then
        echo "TIMEOUT"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
    else
        echo "ERROR"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
    fi
done

echo ""
echo "================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
if [ -n "$FAILED_TESTS" ]; then
    echo "Failed tests:$FAILED_TESTS"
fi
echo "================================"

if [ $FAIL -gt 0 ]; then
    echo "FAILED: $FAIL test(s) failed"
    exit 1
fi

if [ $PASS -eq 0 ]; then
    echo "FAILED: No tests passed (all skipped)"
    exit 1
fi

echo "SUCCESS: All $PASS tests passed"
exit 0
