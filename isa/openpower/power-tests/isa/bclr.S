/* OpenPOWER BCLR (Branch Conditional to Link Register) instruction tests */
/* bclr BO, BI -> Conditionally branch to address in LR */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Test unconditional blr (return) */
test_2:
    li TESTNUM, 2
    li %r8, 0
    bl sub1
    li %r25, 1
    cmpw %cr0, %r8, %r25
    bne %cr0, fail
    b test_3

sub1:
    li %r8, 1
    blr                      /* Unconditional return */

    /* Test conditional return - condition true */
test_3:
    li TESTNUM, 3
    li %r8, 0
    li %r9, 5
    bl sub2
    li %r25, 2
    cmpw %cr0, %r8, %r25
    bne %cr0, fail
    b test_4

sub2:
    li %r8, 2
    cmpwi %cr0, %r9, 5
    beqlr %cr0               /* Return if equal */
    li %r8, 99               /* Should not execute */
    blr

    /* Test conditional return - condition false */
test_4:
    li TESTNUM, 4
    li %r8, 0
    li %r9, 5
    bl sub3
    li %r25, 3
    cmpw %cr0, %r8, %r25
    bne %cr0, fail
    b test_5

sub3:
    li %r8, 2
    cmpwi %cr0, %r9, 10      /* Not equal */
    beqlr %cr0               /* Should NOT return */
    li %r8, 3                /* Should execute */
    blr

    /* Test bgtlr */
test_5:
    li TESTNUM, 5
    li %r8, 0
    li %r9, 10
    bl sub4
    li %r25, 4
    cmpw %cr0, %r8, %r25
    bne %cr0, fail
    b test_6

sub4:
    li %r8, 4
    cmpwi %cr0, %r9, 5
    bgtlr %cr0               /* Return if greater */
    li %r8, 99
    blr

    /* Test bltlr not taken */
test_6:
    li TESTNUM, 6
    li %r8, 0
    li %r9, 10
    bl sub5
    li %r25, 5
    cmpw %cr0, %r8, %r25
    bne %cr0, fail
    b test_done

sub5:
    li %r8, 4
    cmpwi %cr0, %r9, 5
    bltlr %cr0               /* Should NOT return (10 not < 5) */
    li %r8, 5
    blr

test_done:
    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
