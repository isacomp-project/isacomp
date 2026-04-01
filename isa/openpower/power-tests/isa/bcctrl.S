/* OpenPOWER BCCTRL (Branch Conditional to CTR and Link) instruction tests */
/* bcctrl BO, BI -> LR = CIA + 4, conditionally branch to CTR */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Test unconditional bctrl */
test_2:
    li TESTNUM, 2
    li %r8, 0
    LOAD_ADDR(%r9, sub1)
    mtctr %r9
    bctrl                    /* Call via CTR */
    li %r25, 1
    cmpw %cr0, %r8, %r25
    bne %cr0, fail
    b test_3

sub1:
    li %r8, 1
    blr

    /* Test conditional bctrl - beqctrl taken */
test_3:
    li TESTNUM, 3
    li %r8, 0
    li %r9, 5
    LOAD_ADDR(%r10, sub2)
    mtctr %r10
    cmpwi %cr0, %r9, 5
    beqctrl %cr0             /* Call if equal */
    li %r25, 2
    cmpw %cr0, %r8, %r25
    bne %cr0, fail
    b test_4

sub2:
    li %r8, 2
    blr

    /* Test conditional bctrl - not taken */
test_4:
    li TESTNUM, 4
    li %r8, 0
    li %r9, 5
    LOAD_ADDR(%r10, fail)
    mtctr %r10
    cmpwi %cr0, %r9, 10
    beqctrl %cr0             /* Should NOT call */
    li %r8, 3                /* Should execute */
    li %r25, 3
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Test bgtctrl */
test_5:
    li TESTNUM, 5
    li %r8, 0
    li %r9, 10
    LOAD_ADDR(%r10, sub3)
    mtctr %r10
    cmpwi %cr0, %r9, 5
    bgtctrl %cr0             /* Call if greater */
    li %r25, 4
    cmpw %cr0, %r8, %r25
    bne %cr0, fail
    b test_6

sub3:
    li %r8, 4
    blr

    /* Test nested calls via CTR */
test_6:
    li TESTNUM, 6
    li %r8, 1
    LOAD_ADDR(%r10, outer)
    mtctr %r10
    bctrl
    li %r25, 3
    cmpw %cr0, %r8, %r25
    bne %cr0, fail
    b test_done

outer:
    mflr %r20
    addi %r8, %r8, 1
    LOAD_ADDR(%r10, inner)
    mtctr %r10
    bctrl
    mtlr %r20
    blr

inner:
    addi %r8, %r8, 1
    blr

test_done:
    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
