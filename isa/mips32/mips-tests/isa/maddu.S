/* MIPS32 MADDU instruction tests */
/* maddu rs, rt - Multiply and Add Unsigned (HI,LO += rs * rt) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic MADDU tests
   *-------------------------------------------------------------*/

  /* Test 2: Initialize HI/LO to 0, then 2*3 = 6 */
test_2:
    li TESTNUM, 2
    mtlo $zero
    mthi $zero
    li $t1, 2
    li $t2, 3
    maddu $t1, $t2
    mflo $t0
    li $t9, 6
    bne $t0, $t9, fail
    nop

  /* Test 3: 10 + 2*3 = 16 */
test_3:
    li TESTNUM, 3
    li $t3, 10
    mtlo $t3
    mthi $zero
    li $t1, 2
    li $t2, 3
    maddu $t1, $t2
    mflo $t0
    li $t9, 16
    bne $t0, $t9, fail
    nop

  /* Test 4: Accumulate: 0 + 5*5 + 3*3 = 34 */
test_4:
    li TESTNUM, 4
    mtlo $zero
    mthi $zero
    li $t1, 5
    li $t2, 5
    maddu $t1, $t2
    li $t1, 3
    li $t2, 3
    maddu $t1, $t2
    mflo $t0
    li $t9, 34
    bne $t0, $t9, fail
    nop

  /* Test 5: Large unsigned: 0 + 0x10000 * 0x10000 = 0x100000000 */
test_5:
    li TESTNUM, 5
    mtlo $zero
    mthi $zero
    li $t1, 0x00010000
    li $t2, 0x00010000
    maddu $t1, $t2
    mflo $t0
    li $t9, 0
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, 1
    bne $t0, $t9, fail
    nop

  /* Test 6: 100 + 10*10 = 200 */
test_6:
    li TESTNUM, 6
    li $t3, 100
    mtlo $t3
    mthi $zero
    li $t1, 10
    li $t2, 10
    maddu $t1, $t2
    mflo $t0
    li $t9, 200
    bne $t0, $t9, fail
    nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
