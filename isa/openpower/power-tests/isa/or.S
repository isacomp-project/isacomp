/* OpenPOWER OR instruction tests */
/* or rA, rS, rB - OR */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Logical tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2,  or, 0xff00ff00, 0xff00ff00, 0x00000000 )
  TEST_RR_OP( 3,  or, 0xfff0fff0, 0x0ff00ff0, 0xf0f0f0f0 )
  TEST_RR_OP( 4,  or, 0x0fff0fff, 0x00ff00ff, 0x0f0f0f0f )
  TEST_RR_OP( 5,  or, 0xffffffff, 0xffff0000, 0x0000ffff )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 6, or, 0xff0fff0f, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_SRC2_EQ_DEST( 7, or, 0xfff0fff0, 0x0ff00ff0, 0xf0f0f0f0 )
  TEST_RR_SRC12_EQ_DEST( 8, or, 0xff00ff00, 0xff00ff00 )

  /*-------------------------------------------------------------
   * Zero source tests
   *-------------------------------------------------------------*/

  TEST_RR_ZEROSRC1( 9, or, 0xff00ff00, 0xff00ff00 )
  TEST_RR_ZEROSRC2( 10, or, 0x00ff00ff, 0x00ff00ff )
  TEST_RR_ZEROSRC12( 11, or, 0 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
