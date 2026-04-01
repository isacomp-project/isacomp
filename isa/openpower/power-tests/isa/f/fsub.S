/* OpenPOWER FSUB instruction tests */
/* fsub frt, fra, frb - Floating Subtract Double */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic arithmetic tests - IEEE 754 double precision
   * Format: TEST_FP_OP2_D(testnum, inst, res_hi, res_lo, v1_hi, v1_lo, v2_hi, v2_lo)
   *-------------------------------------------------------------*/

  /* 3.0 - 2.0 = 1.0 */
  TEST_FP_OP2_D( 2, fsub, 0x3ff00000, 0x00000000, 0x40080000, 0x00000000, 0x40000000, 0x00000000 )

  /* 7.0 - 4.0 = 3.0 */
  TEST_FP_OP2_D( 3, fsub, 0x40080000, 0x00000000, 0x401c0000, 0x00000000, 0x40100000, 0x00000000 )

  /* 1.0 - 0.5 = 0.5 */
  TEST_FP_OP2_D( 4, fsub, 0x3fe00000, 0x00000000, 0x3ff00000, 0x00000000, 0x3fe00000, 0x00000000 )

  /* 2.0 - (-1.0) = 3.0 */
  TEST_FP_OP2_D( 5, fsub, 0x40080000, 0x00000000, 0x40000000, 0x00000000, 0xbff00000, 0x00000000 )

  /* 0.0 - 0.0 = 0.0 */
  TEST_FP_OP2_D( 6, fsub, 0x00000000, 0x00000000, 0x00000000, 0x00000000, 0x00000000, 0x00000000 )

  /* 5.0 - 10.0 = -5.0 */
  TEST_FP_OP2_D( 7, fsub, 0xc0140000, 0x00000000, 0x40140000, 0x00000000, 0x40240000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
