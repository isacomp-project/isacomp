/* SPARCv8 SRL instruction tests (shift right logical) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic shift tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2,  srl, 0xffff8000, 0xffff8000, 0 )
  TEST_RR_OP( 3,  srl, 0x7fffc000, 0xffff8000, 1 )
  TEST_RR_OP( 4,  srl, 0x01ffff00, 0xffff8000, 7 )
  TEST_RR_OP( 5,  srl, 0x0003fffe, 0xffff8000, 14 )
  TEST_RR_OP( 6,  srl, 0x0001ffff, 0xffff8000, 15 )
  TEST_RR_OP( 7,  srl, 0x00000001, 0xffff8000, 31 )

  TEST_RR_OP( 8,  srl, 0xffffffff, 0xffffffff, 0 )
  TEST_RR_OP( 9,  srl, 0x7fffffff, 0xffffffff, 1 )
  TEST_RR_OP( 10, srl, 0x01ffffff, 0xffffffff, 7 )
  TEST_RR_OP( 11, srl, 0x0003ffff, 0xffffffff, 14 )
  TEST_RR_OP( 12, srl, 0x00000001, 0xffffffff, 31 )

  TEST_RR_OP( 13, srl, 0x21212121, 0x21212121, 0 )
  TEST_RR_OP( 14, srl, 0x10909090, 0x21212121, 1 )
  TEST_RR_OP( 15, srl, 0x00424242, 0x21212121, 7 )
  TEST_RR_OP( 16, srl, 0x00008484, 0x21212121, 14 )
  TEST_RR_OP( 17, srl, 0x00000000, 0x21212121, 31 )

  /* Shift amount uses only low 5 bits */
  TEST_RR_OP( 18, srl, 0x21212121, 0x21212121, 0xffffffe0 )
  TEST_RR_OP( 19, srl, 0x10909090, 0x21212121, 0xffffffe1 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 20, srl, 0x01ffff00, 0xffff8000, 7 )
  TEST_RR_SRC2_EQ_DEST( 21, srl, 0x0003fffe, 0xffff8000, 14 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_RR_DEST_BYPASS( 22, 0, srl, 0x01ffff00, 0xffff8000, 7 )
  TEST_RR_DEST_BYPASS( 23, 1, srl, 0x0003fffe, 0xffff8000, 14 )
  TEST_RR_DEST_BYPASS( 24, 2, srl, 0x00000001, 0xffff8000, 31 )

  /*-------------------------------------------------------------
   * Zero register tests
   *-------------------------------------------------------------*/

  TEST_RR_ZEROSRC1( 25, srl, 0, 15 )
  TEST_RR_ZEROSRC2( 26, srl, 32, 32 )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
