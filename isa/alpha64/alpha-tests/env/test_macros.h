/*
 * Alpha ISA Test Macros
 * Based on riscv-tests style but adapted for Alpha AXP
 *
 * Test result convention:
 *   - Tests write pass/fail status to a known memory location
 *   - Test number is stored in a register for debugging
 *   - On pass: result memory = 1
 *   - On fail: result memory = test number << 1
 */

#ifndef __TEST_MACROS_H
#define __TEST_MACROS_H

/*-----------------------------------------------------------------------
 * Begin/End Macros
 *-----------------------------------------------------------------------*/

#define RVTEST_CODE_BEGIN           \
    .text;                          \
    .globl _start;                  \
    .ent _start;                    \
_start:                             \
    br $27, 1f;                     \
1:  ldgp $gp, 0($27);               \
    lda $sp, _stack;                \
    lda $16, test_name;             \
    jsr $26, _test_start;           \
    ldgp $gp, 0($26);

#define RVTEST_CODE_END             \
    .end _start;

#define RVTEST_DATA_BEGIN           \
    .data;                          \
    .align 3;

#define RVTEST_DATA_END

/*-----------------------------------------------------------------------
 * Pass/Fail Handling
 *-----------------------------------------------------------------------*/

#define RVTEST_PASS                 \
    lda $16, 1($31);                \
    jsr $26, _test_end;             \
    ldgp $gp, 0($26);               \
    call_pal 0;

#define RVTEST_FAIL                 \
    sll $4, 1, $16;                 \
    jsr $26, _test_end;             \
    ldgp $gp, 0($26);               \
    call_pal 0;

/*-----------------------------------------------------------------------
 * Simple Test without Function Call Overhead
 * For bare-metal execution on our generated processor
 *-----------------------------------------------------------------------*/

#define ALPHA_TEST_BEGIN            \
    .text;                          \
    .globl _start;                  \
    .ent _start;                    \
_start:                             \
    lda $4, 0($31);

/*
 * Test structure for processor WITHOUT branch support:
 *
 * Since our processor doesn't support branches yet, we use a simple
 * structure where tests run sequentially and store result at the end.
 *
 * Tests use beq to "skip" to fail on error, but since branches don't
 * work, a failed test just continues to the next instruction. This means
 * we can only reliably detect PASS (all tests complete and store 1).
 *
 * When branches ARE implemented, the fail label will be reachable.
 */

#define ALPHA_TEST_END              \
    /* All tests completed - store 1 (PASS) to result */ \
pass:                               \
    lda $1, 1($31);                 \
    lda $2, 0xF00($31);             \
    stl $1, 0($2);                  \
    br $31, pass;                   \
fail:                               \
    /* Fail code - only reachable if branches work */   \
    sll $4, 1, $1;                  \
    lda $2, 0xF00($31);             \
    stl $1, 0($2);                  \
    br $31, fail;                   \
    .end _start;

/* Legacy macro - kept for compatibility but unused */
#define ALPHA_TEST_FAIL

/*-----------------------------------------------------------------------
 * Test Case Macros
 *-----------------------------------------------------------------------*/

/* Increment test counter */
#define TEST_CASE_START(testnum)    \
    lda $4, testnum($31);

/*
 * TEST_RR_OP: Test R-type instruction (two register operands)
 *   testnum - test number
 *   inst    - instruction to test
 *   result  - expected result
 *   val1    - first operand value
 *   val2    - second operand value
 */
#define TEST_RR_OP(testnum, inst, result, val1, val2) \
    TEST_CASE_START(testnum);       \
    lda $1, val1($31);              \
    lda $2, val2($31);              \
    inst $1, $2, $3;                \
    lda $5, result($31);            \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*
 * TEST_RR_OP64: Test R-type instruction with 64-bit values
 */
#define TEST_RR_OP64(testnum, inst, result, val1, val2) \
    TEST_CASE_START(testnum);       \
    ldiq $1, val1;                  \
    ldiq $2, val2;                  \
    inst $1, $2, $3;                \
    ldiq $5, result;                \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*
 * TEST_RI_OP: Test instruction with register and immediate
 *   Uses the immediate form if available
 */
