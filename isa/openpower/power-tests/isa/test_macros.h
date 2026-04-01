/* OpenPOWER Test Macros for ISA testing */
/* Based on riscv-tests macro structure */

#ifndef __POWER_TEST_MACROS_H
#define __POWER_TEST_MACROS_H

/*-----------------------------------------------------------------------
 * Helper macros
 *-----------------------------------------------------------------------*/

/* Test number register - %r2 */
#define TESTNUM %r2

/* Insert NOPs for bypass testing */
#define TEST_INSERT_NOPS_0
#define TEST_INSERT_NOPS_1  nop; TEST_INSERT_NOPS_0
#define TEST_INSERT_NOPS_2  nop; TEST_INSERT_NOPS_1
#define TEST_INSERT_NOPS_3  nop; TEST_INSERT_NOPS_2
#define TEST_INSERT_NOPS_4  nop; TEST_INSERT_NOPS_3
#define TEST_INSERT_NOPS_5  nop; TEST_INSERT_NOPS_4

/* Load immediate value (handles both 16-bit and 32-bit) */
#define LOAD_IMM(reg, val) \
    lis reg, ((val) >> 16) & 0xFFFF; \
    ori reg, reg, (val) & 0xFFFF

/* Load 64-bit immediate value */
#define LOAD_IMM64(reg, val) \
    lis reg, ((val) >> 48) & 0xFFFF; \
    ori reg, reg, ((val) >> 32) & 0xFFFF; \
    sldi reg, reg, 32; \
    oris reg, reg, ((val) >> 16) & 0xFFFF; \
    ori reg, reg, (val) & 0xFFFF

/* Load address of symbol */
#define LOAD_ADDR(reg, symbol) \
    lis reg, symbol@ha; \
    addi reg, reg, symbol@l

/* Core test case macro (32-bit) */
#define TEST_CASE(testnum, destreg, result, code...) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    code; \
    LOAD_IMM(%r25, result); \
    cmpw %cr0, destreg, %r25; \
    bne %cr0, fail;

/*-----------------------------------------------------------------------
 * Tests for instructions with register-register operands
 * Format: inst rD, rA, rB
 *-----------------------------------------------------------------------*/

#define TEST_RR_OP(testnum, inst, result, val1, val2) \
    TEST_CASE(testnum, %r8, result, \
        LOAD_IMM(%r9, val1); \
        LOAD_IMM(%r10, val2); \
        inst %r8, %r9, %r10; \
    )

#define TEST_RR_SRC1_EQ_DEST(testnum, inst, result, val1, val2) \
    TEST_CASE(testnum, %r9, result, \
        LOAD_IMM(%r9, val1); \
        LOAD_IMM(%r10, val2); \
        inst %r9, %r9, %r10; \
    )

#define TEST_RR_SRC2_EQ_DEST(testnum, inst, result, val1, val2) \
    TEST_CASE(testnum, %r10, result, \
        LOAD_IMM(%r9, val1); \
        LOAD_IMM(%r10, val2); \
        inst %r10, %r9, %r10; \
    )

#define TEST_RR_SRC12_EQ_DEST(testnum, inst, result, val1) \
    TEST_CASE(testnum, %r9, result, \
        LOAD_IMM(%r9, val1); \
        inst %r9, %r9, %r9; \
    )

#define TEST_RR_DEST_BYPASS(testnum, nop_cycles, inst, result, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li %r12, 0; \
1:  LOAD_IMM(%r9, val1); \
    LOAD_IMM(%r10, val2); \
    inst %r8, %r9, %r10; \
    TEST_INSERT_NOPS_ ## nop_cycles \
    addi %r11, %r8, 0; \
    addi %r12, %r12, 1; \
    li %r13, 2; \
    cmpw %cr0, %r12, %r13; \
    bne %cr0, 1b; \
    LOAD_IMM(%r25, result); \
    cmpw %cr0, %r11, %r25; \
    bne %cr0, fail;

