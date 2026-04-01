/* SPARCv8 BGE instruction tests (branch on greater or equal, signed) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch taken: val1 >= val2 (signed)
   *-------------------------------------------------------------*/

  TEST_BR_TAKEN( 2, bge, 0, 0 )
  TEST_BR_TAKEN( 3, bge, 1, 0 )
  TEST_BR_TAKEN( 4, bge, 1, 1 )
  TEST_BR_TAKEN( 5, bge, 0, -1 )
  TEST_BR_TAKEN( 6, bge, -1, -1 )
  TEST_BR_TAKEN( 7, bge, -1, -2 )

  /*-------------------------------------------------------------
   * Branch not taken: val1 < val2 (signed)
   *-------------------------------------------------------------*/

  TEST_BR_NOT_TAKEN( 8, bge, 0, 1 )
  TEST_BR_NOT_TAKEN( 9, bge, -1, 0 )
  TEST_BR_NOT_TAKEN( 10, bge, -2, -1 )
  TEST_BR_NOT_TAKEN( 11, bge, 0x80000000, 0x7fffffff )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
