/* OpenPOWER LBZX (Load Byte and Zero Indexed) instruction tests */
/* lbzx rD, rA, rB -> rD = MEM[rA + rB], zero extended */

#include "test_macros.h"

RVTEST_CODE_BEGIN

test_2:
    li TESTNUM, 2
    LOAD_ADDR(%r10, tdat)
    li %r11, 0
    lbzx %r8, %r10, %r11
    li %r25, 0xff
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    LOAD_ADDR(%r10, tdat)
    li %r11, 1
    lbzx %r8, %r10, %r11
    li %r25, 0x00
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    LOAD_ADDR(%r10, tdat)
    li %r11, 2
    lbzx %r8, %r10, %r11
    li %r25, 0xf0
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_5:
    li TESTNUM, 5
    LOAD_ADDR(%r10, tdat)
    li %r11, 3
    lbzx %r8, %r10, %r11
    li %r25, 0x0f
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* rA = 0 uses address 0 + rB */
test_6:
    li TESTNUM, 6
    LOAD_ADDR(%r11, tdat4)
    lbzx %r8, 0, %r11
    li %r25, 0xde
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Negative index - loads from tdat4-4 = tdat[0] = 0xff */
test_7:
    li TESTNUM, 7
    LOAD_ADDR(%r10, tdat4)
    li %r11, -4
    lbzx %r8, %r10, %r11
    li %r25, 0xff
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
tdat:
    .byte 0xff, 0x00, 0xf0, 0x0f
tdat4:
    .byte 0xde, 0xad, 0xbe, 0xef
    .byte 0x12, 0x34, 0x56, 0x78
RVTEST_DATA_END
