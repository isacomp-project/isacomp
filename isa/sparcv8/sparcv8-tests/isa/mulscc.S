/* SPARCv8 MULScc instruction tests (multiply step with condition codes) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MULScc: Multiply step, sets icc
   * 1. operand1 = ((N xor V) << 31) | (rs1 >> 1)
   * 2. if Y[0] == 1: result = operand1 + operand2; else result = operand1
   * 3. Y = (rs1[0] << 31) | (Y >> 1)
   * 4. rd = result, set icc
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: Basic MULScc with Y[0]=0 (no add)
   * N=0, V=0, so operand1 = rs1 >> 1
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    /* Set up: N=0, V=0 in PSR by doing subcc 0,0 */
    subcc %g0, %g0, %g0
    /* Set Y with bit 0 = 0 */
    set 0x00000010, %l1
    wr %l1, %g0, %y
    nop; nop; nop
    /* rs1 = 0x00000010, rs2 = anything */
    set 0x00000010, %l1
    set 0x00000020, %l2
    mulscc %l1, %l2, %l0
    /* operand1 = 0 << 31 | (0x10 >> 1) = 0x08 */
    /* Y[0] = 0, so result = operand1 + 0 = 0x08 */
    cmp %l0, 0x08
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: MULScc with Y[0]=1 (add operand2)
   * N=0, V=0, so operand1 = rs1 >> 1
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    /* Set up: N=0, V=0 */
    subcc %g0, %g0, %g0
    /* Set Y with bit 0 = 1 */
    set 0x00000011, %l1
    wr %l1, %g0, %y
    nop; nop; nop
    /* rs1 = 0x00000010, rs2 = 0x04 */
    set 0x00000010, %l1
    set 0x00000004, %l2
    mulscc %l1, %l2, %l0
    /* operand1 = 0 << 31 | (0x10 >> 1) = 0x08 */
    /* Y[0] = 1, so result = 0x08 + 0x04 = 0x0C */
    cmp %l0, 0x0C
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Check Y register shift
   * Y should be (rs1[0] << 31) | (Y >> 1)
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    subcc %g0, %g0, %g0
    /* Set Y = 0x80000000 */
    set 0x80000000, %l1
    wr %l1, %g0, %y
    nop; nop; nop
    /* rs1 = 0x00000001 (bit 0 = 1) */
    set 0x00000001, %l1
    set 0, %l2
    mulscc %l1, %l2, %l0
    /* After MULScc: Y = (1 << 31) | (0x80000000 >> 1) = 0x80000000 | 0x40000000 = 0xC0000000 */
    rd %y, %l3
    set 0xC0000000, %l4
    cmp %l3, %l4
    be test_4_pass
    nop
    ba fail
    nop
test_4_pass:

  /*-------------------------------------------------------------
   * Test 5: MULScc with N=1 (inserts 1 in MSB of operand1)
   *-------------------------------------------------------------*/
test_5:
    mov 5, TESTNUM
    /* Set N=1, V=0 by doing negative result */
    set -1, %l1
    subcc %l1, %g0, %g0   /* N=1, V=0 */
    /* Set Y with bit 0 = 0 */
    set 0x00000000, %l1
    wr %l1, %g0, %y
    nop; nop; nop
    /* rs1 = 0x00000010 */
    set 0x00000010, %l1
    set 0, %l2
    mulscc %l1, %l2, %l0
    /* N xor V = 1 xor 0 = 1 */
    /* operand1 = 1 << 31 | (0x10 >> 1) = 0x80000008 */
    /* Y[0] = 0, so result = operand1 = 0x80000008 */
    set 0x80000008, %l3
    cmp %l0, %l3
    be test_5_pass
    nop
    ba fail
    nop
test_5_pass:

  /*-------------------------------------------------------------
   * Test 6: Result is zero - Z flag should be set
   *-------------------------------------------------------------*/
test_6:
    mov 6, TESTNUM
    subcc %g0, %g0, %g0   /* N=0, V=0 */
    set 0x00000000, %l1
    wr %l1, %g0, %y       /* Y[0] = 0 */
    nop; nop; nop
    mulscc %g0, %g0, %l0  /* operand1 = 0, add 0 */
    be test_6_pass        /* Z should be set */
    nop
    ba fail
    nop
test_6_pass:

  /*-------------------------------------------------------------
   * Test 7: Negative result - N flag should be set
   *-------------------------------------------------------------*/
test_7:
    mov 7, TESTNUM
    /* Force N=1, V=0 */
    set -1, %l1
    subcc %l1, %g0, %g0
    /* Set Y with bit 0 = 0 */
    set 0x00000000, %l1
    wr %l1, %g0, %y
    nop; nop; nop
    set 0x00000010, %l1
    mulscc %l1, %g0, %l0  /* Result has bit 31 set */
    bneg test_7_pass
    nop
    ba fail
    nop
test_7_pass:

  /*-------------------------------------------------------------
   * Test 8: MULScc with immediate operand
   *-------------------------------------------------------------*/
test_8:
    mov 8, TESTNUM
    subcc %g0, %g0, %g0   /* N=0, V=0 */
    set 0x00000001, %l1   /* Y[0] = 1 */
    wr %l1, %g0, %y
    nop; nop; nop
    set 0x00000020, %l1
    mulscc %l1, 4, %l0    /* operand1 = 0x10, add 4 = 0x14 */
    cmp %l0, 0x14
    be test_8_pass
    nop
    ba fail
    nop
test_8_pass:

  /*-------------------------------------------------------------
   * Test 9: MULScc result to %g0 discards result
   *-------------------------------------------------------------*/
test_9:
    mov 9, TESTNUM
    subcc %g0, %g0, %g0
    set 0x00000001, %l1
    wr %l1, %g0, %y
    nop; nop; nop
    set 0x00000020, %l1
    mulscc %l1, 4, %g0    /* Result discarded */
    cmp %g0, 0
    be test_9_pass
    nop
    ba fail
    nop
test_9_pass:

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
