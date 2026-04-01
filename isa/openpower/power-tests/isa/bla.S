/* OpenPOWER BLA (Branch and Link Absolute) instruction tests */
/* bla target -> LR = CIA + 4, Branch to absolute address target */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Test branch and link with return */
test_2:
    li TESTNUM, 2
    li %r8, 0
    bl subroutine1
    li %r25, 42
    cmpw %cr0, %r8, %r25
    bne %cr0, fail
    b test_3

subroutine1:
    li %r8, 42
    blr                      /* Return via LR */

test_3:
    li TESTNUM, 3
    li %r8, 0
    li %r9, 5
    bl subroutine2           /* Call subroutine that adds to r8 */
    li %r25, 5
    cmpw %cr0, %r8, %r25
    bne %cr0, fail
    b test_4

subroutine2:
    add %r8, %r8, %r9
    blr

    /* Nested calls */
test_4:
    li TESTNUM, 4
    li %r8, 1
    bl outer_sub
    li %r25, 3
    cmpw %cr0, %r8, %r25
    bne %cr0, fail
    b test_done

outer_sub:
    mflr %r20                /* Save LR */
    addi %r8, %r8, 1
    bl inner_sub
    mtlr %r20                /* Restore LR */
    blr

inner_sub:
    addi %r8, %r8, 1
    blr

test_done:
    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