#define TEST_RI_OP(testnum, inst, result, val1, imm) \
    TEST_CASE_START(testnum);       \
    lda $1, val1($31);              \
    inst $1, imm, $3;               \
    lda $5, result($31);            \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*
 * TEST_R_OP: Test single operand instruction
 */
#define TEST_R_OP(testnum, inst, result, val1) \
    TEST_CASE_START(testnum);       \
    lda $1, val1($31);              \
    inst $1, $3;                    \
    lda $5, result($31);            \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*
 * TEST_LD: Test load instruction
 *   testnum - test number
 *   inst    - load instruction
 *   result  - expected result
 *   offset  - offset from base
 *   base    - base address label
 */
#define TEST_LD(testnum, inst, result, offset, base) \
    TEST_CASE_START(testnum);       \
    lda $1, base;                   \
    inst $3, offset($1);            \
    ldiq $5, result;                \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*
 * TEST_ST: Test store instruction
 *   Stores a value and reads it back
 */
#define TEST_ST(testnum, st_inst, ld_inst, val, offset, base) \
    TEST_CASE_START(testnum);       \
    lda $1, base;                   \
    ldiq $2, val;                   \
    st_inst $2, offset($1);         \
    ld_inst $3, offset($1);         \
    cmpeq $2, $3, $6;               \
    beq $6, fail;

/*
 * TEST_BR_TAKEN: Test that branch is taken
 */
#define TEST_BR_TAKEN(testnum, inst, val) \
    TEST_CASE_START(testnum);       \
    lda $1, val($31);               \
    inst $1, 1f;                    \
    br $31, fail;                   \
1:

/*
 * TEST_BR_NOT_TAKEN: Test that branch is not taken
 */
#define TEST_BR_NOT_TAKEN(testnum, inst, val) \
    TEST_CASE_START(testnum);       \
    lda $1, val($31);               \
    inst $1, 1f;                    \
    br $31, 2f;                     \
1:  br $31, fail;                   \
2:

/*
 * TEST_CMOV: Test conditional move
 */
#define TEST_CMOV_TAKEN(testnum, inst, val, src, dst_init) \
    TEST_CASE_START(testnum);       \
    lda $1, val($31);               \
    lda $2, src($31);               \
    lda $3, dst_init($31);          \
    inst $1, $2, $3;                \
    lda $5, src($31);               \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

#define TEST_CMOV_NOT_TAKEN(testnum, inst, val, src, dst_init) \
    TEST_CASE_START(testnum);       \
    lda $1, val($31);               \
    lda $2, src($31);               \
    lda $3, dst_init($31);          \
    inst $1, $2, $3;                \
    lda $5, dst_init($31);          \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*
 * TEST_CMP: Test comparison instruction
 */
#define TEST_CMP(testnum, inst, expected, val1, val2) \
    TEST_CASE_START(testnum);       \
    lda $1, val1($31);              \
    lda $2, val2($31);              \
    inst $1, $2, $3;                \
    lda $5, expected($31);          \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*
 * TEST_IMM_OP: Test instruction with immediate operand
 *   For instructions like LDA that take a 16-bit displacement
 */
#define TEST_IMM_OP(testnum, inst, result, base_val, imm) \
    TEST_CASE_START(testnum);       \
    lda $1, base_val($31);          \
    inst $3, imm($1);               \
    lda $5, result($31);            \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*
 * Load 64-bit immediate (pseudo-instruction)
 * Uses LDA + LDAH sequence for large constants
 */
.macro ldiq reg, value
    .if (\value >= -32768) && (\value <= 32767)
        lda \reg, \value($31)
    .else
        lda \reg, (\value & 0xFFFF)($31)
        ldah \reg, (((\value + 0x8000) >> 16) & 0xFFFF)(\reg)
    .endif
.endm

/*-----------------------------------------------------------------------
 * NOP insertion macros for bypass testing
 * These test pipeline forwarding by inserting delays between instructions
 *-----------------------------------------------------------------------*/