#define TEST_RR_SRC12_BYPASS(testnum, src1_nops, src2_nops, inst, result, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li %r12, 0; \
1:  LOAD_IMM(%r9, val1); \
    TEST_INSERT_NOPS_ ## src1_nops \
    LOAD_IMM(%r10, val2); \
    TEST_INSERT_NOPS_ ## src2_nops \
    inst %r8, %r9, %r10; \
    addi %r12, %r12, 1; \
    li %r13, 2; \
    cmpw %cr0, %r12, %r13; \
    bne %cr0, 1b; \
    LOAD_IMM(%r25, result); \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

#define TEST_RR_SRC21_BYPASS(testnum, src1_nops, src2_nops, inst, result, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li %r12, 0; \
1:  LOAD_IMM(%r10, val2); \
    TEST_INSERT_NOPS_ ## src1_nops \
    LOAD_IMM(%r9, val1); \
    TEST_INSERT_NOPS_ ## src2_nops \
    inst %r8, %r9, %r10; \
    addi %r12, %r12, 1; \
    li %r13, 2; \
    cmpw %cr0, %r12, %r13; \
    bne %cr0, 1b; \
    LOAD_IMM(%r25, result); \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

/* Note: %r0 in PowerPC is NOT always zero like MIPS $zero */
#define TEST_RR_ZEROSRC1(testnum, inst, result, val) \
    TEST_CASE(testnum, %r8, result, \
        li %r9, 0; \
        LOAD_IMM(%r10, val); \
        inst %r8, %r9, %r10; \
    )

#define TEST_RR_ZEROSRC2(testnum, inst, result, val) \
    TEST_CASE(testnum, %r8, result, \
        LOAD_IMM(%r9, val); \
        li %r10, 0; \
        inst %r8, %r9, %r10; \
    )

#define TEST_RR_ZEROSRC12(testnum, inst, result) \
    TEST_CASE(testnum, %r8, result, \
        li %r9, 0; \
        li %r10, 0; \
        inst %r8, %r9, %r10; \
    )

/*-----------------------------------------------------------------------
 * Tests for instructions with immediate operands
 * Format: inst rD, rA, SIMM (D-form)
 *-----------------------------------------------------------------------*/

#define TEST_IMM_OP(testnum, inst, result, val1, imm) \
    TEST_CASE(testnum, %r8, result, \
        LOAD_IMM(%r9, val1); \
        inst %r8, %r9, imm; \
    )

#define TEST_IMM_SRC1_EQ_DEST(testnum, inst, result, val1, imm) \
    TEST_CASE(testnum, %r9, result, \
        LOAD_IMM(%r9, val1); \
        inst %r9, %r9, imm; \
    )

#define TEST_IMM_DEST_BYPASS(testnum, nop_cycles, inst, result, val1, imm) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li %r12, 0; \
1:  LOAD_IMM(%r9, val1); \
    inst %r8, %r9, imm; \
    TEST_INSERT_NOPS_ ## nop_cycles \
    addi %r11, %r8, 0; \
    addi %r12, %r12, 1; \
    li %r13, 2; \
    cmpw %cr0, %r12, %r13; \
    bne %cr0, 1b; \
    LOAD_IMM(%r25, result); \
    cmpw %cr0, %r11, %r25; \
    bne %cr0, fail;

#define TEST_IMM_SRC1_BYPASS(testnum, nop_cycles, inst, result, val1, imm) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li %r12, 0; \
1:  LOAD_IMM(%r9, val1); \
    TEST_INSERT_NOPS_ ## nop_cycles \
    inst %r8, %r9, imm; \
    addi %r12, %r12, 1; \
    li %r13, 2; \
    cmpw %cr0, %r12, %r13; \
    bne %cr0, 1b; \
    LOAD_IMM(%r25, result); \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

#define TEST_IMM_ZEROSRC1(testnum, inst, result, imm) \
    TEST_CASE(testnum, %r8, result, \
        li %r9, 0; \
        inst %r8, %r9, imm; \
    )

