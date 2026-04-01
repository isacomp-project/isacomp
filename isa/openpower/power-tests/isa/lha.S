/* OpenPOWER LHA (Load Halfword Algebraic) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Basic load tests - lha rD, D(rA)
     * Sign-extends halfword to 64 bits
     *-------------------------------------------------------------*/

    /* Load positive values (bit 15 = 0) */
    TEST_LD_OP( 2, lha, 0x0000000000007fff, 0, tdat_pos1 )
    TEST_LD_OP( 3, lha, 0x0000000000000001, 0, tdat_pos2 )
    TEST_LD_OP( 4, lha, 0x0000000000000000, 0, tdat_zero )

    /* Load negative values (bit 15 = 1, should sign-extend) */
test_5:
    li TESTNUM, 5
    lis %r9, tdat_neg1@ha
    addi %r9, %r9, tdat_neg1@l
    lha %r8, 0(%r9)        /* Load 0x8000 -> sign-extend to -32768 */
    lis %r25, 0xffff
    ori %r25, %r25, 0x8000
    extsw %r25, %r25       /* Sign-extend expected to 64-bit */
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_6:
    li TESTNUM, 6
    lis %r9, tdat_neg2@ha
    addi %r9, %r9, tdat_neg2@l
    lha %r8, 0(%r9)        /* Load 0xffff -> sign-extend to -1 */
    li %r25, -1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_7:
    li TESTNUM, 7
    lis %r9, tdat_neg3@ha
    addi %r9, %r9, tdat_neg3@l
    lha %r8, 0(%r9)        /* Load 0xff00 -> sign-extend to -256 */
    li %r25, -256
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Load with positive offset */
test_8:
    li TESTNUM, 8
    lis %r9, tdat_pos1@ha
    addi %r9, %r9, tdat_pos1@l
    lha %r8, 2(%r9)        /* Load tdat_pos2 */
    li %r25, 0x0001
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Load with negative offset */
test_9:
    li TESTNUM, 9
    lis %r9, tdat_neg2@ha
    addi %r9, %r9, tdat_neg2@l
    lha %r8, -2(%r9)       /* Load tdat_neg1 */
    li %r25, -32768
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

test_10:
    li TESTNUM, 10
    lis %r9, tdat_neg2@ha
    addi %r9, %r9, tdat_neg2@l
    lha %r8, 0(%r9)
    addi %r10, %r8, 0
    li %r25, -1
    cmpd %cr0, %r10, %r25
    bne %cr0, fail

test_11:
    li TESTNUM, 11
    lis %r9, tdat_pos1@ha
    addi %r9, %r9, tdat_pos1@l
    lha %r8, 0(%r9)
    nop
    addi %r10, %r8, 0
    li %r25, 0x7fff
    cmpd %cr0, %r10, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
    .balign 8
tdat_pos1:  .short 0x7fff
tdat_pos2:  .short 0x0001
tdat_zero:  .short 0x0000
tdat_neg1:  .short 0x8000
tdat_neg2:  .short 0xffff
tdat_neg3:  .short 0xff00
RVTEST_DATA_END
