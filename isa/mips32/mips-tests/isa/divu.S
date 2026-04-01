/* MIPS32 DIVU instruction tests */
/* divu rs, rt - Divide Unsigned (quotient in LO, remainder in HI) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic DIVU tests
   *-------------------------------------------------------------*/

  /* Test 2: 20 / 6 = 3 remainder 2 */
test_2:
    li TESTNUM, 2
    li $t1, 20
    li $t2, 6
    divu $zero, $t1, $t2
    mflo $t0
    li $t9, 3
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, 2
    bne $t0, $t9, fail
    nop

  /* Test 3: 0xFFFFFFFF / 2 = 0x7FFFFFFF remainder 1 */
test_3:
    li TESTNUM, 3
    li $t1, 0xFFFFFFFF
    li $t2, 2
    divu $zero, $t1, $t2
    mflo $t0
    li $t9, 0x7FFFFFFF
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, 1
    bne $t0, $t9, fail
    nop

  /* Test 4: 100 / 10 = 10 remainder 0 */
test_4:
    li TESTNUM, 4
    li $t1, 100
    li $t2, 10
    divu $zero, $t1, $t2
    mflo $t0
    li $t9, 10
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, 0
    bne $t0, $t9, fail
    nop

  /* Test 5: 0 / 5 = 0 remainder 0 */
test_5:
    li TESTNUM, 5
    li $t1, 0
    li $t2, 5
    divu $zero, $t1, $t2
    mflo $t0
    li $t9, 0
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, 0
    bne $t0, $t9, fail
    nop

  /* Test 6: 0x80000000 / 2 = 0x40000000 (unsigned) */
test_6:
    li TESTNUM, 6
    li $t1, 0x80000000
    li $t2, 2
    divu $zero, $t1, $t2
    mflo $t0
    li $t9, 0x40000000
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, 0
    bne $t0, $t9, fail
    nop

  /* Test 7: 17 / 5 = 3 remainder 2 */
test_7:
    li TESTNUM, 7
    li $t1, 17
    li $t2, 5
    divu $zero, $t1, $t2
    mflo $t0
    li $t9, 3
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, 2
    bne $t0, $t9, fail
    nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
