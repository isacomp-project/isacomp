/* OpenPOWER ADDIS (Add Immediate Shifted) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * ADDIS tests - addis rD, rA, SIMM
     * rD = rA + (SIMM << 16)
     *-------------------------------------------------------------*/

    /* Basic tests with rA = 0 (lis pseudo-instruction) */
test_2:
    li TESTNUM, 2
    addis %r8, %r0, 0
    li %r25, 0
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    addis %r8, %r0, 1
    LOAD_IMM(%r25, 0x00010000)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    addis %r8, %r0, 0x7fff
    LOAD_IMM(%r25, 0x7fff0000)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_5:
    li TESTNUM, 5
    addis %r8, %r0, -1      /* 0xffff */
    LOAD_IMM(%r25, 0xffff0000)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* ADDIS with non-zero rA */
test_6:
    li TESTNUM, 6
    li %r9, 0x1234
    addis %r8, %r9, 1       /* 0x1234 + 0x10000 */
    LOAD_IMM(%r25, 0x00011234)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_7:
    li TESTNUM, 7
    li %r9, 0x5678
    addis %r8, %r9, 0x1234  /* 0x5678 + 0x12340000 */
    LOAD_IMM(%r25, 0x12345678)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_8:
    li TESTNUM, 8
    LOAD_IMM(%r9, 0x12340000)
    addis %r8, %r9, 1       /* 0x12340000 + 0x10000 */
    LOAD_IMM(%r25, 0x12350000)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Negative immediate */
test_9:
    li TESTNUM, 9
    LOAD_IMM(%r9, 0x00020000)
    addis %r8, %r9, -1      /* 0x20000 - 0x10000 */
    LOAD_IMM(%r25, 0x00010000)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Source equals destination */
test_10:
    li TESTNUM, 10
    li %r9, 0x5678
    addis %r9, %r9, 0x1234
    LOAD_IMM(%r25, 0x12345678)
    cmpw %cr0, %r9, %r25
    bne %cr0, fail

    /* Building 32-bit constants (lis/ori pattern) */
test_11:
    li TESTNUM, 11
    addis %r8, %r0, 0xdead
    ori %r8, %r8, 0xbeef
    LOAD_IMM(%r25, 0xdeadbeef)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
