/* MIPS32 MSUB.S instruction tests */
/* msub.s fd, fr, fs, ft - Floating-Point Fused Multiply-Subtract Single */
/* fd = (fs * ft) - fr */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic MSUB.S tests - IEEE 754 single precision
   * msub.s fd, fr, fs, ft: fd = (fs * ft) - fr
   *-------------------------------------------------------------*/

  /* (2.0 * 3.0) - 1.0 = 5.0 */
  TEST_FP_OP3_S( 2, msub.s, 0x40a00000, 0x3f800000, 0x40000000, 0x40400000 )

  /* (2.0 * 3.0) - 0.0 = 6.0 */
  TEST_FP_OP3_S( 3, msub.s, 0x40c00000, 0x00000000, 0x40000000, 0x40400000 )

  /* (1.0 * 5.0) - 10.0 = -5.0 */
  TEST_FP_OP3_S( 4, msub.s, 0xc0a00000, 0x41200000, 0x3f800000, 0x40a00000 )

  /* (2.0 * 2.0) - (-1.0) = 5.0 */
  TEST_FP_OP3_S( 5, msub.s, 0x40a00000, 0xbf800000, 0x40000000, 0x40000000 )

  /* (4.0 * 3.0) - 2.0 = 10.0 */
  TEST_FP_OP3_S( 6, msub.s, 0x41200000, 0x40000000, 0x40800000, 0x40400000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
