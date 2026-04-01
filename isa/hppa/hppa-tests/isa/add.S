/* HPPA ADD instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Arithmetic tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2,  add, 0x00000000, 0x00000000, 0x00000000 )
  TEST_RR_OP( 3,  add, 0x00000002, 0x00000001, 0x00000001 )
  TEST_RR_OP( 4,  add, 0x0000000a, 0x00000003, 0x00000007 )

  TEST_RR_OP( 5,  add, 0x00000010, 0x00000000, 0x00000010 )
  TEST_RR_OP( 6,  add, 0x00000020, 0x00000010, 0x00000010 )

  TEST_RR_OP( 7,  add, 0x000000ff, 0x000000f0, 0x0000000f )
  TEST_RR_OP( 8,  add, 0x00000100, 0x000000ff, 0x00000001 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 9, add, 24, 13, 11 )
  TEST_RR_SRC2_EQ_DEST( 10, add, 25, 14, 11 )
  TEST_RR_SRC12_EQ_DEST( 11, add, 26, 13 )

  /*-------------------------------------------------------------
   * Zero source tests
   *-------------------------------------------------------------*/

  TEST_RR_ZEROSRC1( 12, add, 15, 15 )
  TEST_RR_ZEROSRC2( 13, add, 32, 32 )
  TEST_RR_ZEROSRC12( 14, add, 0 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
