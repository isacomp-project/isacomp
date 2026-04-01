/* j2 (SuperH-2) Test Macros for ISA testing */
/* Based on riscv-tests and mips-tests macro structure */
/* Adapted for j2 core from j-core.org */

#ifndef __J2_TEST_MACROS_H
#define __J2_TEST_MACROS_H

/*-----------------------------------------------------------------------
 * Helper macros
 *-----------------------------------------------------------------------*/

/* Test number register - R1 */
#define TESTNUM r1

/* Insert NOPs for bypass testing */
#define TEST_INSERT_NOPS_0
#define TEST_INSERT_NOPS_1  nop; TEST_INSERT_NOPS_0
#define TEST_INSERT_NOPS_2  nop; TEST_INSERT_NOPS_1
#define TEST_INSERT_NOPS_3  nop; TEST_INSERT_NOPS_2
#define TEST_INSERT_NOPS_4  nop; TEST_INSERT_NOPS_3
#define TEST_INSERT_NOPS_5  nop; TEST_INSERT_NOPS_4

/*-----------------------------------------------------------------------
 * Begin/End Test Macros
 *-----------------------------------------------------------------------*/

#define J2TEST_CODE_BEGIN \
    .text; \
    .globl _start; \
_start:

#define J2TEST_CODE_END

/*-----------------------------------------------------------------------
 * Pass/Fail Macros
 *-----------------------------------------------------------------------*/

#define TEST_PASSFAIL \
    bra pass; \
    nop;

#define J2TEST_PASS \
pass: \
    bra pass; \
    nop;

#define J2TEST_FAIL \
fail: \
    bra fail; \
    nop;

/*-----------------------------------------------------------------------
 * Data Section Macros
 *-----------------------------------------------------------------------*/

#define J2TEST_DATA_BEGIN \
    .data; \
    .align 2;

#define J2TEST_DATA_END

#define TEST_DATA

/*-----------------------------------------------------------------------
 * Core test case macro
 *-----------------------------------------------------------------------*/

#define TEST_CASE(testnum, testreg, correctval, code...) \
test_ ## testnum: \
    code; \
    mov.l test_ ## testnum ## _data, r2; \
    cmp/eq r2, testreg; \
    bt test_ ## testnum ## _pass; \
    nop; \
    bra fail; \
    nop; \
test_ ## testnum ## _pass: \
    bra 2f; \
    nop; \
    .align 2; \
test_ ## testnum ## _data: \
    .long correctval; \
2:

/*-----------------------------------------------------------------------
 * Tests for instructions with register-register operands
 *-----------------------------------------------------------------------*/

#define TEST_RR_OP(testnum, inst, result, val1, val2) \
    TEST_CASE(testnum, r3, result, \
        mov.l test_ ## testnum ## _src1, r1; \
        mov.l test_ ## testnum ## _src2, r2; \
        inst r1, r3; \
        bra 3f; \
        nop; \
        .align 2; \
    test_ ## testnum ## _src1: \
        .long val1; \
    test_ ## testnum ## _src2: \
        .long val2; \
    3: \
        mov r1, r4; \
        inst r2, r4; \
        mov r4, r3; \
    )

#define TEST_RR_SRC1_EQ_DEST(testnum, inst, result, val1, val2) \
    TEST_CASE(testnum, r1, result, \
        mov.l test_ ## testnum ## _src1, r1; \
        mov.l test_ ## testnum ## _src2, r2; \
        inst r2, r1; \
        bra 3f; \
        nop; \
        .align 2; \
    test_ ## testnum ## _src1: \
        .long val1; \
    test_ ## testnum ## _src2: \
        .long val2; \
    3: \
    )

#define TEST_RR_SRC2_EQ_DEST(testnum, inst, result, val1, val2) \
    TEST_CASE(testnum, r2, result, \
        mov.l test_ ## testnum ## _src1, r1; \
        mov.l test_ ## testnum ## _src2, r2; \
        inst r1, r2; \
        bra 3f; \
        nop; \
        .align 2; \
    test_ ## testnum ## _src1: \
        .long val1; \
    test_ ## testnum ## _src2: \
        .long val2; \
    3: \
    )

#define TEST_RR_SRC12_EQ_DEST(testnum, inst, result, val1) \
    TEST_CASE(testnum, r1, result, \
        mov.l test_ ## testnum ## _src, r1; \
        inst r1, r1; \
        bra 3f; \
        nop; \
        .align 2; \
    test_ ## testnum ## _src: \
        .long val1; \
    3: \
    )

/*-----------------------------------------------------------------------
 * Tests for instructions with register-immediate operands
 *-----------------------------------------------------------------------*/

#define TEST_IMM_OP(testnum, inst, result, val1, imm) \
    TEST_CASE(testnum, r2, result, \
        mov.l test_ ## testnum ## _src, r1; \
        inst imm, r1; \
        mov r1, r2; \
        bra 3f; \
        nop; \
        .align 2; \
    test_ ## testnum ## _src: \
        .long val1; \
    3: \
    )

/*-----------------------------------------------------------------------
 * Tests for load instructions
 *-----------------------------------------------------------------------*/

#define TEST_LD_OP(testnum, inst, result, offset, base) \
    TEST_CASE(testnum, r2, result, \
        mov.l test_ ## testnum ## _base, r1; \
        inst @r1, r2; \
        bra 3f; \
        nop; \
        .align 2; \
    test_ ## testnum ## _base: \
        .long base; \
    3: \
    )

/*-----------------------------------------------------------------------
 * Tests for store instructions
 *-----------------------------------------------------------------------*/

