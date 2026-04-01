/* OpenPOWER STW (Store Word) instruction tests */
/* Based on riscv-tests/mips-tests store patterns */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Basic store tests - stw rS, D(rA)
     * Stores least significant word (32 bits)
     *-------------------------------------------------------------*/

    /* Store to aligned addresses, then load back to verify */
    TEST_ST_OP( 2, lwz, stw, 0x0000000000aa00aa, 0, tdat1 )
    TEST_ST_OP( 3, lwz, stw, 0x00000000aa00aa00, 0, tdat2 )
    TEST_ST_OP( 4, lwz, stw, 0x000000000aa00aa0, 0, tdat3 )
    TEST_ST_OP( 5, lwz, stw, 0x00000000a00aa00a, 0, tdat4 )

    /* Store with positive offset */
    TEST_ST_OP( 6, lwz, stw, 0x0000000011223344, 4, tdat1 )
    TEST_ST_OP( 7, lwz, stw, 0x0000000055667788, 8, tdat1 )
    TEST_ST_OP( 8, lwz, stw, 0x0000000099aabbcc, 12, tdat1 )

    /* Store with negative offset */
    TEST_ST_OP( 9, lwz, stw, 0x00000000deadbeef, -12, tdat8 )
    TEST_ST_OP(10, lwz, stw, 0x00000000cafebabe, -8, tdat8 )
    TEST_ST_OP(11, lwz, stw, 0x00000000feedface, -4, tdat8 )

    /*-------------------------------------------------------------
     * Verify that only LSW is stored
     *-------------------------------------------------------------*/

test_12:
    li TESTNUM, 12
    lis %r9, tdat_verify@ha
    addi %r9, %r9, tdat_verify@l
    /* Load a 64-bit value into register */
    lis %r10, 0x1234
    ori %r10, %r10, 0x5678
    sldi %r10, %r10, 32
    oris %r10, %r10, 0xabcd
    ori %r10, %r10, 0xef01
    /* r10 = 0x12345678abcdef01 */
    /* Store word - should only store 0xabcdef01 */
    stw %r10, 0(%r9)
    /* Load back */
    lwz %r8, 0(%r9)
    LOAD_IMM(%r25, 0xabcdef01)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /*-------------------------------------------------------------
     * Bypassing tests - store followed by load
     *-------------------------------------------------------------*/

test_13:
    li TESTNUM, 13
    lis %r9, tdat_bypass@ha
    addi %r9, %r9, tdat_bypass@l
    LOAD_IMM(%r10, 0x12345678)
    stw %r10, 0(%r9)
    lwz %r8, 0(%r9)        /* immediate load after store */
    LOAD_IMM(%r25, 0x12345678)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_14:
    li TESTNUM, 14
    lis %r9, tdat_bypass@ha
    addi %r9, %r9, tdat_bypass@l
    LOAD_IMM(%r10, 0x87654321)
    stw %r10, 4(%r9)
    nop
    lwz %r8, 4(%r9)        /* load after 1 nop */
    LOAD_IMM(%r25, 0x87654321)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_15:
    li TESTNUM, 15
    lis %r9, tdat_bypass@ha
    addi %r9, %r9, tdat_bypass@l
    LOAD_IMM(%r10, 0xfedcba98)
    stw %r10, 8(%r9)
    nop
    nop
    lwz %r8, 8(%r9)        /* load after 2 nops */
    LOAD_IMM(%r25, 0xfedcba98)
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
    .balign 8
tdat1:  .long 0xdeadbeef
tdat2:  .long 0xdeadbeef
tdat3:  .long 0xdeadbeef
tdat4:  .long 0xdeadbeef
tdat5:  .long 0xdeadbeef
tdat6:  .long 0xdeadbeef
tdat7:  .long 0xdeadbeef
tdat8:  .long 0xdeadbeef
    .balign 8
tdat_verify:  .long 0x00000000
    .balign 8
tdat_bypass:  .long 0x00000000, 0x00000000, 0x00000000, 0x00000000
RVTEST_DATA_END
