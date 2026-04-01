/* OpenPOWER ANDIS. (AND Immediate Shifted) instruction tests */
/* andis. rA, rS, UIMM -> rA = rS & (UIMM << 16), updates CR0 */

#include "test_macros.h"

RVTEST_CODE_BEGIN

test_2:
    li TESTNUM, 2
    LOAD_IMM(%r9, 0xffff0000)
    andis. %r8, %r9, 0x0f0f
    LOAD_IMM(%r25, 0x0f0f0000)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    LOAD_IMM(%r9, 0x12345678)
    andis. %r8, %r9, 0xffff
    LOAD_IMM(%r25, 0x12340000)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    LOAD_IMM(%r9, 0x12345678)
    andis. %r8, %r9, 0x0000
    li %r25, 0
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_5:
    li TESTNUM, 5
    LOAD_IMM(%r9, 0xabcdef01)
    andis. %r8, %r9, 0xf0f0
    LOAD_IMM(%r25, 0xa0c00000)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Source equals destination */
test_6:
    li TESTNUM, 6
    LOAD_IMM(%r9, 0xffff1234)
    andis. %r9, %r9, 0x00ff
    LOAD_IMM(%r25, 0x00ff0000)
    cmpw %cr0, %r9, %r25
    bne %cr0, fail

    /* Zero source */
test_7:
    li TESTNUM, 7
    li %r9, 0
    andis. %r8, %r9, 0xffff
    li %r25, 0
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
