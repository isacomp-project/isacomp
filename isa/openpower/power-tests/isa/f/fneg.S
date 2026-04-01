/* OpenPOWER FNEG instruction tests */
/* fneg frt, frb - Floating Negate */
/* Inverts the sign bit */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic negation tests
   *-------------------------------------------------------------*/

  /* fneg(1.0) = -1.0 */
  TEST_FP_SIGN_D( 2, fneg, 0xbff00000, 0x00000000,
                  0x3ff00000, 0x00000000 )

  /* fneg(-1.0) = 1.0 */
  TEST_FP_SIGN_D( 3, fneg, 0x3ff00000, 0x00000000,
                  0xbff00000, 0x00000000 )

  /* fneg(0.0) = -0.0 */
  TEST_FP_SIGN_D( 4, fneg, 0x80000000, 0x00000000,
                  0x00000000, 0x00000000 )

  /* fneg(-0.0) = 0.0 */
  TEST_FP_SIGN_D( 5, fneg, 0x00000000, 0x00000000,
                  0x80000000, 0x00000000 )

  /* fneg(2.0) = -2.0 */
  TEST_FP_SIGN_D( 6, fneg, 0xc0000000, 0x00000000,
                  0x40000000, 0x00000000 )

  /* fneg(-2.0) = 2.0 */
  TEST_FP_SIGN_D( 7, fneg, 0x40000000, 0x00000000,
                  0xc0000000, 0x00000000 )

  /* fneg(pi) = -pi */
  TEST_FP_SIGN_D( 8, fneg, 0xc00921fb, 0x54442d18,
                  0x400921fb, 0x54442d18 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
