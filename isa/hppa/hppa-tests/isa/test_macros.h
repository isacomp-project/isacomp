/* HPPA (PA-RISC) Test Macros for ISA testing */
/* Based on riscv-tests/mips-tests macro structure */

#ifndef __HPPA_TEST_MACROS_H
#define __HPPA_TEST_MACROS_H

/*-----------------------------------------------------------------------
 * Helper macros
 *-----------------------------------------------------------------------*/

/* Test number register - %r28 (ret0) used for test number */
#define TESTNUM %r28

/* Insert NOPs for bypass testing */
#define TEST_INSERT_NOPS_0
#define TEST_INSERT_NOPS_1  nop ; TEST_INSERT_NOPS_0
#define TEST_INSERT_NOPS_2  nop ; TEST_INSERT_NOPS_1
#define TEST_INSERT_NOPS_3  nop ; TEST_INSERT_NOPS_2

/* Load immediate helper - uses LDIL+LDO for full 32-bit values */
/* Note: Use L% and R% syntax to avoid C preprocessor confusion with L'val char literal */
#define LI(reg, val) \
    ldil L%val, reg ; \
    ldo R%val(reg), reg

/* Core test case macro */
#define TEST_CASE(testnum, destreg, result, code...) \
test_ ## testnum: ; \
    LI(TESTNUM, testnum) ; \
    code ; \
    LI(%r29, result) ; \
    cmpb,<> destreg, %r29, fail ; \
    nop ;

/*-----------------------------------------------------------------------
 * Tests for instructions with register-register operands
 *-----------------------------------------------------------------------*/

#define TEST_RR_OP(testnum, inst, result, val1, val2) \
    TEST_CASE(testnum, %r1, result, \
        LI(%r2, val1) ; \
        LI(%r3, val2) ; \
        inst %r2, %r3, %r1 ; \
    )

#define TEST_RR_SRC1_EQ_DEST(testnum, inst, result, val1, val2) \
    TEST_CASE(testnum, %r2, result, \
        LI(%r2, val1) ; \
        LI(%r3, val2) ; \
        inst %r2, %r3, %r2 ; \
    )

#define TEST_RR_SRC2_EQ_DEST(testnum, inst, result, val1, val2) \
    TEST_CASE(testnum, %r3, result, \
        LI(%r2, val1) ; \
        LI(%r3, val2) ; \
        inst %r2, %r3, %r3 ; \
    )

#define TEST_RR_SRC12_EQ_DEST(testnum, inst, result, val1) \
    TEST_CASE(testnum, %r2, result, \
        LI(%r2, val1) ; \
        inst %r2, %r2, %r2 ; \
    )

#define TEST_RR_ZEROSRC1(testnum, inst, result, val) \
    TEST_CASE(testnum, %r1, result, \
        LI(%r3, val) ; \
        inst %r0, %r3, %r1 ; \
    )

#define TEST_RR_ZEROSRC2(testnum, inst, result, val) \
    TEST_CASE(testnum, %r1, result, \
        LI(%r2, val) ; \
        inst %r2, %r0, %r1 ; \
    )

#define TEST_RR_ZEROSRC12(testnum, inst, result) \
    TEST_CASE(testnum, %r1, result, \
        inst %r0, %r0, %r1 ; \
    )

#define TEST_RR_ZERODEST(testnum, inst, val1, val2) \
test_ ## testnum: ; \
    LI(TESTNUM, testnum) ; \
    LI(%r2, val1) ; \
    LI(%r3, val2) ; \
    inst %r2, %r3, %r0 ; \
    cmpb,<> %r0, %r0, fail ; \
    nop ;

/*-----------------------------------------------------------------------
 * Tests for instructions with immediate operands
 * Note: HPPA uses different syntax - LDO d(b),t for immediate add
 *-----------------------------------------------------------------------*/

#define TEST_IMM_OP(testnum, inst, result, val1, imm) \
    TEST_CASE(testnum, %r1, result, \
        LI(%r2, val1) ; \
        inst imm(%r2), %r1 ; \
    )

#define TEST_IMM_SRC1_EQ_DEST(testnum, inst, result, val1, imm) \
    TEST_CASE(testnum, %r2, result, \
        LI(%r2, val1) ; \
        inst imm(%r2), %r2 ; \
    )

#define TEST_IMM_ZEROSRC1(testnum, inst, result, imm) \
    TEST_CASE(testnum, %r1, result, \
        inst imm(%r0), %r1 ; \
    )

/*-----------------------------------------------------------------------
 * Tests for load instructions
 *-----------------------------------------------------------------------*/

#define TEST_LD_OP(testnum, inst, result, offset, base) \
    TEST_CASE(testnum, %r1, result, \
        ldil L'base, %r2 ; \
        ldo R'base(%r2), %r2 ; \
        inst offset(%r2), %r1 ; \
    )

/*-----------------------------------------------------------------------
 * Tests for store instructions
 *-----------------------------------------------------------------------*/

#define TEST_ST_OP(testnum, load_inst, store_inst, result, offset, base) \
    TEST_CASE(testnum, %r1, result, \
        ldil L'base, %r2 ; \
        ldo R'base(%r2), %r2 ; \
        LI(%r3, result) ; \
        store_inst %r3, offset(%r2) ; \
        load_inst offset(%r2), %r1 ; \
    )

/*-----------------------------------------------------------------------
 * Tests for branch instructions
 *-----------------------------------------------------------------------*/

#define TEST_BR2_OP_TAKEN(testnum, inst, val1, val2) \
test_ ## testnum: ; \
    LI(TESTNUM, testnum) ; \
    LI(%r2, val1) ; \
    LI(%r3, val2) ; \
    inst %r2, %r3, 2f ; \
    nop ; \
    b fail ; \
    nop ; \
1:  b 3f ; \
    nop ; \
2:  inst %r2, %r3, 1b ; \
    nop ; \
    b fail ; \
    nop ; \
3:

#define TEST_BR2_OP_NOTTAKEN(testnum, inst, val1, val2) \
test_ ## testnum: ; \
    LI(TESTNUM, testnum) ; \
    LI(%r2, val1) ; \
    LI(%r3, val2) ; \
    inst %r2, %r3, 1f ; \
    nop ; \
    b 2f ; \
    nop ; \
1:  b fail ; \
    nop ; \
2:  inst %r2, %r3, 1b ; \
    nop ;

/*-----------------------------------------------------------------------
 * Test framework macros
 *-----------------------------------------------------------------------*/

#define RVTEST_CODE_BEGIN \
    .text ; \
    .align 4 ; \
    .globl _start ; \
_start: ; \
    ldo 0x1ffc(%r0), %r30 ; \
    ldo 0(%r0), TESTNUM ;

#define RVTEST_CODE_END

#define TEST_PASSFAIL \
    b pass ; \
    nop ;

#define RVTEST_PASS \
pass: ; \
    b pass ; \
    nop

#define RVTEST_FAIL \
fail: ; \
    b fail ; \
    nop

#define RVTEST_DATA_BEGIN \
    .data ; \
    .align 4 ;

#define RVTEST_DATA_END

#define TEST_DATA

#endif /* __HPPA_TEST_MACROS_H */
