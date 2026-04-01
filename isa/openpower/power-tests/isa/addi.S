/* OpenPOWER ADDI instruction tests */
/* addi rD, rA, SIMM - Add Immediate */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Arithmetic tests
   *-------------------------------------------------------------*/

  TEST_IMM_OP( 2,  addi, 0x00000000, 0x00000000, 0x000 )
  TEST_IMM_OP( 3,  addi, 0x00000002, 0x00000001, 0x001 )
  TEST_IMM_OP( 4,  addi, 0x0000000a, 0x00000003, 0x007 )

  TEST_IMM_OP( 5,  addi, 0x00000800, 0x00000000, 0x800 )  /* 0x800 = +2048, zero in upper bits */
  TEST_IMM_OP( 6,  addi, 0x80001000, 0x80000800, 0x800 )  /* 0x80000800 + 0x00000800 = 0x80001000 */

  TEST_IMM_OP( 7,  addi, 0x000007ff, 0x00000000, 0x7ff )
  TEST_IMM_OP( 8,  addi, 0x7fffffff, 0x7ffff800, 0x7ff )

  TEST_IMM_OP( 9,  addi, 0xffffffff, 0x00000001, -2 )
  TEST_IMM_OP( 10, addi, 0x80000000, 0x80000001, -1 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_IMM_SRC1_EQ_DEST( 11, addi, 24, 13, 11 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_IMM_DEST_BYPASS( 12, 0, addi, 24, 13, 11 )
  TEST_IMM_DEST_BYPASS( 13, 1, addi, 23, 13, 10 )
  TEST_IMM_DEST_BYPASS( 14, 2, addi, 22, 13, 9 )

  TEST_IMM_SRC1_BYPASS( 15, 0, addi, 24, 13, 11 )
  TEST_IMM_SRC1_BYPASS( 16, 1, addi, 23, 13, 10 )
  TEST_IMM_SRC1_BYPASS( 17, 2, addi, 22, 13, 9 )

  TEST_IMM_ZEROSRC1( 18, addi, 32, 32 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
