/* OpenPOWER LBZ (Load Byte and Zero) instruction tests */
/* Based on riscv-tests/mips-tests load patterns */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Basic load tests - lbz rD, D(rA)
     * Zero-extends byte to 64 bits
     *-------------------------------------------------------------*/

    /* Load from aligned addresses */
    TEST_LD_OP( 2, lbz, 0x00000000000000ff, 0, tdat1 )
    TEST_LD_OP( 3, lbz, 0x0000000000000000, 0, tdat2 )
    TEST_LD_OP( 4, lbz, 0x00000000000000f0, 0, tdat3 )
    TEST_LD_OP( 5, lbz, 0x000000000000000f, 0, tdat4 )

    /* Load with positive offset */
    TEST_LD_OP( 6, lbz, 0x0000000000000000, 1, tdat1 )
    TEST_LD_OP( 7, lbz, 0x00000000000000f0, 2, tdat1 )
    TEST_LD_OP( 8, lbz, 0x000000000000000f, 3, tdat1 )

    /* Load with negative offset */
    TEST_LD_OP( 9, lbz, 0x00000000000000ff, -3, tdat4 )
    TEST_LD_OP(10, lbz, 0x0000000000000000, -2, tdat4 )
    TEST_LD_OP(11, lbz, 0x00000000000000f0, -1, tdat4 )
    TEST_LD_OP(12, lbz, 0x000000000000000f,  0, tdat4 )

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    /* Note: PowerPC doesn't have the same bypass structure as RISC-V
       but we test load-use patterns */
test_13:
    li TESTNUM, 13
    lis %r9, tdat1@ha
    addi %r9, %r9, tdat1@l
    lbz %r8, 0(%r9)
    addi %r10, %r8, 0      /* immediate use */
    li %r25, 0xff
    cmpw %cr0, %r10, %r25
    bne %cr0, fail

test_14:
    li TESTNUM, 14
    lis %r9, tdat2@ha
    addi %r9, %r9, tdat2@l
    lbz %r8, 0(%r9)
    nop
    addi %r10, %r8, 0      /* use after 1 nop */
    li %r25, 0x00
    cmpw %cr0, %r10, %r25
    bne %cr0, fail

test_15:
    li TESTNUM, 15
    lis %r9, tdat3@ha
    addi %r9, %r9, tdat3@l
    lbz %r8, 0(%r9)
    nop
    nop
    addi %r10, %r8, 0      /* use after 2 nops */
    li %r25, 0xf0
    cmpw %cr0, %r10, %r25
    bne %cr0, fail

    /*-------------------------------------------------------------
     * Test that lbz zero-extends (not sign-extends)
     *-------------------------------------------------------------*/

test_16:
    li TESTNUM, 16
    lis %r9, tdat1@ha
    addi %r9, %r9, tdat1@l
    lbz %r8, 0(%r9)        /* Load 0xff */
    /* Should be 0x00000000000000ff, NOT 0xffffffffffffffff */
    lis %r25, 0
    ori %r25, %r25, 0xff
    cmpd %cr0, %r8, %r25   /* 64-bit compare */
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
    .balign 8
tdat1:  .byte 0xff
tdat2:  .byte 0x00
tdat3:  .byte 0xf0
tdat4:  .byte 0x0f
RVTEST_DATA_END
