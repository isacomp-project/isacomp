/* OpenPOWER STWX (Store Word Indexed) instruction tests */
/* stwx rS, rA, rB -> MEM[rA + rB] = rS[32:63] */

#include "test_macros.h"

RVTEST_CODE_BEGIN

test_2:
    li TESTNUM, 2
    LOAD_ADDR(%r10, tdat)
    li %r11, 0
    LOAD_IMM(%r9, 0x12345678)
    stwx %r9, %r10, %r11
    lwzx %r8, %r10, %r11
    LOAD_IMM(%r25, 0x12345678)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    LOAD_ADDR(%r10, tdat)
    li %r11, 4
    LOAD_IMM(%r9, 0xdeadbeef)
    stwx %r9, %r10, %r11
    lwzx %r8, %r10, %r11
    LOAD_IMM(%r25, 0xdeadbeef)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    LOAD_ADDR(%r10, tdat)
    li %r11, 8
    LOAD_IMM(%r9, 0xcafebabe)
    stwx %r9, %r10, %r11
    lwzx %r8, %r10, %r11
    LOAD_IMM(%r25, 0xcafebabe)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* rA = 0 uses address 0 + rB */
test_5:
    li TESTNUM, 5
    LOAD_ADDR(%r11, tdat2)
    LOAD_IMM(%r9, 0xfeedface)
    stwx %r9, 0, %r11
    lwzx %r8, 0, %r11
    LOAD_IMM(%r25, 0xfeedface)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Negative index */
test_6:
    li TESTNUM, 6
    LOAD_ADDR(%r10, tdat2)
    li %r11, -4
    LOAD_IMM(%r9, 0x87654321)
    stwx %r9, %r10, %r11
    lwzx %r8, %r10, %r11
    LOAD_IMM(%r25, 0x87654321)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
    .balign 4
tdat:
    .long 0, 0, 0, 0
tdat2:
    .long 0, 0, 0, 0
RVTEST_DATA_END