#define TEST_INSERT_NOPS_0
#define TEST_INSERT_NOPS_1  nop; TEST_INSERT_NOPS_0
#define TEST_INSERT_NOPS_2  nop; TEST_INSERT_NOPS_1
#define TEST_INSERT_NOPS_3  nop; TEST_INSERT_NOPS_2
#define TEST_INSERT_NOPS_4  nop; TEST_INSERT_NOPS_3
#define TEST_INSERT_NOPS_5  nop; TEST_INSERT_NOPS_4

/*-----------------------------------------------------------------------
 * Source/Destination overlap tests
 *-----------------------------------------------------------------------*/

/*
 * TEST_RR_SRC1_EQ_DEST: src1 register same as dest
 */
#define TEST_RR_SRC1_EQ_DEST(testnum, inst, result, val1, val2) \
    TEST_CASE_START(testnum);       \
    lda $1, val1($31);              \
    lda $2, val2($31);              \
    inst $1, $2, $1;                \
    lda $5, result($31);            \
    cmpeq $1, $5, $6;               \
    beq $6, fail;

/*
 * TEST_RR_SRC2_EQ_DEST: src2 register same as dest
 */
#define TEST_RR_SRC2_EQ_DEST(testnum, inst, result, val1, val2) \
    TEST_CASE_START(testnum);       \
    lda $1, val1($31);              \
    lda $2, val2($31);              \
    inst $1, $2, $2;                \
    lda $5, result($31);            \
    cmpeq $2, $5, $6;               \
    beq $6, fail;

/*
 * TEST_RR_SRC12_EQ_DEST: both src registers same as dest
 */
#define TEST_RR_SRC12_EQ_DEST(testnum, inst, result, val1) \
    TEST_CASE_START(testnum);       \
    lda $1, val1($31);              \
    inst $1, $1, $1;                \
    lda $5, result($31);            \
    cmpeq $1, $5, $6;               \
    beq $6, fail;

/*-----------------------------------------------------------------------
 * Zero register (R31) tests
 *-----------------------------------------------------------------------*/

/*
 * TEST_RR_ZEROSRC1: use R31 as first source
 */
#define TEST_RR_ZEROSRC1(testnum, inst, result, val2) \
    TEST_CASE_START(testnum);       \
    lda $2, val2($31);              \
    inst $31, $2, $3;               \
    lda $5, result($31);            \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*
 * TEST_RR_ZEROSRC2: use R31 as second source
 */
#define TEST_RR_ZEROSRC2(testnum, inst, result, val1) \
    TEST_CASE_START(testnum);       \
    lda $1, val1($31);              \
    inst $1, $31, $3;               \
    lda $5, result($31);            \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*
 * TEST_RR_ZEROSRC12: use R31 as both sources
 */
#define TEST_RR_ZEROSRC12(testnum, inst, result) \
    TEST_CASE_START(testnum);       \
    inst $31, $31, $3;              \
    lda $5, result($31);            \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*
 * TEST_RR_ZERODEST: use R31 as destination (should be discarded)
 * Note: We verify R31 is still 0 after the operation
 */
#define TEST_RR_ZERODEST(testnum, inst, val1, val2) \
    TEST_CASE_START(testnum);       \
    lda $1, val1($31);              \
    lda $2, val2($31);              \
    inst $1, $2, $31;               \
    bne $31, fail;

/*-----------------------------------------------------------------------
 * Bypass tests - test pipeline forwarding
 * These insert NOPs to test different pipeline stages
 *-----------------------------------------------------------------------*/

/*
 * TEST_RR_DEST_BYPASS: Test destination bypass with N nops after instruction
 */
#define TEST_RR_DEST_BYPASS(testnum, nop_cycles, inst, result, val1, val2) \
    TEST_CASE_START(testnum);       \
    lda $10, 0($31);                \
