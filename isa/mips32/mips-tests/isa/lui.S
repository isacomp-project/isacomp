/* MIPS32 LUI instruction tests */
/* Based on riscv-tests structure */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic tests
   *-------------------------------------------------------------*/

  TEST_LUI_OP( 2, 0x00000000, 0x0000 )
  TEST_LUI_OP( 3, 0xffff0000, 0xffff )
  TEST_LUI_OP( 4, 0x80000000, 0x8000 )
  TEST_LUI_OP( 5, 0x7fff0000, 0x7fff )
  TEST_LUI_OP( 6, 0x12340000, 0x1234 )
  TEST_LUI_OP( 7, 0xabcd0000, 0xabcd )
  TEST_LUI_OP( 8, 0x00010000, 0x0001 )

  /* Zero dest test - lui $zero should have no effect */
test_9:
  li TESTNUM, 9
  lui $zero, 0x1234
  bne $zero, $zero, fail
  nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
