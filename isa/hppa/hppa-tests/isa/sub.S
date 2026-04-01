/* HPPA SUB instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Arithmetic tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2,  sub, 0x00000000, 0x00000000, 0x00000000 )
  TEST_RR_OP( 3,  sub, 0x00000000, 0x00000001, 0x00000001 )
  TEST_RR_OP( 4,  sub, 0x00000004, 0x00000007, 0x00000003 )

  TEST_RR_OP( 5,  sub, 0x00000010, 0x00000010, 0x00000000 )
  TEST_RR_OP( 6,  sub, 0x00000000, 0x00000010, 0x00000010 )

  TEST_RR_OP( 7,  sub, 0x000000e1, 0x000000f0, 0x0000000f )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 8, sub, 2, 13, 11 )
  TEST_RR_SRC2_EQ_DEST( 9, sub, 3, 14, 11 )
  TEST_RR_SRC12_EQ_DEST( 10, sub, 0, 13 )

  /*-------------------------------------------------------------
   * Zero source tests
   *-------------------------------------------------------------*/

  TEST_RR_ZEROSRC2( 11, sub, 15, 15 )
  TEST_RR_ZEROSRC12( 12, sub, 0 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
