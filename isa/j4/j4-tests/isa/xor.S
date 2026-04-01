/* j4 (SuperH-4) XOR instruction tests */

#include "test_macros.h"

J4TEST_CODE_BEGIN

  TEST_RR_OP( 2, xor, 0xf00ff00f, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_OP( 3, xor, 0x0f0f0f0f, 0x0ff00ff0, 0x00ff00ff )
  TEST_RR_OP( 4, xor, 0xf0f0f0f0, 0x00ff00ff, 0xf00ff00f )
  TEST_RR_OP( 5, xor, 0x0f0f0f0f, 0xf00ff00f, 0xff00ff00 )

  TEST_RR_SRC1_EQ_DEST( 6, xor, 0xf00ff00f, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_SRC2_EQ_DEST( 7, xor, 0x0f0f0f0f, 0x0ff00ff0, 0x00ff00ff )
  TEST_RR_SRC12_EQ_DEST( 8, xor, 0x00000000, 0xff00ff00 )

  TEST_PASSFAIL

J4TEST_CODE_END

J4TEST_PASS
J4TEST_FAIL

J4TEST_DATA_BEGIN
  TEST_DATA
J4TEST_DATA_END
