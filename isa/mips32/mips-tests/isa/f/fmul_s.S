/* MIPS32 MUL.S instruction tests */
/* mul.s fd, fs, ft - Floating-Point Multiply Single */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic multiplication tests - IEEE 754 single precision
   *-------------------------------------------------------------*/

  /* 2.0 * 3.0 = 6.0 */
  TEST_FP_OP2_S( 2, mul.s, 0x40c00000, 0x40000000, 0x40400000 )

  /* 1.0 * 1.0 = 1.0 */
  TEST_FP_OP2_S( 3, mul.s, 0x3f800000, 0x3f800000, 0x3f800000 )

  /* 2.0 * 0.5 = 1.0 */
  TEST_FP_OP2_S( 4, mul.s, 0x3f800000, 0x40000000, 0x3f000000 )

  /* 4.0 * 4.0 = 16.0 */
  TEST_FP_OP2_S( 5, mul.s, 0x41800000, 0x40800000, 0x40800000 )

  /* -2.0 * 3.0 = -6.0 */
  TEST_FP_OP2_S( 6, mul.s, 0xc0c00000, 0xc0000000, 0x40400000 )

  /* -2.0 * -2.0 = 4.0 */
  TEST_FP_OP2_S( 7, mul.s, 0x40800000, 0xc0000000, 0xc0000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