/*-----------------------------------------------------------------------
 * Tests for logical immediate instructions
 * Format: inst rA, rS, UIMM (D-form, rA = rS op UIMM)
 *-----------------------------------------------------------------------*/

#define TEST_LOGIMM_OP(testnum, inst, result, val1, imm) \
    TEST_CASE(testnum, %r8, result, \
        LOAD_IMM(%r9, val1); \
        inst %r8, %r9, imm; \
    )

/*-----------------------------------------------------------------------
 * Tests for shift instructions
 * Format: inst rA, rS, SH
 *-----------------------------------------------------------------------*/

#define TEST_SHIFT_OP(testnum, inst, result, val1, shamt) \
    TEST_CASE(testnum, %r8, result, \
        LOAD_IMM(%r9, val1); \
        inst %r8, %r9, shamt; \
    )

#define TEST_SHIFT_REG_OP(testnum, inst, result, val1, val2) \
    TEST_CASE(testnum, %r8, result, \
        LOAD_IMM(%r9, val1); \
        LOAD_IMM(%r10, val2); \
        inst %r8, %r9, %r10; \
    )

#define TEST_SHIFT_SRC1_EQ_DEST(testnum, inst, result, val1, shamt) \
    TEST_CASE(testnum, %r9, result, \
        LOAD_IMM(%r9, val1); \
        inst %r9, %r9, shamt; \
    )

/*-----------------------------------------------------------------------
 * Tests for load instructions
 * Format: inst rD, D(rA)
 *-----------------------------------------------------------------------*/

#define TEST_LD_OP(testnum, inst, result, offset, base) \
    TEST_CASE(testnum, %r8, result, \
        lis %r9, base@ha; \
        addi %r9, %r9, base@l; \
        inst %r8, offset(%r9); \
    )

/*-----------------------------------------------------------------------
 * Tests for store instructions
 * Format: inst rS, D(rA)
 *-----------------------------------------------------------------------*/

#define TEST_ST_OP(testnum, load_inst, store_inst, result, offset, base) \
    TEST_CASE(testnum, %r8, result, \
        lis %r9, base@ha; \
        addi %r9, %r9, base@l; \
        LOAD_IMM(%r10, result); \
        store_inst %r10, offset(%r9); \
        load_inst %r8, offset(%r9); \
    )

/*-----------------------------------------------------------------------
 * Test framework macros
 *-----------------------------------------------------------------------*/

#define RVTEST_CODE_BEGIN \
    .section .text; \
    .globl _start; \
_start: \
    /* Stack at end of 128KB memory (16384 * 8 = 0x20000) */ \
    lis %r1, 0x0002; \
    ori %r1, %r1, 0x0000; \
    li %r2, 0;

#define RVTEST_CODE_END

#define TEST_PASSFAIL \
    b pass;

#define RVTEST_PASS \
    .globl pass; \
pass: \
    b pass

#define RVTEST_FAIL \
    .globl fail; \
fail: \
    b fail

#define RVTEST_DATA_BEGIN \
    .section .data; \
    .balign 8;

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

/* Helper: Load single-precision FP value by hex pattern into FPR */
/* Note: On little-endian, lower 32 bits are at the lower address */
#define LOAD_FP_HEX(fpreg, gpreg, temp_gpr, hexval) \
    LOAD_IMM(gpreg, hexval); \
    std gpreg, -8(%r1); \
    lfs fpreg, -8(%r1);

/* Helper: Store FP result to integer register for comparison */
/* Note: Use -16(%r1) for 8-byte alignment (stfs/lwz need aligned access) */
#define STORE_FP_TO_INT(fpreg, gpreg) \
    stfs fpreg, -16(%r1); \
    lwz gpreg, -16(%r1);

/*-----------------------------------------------------------------------
 * Tests for FP register-register operations (2 operands)
 * Format: fadds frt, fra, frb
 *-----------------------------------------------------------------------*/

