/* MIPS32 ORI instruction tests */
/* Based on riscv-tests structure */
/* Note: MIPS ORI uses 16-bit unsigned immediate (0-65535) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Logical tests
   *-------------------------------------------------------------*/

  TEST_IMM_OP( 2, ori, 0xff00ff0f, 0xff00ff00, 0x0f0f )
  TEST_IMM_OP( 3, ori, 0x0ff00ff0, 0x0ff00ff0, 0x00f0 )
  TEST_IMM_OP( 4, ori, 0x00ff07ff, 0x00ff00ff, 0x070f )
  TEST_IMM_OP( 5, ori, 0xf00ff0ff, 0xf00ff00f, 0x00f0 )

  /* Zero and all ones tests */
  TEST_IMM_OP( 6, ori, 0xffffffff, 0xffffffff, 0x0000 )
  TEST_IMM_OP( 7, ori, 0xffffffff, 0xffffffff, 0xffff )
  TEST_IMM_OP( 8, ori, 0x0000ffff, 0x00000000, 0xffff )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_IMM_SRC1_EQ_DEST( 9, ori, 0xff00fff0, 0xff00ff00, 0x00f0 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_IMM_DEST_BYPASS( 10, 0, ori, 0x0ff00ff0, 0x0ff00ff0, 0x00f0 )
  TEST_IMM_DEST_BYPASS( 11, 1, ori, 0x00ff07ff, 0x00ff00ff, 0x070f )
  TEST_IMM_DEST_BYPASS( 12, 2, ori, 0xf00ff0ff, 0xf00ff00f, 0x00f0 )

  TEST_IMM_SRC1_BYPASS( 13, 0, ori, 0x0ff00ff0, 0x0ff00ff0, 0x00f0 )
  TEST_IMM_SRC1_BYPASS( 14, 1, ori, 0x00ff0fff, 0x00ff00ff, 0x0f0f )
  TEST_IMM_SRC1_BYPASS( 15, 2, ori, 0xf00ff0ff, 0xf00ff00f, 0x00f0 )

  TEST_IMM_ZEROSRC1( 16, ori, 0x00f0, 0x00f0 )
  TEST_IMM_ZERODEST( 17, ori, 0x00ff00ff, 0x070f )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
