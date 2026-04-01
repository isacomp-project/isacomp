#!/bin/bash

# Test J4 (SuperH-4) MMU instructions using the CAM-based TLB implementation
# Supports both iverilog and verilator simulators
#
# Environment variables:
#   SIMULATOR   - 'iverilog' (default) or 'verilator'
#   TLB_CONFIG  - TLB configuration to use:
#                 'identity'   - Identity mapping (VPN=PPN) [default]
#                 'offset'     - Non-identity with +16 offset
#                 'offset32'   - Non-identity with +32 offset
#                 'scrambled'  - Randomized mapping
#                 'minimal'    - Minimal entries
#                 'complex'    - Complex mixed mapping (original)
#
# Usage:
#   ./run_mmu_tests.sh                    # Run with defaults
#   TLB_CONFIG=offset ./run_mmu_tests.sh  # Use offset mapping
#   TLB_CONFIG=scrambled ./run_mmu_tests.sh  # Use scrambled mapping

SIMULATOR=${SIMULATOR:-iverilog}
TLB_CONFIG=${TLB_CONFIG:-complex}

echo "J4 (SuperH-4) MMU Test Suite"
echo "============================"
echo "Simulator: $SIMULATOR"
echo "TLB Config: $TLB_CONFIG"
echo ""

# Compile testbench
echo "Compiling testbench..."

