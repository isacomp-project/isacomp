/* OpenPOWER FNMSUB instruction tests */
/* fnmsub frt, fra, frc, frb - Floating Negative Multiply-Subtract Double */
/* frt = -((fra * frc) - frb) */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic negative fused multiply-subtract tests
   *-------------------------------------------------------------*/

  /* -((2.0 * 3.0) - 1.0) = -(6 - 1) = -5.0 */
  /* -5.0 = 0xc014000000000000 */
  TEST_FP_OP3_D( 2, fnmsub, 0xc0140000, 0x00000000,
                 0x40000000, 0x00000000,   /* fra = 2.0 */
                 0x40080000, 0x00000000,   /* frc = 3.0 */
                 0x3ff00000, 0x00000000 )  /* frb = 1.0 */

  /* -((1.0 * 1.0) - 1.0) = -(0) = -0.0 or 0.0 */
  /* Note: Result may be +0.0 or -0.0 depending on implementation */
  TEST_FP_OP3_D( 3, fnmsub, 0x80000000, 0x00000000,
                 0x3ff00000, 0x00000000,
                 0x3ff00000, 0x00000000,
                 0x3ff00000, 0x00000000 )

  /* -((2.0 * 2.0) - 5.0) = -(4 - 5) = -(-1) = 1.0 */
  TEST_FP_OP3_D( 4, fnmsub, 0x3ff00000, 0x00000000,
                 0x40000000, 0x00000000,
                 0x40000000, 0x00000000,
                 0x40140000, 0x00000000 )

  /* -((3.0 * 3.0) - 4.0) = -(9 - 4) = -5.0 */
  TEST_FP_OP3_D( 5, fnmsub, 0xc0140000, 0x00000000,
                 0x40080000, 0x00000000,
                 0x40080000, 0x00000000,
                 0x40100000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
