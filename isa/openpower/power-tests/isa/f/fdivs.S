/* OpenPOWER FDIVS instruction tests */
/* fdivs frt, fra, frb - Floating Divide Single */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic division tests - IEEE 754 single precision
   *-------------------------------------------------------------*/

  /* 6.0 / 2.0 = 3.0 */
  TEST_FP_OP2_S( 2, fdivs, 0x40400000, 0x40c00000, 0x40000000 )

  /* 4.0 / 2.0 = 2.0 */
  TEST_FP_OP2_S( 3, fdivs, 0x40000000, 0x40800000, 0x40000000 )

  /* 1.0 / 2.0 = 0.5 */
  TEST_FP_OP2_S( 4, fdivs, 0x3f000000, 0x3f800000, 0x40000000 )

  /* 10.0 / 5.0 = 2.0 */
  TEST_FP_OP2_S( 5, fdivs, 0x40000000, 0x41200000, 0x40a00000 )

  /* -6.0 / 2.0 = -3.0 */
  TEST_FP_OP2_S( 6, fdivs, 0xc0400000, 0xc0c00000, 0x40000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
