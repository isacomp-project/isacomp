/* OpenPOWER FRIM instruction tests */
/* frim frt, frb - Floating Round to Integer Toward -Infinity */
/* Rounds down (floor function) */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic floor tests (toward -infinity)
   *-------------------------------------------------------------*/

  /* frim(1.1) = 1.0 */
  /* 1.1 = 0x3ff199999999999a */
  TEST_FP_ROUND_D( 2, frim, 0x3ff00000, 0x00000000,
                   0x3ff19999, 0x9999999a )

  /* frim(1.5) = 1.0 */
  TEST_FP_ROUND_D( 3, frim, 0x3ff00000, 0x00000000,
                   0x3ff80000, 0x00000000 )

  /* frim(1.9) = 1.0 */
  TEST_FP_ROUND_D( 4, frim, 0x3ff00000, 0x00000000,
                   0x3ffe6666, 0x66666666 )

  /* frim(-1.1) = -2.0 (toward -inf = more negative) */
  TEST_FP_ROUND_D( 5, frim, 0xc0000000, 0x00000000,
                   0xbff19999, 0x9999999a )

  /* frim(-1.5) = -2.0 */
  TEST_FP_ROUND_D( 6, frim, 0xc0000000, 0x00000000,
                   0xbff80000, 0x00000000 )

  /* frim(-1.9) = -2.0 */
  TEST_FP_ROUND_D( 7, frim, 0xc0000000, 0x00000000,
                   0xbffe6666, 0x66666666 )

  /* frim(0.9) = 0.0 */
  /* 0.9 = 0x3feccccccccccccd */
  TEST_FP_ROUND_D( 8, frim, 0x00000000, 0x00000000,
                   0x3feccccc, 0xcccccccd )

  /* frim(-0.1) = -1.0 */
  TEST_FP_ROUND_D( 9, frim, 0xbff00000, 0x00000000,
                   0xbfb99999, 0x9999999a )

  /* frim(already integer 5.0) = 5.0 */
  TEST_FP_ROUND_D( 10, frim, 0x40140000, 0x00000000,
                   0x40140000, 0x00000000 )

  /* frim(0.0) = 0.0 */
  TEST_FP_ROUND_D( 11, frim, 0x00000000, 0x00000000,
                   0x00000000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
