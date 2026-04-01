/* SPARCv8 BL instruction tests (branch on less, signed) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch taken: val1 < val2 (signed)
   *-------------------------------------------------------------*/

  TEST_BR_TAKEN( 2, bl, 0, 1 )
  TEST_BR_TAKEN( 3, bl, -1, 0 )
  TEST_BR_TAKEN( 4, bl, -2, -1 )
  TEST_BR_TAKEN( 5, bl, 0x80000000, 0x7fffffff )

  /*-------------------------------------------------------------
   * Branch not taken: val1 >= val2 (signed)
   *-------------------------------------------------------------*/

  TEST_BR_NOT_TAKEN( 6, bl, 0, 0 )
  TEST_BR_NOT_TAKEN( 7, bl, 1, 0 )
  TEST_BR_NOT_TAKEN( 8, bl, 1, 1 )
  TEST_BR_NOT_TAKEN( 9, bl, 0, -1 )
  TEST_BR_NOT_TAKEN( 10, bl, -1, -2 )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
