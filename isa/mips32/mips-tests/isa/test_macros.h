/* MIPS32 Test Macros for ISA testing */
/* Based on riscv-tests macro structure */

#ifndef __MIPS32_TEST_MACROS_H
#define __MIPS32_TEST_MACROS_H

/*-----------------------------------------------------------------------
 * Helper macros
 *-----------------------------------------------------------------------*/

/* Test number register - $v0 ($2) */
#define TESTNUM $2

/* Insert NOPs for bypass testing */
#define TEST_INSERT_NOPS_0
#define TEST_INSERT_NOPS_1  nop; TEST_INSERT_NOPS_0
#define TEST_INSERT_NOPS_2  nop; TEST_INSERT_NOPS_1
#define TEST_INSERT_NOPS_3  nop; TEST_INSERT_NOPS_2
#define TEST_INSERT_NOPS_4  nop; TEST_INSERT_NOPS_3
#define TEST_INSERT_NOPS_5  nop; TEST_INSERT_NOPS_4

/* Core test case macro */
#define TEST_CASE(testnum, destreg, result, code...) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    code; \
    li $t9, result; \
    bne destreg, $t9, fail; \
    nop;

/*-----------------------------------------------------------------------
 * Tests for instructions with register-register operands
 *-----------------------------------------------------------------------*/

#define TEST_RR_OP(testnum, inst, result, val1, val2) \
    TEST_CASE(testnum, $t0, result, \
        li $t1, val1; \
        li $t2, val2; \
        inst $t0, $t1, $t2; \
    )

#define TEST_RR_SRC1_EQ_DEST(testnum, inst, result, val1, val2) \
    TEST_CASE(testnum, $t1, result, \
        li $t1, val1; \
        li $t2, val2; \
        inst $t1, $t1, $t2; \
    )

#define TEST_RR_SRC2_EQ_DEST(testnum, inst, result, val1, val2) \
    TEST_CASE(testnum, $t2, result, \
        li $t1, val1; \
        li $t2, val2; \
        inst $t2, $t1, $t2; \
    )

#define TEST_RR_SRC12_EQ_DEST(testnum, inst, result, val1) \
    TEST_CASE(testnum, $t1, result, \
        li $t1, val1; \
        inst $t1, $t1, $t1; \
    )

#define TEST_RR_DEST_BYPASS(testnum, nop_cycles, inst, result, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t4, 0; \
1:  li $t1, val1; \
    li $t2, val2; \
    inst $t0, $t1, $t2; \
    TEST_INSERT_NOPS_ ## nop_cycles \
    addi $t3, $t0, 0; \
    addi $t4, $t4, 1; \
    li $t5, 2; \
    bne $t4, $t5, 1b; \
    nop; \
    li $t9, result; \
    bne $t3, $t9, fail; \
    nop;

#define TEST_RR_SRC12_BYPASS(testnum, src1_nops, src2_nops, inst, result, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t4, 0; \
1:  li $t1, val1; \
    TEST_INSERT_NOPS_ ## src1_nops \
    li $t2, val2; \
    TEST_INSERT_NOPS_ ## src2_nops \
    inst $t0, $t1, $t2; \
    addi $t4, $t4, 1; \
    li $t5, 2; \
    bne $t4, $t5, 1b; \
    nop; \
    li $t9, result; \
    bne $t0, $t9, fail; \
    nop;

#define TEST_RR_SRC21_BYPASS(testnum, src1_nops, src2_nops, inst, result, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t4, 0; \
1:  li $t2, val2; \
    TEST_INSERT_NOPS_ ## src1_nops \
    li $t1, val1; \
    TEST_INSERT_NOPS_ ## src2_nops \
    inst $t0, $t1, $t2; \
    addi $t4, $t4, 1; \
    li $t5, 2; \
    bne $t4, $t5, 1b; \
    nop; \
    li $t9, result; \
    bne $t0, $t9, fail; \
    nop;

