/* OpenPOWER STH (Store Halfword) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Basic store tests - sth rS, D(rA)
     * Stores least significant halfword
     *-------------------------------------------------------------*/

    /* Store to aligned addresses, then load back */
    TEST_ST_OP( 2, lhz, sth, 0x000000000000aabb, 0, tdat1 )
    TEST_ST_OP( 3, lhz, sth, 0x000000000000ccdd, 0, tdat2 )
    TEST_ST_OP( 4, lhz, sth, 0x000000000000eeff, 0, tdat3 )
    TEST_ST_OP( 5, lhz, sth, 0x0000000000001122, 0, tdat4 )

    /* Store with positive offset */
    TEST_ST_OP( 6, lhz, sth, 0x0000000000003344, 2, tdat1 )
    TEST_ST_OP( 7, lhz, sth, 0x0000000000005566, 4, tdat1 )

    /* Store with negative offset */
    TEST_ST_OP( 8, lhz, sth, 0x0000000000007788, -4, tdat8 )
    TEST_ST_OP( 9, lhz, sth, 0x00000000000099aa, -2, tdat8 )

    /*-------------------------------------------------------------
     * Verify that only LSH is stored
     *-------------------------------------------------------------*/

test_10:
    li TESTNUM, 10
    lis %r9, tdat_verify@ha
    addi %r9, %r9, tdat_verify@l
    /* Load a large value */
    LOAD_IMM(%r10, 0x12345678)
    /* Store halfword - should only store 0x5678 */
    sth %r10, 0(%r9)
    /* Load back */
    lhz %r8, 0(%r9)
    lis %r25, 0
    ori %r25, %r25, 0x5678
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

test_11:
    li TESTNUM, 11
    lis %r9, tdat_bypass@ha
    addi %r9, %r9, tdat_bypass@l
    lis %r10, 0
    ori %r10, %r10, 0xabcd
    sth %r10, 0(%r9)
    lhz %r8, 0(%r9)
    lis %r25, 0
    ori %r25, %r25, 0xabcd
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_12:
    li TESTNUM, 12
    lis %r9, tdat_bypass@ha
    addi %r9, %r9, tdat_bypass@l
    lis %r10, 0
    ori %r10, %r10, 0xef01
    sth %r10, 2(%r9)
    nop
    lhz %r8, 2(%r9)
    lis %r25, 0
    ori %r25, %r25, 0xef01
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
    .balign 8
tdat1:  .short 0xbeef
tdat2:  .short 0xbeef
tdat3:  .short 0xbeef
tdat4:  .short 0xbeef
tdat5:  .short 0xbeef
tdat6:  .short 0xbeef
tdat7:  .short 0xbeef
tdat8:  .short 0xbeef
    .balign 8
tdat_verify:  .short 0x0000
    .balign 8
tdat_bypass:  .short 0x0000, 0x0000, 0x0000, 0x0000
RVTEST_DATA_END
