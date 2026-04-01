/* OpenPOWER STB (Store Byte) instruction tests */
/* Based on riscv-tests/mips-tests store patterns */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Basic store tests - stb rS, D(rA)
     * Stores least significant byte
     *-------------------------------------------------------------*/

    /* Store to aligned addresses, then load back to verify */
    TEST_ST_OP( 2, lbz, stb, 0x00000000000000aa, 0, tdat1 )
    TEST_ST_OP( 3, lbz, stb, 0x0000000000000000, 0, tdat2 )
    TEST_ST_OP( 4, lbz, stb, 0x00000000000000a0, 0, tdat3 )
    TEST_ST_OP( 5, lbz, stb, 0x000000000000000a, 0, tdat4 )

    /* Store with positive offset */
    TEST_ST_OP( 6, lbz, stb, 0x00000000000000bb, 1, tdat1 )
    TEST_ST_OP( 7, lbz, stb, 0x00000000000000cc, 2, tdat1 )
    TEST_ST_OP( 8, lbz, stb, 0x00000000000000dd, 3, tdat1 )

    /* Store with negative offset */
    TEST_ST_OP( 9, lbz, stb, 0x00000000000000ee, -3, tdat8 )
    TEST_ST_OP(10, lbz, stb, 0x00000000000000ff, -2, tdat8 )
    TEST_ST_OP(11, lbz, stb, 0x0000000000000011, -1, tdat8 )

    /*-------------------------------------------------------------
     * Verify that only LSB is stored
     *-------------------------------------------------------------*/

test_12:
    li TESTNUM, 12
    lis %r9, tdat_verify@ha
    addi %r9, %r9, tdat_verify@l
    /* Load a large value into register */
    LOAD_IMM(%r10, 0x12345678)
    /* Store byte - should only store 0x78 */
    stb %r10, 0(%r9)
    /* Load back */
    lbz %r8, 0(%r9)
    li %r25, 0x78
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /*-------------------------------------------------------------
     * Bypassing tests - store followed by load
     *-------------------------------------------------------------*/

test_13:
    li TESTNUM, 13
    lis %r9, tdat_bypass@ha
    addi %r9, %r9, tdat_bypass@l
    li %r10, 0x55
    stb %r10, 0(%r9)
    lbz %r8, 0(%r9)        /* immediate load after store */
    li %r25, 0x55
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_14:
    li TESTNUM, 14
    lis %r9, tdat_bypass@ha
    addi %r9, %r9, tdat_bypass@l
    li %r10, 0x66
    stb %r10, 1(%r9)
    nop
    lbz %r8, 1(%r9)        /* load after 1 nop */
    li %r25, 0x66
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_15:
    li TESTNUM, 15
    lis %r9, tdat_bypass@ha
    addi %r9, %r9, tdat_bypass@l
    li %r10, 0x77
    stb %r10, 2(%r9)
    nop
    nop
    lbz %r8, 2(%r9)        /* load after 2 nops */
    li %r25, 0x77
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
    .balign 8
tdat1:  .byte 0xef
tdat2:  .byte 0xef
tdat3:  .byte 0xef
tdat4:  .byte 0xef
tdat5:  .byte 0xef
tdat6:  .byte 0xef
tdat7:  .byte 0xef
tdat8:  .byte 0xef
    .balign 8
tdat_verify:  .byte 0x00
    .balign 8
tdat_bypass:  .byte 0x00, 0x00, 0x00, 0x00
RVTEST_DATA_END
