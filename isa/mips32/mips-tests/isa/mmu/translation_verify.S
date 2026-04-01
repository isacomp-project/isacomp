/* MIPS32 MMU Translation Verification Test
 *
 * This test verifies that TLB address translation actually works by:
 * 1. Writing a marker to physical memory using kseg0 (unmapped)
 * 2. Setting up a TLB entry with NON-IDENTITY mapping
 * 3. Reading through the virtual address - should get the marker
 * 4. Writing through the virtual address
 * 5. Verifying the write reached the correct physical address
 *
 * TLB Configuration:
 *   VPN2=0x10 (VA 0x00020000-0x00021FFF) -> PFN=0x40/0x41 (PA 0x00040000-0x00041FFF)
 *   This is a +0x20000 byte offset (non-identity)
 *
 * Note: Code runs from kseg0 (test runner adds 0x80000000 to PC)
 */

#include "mmu_test_macros.h"

RVTEST_CODE_BEGIN

    /* ============================================================
     * Step 1: Write marker to physical address using kseg0
     * PA 0x00040000 = kseg0 VA 0x80040000
     * ============================================================ */
test_1:
    li TESTNUM, 1
    li $t0, 0x80040000          /* kseg0 address for PA 0x40000 */
    li $t1, 0xDEADBEEF          /* First marker value */
    sw $t1, 0($t0)              /* Write marker */
    nop

    /* Verify write worked */
    lw $t2, 0($t0)
    bne $t1, $t2, fail
    nop

    /* ============================================================
     * Step 2: Set up TLB entry with non-identity mapping
     * VPN2=0x10 (VA 0x20000-0x21FFF) -> PFN=0x40,0x41 (PA 0x40000-0x41FFF)
     * ============================================================ */
test_2:
    li TESTNUM, 2
    /* Set Index = 0 (use first TLB entry) */
    li $t0, 0
    mtc0 $t0, $0, 0             /* CP0 Index */

    /* Set EntryHi: VPN2=0x10, ASID=0
     * VPN2 is bits 31:13, so VPN2=0x10 -> EntryHi[31:13]=0x10 -> 0x00020000 */
    li $t0, 0x00020000          /* VPN2=0x10 << 13, ASID=0 */
    mtc0 $t0, $10, 0            /* CP0 EntryHi */

    /* Set EntryLo0: PFN=0x40, D=1, V=1, G=1
     * PFN is bits 25:6, D=bit2, V=bit1, G=bit0
     * PFN=0x40 << 6 = 0x1000, D|V|G = 0x7
     * EntryLo0 = 0x1007 */
    li $t0, 0x00001007
    mtc0 $t0, $2, 0             /* CP0 EntryLo0 */

    /* Set EntryLo1: PFN=0x41, D=1, V=1, G=1
     * PFN=0x41 << 6 = 0x1040, D|V|G = 0x7
     * EntryLo1 = 0x1047 */
    li $t0, 0x00001047
    mtc0 $t0, $3, 0             /* CP0 EntryLo1 */

    nop
    nop

    /* Write the TLB entry */
    tlbwi
    nop
    nop
    nop

    /* ============================================================
     * Step 3: Read through virtual address using kuseg
     * VA 0x00020000 should translate to PA 0x00040000
     * ============================================================ */
test_3:
    li TESTNUM, 3
    li $t3, 0x00020000          /* Virtual address in kuseg */
    lw $t4, 0($t3)              /* Load through TLB */

    /* Verify we got our marker */
    li $t5, 0xDEADBEEF
    bne $t4, $t5, fail
    nop

    /* ============================================================
     * Step 4: Write through virtual address
     * ============================================================ */
test_4:
    li TESTNUM, 4
    li $t6, 0xCAFEBABE          /* Second marker */
    li $t3, 0x00020000
    sw $t6, 0($t3)              /* Store through TLB to VA 0x20000 -> PA 0x40000 */
    nop

    /* ============================================================
     * Step 5: Verify write reached correct physical address
     * Read from PA 0x40000 via kseg0
     * ============================================================ */
test_5:
    li TESTNUM, 5
    li $t0, 0x80040000          /* kseg0 address for PA 0x40000 */
    lw $t7, 0($t0)              /* Read from physical memory */

    bne $t6, $t7, fail          /* Should be 0xCAFEBABE */
    nop

    /* ============================================================
     * Step 6: Test odd page (VA[12]=1)
     * VA 0x00021000 should translate to PA 0x00041000 (using EntryLo1)
     * ============================================================ */
test_6:
    li TESTNUM, 6
    /* Write marker to PA 0x41000 via kseg0 */
    li $t0, 0x80041000          /* kseg0 address for PA 0x41000 */
    li $t1, 0x12345678
    sw $t1, 0($t0)
    nop

    /* Read through VA 0x21000 (odd page) */
    li $t3, 0x00021000          /* Virtual address with bit 12 = 1 */
    lw $t4, 0($t3)

    bne $t1, $t4, fail
    nop

    TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