#define TEST_FP_OP2_S(testnum, inst, result_hex, val1_hex, val2_hex) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX(%f0, %r9, %r10, val1_hex); \
    LOAD_FP_HEX(%f1, %r9, %r10, val2_hex); \
    inst %f2, %f0, %f1; \
    STORE_FP_TO_INT(%f2, %r8); \
    LOAD_IMM(%r25, result_hex); \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

/*-----------------------------------------------------------------------
 * Tests for FP unary operations (1 operand)
 * Format: fsqrts frt, frb
 *-----------------------------------------------------------------------*/

#define TEST_FP_OP1_S(testnum, inst, result_hex, val1_hex) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX(%f0, %r9, %r10, val1_hex); \
    inst %f2, %f0; \
    STORE_FP_TO_INT(%f2, %r8); \
    LOAD_IMM(%r25, result_hex); \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

/*-----------------------------------------------------------------------
 * Tests for FP comparison operations
 * Format: fcmpu bf, fra, frb
 * Result sets CR field, we check the less-than bit
 *-----------------------------------------------------------------------*/

#define TEST_FP_CMP_LT_S(testnum, expected, val1_hex, val2_hex) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX(%f0, %r9, %r10, val1_hex); \
    LOAD_FP_HEX(%f1, %r9, %r10, val2_hex); \
    fcmpu %cr0, %f0, %f1; \
    mfcr %r8; \
    rlwinm %r8, %r8, 1, 31, 31; \
    li %r25, expected; \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

#define TEST_FP_CMP_EQ_S(testnum, expected, val1_hex, val2_hex) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX(%f0, %r9, %r10, val1_hex); \
    LOAD_FP_HEX(%f1, %r9, %r10, val2_hex); \
    fcmpu %cr0, %f0, %f1; \
    mfcr %r8; \
    rlwinm %r8, %r8, 3, 31, 31; \
    li %r25, expected; \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

/*-----------------------------------------------------------------------
 * Tests for FP-to-Integer conversion
 * Format: fctiwz frt, frb
 *-----------------------------------------------------------------------*/

#define TEST_FP_CVT_W_S(testnum, result, val1_hex) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX(%f0, %r9, %r10, val1_hex); \
    fctiwz %f2, %f0; \
    stfd %f2, -8(%r1); \
    lwz %r8, -8(%r1); \
    LOAD_IMM(%r25, result); \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

/*-----------------------------------------------------------------------
 * Tests for Integer-to-FP conversion
 * Format: fcfids frt, frb
 *-----------------------------------------------------------------------*/

#define TEST_INT_FP_CVT_S_W(testnum, result_hex, val1) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_IMM(%r9, val1); \
    std %r9, -8(%r1); \
    lfd %f0, -8(%r1); \
    fcfids %f2, %f0; \
    STORE_FP_TO_INT(%f2, %r8); \
    LOAD_IMM(%r25, result_hex); \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

/*-----------------------------------------------------------------------
 * Tests for FP load/store
 *-----------------------------------------------------------------------*/

#define TEST_FP_LD_OP(testnum, result_hex, offset, base) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    lis %r9, base@ha; \
    addi %r9, %r9, base@l; \
    lfs %f0, offset(%r9); \
    STORE_FP_TO_INT(%f0, %r8); \
    LOAD_IMM(%r25, result_hex); \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

#define TEST_FP_ST_OP(testnum, val_hex, offset, base) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX(%f0, %r9, %r10, val_hex); \
    lis %r10, base@ha; \
    addi %r10, %r10, base@l; \
    stfs %f0, offset(%r10); \
    lfs %f1, offset(%r10); \
    STORE_FP_TO_INT(%f1, %r8); \
    LOAD_IMM(%r25, val_hex); \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

/*-----------------------------------------------------------------------
 * Tests for FP move operations
 *-----------------------------------------------------------------------*/

