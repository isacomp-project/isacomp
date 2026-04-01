/* MicroVAX Test Macros for ISA testing */
/* Based on riscv-tests macro structure */
/* This is used with our custom MicroVAX assembler */

#ifndef __MICROVAX_TEST_MACROS_H
#define __MICROVAX_TEST_MACROS_H

/*-----------------------------------------------------------------------
 * MicroVAX Simplified Encoding:
 *   [31:24] = opcode
 *   [23:20] = operand 1 (register or field)
 *   [19:16] = operand 2 (register or field)
 *   [15:12] = operand 3 (register, for 3-operand instructions)
 *   [15:0]  = immediate/displacement (for some formats)
 *
 * Register convention:
 *   R0-R11: General purpose
 *   R12 (0xC): AP - Argument Pointer
 *   R13 (0xD): FP - Frame Pointer
 *   R14 (0xE): SP - Stack Pointer
 *   R15 (0xF): PC - Program Counter (not directly accessible)
 *-----------------------------------------------------------------------*/

/* Opcode definitions */
#define OP_NOP      0x01
#define OP_RSB      0x05
#define OP_BRB      0x11
#define OP_BNEQ     0x12
#define OP_BEQL     0x13
#define OP_BLSS     0x14
#define OP_BGEQ     0x15
#define OP_BGTR     0x16
#define OP_BLEQ     0x17
#define OP_BLSSU    0x18
#define OP_BGEQU    0x19
#define OP_JSB      0x20
#define OP_ASHL     0x78
#define OP_ASHLI    0x79
#define OP_SHRLI    0x7A
#define OP_SHRAI    0x7B
#define OP_ANDL2    0x88
#define OP_ANDL3    0x89
#define OP_CMPL     0x91
#define OP_TSTL     0x95
#define OP_ROTL     0x9C
#define OP_ADDL2    0xC0
#define OP_ADDL3    0xC1
#define OP_SUBL2    0xC2
#define OP_SUBL3    0xC3
#define OP_ADDLI    0xC4
#define OP_SUBLI    0xC5
#define OP_MULL2    0xC6
#define OP_MULL3    0xC7
#define OP_BISL2    0xC8
#define OP_BISL3    0xC9
#define OP_BICL2    0xCA
#define OP_BICL3    0xCB
#define OP_XORL2    0xCC
#define OP_XORL3    0xCD
#define OP_MNEGL    0xCE
#define OP_MCOML    0xCF
#define OP_MOVL     0xD0
#define OP_MOVLI    0xD1
#define OP_CLRL     0xD4
#define OP_INCL     0xD6
#define OP_DECL     0xD7
#define OP_LDL      0xE0
#define OP_STL      0xE8

/* Register aliases */
#define R0  0x0
#define R1  0x1
#define R2  0x2
#define R3  0x3
#define R4  0x4
#define R5  0x5
#define R6  0x6
#define R7  0x7
#define R8  0x8
#define R9  0x9
#define R10 0xA
#define R11 0xB
#define AP  0xC
#define FP  0xD
#define SP  0xE

/* Test number register - we use R10 */
#define TESTNUM R10

/*-----------------------------------------------------------------------
 * Instruction encoding helpers
 *-----------------------------------------------------------------------*/

/* 2-operand register instruction: ADDL2, SUBL2, etc. */
#define ENCODE_RR2(opcode, src, dst) \
    (((opcode) << 24) | ((src) << 20) | ((dst) << 16))

/* 3-operand register instruction: ADDL3, SUBL3, etc. */
#define ENCODE_RR3(opcode, src1, src2, dst) \
    (((opcode) << 24) | ((src1) << 20) | ((src2) << 16) | ((dst) << 12))

/* Single operand instruction: INCL, DECL, CLRL */
#define ENCODE_R1(opcode, dst) \
    (((opcode) << 24) | ((dst) << 20))

/* Immediate instruction (20-bit immediate): MOVLI, ADDLI, SUBLI */
#define ENCODE_RI(opcode, dst, imm) \
    (((opcode) << 24) | ((dst) << 20) | ((imm) & 0xFFFFF))

/* Shift immediate: ASHLI, SHRLI, SHRAI */
#define ENCODE_SHIFT(opcode, src, dst, shamt) \
    (((opcode) << 24) | ((src) << 20) | ((dst) << 16) | ((shamt) << 11))

/* Load/Store: LDL, STL */
#define ENCODE_MEM(opcode, reg1, reg2, offset) \
    (((opcode) << 24) | ((reg1) << 20) | ((reg2) << 16) | ((offset) & 0xFFFF))

/* Branch with displacement */
#define ENCODE_BR(opcode, disp) \
    (((opcode) << 24) | ((disp) & 0xFFFFFF))

/* Conditional branch: BEQL, BNEQ, etc. */
#define ENCODE_COND_BR(opcode, src1, src2, disp) \
    (((opcode) << 24) | ((src1) << 20) | ((src2) << 16) | ((disp) & 0xFFFF))

/*-----------------------------------------------------------------------
 * Test framework macros
 *-----------------------------------------------------------------------*/

/* Start of test code */
#define RVTEST_CODE_BEGIN \
    .text; \
    .align 2; \
    .globl _start; \
_start:

/* End of test code */
#define RVTEST_CODE_END

/* Pass/fail macros */
#define TEST_PASSFAIL \
    .word ENCODE_BR(OP_BRB, 0)  /* BRB to self = halt at pass */

#define RVTEST_PASS \
pass: \
    .word ENCODE_BR(OP_BRB, 0)  /* BRB to self = infinite loop at pass */

#define RVTEST_FAIL \
fail: \
    .word ENCODE_BR(OP_BRB, 0)  /* BRB to self = infinite loop at fail */

