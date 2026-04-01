/* OpenPOWER FMR, FNEG, FABS instruction tests */
/* Move, Negate, Absolute value operations */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Move tests - IEEE 754 single precision
   *-------------------------------------------------------------*/

  /* fmr: copy 1.0 */
  TEST_FP_MR( 2, 0x3f800000, 0x3f800000 )

  /* fmr: copy -2.0 */
  TEST_FP_MR( 3, 0xc0000000, 0xc0000000 )

  /*-------------------------------------------------------------
   * Negate tests
   *-------------------------------------------------------------*/

  /* fneg: negate 1.0 = -1.0 */
  TEST_FP_OP1_S( 4, fneg, 0xbf800000, 0x3f800000 )

  /* fneg: negate -2.0 = 2.0 */
  TEST_FP_OP1_S( 5, fneg, 0x40000000, 0xc0000000 )

  /* fneg: negate 0.0 = -0.0 */
  TEST_FP_OP1_S( 6, fneg, 0x80000000, 0x00000000 )

  /*-------------------------------------------------------------
   * Absolute value tests
   *-------------------------------------------------------------*/

  /* fabs: |1.0| = 1.0 */
  TEST_FP_OP1_S( 7, fabs, 0x3f800000, 0x3f800000 )

  /* fabs: |-2.0| = 2.0 */
  TEST_FP_OP1_S( 8, fabs, 0x40000000, 0xc0000000 )

  /* fabs: |-0.0| = 0.0 */
  TEST_FP_OP1_S( 9, fabs, 0x00000000, 0x80000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
