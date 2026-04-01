/* SPARCv8 BNE instruction tests (branch on not equal) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch taken: unequal values
   *-------------------------------------------------------------*/

  TEST_BR_TAKEN( 2, bne, 0, 1 )
  TEST_BR_TAKEN( 3, bne, 1, 0 )
  TEST_BR_TAKEN( 4, bne, -1, 1 )
  TEST_BR_TAKEN( 5, bne, 1, -1 )

  /*-------------------------------------------------------------
   * Branch not taken: equal values
   *-------------------------------------------------------------*/

  TEST_BR_NOT_TAKEN( 6, bne, 0, 0 )
  TEST_BR_NOT_TAKEN( 7, bne, 1, 1 )
  TEST_BR_NOT_TAKEN( 8, bne, -1, -1 )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
