/* j2 (SuperH-2) SUB instruction tests */

#include "test_macros.h"

J2TEST_CODE_BEGIN

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

  TEST_RR_SRC1_EQ_DEST( 17, sub, 2, 13, 11 )
  TEST_RR_SRC2_EQ_DEST( 18, sub, 3, 14, 11 )
  TEST_RR_SRC12_EQ_DEST( 19, sub, 0, 13 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_RR_DEST_BYPASS( 20, 0, sub, 2, 13, 11 )
  TEST_RR_DEST_BYPASS( 21, 1, sub, 3, 14, 11 )
  TEST_RR_DEST_BYPASS( 22, 2, sub, 4, 15, 11 )

  /* For SUB: ZEROSRC1 means 0 - val = -val */
  TEST_RR_ZEROSRC1( 35, sub, 0xFFFFFFF1, 15 )  /* 0 - 15 = -15 */
  TEST_RR_ZEROSRC2( 36, sub, 32, 32 )          /* 32 - 0 = 32 */
  TEST_RR_ZEROSRC12( 37, sub, 0 )              /* 0 - 0 = 0 */
  /* Skip ZERODEST for SUB - the generic macro uses ADD formula */

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
