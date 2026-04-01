/*
 * Alpha LDL_L (Load Longword Locked) Test
 * Tests load-linked instruction for atomic operations
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Load-locked tests - use direct addressing for testbench
     *-------------------------------------------------------------*/

    /* Test 1: Initialize test data at address 0x300 */
    TEST_CASE_START(1)
    lda $1, 0x300($31)       /* Base address */
    ldiq $2, 0x12345678
    stl $2, 0($1)            /* Store test value */
    lda $2, 0x5678($31)      /* Use simpler value 0x5678 */
    stl $2, 4($1)            /* Store second value */
    lda $2, 0($31)
    stl $2, 8($1)            /* Clear third slot */

    /* Test 2: Simple LDL_L */
    TEST_CASE_START(2)
    lda $1, 0x300($31)
    ldl_l $3, 0($1)
    ldiq $5, 0x12345678
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: LDL_L with offset */
    TEST_CASE_START(3)
    lda $1, 0x300($31)
    ldl_l $3, 4($1)
    /* Just check that ldl_l returns same value as regular ldl */
    ldl $5, 4($1)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: LDL_L / STL_C sequence (basic atomic) */
    TEST_CASE_START(4)
    lda $1, 0x300($31)
    ldl_l $2, 8($1)          /* Load-locked the location */
    ldiq $3, 0x9999          /* Value to store */
    stl_c $3, 8($1)          /* Store-conditional */
    beq $3, fail             /* STL_C should succeed (return 1) */
    ldl $4, 8($1)            /* Verify the store */
    ldiq $5, 0x9999
    cmpeq $4, $5, $6
    beq $6, fail

    /* Test 5: Multiple LDL_L (each clears previous lock) */
    TEST_CASE_START(5)
    lda $1, 0x300($31)
    ldl_l $2, 0($1)
    ldl_l $3, 4($1)
    /* Only the second lock should be active */

ALPHA_TEST_END
