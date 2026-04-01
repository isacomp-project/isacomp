/* OpenPOWER LD (Load Doubleword) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Basic load tests - ld rD, DS(rA)
     * Loads full 64-bit doubleword
     *-------------------------------------------------------------*/

    /* Load from aligned addresses */
test_2:
    li TESTNUM, 2
    lis %r9, tdat1@ha
    addi %r9, %r9, tdat1@l
    ld %r8, 0(%r9)
    lis %r25, 0x0011
    ori %r25, %r25, 0x2233
    sldi %r25, %r25, 32
    oris %r25, %r25, 0x4455
    ori %r25, %r25, 0x6677
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    lis %r9, tdat2@ha
    addi %r9, %r9, tdat2@l
    ld %r8, 0(%r9)
    lis %r25, 0xfffe
    ori %r25, %r25, 0xddcc
    sldi %r25, %r25, 32
    oris %r25, %r25, 0xbbaa
    ori %r25, %r25, 0x9988
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Load with positive offset */
test_4:
    li TESTNUM, 4
    lis %r9, tdat1@ha
    addi %r9, %r9, tdat1@l
    ld %r8, 8(%r9)         /* Load tdat2 */
    lis %r25, 0xfffe
    ori %r25, %r25, 0xddcc
    sldi %r25, %r25, 32
    oris %r25, %r25, 0xbbaa
    ori %r25, %r25, 0x9988
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Load with negative offset */
test_5:
    li TESTNUM, 5
    lis %r9, tdat2@ha
    addi %r9, %r9, tdat2@l
    ld %r8, -8(%r9)        /* Load tdat1 */
    lis %r25, 0x0011
    ori %r25, %r25, 0x2233
    sldi %r25, %r25, 32
    oris %r25, %r25, 0x4455
    ori %r25, %r25, 0x6677
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Load all zeros */
test_6:
    li TESTNUM, 6
    lis %r9, tdat_zero@ha
    addi %r9, %r9, tdat_zero@l
    ld %r8, 0(%r9)
    li %r25, 0
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Load all ones */
test_7:
    li TESTNUM, 7
    lis %r9, tdat_ones@ha
    addi %r9, %r9, tdat_ones@l
    ld %r8, 0(%r9)
    li %r25, -1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

test_8:
    li TESTNUM, 8
    lis %r9, tdat_ones@ha
    addi %r9, %r9, tdat_ones@l
    ld %r8, 0(%r9)
    addi %r10, %r8, 0
    li %r25, -1
    cmpd %cr0, %r10, %r25
    bne %cr0, fail

test_9:
    li TESTNUM, 9
    lis %r9, tdat_zero@ha
    addi %r9, %r9, tdat_zero@l
    ld %r8, 0(%r9)
    nop
    addi %r10, %r8, 0
    li %r25, 0
    cmpd %cr0, %r10, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
    .balign 8
tdat1:      .quad 0x0011223344556677
tdat2:      .quad 0xfffeddccbbaa9988
tdat_zero:  .quad 0x0000000000000000
tdat_ones:  .quad 0xffffffffffffffff
RVTEST_DATA_END
