/* MIPS32 JR instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /* Basic jr test */
test_2:
  li TESTNUM, 2
  la $t0, target2
  jr $t0
  nop
  j fail
  nop
target2:

  /* JR with different registers */
test_3:
  li TESTNUM, 3
  la $t1, target3
  jr $t1
  nop
  j fail
  nop
target3:

test_4:
  li TESTNUM, 4
  la $t2, target4
  jr $t2
  nop
  j fail
  nop
target4:

  /* JR after computation */
test_5:
  li TESTNUM, 5
  la $t0, target5_base
  li $t1, 8
  addu $t2, $t0, $t1
  jr $t2
  nop
  j fail
  nop
target5_base:
  j fail
  nop
target5:

  /* JR bypass tests */
test_6:
  li TESTNUM, 6
  la $t0, target6
  jr $t0
  nop
  j fail
  nop
target6:

test_7:
  li TESTNUM, 7
  la $t0, target7
  nop
  jr $t0
  nop
  j fail
  nop
target7:

test_8:
  li TESTNUM, 8
  la $t0, target8
  nop
  nop
  jr $t0
  nop
  j fail
  nop
target8:

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