/* Data section macros */
#define RVTEST_DATA_BEGIN \
    .data; \
    .align 2;

#define RVTEST_DATA_END

#define TEST_DATA

/*-----------------------------------------------------------------------
 * Test macros for 2-operand register-register operations
 * TEST_RR_OP2: dst = dst OP src
 *-----------------------------------------------------------------------*/

#define TEST_RR_OP2(testnum, inst_op, result, dst_init, src_val) \
test_ ## testnum: \
    .word ENCODE_RI(OP_MOVLI, TESTNUM, testnum); \
    .word ENCODE_RI(OP_MOVLI, R0, dst_init); \
    .word ENCODE_RI(OP_MOVLI, R1, src_val); \
    .word ENCODE_RR2(inst_op, R1, R0); \
    .word ENCODE_RI(OP_MOVLI, R2, result); \
    .word ENCODE_COND_BR(OP_BNEQ, R0, R2, (fail - . - 4));

/*-----------------------------------------------------------------------
 * Test macros for 3-operand register-register operations
 * TEST_RR_OP3: dst = src1 OP src2
 *-----------------------------------------------------------------------*/

#define TEST_RR_OP3(testnum, inst_op, result, val1, val2) \
test_ ## testnum: \
    .word ENCODE_RI(OP_MOVLI, TESTNUM, testnum); \
    .word ENCODE_RI(OP_MOVLI, R0, val1); \
    .word ENCODE_RI(OP_MOVLI, R1, val2); \
    .word ENCODE_RR3(inst_op, R0, R1, R2); \
    .word ENCODE_RI(OP_MOVLI, R3, result); \
    .word ENCODE_COND_BR(OP_BNEQ, R2, R3, (fail - . - 4));

/*-----------------------------------------------------------------------
 * Test macros for immediate operations
 *-----------------------------------------------------------------------*/

#define TEST_IMM_OP(testnum, inst_op, result, init_val, imm_val) \
test_ ## testnum: \
    .word ENCODE_RI(OP_MOVLI, TESTNUM, testnum); \
    .word ENCODE_RI(OP_MOVLI, R0, init_val); \
    .word ENCODE_RI(inst_op, R0, imm_val); \
    .word ENCODE_RI(OP_MOVLI, R1, result); \
    .word ENCODE_COND_BR(OP_BNEQ, R0, R1, (fail - . - 4));

/*-----------------------------------------------------------------------
 * Test macros for single-operand operations (INCL, DECL, CLRL)
 *-----------------------------------------------------------------------*/

#define TEST_R1_OP(testnum, inst_op, result, init_val) \
test_ ## testnum: \
    .word ENCODE_RI(OP_MOVLI, TESTNUM, testnum); \
    .word ENCODE_RI(OP_MOVLI, R0, init_val); \
    .word ENCODE_R1(inst_op, R0); \
    .word ENCODE_RI(OP_MOVLI, R1, result); \
    .word ENCODE_COND_BR(OP_BNEQ, R0, R1, (fail - . - 4));

/*-----------------------------------------------------------------------
 * Test macros for shift operations
 *-----------------------------------------------------------------------*/

#define TEST_SHIFT_OP(testnum, inst_op, result, val, shamt) \
test_ ## testnum: \
    .word ENCODE_RI(OP_MOVLI, TESTNUM, testnum); \
    .word ENCODE_RI(OP_MOVLI, R0, val); \
    .word ENCODE_SHIFT(inst_op, R0, R1, shamt); \
    .word ENCODE_RI(OP_MOVLI, R2, result); \
    .word ENCODE_COND_BR(OP_BNEQ, R1, R2, (fail - . - 4));

/*-----------------------------------------------------------------------
 * Test macros for load/store operations
 *-----------------------------------------------------------------------*/

#define TEST_LD_OP(testnum, result, base_reg, offset) \
test_ ## testnum: \
    .word ENCODE_RI(OP_MOVLI, TESTNUM, testnum); \
    .word ENCODE_MEM(OP_LDL, base_reg, R0, offset); \
    .word ENCODE_RI(OP_MOVLI, R1, result); \
    .word ENCODE_COND_BR(OP_BNEQ, R0, R1, (fail - . - 4));

#define TEST_ST_OP(testnum, val, base_reg, offset) \
test_ ## testnum: \
    .word ENCODE_RI(OP_MOVLI, TESTNUM, testnum); \
    .word ENCODE_RI(OP_MOVLI, R0, val); \
    .word ENCODE_MEM(OP_STL, R0, base_reg, offset); \
    .word ENCODE_MEM(OP_LDL, base_reg, R1, offset); \
    .word ENCODE_COND_BR(OP_BNEQ, R0, R1, (fail - . - 4));

/*-----------------------------------------------------------------------
 * Test macros for branch operations
 *-----------------------------------------------------------------------*/

#define TEST_BR_TAKEN(testnum, inst_op, val1, val2) \
test_ ## testnum: \
    .word ENCODE_RI(OP_MOVLI, TESTNUM, testnum); \
    .word ENCODE_RI(OP_MOVLI, R0, val1); \
    .word ENCODE_RI(OP_MOVLI, R1, val2); \
    .word ENCODE_COND_BR(inst_op, R0, R1, 8); \
    .word ENCODE_BR(OP_BRB, (fail - . - 4)); \
    /* branch target here */

#define TEST_BR_NOT_TAKEN(testnum, inst_op, val1, val2) \
test_ ## testnum: \
    .word ENCODE_RI(OP_MOVLI, TESTNUM, testnum); \
    .word ENCODE_RI(OP_MOVLI, R0, val1); \
    .word ENCODE_RI(OP_MOVLI, R1, val2); \
    .word ENCODE_COND_BR(inst_op, R0, R1, (fail - . - 4));

#endif /* __MICROVAX_TEST_MACROS_H */