#define TEST_FP_MR(testnum, result_hex, val_hex) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX(%f0, %r9, %r10, val_hex); \
    fmr %f2, %f0; \
    STORE_FP_TO_INT(%f2, %r8); \
    LOAD_IMM(%r25, result_hex); \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

/*-----------------------------------------------------------------------
 * Tests for FP fused multiply-add (3 operands)
 * Format: fmadds frt, fra, frc, frb  (frt = fra*frc + frb)
 *-----------------------------------------------------------------------*/

#define TEST_FP_OP3_S(testnum, inst, result_hex, val1_hex, val2_hex, val3_hex) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX(%f0, %r9, %r10, val1_hex); \
    LOAD_FP_HEX(%f1, %r9, %r10, val2_hex); \
    LOAD_FP_HEX(%f2, %r9, %r10, val3_hex); \
    inst %f3, %f0, %f1, %f2; \
    STORE_FP_TO_INT(%f3, %r8); \
    LOAD_IMM(%r25, result_hex); \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

/*-----------------------------------------------------------------------
 * IEEE 754 Double-Precision Floating-Point Test Macros
 *-----------------------------------------------------------------------*/

/* FP Constants for double-precision (IEEE 754) */
/* 1.0 = 0x3ff0000000000000 */
/* 2.0 = 0x4000000000000000 */
/* 3.0 = 0x4008000000000000 */
/* 4.0 = 0x4010000000000000 */

/* Helper: Load double-precision FP value by hex pattern into FPR */
#define LOAD_FP_HEX_D(fpreg, gpreg, hexval_hi, hexval_lo) \
    lis gpreg, ((hexval_hi) >> 16) & 0xFFFF; \
    ori gpreg, gpreg, (hexval_hi) & 0xFFFF; \
    sldi gpreg, gpreg, 32; \
    oris gpreg, gpreg, ((hexval_lo) >> 16) & 0xFFFF; \
    ori gpreg, gpreg, (hexval_lo) & 0xFFFF; \
    std gpreg, -8(%r1); \
    lfd fpreg, -8(%r1);

/* Helper: Store DP result to integer register for comparison */
#define STORE_FP_TO_INT_D(fpreg, gpreg) \
    stfd fpreg, -8(%r1); \
    ld gpreg, -8(%r1);

/* Helper: Load 64-bit expected value from hi/lo parts into register */
#define LOAD_EXPECTED_D(reg, hi, lo) \
    lis reg, ((hi) >> 16) & 0xFFFF; \
    ori reg, reg, (hi) & 0xFFFF; \
    sldi reg, reg, 32; \
    oris reg, reg, ((lo) >> 16) & 0xFFFF; \
    ori reg, reg, (lo) & 0xFFFF;

/*-----------------------------------------------------------------------
 * Tests for DP FP register-register operations (2 operands)
 * Format: fadd frt, fra, frb
 * val_hi = upper 32 bits, val_lo = lower 32 bits of IEEE 754 double
 *-----------------------------------------------------------------------*/

#define TEST_FP_OP2_D(testnum, inst, res_hi, res_lo, v1_hi, v1_lo, v2_hi, v2_lo) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX_D(%f0, %r9, v1_hi, v1_lo); \
    LOAD_FP_HEX_D(%f1, %r9, v2_hi, v2_lo); \
    inst %f2, %f0, %f1; \
    STORE_FP_TO_INT_D(%f2, %r8); \
    LOAD_EXPECTED_D(%r25, res_hi, res_lo); \
    cmpd %cr0, %r8, %r25; \
    bne %cr0, fail;

/*-----------------------------------------------------------------------
 * Tests for DP FP unary operations (1 operand)
 * Format: fsqrt frt, frb
 *-----------------------------------------------------------------------*/

