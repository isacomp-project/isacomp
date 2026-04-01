/* MIPS32 XORI instruction tests */
/* Based on riscv-tests structure */
/* Note: MIPS XORI uses 16-bit unsigned immediate (0-65535) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Logical tests
   *-------------------------------------------------------------*/

  TEST_IMM_OP( 2, xori, 0xff00f00f, 0xff00ff00, 0x0f0f )
  TEST_IMM_OP( 3, xori, 0x0ff00f00, 0x0ff00ff0, 0x00f0 )
  TEST_IMM_OP( 4, xori, 0x00ff07f0, 0x00ff00ff, 0x070f )
  TEST_IMM_OP( 5, xori, 0xf00ff0ff, 0xf00ff00f, 0x00f0 )

  /* Zero and all ones tests */
  TEST_IMM_OP( 6, xori, 0xffffffff, 0xffffffff, 0x0000 )
  TEST_IMM_OP( 7, xori, 0xffff0000, 0xffffffff, 0xffff )
  TEST_IMM_OP( 8, xori, 0x0000ffff, 0x00000000, 0xffff )

  /* XOR with same value = 0 (using register, not immediate) */
  TEST_IMM_OP( 9, xori, 0x0000f0f0, 0x0000f0f0, 0x0000 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_IMM_SRC1_EQ_DEST( 10, xori, 0xff00f00f, 0xff00ff00, 0x0f0f )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_IMM_DEST_BYPASS( 11, 0, xori, 0x0ff00f00, 0x0ff00ff0, 0x00f0 )
  TEST_IMM_DEST_BYPASS( 12, 1, xori, 0x00ff07f0, 0x00ff00ff, 0x070f )
  TEST_IMM_DEST_BYPASS( 13, 2, xori, 0xf00ff0ff, 0xf00ff00f, 0x00f0 )

  TEST_IMM_SRC1_BYPASS( 14, 0, xori, 0x0ff00f00, 0x0ff00ff0, 0x00f0 )
  TEST_IMM_SRC1_BYPASS( 15, 1, xori, 0x00ff0ff0, 0x00ff00ff, 0x0f0f )
  TEST_IMM_SRC1_BYPASS( 16, 2, xori, 0xf00ff0ff, 0xf00ff00f, 0x00f0 )

  TEST_IMM_ZEROSRC1( 17, xori, 0x00f0, 0x00f0 )
  TEST_IMM_ZERODEST( 18, xori, 0x00ff00ff, 0x070f )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
