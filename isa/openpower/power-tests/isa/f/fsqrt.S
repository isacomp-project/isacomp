/* OpenPOWER FSQRT instruction tests */
/* fsqrt frt, frb - Floating Square Root Double */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic arithmetic tests - IEEE 754 double precision
   * Format: TEST_FP_OP1_D(testnum, inst, res_hi, res_lo, v1_hi, v1_lo)
   *-------------------------------------------------------------*/

  /* sqrt(4.0) = 2.0 */
  /* 4.0 = 0x4010000000000000, 2.0 = 0x4000000000000000 */
  TEST_FP_OP1_D( 2, fsqrt, 0x40000000, 0x00000000, 0x40100000, 0x00000000 )

  /* sqrt(9.0) = 3.0 */
  /* 9.0 = 0x4022000000000000, 3.0 = 0x4008000000000000 */
  TEST_FP_OP1_D( 3, fsqrt, 0x40080000, 0x00000000, 0x40220000, 0x00000000 )

  /* sqrt(1.0) = 1.0 */
  TEST_FP_OP1_D( 4, fsqrt, 0x3ff00000, 0x00000000, 0x3ff00000, 0x00000000 )

  /* sqrt(0.0) = 0.0 */
  TEST_FP_OP1_D( 5, fsqrt, 0x00000000, 0x00000000, 0x00000000, 0x00000000 )

  /* sqrt(16.0) = 4.0 */
  /* 16.0 = 0x4030000000000000, 4.0 = 0x4010000000000000 */
  TEST_FP_OP1_D( 6, fsqrt, 0x40100000, 0x00000000, 0x40300000, 0x00000000 )

  /* sqrt(25.0) = 5.0 */
  /* 25.0 = 0x4039000000000000, 5.0 = 0x4014000000000000 */
  TEST_FP_OP1_D( 7, fsqrt, 0x40140000, 0x00000000, 0x40390000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
