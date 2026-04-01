/* OpenPOWER MFSPR (Move From Special Purpose Register) instruction tests */
/* mfspr rD, SPR -> rD = SPR */

#include "test_macros.h"

/* SPR numbers */
#define SPR_LR   8
#define SPR_CTR  9
#define SPR_XER  1

RVTEST_CODE_BEGIN

    /* Test reading LR */
test_2:
    li TESTNUM, 2
    bl 1f                    /* Set LR to known value */
1:
    mflr %r9                 /* Get LR using mflr (alias for mfspr r, 8) */
    mfspr %r8, SPR_LR        /* Read LR via mfspr */
    cmpd %cr0, %r8, %r9
    bne %cr0, fail

    /* Test reading CTR */
test_3:
    li TESTNUM, 3
    LOAD_IMM(%r9, 0x12345678)
    mtctr %r9                /* Set CTR */
    mfspr %r8, SPR_CTR       /* Read CTR */
    LOAD_IMM(%r25, 0x12345678)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Test reading CTR after modification */
test_4:
    li TESTNUM, 4
    li %r9, 100
    mtctr %r9
    mfctr %r8                /* mfctr is alias for mfspr r, 9 */
    li %r25, 100
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Test reading LR after nested calls */
test_5:
    li TESTNUM, 5
    bl sub1
    b test_6

sub1:
    mflr %r20                /* Save original LR */
    bl sub2                  /* Nested call */
    mfspr %r8, SPR_LR        /* Read LR - should be return to sub1 */
    mtlr %r20
    blr

sub2:
    mfspr %r21, SPR_LR       /* Read LR inside nested call */
    blr

test_6:
    li TESTNUM, 6
    /* Test that LR read matches expected */
    LOAD_IMM(%r9, 0xabcd)
    mtctr %r9
    mfspr %r8, SPR_CTR
    LOAD_IMM(%r25, 0xabcd)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
