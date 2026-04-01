/* MIPS32 MMU Sub-word Translation Test
 *
 * Tests byte (LB/SB) and halfword (LH/SH) accesses through TLB translation.
 * VPN2=0x10 (VA 0x20000) -> PFN=0x50 (PA 0x50000)
 */

#include "mmu_test_macros.h"

RVTEST_CODE_BEGIN

    /* Setup TLB entry */
test_1:
    li TESTNUM, 1
    li $t0, 0
    mtc0 $t0, $0, 0
    li $t0, 0x00020000
    mtc0 $t0, $10, 0
    li $t0, 0x00001407           /* PFN=0x50 */
    mtc0 $t0, $2, 0
    li $t0, 0x00001447
    mtc0 $t0, $3, 0
    nop
    tlbwi
    nop

    /* Clear target memory */
test_2:
    li TESTNUM, 2
    li $t0, 0x80050000
    sw $zero, 0($t0)
    nop

    /* Test byte stores through TLB */
test_3:
    li TESTNUM, 3
    li $t0, 0x00020000
    li $t1, 0x11
    sb $t1, 0($t0)
    li $t1, 0x22
    sb $t1, 1($t0)
    li $t1, 0x33
    sb $t1, 2($t0)
    li $t1, 0x44
    sb $t1, 3($t0)
    nop

    /* Verify word at PA 0x50000 = 0x44332211 (little-endian) */
test_4:
    li TESTNUM, 4
    li $t0, 0x80050000
    lw $t2, 0($t0)
    li $t3, 0x44332211
    bne $t2, $t3, fail
    nop

    /* Test byte loads through TLB */
test_5:
    li TESTNUM, 5
    li $t0, 0x80050004
    li $t1, 0xAABBCCDD
    sw $t1, 0($t0)
    nop

    li $t0, 0x00020004
    lbu $t2, 0($t0)              /* Should be 0xDD */
    li $t3, 0xDD
    bne $t2, $t3, fail
    nop

test_6:
    li TESTNUM, 6
    li $t0, 0x00020004
    lbu $t2, 3($t0)              /* Should be 0xAA */
    li $t3, 0xAA
    bne $t2, $t3, fail
    nop

    /* Test halfword stores */
test_7:
    li TESTNUM, 7
    li $t0, 0x00020008
    li $t1, 0x5566
    sh $t1, 0($t0)
    li $t1, 0x7788
    sh $t1, 2($t0)
    nop

    li $t0, 0x80050008
    lw $t2, 0($t0)
    li $t3, 0x77885566
    bne $t2, $t3, fail
    nop

    /* Test halfword loads */
test_8:
    li TESTNUM, 8
    li $t0, 0x8005000C
    li $t1, 0x99AABBCC
    sw $t1, 0($t0)
    nop

    li $t0, 0x0002000C
    lhu $t2, 0($t0)
    li $t3, 0xBBCC
    bne $t2, $t3, fail
    nop

test_9:
    li TESTNUM, 9
    li $t0, 0x0002000C
    lhu $t2, 2($t0)
    li $t3, 0x99AA
    bne $t2, $t3, fail
    nop

    TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
