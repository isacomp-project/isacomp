/* OpenPOWER LWA (Load Word Algebraic) instruction tests */
/* lwa rD, DS(rA) -> rD = sign_extend(MEM[rA + DS]) */
/* NOTE: Tests simplified to avoid sldi (not implemented) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Positive values (no sign extension needed) */
test_2:
    li TESTNUM, 2
    LOAD_ADDR(%r10, tdat)
    lwa %r8, 0(%r10)
    /* Check low 32 bits equal 0x00ff00ff */
    LOAD_IMM(%r25, 0x00ff00ff)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    LOAD_ADDR(%r10, tdat)
    lwa %r8, 4(%r10)
    /* Check low 32 bits equal 0x7f00ff00 */
    LOAD_IMM(%r25, 0x7f00ff00)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Negative values (sign extension) - verify low 32 bits */
test_4:
    li TESTNUM, 4
    LOAD_ADDR(%r10, tdat)
    lwa %r8, 8(%r10)
    /* Check low 32 bits equal 0x80000001 (sign-extended) */
    LOAD_IMM(%r25, 0x80000001)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_5:
    li TESTNUM, 5
    LOAD_ADDR(%r10, tdat)
    lwa %r8, 12(%r10)
    /* Load 0xffffffff, sign-extended should be -1 */
    li %r25, -1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Zero value */
test_6:
    li TESTNUM, 6
    LOAD_ADDR(%r10, tdat)
    lwa %r8, 20(%r10)
    li %r25, 0
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
    .balign 4
tdat:
    .long 0x00ff00ff      /* positive */
    .long 0x7f00ff00      /* positive (MSB = 0) */
    .long 0x80000001      /* negative (MSB = 1) */
    .long 0xffffffff      /* -1 */
    .long 0xff00ff00      /* negative (MSB = 1) */
    .long 0x00000000      /* zero */
RVTEST_DATA_END
