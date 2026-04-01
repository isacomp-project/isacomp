/* OpenPOWER STDX (Store Doubleword Indexed) instruction tests */
/* stdx rS, rA, rB -> MEM[rA + rB] = rS */

#include "test_macros.h"

RVTEST_CODE_BEGIN

test_2:
    li TESTNUM, 2
    LOAD_ADDR(%r10, tdat)
    li %r11, 0
    LOAD_IMM64(%r9, 0x123456789abcdef0)
    stdx %r9, %r10, %r11
    ldx %r8, %r10, %r11
    LOAD_IMM64(%r25, 0x123456789abcdef0)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    LOAD_ADDR(%r10, tdat)
    li %r11, 8
    LOAD_IMM64(%r9, 0xdeadbeefcafebabe)
    stdx %r9, %r10, %r11
    ldx %r8, %r10, %r11
    LOAD_IMM64(%r25, 0xdeadbeefcafebabe)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    LOAD_ADDR(%r10, tdat)
    li %r11, 16
    LOAD_IMM64(%r9, 0xfeedfacef00dbeef)
    stdx %r9, %r10, %r11
    ldx %r8, %r10, %r11
    LOAD_IMM64(%r25, 0xfeedfacef00dbeef)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* rA = 0 uses address 0 + rB */
test_5:
    li TESTNUM, 5
    LOAD_ADDR(%r11, tdat2)
    LOAD_IMM64(%r9, 0x0102030405060708)
    stdx %r9, 0, %r11
    ldx %r8, 0, %r11
    LOAD_IMM64(%r25, 0x0102030405060708)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Negative index */
test_6:
    li TESTNUM, 6
    LOAD_ADDR(%r10, tdat2)
    li %r11, -8
    LOAD_IMM64(%r9, 0x8765432112345678)
    stdx %r9, %r10, %r11
    ldx %r8, %r10, %r11
    LOAD_IMM64(%r25, 0x8765432112345678)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
    .balign 8
tdat:
    .quad 0, 0, 0, 0
tdat2:
    .quad 0, 0, 0, 0
RVTEST_DATA_END
