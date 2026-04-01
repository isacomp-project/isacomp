/* OpenPOWER FRIZ instruction tests */
/* friz frt, frb - Floating Round to Integer Toward Zero */
/* Truncates toward zero (like C cast to int) */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic truncation tests (toward zero)
   *-------------------------------------------------------------*/

  /* friz(1.9) = 1.0 */
  /* 1.9 = 0x3ffe666666666666 */
  TEST_FP_ROUND_D( 2, friz, 0x3ff00000, 0x00000000,
                   0x3ffe6666, 0x66666666 )

  /* friz(1.5) = 1.0 */
  TEST_FP_ROUND_D( 3, friz, 0x3ff00000, 0x00000000,
                   0x3ff80000, 0x00000000 )

  /* friz(1.1) = 1.0 */
  /* 1.1 = 0x3ff199999999999a */
  TEST_FP_ROUND_D( 4, friz, 0x3ff00000, 0x00000000,
                   0x3ff19999, 0x9999999a )

  /* friz(-1.9) = -1.0 (toward zero = less negative) */
  TEST_FP_ROUND_D( 5, friz, 0xbff00000, 0x00000000,
                   0xbffe6666, 0x66666666 )

  /* friz(-1.5) = -1.0 */
  TEST_FP_ROUND_D( 6, friz, 0xbff00000, 0x00000000,
                   0xbff80000, 0x00000000 )

  /* friz(-1.1) = -1.0 */
  TEST_FP_ROUND_D( 7, friz, 0xbff00000, 0x00000000,
                   0xbff19999, 0x9999999a )

  /* friz(0.9) = 0.0 */
  /* 0.9 = 0x3feccccccccccccd */
  TEST_FP_ROUND_D( 8, friz, 0x00000000, 0x00000000,
                   0x3feccccc, 0xcccccccd )

  /* friz(-0.9) = -0.0 (or 0.0) */
  TEST_FP_ROUND_D( 9, friz, 0x80000000, 0x00000000,
                   0xbfeccccc, 0xcccccccd )

  /* friz(already integer 5.0) = 5.0 */
  TEST_FP_ROUND_D( 10, friz, 0x40140000, 0x00000000,
                   0x40140000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
