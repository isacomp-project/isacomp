/* SPARCv8 BE instruction tests (branch on equal) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch taken: equal values
   *-------------------------------------------------------------*/

  TEST_BR_TAKEN( 2, be, 0, 0 )
  TEST_BR_TAKEN( 3, be, 1, 1 )
  TEST_BR_TAKEN( 4, be, -1, -1 )

  /*-------------------------------------------------------------
   * Branch not taken: unequal values
   *-------------------------------------------------------------*/

  TEST_BR_NOT_TAKEN( 5, be, 0, 1 )
  TEST_BR_NOT_TAKEN( 6, be, 1, 0 )
  TEST_BR_NOT_TAKEN( 7, be, -1, 1 )
  TEST_BR_NOT_TAKEN( 8, be, 1, -1 )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
