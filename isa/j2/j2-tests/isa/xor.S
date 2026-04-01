/* j2 (SuperH-2) XOR instruction tests */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Logical tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2, xor, 0xf00ff00f, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_OP( 3, xor, 0x00ff00ff, 0x0ff00ff0, 0x0f0f0f0f )
  TEST_RR_OP( 4, xor, 0x0ff00ff0, 0x00ff00ff, 0x0f0f0f0f )
  TEST_RR_OP( 5, xor, 0xff00ff00, 0xf00ff00f, 0x0f0f0f0f )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 6, xor, 0xf00ff00f, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_SRC2_EQ_DEST( 7, xor, 0x00ff00ff, 0x0ff00ff0, 0x0f0f0f0f )
  TEST_RR_SRC12_EQ_DEST( 8, xor, 0x00000000, 0xff00ff00 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_RR_DEST_BYPASS( 9,  0, xor, 0xf00ff00f, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_DEST_BYPASS( 10, 1, xor, 0x00ff00ff, 0x0ff00ff0, 0x0f0f0f0f )
  TEST_RR_DEST_BYPASS( 11, 2, xor, 0x0ff00ff0, 0x00ff00ff, 0x0f0f0f0f )

  TEST_RR_ZEROSRC1( 12, xor, 0xff00ff00, 0xff00ff00 )
  TEST_RR_ZEROSRC2( 13, xor, 0x00ff00ff, 0x00ff00ff )
  TEST_RR_ZEROSRC12( 14, xor, 0 )
  /* Skip ZERODEST for XOR - the generic macro uses ADD formula */

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