if [ "$SIMULATOR" = "verilator" ]; then
    if [ ! -f "test_simple" ] || [ "j4_complete.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
        verilator --timing --exe --binary \
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \
            -o test_simple cvfpu_simple.v j4_complete.v simple_tb.sv
        if [ $? -ne 0 ]; then
            echo "ERROR: Verilator compilation failed!"
            exit 1
        fi
        mv obj_dir/test_simple . 2>/dev/null || true
    fi
    TEST_CMD="./test_simple"
else
    if [ ! -f "test_simple" ] || [ "j4_complete.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
        iverilog -g2012 -o test_simple cvfpu_simple.v j4_complete.v simple_tb.sv
        if [ $? -ne 0 ]; then
            echo "ERROR: Icarus Verilog compilation failed!"
            exit 1
        fi
    fi
    TEST_CMD="vvp test_simple"
fi

# Generate TLB configuration based on TLB_CONFIG setting
echo "Generating TLB configuration ($TLB_CONFIG)..."

if [ "$TLB_CONFIG" = "complex" ]; then
    # Original complex configuration
    # Create TLB memory files with complex page table setup for thorough testing
    # SH4 UTLB has 64 entries, ITLB has 4 entries
    #
    # UTLB Entry Format:
    #   VPN[31:10] - Virtual Page Number (22 bits, stored in CAM)
    #   ASID[7:0]  - Address Space Identifier
    #   PPN[28:10] - Physical Page Number (19 bits)
    #   SZ[1:0]    - Page size (00=1KB, 01=4KB, 10=64KB, 11=1MB)
    #   PR[1:0]    - Protection (00=priv-only, 01=priv-RW/user-R, 10=priv-RW/user-RW, 11=reserved)
    #   C          - Cacheable
    #   D          - Dirty (writable)
    #   SH         - Shared
    #   WT         - Write-through
    #   V          - Valid
    #
    # UTLB Configuration:
    # ==================
    # Entries 0-15:  Identity mapping (VPN=PPN), Global (SH=1) - for test code execution
    # Entries 16-23: Non-identity mapping (VPN -> PPN+16), Global - tests address translation
    # Entries 24-31: Different page sizes (1KB, 4KB, 64KB, 1MB), Global
    # Entries 32-39: ASID-specific (ASID=0, SH=0) - tests ASID matching
    # Entries 40-47: Large offset mapping (VPN -> PPN+64), Global - tests large translations
    # Entries 48-55: Read-only pages (D=0), Global - tests write protection
    # Entries 56-59: Invalid entries (V=0) - tests TLB miss exceptions
    # Entries 60-63: High address mapping, Global - tests high virtual addresses
    #
    python3 -c "
# Complex UTLB configuration for J4/SH4
utlb_vpn = []   # 22 bits: VPN[31:10]
utlb_asid = []  # 8 bits
utlb_ppn = []   # 19 bits: PPN[28:10]
utlb_sz = []    # 2 bits: page size
utlb_pr = []    # 2 bits: protection
utlb_c = []     # 1 bit: cacheable
utlb_d = []     # 1 bit: dirty/writable
utlb_sh = []    # 1 bit: shared (acts as global)
utlb_wt = []    # 1 bit: write-through
utlb_v = []     # 1 bit: valid

for i in range(64):
    if i < 16:
        # Entries 0-15: Identity mapping, Shared/Global
        # VPN[31:10] = i (maps VA i*1KB to PA i*1KB with 1KB pages)
        # Exception: Entry 12 has non-identity mapping for translation-verify test
        vpn = i
        asid = 0
        if i == 12:
            ppn = 8  # Non-identity: VA 0x3000 -> PA 0x2000
        else:
            ppn = i
        sz = 0   # 1KB pages
        pr = 2   # RW for priv and user
        c = 0    # Uncached
        d = 1    # Writable
        sh = 1   # Shared (global)
        wt = 0
        v = 1    # Valid

    elif i < 24:
        # Entries 16-23: Non-identity mapping with +16 page offset
        vpn = i
        asid = 0
        ppn = i + 16  # Offset by 16 pages
        sz = 0
        pr = 2
        c = 0
        d = 1
        sh = 1
        wt = 0
        v = 1

    elif i < 32:
        # Entries 24-31: Different page sizes
        vpn = i
        asid = 0
        ppn = i
        sz = (i - 24) % 4  # Cycle through 0,1,2,3 (1KB,4KB,64KB,1MB)
        pr = 2
        c = 0
        d = 1
        sh = 1
        wt = 0
        v = 1

    elif i < 40:
        # Entries 32-39: ASID-specific (not shared/global)
        vpn = i
        asid = 0  # Only matches ASID 0
        ppn = i
        sz = 0
        pr = 2
        c = 0
        d = 1
        sh = 0  # NOT shared - requires ASID match
        wt = 0
        v = 1

    elif i < 48:
        # Entries 40-47: Large offset mapping (+64 pages)
        vpn = i
        asid = 0
        ppn = i + 64
        sz = 0
        pr = 2
        c = 0
        d = 1
        sh = 1
        wt = 0
        v = 1

    elif i < 56:
        # Entries 48-55: Read-only pages (D=0)
        vpn = i
        asid = 0
        ppn = i
        sz = 0
        pr = 2
        c = 0
        d = 0  # NOT dirty/writable
        sh = 1
        wt = 0
        v = 1

    elif i < 60:
        # Entries 56-59: Invalid entries (V=0)
        vpn = i
        asid = 0
        ppn = i
        sz = 0
        pr = 2
        c = 0
        d = 1
        sh = 1
        wt = 0
        v = 0  # INVALID

    else:
        # Entries 60-63: High address mapping
        # Maps high virtual addresses to low physical
        vpn = 0x100000 + (i - 60)  # High kuseg addresses
        asid = 0
        ppn = i - 60  # Map to low physical
        sz = 0
        pr = 2
        c = 0
        d = 1
        sh = 1
        wt = 0
        v = 1

    utlb_vpn.append(vpn)
    utlb_asid.append(asid)
    utlb_ppn.append(ppn)
    utlb_sz.append(sz)
    utlb_pr.append(pr)
    utlb_c.append(c)
    utlb_d.append(d)
    utlb_sh.append(sh)
    utlb_wt.append(wt)
    utlb_v.append(v)

# Write UTLB files
with open('utlb_vpn.hex', 'w') as f:
    for val in utlb_vpn: f.write(f'{val:08x}\n')
with open('utlb_asid.hex', 'w') as f:
    for val in utlb_asid: f.write(f'{val:08x}\n')
with open('utlb_ppn.hex', 'w') as f:
    for val in utlb_ppn: f.write(f'{val:08x}\n')
with open('utlb_sz.hex', 'w') as f:
    for val in utlb_sz: f.write(f'{val:08x}\n')
with open('utlb_pr.hex', 'w') as f:
    for val in utlb_pr: f.write(f'{val:08x}\n')
with open('utlb_c.hex', 'w') as f:
    for val in utlb_c: f.write(f'{val:08x}\n')
with open('utlb_d.hex', 'w') as f:
    for val in utlb_d: f.write(f'{val:08x}\n')
with open('utlb_sh.hex', 'w') as f:
    for val in utlb_sh: f.write(f'{val:08x}\n')
with open('utlb_wt.hex', 'w') as f:
    for val in utlb_wt: f.write(f'{val:08x}\n')
with open('utlb_v.hex', 'w') as f:
    for val in utlb_v: f.write(f'{val:08x}\n')

# ITLB - 4 entries, identity mapping
for name in ['itlb_vpn.hex', 'itlb_asid.hex', 'itlb_ppn.hex', 'itlb_sz.hex',
             'itlb_pr.hex', 'itlb_c.hex', 'itlb_sh.hex']:
    with open(name, 'w') as f:
        for i in range(4):
            f.write(f'{i:08x}\n')
with open('itlb_v.hex', 'w') as f:
    for i in range(4):
        f.write('00000001\n')

# Print summary
print('J4 UTLB Configuration Summary:')
print('Entry | VPN      | ASID | PPN   | SZ | PR | C | D | SH | V | Description')
print('-' * 80)
for i in range(64):
    if i < 16:
        if i == 12:
            desc = 'Non-identity (VA->PA-0x1000), Shared'
        else:
            desc = 'Identity, Shared'
    elif i < 24:
        desc = 'Non-identity (+16)'
    elif i < 32:
        desc = f'Page size {[\"1KB\",\"4KB\",\"64KB\",\"1MB\"][utlb_sz[i]]}'
    elif i < 40:
        desc = 'ASID-specific (SH=0)'
    elif i < 48:
        desc = 'Large offset (+64)'
    elif i < 56:
        desc = 'Read-only (D=0)'
    elif i < 60:
        desc = 'Invalid (V=0)'
    else:
        desc = 'High address mapping'
    print(f'{i:5} | {utlb_vpn[i]:06x}   | {utlb_asid[i]:4} | {utlb_ppn[i]:5} | {utlb_sz[i]:2} | {utlb_pr[i]:2} | {utlb_c[i]} | {utlb_d[i]} | {utlb_sh[i]:2} | {utlb_v[i]} | {desc}')
"

else
    # Use generate_tlb_config.py for other configurations
    if [ -f "generate_tlb_config.py" ]; then
        python3 generate_tlb_config.py "$TLB_CONFIG" .
    else
        echo "ERROR: generate_tlb_config.py not found and TLB_CONFIG=$TLB_CONFIG"
        echo "Available configs: complex, identity, offset, offset32, scrambled, minimal"
        exit 1
    fi
fi

# MMU-specific tests
MMU_TESTS="ldtlb tlb_miss tlb_hit p1_direct p2_direct translation-verify"

# Base instruction tests - comprehensive set similar to MIPS32
# These run through the TLB with identity mapping to verify CAM lookups work
BASE_TESTS="add addc addi addv sub subc subv neg negc and andi or ori xor xori not tst tsti shll shlr shll2 shlr2 shll8 shlr8 shll16 shlr16 rotl rotr rotcl rotcr shal shar mov movi mova movt movl movl_store movl_pcrel movw movw_store movw_pcrel movb movb_store cmpeq cmpge cmpgt cmphi cmphs cmppl cmppz cmpimm cmpstr bt bf bra jmp jsr rts clrt sett nop swapb swapw extsb extsw extub extuw div0s div0u div1 dt mull mulsw muluw dmulsl dmulul macl macw clrmac lds_pr sts_pr lds_gbr sts_gbr lds_mach sts_mach lds_macl tasb trapa"

PASS=0
FAIL=0
SKIP=0
FAILED_TESTS=""

# Run MMU-specific tests
echo ""
echo "Running MMU-specific tests..."
for test in $MMU_TESTS; do
    echo -n "Testing $test... "

    TEST_BASE="../../../isa/j4/j4-tests/isa/mmu/j4-mmu-$test"

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

    # Get pass/fail addresses (P1 region = 0x8xxxxxxx)
    read PASS_ADDR FAIL_ADDR < "$TEST_BASE.addrs"

    # Convert hex file to umem.hex
    python3 -c "
import sys
data = {}
ext_addr = 0
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
            # Convert P1/P2 address to physical (strip top 3 bits)
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
            ext_addr = int(line[9:13], 16) << 16

if not data:
    sys.exit(1)

# Detect if ELF is little-endian by checking instruction patterns
# Little-endian SH4 hex has low byte first (e.g., 13 D1 for MOV.L)
# Big-endian SH4 hex has high byte first (e.g., D1 xx for MOV.L)
# Check first byte - if it's not 0xD1-0xDF, likely little-endian
is_little_endian = data.get(0, 0) < 0xD0

# Find the boundary between code and data
# Data typically starts after code, often at aligned address
# Look for start of data by finding first .align 4 boundary after code ends
# Code ends where we see repeated NOPs (0x0009) or the PC-relative data starts
# A simple heuristic: data starts at first aligned address >= 0x40 where word != instructions
data_start = 0x50  # Default: data often starts around here

# Write umem - unified memory (big-endian, 32-bit words)
# Memory is organized as 32-bit words (2 instructions per word)
# For little-endian hex files:
#   - Instructions: swap bytes within each 16-bit halfword
#   - Data: full 32-bit byte-swap (little-endian to big-endian)
with open('umem.hex', 'w') as f:
    for word_idx in range(4096):  # 16KB memory
        addr = word_idx * 4
        b0 = data.get(addr + 0, 0)
        b1 = data.get(addr + 1, 0)
        b2 = data.get(addr + 2, 0)
        b3 = data.get(addr + 3, 0)
        if is_little_endian:
            if addr < data_start:
                # Instructions: swap bytes within each 16-bit halfword
                word = (b1 << 24) | (b0 << 16) | (b3 << 8) | b2
            else:
                # Data: full 32-bit byte-swap (little-endian to big-endian)
                word = (b3 << 24) | (b2 << 16) | (b1 << 8) | b0
        else:
            # Big-endian: bytes are already in correct order
            word = (b0 << 24) | (b1 << 16) | (b2 << 8) | b3
        f.write(f'{word:08x}\n')
"

    # Run test
    RESULT=$(timeout 10 $TEST_CMD +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)
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

# Also run base tests (from j4_complete test suite)
echo ""
echo "Running base instruction tests..."
for test in $BASE_TESTS; do
    echo -n "Testing $test... "

    TEST_BASE="../../../isa/j4/j4-tests/isa/j4-isacomp-$test"

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

    # Use physical addresses directly (PC starts at 0x0)
    read PASS_ADDR FAIL_ADDR < "$TEST_BASE.addrs"

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
    for word_idx in range(4096):  # 16KB memory
        word = 0
        addr = word_idx * 4
        # Big-endian 32-bit word from 4 bytes
        for i in range(4):
            word |= data.get(addr + i, 0) << ((3 - i) * 8)
        f.write(f'{word:08x}\n')
"

    RESULT=$(timeout 10 $TEST_CMD +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)
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
