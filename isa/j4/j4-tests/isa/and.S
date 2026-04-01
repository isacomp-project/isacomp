/* j4 (SuperH-4) AND instruction tests */

#include "test_macros.h"

J4TEST_CODE_BEGIN

  TEST_RR_OP( 2, and, 0x0f000f00, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_OP( 3, and, 0x00f000f0, 0x0ff00ff0, 0x00ff00ff )
  TEST_RR_OP( 4, and, 0x000f000f, 0x00ff00ff, 0xf00ff00f )
  TEST_RR_OP( 5, and, 0xf000f000, 0xf00ff00f, 0xff00ff00 )

  TEST_RR_SRC1_EQ_DEST( 6, and, 0x0f000f00, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_SRC2_EQ_DEST( 7, and, 0x00f000f0, 0x0ff00ff0, 0x00ff00ff )
  TEST_RR_SRC12_EQ_DEST( 8, and, 0xff00ff00, 0xff00ff00 )

  TEST_PASSFAIL

J4TEST_CODE_END

J4TEST_PASS
J4TEST_FAIL

J4TEST_DATA_BEGIN
  TEST_DATA
J4TEST_DATA_END