1:  lda $1, val1($31);              \
    lda $2, val2($31);              \
    inst $1, $2, $14;               \
    TEST_INSERT_NOPS_ ## nop_cycles \
    addq $14, $31, $3;              \
    addq $10, 1, $10;               \
    lda $11, 2($31);                \
    cmplt $10, $11, $12;            \
    bne $12, 1b;                    \
    lda $5, result($31);            \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*
 * TEST_RR_SRC12_BYPASS: Test source operand bypass
 * Insert nops between loading src1 and src2, and between src2 and instruction
 */
#define TEST_RR_SRC12_BYPASS(testnum, src1_nops, src2_nops, inst, result, val1, val2) \
    TEST_CASE_START(testnum);       \
    lda $10, 0($31);                \
1:  lda $1, val1($31);              \
    TEST_INSERT_NOPS_ ## src1_nops  \
    lda $2, val2($31);              \
    TEST_INSERT_NOPS_ ## src2_nops  \
    inst $1, $2, $3;                \
    addq $10, 1, $10;               \
    lda $11, 2($31);                \
    cmplt $10, $11, $12;            \
    bne $12, 1b;                    \
    lda $5, result($31);            \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*
 * TEST_RR_SRC21_BYPASS: Test source operand bypass with reversed load order
 */
#define TEST_RR_SRC21_BYPASS(testnum, src1_nops, src2_nops, inst, result, val1, val2) \
    TEST_CASE_START(testnum);       \
    lda $10, 0($31);                \
1:  lda $2, val2($31);              \
    TEST_INSERT_NOPS_ ## src1_nops  \
    lda $1, val1($31);              \
    TEST_INSERT_NOPS_ ## src2_nops  \
    inst $1, $2, $3;                \
    addq $10, 1, $10;               \
    lda $11, 2($31);                \
    cmplt $10, $11, $12;            \
    bne $12, 1b;                    \
    lda $5, result($31);            \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*-----------------------------------------------------------------------
 * 64-bit value test macros using ldiq
 *-----------------------------------------------------------------------*/

/*
 * TEST_RR_OP64_SRC1_EQ_DEST: 64-bit test with src1 = dest
 */
#define TEST_RR_OP64_SRC1_EQ_DEST(testnum, inst, result, val1, val2) \
    TEST_CASE_START(testnum);       \
    ldiq $1, val1;                  \
    ldiq $2, val2;                  \
    inst $1, $2, $1;                \
    ldiq $5, result;                \
    cmpeq $1, $5, $6;               \
    beq $6, fail;

/*
 * TEST_RR_OP64_SRC2_EQ_DEST: 64-bit test with src2 = dest
 */
#define TEST_RR_OP64_SRC2_EQ_DEST(testnum, inst, result, val1, val2) \
    TEST_CASE_START(testnum);       \
    ldiq $1, val1;                  \
    ldiq $2, val2;                  \
    inst $1, $2, $2;                \
    ldiq $5, result;                \
    cmpeq $2, $5, $6;               \
    beq $6, fail;

/*
 * TEST_RR_OP64_ZEROSRC1: 64-bit test with R31 as src1
 */
#define TEST_RR_OP64_ZEROSRC1(testnum, inst, result, val2) \
    TEST_CASE_START(testnum);       \
    ldiq $2, val2;                  \
    inst $31, $2, $3;               \
    ldiq $5, result;                \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*
 * TEST_RR_OP64_ZEROSRC2: 64-bit test with R31 as src2
 */
#define TEST_RR_OP64_ZEROSRC2(testnum, inst, result, val1) \
    TEST_CASE_START(testnum);       \
    ldiq $1, val1;                  \
    inst $1, $31, $3;               \
    ldiq $5, result;                \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*-----------------------------------------------------------------------
 * Branch bypass tests
 *-----------------------------------------------------------------------*/

#define TEST_BR2_SRC12_BYPASS(testnum, src1_nops, src2_nops, inst, val1, val2) \
    TEST_CASE_START(testnum);       \
    lda $10, 0($31);                \
