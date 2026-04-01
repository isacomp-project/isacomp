/* OpenPOWER XORI (XOR Immediate) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * XORI tests - xori rA, rS, UIMM (rA = rS ^ (0 || UIMM))
     * Note: UIMM is zero-extended
     *-------------------------------------------------------------*/

    /* Basic tests */
    TEST_LOGIMM_OP( 2, xori, 0xff00f00f, 0xff00ff00, 0x0f0f )
    TEST_LOGIMM_OP( 3, xori, 0x0ff00f00, 0x0ff00ff0, 0x00f0 )
    TEST_LOGIMM_OP( 4, xori, 0x00ff0ff0, 0x00ff00ff, 0x0f0f )
    TEST_LOGIMM_OP( 5, xori, 0xf00ff0ff, 0xf00ff00f, 0x00f0 )

    /* XORI with zero immediate */
    TEST_LOGIMM_OP( 6, xori, 0x12345678, 0x12345678, 0x0000 )

    /* XORI with max immediate */
    TEST_LOGIMM_OP( 7, xori, 0x1234a987, 0x12345678, 0xffff )

    /* XORI with zero source */
    TEST_LOGIMM_OP( 8, xori, 0x0000abcd, 0x00000000, 0xabcd )

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

test_9:
    li TESTNUM, 9
    LOAD_IMM(%r9, 0xff00ff00)
    xori %r9, %r9, 0x0f0f
    LOAD_IMM(%r25, 0xff00f00f)
    cmpw %cr0, %r9, %r25
    bne %cr0, fail

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

test_10:
    li TESTNUM, 10
    LOAD_IMM(%r9, 0xff00ff00)
    xori %r8, %r9, 0x0f0f
    addi %r10, %r8, 0
    LOAD_IMM(%r25, 0xff00f00f)
    cmpw %cr0, %r10, %r25
    bne %cr0, fail

test_11:
    li TESTNUM, 11
    LOAD_IMM(%r9, 0x0ff00ff0)
    xori %r8, %r9, 0x00f0
    nop
    addi %r10, %r8, 0
    LOAD_IMM(%r25, 0x0ff00f00)
    cmpw %cr0, %r10, %r25
    bne %cr0, fail

    /*-------------------------------------------------------------
     * Zero source tests
     *-------------------------------------------------------------*/

test_12:
    li TESTNUM, 12
    li %r9, 0
    xori %r8, %r9, 0x1234
    li %r25, 0x1234
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
