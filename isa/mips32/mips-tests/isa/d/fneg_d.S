/* MIPS32 NEG.D instruction tests */
/* neg.d fd, fs - Floating-Point Negate Double */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic NEG.D tests - IEEE 754 double precision
   *-------------------------------------------------------------*/

  /* neg(1.0) = -1.0 */
  TEST_FP_OP1_D( 2, neg.d, 0xbff00000, 0x00000000, 0x3ff00000, 0x00000000 )

  /* neg(-1.0) = 1.0 */
  TEST_FP_OP1_D( 3, neg.d, 0x3ff00000, 0x00000000, 0xbff00000, 0x00000000 )

  /* neg(0.0) = -0.0 */
  TEST_FP_OP1_D( 4, neg.d, 0x80000000, 0x00000000, 0x00000000, 0x00000000 )

  /* neg(-0.0) = 0.0 */
  TEST_FP_OP1_D( 5, neg.d, 0x00000000, 0x00000000, 0x80000000, 0x00000000 )

  /* neg(5.0) = -5.0 */
  TEST_FP_OP1_D( 6, neg.d, 0xc0140000, 0x00000000, 0x40140000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
