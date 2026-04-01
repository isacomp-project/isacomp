/* SPARCv8 Register Window Tests */
/* Tests the register window mechanism with SAVE/RESTORE */
/* Window implementation: 8 windows, CWP as 3-bit counter */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Test 2: Basic SAVE arithmetic (rs1 + rs2 -> rd in new window)
   * This verifies SAVE computes the result correctly
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    mov 100, %o0              /* Set up operand in output register */
    mov 50, %o1               /* Set up operand in output register */
    save %o0, %o1, %l0        /* l0 in new window = o0 + o1 = 150 */
    /* Now in new window - check result */
    cmp %l0, 150
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:
    restore %g0, %g0, %g0     /* Go back to original window */

  /*-------------------------------------------------------------
   * Test 3: Outs-to-ins overlap (caller's outs = callee's ins)
   * After SAVE, the old window's %o registers should be visible
   * as the new window's %i registers
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    mov 0x123, %o0            /* Put a value in caller's %o0 */
    mov 0x456, %o1            /* Put a value in caller's %o1 */
    mov 0x789, %o2            /* Put a value in caller's %o2 */
    save %g0, %g0, %g0        /* Switch to new window */
    /* In new window, caller's outs should be our ins */
    cmp %i0, 0x123            /* Callee's %i0 should be caller's %o0 */
    bne fail
    nop
    cmp %i1, 0x456            /* Callee's %i1 should be caller's %o1 */
    bne fail
    nop
    cmp %i2, 0x789            /* Callee's %i2 should be caller's %o2 */
    bne fail
    nop
    restore %g0, %g0, %g0     /* Go back to original window */

  /*-------------------------------------------------------------
   * Test 4: Local register isolation
   * Each window has its own set of local registers
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    mov 0x555, %l4            /* Put a value in caller's local */
    save %g0, %g0, %g0        /* Switch to new window */
    /* In new window, locals should be independent (initially 0 or garbage) */
    /* Store a different value in new window's local */
    mov 0x666, %l4
    restore %g0, %g0, %g0     /* Go back to original window */
    /* Original local should still have our original value */
    cmp %l4, 0x555
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 5: Caller's output registers preserved across SAVE/RESTORE
   * After a SAVE+RESTORE round trip, the caller's out registers
   * should still contain their original values
   *-------------------------------------------------------------*/
test_5:
    mov 5, TESTNUM
    /* Set values in caller's output registers */
    mov 0x111, %o0
    mov 0x222, %o1
    mov 0x333, %o2
    save %g0, %g0, %g0        /* Switch to new window (callee) */
    /* In callee, do some work (doesn't affect caller's outs) */
    mov 0xABC, %l0
    restore %g0, %g0, %g0     /* Back to caller window */
    /* Caller's outs should still have original values */
    cmp %o0, 0x111
    bne fail
    nop
    cmp %o1, 0x222
    bne fail
    nop
    cmp %o2, 0x333
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 6: Multiple window switches - verify chained parameter passing
   * Each SAVE passes caller's outs as callee's ins
   *-------------------------------------------------------------*/
test_6:
    mov 6, TESTNUM
    mov 0x100, %o0            /* Original window: o0 = 0x100 */
    save %g0, %g0, %g0        /* New window (CWP-1) */
    /* In new window: i0 should be 0x100 from original */
    cmp %i0, 0x100
    bne fail
    nop
    mov 0x200, %o0            /* This window: o0 = 0x200 */
    save %g0, %g0, %g0        /* Another new window (CWP-1) */
    /* In this window: i0 should be 0x200 from previous */
    cmp %i0, 0x200
    bne fail
    nop
    /* Now return through both windows */
    restore %g0, %g0, %g0     /* Back to first callee */
    /* i0 should still be 0x100 (from original's outs) */
    cmp %i0, 0x100
    bne fail
    nop
    restore %g0, %g0, %g0     /* Back to original window */
    /* Original window: o0 should still have 0x100 */
    cmp %o0, 0x100
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 7: SAVE with immediate operand
   *-------------------------------------------------------------*/
