/* j2 (SuperH-2) OR instruction tests */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Logical tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2, or, 0xff0fff0f, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_OP( 3, or, 0x0fff0fff, 0x0ff00ff0, 0x0f0f0f0f )
  TEST_RR_OP( 4, or, 0x0fff0fff, 0x00ff00ff, 0x0f0f0f0f )
  TEST_RR_OP( 5, or, 0xff0fff0f, 0xf00ff00f, 0x0f0f0f0f )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 6, or, 0xff0fff0f, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_SRC2_EQ_DEST( 7, or, 0x0fff0fff, 0x0ff00ff0, 0x0f0f0f0f )
  TEST_RR_SRC12_EQ_DEST( 8, or, 0xff00ff00, 0xff00ff00 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_RR_DEST_BYPASS( 9,  0, or, 0xff0fff0f, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_DEST_BYPASS( 10, 1, or, 0x0fff0fff, 0x0ff00ff0, 0x0f0f0f0f )
  TEST_RR_DEST_BYPASS( 11, 2, or, 0x0fff0fff, 0x00ff00ff, 0x0f0f0f0f )

  TEST_RR_ZEROSRC1( 12, or, 0xff00ff00, 0xff00ff00 )
  TEST_RR_ZEROSRC2( 13, or, 0x00ff00ff, 0x00ff00ff )
  TEST_RR_ZEROSRC12( 14, or, 0 )
  TEST_RR_ZERODEST( 15, or, 0x11111111, 0x22222222 )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
