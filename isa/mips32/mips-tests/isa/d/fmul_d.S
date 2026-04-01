/* MIPS32 MUL.D instruction tests */
/* mul.d fd, fs, ft - Floating-Point Multiply Double */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic multiplication tests - IEEE 754 double precision
   *-------------------------------------------------------------*/

  /* 2.0 * 3.0 = 6.0 */
  /* 6.0 = 0x40180000_00000000 */
  TEST_FP_OP2_D( 2, mul.d, 0x40180000, 0x00000000, 0x40000000, 0x00000000, 0x40080000, 0x00000000 )

  /* 1.0 * 1.0 = 1.0 */
  TEST_FP_OP2_D( 3, mul.d, 0x3ff00000, 0x00000000, 0x3ff00000, 0x00000000, 0x3ff00000, 0x00000000 )

  /* 0.5 * 2.0 = 1.0 */
  TEST_FP_OP2_D( 4, mul.d, 0x3ff00000, 0x00000000, 0x3fe00000, 0x00000000, 0x40000000, 0x00000000 )

  /* -2.0 * 3.0 = -6.0 */
  TEST_FP_OP2_D( 5, mul.d, 0xc0180000, 0x00000000, 0xc0000000, 0x00000000, 0x40080000, 0x00000000 )

  /* 0.0 * 5.0 = 0.0 */
  TEST_FP_OP2_D( 6, mul.d, 0x00000000, 0x00000000, 0x00000000, 0x00000000, 0x40140000, 0x00000000 )

  /* -1.0 * -1.0 = 1.0 */
  TEST_FP_OP2_D( 7, mul.d, 0x3ff00000, 0x00000000, 0xbff00000, 0x00000000, 0xbff00000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
