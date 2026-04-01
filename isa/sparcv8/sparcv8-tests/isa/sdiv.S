/* SPARCv8 SDIV instruction tests (signed divide) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * SDIV: Signed divide (Y:rs1) / rs2 -> rd
   * Y register holds high 32 bits of 64-bit dividend
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: Simple positive division (Y=0)
   *-------------------------------------------------------------*/

  TEST_CASE( 2, %l0, 3, \
    wr %g0, 0, %y; \
    nop; nop; nop; \
    set 15, %l1; \
    set 5, %l2; \
    sdiv %l1, %l2, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 3: Division by 1
   *-------------------------------------------------------------*/

  TEST_CASE( 3, %l0, 42, \
    wr %g0, 0, %y; \
    nop; nop; nop; \
    set 42, %l1; \
    set 1, %l2; \
    sdiv %l1, %l2, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 4: Negative dividend
   *-------------------------------------------------------------*/

  TEST_CASE( 4, %l0, -3, \
    wr %g0, -1, %y; /* sign extend for negative dividend */ \
    nop; nop; nop; \
    set -15, %l1; \
    set 5, %l2; \
    sdiv %l1, %l2, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 5: Negative divisor
   *-------------------------------------------------------------*/

  TEST_CASE( 5, %l0, -3, \
    wr %g0, 0, %y; \
    nop; nop; nop; \
    set 15, %l1; \
    set -5, %l2; \
    sdiv %l1, %l2, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 6: Both negative
   *-------------------------------------------------------------*/

  TEST_CASE( 6, %l0, 3, \
    wr %g0, -1, %y; \
    nop; nop; nop; \
    set -15, %l1; \
    set -5, %l2; \
    sdiv %l1, %l2, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 7: Division with remainder (truncates toward zero)
   *-------------------------------------------------------------*/

  TEST_CASE( 7, %l0, 3, \
    wr %g0, 0, %y; \
    nop; nop; nop; \
    set 17, %l1; \
    set 5, %l2; \
    sdiv %l1, %l2, %l0; \
    /* 17 / 5 = 3 remainder 2 */ \
  )

  /*-------------------------------------------------------------
   * Test 8: SDIV with immediate operand
   *-------------------------------------------------------------*/

  TEST_CASE( 8, %l0, 5, \
    wr %g0, 0, %y; \
    nop; nop; nop; \
    set 50, %l1; \
    sdiv %l1, 10, %l0; \
  )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
