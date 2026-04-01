/* OpenPOWER SETB instruction tests */
/* setb rD, BFA - Set Boolean */
/* rD = -1 if LT bit set, +1 if GT bit set, 0 if EQ bit set */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic tests: less than -> -1
   *-------------------------------------------------------------*/

  /* 5 < 10 -> setb returns -1 */
  TEST_SETB_LT( 2, 5, 10 )

  /* -5 < 0 -> setb returns -1 */
  TEST_SETB_LT( 3, -5, 0 )

  /* 0 < 1 -> setb returns -1 */
  TEST_SETB_LT( 4, 0, 1 )

  /* -100 < -50 -> setb returns -1 */
  TEST_SETB_LT( 5, -100, -50 )

  /*-------------------------------------------------------------
   * Basic tests: greater than -> +1
   *-------------------------------------------------------------*/

  /* 10 > 5 -> setb returns +1 */
  TEST_SETB_GT( 6, 10, 5 )

  /* 0 > -5 -> setb returns +1 */
  TEST_SETB_GT( 7, 0, -5 )

  /* 1 > 0 -> setb returns +1 */
  TEST_SETB_GT( 8, 1, 0 )

  /* -50 > -100 -> setb returns +1 */
  TEST_SETB_GT( 9, -50, -100 )

  /*-------------------------------------------------------------
   * Basic tests: equal -> 0
   *-------------------------------------------------------------*/

  /* 5 == 5 -> setb returns 0 */
  TEST_SETB_EQ( 10, 5, 5 )

  /* 0 == 0 -> setb returns 0 */
  TEST_SETB_EQ( 11, 0, 0 )

  /* -10 == -10 -> setb returns 0 */
  TEST_SETB_EQ( 12, -10, -10 )

  /* 0x7FFFFFFF == 0x7FFFFFFF -> setb returns 0 */
  TEST_SETB_EQ( 13, 0x7FFFFFFF, 0x7FFFFFFF )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
