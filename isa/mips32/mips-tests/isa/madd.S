/* MIPS32 MADD instruction tests */
/* madd rs, rt - Multiply and Add (HI,LO += rs * rt) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic MADD tests
   *-------------------------------------------------------------*/

  /* Test 2: Initialize HI/LO to 0, then 2*3 = 6 */
test_2:
    li TESTNUM, 2
    mtlo $zero
    mthi $zero
    li $t1, 2
    li $t2, 3
    madd $t1, $t2
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
    madd $t1, $t2
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
    madd $t1, $t2
    li $t1, 3
    li $t2, 3
    madd $t1, $t2
    mflo $t0
    li $t9, 34
    bne $t0, $t9, fail
    nop

  /* Test 5: Negative multiply: 100 + (-2)*3 = 94 */
test_5:
    li TESTNUM, 5
    li $t3, 100
    mtlo $t3
    mthi $zero
    li $t1, -2
    li $t2, 3
    madd $t1, $t2
    mflo $t0
    li $t9, 94
    bne $t0, $t9, fail
    nop

  /* Test 6: Both negative: 100 + (-2)*(-3) = 106 */
test_6:
    li TESTNUM, 6
    li $t3, 100
    mtlo $t3
    mthi $zero
    li $t1, -2
    li $t2, -3
    madd $t1, $t2
    mflo $t0
    li $t9, 106
    bne $t0, $t9, fail
    nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