#define TEST_RR_ZEROSRC1(testnum, inst, result, val) \
    TEST_CASE(testnum, $t0, result, \
        li $t1, val; \
        inst $t0, $zero, $t1; \
    )

#define TEST_RR_ZEROSRC2(testnum, inst, result, val) \
    TEST_CASE(testnum, $t0, result, \
        li $t1, val; \
        inst $t0, $t1, $zero; \
    )

#define TEST_RR_ZEROSRC12(testnum, inst, result) \
    TEST_CASE(testnum, $t0, result, \
        inst $t0, $zero, $zero; \
    )

#define TEST_RR_ZERODEST(testnum, inst, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t1, val1; \
    li $t2, val2; \
    inst $zero, $t1, $t2; \
    bne $zero, $zero, fail; \
    nop;

/*-----------------------------------------------------------------------
 * Tests for instructions with immediate operands
 *-----------------------------------------------------------------------*/

#define TEST_IMM_OP(testnum, inst, result, val1, imm) \
    TEST_CASE(testnum, $t0, result, \
        li $t1, val1; \
        inst $t0, $t1, imm; \
    )

#define TEST_IMM_SRC1_EQ_DEST(testnum, inst, result, val1, imm) \
    TEST_CASE(testnum, $t1, result, \
        li $t1, val1; \
        inst $t1, $t1, imm; \
    )

#define TEST_IMM_DEST_BYPASS(testnum, nop_cycles, inst, result, val1, imm) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t4, 0; \
1:  li $t1, val1; \
    inst $t0, $t1, imm; \
    TEST_INSERT_NOPS_ ## nop_cycles \
    addi $t3, $t0, 0; \
    addi $t4, $t4, 1; \
    li $t5, 2; \
    bne $t4, $t5, 1b; \
    nop; \
    li $t9, result; \
    bne $t3, $t9, fail; \
    nop;

#define TEST_IMM_SRC1_BYPASS(testnum, nop_cycles, inst, result, val1, imm) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t4, 0; \
1:  li $t1, val1; \
    TEST_INSERT_NOPS_ ## nop_cycles \
    inst $t0, $t1, imm; \
    addi $t4, $t4, 1; \
    li $t5, 2; \
    bne $t4, $t5, 1b; \
    nop; \
    li $t9, result; \
    bne $t0, $t9, fail; \
    nop;

#define TEST_IMM_ZEROSRC1(testnum, inst, result, imm) \
    TEST_CASE(testnum, $t0, result, \
        inst $t0, $zero, imm; \
    )

#define TEST_IMM_ZERODEST(testnum, inst, val1, imm) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t1, val1; \
    inst $zero, $t1, imm; \
    bne $zero, $zero, fail; \
    nop;

/*-----------------------------------------------------------------------
 * Tests for shift instructions with shamt operand
 *-----------------------------------------------------------------------*/

#define TEST_SHIFT_OP(testnum, inst, result, val1, shamt) \
    TEST_CASE(testnum, $t0, result, \
        li $t1, val1; \
        inst $t0, $t1, shamt; \
    )

#define TEST_SHIFT_SRC1_EQ_DEST(testnum, inst, result, val1, shamt) \
    TEST_CASE(testnum, $t1, result, \
        li $t1, val1; \
        inst $t1, $t1, shamt; \
    )

#define TEST_SHIFT_ZERODEST(testnum, inst, val1, shamt) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t1, val1; \
    inst $zero, $t1, shamt; \
    bne $zero, $zero, fail; \
    nop;

/*-----------------------------------------------------------------------
 * Tests for load instructions
 *-----------------------------------------------------------------------*/

#define TEST_LD_OP(testnum, inst, result, offset, base) \
    TEST_CASE(testnum, $t0, result, \
        la $t1, base; \
        inst $t0, offset($t1); \
    )

#define TEST_LD_DEST_BYPASS(testnum, nop_cycles, inst, result, offset, base) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t4, 0; \
1:  la $t1, base; \
    inst $t0, offset($t1); \
    TEST_INSERT_NOPS_ ## nop_cycles \
    addi $t3, $t0, 0; \
    addi $t4, $t4, 1; \
    li $t5, 2; \
    bne $t4, $t5, 1b; \
    nop; \
    li $t9, result; \
    bne $t3, $t9, fail; \
    nop;

