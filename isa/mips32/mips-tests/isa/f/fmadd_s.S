/* MIPS32 MADD.S instruction tests */
/* madd.s fd, fr, fs, ft - Floating-Point Fused Multiply-Add Single */
/* fd = fr + (fs * ft) */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic MADD.S tests - IEEE 754 single precision
   * madd.s fd, fr, fs, ft: fd = fr + (fs * ft)
   *-------------------------------------------------------------*/

  /* 1.0 + (2.0 * 3.0) = 7.0 */
  TEST_FP_OP3_S( 2, madd.s, 0x40e00000, 0x3f800000, 0x40000000, 0x40400000 )

  /* 0.0 + (2.0 * 3.0) = 6.0 */
  TEST_FP_OP3_S( 3, madd.s, 0x40c00000, 0x00000000, 0x40000000, 0x40400000 )

  /* 10.0 + (1.0 * 5.0) = 15.0 */
  TEST_FP_OP3_S( 4, madd.s, 0x41700000, 0x41200000, 0x3f800000, 0x40a00000 )

  /* -1.0 + (2.0 * 2.0) = 3.0 */
  TEST_FP_OP3_S( 5, madd.s, 0x40400000, 0xbf800000, 0x40000000, 0x40000000 )

  /* 1.0 + (-2.0 * 3.0) = -5.0 */
  TEST_FP_OP3_S( 6, madd.s, 0xc0a00000, 0x3f800000, 0xc0000000, 0x40400000 )

  /* 0.5 + (0.5 * 0.5) = 0.75 */
  TEST_FP_OP3_S( 7, madd.s, 0x3f400000, 0x3f000000, 0x3f000000, 0x3f000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
