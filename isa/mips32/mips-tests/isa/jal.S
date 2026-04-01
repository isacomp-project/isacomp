/* MIPS32 JAL instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /* Basic jal test */
test_2:
  li TESTNUM, 2
  jal target2
  nop
  j cont2
  nop
target2:
  jr $ra
  nop
cont2:

  /* JAL return address test */
test_3:
  li TESTNUM, 3
  la $t0, ret_addr3
  jal target3
  nop
ret_addr3:
  j cont3
  nop
target3:
  /* ra should point to ret_addr3 (jal sets ra = pc + 8, the instruction after the delay slot) */
  bne $ra, $t0, fail
  nop
  jr $ra
  nop
cont3:

  /* Nested function calls */
test_4:
  li TESTNUM, 4
  li $t0, 0
  jal func1
  nop
  li $t9, 3
  bne $t0, $t9, fail
  nop
  j done4
  nop

func1:
  addi $sp, $sp, -4
  sw $ra, 0($sp)
  addi $t0, $t0, 1
  jal func2
  nop
  lw $ra, 0($sp)
  addi $sp, $sp, 4
  jr $ra
  nop

func2:
  addi $sp, $sp, -4
  sw $ra, 0($sp)
  addi $t0, $t0, 1
  jal func3
  nop
  lw $ra, 0($sp)
  addi $sp, $sp, 4
  jr $ra
  nop

func3:
  addi $t0, $t0, 1
  jr $ra
  nop

done4:

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
