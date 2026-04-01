/* OpenPOWER FADDS instruction tests */
/* fadds frt, fra, frb - Floating Add Single */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic arithmetic tests - IEEE 754 single precision
   * Using hex representations of float values
   *-------------------------------------------------------------*/

  /* 1.0 + 2.0 = 3.0 */
  TEST_FP_OP2_S( 2, fadds, 0x40400000, 0x3f800000, 0x40000000 )

  /* 3.0 + 4.0 = 7.0 */
  TEST_FP_OP2_S( 3, fadds, 0x40e00000, 0x40400000, 0x40800000 )

  /* 0.5 + 0.5 = 1.0 */
  TEST_FP_OP2_S( 4, fadds, 0x3f800000, 0x3f000000, 0x3f000000 )

  /* -1.0 + 2.0 = 1.0 */
  TEST_FP_OP2_S( 5, fadds, 0x3f800000, 0xbf800000, 0x40000000 )

  /* 0.0 + 0.0 = 0.0 */
  TEST_FP_OP2_S( 6, fadds, 0x00000000, 0x00000000, 0x00000000 )

  /* 10.0 + (-5.0) = 5.0 */
  TEST_FP_OP2_S( 7, fadds, 0x40a00000, 0x41200000, 0xc0a00000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
