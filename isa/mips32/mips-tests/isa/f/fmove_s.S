/* MIPS32 MOV.S, NEG.S, ABS.S instruction tests */
/* Move, Negate, Absolute value operations */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Move tests - IEEE 754 single precision
   *-------------------------------------------------------------*/

  /* mov.s: copy 1.0 */
  TEST_FP_OP1_S( 2, mov.s, 0x3f800000, 0x3f800000 )

  /* mov.s: copy -2.0 */
  TEST_FP_OP1_S( 3, mov.s, 0xc0000000, 0xc0000000 )

  /*-------------------------------------------------------------
   * Negate tests
   *-------------------------------------------------------------*/

  /* neg.s: negate 1.0 = -1.0 */
  TEST_FP_OP1_S( 4, neg.s, 0xbf800000, 0x3f800000 )

  /* neg.s: negate -2.0 = 2.0 */
  TEST_FP_OP1_S( 5, neg.s, 0x40000000, 0xc0000000 )

  /* neg.s: negate 0.0 = -0.0 */
  TEST_FP_OP1_S( 6, neg.s, 0x80000000, 0x00000000 )

  /*-------------------------------------------------------------
   * Absolute value tests
   *-------------------------------------------------------------*/

  /* abs.s: |1.0| = 1.0 */
  TEST_FP_OP1_S( 7, abs.s, 0x3f800000, 0x3f800000 )

  /* abs.s: |-2.0| = 2.0 */
  TEST_FP_OP1_S( 8, abs.s, 0x40000000, 0xc0000000 )

  /* abs.s: |-0.0| = 0.0 */
  TEST_FP_OP1_S( 9, abs.s, 0x00000000, 0x80000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
