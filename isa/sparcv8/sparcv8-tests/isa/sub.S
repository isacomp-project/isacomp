/* SPARCv8 SUB instruction tests */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Arithmetic tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2,  sub, 0x00000000, 0x00000000, 0x00000000 )
  TEST_RR_OP( 3,  sub, 0x00000000, 0x00000001, 0x00000001 )
  TEST_RR_OP( 4,  sub, 0xfffffffc, 0x00000003, 0x00000007 )

  TEST_RR_OP( 5,  sub, 0x00008000, 0x00000000, 0xffff8000 )
  TEST_RR_OP( 6,  sub, 0x80000000, 0x80000000, 0x00000000 )
  TEST_RR_OP( 7,  sub, 0x80008000, 0x80000000, 0xffff8000 )

  TEST_RR_OP( 8,  sub, 0xffff8001, 0x00000000, 0x00007fff )
  TEST_RR_OP( 9,  sub, 0x7fffffff, 0x7fffffff, 0x00000000 )
  TEST_RR_OP( 10, sub, 0x7fff8000, 0x7fffffff, 0x00007fff )

  TEST_RR_OP( 11, sub, 0x7fff8001, 0x80000000, 0x00007fff )
  TEST_RR_OP( 12, sub, 0x80007fff, 0x7fffffff, 0xffff8000 )

  TEST_RR_OP( 13, sub, 0x00000001, 0x00000000, 0xffffffff )
  TEST_RR_OP( 14, sub, 0xfffffffe, 0xffffffff, 0x00000001 )
  TEST_RR_OP( 15, sub, 0x00000000, 0xffffffff, 0xffffffff )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 16, sub, 2, 13, 11 )
  TEST_RR_SRC2_EQ_DEST( 17, sub, 3, 14, 11 )
  TEST_RR_SRC12_EQ_DEST( 18, sub, 0, 13 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_RR_DEST_BYPASS( 19, 0, sub, 2, 13, 11 )
  TEST_RR_DEST_BYPASS( 20, 1, sub, 3, 14, 11 )
  TEST_RR_DEST_BYPASS( 21, 2, sub, 4, 15, 11 )

  /*-------------------------------------------------------------
   * Zero register tests
   *-------------------------------------------------------------*/

  TEST_RR_ZEROSRC1( 22, sub, -15, 15 )
  TEST_RR_ZEROSRC2( 23, sub, 32, 32 )
  TEST_RR_ZEROSRC12( 24, sub, 0 )

  /*-------------------------------------------------------------
   * Immediate tests
   *-------------------------------------------------------------*/

  TEST_RI_OP( 25, sub, 0x00000000, 0x00000001, 1 )
  TEST_RI_OP( 26, sub, 0xfffffffc, 0x00000003, 7 )
  TEST_RI_OP( 27, sub, 0x00000800, 0x00000000, -2048 )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
