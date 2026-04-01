/* OpenPOWER FCMPU instruction tests */
/* fcmpu bf, fra, frb - Floating Compare Unordered */
/* Sets CR field: LT if fra < frb, GT if fra > frb, EQ if equal, FU if unordered */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic comparison tests
   * Format: TEST_FP_CMP_D(testnum, inst, exp_lt, exp_gt, exp_eq, ...)
   *-------------------------------------------------------------*/

  /* 1.0 < 2.0: LT=1, GT=0, EQ=0 */
  TEST_FP_CMP_D( 2, fcmpu, 1, 0, 0,
                 0x3ff00000, 0x00000000,   /* 1.0 */
                 0x40000000, 0x00000000 )  /* 2.0 */

  /* 2.0 > 1.0: LT=0, GT=1, EQ=0 */
  TEST_FP_CMP_D( 3, fcmpu, 0, 1, 0,
                 0x40000000, 0x00000000,   /* 2.0 */
                 0x3ff00000, 0x00000000 )  /* 1.0 */

  /* 1.0 == 1.0: LT=0, GT=0, EQ=1 */
  TEST_FP_CMP_D( 4, fcmpu, 0, 0, 1,
                 0x3ff00000, 0x00000000,   /* 1.0 */
                 0x3ff00000, 0x00000000 )  /* 1.0 */

  /* 0.0 == 0.0: LT=0, GT=0, EQ=1 */
  TEST_FP_CMP_D( 5, fcmpu, 0, 0, 1,
                 0x00000000, 0x00000000,
                 0x00000000, 0x00000000 )

  /* -1.0 < 1.0: LT=1, GT=0, EQ=0 */
  TEST_FP_CMP_D( 6, fcmpu, 1, 0, 0,
                 0xbff00000, 0x00000000,   /* -1.0 */
                 0x3ff00000, 0x00000000 )  /* 1.0 */

  /* 1.0 > -1.0: LT=0, GT=1, EQ=0 */
  TEST_FP_CMP_D( 7, fcmpu, 0, 1, 0,
                 0x3ff00000, 0x00000000,   /* 1.0 */
                 0xbff00000, 0x00000000 )  /* -1.0 */

  /* -2.0 < -1.0: LT=1, GT=0, EQ=0 */
  TEST_FP_CMP_D( 8, fcmpu, 1, 0, 0,
                 0xc0000000, 0x00000000,   /* -2.0 */
                 0xbff00000, 0x00000000 )  /* -1.0 */

  /* +0.0 == -0.0: LT=0, GT=0, EQ=1 */
  TEST_FP_CMP_D( 9, fcmpu, 0, 0, 1,
                 0x00000000, 0x00000000,   /* +0.0 */
                 0x80000000, 0x00000000 )  /* -0.0 */

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
