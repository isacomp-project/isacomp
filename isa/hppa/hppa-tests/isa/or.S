/* HPPA OR instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Logical tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2,  or, 0x00000000, 0x00000000, 0x00000000 )
  TEST_RR_OP( 3,  or, 0x00000001, 0x00000001, 0x00000001 )
  TEST_RR_OP( 4,  or, 0x00000001, 0x00000001, 0x00000000 )

  TEST_RR_OP( 5,  or, 0x00000007, 0x00000003, 0x00000005 )
  TEST_RR_OP( 6,  or, 0x000000ff, 0x000000f0, 0x0000001f )
  TEST_RR_OP( 7,  or, 0x000000ff, 0x0000000f, 0x000000f0 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 8, or, 0xff, 0x0f, 0xf0 )
  TEST_RR_SRC2_EQ_DEST( 9, or, 0xff, 0xf0, 0x0f )
  TEST_RR_SRC12_EQ_DEST( 10, or, 0x0f, 0x0f )

  /*-------------------------------------------------------------
   * Zero source tests
   *-------------------------------------------------------------*/

  TEST_RR_ZEROSRC1( 11, or, 0xff, 0xff )
  TEST_RR_ZEROSRC2( 12, or, 0xff, 0xff )
  TEST_RR_ZEROSRC12( 13, or, 0 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
