/* MIPS32 ANDI instruction tests */
/* Based on riscv-tests structure */
/* Note: MIPS ANDI uses 16-bit unsigned immediate (0-65535) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Logical tests
   *-------------------------------------------------------------*/

  TEST_IMM_OP( 2, andi, 0x00000f00, 0xff00ff00, 0x0f0f )
  TEST_IMM_OP( 3, andi, 0x000000f0, 0x0ff00ff0, 0x00f0 )
  TEST_IMM_OP( 4, andi, 0x0000000f, 0x00ff00ff, 0x070f )
  TEST_IMM_OP( 5, andi, 0x00000000, 0xf00ff00f, 0x00f0 )

  /* Zero and all ones tests */
  TEST_IMM_OP( 6, andi, 0x00000000, 0xffffffff, 0x0000 )
  TEST_IMM_OP( 7, andi, 0x0000ffff, 0xffffffff, 0xffff )
  TEST_IMM_OP( 8, andi, 0x00000000, 0x00000000, 0xffff )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_IMM_SRC1_EQ_DEST( 9, andi, 0x00000000, 0xff00ff00, 0x00f0 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_IMM_DEST_BYPASS( 10, 0, andi, 0x00000700, 0x0ff00ff0, 0x0707 )
  TEST_IMM_DEST_BYPASS( 11, 1, andi, 0x000000f0, 0x00ff00ff, 0x00f0 )
  TEST_IMM_DEST_BYPASS( 12, 2, andi, 0x0000000f, 0xf00ff00f, 0x0f0f )

  TEST_IMM_SRC1_BYPASS( 13, 0, andi, 0x00000700, 0x0ff00ff0, 0x0707 )
  TEST_IMM_SRC1_BYPASS( 14, 1, andi, 0x000000f0, 0x00ff00ff, 0x00f0 )
  TEST_IMM_SRC1_BYPASS( 15, 2, andi, 0x0000000f, 0xf00ff00f, 0x070f )

  TEST_IMM_ZEROSRC1( 16, andi, 0, 0x00f0 )
  TEST_IMM_ZERODEST( 17, andi, 0x00ff00ff, 0x070f )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
