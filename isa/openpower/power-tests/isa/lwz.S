/* OpenPOWER LWZ (Load Word and Zero) instruction tests */
/* Based on riscv-tests/mips-tests load patterns */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Basic load tests - lwz rD, D(rA)
     * Zero-extends word to 64 bits
     *-------------------------------------------------------------*/

    /* Load from aligned addresses */
    TEST_LD_OP( 2, lwz, 0x0000000000ff00ff, 0, tdat1 )
    TEST_LD_OP( 3, lwz, 0x00000000ff00ff00, 0, tdat2 )
    TEST_LD_OP( 4, lwz, 0x000000000ff00ff0, 0, tdat3 )
    TEST_LD_OP( 5, lwz, 0x00000000f00ff00f, 0, tdat4 )

    /* Load with positive offset */
    TEST_LD_OP( 6, lwz, 0x00000000ff00ff00, 4, tdat1 )
    TEST_LD_OP( 7, lwz, 0x000000000ff00ff0, 8, tdat1 )
    TEST_LD_OP( 8, lwz, 0x00000000f00ff00f, 12, tdat1 )

    /* Load with negative offset */
    TEST_LD_OP( 9, lwz, 0x0000000000ff00ff, -12, tdat4 )
    TEST_LD_OP(10, lwz, 0x00000000ff00ff00, -8, tdat4 )
    TEST_LD_OP(11, lwz, 0x000000000ff00ff0, -4, tdat4 )
    TEST_LD_OP(12, lwz, 0x00000000f00ff00f,  0, tdat4 )

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

test_13:
    li TESTNUM, 13
    lis %r9, tdat1@ha
    addi %r9, %r9, tdat1@l
    lwz %r8, 0(%r9)
    addi %r10, %r8, 0      /* immediate use */
    LOAD_IMM(%r25, 0x00ff00ff)
    cmpw %cr0, %r10, %r25
    bne %cr0, fail

test_14:
    li TESTNUM, 14
    lis %r9, tdat2@ha
    addi %r9, %r9, tdat2@l
    lwz %r8, 0(%r9)
    nop
    addi %r10, %r8, 0      /* use after 1 nop */
    LOAD_IMM(%r25, 0xff00ff00)
    cmpw %cr0, %r10, %r25
    bne %cr0, fail

test_15:
    li TESTNUM, 15
    lis %r9, tdat3@ha
    addi %r9, %r9, tdat3@l
    lwz %r8, 0(%r9)
    nop
    nop
    addi %r10, %r8, 0      /* use after 2 nops */
    LOAD_IMM(%r25, 0x0ff00ff0)
    cmpw %cr0, %r10, %r25
    bne %cr0, fail

    /*-------------------------------------------------------------
     * Test that lwz zero-extends (not sign-extends)
     * NOTE: test_16 requires srdi which is not yet implemented
     *-------------------------------------------------------------*/

    /* test_16 skipped - srdi not implemented */

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
    .balign 8
tdat1:  .long 0x00ff00ff
tdat2:  .long 0xff00ff00
tdat3:  .long 0x0ff00ff0
tdat4:  .long 0xf00ff00f
RVTEST_DATA_END
