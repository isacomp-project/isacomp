/* OpenPOWER FMSUB instruction tests */
/* fmsub frt, fra, frc, frb - Floating Multiply-Subtract Double */
/* frt = (fra * frc) - frb */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic fused multiply-subtract tests
   *-------------------------------------------------------------*/

  /* 2.0 * 3.0 - 1.0 = 5.0 */
  /* 5.0 = 0x4014000000000000 */
  TEST_FP_OP3_D( 2, fmsub, 0x40140000, 0x00000000,
                 0x40000000, 0x00000000,   /* fra = 2.0 */
                 0x40080000, 0x00000000,   /* frc = 3.0 */
                 0x3ff00000, 0x00000000 )  /* frb = 1.0 */

  /* 1.0 * 1.0 - 1.0 = 0.0 */
  TEST_FP_OP3_D( 3, fmsub, 0x00000000, 0x00000000,
                 0x3ff00000, 0x00000000,
                 0x3ff00000, 0x00000000,
                 0x3ff00000, 0x00000000 )

  /* 4.0 * 2.0 - 3.0 = 5.0 */
  TEST_FP_OP3_D( 4, fmsub, 0x40140000, 0x00000000,
                 0x40100000, 0x00000000,
                 0x40000000, 0x00000000,
                 0x40080000, 0x00000000 )

  /* 2.0 * 2.0 - 5.0 = -1.0 */
  /* -1.0 = 0xbff0000000000000 */
  TEST_FP_OP3_D( 5, fmsub, 0xbff00000, 0x00000000,
                 0x40000000, 0x00000000,
                 0x40000000, 0x00000000,
                 0x40140000, 0x00000000 )

  /* 10.0 * 0.5 - 2.0 = 3.0 */
  TEST_FP_OP3_D( 6, fmsub, 0x40080000, 0x00000000,
                 0x40240000, 0x00000000,
                 0x3fe00000, 0x00000000,
                 0x40000000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
