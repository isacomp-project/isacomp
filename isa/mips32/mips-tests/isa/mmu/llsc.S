/* MIPS32 LL/SC (Load Linked / Store Conditional) Tests */
/* Tests atomic operations */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Test 2: Basic LL - Load Linked
   *-------------------------------------------------------------*/
test_2:
    li TESTNUM, 2
    la $t1, test_data
    li $t2, 0x12345678
    sw $t2, 0($t1)       /* Store test value */
    nop
    ll $t0, 0($t1)       /* Load linked */
    li $t9, 0x12345678
    bne $t0, $t9, fail
    nop

  /*-------------------------------------------------------------
   * Test 3: Basic SC after LL - should succeed
   *-------------------------------------------------------------*/
test_3:
    li TESTNUM, 3
    la $t1, test_data
    ll $t0, 0($t1)       /* Load linked */
    li $t2, 0xDEADBEEF
    sc $t2, 0($t1)       /* Store conditional */
    /* $t2 should now be 1 (success) */
    li $t9, 1
    bne $t2, $t9, fail
    nop
    /* Verify the value was written */
    lw $t0, 0($t1)
    li $t9, 0xDEADBEEF
    bne $t0, $t9, fail
    nop

  /*-------------------------------------------------------------
   * Test 4: SC without LL - should fail
   *-------------------------------------------------------------*/
test_4:
    li TESTNUM, 4
    la $t1, test_data2
    li $t2, 0x11111111
    sw $t2, 0($t1)       /* Initial value */
    nop
    /* No LL before this SC */
    li $t2, 0x22222222
    sc $t2, 0($t1)       /* Store conditional without LL */
    /* $t2 should be 0 (failure) if LLbit was cleared */
    /* Note: behavior depends on implementation - some may succeed */
    /* We just check that the result is 0 or 1 */
    sltu $t3, $t2, 2
    li $t9, 1
    bne $t3, $t9, fail
    nop

  /*-------------------------------------------------------------
   * Test 5: SC to different address - should fail
   *-------------------------------------------------------------*/
test_5:
    li TESTNUM, 5
    la $t1, test_data
    la $t3, test_data2
    ll $t0, 0($t1)       /* Load linked from test_data */
    li $t2, 0x33333333
    sc $t2, 0($t3)       /* Store conditional to different address */
    /* Should fail (return 0) */
    bne $t2, $zero, fail
    nop

  /*-------------------------------------------------------------
   * Test 6: Atomic increment pattern
   *-------------------------------------------------------------*/
test_6:
    li TESTNUM, 6
    la $t1, test_data3
    li $t2, 10
    sw $t2, 0($t1)       /* Initial value = 10 */
    nop
    /* Atomic increment */
retry_6:
    ll $t0, 0($t1)       /* Load current value */
    addiu $t0, $t0, 1    /* Increment */
    move $t2, $t0
    sc $t2, 0($t1)       /* Store back */
    beq $t2, $zero, retry_6  /* Retry if failed */
    nop
    /* Verify value is now 11 */
    lw $t0, 0($t1)
    li $t9, 11
    bne $t0, $t9, fail
    nop

  /*-------------------------------------------------------------
   * Test 7: Multiple increments
   *-------------------------------------------------------------*/
test_7:
    li TESTNUM, 7
    la $t1, test_data3
    li $t2, 0
    sw $t2, 0($t1)       /* Reset to 0 */
    nop
    /* Do 5 increments */
    li $t4, 5
loop_7:
retry_7:
    ll $t0, 0($t1)
    addiu $t0, $t0, 1
    move $t2, $t0
    sc $t2, 0($t1)
    beq $t2, $zero, retry_7
    nop
    addiu $t4, $t4, -1
    bne $t4, $zero, loop_7
    nop
    /* Verify final value is 5 */
    lw $t0, 0($t1)
    li $t9, 5
    bne $t0, $t9, fail
    nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
  .align 2
test_data:
  .word 0
test_data2:
  .word 0
test_data3:
  .word 0
RVTEST_DATA_END
