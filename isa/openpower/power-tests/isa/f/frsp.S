/* OpenPOWER FRSP instruction tests */
/* frsp frt, frb - Floating Round to Single-Precision */
/* Rounds double-precision value to single-precision, result in DP format */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic rounding tests
   * Result is a double-precision value that is exactly representable
   * as single-precision
   *-------------------------------------------------------------*/

  /* frsp(1.0) = 1.0 (exact) */
  TEST_FP_OP1_D( 2, frsp, 0x3ff00000, 0x00000000,
                 0x3ff00000, 0x00000000 )

  /* frsp(2.0) = 2.0 (exact) */
  TEST_FP_OP1_D( 3, frsp, 0x40000000, 0x00000000,
                 0x40000000, 0x00000000 )

  /* frsp(0.0) = 0.0 */
  TEST_FP_OP1_D( 4, frsp, 0x00000000, 0x00000000,
                 0x00000000, 0x00000000 )

  /* frsp(-1.0) = -1.0 (exact) */
  TEST_FP_OP1_D( 5, frsp, 0xbff00000, 0x00000000,
                 0xbff00000, 0x00000000 )

  /* frsp(0.5) = 0.5 (exact) */
  TEST_FP_OP1_D( 6, frsp, 0x3fe00000, 0x00000000,
                 0x3fe00000, 0x00000000 )

  /* frsp(3.14159...) - rounds to SP precision */
  /* pi in DP = 0x400921fb54442d18 */
  /* pi rounded to SP then stored as DP = 0x400921fb60000000 */
  TEST_FP_OP1_D( 7, frsp, 0x400921fb, 0x60000000,
                 0x400921fb, 0x54442d18 )

  /* frsp(-0.0) = -0.0 */
  TEST_FP_OP1_D( 8, frsp, 0x80000000, 0x00000000,
                 0x80000000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
