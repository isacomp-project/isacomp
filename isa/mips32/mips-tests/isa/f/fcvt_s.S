/* MIPS32 Floating-Point Conversion instruction tests */
/* cvt.s.w, cvt.w.s - Convert between integer and single-precision */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * CVT.S.W tests - Integer to Float
   *-------------------------------------------------------------*/

  /* int 0 -> float 0.0 */
  TEST_INT_FP_CVT_S_W( 2, 0x00000000, 0 )

  /* int 1 -> float 1.0 */
  TEST_INT_FP_CVT_S_W( 3, 0x3f800000, 1 )

  /* int -1 -> float -1.0 */
  TEST_INT_FP_CVT_S_W( 4, 0xbf800000, -1 )

  /* int 100 -> float 100.0 */
  TEST_INT_FP_CVT_S_W( 5, 0x42c80000, 100 )

  /* int -100 -> float -100.0 */
  TEST_INT_FP_CVT_S_W( 6, 0xc2c80000, -100 )

  /* int 1000000 -> float 1000000.0 */
  TEST_INT_FP_CVT_S_W( 7, 0x49742400, 1000000 )

  /*-------------------------------------------------------------
   * CVT.W.S tests - Float to Integer
   *-------------------------------------------------------------*/

  /* float 0.0 -> int 0 */
  TEST_FP_CVT_W_S( 8, 0, 0x00000000 )

  /* float 1.0 -> int 1 */
  TEST_FP_CVT_W_S( 9, 1, 0x3f800000 )

  /* float -1.0 -> int -1 */
  TEST_FP_CVT_W_S( 10, -1, 0xbf800000 )

  /* float 100.0 -> int 100 */
  TEST_FP_CVT_W_S( 11, 100, 0x42c80000 )

  /* float 1.5 -> int 2 (RNE default) */
  TEST_FP_CVT_W_S( 12, 2, 0x3fc00000 )

  /* float 2.5 -> int 2 (RNE rounds to even) */
  TEST_FP_CVT_W_S( 13, 2, 0x40200000 )

  /* float 3.5 -> int 4 (RNE rounds to even) */
  TEST_FP_CVT_W_S( 14, 4, 0x40600000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