test_7:
    mov 7, TESTNUM
    mov 100, %o0
    save %o0, 23, %l0         /* l0 = 100 + 23 = 123 */
    cmp %l0, 123
    bne fail
    nop
    restore %g0, %g0, %g0

  /*-------------------------------------------------------------
   * Test 8: RESTORE with arithmetic (returns to caller with result)
   *-------------------------------------------------------------*/
test_8:
    mov 8, TESTNUM
    save %g0, %g0, %g0        /* Go to callee window */
    mov 50, %l1               /* Prepare operands in callee locals */
    mov 75, %l2
    restore %l1, %l2, %o0     /* Return with o0 = 50 + 75 = 125 */
    /* Back in caller, check %o0 (which was callee's destination) */
    /* RESTORE reads from old window (callee) and writes to new window (caller) */
    cmp %o0, 125
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 9: Global registers are shared across windows
   *-------------------------------------------------------------*/
test_9:
    mov 9, TESTNUM
    mov 0x999, %g1            /* Set global in current window */
    save %g0, %g0, %g0        /* Switch window */
    /* Global should still be visible */
    cmp %g1, 0x999
    bne fail
    nop
    /* Modify global in new window */
    mov 0x888, %g1
    restore %g0, %g0, %g0
    /* Modified value should be visible back in original window */
    cmp %g1, 0x888
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 10: SAVE preserves all caller's output registers as callee's inputs
   *-------------------------------------------------------------*/
test_10:
    mov 10, TESTNUM
    mov 0x10, %o0
    mov 0x20, %o1
    mov 0x30, %o2
    mov 0x40, %o3
    mov 0x50, %o4
    mov 0x60, %o5
    /* Note: %o6 is stack pointer, %o7 is return address - skip those */
    save %g0, %g0, %g0
    /* Verify all inputs match caller's outputs */
    cmp %i0, 0x10
    bne fail
    nop
    cmp %i1, 0x20
    bne fail
    nop
    cmp %i2, 0x30
    bne fail
    nop
    cmp %i3, 0x40
    bne fail
    nop
    cmp %i4, 0x50
    bne fail
    nop
    cmp %i5, 0x60
    bne fail
    nop
    restore %g0, %g0, %g0

  /*-------------------------------------------------------------
   * Test 11: Window round-trip - SAVE and RESTORE preserve values
   *-------------------------------------------------------------*/
test_11:
    mov 11, TESTNUM
    mov 0xABC, %o0            /* Mark original window */
    mov 0xDEF, %l3            /* Store in local */
    save %g0, %g0, %g0        /* Window 1 */
    save %g0, %g0, %g0        /* Window 2 */
    save %g0, %g0, %g0        /* Window 3 */
    /* Go back through all windows */
    restore %g0, %g0, %g0     /* Back to 2 */
    restore %g0, %g0, %g0     /* Back to 1 */
    restore %g0, %g0, %g0     /* Back to 0 */
    /* Check we're back to original window by checking %o0 and %l3 */
    cmp %o0, 0xABC
    bne fail
    nop
    cmp %l3, 0xDEF
    bne fail
    nop

  /*-------------------------------------------------------------
   * Test 12: Nested procedure simulation with correct ABI
   * Return values go in %i0 (= caller's %o0 after RESTORE)
   *-------------------------------------------------------------*/
test_12:
    mov 12, TESTNUM
    /* f1 setup: pass argument in %o0 */
    mov 10, %o0               /* arg1 = 10 */
    save %g0, %g0, %g0        /* Enter f2: i0 = 10 */
    /* f2: compute and pass to f3 */
    add %i0, 5, %o0           /* o0 = i0 + 5 = 15 */
    save %g0, %g0, %g0        /* Enter f3: i0 = 15 */
    /* f3: compute result, return in %i0 (= f2's %o0) */
    add %i0, 3, %i0           /* i0 = i0 + 3 = 18 (return value) */
    restore %g0, %g0, %g0     /* Return to f2 */
    /* f2: received value is in %o0 (was f3's %i0) */
    cmp %o0, 18
    bne fail
    nop
    /* f2: compute and return in %i0 (= f1's %o0) */
    add %o0, 2, %i0           /* i0 = 18 + 2 = 20 (return to f1) */
    restore %g0, %g0, %g0     /* Return to f1 */
    /* f1: received value is in %o0 (was f2's %i0) */
    cmp %o0, 20
    bne fail
    nop

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
