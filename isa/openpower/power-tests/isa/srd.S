/* OpenPOWER SRD (Shift Right Doubleword) instruction tests */
/* srd rA, rS, rB -> rA = rS >> (rB[58:63]), zeros shifted in */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Basic shifts - use sldi to create proper 64-bit values without sign extension */
test_2:
    li TESTNUM, 2
    li %r9, 1
    sldi %r9, %r9, 31        /* 0x0000000080000000 - no sign extension */
    li %r10, 0
    srd %r8, %r9, %r10
    li %r25, 1
    sldi %r25, %r25, 31      /* 0x0000000080000000 */
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    li %r9, 1
    sldi %r9, %r9, 31        /* 0x0000000080000000 */
    li %r10, 1
    srd %r8, %r9, %r10
    li %r25, 1
    sldi %r25, %r25, 30      /* 0x0000000040000000 */
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    li %r9, 1
    sldi %r9, %r9, 31        /* 0x0000000080000000 */
    li %r10, 7
    srd %r8, %r9, %r10
    li %r25, 1
    sldi %r25, %r25, 24      /* 0x0000000001000000 */
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_5:
    li TESTNUM, 5
    li %r9, 1
    sldi %r9, %r9, 31        /* 0x0000000080000000 */
    li %r10, 31
    srd %r8, %r9, %r10
    li %r25, 1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* 64-bit value shifts */
test_6:
    li TESTNUM, 6
    li %r9, 1
    sldi %r9, %r9, 63        /* 0x8000000000000000 */
    li %r10, 32
    srd %r8, %r9, %r10
    li %r25, 1
    sldi %r25, %r25, 31      /* 0x80000000 */
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_7:
    li TESTNUM, 7
    li %r9, 1
    sldi %r9, %r9, 63        /* 0x8000000000000000 */
    li %r10, 63
    srd %r8, %r9, %r10
    li %r25, 1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Shift by 64 or more - result is zero */
test_8:
    li TESTNUM, 8
    li %r9, -1               /* All ones */
    li %r10, 64
    srd %r8, %r9, %r10
    li %r25, 0
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Multi-bit pattern */
test_9:
    li TESTNUM, 9
    LOAD_IMM(%r9, 0x12345670)
    li %r10, 4
    srd %r8, %r9, %r10
    LOAD_IMM(%r25, 0x1234567)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Source equals destination */
test_10:
    li TESTNUM, 10
    LOAD_IMM(%r9, 0xff00)
    li %r10, 8
    srd %r9, %r9, %r10
    li %r25, 0xff
    cmpd %cr0, %r9, %r25
    bne %cr0, fail

    /* Zero source */
test_11:
    li TESTNUM, 11
    li %r9, 0
    li %r10, 10
    srd %r8, %r9, %r10
    li %r25, 0
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
