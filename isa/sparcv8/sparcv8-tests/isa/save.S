/* SPARCv8 SAVE instruction tests */
/* Tests SAVE arithmetic and window switching behavior */
/* SAVE: CWP <- CWP-1, rd(new) <- rs1(old) + operand2(old) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Test 2: SAVE with two registers
   * Computes rs1 + rs2, stores result in new window's rd
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    mov 100, %l1              /* Set up in current window */
    mov 50, %l2
    save %l1, %l2, %l0        /* New window's l0 = 100 + 50 = 150 */
    /* Now in new window */
    cmp %l0, 150
    bne fail
    nop
    restore %g0, %g0, %g0     /* Return to original window */

  /*-------------------------------------------------------------
   * Test 3: SAVE with immediate operand
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    mov 100, %l1
    save %l1, 10, %l0         /* New window's l0 = 100 + 10 = 110 */
    cmp %l0, 110
    bne fail
    nop
    restore %g0, %g0, %g0

  /*-------------------------------------------------------------
   * Test 4: SAVE with negative immediate
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    mov 100, %l1
    save %l1, -96, %l0        /* New window's l0 = 100 - 96 = 4 */
    cmp %l0, 4
    bne fail
    nop
    restore %g0, %g0, %g0

  /*-------------------------------------------------------------
   * Test 5: SAVE to %g0 discards result (global 0 always 0)
   *-------------------------------------------------------------*/
test_5:
    mov 5, TESTNUM
    mov 100, %l1
    save %l1, 50, %g0         /* Result discarded */
    /* %g0 should still be 0 */
    cmp %g0, 0
    bne fail
    nop
    restore %g0, %g0, %g0

  /*-------------------------------------------------------------
   * Test 6: SAVE with %g0 as rs1 source
   *-------------------------------------------------------------*/
test_6:
    mov 6, TESTNUM
    mov 25, %l1
    save %g0, %l1, %l0        /* New window's l0 = 0 + 25 = 25 */
    cmp %l0, 25
    bne fail
    nop
    restore %g0, %g0, %g0

  /*-------------------------------------------------------------
   * Test 7: SAVE with %g0 as rs2 source
   *-------------------------------------------------------------*/
test_7:
    mov 7, TESTNUM
    mov 42, %l1
    save %l1, %g0, %l0        /* New window's l0 = 42 + 0 = 42 */
    cmp %l0, 42
    bne fail
    nop
    restore %g0, %g0, %g0

  /*-------------------------------------------------------------
   * Test 8: SAVE reads rs1 from OLD window (using outs)
   * After SAVE, old window's outs become new window's ins
   *-------------------------------------------------------------*/
test_8:
    mov 8, TESTNUM
    mov 0x55, %o0             /* Value in current window's out */
    mov 0x11, %o1             /* Another value in outs */
    save %o0, %o1, %l0        /* Result = 0x55 + 0x11 = 0x66 */
    /* Check the arithmetic result */
    cmp %l0, 0x66
    bne fail
    nop
    /* Also verify the out-to-in overlap: our i0 should be old o0 */
    cmp %i0, 0x55
    bne fail
    nop
    cmp %i1, 0x11
    bne fail
    nop
    restore %g0, %g0, %g0

  /*-------------------------------------------------------------
   * Test 9: SAVE result to output register (o-register in new window)
   *-------------------------------------------------------------*/
test_9:
    mov 9, TESTNUM
    mov 20, %l1
    mov 30, %l2
    save %l1, %l2, %o0        /* New window's o0 = 20 + 30 = 50 */
    cmp %o0, 50
    bne fail
    nop
    restore %g0, %g0, %g0

  /*-------------------------------------------------------------
   * Test 10: SAVE result to input register (i-register in new window)
   * Note: i-registers overlap with caller's outs, so this overwrites
   *-------------------------------------------------------------*/
test_10:
    mov 10, TESTNUM
    mov 0x77, %o0             /* This will become new window's i0 */
    mov 7, %l1
    mov 3, %l2
    save %l1, %l2, %i0        /* New window's i0 = 7 + 3 = 10 */
    /* i0 was overwritten by save result */
    cmp %i0, 10
    bne fail
    nop
    restore %g0, %g0, %g0

  /*-------------------------------------------------------------
   * Test 11: Nested SAVE - verify window depth
   *-------------------------------------------------------------*/
test_11:
    mov 11, TESTNUM
    mov 1, %l0                /* Window 0: l0 = 1 */
    save %g0, 2, %l0          /* Window 1: l0 = 2 */
    save %g0, 3, %l0          /* Window 2: l0 = 3 */
    /* Check window 2's local */
    cmp %l0, 3
    bne fail
    nop
    restore %g0, %g0, %g0     /* Back to window 1 */
    cmp %l0, 2
    bne fail
    nop
    restore %g0, %g0, %g0     /* Back to window 0 */
    cmp %l0, 1
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 12: SAVE with large immediate (max positive simm13)
   *-------------------------------------------------------------*/
test_12:
    mov 12, TESTNUM
    mov 0, %l1
    save %l1, 0xFFF, %l0      /* 0 + 4095 = 4095 */
    cmp %l0, 0xFFF
    bne fail
    nop
    restore %g0, %g0, %g0

  /*-------------------------------------------------------------
   * Test 13: SAVE preserves caller's locals through round-trip
   *-------------------------------------------------------------*/
test_13:
    mov 13, TESTNUM
    mov 0xAB, %l4             /* Store in local */
    mov 0xCD, %l5             /* Store in another local */
    save %g0, %g0, %g0        /* Go to new window */
    /* Do some work in callee - shouldn't affect caller's locals */
    mov 0xFF, %l4
    mov 0xEE, %l5
    restore %g0, %g0, %g0     /* Return to caller */
    /* Caller's locals should be unchanged */
    cmp %l4, 0xAB
    bne fail
    nop
    cmp %l5, 0xCD
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 14: SAVE with stack pointer setup (typical use case)
   * sp (o6) typically decremented by frame size
   *-------------------------------------------------------------*/
test_14:
    mov 14, TESTNUM
    set 0x1000, %o6           /* Set stack pointer = 4096 */
    save %o6, -96, %o6        /* New sp = old sp - 96 = 4000 */
    /* In new window: o6 (new sp) should be 0x1000 - 96 = 0xFA0 */
    set 0xFA0, %l0
    cmp %o6, %l0
    bne fail
    nop
    restore %g0, %g0, %g0

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