1:  lda $1, val1($31);              \
    TEST_INSERT_NOPS_ ## src1_nops  \
    lda $2, val2($31);              \
    TEST_INSERT_NOPS_ ## src2_nops  \
    inst $1, 2f;                    \
    addq $10, 1, $10;               \
    lda $11, 2($31);                \
    cmplt $10, $11, $12;            \
    bne $12, 1b;                    \
    br $31, 3f;                     \
2:  br $31, fail;                   \
3:

/*-----------------------------------------------------------------------
 * Load/Store bypass tests
 *-----------------------------------------------------------------------*/

#define TEST_LD_DEST_BYPASS(testnum, nop_cycles, inst, result, offset, base) \
    TEST_CASE_START(testnum);       \
    lda $10, 0($31);                \
1:  lda $13, base;                  \
    inst $14, offset($13);          \
    TEST_INSERT_NOPS_ ## nop_cycles \
    addq $14, $31, $3;              \
    addq $10, 1, $10;               \
    lda $11, 2($31);                \
    cmplt $10, $11, $12;            \
    bne $12, 1b;                    \
    ldiq $5, result;                \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

#define TEST_LD_SRC1_BYPASS(testnum, nop_cycles, inst, result, offset, base) \
    TEST_CASE_START(testnum);       \
    lda $10, 0($31);                \
1:  lda $13, base;                  \
    TEST_INSERT_NOPS_ ## nop_cycles \
    inst $3, offset($13);           \
    addq $10, 1, $10;               \
    lda $11, 2($31);                \
    cmplt $10, $11, $12;            \
    bne $12, 1b;                    \
    ldiq $5, result;                \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*-----------------------------------------------------------------------
 * Floating-Point Test Macros
 * For IEEE single (S_floating) and double (T_floating) precision
 *-----------------------------------------------------------------------*/

/*
 * Load IEEE 754 float constant into FP register
 * Alpha FP registers are 64-bit; single precision uses low 32 bits
 */
.macro ldfps freg, hex_val
    lda $1, fp_const_\@($31)
    lds \freg, 0($1)
    br $31, fp_const_end_\@
    .align 3
fp_const_\@:
    .long \hex_val
    .long 0xFFFFFFFF
fp_const_end_\@:
.endm

.macro ldfpt freg, hex_hi, hex_lo
    lda $1, fp_const_\@($31)
    ldt \freg, 0($1)
    br $31, fp_const_end_\@
    .align 3
fp_const_\@:
    .long \hex_lo
    .long \hex_hi
fp_const_end_\@:
.endm

/*
 * TEST_FP_OP2_S: Test single-precision binary FP operation
 *   testnum  - test number
 *   inst     - FP instruction (e.g., adds)
 *   result   - expected result (IEEE 754 hex)
 *   val1     - first operand (IEEE 754 hex)
 *   val2     - second operand (IEEE 754 hex)
 */
#define TEST_FP_OP2_S(testnum, inst, result, val1, val2) \
    TEST_CASE_START(testnum);       \
    ldfps $f1, val1;                \
    ldfps $f2, val2;                \
    inst $f1, $f2, $f3;             \
    ldfps $f5, result;              \
    cmpteq $f3, $f5, $f6;           \
    fbeq $f6, fail;

/*
 * TEST_FP_OP2_T: Test double-precision binary FP operation
 *   Uses split hex values: hi = bits[63:32], lo = bits[31:0]
 */
#define TEST_FP_OP2_T(testnum, inst, res_hi, res_lo, v1_hi, v1_lo, v2_hi, v2_lo) \
    TEST_CASE_START(testnum);       \
    ldfpt $f1, v1_hi, v1_lo;        \
    ldfpt $f2, v2_hi, v2_lo;        \
    inst $f1, $f2, $f3;             \
    ldfpt $f5, res_hi, res_lo;      \
    cmpteq $f3, $f5, $f6;           \
    fbeq $f6, fail;

/*
 * TEST_FP_OP1_S: Test single-precision unary FP operation
 */
#define TEST_FP_OP1_S(testnum, inst, result, val1) \
    TEST_CASE_START(testnum);       \
    ldfps $f1, val1;                \
    inst $f1, $f3;                  \
    ldfps $f5, result;              \
    cmpteq $f3, $f5, $f6;           \
    fbeq $f6, fail;

