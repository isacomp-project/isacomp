/* SPARCv8 TSUBcc instruction tests (tagged subtract with condition codes) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TSUBcc: Tagged subtract, sets icc
   * rd <- rs1 - reg_or_imm
   * Tag overflow (V flag) if either of low 2 bits of operands are
   * non-zero or if arithmetic overflow
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: Simple subtraction with properly tagged operands
   * Both operands have low 2 bits = 00 (no tag overflow)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set 20, %l1           /* Low 2 bits = 00 */
    set 8, %l2            /* Low 2 bits = 00 */
    tsubcc %l1, %l2, %l0  /* 20 - 8 = 12 */
    cmp %l0, 12
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: No tag overflow when both have tag bits = 00
   * V flag should be clear (no overflow)
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 16, %l1           /* Low 2 bits = 00 */
    set 8, %l2            /* Low 2 bits = 00 */
    tsubcc %l1, %l2, %l0
    bvc test_3_pass       /* V should be clear */
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Tag overflow when first operand has tag bits set
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 21, %l1           /* Low 2 bits = 01 (tagged!) */
    set 8, %l2            /* Low 2 bits = 00 */
    tsubcc %l1, %l2, %l0
    bvs test_4_pass       /* V should be set (tag overflow) */
    nop
    ba fail
    nop
test_4_pass:

  /*-------------------------------------------------------------
   * Test 5: Tag overflow when second operand has tag bits set
   *-------------------------------------------------------------*/
test_5:
    mov 5, TESTNUM
    set 16, %l1           /* Low 2 bits = 00 */
    set 6, %l2            /* Low 2 bits = 10 (tagged!) */
    tsubcc %l1, %l2, %l0
    bvs test_5_pass       /* V should be set (tag overflow) */
    nop
    ba fail
    nop
test_5_pass:

  /*-------------------------------------------------------------
   * Test 6: Tag overflow when both operands have tag bits set
   *-------------------------------------------------------------*/
test_6:
    mov 6, TESTNUM
    set 21, %l1           /* Low 2 bits = 01 */
    set 7, %l2            /* Low 2 bits = 11 */
    tsubcc %l1, %l2, %l0
    bvs test_6_pass       /* V should be set (tag overflow) */
    nop
    ba fail
    nop
test_6_pass:

  /*-------------------------------------------------------------
   * Test 7: Result is zero - Z flag should be set
   *-------------------------------------------------------------*/
test_7:
    mov 7, TESTNUM
    set 12, %l1
    set 12, %l2
    tsubcc %l1, %l2, %l0  /* 12 - 12 = 0 */
    be test_7_pass        /* Z should be set */
    nop
    ba fail
    nop
test_7_pass:

  /*-------------------------------------------------------------
   * Test 8: Negative result - N flag should be set
   *-------------------------------------------------------------*/
test_8:
    mov 8, TESTNUM
    set 4, %l1            /* Low 2 bits = 00 */
    set 8, %l2            /* Low 2 bits = 00 */
    tsubcc %l1, %l2, %l0  /* 4 - 8 = -4 */
    bneg test_8_pass      /* N should be set */
    nop
    ba fail
    nop
test_8_pass:

  /*-------------------------------------------------------------
   * Test 9: TSUBcc with immediate operand (tag bits 00)
   *-------------------------------------------------------------*/
test_9:
    mov 9, TESTNUM
    set 100, %l1          /* Low 2 bits = 00 */
    tsubcc %l1, 20, %l0   /* 100 - 20 = 80 */
    cmp %l0, 80
    be test_9_pass
    nop
    ba fail
    nop
test_9_pass:

  /*-------------------------------------------------------------
   * Test 10: TSUBcc result to %g0 discards result
   *-------------------------------------------------------------*/
test_10:
    mov 10, TESTNUM
    set 20, %l1
    set 8, %l2
    tsubcc %l1, %l2, %g0  /* Result discarded */
    cmp %g0, 0
    be test_10_pass
    nop
    ba fail
    nop
test_10_pass:

  /*-------------------------------------------------------------
   * Test 11: Arithmetic overflow should also set V flag
   * Even with tag bits = 00
   *-------------------------------------------------------------*/
test_11:
    mov 11, TESTNUM
    set 0x80000000, %l1   /* Most negative with tag=00 */
    set 4, %l2            /* Small positive with tag=00 */
    tsubcc %l1, %l2, %l0  /* Should overflow (negative - positive = more negative) */
    bvs test_11_pass      /* V should be set (arithmetic overflow) */
    nop
    ba fail
    nop
test_11_pass:

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
