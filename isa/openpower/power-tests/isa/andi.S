/* OpenPOWER ANDI. (AND Immediate, record CR0) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * ANDI. tests - andi. rA, rS, UIMM (rA = rS & (0 || UIMM))
     * Note: UIMM is zero-extended. The dot means CR0 is updated.
     *-------------------------------------------------------------*/

    /* Basic tests */
    TEST_LOGIMM_OP( 2, andi., 0x00000f00, 0xff00ff00, 0x0f0f )
    TEST_LOGIMM_OP( 3, andi., 0x000000f0, 0x0ff00ff0, 0x00f0 )
    TEST_LOGIMM_OP( 4, andi., 0x0000000f, 0x00ff00ff, 0x0f0f )
    TEST_LOGIMM_OP( 5, andi., 0x00000000, 0xf00ff00f, 0x00f0 )

    /* ANDI with zero immediate */
    TEST_LOGIMM_OP( 6, andi., 0x00000000, 0x12345678, 0x0000 )

    /* ANDI with max immediate */
    TEST_LOGIMM_OP( 7, andi., 0x00005678, 0x12345678, 0xffff )

    /* ANDI with zero source */
    TEST_LOGIMM_OP( 8, andi., 0x00000000, 0x00000000, 0xabcd )

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

test_9:
    li TESTNUM, 9
    LOAD_IMM(%r9, 0xff00ff00)
    andi. %r9, %r9, 0x0f0f
    LOAD_IMM(%r25, 0x00000f00)
    cmpw %cr0, %r9, %r25
    bne %cr0, fail

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

test_10:
    li TESTNUM, 10
    LOAD_IMM(%r9, 0xff00ff00)
    andi. %r8, %r9, 0x0f0f
    addi %r10, %r8, 0
    LOAD_IMM(%r25, 0x00000f00)
    cmpw %cr0, %r10, %r25
    bne %cr0, fail

test_11:
    li TESTNUM, 11
    LOAD_IMM(%r9, 0x0ff00ff0)
    andi. %r8, %r9, 0x00f0
    nop
    addi %r10, %r8, 0
    LOAD_IMM(%r25, 0x000000f0)
    cmpw %cr0, %r10, %r25
    bne %cr0, fail

    /*-------------------------------------------------------------
     * Zero source tests
     *-------------------------------------------------------------*/

test_12:
    li TESTNUM, 12
    li %r9, 0
    andi. %r8, %r9, 0x1234
    li %r25, 0
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
