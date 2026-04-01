/* OpenPOWER LWZX (Load Word and Zero Indexed) instruction tests */
/* lwzx rD, rA, rB -> rD = MEM[rA + rB], zero extended */

#include "test_macros.h"

RVTEST_CODE_BEGIN

test_2:
    li TESTNUM, 2
    LOAD_ADDR(%r10, tdat)
    li %r11, 0
    lwzx %r8, %r10, %r11
    LOAD_IMM(%r25, 0x00ff00ff)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    LOAD_ADDR(%r10, tdat)
    li %r11, 4
    lwzx %r8, %r10, %r11
    LOAD_IMM(%r25, 0xff00ff00)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    LOAD_ADDR(%r10, tdat)
    li %r11, 8
    lwzx %r8, %r10, %r11
    LOAD_IMM(%r25, 0x0ff00ff0)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_5:
    li TESTNUM, 5
    LOAD_ADDR(%r10, tdat)
    li %r11, 12
    lwzx %r8, %r10, %r11
    LOAD_IMM(%r25, 0xf00ff00f)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* rA = 0 uses address 0 + rB */
test_6:
    li TESTNUM, 6
    LOAD_ADDR(%r11, tdat2)
    lwzx %r8, 0, %r11
    LOAD_IMM(%r25, 0xdeadbeef)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Negative index */
test_7:
    li TESTNUM, 7
    LOAD_ADDR(%r10, tdat2)
    li %r11, -4
    lwzx %r8, %r10, %r11
    LOAD_IMM(%r25, 0xf00ff00f)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
tdat:
    .long 0x00ff00ff
    .long 0xff00ff00
    .long 0x0ff00ff0
    .long 0xf00ff00f
tdat2:
    .long 0xdeadbeef
    .long 0x12345678
RVTEST_DATA_END
