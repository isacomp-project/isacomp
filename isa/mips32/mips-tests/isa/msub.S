/* MIPS32 MSUB instruction tests */
/* msub rs, rt - Multiply and Subtract (HI,LO -= rs * rt) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic MSUB tests
   *-------------------------------------------------------------*/

  /* Test 2: 100 - 2*3 = 94 */
test_2:
    li TESTNUM, 2
    li $t3, 100
    mtlo $t3
    mthi $zero
    li $t1, 2
    li $t2, 3
    msub $t1, $t2
    mflo $t0
    li $t9, 94
    bne $t0, $t9, fail
    nop

  /* Test 3: 50 - 5*5 = 25 */
test_3:
    li TESTNUM, 3
    li $t3, 50
    mtlo $t3
    mthi $zero
    li $t1, 5
    li $t2, 5
    msub $t1, $t2
    mflo $t0
    li $t9, 25
    bne $t0, $t9, fail
    nop

  /* Test 4: 100 - (-2)*3 = 106 */
test_4:
    li TESTNUM, 4
    li $t3, 100
    mtlo $t3
    mthi $zero
    li $t1, -2
    li $t2, 3
    msub $t1, $t2
    mflo $t0
    li $t9, 106
    bne $t0, $t9, fail
    nop

  /* Test 5: 100 - (-2)*(-3) = 94 */
test_5:
    li TESTNUM, 5
    li $t3, 100
    mtlo $t3
    mthi $zero
    li $t1, -2
    li $t2, -3
    msub $t1, $t2
    mflo $t0
    li $t9, 94
    bne $t0, $t9, fail
    nop

  /* Test 6: Chain: 100 - 3*3 - 2*2 = 87 */
test_6:
    li TESTNUM, 6
    li $t3, 100
    mtlo $t3
    mthi $zero
    li $t1, 3
    li $t2, 3
    msub $t1, $t2
    li $t1, 2
    li $t2, 2
    msub $t1, $t2
    mflo $t0
    li $t9, 87
    bne $t0, $t9, fail
    nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
