/* OpenPOWER LHZ (Load Halfword and Zero) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Basic load tests - lhz rD, D(rA)
     * Zero-extends halfword to 64 bits
     *-------------------------------------------------------------*/

    /* Load from aligned addresses */
    TEST_LD_OP( 2, lhz, 0x000000000000ff00, 0, tdat1 )
    TEST_LD_OP( 3, lhz, 0x00000000000000ff, 0, tdat2 )
    TEST_LD_OP( 4, lhz, 0x000000000000f0f0, 0, tdat3 )
    TEST_LD_OP( 5, lhz, 0x0000000000000f0f, 0, tdat4 )

    /* Load with positive offset */
    TEST_LD_OP( 6, lhz, 0x00000000000000ff, 2, tdat1 )
    TEST_LD_OP( 7, lhz, 0x000000000000f0f0, 4, tdat1 )
    TEST_LD_OP( 8, lhz, 0x0000000000000f0f, 6, tdat1 )

    /* Load with negative offset */
    TEST_LD_OP( 9, lhz, 0x000000000000ff00, -6, tdat4 )
    TEST_LD_OP(10, lhz, 0x00000000000000ff, -4, tdat4 )
    TEST_LD_OP(11, lhz, 0x000000000000f0f0, -2, tdat4 )
    TEST_LD_OP(12, lhz, 0x0000000000000f0f,  0, tdat4 )

    /*-------------------------------------------------------------
     * Test that lhz zero-extends (not sign-extends)
     *-------------------------------------------------------------*/

test_13:
    li TESTNUM, 13
    lis %r9, tdat1@ha
    addi %r9, %r9, tdat1@l
    lhz %r8, 0(%r9)        /* Load 0xff00 */
    /* Should be 0x000000000000ff00, NOT sign-extended */
    lis %r25, 0
    ori %r25, %r25, 0xff00
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

test_14:
    li TESTNUM, 14
    lis %r9, tdat1@ha
    addi %r9, %r9, tdat1@l
    lhz %r8, 0(%r9)
    addi %r10, %r8, 0
    lis %r25, 0
    ori %r25, %r25, 0xff00
    cmpw %cr0, %r10, %r25
    bne %cr0, fail

test_15:
    li TESTNUM, 15
    lis %r9, tdat2@ha
    addi %r9, %r9, tdat2@l
    lhz %r8, 0(%r9)
    nop
    addi %r10, %r8, 0
    li %r25, 0x00ff
    cmpw %cr0, %r10, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
    .balign 8
tdat1:  .short 0xff00
tdat2:  .short 0x00ff
tdat3:  .short 0xf0f0
tdat4:  .short 0x0f0f
RVTEST_DATA_END
