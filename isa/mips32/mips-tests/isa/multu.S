/* MIPS32 MULTU instruction tests */
/* multu rs, rt - Multiply Unsigned (result in HI/LO) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic MULTU tests
   *-------------------------------------------------------------*/

  /* Test 2: 0 * 0 = 0 */
test_2:
    li TESTNUM, 2
    li $t1, 0
    li $t2, 0
    multu $t1, $t2
    mflo $t0
    li $t9, 0
    bne $t0, $t9, fail
    nop

  /* Test 3: 2 * 3 = 6 */
test_3:
    li TESTNUM, 3
    li $t1, 2
    li $t2, 3
    multu $t1, $t2
    mflo $t0
    li $t9, 6
    bne $t0, $t9, fail
    nop

  /* Test 4: 0xFFFFFFFF * 1 = 0xFFFFFFFF, HI = 0 */
test_4:
    li TESTNUM, 4
    li $t1, 0xFFFFFFFF
    li $t2, 1
    multu $t1, $t2
    mflo $t0
    li $t9, 0xFFFFFFFF
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, 0
    bne $t0, $t9, fail
    nop

  /* Test 5: 0xFFFFFFFF * 0xFFFFFFFF = large result */
test_5:
    li TESTNUM, 5
    li $t1, 0xFFFFFFFF
    li $t2, 0xFFFFFFFF
    multu $t1, $t2
    mflo $t0
    li $t9, 0x00000001
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, 0xFFFFFFFE
    bne $t0, $t9, fail
    nop

  /* Test 6: 0x10000 * 0x10000 = 0x100000000 */
test_6:
    li TESTNUM, 6
    li $t1, 0x00010000
    li $t2, 0x00010000
    multu $t1, $t2
    mflo $t0
    li $t9, 0x00000000
    bne $t0, $t9, fail
    nop
    mfhi $t0
    li $t9, 0x00000001
    bne $t0, $t9, fail
    nop

  /* Test 7: 100 * 200 = 20000 */
test_7:
    li TESTNUM, 7
    li $t1, 100
    li $t2, 200
    multu $t1, $t2
    mflo $t0
    li $t9, 20000
    bne $t0, $t9, fail
    nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
