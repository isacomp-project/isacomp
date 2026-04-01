/* OpenPOWER STHX (Store Halfword Indexed) instruction tests */
/* sthx rS, rA, rB -> MEM[rA + rB] = rS[48:63] */

#include "test_macros.h"

RVTEST_CODE_BEGIN

test_2:
    li TESTNUM, 2
    LOAD_ADDR(%r10, tdat)
    li %r11, 0
    li %r9, 0x1234
    sthx %r9, %r10, %r11
    lhzx %r8, %r10, %r11
    li %r25, 0x1234
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    LOAD_ADDR(%r10, tdat)
    li %r11, 2
    li %r9, 0x5678
    sthx %r9, %r10, %r11
    lhzx %r8, %r10, %r11
    li %r25, 0x5678
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    LOAD_ADDR(%r10, tdat)
    li %r11, 4
    LOAD_IMM(%r9, 0x12345678)  /* Only low halfword stored */
    sthx %r9, %r10, %r11
    lhzx %r8, %r10, %r11
    li %r25, 0x5678
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* rA = 0 uses address 0 + rB */
test_5:
    li TESTNUM, 5
    LOAD_ADDR(%r11, tdat2)
    LOAD_IMM(%r9, 0xabcd)
    sthx %r9, 0, %r11
    lhzx %r8, 0, %r11
    LOAD_IMM(%r25, 0xabcd)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Negative index */
test_6:
    li TESTNUM, 6
    LOAD_ADDR(%r10, tdat2)
    li %r11, -2
    LOAD_IMM(%r9, 0xef01)
    sthx %r9, %r10, %r11
    lhzx %r8, %r10, %r11
    LOAD_IMM(%r25, 0xef01)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
    .balign 2
tdat:
    .short 0, 0, 0, 0
tdat2:
    .short 0, 0, 0, 0
RVTEST_DATA_END
