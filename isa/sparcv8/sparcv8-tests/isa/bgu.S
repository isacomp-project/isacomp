/* SPARCv8 BGU instruction tests (branch on greater unsigned) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch taken: val1 > val2 (unsigned)
   *-------------------------------------------------------------*/

  TEST_BR_TAKEN( 2, bgu, 1, 0 )
  TEST_BR_TAKEN( 3, bgu, 2, 1 )
  TEST_BR_TAKEN( 4, bgu, 0xffffffff, 0 )
  TEST_BR_TAKEN( 5, bgu, 0x80000000, 0x7fffffff )

  /*-------------------------------------------------------------
   * Branch not taken: val1 <= val2 (unsigned)
   *-------------------------------------------------------------*/

  TEST_BR_NOT_TAKEN( 6, bgu, 0, 0 )
  TEST_BR_NOT_TAKEN( 7, bgu, 0, 1 )
  TEST_BR_NOT_TAKEN( 8, bgu, 0, 0xffffffff )
  TEST_BR_NOT_TAKEN( 9, bgu, 0x7fffffff, 0x80000000 )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
