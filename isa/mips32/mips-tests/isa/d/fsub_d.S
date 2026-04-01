/* MIPS32 SUB.D instruction tests */
/* sub.d fd, fs, ft - Floating-Point Subtract Double */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic arithmetic tests - IEEE 754 double precision
   *-------------------------------------------------------------*/

  /* 3.0 - 2.0 = 1.0 */
  TEST_FP_OP2_D( 2, sub.d, 0x3ff00000, 0x00000000, 0x40080000, 0x00000000, 0x40000000, 0x00000000 )

  /* 1.0 - 0.5 = 0.5 */
  TEST_FP_OP2_D( 3, sub.d, 0x3fe00000, 0x00000000, 0x3ff00000, 0x00000000, 0x3fe00000, 0x00000000 )

  /* 0.0 - 1.0 = -1.0 */
  TEST_FP_OP2_D( 4, sub.d, 0xbff00000, 0x00000000, 0x00000000, 0x00000000, 0x3ff00000, 0x00000000 )

  /* -1.0 - (-2.0) = 1.0 */
  TEST_FP_OP2_D( 5, sub.d, 0x3ff00000, 0x00000000, 0xbff00000, 0x00000000, 0xc0000000, 0x00000000 )

  /* 5.0 - 5.0 = 0.0 */
  TEST_FP_OP2_D( 6, sub.d, 0x00000000, 0x00000000, 0x40140000, 0x00000000, 0x40140000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
