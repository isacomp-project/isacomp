/* OpenPOWER LDX (Load Doubleword Indexed) instruction tests */
/* ldx rD, rA, rB -> rD = MEM[rA + rB] */

#include "test_macros.h"

RVTEST_CODE_BEGIN

test_2:
    li TESTNUM, 2
    LOAD_ADDR(%r10, tdat)
    li %r11, 0
    ldx %r8, %r10, %r11
    LOAD_IMM64(%r25, 0x00ff00ff00ff00ff)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    LOAD_ADDR(%r10, tdat)
    li %r11, 8
    ldx %r8, %r10, %r11
    LOAD_IMM64(%r25, 0xff00ff00ff00ff00)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    LOAD_ADDR(%r10, tdat)
    li %r11, 16
    ldx %r8, %r10, %r11
    LOAD_IMM64(%r25, 0x0ff00ff00ff00ff0)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_5:
    li TESTNUM, 5
    LOAD_ADDR(%r10, tdat)
    li %r11, 24
    ldx %r8, %r10, %r11
    LOAD_IMM64(%r25, 0xf00ff00ff00ff00f)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* rA = 0 uses address 0 + rB */
test_6:
    li TESTNUM, 6
    LOAD_ADDR(%r11, tdat2)
    ldx %r8, 0, %r11
    LOAD_IMM64(%r25, 0xdeadbeefcafebabe)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Negative index */
test_7:
    li TESTNUM, 7
    LOAD_ADDR(%r10, tdat2)
    li %r11, -8
    ldx %r8, %r10, %r11
    LOAD_IMM64(%r25, 0xf00ff00ff00ff00f)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
tdat:
    .quad 0x00ff00ff00ff00ff
    .quad 0xff00ff00ff00ff00
    .quad 0x0ff00ff00ff00ff0
    .quad 0xf00ff00ff00ff00f
tdat2:
    .quad 0xdeadbeefcafebabe
    .quad 0x123456789abcdef0
RVTEST_DATA_END