#define TEST_LD_SRC1_BYPASS(testnum, nop_cycles, inst, result, offset, base) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t4, 0; \
1:  la $t1, base; \
    TEST_INSERT_NOPS_ ## nop_cycles \
    inst $t0, offset($t1); \
    addi $t4, $t4, 1; \
    li $t5, 2; \
    bne $t4, $t5, 1b; \
    nop; \
    li $t9, result; \
    bne $t0, $t9, fail; \
    nop;

/*-----------------------------------------------------------------------
 * Tests for store instructions
 *-----------------------------------------------------------------------*/

#define TEST_ST_OP(testnum, load_inst, store_inst, result, offset, base) \
    TEST_CASE(testnum, $t0, result, \
        la $t1, base; \
        li $t2, result; \
        store_inst $t2, offset($t1); \
        load_inst $t0, offset($t1); \
    )

#define TEST_ST_SRC12_BYPASS(testnum, src1_nops, src2_nops, load_inst, store_inst, result, offset, base) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t4, 0; \
1:  li $t2, result; \
    TEST_INSERT_NOPS_ ## src1_nops \
    la $t1, base; \
    TEST_INSERT_NOPS_ ## src2_nops \
    store_inst $t2, offset($t1); \
    load_inst $t0, offset($t1); \
    addi $t4, $t4, 1; \
    li $t5, 2; \
    bne $t4, $t5, 1b; \
    nop; \
    li $t9, result; \
    bne $t0, $t9, fail; \
    nop;

#define TEST_ST_SRC21_BYPASS(testnum, src1_nops, src2_nops, load_inst, store_inst, result, offset, base) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t4, 0; \
1:  la $t1, base; \
    TEST_INSERT_NOPS_ ## src1_nops \
    li $t2, result; \
    TEST_INSERT_NOPS_ ## src2_nops \
    store_inst $t2, offset($t1); \
    load_inst $t0, offset($t1); \
    addi $t4, $t4, 1; \
    li $t5, 2; \
    bne $t4, $t5, 1b; \
    nop; \
    li $t9, result; \
    bne $t0, $t9, fail; \
    nop;

/*-----------------------------------------------------------------------
 * Tests for branch instructions
 *-----------------------------------------------------------------------*/

/*
 * With DELAY_SLOT defined, the instruction after a taken branch/jump
 * executes before the branch takes effect. The macros below use a NOP
 * in the delay slot position, which produces identical observable
 * behaviour in both modes. See delay_slot.S for tests that exercise
 * meaningful delay slot instructions.
 */

#define TEST_BR2_OP_TAKEN(testnum, inst, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t1, val1; \
    li $t2, val2; \
    inst $t1, $t2, 2f; \
    nop; \
    j fail; \
    nop; \
1:  j 3f; \
    nop; \
2:  inst $t1, $t2, 1b; \
    nop; \
    j fail; \
    nop; \
3:

#define TEST_BR2_OP_NOTTAKEN(testnum, inst, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t1, val1; \
    li $t2, val2; \
    inst $t1, $t2, 1f; \
    nop; \
    j 2f; \
    nop; \
1:  j fail; \
    nop; \
2:  inst $t1, $t2, 1b; \
    nop;

#define TEST_BR2_SRC12_BYPASS(testnum, src1_nops, src2_nops, inst, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t4, 0; \
1:  li $t1, val1; \
    TEST_INSERT_NOPS_ ## src1_nops \
    li $t2, val2; \
    TEST_INSERT_NOPS_ ## src2_nops \
    inst $t1, $t2, fail; \
    nop; \
    addi $t4, $t4, 1; \
    li $t5, 2; \
    bne $t4, $t5, 1b; \
    nop;

