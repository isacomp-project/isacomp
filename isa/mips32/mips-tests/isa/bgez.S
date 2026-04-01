/* MIPS32 BGEZ instruction tests */
/* bgez rs, offset - Branch on Greater Than or Equal to Zero */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch taken tests
   *-------------------------------------------------------------*/

  /* Test 2: Branch on zero (should be taken) */
test_2:
    li TESTNUM, 2
    li $t1, 0
    bgez $t1, 1f
    nop
    j fail
    nop
1:

  /* Test 3: Branch on positive (should be taken) */
test_3:
    li TESTNUM, 3
    li $t1, 1
    bgez $t1, 1f
    nop
    j fail
    nop
1:

  /* Test 4: Branch on large positive (should be taken) */
test_4:
    li TESTNUM, 4
    li $t1, 0x7FFFFFFF
    bgez $t1, 1f
    nop
    j fail
    nop
1:

  /*-------------------------------------------------------------
   * Branch not taken tests
   *-------------------------------------------------------------*/

  /* Test 5: Branch on -1 (should not be taken) */
test_5:
    li TESTNUM, 5
    li $t1, -1
    bgez $t1, fail
    nop

  /* Test 6: Branch on -2 (should not be taken) */
test_6:
    li TESTNUM, 6
    li $t1, -2
    bgez $t1, fail
    nop

  /* Test 7: Branch on 0x80000000 (should not be taken) */
test_7:
    li TESTNUM, 7
    li $t1, 0x80000000
    bgez $t1, fail
    nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
