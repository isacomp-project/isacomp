/* MIPS32 LW instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /* Basic load tests */
test_2:
  li TESTNUM, 2
  la $t0, tdat
  lw $t1, 0($t0)
  li $t9, 0x00ff00ff
  bne $t1, $t9, fail
  nop

test_3:
  li TESTNUM, 3
  la $t0, tdat
  lw $t1, 4($t0)
  li $t9, 0xff00ff00
  bne $t1, $t9, fail
  nop

test_4:
  li TESTNUM, 4
  la $t0, tdat
  lw $t1, 8($t0)
  li $t9, 0x0ff00ff0
  bne $t1, $t9, fail
  nop

test_5:
  li TESTNUM, 5
  la $t0, tdat
  lw $t1, 12($t0)
  li $t9, 0xf00ff00f
  bne $t1, $t9, fail
  nop

  /* Negative offset */
test_6:
  li TESTNUM, 6
  la $t0, tdat4
  lw $t1, -12($t0)
  li $t9, 0x00ff00ff
  bne $t1, $t9, fail
  nop

test_7:
  li TESTNUM, 7
  la $t0, tdat4
  lw $t1, -8($t0)
  li $t9, 0xff00ff00
  bne $t1, $t9, fail
  nop

  /* Bypass tests */
test_8:
  li TESTNUM, 8
  la $t0, tdat
  lw $t1, 0($t0)
  addi $t2, $t1, 0
  li $t9, 0x00ff00ff
  bne $t2, $t9, fail
  nop

test_9:
  li TESTNUM, 9
  la $t0, tdat
  lw $t1, 4($t0)
  nop
  addi $t2, $t1, 0
  li $t9, 0xff00ff00
  bne $t2, $t9, fail
  nop

  /* Zero dest test */
test_10:
  li TESTNUM, 10
  la $t0, tdat
  lw $zero, 0($t0)
  bne $zero, $0, fail
  nop

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  .align 4
tdat:
tdat1: .word 0x00ff00ff
tdat2: .word 0xff00ff00
tdat3: .word 0x0ff00ff0
tdat4: .word 0xf00ff00f
RVTEST_DATA_END