#define TEST_FP_OP1_D(testnum, inst, res_hi, res_lo, v1_hi, v1_lo) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX_D(%f0, %r9, v1_hi, v1_lo); \
    inst %f2, %f0; \
    STORE_FP_TO_INT_D(%f2, %r8); \
    LOAD_EXPECTED_D(%r25, res_hi, res_lo); \
    cmpd %cr0, %r8, %r25; \
    bne %cr0, fail;

/*-----------------------------------------------------------------------
 * Tests for DP FP fused multiply-add (3 operands)
 * Format: fmadd frt, fra, frc, frb  (frt = fra*frc + frb)
 *-----------------------------------------------------------------------*/

#define TEST_FP_OP3_D(testnum, inst, res_hi, res_lo, v1_hi, v1_lo, v2_hi, v2_lo, v3_hi, v3_lo) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX_D(%f0, %r9, v1_hi, v1_lo); \
    LOAD_FP_HEX_D(%f1, %r9, v2_hi, v2_lo); \
    LOAD_FP_HEX_D(%f2, %r9, v3_hi, v3_lo); \
    inst %f3, %f0, %f1, %f2; \
    STORE_FP_TO_INT_D(%f3, %r8); \
    LOAD_EXPECTED_D(%r25, res_hi, res_lo); \
    cmpd %cr0, %r8, %r25; \
    bne %cr0, fail;

/*-----------------------------------------------------------------------
 * Tests for DP FP load/store
 *-----------------------------------------------------------------------*/

#define TEST_FP_LD_OP_D(testnum, res_hi, res_lo, offset, base) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    lis %r9, base@ha; \
    addi %r9, %r9, base@l; \
    lfd %f0, offset(%r9); \
    STORE_FP_TO_INT_D(%f0, %r8); \
    LOAD_EXPECTED_D(%r25, res_hi, res_lo); \
    cmpd %cr0, %r8, %r25; \
    bne %cr0, fail;

#define TEST_FP_ST_OP_D(testnum, val_hi, val_lo, offset, base) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX_D(%f0, %r9, val_hi, val_lo); \
    lis %r10, base@ha; \
    addi %r10, %r10, base@l; \
    stfd %f0, offset(%r10); \
    lfd %f1, offset(%r10); \
    STORE_FP_TO_INT_D(%f1, %r8); \
    LOAD_EXPECTED_D(%r25, val_hi, val_lo); \
    cmpd %cr0, %r8, %r25; \
    bne %cr0, fail;

/*-----------------------------------------------------------------------
 * Tests for 64-bit register-register operations
 * Uses cmpd for 64-bit comparison
 *-----------------------------------------------------------------------*/

#define TEST_CASE64(testnum, destreg, result_hi, result_lo, code...) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    code; \
    LOAD_EXPECTED_D(%r25, result_hi, result_lo); \
    cmpd %cr0, destreg, %r25; \
    bne %cr0, fail;

#define TEST_RR_OP64(testnum, inst, res_hi, res_lo, val1_hi, val1_lo, val2_hi, val2_lo) \
    TEST_CASE64(testnum, %r8, res_hi, res_lo, \
        LOAD_EXPECTED_D(%r9, val1_hi, val1_lo); \
        LOAD_EXPECTED_D(%r10, val2_hi, val2_lo); \
        inst %r8, %r9, %r10; \
    )

/*-----------------------------------------------------------------------
 * Tests for indexed load instructions (X-form)
 * Format: inst rD, rA, rB
 * For symbol addresses, use TEST_LDX_SYM_OP
 *-----------------------------------------------------------------------*/

#define TEST_LDX_OP(testnum, inst, result, base_reg_val, index_val) \
    TEST_CASE(testnum, %r8, result, \
        LOAD_IMM(%r9, base_reg_val); \
        LOAD_IMM(%r10, index_val); \
        inst %r8, %r9, %r10; \
    )

#define TEST_LDX_OP64(testnum, inst, res_hi, res_lo, base_val, index_val) \
    TEST_CASE64(testnum, %r8, res_hi, res_lo, \
        LOAD_IMM(%r9, base_val); \
        LOAD_IMM(%r10, index_val); \
        inst %r8, %r9, %r10; \
    )

