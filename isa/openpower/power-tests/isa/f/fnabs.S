/* OpenPOWER FNABS instruction tests */
/* fnabs frt, frb - Floating Negative Absolute Value */
/* Sets the sign bit (result is always negative or -0) */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic negative absolute value tests
   *-------------------------------------------------------------*/

  /* fnabs(1.0) = -1.0 */
  TEST_FP_SIGN_D( 2, fnabs, 0xbff00000, 0x00000000,
                  0x3ff00000, 0x00000000 )

  /* fnabs(-1.0) = -1.0 */
  TEST_FP_SIGN_D( 3, fnabs, 0xbff00000, 0x00000000,
                  0xbff00000, 0x00000000 )

  /* fnabs(0.0) = -0.0 */
  TEST_FP_SIGN_D( 4, fnabs, 0x80000000, 0x00000000,
                  0x00000000, 0x00000000 )

  /* fnabs(-0.0) = -0.0 */
  TEST_FP_SIGN_D( 5, fnabs, 0x80000000, 0x00000000,
                  0x80000000, 0x00000000 )

  /* fnabs(2.0) = -2.0 */
  TEST_FP_SIGN_D( 6, fnabs, 0xc0000000, 0x00000000,
                  0x40000000, 0x00000000 )

  /* fnabs(-2.0) = -2.0 */
  TEST_FP_SIGN_D( 7, fnabs, 0xc0000000, 0x00000000,
                  0xc0000000, 0x00000000 )

  /* fnabs(pi) = -pi */
  TEST_FP_SIGN_D( 8, fnabs, 0xc00921fb, 0x54442d18,
                  0x400921fb, 0x54442d18 )

  /* fnabs(-pi) = -pi */
  TEST_FP_SIGN_D( 9, fnabs, 0xc00921fb, 0x54442d18,
                  0xc00921fb, 0x54442d18 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
