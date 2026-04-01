/* OpenPOWER STD (Store Doubleword) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Basic store tests - std rS, DS(rA)
     * Stores full 64-bit doubleword
     *-------------------------------------------------------------*/

    /* Store and verify with ld */
test_2:
    li TESTNUM, 2
    lis %r9, tdat1@ha
    addi %r9, %r9, tdat1@l
    /* Create 64-bit value */
    lis %r10, 0x1122
    ori %r10, %r10, 0x3344
    sldi %r10, %r10, 32
    oris %r10, %r10, 0x5566
    ori %r10, %r10, 0x7788
    std %r10, 0(%r9)
    ld %r8, 0(%r9)
    cmpd %cr0, %r8, %r10
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    lis %r9, tdat2@ha
    addi %r9, %r9, tdat2@l
    /* Store all ones */
    li %r10, -1
    std %r10, 0(%r9)
    ld %r8, 0(%r9)
    cmpd %cr0, %r8, %r10
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    lis %r9, tdat3@ha
    addi %r9, %r9, tdat3@l
    /* Store all zeros */
    li %r10, 0
    std %r10, 0(%r9)
    ld %r8, 0(%r9)
    cmpd %cr0, %r8, %r10
    bne %cr0, fail

    /* Store with positive offset */
test_5:
    li TESTNUM, 5
    lis %r9, tdat1@ha
    addi %r9, %r9, tdat1@l
    lis %r10, 0xaabb
    ori %r10, %r10, 0xccdd
    sldi %r10, %r10, 32
    oris %r10, %r10, 0xeeff
    ori %r10, %r10, 0x0011
    std %r10, 8(%r9)       /* Store to tdat2 */
    ld %r8, 8(%r9)
    cmpd %cr0, %r8, %r10
    bne %cr0, fail

    /* Store with negative offset */
test_6:
    li TESTNUM, 6
    lis %r9, tdat4@ha
    addi %r9, %r9, tdat4@l
    lis %r10, 0xdead
    ori %r10, %r10, 0xbeef
    sldi %r10, %r10, 32
    oris %r10, %r10, 0xcafe
    ori %r10, %r10, 0xbabe
    std %r10, -8(%r9)      /* Store to tdat3 */
    ld %r8, -8(%r9)
    cmpd %cr0, %r8, %r10
    bne %cr0, fail

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

test_7:
    li TESTNUM, 7
    lis %r9, tdat_bypass@ha
    addi %r9, %r9, tdat_bypass@l
    lis %r10, 0x1234
    ori %r10, %r10, 0x5678
    sldi %r10, %r10, 32
    oris %r10, %r10, 0x9abc
    ori %r10, %r10, 0xdef0
    std %r10, 0(%r9)
    ld %r8, 0(%r9)         /* immediate load */
    cmpd %cr0, %r8, %r10
    bne %cr0, fail

test_8:
    li TESTNUM, 8
    lis %r9, tdat_bypass@ha
    addi %r9, %r9, tdat_bypass@l
    li %r10, 0x5555
    sldi %r10, %r10, 48
    std %r10, 8(%r9)
    nop
    ld %r8, 8(%r9)         /* load after 1 nop */
    cmpd %cr0, %r8, %r10
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
    .balign 8
tdat1:  .quad 0x0000000000000000
tdat2:  .quad 0x0000000000000000
tdat3:  .quad 0x0000000000000000
tdat4:  .quad 0x0000000000000000
    .balign 8
tdat_bypass:  .quad 0x0000000000000000, 0x0000000000000000
RVTEST_DATA_END
