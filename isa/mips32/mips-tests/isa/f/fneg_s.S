/* MIPS32 NEG.S instruction tests */
/* neg.s fd, fs - Floating-Point Negate Single */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic NEG.S tests - IEEE 754 single precision
   *-------------------------------------------------------------*/

  /* neg(1.0) = -1.0 */
  TEST_FP_OP1_S( 2, neg.s, 0xbf800000, 0x3f800000 )

  /* neg(-1.0) = 1.0 */
  TEST_FP_OP1_S( 3, neg.s, 0x3f800000, 0xbf800000 )

  /* neg(0.0) = -0.0 */
  TEST_FP_OP1_S( 4, neg.s, 0x80000000, 0x00000000 )

  /* neg(-0.0) = 0.0 */
  TEST_FP_OP1_S( 5, neg.s, 0x00000000, 0x80000000 )

  /* neg(3.14159) = -3.14159 */
  TEST_FP_OP1_S( 6, neg.s, 0xc0490fdb, 0x40490fdb )

  /* neg(-100.5) = 100.5 */
  TEST_FP_OP1_S( 7, neg.s, 0x42c90000, 0xc2c90000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
