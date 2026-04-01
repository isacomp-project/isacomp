/* SPARCv8 Test Macros for ISA testing */
/* Based on riscv-tests, mips-tests, and j2-tests macro structure */

#ifndef __SPARCV8_TEST_MACROS_H
#define __SPARCV8_TEST_MACROS_H

/*-----------------------------------------------------------------------
 * Register definitions
 * SPARCv8 has 32 registers visible at a time:
 *   %g0-%g7: globals (%g0 always 0)
 *   %o0-%o7: outs (caller saves, %o7 = return address for CALL)
 *   %l0-%l7: locals
 *   %i0-%i7: ins (%i6 = frame pointer, %i7 = return address)
 *-----------------------------------------------------------------------*/

#define TESTNUM %l0

/* Result and scratch registers */
#define TEST_RESULT %l1
#define TEST_SCRATCH1 %l2
#define TEST_SCRATCH2 %l3
#define TEST_SCRATCH3 %l4
#define TEST_EXPECTED %l5

/*-----------------------------------------------------------------------
 * Helper macros
 *-----------------------------------------------------------------------*/

/* Insert NOPs for bypass testing (also fills delay slots) */
#define TEST_INSERT_NOPS_0
#define TEST_INSERT_NOPS_1  nop; TEST_INSERT_NOPS_0
#define TEST_INSERT_NOPS_2  nop; TEST_INSERT_NOPS_1
#define TEST_INSERT_NOPS_3  nop; TEST_INSERT_NOPS_2
#define TEST_INSERT_NOPS_4  nop; TEST_INSERT_NOPS_3
#define TEST_INSERT_NOPS_5  nop; TEST_INSERT_NOPS_4

/* Load a 32-bit immediate into a register using sethi + or */
#define LOAD_IMM(reg, val) \
    sethi %hi(val), reg; \
    or reg, %lo(val), reg

/*-----------------------------------------------------------------------
 * Begin/End Test Macros
 *-----------------------------------------------------------------------*/

#define SPARCV8_TEST_CODE_BEGIN \
    .text; \
    .align 4; \
    .globl _start; \
_start:

#define SPARCV8_TEST_CODE_END

/*-----------------------------------------------------------------------
 * Pass/Fail Macros
 * Tests branch to 'pass' on success, 'fail' on failure
 * Simulator detects completion by PC reaching these addresses
 *-----------------------------------------------------------------------*/

#define TEST_PASSFAIL \
    ba pass; \
    nop;

#define SPARCV8_PASS \
    .globl pass; \
pass: \
    ba pass; \
    nop;

#define SPARCV8_FAIL \
    .globl fail; \
fail: \
    ba fail; \
    nop;

/*-----------------------------------------------------------------------
 * Data Section Macros
 *-----------------------------------------------------------------------*/

#define SPARCV8_DATA_BEGIN \
    .data; \
    .align 4;

#define SPARCV8_DATA_END

#define TEST_DATA

/*-----------------------------------------------------------------------
 * Core test case macro
 * Executes code, compares result register to expected value
 *-----------------------------------------------------------------------*/

#define TEST_CASE(testnum, testreg, correctval, code...) \
test_ ## testnum: \
    mov testnum, TESTNUM; \
    code; \
    LOAD_IMM(TEST_EXPECTED, correctval); \
    cmp testreg, TEST_EXPECTED; \
    be test_ ## testnum ## _pass; \
    nop; \
    ba fail; \
    nop; \
test_ ## testnum ## _pass:

/*-----------------------------------------------------------------------
 * Tests for instructions with register-register operands
 * SPARCv8 format: inst %rs1, %rs2, %rd
 *-----------------------------------------------------------------------*/

#define TEST_RR_OP(testnum, inst, result, val1, val2) \
    TEST_CASE(testnum, TEST_RESULT, result, \
        LOAD_IMM(TEST_SCRATCH1, val1); \
        LOAD_IMM(TEST_SCRATCH2, val2); \
        inst TEST_SCRATCH1, TEST_SCRATCH2, TEST_RESULT; \
    )

#define TEST_RR_SRC1_EQ_DEST(testnum, inst, result, val1, val2) \
    TEST_CASE(testnum, TEST_SCRATCH1, result, \
        LOAD_IMM(TEST_SCRATCH1, val1); \
        LOAD_IMM(TEST_SCRATCH2, val2); \
        inst TEST_SCRATCH1, TEST_SCRATCH2, TEST_SCRATCH1; \
    )

#define TEST_RR_SRC2_EQ_DEST(testnum, inst, result, val1, val2) \
    TEST_CASE(testnum, TEST_SCRATCH2, result, \
        LOAD_IMM(TEST_SCRATCH1, val1); \
        LOAD_IMM(TEST_SCRATCH2, val2); \
        inst TEST_SCRATCH1, TEST_SCRATCH2, TEST_SCRATCH2; \
    )

#define TEST_RR_SRC12_EQ_DEST(testnum, inst, result, val1) \
    TEST_CASE(testnum, TEST_SCRATCH1, result, \
        LOAD_IMM(TEST_SCRATCH1, val1); \
        inst TEST_SCRATCH1, TEST_SCRATCH1, TEST_SCRATCH1; \
    )