/* Indexed load with symbol base address */
#define TEST_LDX_SYM_OP(testnum, inst, result, base_sym, index_val) \
    TEST_CASE(testnum, %r8, result, \
        lis %r9, base_sym@ha; \
        addi %r9, %r9, base_sym@l; \
        li %r10, index_val; \
        inst %r8, %r9, %r10; \
    )

#define TEST_LDX_SYM_OP64(testnum, inst, res_hi, res_lo, base_sym, index_val) \
    TEST_CASE64(testnum, %r8, res_hi, res_lo, \
        lis %r9, base_sym@ha; \
        addi %r9, %r9, base_sym@l; \
        li %r10, index_val; \
        inst %r8, %r9, %r10; \
    )

/*-----------------------------------------------------------------------
 * Tests for rotate/mask instructions
 * Format: rldicl rA, rS, SH, MB  (rotate left, mask begins at MB)
 * Format: rldicr rA, rS, SH, ME  (rotate left, mask ends at ME)
 * Format: rlwinm rA, rS, SH, MB, ME
 *-----------------------------------------------------------------------*/

#define TEST_ROTATE_OP(testnum, inst, result, val1, sh, mb, me) \
    TEST_CASE(testnum, %r8, result, \
        LOAD_IMM(%r9, val1); \
        inst %r8, %r9, sh, mb, me; \
    )

#define TEST_ROTATE_OP64(testnum, inst, res_hi, res_lo, val_hi, val_lo, sh, mb) \
    TEST_CASE64(testnum, %r8, res_hi, res_lo, \
        LOAD_EXPECTED_D(%r9, val_hi, val_lo); \
        inst %r8, %r9, sh, mb; \
    )

/*-----------------------------------------------------------------------
 * Tests for cmpb (Compare Bytes)
 * Format: cmpb rA, rS, rB
 * Each byte of rA is 0xFF if corresponding bytes of rS and rB are equal
 *-----------------------------------------------------------------------*/

#define TEST_CMPB_OP(testnum, result, val1, val2) \
    TEST_CASE(testnum, %r8, result, \
        LOAD_IMM(%r9, val1); \
        LOAD_IMM(%r10, val2); \
        cmpb %r8, %r9, %r10; \
    )

#define TEST_CMPB_OP64(testnum, res_hi, res_lo, v1_hi, v1_lo, v2_hi, v2_lo) \
    TEST_CASE64(testnum, %r8, res_hi, res_lo, \
        LOAD_EXPECTED_D(%r9, v1_hi, v1_lo); \
        LOAD_EXPECTED_D(%r10, v2_hi, v2_lo); \
        cmpb %r8, %r9, %r10; \
    )

/*-----------------------------------------------------------------------
 * Tests for setb (Set Boolean)
 * Format: setb rD, BFA
 * Sets rD to -1 if CR bit LT is set, +1 if GT is set, 0 if EQ
 *-----------------------------------------------------------------------*/

#define TEST_SETB_LT(testnum, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_IMM(%r9, val1); \
    LOAD_IMM(%r10, val2); \
    cmpw %cr0, %r9, %r10; \
    setb %r8, 0; \
    li %r25, -1; \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

#define TEST_SETB_GT(testnum, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_IMM(%r9, val1); \
    LOAD_IMM(%r10, val2); \
    cmpw %cr0, %r9, %r10; \
    setb %r8, 0; \
    li %r25, 1; \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

#define TEST_SETB_EQ(testnum, val1, val2) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_IMM(%r9, val1); \
    LOAD_IMM(%r10, val2); \
    cmpw %cr0, %r9, %r10; \
    setb %r8, 0; \
    li %r25, 0; \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

/*-----------------------------------------------------------------------
 * Tests for extswsli (Extend Sign Word and Shift Left Immediate)
 * Format: extswsli rA, rS, SH
 *-----------------------------------------------------------------------*/

