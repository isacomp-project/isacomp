/* HPPA SH1ADD (Shift 1 and Add) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Shift-and-add tests: result = (r1 << 1) + r2
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2,  sh1add, 0x00000000, 0x00000000, 0x00000000 )
  TEST_RR_OP( 3,  sh1add, 0x00000002, 0x00000001, 0x00000000 )
  TEST_RR_OP( 4,  sh1add, 0x00000003, 0x00000001, 0x00000001 )

  TEST_RR_OP( 5,  sh1add, 0x0000000a, 0x00000005, 0x00000000 )
  TEST_RR_OP( 6,  sh1add, 0x00000015, 0x0000000a, 0x00000001 )
  TEST_RR_OP( 7,  sh1add, 0x00000028, 0x00000014, 0x00000000 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 8, sh1add, 0x0a, 0x05, 0x00 )
  TEST_RR_SRC2_EQ_DEST( 9, sh1add, 0x0b, 0x05, 0x01 )

  /*-------------------------------------------------------------
   * Zero source tests
   *-------------------------------------------------------------*/

  TEST_RR_ZEROSRC1( 10, sh1add, 0x05, 0x05 )
  TEST_RR_ZEROSRC2( 11, sh1add, 0x0a, 0x05 )
  TEST_RR_ZEROSRC12( 12, sh1add, 0 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
