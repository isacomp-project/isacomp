/* OpenPOWER AND instruction tests */
/* and rA, rS, rB - AND */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Logical tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2,  and, 0xff00ff00, 0xff00ff00, 0xff00ff00 )
  TEST_RR_OP( 3,  and, 0x00000000, 0x0ff00ff0, 0xf00ff00f )
  TEST_RR_OP( 4,  and, 0x00000000, 0x00ff00ff, 0xff00ff00 )
  TEST_RR_OP( 5,  and, 0xf0f0f0f0, 0xf0f0f0f0, 0xf0f0f0f0 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 6, and, 0x0f000f00, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_SRC2_EQ_DEST( 7, and, 0x00f000f0, 0x0ff00ff0, 0xf0f0f0f0 )
  TEST_RR_SRC12_EQ_DEST( 8, and, 0xff00ff00, 0xff00ff00 )

  /*-------------------------------------------------------------
   * Zero source tests
   *-------------------------------------------------------------*/

  TEST_RR_ZEROSRC1( 9, and, 0, 0xff00ff00 )
  TEST_RR_ZEROSRC2( 10, and, 0, 0x00ff00ff )
  TEST_RR_ZEROSRC12( 11, and, 0 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
