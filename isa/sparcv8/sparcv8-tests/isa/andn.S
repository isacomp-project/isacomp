/* SPARCv8 ANDN instruction tests */
/* ANDN is AND with second operand complemented: a & ~b */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Logical tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2,  andn, 0xf000f000, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_OP( 3,  andn, 0x0f000f00, 0x0ff00ff0, 0xf0f0f0f0 )
  TEST_RR_OP( 4,  andn, 0x00f000f0, 0x00ff00ff, 0x0f0f0f0f )
  TEST_RR_OP( 5,  andn, 0x000f000f, 0xf00ff00f, 0xf0f0f0f0 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 6, andn, 0xf000f000, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_SRC2_EQ_DEST( 7, andn, 0x0f000f00, 0x0ff00ff0, 0xf0f0f0f0 )
  TEST_RR_SRC12_EQ_DEST( 8, andn, 0x00000000, 0xff00ff00 )

  /*-------------------------------------------------------------
   * Zero register tests
   *-------------------------------------------------------------*/

  TEST_RR_ZEROSRC1( 9, andn, 0x00000000, 0xff00ff00 )
  TEST_RR_ZEROSRC2( 10, andn, 0x00ff00ff, 0x00ff00ff )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
