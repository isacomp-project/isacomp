/* MIPS32 SLTIU instruction tests */
/* Based on riscv-tests structure */
/* Note: Unsigned comparison but immediate is sign-extended before compare */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Arithmetic tests (unsigned comparison)
   *-------------------------------------------------------------*/

  TEST_IMM_OP( 2,  sltiu, 0, 0x00000000, 0x000 )
  TEST_IMM_OP( 3,  sltiu, 0, 0x00000001, 0x001 )
  TEST_IMM_OP( 4,  sltiu, 1, 0x00000003, 0x007 )
  TEST_IMM_OP( 5,  sltiu, 0, 0x00000007, 0x003 )

  /* Unsigned with sign-extended immediate:
   * -2048 sign-extends to 0xfffff800 which is very large unsigned */
  TEST_IMM_OP( 6,  sltiu, 1, 0x00000000, -2048 )
  TEST_IMM_OP( 7,  sltiu, 0, 0x80000000, 0x000 )
  TEST_IMM_OP( 8,  sltiu, 0, 0x80000000, 0x7ff )

  TEST_IMM_OP( 9,  sltiu, 1, 0x00000000, 0x7ff )
  TEST_IMM_OP( 10, sltiu, 0, 0x7fffffff, 0x000 )
  TEST_IMM_OP( 11, sltiu, 0, 0x7fffffff, 0x7ff )

  TEST_IMM_OP( 12, sltiu, 0, 0x80000000, 0x7ff )
  /* 0x7fffffff < 0xfffff800 unsigned, so result is 1 */
  TEST_IMM_OP( 13, sltiu, 1, 0x7fffffff, -2048 )

  /* -1 (0xffffffff) is max unsigned, so 0 < max and max < 1 are false */
  TEST_IMM_OP( 14, sltiu, 1, 0x00000000, -1 )
  TEST_IMM_OP( 15, sltiu, 0, 0xffffffff, 0x001 )
  TEST_IMM_OP( 16, sltiu, 0, 0xffffffff, -1 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_IMM_SRC1_EQ_DEST( 17, sltiu, 1, 11, 13 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_IMM_DEST_BYPASS( 18, 0, sltiu, 0, 15, 13 )
  TEST_IMM_DEST_BYPASS( 19, 1, sltiu, 1, 10, 13 )
  TEST_IMM_DEST_BYPASS( 20, 2, sltiu, 0, 16, 13 )

  TEST_IMM_SRC1_BYPASS( 21, 0, sltiu, 1, 11, 13 )
  TEST_IMM_SRC1_BYPASS( 22, 1, sltiu, 0, 17, 13 )
  TEST_IMM_SRC1_BYPASS( 23, 2, sltiu, 1, 8, 13 )

  /* $zero < 0xffffffff unsigned */
  TEST_IMM_ZEROSRC1( 24, sltiu, 1, -1 )
  TEST_IMM_ZERODEST( 25, sltiu, 0x00ff00ff, 0x7ff )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
