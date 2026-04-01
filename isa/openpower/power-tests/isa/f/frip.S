/* OpenPOWER FRIP instruction tests */
/* frip frt, frb - Floating Round to Integer Toward +Infinity */
/* Rounds up (ceiling function) */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic ceiling tests (toward +infinity)
   *-------------------------------------------------------------*/

  /* frip(1.1) = 2.0 */
  /* 1.1 = 0x3ff199999999999a */
  TEST_FP_ROUND_D( 2, frip, 0x40000000, 0x00000000,
                   0x3ff19999, 0x9999999a )

  /* frip(1.5) = 2.0 */
  TEST_FP_ROUND_D( 3, frip, 0x40000000, 0x00000000,
                   0x3ff80000, 0x00000000 )

  /* frip(1.9) = 2.0 */
  TEST_FP_ROUND_D( 4, frip, 0x40000000, 0x00000000,
                   0x3ffe6666, 0x66666666 )

  /* frip(-1.1) = -1.0 (toward +inf = less negative) */
  TEST_FP_ROUND_D( 5, frip, 0xbff00000, 0x00000000,
                   0xbff19999, 0x9999999a )

  /* frip(-1.5) = -1.0 */
  TEST_FP_ROUND_D( 6, frip, 0xbff00000, 0x00000000,
                   0xbff80000, 0x00000000 )

  /* frip(-1.9) = -1.0 */
  TEST_FP_ROUND_D( 7, frip, 0xbff00000, 0x00000000,
                   0xbffe6666, 0x66666666 )

  /* frip(0.1) = 1.0 */
  /* 0.1 = 0x3fb999999999999a */
  TEST_FP_ROUND_D( 8, frip, 0x3ff00000, 0x00000000,
                   0x3fb99999, 0x9999999a )

  /* frip(-0.1) = -0.0 (or 0.0) */
  TEST_FP_ROUND_D( 9, frip, 0x80000000, 0x00000000,
                   0xbfb99999, 0x9999999a )

  /* frip(already integer 5.0) = 5.0 */
  TEST_FP_ROUND_D( 10, frip, 0x40140000, 0x00000000,
                   0x40140000, 0x00000000 )

  /* frip(0.0) = 0.0 */
  TEST_FP_ROUND_D( 11, frip, 0x00000000, 0x00000000,
                   0x00000000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
