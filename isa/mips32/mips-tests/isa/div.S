/* MIPS32 DIV instruction tests */
/* div rs, rt - Divide (signed, quotient in LO, remainder in HI) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic DIV tests - check LO (quotient) and HI (remainder)
   *-------------------------------------------------------------*/

  /* Test 2: 20 / 6 = 3 remainder 2 */
test_2:
    li TESTNUM, 2
    li $t1, 20
    li $t2, 6
    div $zero, $t1, $t2
    mflo $t0
    li $t9, 3
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, 2
    bne $t0, $t9, fail
    nop

  /* Test 3: 10 / 5 = 2 remainder 0 */
test_3:
    li TESTNUM, 3
    li $t1, 10
    li $t2, 5
    div $zero, $t1, $t2
    mflo $t0
    li $t9, 2
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, 0
    bne $t0, $t9, fail
    nop

  /* Test 4: -20 / 6 = -3 remainder -2 */
test_4:
    li TESTNUM, 4
    li $t1, -20
    li $t2, 6
    div $zero, $t1, $t2
    mflo $t0
    li $t9, -3
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, -2
    bne $t0, $t9, fail
    nop

  /* Test 5: 20 / -6 = -3 remainder 2 */
test_5:
    li TESTNUM, 5
    li $t1, 20
    li $t2, -6
    div $zero, $t1, $t2
    mflo $t0
    li $t9, -3
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, 2
    bne $t0, $t9, fail
    nop

  /* Test 6: -20 / -6 = 3 remainder -2 */
test_6:
    li TESTNUM, 6
    li $t1, -20
    li $t2, -6
    div $zero, $t1, $t2
    mflo $t0
    li $t9, 3
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, -2
    bne $t0, $t9, fail
    nop

  /* Test 7: 0 / 5 = 0 remainder 0 */
test_7:
    li TESTNUM, 7
    li $t1, 0
    li $t2, 5
    div $zero, $t1, $t2
    mflo $t0
    li $t9, 0
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, 0
    bne $t0, $t9, fail
    nop

  /* Test 8: Large division */
test_8:
    li TESTNUM, 8
    li $t1, 0x7FFFFFFF
    li $t2, 2
    div $zero, $t1, $t2
    mflo $t0
    li $t9, 0x3FFFFFFF
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, 1
    bne $t0, $t9, fail
    nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
