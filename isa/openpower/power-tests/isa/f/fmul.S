/* OpenPOWER FMUL instruction tests */
/* fmul frt, fra, frc - Floating Multiply Double */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic arithmetic tests - IEEE 754 double precision
   * Format: TEST_FP_OP2_D(testnum, inst, res_hi, res_lo, v1_hi, v1_lo, v2_hi, v2_lo)
   *-------------------------------------------------------------*/

  /* 2.0 * 3.0 = 6.0 */
  /* 2.0 = 0x4000000000000000, 3.0 = 0x4008000000000000, 6.0 = 0x4018000000000000 */
  TEST_FP_OP2_D( 2, fmul, 0x40180000, 0x00000000, 0x40000000, 0x00000000, 0x40080000, 0x00000000 )

  /* 4.0 * 5.0 = 20.0 */
  /* 4.0 = 0x4010000000000000, 5.0 = 0x4014000000000000, 20.0 = 0x4034000000000000 */
  TEST_FP_OP2_D( 3, fmul, 0x40340000, 0x00000000, 0x40100000, 0x00000000, 0x40140000, 0x00000000 )

  /* 0.5 * 2.0 = 1.0 */
  TEST_FP_OP2_D( 4, fmul, 0x3ff00000, 0x00000000, 0x3fe00000, 0x00000000, 0x40000000, 0x00000000 )

  /* -1.0 * 2.0 = -2.0 */
  /* -2.0 = 0xc000000000000000 */
  TEST_FP_OP2_D( 5, fmul, 0xc0000000, 0x00000000, 0xbff00000, 0x00000000, 0x40000000, 0x00000000 )

  /* 0.0 * 5.0 = 0.0 */
  TEST_FP_OP2_D( 6, fmul, 0x00000000, 0x00000000, 0x00000000, 0x00000000, 0x40140000, 0x00000000 )

  /* 1.0 * 1.0 = 1.0 */
  TEST_FP_OP2_D( 7, fmul, 0x3ff00000, 0x00000000, 0x3ff00000, 0x00000000, 0x3ff00000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
