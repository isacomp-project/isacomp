/* MIPS32 NOR instruction tests */
/* Based on riscv-tests structure */
/* NOR rd, rs, rt: rd = ~(rs | rt) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Logical tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2, nor, 0x00f000f0, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_OP( 3, nor, 0x000f000f, 0x0ff00ff0, 0xf0f0f0f0 )
  TEST_RR_OP( 4, nor, 0xf000f000, 0x00ff00ff, 0x0f0f0f0f )
  TEST_RR_OP( 5, nor, 0x0f000f00, 0xf00ff00f, 0x00f000f0 )

  /* NOR with zero = NOT */
  TEST_RR_OP( 6, nor, 0x00ff00ff, 0xff00ff00, 0x00000000 )
  TEST_RR_OP( 7, nor, 0xffffffff, 0x00000000, 0x00000000 )
  TEST_RR_OP( 8, nor, 0x00000000, 0xffffffff, 0x00000000 )

  /* NOR with all ones = 0 */
  TEST_RR_OP( 9, nor, 0x00000000, 0xffffffff, 0xffffffff )
  TEST_RR_OP( 10, nor, 0x00000000, 0x12345678, 0xffffffff )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 11, nor, 0x00f000f0, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_SRC2_EQ_DEST( 12, nor, 0x00f000f0, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_SRC12_EQ_DEST( 13, nor, 0x00ff00ff, 0xff00ff00 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_RR_DEST_BYPASS( 14, 0, nor, 0x00f000f0, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_DEST_BYPASS( 15, 1, nor, 0x000f000f, 0x0ff00ff0, 0xf0f0f0f0 )
  TEST_RR_DEST_BYPASS( 16, 2, nor, 0xf000f000, 0x00ff00ff, 0x0f0f0f0f )

  TEST_RR_SRC12_BYPASS( 17, 0, 0, nor, 0x00f000f0, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_SRC12_BYPASS( 18, 0, 1, nor, 0x000f000f, 0x0ff00ff0, 0xf0f0f0f0 )
  TEST_RR_SRC12_BYPASS( 19, 0, 2, nor, 0xf000f000, 0x00ff00ff, 0x0f0f0f0f )
  TEST_RR_SRC12_BYPASS( 20, 1, 0, nor, 0x00f000f0, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_SRC12_BYPASS( 21, 1, 1, nor, 0x000f000f, 0x0ff00ff0, 0xf0f0f0f0 )
  TEST_RR_SRC12_BYPASS( 22, 2, 0, nor, 0xf000f000, 0x00ff00ff, 0x0f0f0f0f )

  TEST_RR_SRC21_BYPASS( 23, 0, 0, nor, 0x00f000f0, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_SRC21_BYPASS( 24, 0, 1, nor, 0x000f000f, 0x0ff00ff0, 0xf0f0f0f0 )
  TEST_RR_SRC21_BYPASS( 25, 0, 2, nor, 0xf000f000, 0x00ff00ff, 0x0f0f0f0f )
  TEST_RR_SRC21_BYPASS( 26, 1, 0, nor, 0x00f000f0, 0xff00ff00, 0x0f0f0f0f )
  TEST_RR_SRC21_BYPASS( 27, 1, 1, nor, 0x000f000f, 0x0ff00ff0, 0xf0f0f0f0 )
  TEST_RR_SRC21_BYPASS( 28, 2, 0, nor, 0xf000f000, 0x00ff00ff, 0x0f0f0f0f )

  /* NOR $zero, $zero = 0xffffffff */
  TEST_RR_ZEROSRC1( 29, nor, 0x00ff00ff, 0xff00ff00 )
  TEST_RR_ZEROSRC2( 30, nor, 0xff00ff00, 0x00ff00ff )
  TEST_RR_ZEROSRC12( 31, nor, 0xffffffff )
  TEST_RR_ZERODEST( 32, nor, 0x11111111, 0x22222222 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
