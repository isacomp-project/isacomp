/* MIPS32 LB instruction tests */
/* Based on riscv-tests structure */
/* LB loads a byte and sign-extends to 32 bits */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic tests
   *-------------------------------------------------------------*/

  TEST_LD_OP( 2, lb, 0xffffffff, 0, tdat )
  TEST_LD_OP( 3, lb, 0x00000000, 1, tdat )
  TEST_LD_OP( 4, lb, 0xfffffff0, 2, tdat )
  TEST_LD_OP( 5, lb, 0x0000000f, 3, tdat )

  /* Test with negative offset */
  TEST_LD_OP( 6, lb, 0xffffffff, -3, tdat4 )
  TEST_LD_OP( 7, lb, 0x00000000, -2, tdat4 )
  TEST_LD_OP( 8, lb, 0xfffffff0, -1, tdat4 )
  TEST_LD_OP( 9, lb, 0x0000000f, 0, tdat4 )

  /* Test with positive offset */
  TEST_LD_OP( 10, lb, 0xffffffff, 0, tdat )
  TEST_LD_OP( 11, lb, 0x00000000, 1, tdat )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_LD_DEST_BYPASS( 12, 0, lb, 0xfffffff0, 2, tdat )
  TEST_LD_DEST_BYPASS( 13, 1, lb, 0x0000000f, 3, tdat )
  TEST_LD_DEST_BYPASS( 14, 2, lb, 0x00000000, 1, tdat )

  TEST_LD_SRC1_BYPASS( 15, 0, lb, 0xfffffff0, 2, tdat )
  TEST_LD_SRC1_BYPASS( 16, 1, lb, 0x0000000f, 3, tdat )
  TEST_LD_SRC1_BYPASS( 17, 2, lb, 0x00000000, 1, tdat )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA

tdat:
tdat1:  .byte 0xff
tdat2:  .byte 0x00
tdat3:  .byte 0xf0
tdat4:  .byte 0x0f

RVTEST_DATA_END
