/* MIPS32 J instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /* Basic jump test */
test_2:
  li TESTNUM, 2
  j target2
  nop
  j fail
  nop
target2:

  /* Jump forward */
test_3:
  li TESTNUM, 3
  j target3
  nop
  j fail
  nop
target3a:
  j target3b
  nop
  j fail
  nop
target3:
  j target3a
  nop
  j fail
  nop
target3b:

  /* Multiple jumps in sequence */
test_4:
  li TESTNUM, 4
  li $t0, 0
  j step1
  nop
step4:
  addi $t0, $t0, 1
  j done4
  nop
step3:
  addi $t0, $t0, 1
  j step4
  nop
step2:
  addi $t0, $t0, 1
  j step3
  nop
step1:
  addi $t0, $t0, 1
  j step2
  nop
done4:
  li $t9, 4
  bne $t0, $t9, fail
  nop

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