#define TEST_BR2_SRC21_BYPASS(testnum, src1_nops, src2_nops, inst, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t4, 0; \
1:  li $t2, val2; \
    TEST_INSERT_NOPS_ ## src1_nops \
    li $t1, val1; \
    TEST_INSERT_NOPS_ ## src2_nops \
    inst $t1, $t2, fail; \
    nop; \
    addi $t4, $t4, 1; \
    li $t5, 2; \
    bne $t4, $t5, 1b; \
    nop;

/*-----------------------------------------------------------------------
 * Delay-slot-aware branch tests
 * These use a meaningful instruction in the delay slot position.
 * With DELAY_SLOT: the delay slot instruction executes, affecting the result.
 * Without DELAY_SLOT: the delay slot instruction is skipped on taken branches.
 *-----------------------------------------------------------------------*/

#ifdef DELAY_SLOT

/* Branch taken with delay slot work: delay slot adds 1 to $t0 */
#define TEST_BR2_OP_TAKEN_DS(testnum, inst, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t0, 0; \
    li $t1, val1; \
    li $t2, val2; \
    inst $t1, $t2, 1f; \
    addi $t0, $t0, 1; \
    j fail; \
    nop; \
1:  li $t9, 1; \
    bne $t0, $t9, fail; \
    nop;

/* Branch not taken with delay slot work: instruction always executes */
#define TEST_BR2_OP_NOTTAKEN_DS(testnum, inst, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t0, 0; \
    li $t1, val1; \
    li $t2, val2; \
    inst $t1, $t2, fail; \
    addi $t0, $t0, 1; \
    li $t9, 1; \
    bne $t0, $t9, fail; \
    nop;

#else /* !DELAY_SLOT */

/* Without delay slots: instruction after taken branch does NOT execute */
#define TEST_BR2_OP_TAKEN_DS(testnum, inst, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t0, 0; \
    li $t1, val1; \
    li $t2, val2; \
    inst $t1, $t2, 1f; \
    addi $t0, $t0, 1; \
    j fail; \
    nop; \
1:  li $t9, 0; \
    bne $t0, $t9, fail; \
    nop;

/* Without delay slots: instruction after not-taken branch executes normally */
#define TEST_BR2_OP_NOTTAKEN_DS(testnum, inst, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t0, 0; \
    li $t1, val1; \
    li $t2, val2; \
    inst $t1, $t2, fail; \
    addi $t0, $t0, 1; \
    li $t9, 1; \
    bne $t0, $t9, fail; \
    nop;

#endif /* DELAY_SLOT */

/*-----------------------------------------------------------------------
 * Tests for jump instructions
 *-----------------------------------------------------------------------*/

#define TEST_JR_SRC1_BYPASS(testnum, nop_cycles) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t4, 0; \
1:  la $t3, 2f; \
    TEST_INSERT_NOPS_ ## nop_cycles \
    jr $t3; \
    nop; \
    j fail; \
    nop; \
2:  addi $t4, $t4, 1; \
    li $t5, 2; \
    bne $t4, $t5, 1b; \
    nop;

#define TEST_JALR_SRC1_BYPASS(testnum, nop_cycles) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t4, 0; \
1:  la $t3, 2f; \
    TEST_INSERT_NOPS_ ## nop_cycles \
    jalr $ra, $t3; \
    nop; \
    j fail; \
    nop; \
2:  addi $t4, $t4, 1; \
    li $t5, 2; \
    bne $t4, $t5, 1b; \
    nop;

/*-----------------------------------------------------------------------
 * Delay-slot-aware jump tests
 * These put meaningful instructions in the delay slot to validate
 * that the delay slot executes (DELAY_SLOT) or is skipped (!DELAY_SLOT).
 *-----------------------------------------------------------------------*/

#ifdef DELAY_SLOT

#define TEST_JR_SRC1_BYPASS_DS(testnum, nop_cycles) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t0, 0; \
    la $t3, 1f; \
    TEST_INSERT_NOPS_ ## nop_cycles \
    jr $t3; \
    addi $t0, $t0, 1; \
    j fail; \
    nop; \