/*-----------------------------------------------------------------------
 * Tests for instructions with register-immediate operands
 * SPARCv8 format: inst %rs1, simm13, %rd
 *-----------------------------------------------------------------------*/

#define TEST_RI_OP(testnum, inst, result, val1, imm) \
    TEST_CASE(testnum, TEST_RESULT, result, \
        LOAD_IMM(TEST_SCRATCH1, val1); \
        inst TEST_SCRATCH1, imm, TEST_RESULT; \
    )

#define TEST_RI_SRC_EQ_DEST(testnum, inst, result, val1, imm) \
    TEST_CASE(testnum, TEST_SCRATCH1, result, \
        LOAD_IMM(TEST_SCRATCH1, val1); \
        inst TEST_SCRATCH1, imm, TEST_SCRATCH1; \
    )

/*-----------------------------------------------------------------------
 * Tests for SETHI instruction
 *-----------------------------------------------------------------------*/

#define TEST_SETHI(testnum, result, imm22) \
    TEST_CASE(testnum, TEST_RESULT, result, \
        sethi imm22, TEST_RESULT; \
    )

/*-----------------------------------------------------------------------
 * Tests for load instructions
 * SPARCv8 format: ld [%rs1 + offset], %rd
 *-----------------------------------------------------------------------*/

#define TEST_LD_OP(testnum, inst, result, offset, base) \
test_ ## testnum: \
    mov testnum, TESTNUM; \
    LOAD_IMM(TEST_SCRATCH1, base); \
    inst [TEST_SCRATCH1 + offset], TEST_RESULT; \
    LOAD_IMM(TEST_EXPECTED, result); \
    cmp TEST_RESULT, TEST_EXPECTED; \
    be test_ ## testnum ## _pass; \
    nop; \
    ba fail; \
    nop; \
test_ ## testnum ## _pass:

/*-----------------------------------------------------------------------
 * Tests for store instructions
 * SPARCv8 format: st %rd, [%rs1 + offset]
 *-----------------------------------------------------------------------*/

#define TEST_ST_OP(testnum, st_inst, ld_inst, result, offset, base) \
test_ ## testnum: \
    mov testnum, TESTNUM; \
    LOAD_IMM(TEST_SCRATCH1, result); \
    LOAD_IMM(TEST_SCRATCH2, base); \
    st_inst TEST_SCRATCH1, [TEST_SCRATCH2 + offset]; \
    ld_inst [TEST_SCRATCH2 + offset], TEST_RESULT; \
    LOAD_IMM(TEST_EXPECTED, result); \
    cmp TEST_RESULT, TEST_EXPECTED; \
    be test_ ## testnum ## _pass; \
    nop; \
    ba fail; \
    nop; \
test_ ## testnum ## _pass:

/*-----------------------------------------------------------------------
 * Tests for branch instructions based on condition codes
 * SPARCv8: subcc sets icc, then branch tests icc
 *-----------------------------------------------------------------------*/

#define TEST_BR_TAKEN(testnum, inst, val1, val2) \
test_ ## testnum: \
    mov testnum, TESTNUM; \
    LOAD_IMM(TEST_SCRATCH1, val1); \
    LOAD_IMM(TEST_SCRATCH2, val2); \
    subcc TEST_SCRATCH1, TEST_SCRATCH2, %g0; \
    inst test_ ## testnum ## _target; \
    nop; \
    ba fail; \
    nop; \
test_ ## testnum ## _target: \
    ba test_ ## testnum ## _pass; \
    nop; \
test_ ## testnum ## _pass:

#define TEST_BR_NOT_TAKEN(testnum, inst, val1, val2) \
test_ ## testnum: \
    mov testnum, TESTNUM; \
    LOAD_IMM(TEST_SCRATCH1, val1); \
    LOAD_IMM(TEST_SCRATCH2, val2); \
    subcc TEST_SCRATCH1, TEST_SCRATCH2, %g0; \
    inst test_ ## testnum ## _fail; \
    nop; \
    ba test_ ## testnum ## _pass; \
    nop; \
test_ ## testnum ## _fail: \
    ba fail; \
    nop; \
test_ ## testnum ## _pass:

/*-----------------------------------------------------------------------
 * Bypass tests - test data forwarding/hazards
 *-----------------------------------------------------------------------*/

#define TEST_RR_DEST_BYPASS(testnum, nop_cycles, inst, result, val1, val2) \
test_ ## testnum: \
    mov testnum, TESTNUM; \
    LOAD_IMM(TEST_SCRATCH1, val1); \
    LOAD_IMM(TEST_SCRATCH2, val2); \
    inst TEST_SCRATCH1, TEST_SCRATCH2, TEST_RESULT; \
    TEST_INSERT_NOPS_ ## nop_cycles; \
    LOAD_IMM(TEST_EXPECTED, result); \
    cmp TEST_RESULT, TEST_EXPECTED; \
    be test_ ## testnum ## _pass; \
    nop; \
    ba fail; \
    nop; \
