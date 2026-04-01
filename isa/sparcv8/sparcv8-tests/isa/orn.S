/* SPARCv8 ORN instruction tests */
/* ORN is OR with second operand complemented: a | ~b */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Logical tests
   *-------------------------------------------------------------*/

  /* ORN: a | ~b */
  TEST_RR_OP( 2,  orn, 0xff0fff0f, 0xff00ff00, 0xf0f0f0f0 )  /* 0xff00ff00 | ~0xf0f0f0f0 = 0xff00ff00 | 0x0f0f0f0f */
  TEST_RR_OP( 3,  orn, 0xfff0fff0, 0x0ff00ff0, 0x0f0f0f0f )  /* 0x0ff00ff0 | 0xf0f0f0f0 = 0xfff0fff0 */
  TEST_RR_OP( 4,  orn, 0x0fff0fff, 0x00ff00ff, 0xf0f0f0f0 )  /* 0x00ff00ff | 0x0f0f0f0f = 0x0fff0fff */

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 5, orn, 0xff0fff0f, 0xff00ff00, 0xf0f0f0f0 )
  TEST_RR_SRC2_EQ_DEST( 6, orn, 0xfff0fff0, 0x0ff00ff0, 0x0f0f0f0f )
  TEST_RR_SRC12_EQ_DEST( 7, orn, 0xffffffff, 0xff00ff00 )

  /*-------------------------------------------------------------
   * Zero register tests
   *-------------------------------------------------------------*/

  TEST_RR_ZEROSRC1( 8, orn, 0x00ff00ff, 0xff00ff00 )
  TEST_RR_ZEROSRC2( 9, orn, 0xffffffff, 0x00ff00ff )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
