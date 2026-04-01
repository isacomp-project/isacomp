/* SPARCv8 BG instruction tests (branch on greater, signed) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch taken: val1 > val2 (signed)
   *-------------------------------------------------------------*/

  TEST_BR_TAKEN( 2, bg, 1, 0 )
  TEST_BR_TAKEN( 3, bg, 2, 1 )
  TEST_BR_TAKEN( 4, bg, 0, -1 )
  TEST_BR_TAKEN( 5, bg, -1, -2 )
  TEST_BR_TAKEN( 6, bg, 0x7fffffff, 0x7ffffffe )

  /*-------------------------------------------------------------
   * Branch not taken: val1 <= val2 (signed)
   *-------------------------------------------------------------*/

  TEST_BR_NOT_TAKEN( 7, bg, 0, 0 )
  TEST_BR_NOT_TAKEN( 8, bg, 0, 1 )
  TEST_BR_NOT_TAKEN( 9, bg, -1, 0 )
  TEST_BR_NOT_TAKEN( 10, bg, -2, -1 )
  TEST_BR_NOT_TAKEN( 11, bg, 0x80000000, 0x7fffffff )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
