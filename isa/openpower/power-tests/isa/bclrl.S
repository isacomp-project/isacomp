/* OpenPOWER BCLRL (Branch Conditional to LR and Link) instruction tests */
/* bclrl BO, BI -> NIA = LR, LR = CIA + 4, conditionally */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Test blrl - unconditional branch to LR and link */
test_2:
    li TESTNUM, 2
    li %r8, 0
    bl setup_lr              /* Set LR to return point */
    b test_2_cont

setup_lr:
    mflr %r20                /* Save original LR */
    bl 1f                    /* Get current address into LR */
1:
    mflr %r21
    addi %r21, %r21, (target1 - 1b)  /* Calculate target address */
    mtlr %r21
    li %r8, 1
    blrl                     /* Branch to target, link back */
    /* Should return here */
    li %r8, 3
    mtlr %r20
    blr

target1:
    li %r8, 2
    blr                      /* Return to after blrl */

test_2_cont:
    li %r25, 3
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Test conditional bclrl - beqlrl */
test_3:
    li TESTNUM, 3
    li %r8, 0
    li %r9, 5
    bl test_beqlrl
    li %r25, 10
    cmpw %cr0, %r8, %r25
    bne %cr0, fail
    b test_done

test_beqlrl:
    mflr %r20                /* Save LR */
    bl 1f
1:
    mflr %r21
    addi %r21, %r21, (target2 - 1b)
    mtlr %r21
    cmpwi %cr0, %r9, 5
    li %r8, 5
    beqlrl %cr0              /* Should branch */
    li %r8, 99               /* Should not execute */
    b 2f
target2:
    li %r8, 10
    b 2f                     /* Skip to cleanup, don't return to after beqlrl */
2:
    mtlr %r20
    blr

test_done:
    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