1:  li $t9, 1; \
    bne $t0, $t9, fail; \
    nop;

#define TEST_JALR_SRC1_BYPASS_DS(testnum, nop_cycles) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t0, 0; \
    la $t3, 1f; \
    TEST_INSERT_NOPS_ ## nop_cycles \
    jalr $ra, $t3; \
    addi $t0, $t0, 1; \
    j fail; \
    nop; \
1:  li $t9, 1; \
    bne $t0, $t9, fail; \
    nop;

#else /* !DELAY_SLOT */

#define TEST_JR_SRC1_BYPASS_DS(testnum, nop_cycles) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t0, 0; \
    la $t3, 1f; \
    TEST_INSERT_NOPS_ ## nop_cycles \
    jr $t3; \
    addi $t0, $t0, 1; \
    j fail; \
    nop; \
1:  li $t9, 0; \
    bne $t0, $t9, fail; \
    nop;

#define TEST_JALR_SRC1_BYPASS_DS(testnum, nop_cycles) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t0, 0; \
    la $t3, 1f; \
    TEST_INSERT_NOPS_ ## nop_cycles \
    jalr $ra, $t3; \
    addi $t0, $t0, 1; \
    j fail; \
    nop; \
1:  li $t9, 0; \
    bne $t0, $t9, fail; \
    nop;

#endif /* DELAY_SLOT */

/*-----------------------------------------------------------------------
 * Tests for LUI instruction
 *-----------------------------------------------------------------------*/

#define TEST_LUI_OP(testnum, result, imm) \
    TEST_CASE(testnum, $t0, result, \
        lui $t0, imm; \
    )

/*-----------------------------------------------------------------------
 * Legacy bypass macros (for compatibility)
 *-----------------------------------------------------------------------*/

#define TEST_RR_SRC1_BYPASS(testnum, nops, inst, result, val1, val2) \
    TEST_RR_SRC12_BYPASS(testnum, nops, 0, inst, result, val1, val2)

#define TEST_RR_SRC2_BYPASS(testnum, nops, inst, result, val1, val2) \
    TEST_RR_SRC21_BYPASS(testnum, 0, nops, inst, result, val1, val2)

#define TEST_RR_ZERO_DEST(testnum, inst, val1, val2) \
    TEST_RR_ZERODEST(testnum, inst, val1, val2)

#define TEST_IMM_ZERO_DEST(testnum, inst, val1, imm) \
    TEST_IMM_ZERODEST(testnum, inst, val1, imm)

/*-----------------------------------------------------------------------
 * Test framework macros
 *-----------------------------------------------------------------------*/

#define RVTEST_CODE_BEGIN \
    .set noreorder; \
    .set noat; \
    .text; \
    .globl _start; \
    _start: \
    li $sp, 0x1ffc; \
    li $2, 0; \
    li $3, 0;

#define RVTEST_CODE_END

#define TEST_PASSFAIL \
    j pass; \
    nop;

#define RVTEST_PASS \
pass: \
    j pass; \
    nop

#define RVTEST_FAIL \
fail: \
    j fail; \
    nop

#define RVTEST_DATA_BEGIN \
    .data; \
    .align 2;

#define RVTEST_DATA_END

#define TEST_DATA

/*-----------------------------------------------------------------------
 * IEEE 754 Floating-Point Test Macros
 *-----------------------------------------------------------------------*/

/* FP Constants for single-precision (IEEE 754) */
#define qNaNf 0x7fc00000   /* Quiet NaN */
#define sNaNf 0x7f800001   /* Signaling NaN */
#define Inff  0x7f800000   /* Positive infinity */
#define nInff 0xff800000   /* Negative infinity */
#define nZerof 0x80000000  /* Negative zero */

/* Helper: Load single-precision FP value by hex pattern */
#define LOAD_FP_HEX(fpreg, gpreg, hexval) \
    li gpreg, hexval; \
    mtc1 gpreg, fpreg;

