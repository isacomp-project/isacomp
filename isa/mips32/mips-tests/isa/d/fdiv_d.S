/* MIPS32 DIV.D instruction tests */
/* div.d fd, fs, ft - Floating-Point Divide Double */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic division tests - IEEE 754 double precision
   *-------------------------------------------------------------*/

  /* 6.0 / 2.0 = 3.0 */
  TEST_FP_OP2_D( 2, div.d, 0x40080000, 0x00000000, 0x40180000, 0x00000000, 0x40000000, 0x00000000 )

  /* 1.0 / 1.0 = 1.0 */
  TEST_FP_OP2_D( 3, div.d, 0x3ff00000, 0x00000000, 0x3ff00000, 0x00000000, 0x3ff00000, 0x00000000 )

  /* 1.0 / 2.0 = 0.5 */
  TEST_FP_OP2_D( 4, div.d, 0x3fe00000, 0x00000000, 0x3ff00000, 0x00000000, 0x40000000, 0x00000000 )

  /* -6.0 / 2.0 = -3.0 */
  TEST_FP_OP2_D( 5, div.d, 0xc0080000, 0x00000000, 0xc0180000, 0x00000000, 0x40000000, 0x00000000 )

  /* 10.0 / 5.0 = 2.0 */
  TEST_FP_OP2_D( 6, div.d, 0x40000000, 0x00000000, 0x40240000, 0x00000000, 0x40140000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
