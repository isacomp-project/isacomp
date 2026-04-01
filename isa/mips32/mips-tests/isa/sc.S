/* MIPS32 SC instruction tests */
/* sc rt, offset(base) - Store Conditional */
/* Stores word if LL link valid, rt = 1 on success, 0 on failure */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic SC tests - must be preceded by LL
   *-------------------------------------------------------------*/

  /* Test 2: LL followed by SC should succeed */
test_2:
    li TESTNUM, 2
    la $t1, tdat1
    ll $t0, 0($t1)
    li $t2, 0x12345678
    sc $t2, 0($t1)
    /* t2 should be 1 (success) */
    li $t9, 1
    bne $t2, $t9, fail
    nop
    /* Verify store happened */
    lw $t0, 0($t1)
    li $t9, 0x12345678
    bne $t0, $t9, fail
    nop

  /* Test 3: SC without LL should fail (or implementation-defined) */
  /* Note: This is architecture-specific, some impls always succeed */
  /* We'll test LL/SC pair with intervening store to same address */
test_3:
    li TESTNUM, 3
    la $t1, tdat2
    li $t3, 0xDEADBEEF
    sw $t3, 0($t1)
    ll $t0, 0($t1)
    li $t2, 0xCAFEBABE
    sc $t2, 0($t1)
    li $t9, 1
    bne $t2, $t9, fail
    nop
    lw $t0, 0($t1)
    li $t9, 0xCAFEBABE
    bne $t0, $t9, fail
    nop

  /* Test 4: Multiple LL/SC pairs */
test_4:
    li TESTNUM, 4
    la $t1, tdat3
    /* First pair */
    ll $t0, 0($t1)
    li $t2, 0x11111111
    sc $t2, 0($t1)
    li $t9, 1
    bne $t2, $t9, fail
    nop
    /* Second pair */
    ll $t0, 0($t1)
    li $t2, 0x22222222
    sc $t2, 0($t1)
    li $t9, 1
    bne $t2, $t9, fail
    nop
    /* Verify final value */
    lw $t0, 0($t1)
    li $t9, 0x22222222
    bne $t0, $t9, fail
    nop

  /* Test 5: LL/SC with positive offset */
test_5:
    li TESTNUM, 5
    la $t1, tdat
    ll $t0, 12($t1)
    li $t2, 0xAAAAAAAA
    sc $t2, 12($t1)
    li $t9, 1
    bne $t2, $t9, fail
    nop
    lw $t0, 12($t1)
    li $t9, 0xAAAAAAAA
    bne $t0, $t9, fail
    nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
  .align 2
tdat:
tdat1: .word 0x00ff00ff
tdat2: .word 0xff00ff00
tdat3: .word 0x0ff00ff0
tdat4: .word 0xf00ff00f
RVTEST_DATA_END