#define TEST_EXTSWSLI_OP64(testnum, res_hi, res_lo, val, sh) \
    TEST_CASE64(testnum, %r8, res_hi, res_lo, \
        LOAD_IMM(%r9, val); \
        extswsli %r8, %r9, sh; \
    )

/*-----------------------------------------------------------------------
 * Tests for FP sign manipulation
 * Format: fabs/fneg/fnabs frt, frb
 *-----------------------------------------------------------------------*/

#define TEST_FP_SIGN_S(testnum, inst, result_hex, val_hex) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX(%f0, %r9, %r10, val_hex); \
    inst %f2, %f0; \
    STORE_FP_TO_INT(%f2, %r8); \
    LOAD_IMM(%r25, result_hex); \
    cmpw %cr0, %r8, %r25; \
    bne %cr0, fail;

#define TEST_FP_SIGN_D(testnum, inst, res_hi, res_lo, val_hi, val_lo) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX_D(%f0, %r9, val_hi, val_lo); \
    inst %f2, %f0; \
    STORE_FP_TO_INT_D(%f2, %r8); \
    LOAD_EXPECTED_D(%r25, res_hi, res_lo); \
    cmpd %cr0, %r8, %r25; \
    bne %cr0, fail;

/*-----------------------------------------------------------------------
 * Tests for FP select (fsel)
 * Format: fsel frt, fra, frc, frb
 * If fra >= 0, frt = frc, else frt = frb
 *-----------------------------------------------------------------------*/

#define TEST_FSEL_D(testnum, res_hi, res_lo, va_hi, va_lo, vc_hi, vc_lo, vb_hi, vb_lo) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX_D(%f0, %r9, va_hi, va_lo); \
    LOAD_FP_HEX_D(%f1, %r9, vc_hi, vc_lo); \
    LOAD_FP_HEX_D(%f2, %r9, vb_hi, vb_lo); \
    fsel %f3, %f0, %f1, %f2; \
    STORE_FP_TO_INT_D(%f3, %r8); \
    LOAD_EXPECTED_D(%r25, res_hi, res_lo); \
    cmpd %cr0, %r8, %r25; \
    bne %cr0, fail;

/*-----------------------------------------------------------------------
 * Tests for FP comparison with CR field check
 *-----------------------------------------------------------------------*/

#define TEST_FP_CMP_D(testnum, inst, expected_lt, expected_gt, expected_eq, v1_hi, v1_lo, v2_hi, v2_lo) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX_D(%f0, %r9, v1_hi, v1_lo); \
    LOAD_FP_HEX_D(%f1, %r9, v2_hi, v2_lo); \
    inst %cr0, %f0, %f1; \
    mfcr %r8; \
    rlwinm %r11, %r8, 1, 31, 31; \
    li %r25, expected_lt; \
    cmpw %cr1, %r11, %r25; \
    bne %cr1, fail; \
    rlwinm %r11, %r8, 2, 31, 31; \
    li %r25, expected_gt; \
    cmpw %cr1, %r11, %r25; \
    bne %cr1, fail; \
    rlwinm %r11, %r8, 3, 31, 31; \
    li %r25, expected_eq; \
    cmpw %cr1, %r11, %r25; \
    bne %cr1, fail;

/*-----------------------------------------------------------------------
 * Tests for FP rounding to integer
 * Format: frin/friz/frip/frim frt, frb
 *-----------------------------------------------------------------------*/

#define TEST_FP_ROUND_D(testnum, inst, res_hi, res_lo, val_hi, val_lo) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    LOAD_FP_HEX_D(%f0, %r9, val_hi, val_lo); \
    inst %f2, %f0; \
    STORE_FP_TO_INT_D(%f2, %r8); \
    LOAD_EXPECTED_D(%r25, res_hi, res_lo); \
    cmpd %cr0, %r8, %r25; \
    bne %cr0, fail;

#endif /* __POWER_TEST_MACROS_H */