#define TEST_ST_OP(testnum, inst, result, offset, base) \
    TEST_CASE(testnum, r3, result, \
        mov.l test_ ## testnum ## _data, r1; \
        mov.l test_ ## testnum ## _addr, r2; \
        inst r1, @r2; \
        mov.l @r2, r3; \
        bra 3f; \
        nop; \
        .align 2; \
    test_ ## testnum ## _data: \
        .long result; \
    test_ ## testnum ## _addr: \
        .long 0x1000; \
    3: \
    )

/*-----------------------------------------------------------------------
 * Tests for branch instructions
 *-----------------------------------------------------------------------*/

#define TEST_BR_OP(testnum, inst, val1, val2, taken) \
test_ ## testnum: \
    mov.l test_ ## testnum ## _src1, r1; \
    mov.l test_ ## testnum ## _src2, r2; \
    cmp/eq r1, r2; \
    inst test_ ## testnum ## _target; \
    nop; \
    .if taken; \
        bra fail; \
        nop; \
    .else; \
        bra test_ ## testnum ## _pass; \
        nop; \
    .endif; \
test_ ## testnum ## _target: \
    .if taken; \
        bra test_ ## testnum ## _pass; \
        nop; \
    .else; \
        bra fail; \
        nop; \
    .endif; \
test_ ## testnum ## _pass: \
    bra 2f; \
    nop; \
    .align 2; \
test_ ## testnum ## _src1: \
    .long val1; \
test_ ## testnum ## _src2: \
    .long val2; \
2:

/*-----------------------------------------------------------------------
 * Bypass tests
 *-----------------------------------------------------------------------*/

/* J2/SH2 uses 2-operand format: inst Rm, Rn means Rn = Rn op Rm */
/* So to compute val1 op val2, we set Rn = val1, then do inst val2, Rn */
#define TEST_RR_DEST_BYPASS(testnum, nop_cycles, inst, result, val1, val2) \
test_ ## testnum: \
    mov.l test_ ## testnum ## _src1, r1; \
    mov.l test_ ## testnum ## _src2, r2; \
    mov r1, r3; \
    inst r2, r3; \
    TEST_INSERT_NOPS_ ## nop_cycles; \
    mov r3, r4; \
    mov.l test_ ## testnum ## _result, r5; \
    cmp/eq r4, r5; \
    bt test_ ## testnum ## _pass; \
    nop; \
    bra fail; \
    nop; \
test_ ## testnum ## _pass: \
    bra 2f; \
    nop; \
    .align 2; \
test_ ## testnum ## _src1: \
    .long val1; \
test_ ## testnum ## _src2: \
    .long val2; \
test_ ## testnum ## _result: \
    .long result; \
2:

#define TEST_RR_SRC12_BYPASS(testnum, src1_nops, src2_nops, inst, result, val1, val2) \
test_ ## testnum: \
    mov.l test_ ## testnum ## _src1, r1; \
    TEST_INSERT_NOPS_ ## src1_nops; \
    mov.l test_ ## testnum ## _src2, r2; \
    TEST_INSERT_NOPS_ ## src2_nops; \
    mov r1, r3; \
    inst r2, r3; \
    mov.l test_ ## testnum ## _result, r4; \
    cmp/eq r3, r4; \
    bt test_ ## testnum ## _pass; \
    nop; \
    bra fail; \
    nop; \
test_ ## testnum ## _pass: \
    bra 2f; \
    nop; \
    .align 2; \
test_ ## testnum ## _src1: \
    .long val1; \
test_ ## testnum ## _src2: \
    .long val2; \
test_ ## testnum ## _result: \
    .long result; \
2:

#define TEST_RR_SRC21_BYPASS(testnum, src1_nops, src2_nops, inst, result, val1, val2) \
    TEST_RR_SRC12_BYPASS(testnum, src2_nops, src1_nops, inst, result, val2, val1)

/*-----------------------------------------------------------------------
 * Zero source/dest tests
 *-----------------------------------------------------------------------*/

#define TEST_RR_ZEROSRC1(testnum, inst, result, val) \
    TEST_CASE(testnum, r2, result, \
        mov #0, r1; \
        mov.l test_ ## testnum ## _src, r3; \
        mov r1, r2; \
        inst r3, r2; \
        bra 3f; \
        nop; \
        .align 2; \
    test_ ## testnum ## _src: \
        .long val; \
    3: \
    )

#define TEST_RR_ZEROSRC2(testnum, inst, result, val) \
    TEST_CASE(testnum, r2, result, \
        mov.l test_ ## testnum ## _src, r1; \
        mov #0, r3; \
        mov r1, r2; \
        inst r3, r2; \
        bra 3f; \
        nop; \
        .align 2; \
    test_ ## testnum ## _src: \
        .long val; \
    3: \
    )

#define TEST_RR_ZEROSRC12(testnum, inst, result) \
    TEST_CASE(testnum, r2, result, \
        mov #0, r1; \
        mov r1, r2; \
        inst r1, r2; \
    )

/* J2/SH2 has no hardwired zero register, so test r0 as a normal destination */
#define TEST_RR_ZERODEST(testnum, inst, val1, val2) \
test_ ## testnum: \
    mov.l test_ ## testnum ## _src1, r1; \
    mov.l test_ ## testnum ## _src2, r2; \
    mov r1, r0; \
    inst r2, r0; \
    mov.l test_ ## testnum ## _result, r3; \
    cmp/eq r0, r3; \
    bt test_ ## testnum ## _pass; \
    nop; \
    bra fail; \
    nop; \
test_ ## testnum ## _pass: \
    bra 2f; \
    nop; \
    .align 2; \
test_ ## testnum ## _src1: \
    .long val1; \
test_ ## testnum ## _src2: \
    .long val2; \
test_ ## testnum ## _result: \
    .long (val1) + (val2); \
2:

#endif /* __J2_TEST_MACROS_H */
