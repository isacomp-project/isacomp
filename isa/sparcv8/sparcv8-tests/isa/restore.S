/* SPARCv8 RESTORE instruction tests */
/* Tests RESTORE arithmetic and window switching behavior */
/* RESTORE: CWP <- CWP+1, rd(new) <- rs1(old) + operand2(old) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Test 2: RESTORE with two registers
   * Computes rs1 + rs2 (from callee window), stores in caller's rd
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    save %g0, %g0, %g0        /* Enter callee window */
    mov 10, %l1               /* Set up operands in callee window */
    mov 20, %l2
    restore %l1, %l2, %l0     /* Caller's l0 = 10 + 20 = 30 */
    /* Now back in caller window */
    cmp %l0, 30
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 3: RESTORE with immediate operand
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    save %g0, %g0, %g0
    mov 100, %l1
    restore %l1, 15, %l0      /* Caller's l0 = 100 + 15 = 115 */
    cmp %l0, 115
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 4: RESTORE with negative immediate
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    save %g0, %g0, %g0
    mov 100, %l1
    restore %l1, -50, %l0     /* Caller's l0 = 100 - 50 = 50 */
    cmp %l0, 50
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 5: RESTORE to %g0 discards result
   *-------------------------------------------------------------*/
test_5:
    mov 5, TESTNUM
    save %g0, %g0, %g0
    mov 100, %l1
    restore %l1, 50, %g0      /* Result discarded */
    /* %g0 should still be 0 */
    cmp %g0, 0
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 6: RESTORE with %g0 as rs1 source
   *-------------------------------------------------------------*/
test_6:
    mov 6, TESTNUM
    save %g0, %g0, %g0
    mov 42, %l1
    restore %g0, %l1, %l0     /* Caller's l0 = 0 + 42 = 42 */
    cmp %l0, 42
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 7: RESTORE with %g0 as rs2 source
   *-------------------------------------------------------------*/
test_7:
    mov 7, TESTNUM
    save %g0, %g0, %g0
    mov 77, %l1
    restore %l1, %g0, %l0     /* Caller's l0 = 77 + 0 = 77 */
    cmp %l0, 77
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 8: RESTORE with both %g0 sources
   *-------------------------------------------------------------*/
test_8:
    mov 8, TESTNUM
    save %g0, %g0, %g0
    restore %g0, %g0, %l0     /* Caller's l0 = 0 + 0 = 0 */
    cmp %l0, 0
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 9: Return value passing via RESTORE
   * Callee writes result to %i0, which appears as caller's %o0
   *-------------------------------------------------------------*/
test_9:
    mov 9, TESTNUM
    mov 0, %o0                /* Clear caller's o0 */
    save %g0, %g0, %g0        /* Enter callee */
    /* Compute return value in callee */
    mov 25, %l1
    mov 17, %l2
    restore %l1, %l2, %o0     /* Return with caller's o0 = 25 + 17 = 42 */
    /* Back in caller, o0 should have the return value */
    cmp %o0, 42
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 10: Return value via %i0 (standard ABI)
   * Writing to callee's %i0 = writing to caller's %o0
   *-------------------------------------------------------------*/
test_10:
    mov 10, TESTNUM
    mov 0, %o0                /* Clear caller's o0 */
    save %g0, %g0, %g0        /* Enter callee */
    /* Compute in callee and write to i0 for return */
    mov 100, %i0              /* This writes to caller's o0 */
    restore %g0, %g0, %g0     /* Return without arithmetic */
    /* Caller's o0 should have value written to callee's i0 */
    cmp %o0, 100
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 11: RESTORE reads from callee locals, writes to caller
   *-------------------------------------------------------------*/
test_11:
    mov 11, TESTNUM
    mov 0xFF, %l3             /* Set caller's local */
    save %g0, %g0, %g0        /* Enter callee */
    mov 50, %l3               /* Set callee's local (different from caller's) */
    mov 25, %l4
    restore %l3, %l4, %l3     /* Caller's l3 = callee's l3 + l4 = 50 + 25 = 75 */
    /* Check caller's l3 has RESTORE result (not original 0xFF) */
    cmp %l3, 75
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 12: Nested SAVE/RESTORE - two levels deep
   *-------------------------------------------------------------*/
test_12:
    mov 12, TESTNUM
    mov 0xAA, %l0             /* Level 0: l0 = 0xAA */
    save %g0, %g0, %g0        /* Enter level 1 */
    mov 0xBB, %l0             /* Level 1: l0 = 0xBB */
    save %g0, %g0, %g0        /* Enter level 2 */
    mov 0xCC, %l0             /* Level 2: l0 = 0xCC */
    /* Now return through both levels */
    restore %g0, %g0, %g0     /* Back to level 1 */
    cmp %l0, 0xBB
    bne fail
    nop
    restore %g0, %g0, %g0     /* Back to level 0 */
    cmp %l0, 0xAA
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 13: RESTORE with inputs as sources (callee's ins)
   * Callee's ins are caller's outs
   *-------------------------------------------------------------*/
test_13:
    mov 13, TESTNUM
    mov 30, %o0               /* Caller's out will be callee's in */
    mov 12, %o1
    save %g0, %g0, %g0        /* Enter callee */
    /* i0 = caller's o0 = 30, i1 = caller's o1 = 12 */
    restore %i0, %i1, %l0     /* Caller's l0 = 30 + 12 = 42 */
    cmp %l0, 42
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 14: RESTORE result to output register affects next callee
   *-------------------------------------------------------------*/
test_14:
    mov 14, TESTNUM
    save %g0, %g0, %g0        /* Enter level 1 */
    mov 5, %l1
    mov 3, %l2
    restore %l1, %l2, %o0     /* Caller's o0 = 8 */
    /* Now o0 = 8, if we SAVE again, callee's i0 will be 8 */
    save %g0, %g0, %g0        /* Enter new callee */
    cmp %i0, 8                /* Callee's i0 should be 8 */
    bne fail
    nop
    restore %g0, %g0, %g0     /* Return */

  /*-------------------------------------------------------------
   * Test 15: Caller's registers preserved across SAVE/RESTORE
   *-------------------------------------------------------------*/
test_15:
    mov 15, TESTNUM
    mov 0x11, %l1
    mov 0x22, %l2
    mov 0x33, %o0
    mov 0x44, %o1
    save %g0, %g0, %g0        /* Enter callee */
    /* Do some work in callee */
    mov 0x99, %l1
    mov 0x88, %l2
    mov 0x77, %o0
    restore %g0, %g0, %g0     /* Return to caller */
    /* Caller's locals should be preserved */
    cmp %l1, 0x11
    bne fail
    nop
    cmp %l2, 0x22
    bne fail
    nop
    /* Caller's outs should be preserved */
    cmp %o0, 0x33
    bne fail
    nop
    cmp %o1, 0x44
    bne fail
    nop

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
