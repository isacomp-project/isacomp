/* SPARCv8 UMULcc instruction tests (unsigned multiply with condition codes) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * UMULcc: Unsigned multiply, sets icc based on low 32 bits
   * Y:rd <- rs1 * reg_or_imm (unsigned)
   * icc.n = rd[31], icc.z = (rd==0), icc.v = 0, icc.c = 0
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: Simple unsigned multiplication, check result
   *-------------------------------------------------------------*/
  TEST_CASE( 2, %l0, 6, \
    set 2, %l1; \
    set 3, %l2; \
    umulcc %l1, %l2, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 3: Result is zero - Z flag should be set
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 12345, %l1
    umulcc %l1, %g0, %l0
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
    umulcc %l1, %l2, %l0
    bne test_4_pass      /* Z should be clear */
    nop
    ba fail
    nop
test_4_pass:

  /*-------------------------------------------------------------
   * Test 5: Large unsigned value in result bit 31 - N should be set
   *-------------------------------------------------------------*/
test_5:
    mov 5, TESTNUM
    set 0x80000000, %l1
    set 1, %l2
    umulcc %l1, %l2, %l0
    bneg test_5_pass     /* N should be set (bit 31 = 1) */
    nop
    ba fail
    nop
test_5_pass:

  /*-------------------------------------------------------------
   * Test 6: Result with bit 31 = 0 - N should be clear
   *-------------------------------------------------------------*/
test_6:
    mov 6, TESTNUM
    set 0x7FFFFFFF, %l1
    set 1, %l2
    umulcc %l1, %l2, %l0
    bpos test_6_pass     /* N should be clear */
    nop
    ba fail
    nop
test_6_pass:

  /*-------------------------------------------------------------
   * Test 7: Larger multiplication
   *-------------------------------------------------------------*/
  TEST_CASE( 7, %l0, 1000000, \
    set 1000, %l1; \
    set 1000, %l2; \
    umulcc %l1, %l2, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 8: UMULcc with immediate operand
   *-------------------------------------------------------------*/
  TEST_CASE( 8, %l0, 50, \
    set 10, %l1; \
    umulcc %l1, 5, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 9: Multiply by one
   *-------------------------------------------------------------*/
  TEST_CASE( 9, %l0, 99, \
    set 99, %l1; \
    set 1, %l2; \
    umulcc %l1, %l2, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 10: UMULcc result to %g0 discards result
   *-------------------------------------------------------------*/
test_10:
    mov 10, TESTNUM
    set 5, %l1
    set 7, %l2
    umulcc %l1, %l2, %g0
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
