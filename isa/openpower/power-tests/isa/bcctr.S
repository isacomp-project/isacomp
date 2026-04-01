/* OpenPOWER BCCTR (Branch Conditional to Count Register) instruction tests */
/* bcctr BO, BI -> Conditionally branch to address in CTR */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Test unconditional bctr */
test_2:
    li TESTNUM, 2
    li %r8, 0
    LOAD_ADDR(%r9, target1)
    mtctr %r9
    bctr                     /* Branch to CTR */
    b fail                   /* Should not reach here */

target1:
    li %r8, 1
    li %r25, 1
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Test conditional bctr - condition true */
test_3:
    li TESTNUM, 3
    li %r8, 0
    li %r9, 5
    LOAD_ADDR(%r10, target2)
    mtctr %r10
    cmpwi %cr0, %r9, 5
    beqctr %cr0              /* Branch if equal */
    b fail

target2:
    li %r8, 2
    li %r25, 2
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Test conditional bctr - condition false */
test_4:
    li TESTNUM, 4
    li %r8, 0
    li %r9, 5
    LOAD_ADDR(%r10, fail)
    mtctr %r10
    cmpwi %cr0, %r9, 10
    beqctr %cr0              /* Should NOT branch (5 != 10) */
    li %r8, 3                /* Should execute */
    li %r25, 3
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Test bgtctr */
test_5:
    li TESTNUM, 5
    li %r8, 0
    li %r9, 10
    LOAD_ADDR(%r10, target3)
    mtctr %r10
    cmpwi %cr0, %r9, 5
    bgtctr %cr0              /* Branch if greater */
    b fail

target3:
    li %r8, 4
    li %r25, 4
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
