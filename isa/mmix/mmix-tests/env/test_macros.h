/* MMIX Test Macros for ISA testing */
/* MMIX is a 64-bit RISC architecture */
/* Since MMIX toolchain isn't commonly available, we use direct hex encoding */

#ifndef __MMIX_TEST_MACROS_H
#define __MMIX_TEST_MACROS_H

/*-----------------------------------------------------------------------
 * MMIX Instruction Format
 * Each instruction is 32 bits: OP X Y Z
 * OP: opcode (bits 31:24)
 * X: destination register (bits 23:16)
 * Y: first source/operand (bits 15:8)
 * Z: second source/operand (bits 7:0)
 *-----------------------------------------------------------------------*/

/* Test number register - we use $255 */
#define TESTNUM 255

/* MMIX register names (for documentation) */
/* $0-$255 are general purpose registers */

/*-----------------------------------------------------------------------
 * MMIX Opcodes (hex values)
 *-----------------------------------------------------------------------*/
#define OP_ADD      0x20
#define OP_ADDI     0x21
#define OP_SUB      0x24
#define OP_SUBI     0x25
#define OP_MUL      0x18
#define OP_MULI     0x19
#define OP_DIV      0x1C
#define OP_DIVI     0x1D
#define OP_AND      0xC8
#define OP_ANDI     0xC9
#define OP_OR       0xC0
#define OP_ORI      0xC1
#define OP_XOR      0xC6
#define OP_XORI     0xC7
#define OP_NOR      0xC4
#define OP_NAND     0xCC
#define OP_SL       0x38
#define OP_SLI      0x39
#define OP_SLU      0x3A
#define OP_SLUI     0x3B
#define OP_SR       0x3C
#define OP_SRI      0x3D
#define OP_SRU      0x3E
#define OP_SRUI     0x3F
#define OP_CMP      0x30
#define OP_CMPI     0x31
#define OP_CMPU     0x32
#define OP_CMPUI    0x33
#define OP_LDB      0x80
#define OP_LDBI     0x81
#define OP_LDBU     0x82
#define OP_LDO      0x8C
#define OP_LDOI     0x8D
#define OP_STB      0xA0
#define OP_STBI     0xA1
#define OP_STO      0xAC
#define OP_STOI     0xAD
#define OP_BN       0x40
#define OP_BNB      0x41
#define OP_BZ       0x42
#define OP_BZB      0x43
#define OP_BP       0x44
#define OP_BPB      0x45
#define OP_BNN      0x48
#define OP_BNZ      0x4A
#define OP_BNZB     0x4B
#define OP_JMP      0xF0
#define OP_JMPB     0xF1
#define OP_GO       0x9E
#define OP_GOI      0x9F
#define OP_GETA     0xF4
#define OP_SETL     0xE3
#define OP_SETH     0xE0
#define OP_SETMH    0xE1
#define OP_SETML    0xE2

/*-----------------------------------------------------------------------
 * Helper macros for constructing instructions
 *-----------------------------------------------------------------------*/
#define MMIX_INSTR(op, x, y, z) \
    (((op) << 24) | ((x) << 16) | ((y) << 8) | (z))

#define MMIX_INSTR_YZ(op, x, yz) \
    (((op) << 24) | ((x) << 16) | ((yz) & 0xFFFF))

#define MMIX_INSTR_XYZ(op, xyz) \
    (((op) << 24) | ((xyz) & 0xFFFFFF))

/*-----------------------------------------------------------------------
 * Test framework macros
 *-----------------------------------------------------------------------*/

/* These would be used in assembly if we had an assembler */
/* For now, tests are written as hex memory files */

#define RVTEST_CODE_BEGIN \
    /* Start of test code */

#define RVTEST_CODE_END \
    /* End of test code */

#define TEST_PASSFAIL \
    /* Jump to pass if we get here */

#define RVTEST_PASS \
    /* pass: infinite loop at pass address */

#define RVTEST_FAIL \
    /* fail: infinite loop at fail address */

#define RVTEST_DATA_BEGIN \
    /* Start of test data */

#define RVTEST_DATA_END \
    /* End of test data */

#define TEST_DATA

#endif /* __MMIX_TEST_MACROS_H */
