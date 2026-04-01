/* OpenPOWER FABS instruction tests */
/* fabs frt, frb - Floating Absolute Value */
/* Clears the sign bit */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic absolute value tests
   *-------------------------------------------------------------*/

  /* fabs(1.0) = 1.0 */
  TEST_FP_SIGN_D( 2, fabs, 0x3ff00000, 0x00000000,
                  0x3ff00000, 0x00000000 )

  /* fabs(-1.0) = 1.0 */
  TEST_FP_SIGN_D( 3, fabs, 0x3ff00000, 0x00000000,
                  0xbff00000, 0x00000000 )

  /* fabs(0.0) = 0.0 */
  TEST_FP_SIGN_D( 4, fabs, 0x00000000, 0x00000000,
                  0x00000000, 0x00000000 )

  /* fabs(-0.0) = 0.0 */
  TEST_FP_SIGN_D( 5, fabs, 0x00000000, 0x00000000,
                  0x80000000, 0x00000000 )

  /* fabs(-3.14159...) = 3.14159... */
  /* pi = 0x400921fb54442d18, -pi = 0xc00921fb54442d18 */
  TEST_FP_SIGN_D( 6, fabs, 0x400921fb, 0x54442d18,
                  0xc00921fb, 0x54442d18 )

  /* fabs(large positive) = same */
  /* 1e100 = 0x54b249ad2594c37d */
  TEST_FP_SIGN_D( 7, fabs, 0x54b249ad, 0x2594c37d,
                  0x54b249ad, 0x2594c37d )

  /* fabs(large negative) = positive */
  TEST_FP_SIGN_D( 8, fabs, 0x54b249ad, 0x2594c37d,
                  0xd4b249ad, 0x2594c37d )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
