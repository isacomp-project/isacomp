/* MIPS32 MMU Odd/Even Page Translation Test
 *
 * Tests that TLB correctly selects EntryLo0 vs EntryLo1 based on VA[12]:
 *   VPN2=0x10: EntryLo0 (PA 0x40000) for even, EntryLo1 (PA 0x50000) for odd
 * Note: Uses physical addresses within 1MB umem limit
 */

#include "mmu_test_macros.h"

RVTEST_CODE_BEGIN

    /* Setup TLB with different PFNs for even/odd pages */
test_1:
    li TESTNUM, 1
    li $t0, 0
    mtc0 $t0, $0, 0
    li $t0, 0x00020000
    mtc0 $t0, $10, 0
    li $t0, 0x00001007           /* PFN=0x40 -> PA 0x40000 */
    mtc0 $t0, $2, 0
    li $t0, 0x00001407           /* PFN=0x50 -> PA 0x50000 */
    mtc0 $t0, $3, 0
    nop
    tlbwi
    nop

    /* Write markers to physical pages via kseg0 */
test_2:
    li TESTNUM, 2
    li $t0, 0x80040000
    li $t1, 0xEEEEEEEE
    sw $t1, 0($t0)
    li $t0, 0x80050000
    li $t2, 0x0DDD0DDD
    sw $t2, 0($t0)
    nop

    /* Read VA 0x20000 (bit12=0) -> should get even page (0xEEEEEEEE) */
test_3:
    li TESTNUM, 3
    li $t3, 0x00020000
    lw $t4, 0($t3)
    li $t5, 0xEEEEEEEE
    bne $t4, $t5, fail
    nop

    /* Read VA 0x21000 (bit12=1) -> should get odd page (0x0DDD0DDD) */
test_4:
    li TESTNUM, 4
    li $t3, 0x00021000
    lw $t4, 0($t3)
    li $t5, 0x0DDD0DDD
    bne $t4, $t5, fail
    nop

    /* Write to even page via TLB, verify via kseg0 */
test_5:
    li TESTNUM, 5
    li $t3, 0x00020000
    li $t1, 0xAAAA1111
    sw $t1, 0($t3)
    nop
    li $t0, 0x80040000
    lw $t4, 0($t0)
    bne $t1, $t4, fail
    nop

    /* Write to odd page via TLB, verify via kseg0 */
test_6:
    li TESTNUM, 6
    li $t3, 0x00021000
    li $t2, 0xBBBB2222
    sw $t2, 0($t3)
    nop
    li $t0, 0x80050000
    lw $t4, 0($t0)
    bne $t2, $t4, fail
    nop

    TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