/* Helper: Store FP result to integer register for comparison */
#define STORE_FP_TO_INT(fpreg, gpreg) \
    mfc1 gpreg, fpreg;

/*-----------------------------------------------------------------------
 * Tests for FP register-register operations (2 operands)
 * Format: inst.s fd, fs, ft
 *-----------------------------------------------------------------------*/

#define TEST_FP_OP2_S(testnum, inst, result_hex, val1_hex, val2_hex) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX($f0, $t1, val1_hex); \
    LOAD_FP_HEX($f2, $t2, val2_hex); \
    inst $f4, $f0, $f2; \
    STORE_FP_TO_INT($f4, $t0); \
    li $t9, result_hex; \
    bne $t0, $t9, fail; \
    nop;

/*-----------------------------------------------------------------------
 * Tests for FP unary operations (1 operand)
 * Format: inst.s fd, fs
 *-----------------------------------------------------------------------*/

#define TEST_FP_OP1_S(testnum, inst, result_hex, val1_hex) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX($f0, $t1, val1_hex); \
    inst $f2, $f0; \
    STORE_FP_TO_INT($f2, $t0); \
    li $t9, result_hex; \
    bne $t0, $t9, fail; \
    nop;

/*-----------------------------------------------------------------------
 * Tests for FP comparison operations
 * Format: c.cond.s fs, ft
 * Result is in FP condition code
 *-----------------------------------------------------------------------*/

#define TEST_FP_CMP_S(testnum, inst, expected, val1_hex, val2_hex) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX($f0, $t1, val1_hex); \
    LOAD_FP_HEX($f1, $t2, val2_hex); \
    inst $f0, $f1; \
    bc1t 1f; \
    nop; \
    li $t0, 0; \
    j 2f; \
    nop; \
1:  li $t0, 1; \
2:  li $t9, expected; \
    bne $t0, $t9, fail; \
    nop;

/*-----------------------------------------------------------------------
 * Tests for FP-to-Integer conversion
 * Format: cvt.w.s fd, fs
 *-----------------------------------------------------------------------*/

#define TEST_FP_CVT_W_S(testnum, result, val1_hex) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX($f0, $t1, val1_hex); \
    cvt.w.s $f2, $f0; \
    STORE_FP_TO_INT($f2, $t0); \
    li $t9, result; \
    bne $t0, $t9, fail; \
    nop;

/*-----------------------------------------------------------------------
 * Tests for Integer-to-FP conversion
 * Format: cvt.s.w fd, fs
 *-----------------------------------------------------------------------*/

#define TEST_INT_FP_CVT_S_W(testnum, result_hex, val1) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t1, val1; \
    mtc1 $t1, $f0; \
    cvt.s.w $f2, $f0; \
    STORE_FP_TO_INT($f2, $t0); \
    li $t9, result_hex; \
    bne $t0, $t9, fail; \
    nop;

/*-----------------------------------------------------------------------
 * Tests for FP load/store
 *-----------------------------------------------------------------------*/

#define TEST_FP_LD_OP(testnum, inst, result_hex, offset, base) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    la $t1, base; \
    inst $f0, offset($t1); \
    STORE_FP_TO_INT($f0, $t0); \
    li $t9, result_hex; \
    bne $t0, $t9, fail; \
    nop;

#define TEST_FP_ST_OP(testnum, val_hex, offset, base) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX($f0, $t1, val_hex); \
    la $t2, base; \
    swc1 $f0, offset($t2); \
    lwc1 $f1, offset($t2); \
    STORE_FP_TO_INT($f1, $t0); \
    li $t9, val_hex; \
    bne $t0, $t9, fail; \
    nop;

/*-----------------------------------------------------------------------
 * Tests for FP move between integer and FP registers
 *-----------------------------------------------------------------------*/

#define TEST_FP_MFC1(testnum, result, val_hex) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX($f0, $t1, val_hex); \
    mfc1 $t0, $f0; \
    li $t9, result; \
    bne $t0, $t9, fail; \
    nop;

