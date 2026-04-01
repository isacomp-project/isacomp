/* SPARCv8 UDIV instruction tests (unsigned divide) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * UDIV: Unsigned divide (Y:rs1) / rs2 -> rd
   * Y register holds high 32 bits of 64-bit dividend
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: Simple division (Y=0)
   *-------------------------------------------------------------*/

  TEST_CASE( 2, %l0, 3, \
    wr %g0, 0, %y; \
    nop; nop; nop; \
    set 15, %l1; \
    set 5, %l2; \
    udiv %l1, %l2, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 3: Division by 1
   *-------------------------------------------------------------*/

  TEST_CASE( 3, %l0, 42, \
    wr %g0, 0, %y; \
    nop; nop; nop; \
    set 42, %l1; \
    set 1, %l2; \
    udiv %l1, %l2, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 4: Large unsigned dividend (treated as positive)
   *-------------------------------------------------------------*/

  TEST_CASE( 4, %l0, 0x55555555, \
    wr %g0, 0, %y; \
    nop; nop; nop; \
    set 0xffffffff, %l1; \
    set 3, %l2; \
    udiv %l1, %l2, %l0; \
    /* 0xffffffff / 3 = 0x55555555 */ \
  )

  /*-------------------------------------------------------------
   * Test 5: Division with remainder (truncates)
   *-------------------------------------------------------------*/

  TEST_CASE( 5, %l0, 3, \
    wr %g0, 0, %y; \
    nop; nop; nop; \
    set 17, %l1; \
    set 5, %l2; \
    udiv %l1, %l2, %l0; \
    /* 17 / 5 = 3 remainder 2 */ \
  )

  /*-------------------------------------------------------------
   * Test 6: UDIV with immediate operand
   *-------------------------------------------------------------*/

  TEST_CASE( 6, %l0, 5, \
    wr %g0, 0, %y; \
    nop; nop; nop; \
    set 50, %l1; \
    udiv %l1, 10, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 7: 64-bit dividend using Y register
   *-------------------------------------------------------------*/

  TEST_CASE( 7, %l0, 0x10000, \
    wr %g0, 1, %y; \
    nop; nop; nop; \
    set 0, %l1; \
    set 0x10000, %l2; \
    udiv %l1, %l2, %l0; \
    /* (1 << 32) / 0x10000 = 0x10000 */ \
  )

  /*-------------------------------------------------------------
   * Test 8: Power of 2 division
   *-------------------------------------------------------------*/

  TEST_CASE( 8, %l0, 64, \
    wr %g0, 0, %y; \
    nop; nop; nop; \
    set 256, %l1; \
    set 4, %l2; \
    udiv %l1, %l2, %l0; \
  )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
