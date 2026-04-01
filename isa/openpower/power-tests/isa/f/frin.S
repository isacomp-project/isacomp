/* OpenPOWER FRIN instruction tests */
/* frin frt, frb - Floating Round to Integer Nearest */
/* Rounds to nearest integer (ties away from zero) */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic rounding tests (to nearest, ties away from zero)
   *-------------------------------------------------------------*/

  /* frin(1.4) = 1.0 */
  /* 1.4 = 0x3ff6666666666666 */
  TEST_FP_ROUND_D( 2, frin, 0x3ff00000, 0x00000000,
                   0x3ff66666, 0x66666666 )

  /* frin(1.5) = 2.0 (tie goes away from zero) */
  /* 1.5 = 0x3ff8000000000000 */
  TEST_FP_ROUND_D( 3, frin, 0x40000000, 0x00000000,
                   0x3ff80000, 0x00000000 )

  /* frin(1.6) = 2.0 */
  /* 1.6 = 0x3ff999999999999a */
  TEST_FP_ROUND_D( 4, frin, 0x40000000, 0x00000000,
                   0x3ff99999, 0x9999999a )

  /* frin(2.5) = 3.0 */
  /* 2.5 = 0x4004000000000000 */
  TEST_FP_ROUND_D( 5, frin, 0x40080000, 0x00000000,
                   0x40040000, 0x00000000 )

  /* frin(-1.4) = -1.0 */
  /* -1.4 = 0xbff6666666666666 */
  TEST_FP_ROUND_D( 6, frin, 0xbff00000, 0x00000000,
                   0xbff66666, 0x66666666 )

  /* frin(-1.5) = -2.0 (tie goes away from zero = more negative) */
  TEST_FP_ROUND_D( 7, frin, 0xc0000000, 0x00000000,
                   0xbff80000, 0x00000000 )

  /* frin(0.0) = 0.0 */
  TEST_FP_ROUND_D( 8, frin, 0x00000000, 0x00000000,
                   0x00000000, 0x00000000 )

  /* frin(already integer 5.0) = 5.0 */
  TEST_FP_ROUND_D( 9, frin, 0x40140000, 0x00000000,
                   0x40140000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
