/* MIPS32 Delay Slot Tests */
/* Tests that validate correct behavior with and without delay slots. */
/* Build with -DDELAY_SLOT to test delay-slot-aware designs; */
/* build without to test non-delay-slot designs. */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Test 2: J delay slot - instruction after unconditional jump
   * With delay slots: addi executes before jump takes effect
   * Without delay slots: addi is skipped
   *-------------------------------------------------------------*/
test_2:
  li TESTNUM, 2
  li $t0, 42
  j ds_target2
  addi $t0, $t0, 1    /* delay slot or skipped */
  j fail
  nop
ds_target2:
#ifdef DELAY_SLOT
  li $t9, 43           /* delay slot executed: 42+1=43 */
#else
  li $t9, 42           /* delay slot skipped: still 42 */
#endif
  bne $t0, $t9, fail
  nop

  /*-------------------------------------------------------------
   * Test 3: BEQ taken - delay slot with taken branch
   *-------------------------------------------------------------*/
test_3:
  li TESTNUM, 3
  li $t0, 10
  li $t1, 5
  li $t2, 5
  beq $t1, $t2, ds_target3
  addi $t0, $t0, 7     /* delay slot or skipped */
  j fail
  nop
ds_target3:
#ifdef DELAY_SLOT
  li $t9, 17           /* delay slot executed: 10+7=17 */
#else
  li $t9, 10           /* delay slot skipped: still 10 */
#endif
  bne $t0, $t9, fail
  nop

  /*-------------------------------------------------------------
   * Test 4: BEQ not taken - instruction at pc+4 always executes
   * (Both modes should execute the instruction after a not-taken branch)
   *-------------------------------------------------------------*/
test_4:
  li TESTNUM, 4
  li $t0, 10
  li $t1, 5
  li $t2, 6
  beq $t1, $t2, fail   /* not taken */
  addi $t0, $t0, 3     /* always executes (delay slot or sequential) */
  li $t9, 13            /* 10+3=13 in both modes */
  bne $t0, $t9, fail
  nop

  /*-------------------------------------------------------------
   * Test 5: BNE taken - delay slot with taken branch
   *-------------------------------------------------------------*/
test_5:
  li TESTNUM, 5
  li $t0, 100
  li $t1, 1
  li $t2, 2
  bne $t1, $t2, ds_target5
  addi $t0, $t0, -50   /* delay slot or skipped */
  j fail
  nop
ds_target5:
#ifdef DELAY_SLOT
  li $t9, 50           /* delay slot executed: 100-50=50 */
#else
  li $t9, 100          /* delay slot skipped: still 100 */
#endif
  bne $t0, $t9, fail
  nop

  /*-------------------------------------------------------------
   * Test 6: JAL delay slot + return address
   * JAL sets ra = pc+8 (after delay slot) in both modes.
   * With delay slots, the delay slot instruction executes.
   *-------------------------------------------------------------*/
test_6:
  li TESTNUM, 6
  li $t0, 0
  jal ds_func6
  addi $t0, $t0, 1     /* delay slot or skipped */
  /* After return, check $t0 */
#ifdef DELAY_SLOT
  li $t9, 1            /* delay slot executed */
#else
  li $t9, 0            /* delay slot skipped */
#endif
  bne $t0, $t9, fail
  nop
  j ds_cont6
  nop
ds_func6:
  jr $ra
  nop
ds_cont6:

  /*-------------------------------------------------------------
   * Test 7: JR delay slot
   *-------------------------------------------------------------*/
test_7:
  li TESTNUM, 7
  li $t0, 20
  la $t1, ds_target7
  jr $t1
  addi $t0, $t0, 5     /* delay slot or skipped */
  j fail
  nop
ds_target7:
#ifdef DELAY_SLOT
  li $t9, 25           /* delay slot executed: 20+5=25 */
#else
  li $t9, 20           /* delay slot skipped: still 20 */
#endif
  bne $t0, $t9, fail
  nop

  /*-------------------------------------------------------------
   * Test 8: JALR delay slot
   *-------------------------------------------------------------*/
test_8:
  li TESTNUM, 8
  li $t0, 30
  la $t1, ds_func8
  jalr $ra, $t1
  addi $t0, $t0, 2     /* delay slot or skipped */
  /* After return */
#ifdef DELAY_SLOT
  li $t9, 32           /* delay slot executed: 30+2=32 */
#else
  li $t9, 30           /* delay slot skipped: still 30 */
#endif
  bne $t0, $t9, fail
  nop
  j ds_cont8
  nop
