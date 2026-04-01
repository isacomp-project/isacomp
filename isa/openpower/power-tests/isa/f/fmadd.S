/* OpenPOWER FMADD instruction tests */
/* fmadd frt, fra, frc, frb - Floating Multiply-Add Double */
/* frt = (fra * frc) + frb */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic fused multiply-add tests
   * Format: TEST_FP_OP3_D(testnum, inst, res_hi, res_lo,
   *                       fra_hi, fra_lo, frc_hi, frc_lo, frb_hi, frb_lo)
   *-------------------------------------------------------------*/

  /* 2.0 * 3.0 + 1.0 = 7.0 */
  /* 2.0 = 0x4000000000000000, 3.0 = 0x4008000000000000 */
  /* 1.0 = 0x3ff0000000000000, 7.0 = 0x401c000000000000 */
  TEST_FP_OP3_D( 2, fmadd, 0x401c0000, 0x00000000,
                 0x40000000, 0x00000000,   /* fra = 2.0 */
                 0x40080000, 0x00000000,   /* frc = 3.0 */
                 0x3ff00000, 0x00000000 )  /* frb = 1.0 */

  /* 1.0 * 1.0 + 1.0 = 2.0 */
  TEST_FP_OP3_D( 3, fmadd, 0x40000000, 0x00000000,
                 0x3ff00000, 0x00000000,
                 0x3ff00000, 0x00000000,
                 0x3ff00000, 0x00000000 )

  /* 0.5 * 4.0 + 0.0 = 2.0 */
  /* 0.5 = 0x3fe0000000000000, 4.0 = 0x4010000000000000 */
  TEST_FP_OP3_D( 4, fmadd, 0x40000000, 0x00000000,
                 0x3fe00000, 0x00000000,
                 0x40100000, 0x00000000,
                 0x00000000, 0x00000000 )

  /* 2.0 * 2.0 + (-3.0) = 1.0 */
  /* -3.0 = 0xc008000000000000 */
  TEST_FP_OP3_D( 5, fmadd, 0x3ff00000, 0x00000000,
                 0x40000000, 0x00000000,
                 0x40000000, 0x00000000,
                 0xc0080000, 0x00000000 )

  /* (-2.0) * 3.0 + 10.0 = 4.0 */
  /* -2.0 = 0xc000000000000000, 10.0 = 0x4024000000000000, 4.0 = 0x4010000000000000 */
  TEST_FP_OP3_D( 6, fmadd, 0x40100000, 0x00000000,
                 0xc0000000, 0x00000000,
                 0x40080000, 0x00000000,
                 0x40240000, 0x00000000 )

  /* 0.0 * anything + 5.0 = 5.0 */
  TEST_FP_OP3_D( 7, fmadd, 0x40140000, 0x00000000,
                 0x00000000, 0x00000000,
                 0x40080000, 0x00000000,
                 0x40140000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
