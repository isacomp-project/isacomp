/* MIPS32 MMU Kseg0/Kseg1 Unmapped Translation Test
 *
 * Tests kseg0/kseg1 unmapped address translation (top 3 bits stripped):
 *   kseg0 VA 0x80010000 -> PA 0x00010000
 *   kseg1 VA 0xA0010000 -> PA 0x00010000 (same physical address!)
 */

#include "mmu_test_macros.h"

RVTEST_CODE_BEGIN

    /* kseg0 write and read */
test_1:
    li TESTNUM, 1
    li $t0, 0x80010000
    li $t1, 0x11111111
    sw $t1, 0($t0)
    nop
    lw $t2, 0($t0)
    bne $t1, $t2, fail
    nop

    /* kseg1 write and read */
test_2:
    li TESTNUM, 2
    li $t0, 0xA0020000
    li $t1, 0x22222222
    sw $t1, 0($t0)
    nop
    lw $t2, 0($t0)
    bne $t1, $t2, fail
    nop

    /* kseg0 and kseg1 access same physical memory */
test_3:
    li TESTNUM, 3
    li $t0, 0x80030000          /* kseg0: PA 0x30000 */
    li $t1, 0x33333333
    sw $t1, 0($t0)
    nop
    li $t0, 0xA0030000          /* kseg1: PA 0x30000 (same!) */
    lw $t2, 0($t0)
    bne $t1, $t2, fail
    nop

    /* Reverse: write via kseg1, read via kseg0 */
test_4:
    li TESTNUM, 4
    li $t0, 0xA0040000          /* kseg1: PA 0x40000 */
    li $t1, 0x44444444
    sw $t1, 0($t0)
    nop
    li $t0, 0x80040000          /* kseg0: PA 0x40000 */
    lw $t2, 0($t0)
    bne $t1, $t2, fail
    nop

    /* kseg0 byte access */
test_5:
    li TESTNUM, 5
    li $t0, 0x80050000
    li $t1, 0xAABBCCDD
    sw $t1, 0($t0)
    nop

    li $t0, 0xA0050000          /* Read via kseg1 */
    lbu $t2, 0($t0)
    li $t3, 0xDD
    bne $t2, $t3, fail
    nop

test_6:
    li TESTNUM, 6
    li $t0, 0xA0050000
    lbu $t2, 3($t0)
    li $t3, 0xAA
    bne $t2, $t3, fail
    nop

    /* kseg0 halfword access */
test_7:
    li TESTNUM, 7
    li $t0, 0x80050000
    lhu $t2, 0($t0)
    li $t3, 0xCCDD
    bne $t2, $t3, fail
    nop

test_8:
    li TESTNUM, 8
    lhu $t2, 2($t0)
    li $t3, 0xAABB
    bne $t2, $t3, fail
    nop

    TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
