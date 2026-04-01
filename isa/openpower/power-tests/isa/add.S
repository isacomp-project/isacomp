/* OpenPOWER ADD instruction tests */
/* add rD, rA, rB - Add */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Arithmetic tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2,  add, 0x00000000, 0x00000000, 0x00000000 )
  TEST_RR_OP( 3,  add, 0x00000002, 0x00000001, 0x00000001 )
  TEST_RR_OP( 4,  add, 0x0000000a, 0x00000003, 0x00000007 )

  TEST_RR_OP( 5,  add, 0xffff8000, 0x00000000, 0xffff8000 )
  TEST_RR_OP( 6,  add, 0x80000000, 0x80000000, 0x00000000 )
  TEST_RR_OP( 7,  add, 0x7fff8000, 0x80000000, 0xffff8000 )

  TEST_RR_OP( 8,  add, 0x00007fff, 0x00000000, 0x00007fff )
  TEST_RR_OP( 9,  add, 0x7fffffff, 0x7fffffff, 0x00000000 )
  TEST_RR_OP( 10, add, 0x80007ffe, 0x7fffffff, 0x00007fff )

  TEST_RR_OP( 11, add, 0x80007fff, 0x80000000, 0x00007fff )
  TEST_RR_OP( 12, add, 0x7fff7fff, 0x7fffffff, 0xffff8000 )

  TEST_RR_OP( 13, add, 0xffffffff, 0x00000000, 0xffffffff )
  TEST_RR_OP( 14, add, 0x00000000, 0xffffffff, 0x00000001 )
  TEST_RR_OP( 15, add, 0xfffffffe, 0xffffffff, 0xffffffff )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 17, add, 24, 13, 11 )
  TEST_RR_SRC2_EQ_DEST( 18, add, 25, 14, 11 )
  TEST_RR_SRC12_EQ_DEST( 19, add, 26, 13 )

  /*-------------------------------------------------------------
   * Zero source tests
   *-------------------------------------------------------------*/

  TEST_RR_ZEROSRC1( 20, add, 15, 15 )
  TEST_RR_ZEROSRC2( 21, add, 32, 32 )
  TEST_RR_ZEROSRC12( 22, add, 0 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
