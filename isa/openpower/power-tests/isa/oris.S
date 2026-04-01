/* OpenPOWER ORIS (OR Immediate Shifted) instruction tests */
/* oris rA, rS, UIMM -> rA = rS | (UIMM << 16) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

test_2:
    li TESTNUM, 2
    li %r9, 0
    oris %r8, %r9, 0x1234
    LOAD_IMM(%r25, 0x12340000)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    li %r9, 0x5678
    oris %r8, %r9, 0x1234
    LOAD_IMM(%r25, 0x12345678)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    LOAD_IMM(%r9, 0x00005678)
    oris %r8, %r9, 0x0000
    LOAD_IMM(%r25, 0x00005678)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_5:
    li TESTNUM, 5
    LOAD_IMM(%r9, 0x12340000)
    oris %r8, %r9, 0xffff
    LOAD_IMM(%r25, 0xffff0000)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_6:
    li TESTNUM, 6
    LOAD_IMM(%r9, 0x0f0f0f0f)
    oris %r8, %r9, 0xf0f0
    LOAD_IMM(%r25, 0xffff0f0f)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Source equals destination */
test_7:
    li TESTNUM, 7
    LOAD_IMM(%r9, 0xbeef)
    oris %r9, %r9, 0xdead
    LOAD_IMM(%r25, 0xdeadbeef)
    cmpw %cr0, %r9, %r25
    bne %cr0, fail

    /* Zero source */
test_8:
    li TESTNUM, 8
    li %r9, 0
    oris %r8, %r9, 0xabcd
    LOAD_IMM(%r25, 0xabcd0000)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
