/* SPARCv8 SMULcc instruction tests (signed multiply with condition codes) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * SMULcc: Signed multiply, sets icc based on low 32 bits
   * Y:rd <- rs1 * reg_or_imm (signed)
   * icc.n = rd[31], icc.z = (rd==0), icc.v = 0, icc.c = 0
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: Simple positive multiplication, check result
   *-------------------------------------------------------------*/
  TEST_CASE( 2, %l0, 6, \
    set 2, %l1; \
    set 3, %l2; \
    smulcc %l1, %l2, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 3: Result is zero - Z flag should be set
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 12345, %l1
    smulcc %l1, %g0, %l0
    be test_3_pass       /* Z should be set */
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Result is non-zero - Z flag should be clear
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 5, %l1
    set 3, %l2
    smulcc %l1, %l2, %l0
    bne test_4_pass      /* Z should be clear */
    nop
    ba fail
    nop
test_4_pass:

  /*-------------------------------------------------------------
   * Test 5: Negative result - N flag should be set
   *-------------------------------------------------------------*/
test_5:
    mov 5, TESTNUM
    set -3, %l1
    set 5, %l2
    smulcc %l1, %l2, %l0
    bneg test_5_pass     /* N should be set */
    nop
    ba fail
    nop
test_5_pass:

  /*-------------------------------------------------------------
   * Test 6: Positive result - N flag should be clear
   *-------------------------------------------------------------*/
test_6:
    mov 6, TESTNUM
    set 3, %l1
    set 5, %l2
    smulcc %l1, %l2, %l0
    bpos test_6_pass     /* N should be clear */
    nop
    ba fail
    nop
test_6_pass:

  /*-------------------------------------------------------------
   * Test 7: Negative times negative = positive
   *-------------------------------------------------------------*/
  TEST_CASE( 7, %l0, 15, \
    set -3, %l1; \
    set -5, %l2; \
    smulcc %l1, %l2, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 8: SMULcc with immediate operand
   *-------------------------------------------------------------*/
  TEST_CASE( 8, %l0, 50, \
    set 10, %l1; \
    smulcc %l1, 5, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 9: Large multiplication, verify low 32 bits
   *-------------------------------------------------------------*/
  TEST_CASE( 9, %l0, 1000000, \
    set 1000, %l1; \
    set 1000, %l2; \
    smulcc %l1, %l2, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 10: SMULcc result to %g0 discards result
   *-------------------------------------------------------------*/
test_10:
    mov 10, TESTNUM
    set 5, %l1
    set 7, %l2
    smulcc %l1, %l2, %g0
    cmp %g0, 0
    be test_10_pass
    nop
    ba fail
    nop
test_10_pass:

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