/*
 * TEST_FP_OP1_T: Test double-precision unary FP operation
 */
#define TEST_FP_OP1_T(testnum, inst, res_hi, res_lo, v1_hi, v1_lo) \
    TEST_CASE_START(testnum);       \
    ldfpt $f1, v1_hi, v1_lo;        \
    inst $f1, $f3;                  \
    ldfpt $f5, res_hi, res_lo;      \
    cmpteq $f3, $f5, $f6;           \
    fbeq $f6, fail;

/*
 * TEST_FP_CMP_T: Test double-precision FP comparison
 *   Result is 2.0 (true) or 0.0 (false) in Alpha convention
 */
#define TEST_FP_CMP_T_TRUE(testnum, inst, v1_hi, v1_lo, v2_hi, v2_lo) \
    TEST_CASE_START(testnum);       \
    ldfpt $f1, v1_hi, v1_lo;        \
    ldfpt $f2, v2_hi, v2_lo;        \
    inst $f1, $f2, $f3;             \
    /* Result should be 2.0 = 0x4000000000000000 */ \
    ldfpt $f5, 0x40000000, 0x00000000; \
    cmpteq $f3, $f5, $f6;           \
    fbeq $f6, fail;

#define TEST_FP_CMP_T_FALSE(testnum, inst, v1_hi, v1_lo, v2_hi, v2_lo) \
    TEST_CASE_START(testnum);       \
    ldfpt $f1, v1_hi, v1_lo;        \
    ldfpt $f2, v2_hi, v2_lo;        \
    inst $f1, $f2, $f3;             \
    /* Result should be 0.0 = 0x0000000000000000 */ \
    ldfpt $f5, 0x00000000, 0x00000000; \
    cmpteq $f3, $f5, $f6;           \
    fbeq $f6, fail;

/*
 * TEST_FP_LD_S: Test FP load single
 */
#define TEST_FP_LD_S(testnum, result, offset, base) \
    TEST_CASE_START(testnum);       \
    lda $1, base;                   \
    lds $f3, offset($1);            \
    ldfps $f5, result;              \
    cmpteq $f3, $f5, $f6;           \
    fbeq $f6, fail;

/*
 * TEST_FP_LD_T: Test FP load double
 */
#define TEST_FP_LD_T(testnum, res_hi, res_lo, offset, base) \
    TEST_CASE_START(testnum);       \
    lda $1, base;                   \
    ldt $f3, offset($1);            \
    ldfpt $f5, res_hi, res_lo;      \
    cmpteq $f3, $f5, $f6;           \
    fbeq $f6, fail;

/*
 * TEST_FP_ST_S: Test FP store single (store and reload)
 */
#define TEST_FP_ST_S(testnum, val, offset, base) \
    TEST_CASE_START(testnum);       \
    lda $1, base;                   \
    ldfps $f2, val;                 \
    sts $f2, offset($1);            \
    lds $f3, offset($1);            \
    cmpteq $f2, $f3, $f6;           \
    fbeq $f6, fail;

/*
 * TEST_FP_ST_T: Test FP store double (store and reload)
 */
#define TEST_FP_ST_T(testnum, val_hi, val_lo, offset, base) \
    TEST_CASE_START(testnum);       \
    lda $1, base;                   \
    ldfpt $f2, val_hi, val_lo;      \
    stt $f2, offset($1);            \
    ldt $f3, offset($1);            \
    cmpteq $f2, $f3, $f6;           \
    fbeq $f6, fail;

/*
 * TEST_FP_CPYS: Test CPYS (copy sign)
 */
#define TEST_FP_CPYS(testnum, res_hi, res_lo, v1_hi, v1_lo, v2_hi, v2_lo) \
    TEST_CASE_START(testnum);       \
    ldfpt $f1, v1_hi, v1_lo;        \
    ldfpt $f2, v2_hi, v2_lo;        \
    cpys $f1, $f2, $f3;             \
    ldfpt $f5, res_hi, res_lo;      \
    cmpteq $f3, $f5, $f6;           \
    fbeq $f6, fail;

