/* OpenPOWER BCL (Branch Conditional and Link) instruction tests */
/* bcl BO, BI, target -> LR = CIA + 4, conditionally branch */
/* NOTE: blr returns to LR (address after bcl), so tests must structure
   accordingly - after bcl should be instruction to continue, not fail path */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Test conditional branch with link - condition true */
test_2:
    li TESTNUM, 2
    li %r8, 0
    li %r9, 5
    cmpwi %cr0, %r9, 5
    beql %cr0, sub_eq        /* Branch and link if equal */
    b test_2_check           /* LR points here, so blr returns here */

sub_eq:
    li %r8, 1
    blr                      /* Return to LR (test_2_check) */

test_2_check:
    li %r25, 1
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Test conditional branch with link - condition false */
test_3:
    li TESTNUM, 3
    li %r8, 0
    li %r9, 5
    cmpwi %cr0, %r9, 10
    beql %cr0, fail_sub      /* Should NOT branch (5 != 10) */
    li %r8, 1                /* Should execute this */
    b test_3_check

fail_sub:
    b fail

test_3_check:
    li %r25, 1
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Test bgtl - branch if greater and link */
test_4:
    li TESTNUM, 4
    li %r8, 0
    li %r9, 10
    cmpwi %cr0, %r9, 5
    bgtl %cr0, sub_gt
    b test_4_check           /* LR points here */

sub_gt:
    li %r8, 2
    blr

test_4_check:
    li %r25, 2
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Test bltl - branch if less and link */
test_5:
    li TESTNUM, 5
    li %r8, 0
    li %r9, 3
    cmpwi %cr0, %r9, 5
    bltl %cr0, sub_lt
    b test_5_check           /* LR points here */

sub_lt:
    li %r8, 3
    blr

test_5_check:
    li %r25, 3
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
