/* MIPS32 SW instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /* Basic store tests */
test_2:
  li TESTNUM, 2
  la $t0, tdat
  li $t1, 0xaabbccdd
  sw $t1, 0($t0)
  lw $t2, 0($t0)
  li $t9, 0xaabbccdd
  bne $t2, $t9, fail
  nop

test_3:
  li TESTNUM, 3
  la $t0, tdat
  li $t1, 0x11223344
  sw $t1, 4($t0)
  lw $t2, 4($t0)
  li $t9, 0x11223344
  bne $t2, $t9, fail
  nop

test_4:
  li TESTNUM, 4
  la $t0, tdat
  li $t1, 0x55667788
  sw $t1, 8($t0)
  lw $t2, 8($t0)
  li $t9, 0x55667788
  bne $t2, $t9, fail
  nop

  /* Negative offset */
test_5:
  li TESTNUM, 5
  la $t0, tdat4
  li $t1, 0x99aabbcc
  sw $t1, -12($t0)
  lw $t2, -12($t0)
  li $t9, 0x99aabbcc
  bne $t2, $t9, fail
  nop

  /* Store-load bypass */
test_6:
  li TESTNUM, 6
  la $t0, tdat
  li $t1, 0xdeadbeef
  sw $t1, 0($t0)
  lw $t2, 0($t0)
  li $t9, 0xdeadbeef
  bne $t2, $t9, fail
  nop

test_7:
  li TESTNUM, 7
  la $t0, tdat
  li $t1, 0xcafebabe
  sw $t1, 4($t0)
  nop
  lw $t2, 4($t0)
  li $t9, 0xcafebabe
  bne $t2, $t9, fail
  nop

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  .align 4
tdat:
tdat1: .word 0
tdat2: .word 0
tdat3: .word 0
tdat4: .word 0
RVTEST_DATA_END
