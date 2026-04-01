/*
 * Alpha INSLH (Insert Longword High) Test
 * Rc = bv ? (Ra[31:0] >> (64 - 8*bv)) : 0
 * Inserts the high part of an unaligned longword
 * When bv=0, result is 0; otherwise shifts right by (64-8*bv) bits
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic longword high insertion
     * Formula: bv ? (Ra[31:0] >> (64 - 8*bv)) : 0
     *-------------------------------------------------------------*/

    /* Test 1: Position 0 - result is 0 */
    TEST_CASE_START(1)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)
    lda $2, 0($31)
    inslh $1, $2, $3
    lda $5, 0($31)           /* bv=0, result=0 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: Position 1 - shift right (64-8) = 56 */
    TEST_CASE_START(2)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)
    lda $2, 1($31)
    inslh $1, $2, $3
    /* 0x12345678 >> 56 = 0 */
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: Position 5 - shift right (64-40) = 24 */
    TEST_CASE_START(3)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)
    lda $2, 5($31)
    inslh $1, $2, $3
    /* 0x12345678 >> 24 = 0x12 */
    lda $5, 0x12($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Position 6 - shift right (64-48) = 16 */
    TEST_CASE_START(4)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)
    lda $2, 6($31)
    inslh $1, $2, $3
    /* 0x12345678 >> 16 = 0x1234 */
    lda $5, 0x1234($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: Position 7 - shift right (64-56) = 8 */
    TEST_CASE_START(5)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)
    lda $2, 7($31)
    inslh $1, $2, $3
    /* 0x12345678 >> 8 = 0x123456 */
    lda $5, 0x3456($31)
    ldah $5, 0x0012($5)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Test with immediate form
     *-------------------------------------------------------------*/

    /* Test 6: Position 7 using immediate */
    TEST_CASE_START(6)
    lda $1, 0xBCDE($31)
    ldah $1, 0x789A($1)      /* 0x789ABCDE */
    inslh $1, 7, $3
    /* 0x789ABCDE >> 8 = 0x789ABC */
    lda $5, 0x9ABC($31)
    ldah $5, 0x0078($5)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 7: Position 0 using immediate - always 0 */
    TEST_CASE_START(7)
    lda $1, -1($31)
    inslh $1, 0, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Edge cases
     *-------------------------------------------------------------*/

    /* Test 8: Insert from zero */
    TEST_CASE_START(8)
    lda $1, 0($31)
    inslh $1, 7, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
