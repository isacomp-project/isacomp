/* j2 (SuperH-2) AND instruction tests */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Logical tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2, and, 0x0f000f00, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_OP( 3, and, 0x0f000f00, 0x0ff00ff0, 0x0f0f0f0f )
  TEST_RR_OP( 4, and, 0x000f000f, 0x00ff00ff, 0x0f0f0f0f )
  TEST_RR_OP( 5, and, 0x000f000f, 0xf00ff00f, 0x0f0f0f0f )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 6, and, 0x0f000f00, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_SRC2_EQ_DEST( 7, and, 0x0f000f00, 0x0ff00ff0, 0x0f0f0f0f )
  TEST_RR_SRC12_EQ_DEST( 8, and, 0xff00ff00, 0xff00ff00 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_RR_DEST_BYPASS( 9,  0, and, 0x0f000f00, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_DEST_BYPASS( 10, 1, and, 0x0f000f00, 0x0ff00ff0, 0x0f0f0f0f )
  TEST_RR_DEST_BYPASS( 11, 2, and, 0x000f000f, 0x00ff00ff, 0x0f0f0f0f )

  TEST_RR_ZEROSRC1( 12, and, 0, 0xff00ff00 )
  TEST_RR_ZEROSRC2( 13, and, 0, 0x00ff00ff )
  TEST_RR_ZEROSRC12( 14, and, 0 )
  /* Skip ZERODEST for AND - the generic macro uses ADD formula */

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
