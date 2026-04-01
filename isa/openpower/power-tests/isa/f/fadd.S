/* OpenPOWER FADD instruction tests */
/* fadd frt, fra, frb - Floating Add Double */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic arithmetic tests - IEEE 754 double precision
   * Using hex representations of double values
   * Format: TEST_FP_OP2_D(testnum, inst, res_hi, res_lo, v1_hi, v1_lo, v2_hi, v2_lo)
   *-------------------------------------------------------------*/

  /* 1.0 + 2.0 = 3.0 */
  /* 1.0 = 0x3ff0000000000000, 2.0 = 0x4000000000000000, 3.0 = 0x4008000000000000 */
  TEST_FP_OP2_D( 2, fadd, 0x40080000, 0x00000000, 0x3ff00000, 0x00000000, 0x40000000, 0x00000000 )

  /* 3.0 + 4.0 = 7.0 */
  /* 3.0 = 0x4008000000000000, 4.0 = 0x4010000000000000, 7.0 = 0x401c000000000000 */
  TEST_FP_OP2_D( 3, fadd, 0x401c0000, 0x00000000, 0x40080000, 0x00000000, 0x40100000, 0x00000000 )

  /* 0.5 + 0.5 = 1.0 */
  /* 0.5 = 0x3fe0000000000000, 1.0 = 0x3ff0000000000000 */
  TEST_FP_OP2_D( 4, fadd, 0x3ff00000, 0x00000000, 0x3fe00000, 0x00000000, 0x3fe00000, 0x00000000 )

  /* -1.0 + 2.0 = 1.0 */
  /* -1.0 = 0xbff0000000000000, 2.0 = 0x4000000000000000, 1.0 = 0x3ff0000000000000 */
  TEST_FP_OP2_D( 5, fadd, 0x3ff00000, 0x00000000, 0xbff00000, 0x00000000, 0x40000000, 0x00000000 )

  /* 0.0 + 0.0 = 0.0 */
  TEST_FP_OP2_D( 6, fadd, 0x00000000, 0x00000000, 0x00000000, 0x00000000, 0x00000000, 0x00000000 )

  /* 10.0 + (-5.0) = 5.0 */
  /* 10.0 = 0x4024000000000000, -5.0 = 0xc014000000000000, 5.0 = 0x4014000000000000 */
  TEST_FP_OP2_D( 7, fadd, 0x40140000, 0x00000000, 0x40240000, 0x00000000, 0xc0140000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