ds_func8:
  jr $ra
  nop
ds_cont8:

  /*-------------------------------------------------------------
   * Test 9: Delay slot does not chain
   * A branch in the delay slot should NOT create another delay slot.
   * Here the delay slot is a regular ALU instruction; the point is
   * that only ONE delay slot instruction executes.
   *-------------------------------------------------------------*/
test_9:
  li TESTNUM, 9
  li $t0, 0
  j ds_target9a
  addi $t0, $t0, 1     /* delay slot - should execute (or be skipped) */
  addi $t0, $t0, 100   /* should NEVER execute in either mode */
  j fail
  nop
ds_target9a:
#ifdef DELAY_SLOT
  li $t9, 1            /* only the delay slot addi executed */
#else
  li $t9, 0            /* nothing after j executed */
#endif
  bne $t0, $t9, fail
  nop

  /*-------------------------------------------------------------
   * Test 10: Two consecutive jumps - each has its own delay slot
   *-------------------------------------------------------------*/
test_10:
  li TESTNUM, 10
  li $t0, 0
  j ds_target10a
  addi $t0, $t0, 1     /* first delay slot or skipped */
  j fail
  nop
ds_target10a:
  j ds_target10b
  addi $t0, $t0, 2     /* second delay slot or skipped */
  j fail
  nop
ds_target10b:
#ifdef DELAY_SLOT
  li $t9, 3            /* both delay slots executed: 0+1+2=3 */
#else
  li $t9, 0            /* neither delay slot executed */
#endif
  bne $t0, $t9, fail
  nop

  /*-------------------------------------------------------------
   * Test 11: JAL return address is pc+8 in both modes
   * This verifies the return address calculation is correct.
   *-------------------------------------------------------------*/
test_11:
  li TESTNUM, 11
  la $t0, ds_ret11
  jal ds_func11
  nop
ds_ret11:
  j ds_cont11
  nop
ds_func11:
  /* ra should equal ds_ret11 (pc+8 from the jal instruction) */
  bne $ra, $t0, fail
  nop
  jr $ra
  nop
ds_cont11:

  /*-------------------------------------------------------------
   * Test 12: Delay slot with store instruction
   * Verifies memory writes in delay slots take effect.
   *-------------------------------------------------------------*/
test_12:
  li TESTNUM, 12
  la $t1, ds_data12
  li $t2, 0
  sw $t2, 0($t1)       /* clear the data word */
  li $t2, 0xABCD
  j ds_target12
  sw $t2, 0($t1)       /* store in delay slot or skipped */
  j fail
  nop
ds_target12:
  lw $t0, 0($t1)
#ifdef DELAY_SLOT
  li $t9, 0xABCD       /* store executed in delay slot */
#else
  li $t9, 0            /* store skipped, word still 0 */
#endif
  bne $t0, $t9, fail
  nop

  /*-------------------------------------------------------------
   * Test 13: Delay slot with load instruction
   * Verifies memory reads in delay slots work.
   *-------------------------------------------------------------*/
test_13:
  li TESTNUM, 13
  la $t1, ds_data13
  li $t2, 0x1234
  sw $t2, 0($t1)       /* store test value */
  li $t0, 0
  j ds_target13
  lw $t0, 0($t1)       /* load in delay slot or skipped */
  j fail
  nop
ds_target13:
#ifdef DELAY_SLOT
  li $t9, 0x1234       /* load executed in delay slot */
#else
  li $t9, 0            /* load skipped, $t0 still 0 */
#endif
  bne $t0, $t9, fail
  nop

  /*-------------------------------------------------------------
   * Test 14: Delay slot modifying branch source register
   * Tests that delay slot writing a register used by the branch
   * does NOT affect the branch decision (branch reads happen first).
   *-------------------------------------------------------------*/
test_14:
  li TESTNUM, 14
  li $t1, 5
  li $t2, 5
  beq $t1, $t2, ds_target14  /* branch should be TAKEN (5==5) */
  li $t1, 99                  /* delay slot modifies $t1, but branch already decided */
  j fail                      /* should not reach here */
  nop
ds_target14:
  /* Verify $t1 was modified by delay slot (or not) */
#ifdef DELAY_SLOT
  li $t9, 99           /* delay slot set $t1 = 99 */
#else
  li $t9, 5            /* delay slot skipped, $t1 still 5 */
#endif
  bne $t1, $t9, fail
  nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
  .align 2
ds_data12: .word 0
ds_data13: .word 0
RVTEST_DATA_END
