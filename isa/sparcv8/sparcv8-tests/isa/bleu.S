/* SPARCv8 BLEU instruction tests (branch on less or equal unsigned) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch taken: val1 <= val2 (unsigned)
   *-------------------------------------------------------------*/

  TEST_BR_TAKEN( 2, bleu, 0, 0 )
  TEST_BR_TAKEN( 3, bleu, 0, 1 )
  TEST_BR_TAKEN( 4, bleu, 1, 1 )
  TEST_BR_TAKEN( 5, bleu, 0, 0xffffffff )
  TEST_BR_TAKEN( 6, bleu, 0x7fffffff, 0x80000000 )

  /*-------------------------------------------------------------
   * Branch not taken: val1 > val2 (unsigned)
   *-------------------------------------------------------------*/

  TEST_BR_NOT_TAKEN( 7, bleu, 1, 0 )
  TEST_BR_NOT_TAKEN( 8, bleu, 0xffffffff, 0 )
  TEST_BR_NOT_TAKEN( 9, bleu, 0x80000000, 0x7fffffff )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
