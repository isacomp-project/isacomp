/* MIPS32 Floating-Point Compare instruction tests */
/* c.eq.s, c.lt.s, c.le.s - Compare Single */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * C.EQ.S tests - Compare Equal
   *-------------------------------------------------------------*/

  /* 1.0 == 1.0 -> true */
  TEST_FP_CMP_S( 2, c.eq.s, 1, 0x3f800000, 0x3f800000 )

  /* 1.0 == 2.0 -> false */
  TEST_FP_CMP_S( 3, c.eq.s, 0, 0x3f800000, 0x40000000 )

  /* 0.0 == 0.0 -> true */
  TEST_FP_CMP_S( 4, c.eq.s, 1, 0x00000000, 0x00000000 )

  /* 0.0 == -0.0 -> true (per IEEE 754) */
  TEST_FP_CMP_S( 5, c.eq.s, 1, 0x00000000, 0x80000000 )

  /*-------------------------------------------------------------
   * C.LT.S tests - Compare Less Than
   *-------------------------------------------------------------*/

  /* 1.0 < 2.0 -> true */
  TEST_FP_CMP_S( 6, c.lt.s, 1, 0x3f800000, 0x40000000 )

  /* 2.0 < 1.0 -> false */
  TEST_FP_CMP_S( 7, c.lt.s, 0, 0x40000000, 0x3f800000 )

  /* 1.0 < 1.0 -> false */
  TEST_FP_CMP_S( 8, c.lt.s, 0, 0x3f800000, 0x3f800000 )

  /* -1.0 < 1.0 -> true */
  TEST_FP_CMP_S( 9, c.lt.s, 1, 0xbf800000, 0x3f800000 )

  /* -2.0 < -1.0 -> true */
  TEST_FP_CMP_S( 10, c.lt.s, 1, 0xc0000000, 0xbf800000 )

  /*-------------------------------------------------------------
   * C.LE.S tests - Compare Less Than or Equal
   *-------------------------------------------------------------*/

  /* 1.0 <= 2.0 -> true */
  TEST_FP_CMP_S( 11, c.le.s, 1, 0x3f800000, 0x40000000 )

  /* 1.0 <= 1.0 -> true */
  TEST_FP_CMP_S( 12, c.le.s, 1, 0x3f800000, 0x3f800000 )

  /* 2.0 <= 1.0 -> false */
  TEST_FP_CMP_S( 13, c.le.s, 0, 0x40000000, 0x3f800000 )

  /* -1.0 <= 1.0 -> true */
  TEST_FP_CMP_S( 14, c.le.s, 1, 0xbf800000, 0x3f800000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