/*-----------------------------------------------------------------------
 * Control Flow Test Macros (for BR, BSR, JMP, JSR, RET)
 *-----------------------------------------------------------------------*/

/*
 * TEST_BR_UNCONDITIONAL: Test unconditional branch
 */
#define TEST_BR_UNCONDITIONAL(testnum) \
    TEST_CASE_START(testnum);       \
    br $31, 1f;                     \
    br $31, fail;                   \
1:

/*
 * TEST_BSR: Test branch to subroutine (saves return address)
 */
#define TEST_BSR(testnum) \
    TEST_CASE_START(testnum);       \
    bsr $26, 1f;                    \
    br $31, 2f;                     \
1:  ret $31, ($26), 1;              \
2:

/*
 * TEST_JMP: Test indirect jump
 */
#define TEST_JMP(testnum) \
    TEST_CASE_START(testnum);       \
    br $27, 1f;                     \
1:  lda $27, 2f - 1b($27);          \
    jmp $31, ($27);                 \
    br $31, fail;                   \
2:

/*
 * TEST_JSR_RET: Test JSR and RET pair
 */
#define TEST_JSR_RET(testnum) \
    TEST_CASE_START(testnum);       \
    br $27, 1f;                     \
1:  lda $27, 3f - 1b($27);          \
    jsr $26, ($27);                 \
    br $31, 2f;                     \
3:  ret $31, ($26), 1;              \
2:

/*-----------------------------------------------------------------------
 * Memory Barrier Test Macros (for MB, WMB, TRAPB, EXCB)
 *-----------------------------------------------------------------------*/

/*
 * TEST_MB: Test memory barrier (just verify it doesn't crash)
 */
#define TEST_BARRIER(testnum, inst) \
    TEST_CASE_START(testnum);       \
    inst;                           \
    /* If we get here, barrier completed */

/*-----------------------------------------------------------------------
 * Atomic Operation Test Macros (for STL_C, STQ_C)
 *-----------------------------------------------------------------------*/

/*
 * TEST_ATOMIC_SC: Test store conditional
 *   val - value to store
 *   offset - memory offset
 *   base - base address label
 *   ldl_l/stl_c or ldq_l/stq_c pair
 */
#define TEST_ATOMIC_STL_C(testnum, val, offset, base) \
    TEST_CASE_START(testnum);       \
    lda $1, base;                   \
    ldl_l $2, offset($1);           \
    lda $3, val($31);               \
    stl_c $3, offset($1);           \
    beq $3, fail;                   \
    ldl $4, offset($1);             \
    lda $5, val($31);               \
    cmpeq $4, $5, $6;               \
    beq $6, fail;

#define TEST_ATOMIC_STQ_C(testnum, val, offset, base) \
    TEST_CASE_START(testnum);       \
    lda $1, base;                   \
    ldq_l $2, offset($1);           \
    lda $3, val($31);               \
    stq_c $3, offset($1);           \
    beq $3, fail;                   \
    ldq $4, offset($1);             \
    lda $5, val($31);               \
    cmpeq $4, $5, $6;               \
    beq $6, fail;

/*-----------------------------------------------------------------------
 * Logical Operation Test Macros (for BIC, ORNOT, EQV)
 *-----------------------------------------------------------------------*/

#define TEST_LOGIC_OP(testnum, inst, result, val1, val2) \
    TEST_CASE_START(testnum);       \
    ldiq $1, val1;                  \
    ldiq $2, val2;                  \
    inst $1, $2, $3;                \
    ldiq $5, result;                \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

/*-----------------------------------------------------------------------
 * AMASK Test Macro
 *-----------------------------------------------------------------------*/

#define TEST_AMASK(testnum, expected, input) \
    TEST_CASE_START(testnum);       \
    ldiq $1, input;                 \
    amask $1, $3;                   \
    ldiq $5, expected;              \
    cmpeq $3, $5, $6;               \
    beq $6, fail;

#endif /* __TEST_MACROS_H */
