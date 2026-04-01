/* MIPS32 ABS.S instruction tests */
/* abs.s fd, fs - Floating-Point Absolute Value Single */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic ABS.S tests - IEEE 754 single precision
   *-------------------------------------------------------------*/

  /* abs(1.0) = 1.0 */
  TEST_FP_OP1_S( 2, abs.s, 0x3f800000, 0x3f800000 )

  /* abs(-1.0) = 1.0 */
  TEST_FP_OP1_S( 3, abs.s, 0x3f800000, 0xbf800000 )

  /* abs(0.0) = 0.0 */
  TEST_FP_OP1_S( 4, abs.s, 0x00000000, 0x00000000 )

  /* abs(-0.0) = 0.0 */
  TEST_FP_OP1_S( 5, abs.s, 0x00000000, 0x80000000 )

  /* abs(-3.14159) = 3.14159 */
  TEST_FP_OP1_S( 6, abs.s, 0x40490fdb, 0xc0490fdb )

  /* abs(100.5) = 100.5 */
  TEST_FP_OP1_S( 7, abs.s, 0x42c90000, 0x42c90000 )

  /* abs(-100.5) = 100.5 */
  TEST_FP_OP1_S( 8, abs.s, 0x42c90000, 0xc2c90000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
