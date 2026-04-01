/* OpenPOWER ORI (OR Immediate) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * ORI tests - ori rA, rS, UIMM (rA = rS | (0 || UIMM))
     * Note: UIMM is zero-extended, not sign-extended
     *-------------------------------------------------------------*/

    /* Basic tests */
    TEST_LOGIMM_OP( 2, ori, 0xff00ff0f, 0xff00ff00, 0x0f0f )
    TEST_LOGIMM_OP( 3, ori, 0x0ff00ff0, 0x0ff00ff0, 0x00f0 )
    TEST_LOGIMM_OP( 4, ori, 0x00ff0fff, 0x00ff00ff, 0x0f0f )
    TEST_LOGIMM_OP( 5, ori, 0xf00ff0ff, 0xf00ff00f, 0x00f0 )

    /* ORI with zero immediate */
    TEST_LOGIMM_OP( 6, ori, 0x12345678, 0x12345678, 0x0000 )

    /* ORI with max immediate */
    TEST_LOGIMM_OP( 7, ori, 0x1234ffff, 0x12340000, 0xffff )

    /* ORI with zero source */
    TEST_LOGIMM_OP( 8, ori, 0x0000abcd, 0x00000000, 0xabcd )

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

test_9:
    li TESTNUM, 9
    LOAD_IMM(%r9, 0xff00ff00)
    ori %r9, %r9, 0x0f0f
    LOAD_IMM(%r25, 0xff00ff0f)
    cmpw %cr0, %r9, %r25
    bne %cr0, fail

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

test_10:
    li TESTNUM, 10
    LOAD_IMM(%r9, 0xff00ff00)
    ori %r8, %r9, 0x0f0f
    addi %r10, %r8, 0
    LOAD_IMM(%r25, 0xff00ff0f)
    cmpw %cr0, %r10, %r25
    bne %cr0, fail

test_11:
    li TESTNUM, 11
    LOAD_IMM(%r9, 0x0ff00ff0)
    ori %r8, %r9, 0x00f0
    nop
    addi %r10, %r8, 0
    LOAD_IMM(%r25, 0x0ff00ff0)
    cmpw %cr0, %r10, %r25
    bne %cr0, fail

test_12:
    li TESTNUM, 12
    LOAD_IMM(%r9, 0x00ff00ff)
    ori %r8, %r9, 0x0f0f
    nop
    nop
    addi %r10, %r8, 0
    LOAD_IMM(%r25, 0x00ff0fff)
    cmpw %cr0, %r10, %r25
    bne %cr0, fail

    /*-------------------------------------------------------------
     * Zero source tests
     *-------------------------------------------------------------*/

test_13:
    li TESTNUM, 13
    li %r9, 0
    ori %r8, %r9, 0x1234
    li %r25, 0x1234
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
