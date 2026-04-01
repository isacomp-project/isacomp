/* MIPS32 ADD.D instruction tests */
/* add.d fd, fs, ft - Floating-Point Add Double */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic arithmetic tests - IEEE 754 double precision
   * Using hex representations of double values (hi, lo)
   *-------------------------------------------------------------*/

  /* 1.0 + 2.0 = 3.0 */
  /* 1.0 = 0x3FF00000_00000000 */
  /* 2.0 = 0x40000000_00000000 */
  /* 3.0 = 0x40080000_00000000 */
  TEST_FP_OP2_D( 2, add.d, 0x40080000, 0x00000000, 0x3ff00000, 0x00000000, 0x40000000, 0x00000000 )

  /* 0.5 + 0.5 = 1.0 */
  /* 0.5 = 0x3FE00000_00000000 */
  TEST_FP_OP2_D( 3, add.d, 0x3ff00000, 0x00000000, 0x3fe00000, 0x00000000, 0x3fe00000, 0x00000000 )

  /* -1.0 + 2.0 = 1.0 */
  /* -1.0 = 0xBFF00000_00000000 */
  TEST_FP_OP2_D( 4, add.d, 0x3ff00000, 0x00000000, 0xbff00000, 0x00000000, 0x40000000, 0x00000000 )

  /* 0.0 + 0.0 = 0.0 */
  TEST_FP_OP2_D( 5, add.d, 0x00000000, 0x00000000, 0x00000000, 0x00000000, 0x00000000, 0x00000000 )

  /* 10.0 + (-5.0) = 5.0 */
  /* 10.0 = 0x40240000_00000000 */
  /* -5.0 = 0xC0140000_00000000 */
  /* 5.0  = 0x40140000_00000000 */
  TEST_FP_OP2_D( 6, add.d, 0x40140000, 0x00000000, 0x40240000, 0x00000000, 0xc0140000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