test_ ## testnum ## _pass:

#define TEST_RR_SRC12_BYPASS(testnum, src1_nops, src2_nops, inst, result, val1, val2) \
test_ ## testnum: \
    mov testnum, TESTNUM; \
    LOAD_IMM(TEST_SCRATCH1, val1); \
    TEST_INSERT_NOPS_ ## src1_nops; \
    LOAD_IMM(TEST_SCRATCH2, val2); \
    TEST_INSERT_NOPS_ ## src2_nops; \
    inst TEST_SCRATCH1, TEST_SCRATCH2, TEST_RESULT; \
    LOAD_IMM(TEST_EXPECTED, result); \
    cmp TEST_RESULT, TEST_EXPECTED; \
    be test_ ## testnum ## _pass; \
    nop; \
    ba fail; \
    nop; \
test_ ## testnum ## _pass:

#define TEST_RR_SRC21_BYPASS(testnum, src1_nops, src2_nops, inst, result, val1, val2) \
    TEST_RR_SRC12_BYPASS(testnum, src2_nops, src1_nops, inst, result, val2, val1)

/*-----------------------------------------------------------------------
 * Zero source/dest tests
 * %g0 is hardwired to 0 in SPARCv8
 *-----------------------------------------------------------------------*/

#define TEST_RR_ZEROSRC1(testnum, inst, result, val) \
    TEST_CASE(testnum, TEST_RESULT, result, \
        LOAD_IMM(TEST_SCRATCH1, val); \
        inst %g0, TEST_SCRATCH1, TEST_RESULT; \
    )

#define TEST_RR_ZEROSRC2(testnum, inst, result, val) \
    TEST_CASE(testnum, TEST_RESULT, result, \
        LOAD_IMM(TEST_SCRATCH1, val); \
        inst TEST_SCRATCH1, %g0, TEST_RESULT; \
    )

#define TEST_RR_ZEROSRC12(testnum, inst, result) \
    TEST_CASE(testnum, TEST_RESULT, result, \
        inst %g0, %g0, TEST_RESULT; \
    )

/* Writing to %g0 should have no effect */
#define TEST_RR_ZERODEST(testnum, inst, val1, val2) \
test_ ## testnum: \
    mov testnum, TESTNUM; \
    LOAD_IMM(TEST_SCRATCH1, val1); \
    LOAD_IMM(TEST_SCRATCH2, val2); \
    inst TEST_SCRATCH1, TEST_SCRATCH2, %g0; \
    cmp %g0, 0; \
    be test_ ## testnum ## _pass; \
    nop; \
    ba fail; \
    nop; \
test_ ## testnum ## _pass:

/*-----------------------------------------------------------------------
 * Tests for condition code setting instructions (addcc, subcc, etc.)
 *-----------------------------------------------------------------------*/

/* Test that an instruction sets the Z (zero) flag correctly */
#define TEST_CC_Z_SET(testnum, inst, val1, val2) \
test_ ## testnum: \
    mov testnum, TESTNUM; \
    LOAD_IMM(TEST_SCRATCH1, val1); \
    LOAD_IMM(TEST_SCRATCH2, val2); \
    inst TEST_SCRATCH1, TEST_SCRATCH2, TEST_RESULT; \
    be test_ ## testnum ## _pass; \
    nop; \
    ba fail; \
    nop; \
test_ ## testnum ## _pass:

#define TEST_CC_Z_CLEAR(testnum, inst, val1, val2) \
test_ ## testnum: \
    mov testnum, TESTNUM; \
    LOAD_IMM(TEST_SCRATCH1, val1); \
    LOAD_IMM(TEST_SCRATCH2, val2); \
    inst TEST_SCRATCH1, TEST_SCRATCH2, TEST_RESULT; \
    bne test_ ## testnum ## _pass; \
    nop; \
    ba fail; \
    nop; \
test_ ## testnum ## _pass:

/* Test that an instruction sets the N (negative) flag correctly */
#define TEST_CC_N_SET(testnum, inst, val1, val2) \
test_ ## testnum: \
    mov testnum, TESTNUM; \
    LOAD_IMM(TEST_SCRATCH1, val1); \
    LOAD_IMM(TEST_SCRATCH2, val2); \
    inst TEST_SCRATCH1, TEST_SCRATCH2, TEST_RESULT; \
    bneg test_ ## testnum ## _pass; \
    nop; \
    ba fail; \
    nop; \
test_ ## testnum ## _pass:

#define TEST_CC_N_CLEAR(testnum, inst, val1, val2) \
test_ ## testnum: \
    mov testnum, TESTNUM; \
    LOAD_IMM(TEST_SCRATCH1, val1); \
    LOAD_IMM(TEST_SCRATCH2, val2); \
    inst TEST_SCRATCH1, TEST_SCRATCH2, TEST_RESULT; \
    bpos test_ ## testnum ## _pass; \
    nop; \
    ba fail; \
    nop; \
test_ ## testnum ## _pass:

#endif /* __SPARCV8_TEST_MACROS_H */