#define TEST_FP_MTC1(testnum, result_hex, val) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t1, val; \
    mtc1 $t1, $f0; \
    STORE_FP_TO_INT($f0, $t0); \
    li $t9, result_hex; \
    bne $t0, $t9, fail; \
    nop;

/*-----------------------------------------------------------------------
 * Tests for FP fused multiply-add (3 operands)
 * Format: madd.s fd, fr, fs, ft  (fd = fr + fs*ft)
 *-----------------------------------------------------------------------*/

#define TEST_FP_OP3_S(testnum, inst, result_hex, val1_hex, val2_hex, val3_hex) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX($f0, $t1, val1_hex); \
    LOAD_FP_HEX($f1, $t2, val2_hex); \
    LOAD_FP_HEX($f2, $t3, val3_hex); \
    inst $f3, $f0, $f1, $f2; \
    STORE_FP_TO_INT($f3, $t0); \
    li $t9, result_hex; \
    bne $t0, $t9, fail; \
    nop;

/*-----------------------------------------------------------------------
 * IEEE 754 Double-Precision Floating-Point Test Macros
 *-----------------------------------------------------------------------*/

/* Helper: Load double-precision FP value by hex pattern (two words) */
#define LOAD_FP_HEX_D(fpreg, gpreg1, gpreg2, hi_hex, lo_hex) \
    li gpreg1, lo_hex; \
    li gpreg2, hi_hex; \
    mtc1 gpreg1, fpreg; \
    mthc1 gpreg2, fpreg;

/* Helper: Store double FP result to integer registers for comparison */
#define STORE_FP_TO_INT_D(fpreg, gpreg_lo, gpreg_hi) \
    mfc1 gpreg_lo, fpreg; \
    mfhc1 gpreg_hi, fpreg;

/*-----------------------------------------------------------------------
 * Tests for double-precision FP register-register operations (2 operands)
 * Format: inst.d fd, fs, ft
 *-----------------------------------------------------------------------*/

#define TEST_FP_OP2_D(testnum, inst, result_hi, result_lo, val1_hi, val1_lo, val2_hi, val2_lo) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX_D($f0, $t1, $t2, val1_hi, val1_lo); \
    LOAD_FP_HEX_D($f2, $t3, $t4, val2_hi, val2_lo); \
    inst $f4, $f0, $f2; \
    STORE_FP_TO_INT_D($f4, $t0, $t5); \
    li $t9, result_lo; \
    bne $t0, $t9, fail; \
    nop; \
    li $t9, result_hi; \
    bne $t5, $t9, fail; \
    nop;

/*-----------------------------------------------------------------------
 * Tests for double-precision FP unary operations (1 operand)
 * Format: inst.d fd, fs
 *-----------------------------------------------------------------------*/

#define TEST_FP_OP1_D(testnum, inst, result_hi, result_lo, val1_hi, val1_lo) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX_D($f0, $t1, $t2, val1_hi, val1_lo); \
    inst $f2, $f0; \
    STORE_FP_TO_INT_D($f2, $t0, $t5); \
    li $t9, result_lo; \
    bne $t0, $t9, fail; \
    nop; \
    li $t9, result_hi; \
    bne $t5, $t9, fail; \
    nop;

/*-----------------------------------------------------------------------
 * Tests for double-precision FP comparison operations
 * Format: c.cond.d fs, ft
 *-----------------------------------------------------------------------*/

#define TEST_FP_CMP_D(testnum, inst, expected, val1_hi, val1_lo, val2_hi, val2_lo) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX_D($f0, $t1, $t2, val1_hi, val1_lo); \
    LOAD_FP_HEX_D($f2, $t3, $t4, val2_hi, val2_lo); \
    inst $f0, $f2; \
    bc1t 1f; \
    nop; \
    li $t0, 0; \
    j 2f; \
    nop; \
1:  li $t0, 1; \
2:  li $t9, expected; \
    bne $t0, $t9, fail; \
    nop;

#endif /* __MIPS32_TEST_MACROS_H */
