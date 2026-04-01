/* MIPS32 MULT/MULTU/DIV/DIVU Tests */
/* Tests multiply and divide with HI/LO registers */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MULT tests - signed multiply
   *-------------------------------------------------------------*/

  /* Test 2: Simple multiply 3 * 4 = 12 */
test_2:
    li TESTNUM, 2
    li $t1, 3
    li $t2, 4
    mult $t1, $t2
    mflo $t0
    li $t9, 12
    bne $t0, $t9, fail
    nop

  /* Test 3: Multiply with zero */
test_3:
    li TESTNUM, 3
    li $t1, 12345
    li $t2, 0
    mult $t1, $t2
    mflo $t0
    bne $t0, $zero, fail
    nop

  /* Test 4: Multiply negative numbers: -3 * 4 = -12 */
test_4:
    li TESTNUM, 4
    li $t1, -3
    li $t2, 4
    mult $t1, $t2
    mflo $t0
    li $t9, -12
    bne $t0, $t9, fail
    nop

  /* Test 5: Multiply two negatives: -3 * -4 = 12 */
test_5:
    li TESTNUM, 5
    li $t1, -3
    li $t2, -4
    mult $t1, $t2
    mflo $t0
    li $t9, 12
    bne $t0, $t9, fail
    nop

  /* Test 6: Large multiply producing 64-bit result */
test_6:
    li TESTNUM, 6
    li $t1, 0x10000      /* 65536 */
    li $t2, 0x10000      /* 65536 */
    mult $t1, $t2
    mflo $t0             /* Should be 0 (low 32 bits) */
    mfhi $t3             /* Should be 1 (high 32 bits) */
    bne $t0, $zero, fail
    nop
    li $t9, 1
    bne $t3, $t9, fail
    nop

  /*-------------------------------------------------------------
   * MULTU tests - unsigned multiply
   *-------------------------------------------------------------*/

  /* Test 7: Simple unsigned multiply */
test_7:
    li TESTNUM, 7
    li $t1, 5
    li $t2, 7
    multu $t1, $t2
    mflo $t0
    li $t9, 35
    bne $t0, $t9, fail
    nop

  /* Test 8: Large unsigned multiply */
test_8:
    li TESTNUM, 8
    li $t1, 0x80000000   /* 2^31 as unsigned */
    li $t2, 2
    multu $t1, $t2
    mflo $t0             /* Should be 0 */
    mfhi $t3             /* Should be 1 */
    bne $t0, $zero, fail
    nop
    li $t9, 1
    bne $t3, $t9, fail
    nop

  /*-------------------------------------------------------------
   * DIV tests - signed divide
   *-------------------------------------------------------------*/

  /* Test 9: Simple divide 12 / 4 = 3 */
test_9:
    li TESTNUM, 9
    li $t1, 12
    li $t2, 4
    div $zero, $t1, $t2
    mflo $t0             /* Quotient = 3 */
    mfhi $t3             /* Remainder = 0 */
    li $t9, 3
    bne $t0, $t9, fail
    nop
    bne $t3, $zero, fail
    nop

  /* Test 10: Divide with remainder 13 / 4 = 3 rem 1 */
test_10:
    li TESTNUM, 10
    li $t1, 13
    li $t2, 4
    div $zero, $t1, $t2
    mflo $t0             /* Quotient = 3 */
    mfhi $t3             /* Remainder = 1 */
    li $t9, 3
    bne $t0, $t9, fail
    nop
    li $t9, 1
    bne $t3, $t9, fail
    nop

  /* Test 11: Divide negative -12 / 4 = -3 */
test_11:
    li TESTNUM, 11
    li $t1, -12
    li $t2, 4
    div $zero, $t1, $t2
    mflo $t0             /* Quotient = -3 */
    li $t9, -3
    bne $t0, $t9, fail
    nop

  /* Test 12: Divide negative -13 / 4 = -3 rem -1 */
test_12:
    li TESTNUM, 12
    li $t1, -13
    li $t2, 4
    div $zero, $t1, $t2
    mflo $t0             /* Quotient = -3 */
    mfhi $t3             /* Remainder = -1 */
    li $t9, -3
    bne $t0, $t9, fail
    nop
    li $t9, -1
    bne $t3, $t9, fail
    nop

  /*-------------------------------------------------------------
   * DIVU tests - unsigned divide
   *-------------------------------------------------------------*/

  /* Test 13: Simple unsigned divide */
test_13:
    li TESTNUM, 13
    li $t1, 20
    li $t2, 6
    divu $zero, $t1, $t2
    mflo $t0             /* Quotient = 3 */
    mfhi $t3             /* Remainder = 2 */
    li $t9, 3
    bne $t0, $t9, fail
    nop
    li $t9, 2
    bne $t3, $t9, fail
    nop

  /* Test 14: Large unsigned divide */
test_14:
    li TESTNUM, 14
    li $t1, 0x80000000   /* 2^31 as unsigned */
    li $t2, 0x40000000   /* 2^30 as unsigned */
    divu $zero, $t1, $t2
    mflo $t0             /* Quotient = 2 */
    li $t9, 2
    bne $t0, $t9, fail
    nop

  /*-------------------------------------------------------------
   * MTHI/MTLO tests
   *-------------------------------------------------------------*/

  /* Test 15: Write to HI and read back */
test_15:
    li TESTNUM, 15
    li $t1, 0xDEADBEEF
    mthi $t1
    mfhi $t0
    li $t9, 0xDEADBEEF
    bne $t0, $t9, fail
    nop

  /* Test 16: Write to LO and read back */
test_16:
    li TESTNUM, 16
    li $t1, 0xCAFEBABE
    mtlo $t1
    mflo $t0
    li $t9, 0xCAFEBABE
    bne $t0, $t9, fail
    nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
