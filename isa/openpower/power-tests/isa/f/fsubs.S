/* OpenPOWER FSUBS instruction tests */
/* fsubs frt, fra, frb - Floating Subtract Single */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic subtraction tests - IEEE 754 single precision
   *-------------------------------------------------------------*/

  /* 3.0 - 1.0 = 2.0 */
  TEST_FP_OP2_S( 2, fsubs, 0x40000000, 0x40400000, 0x3f800000 )

  /* 4.0 - 2.0 = 2.0 */
  TEST_FP_OP2_S( 3, fsubs, 0x40000000, 0x40800000, 0x40000000 )

  /* 1.0 - 1.0 = 0.0 */
  TEST_FP_OP2_S( 4, fsubs, 0x00000000, 0x3f800000, 0x3f800000 )

  /* 1.0 - 2.0 = -1.0 */
  TEST_FP_OP2_S( 5, fsubs, 0xbf800000, 0x3f800000, 0x40000000 )

  /* 10.0 - 5.0 = 5.0 */
  TEST_FP_OP2_S( 6, fsubs, 0x40a00000, 0x41200000, 0x40a00000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
