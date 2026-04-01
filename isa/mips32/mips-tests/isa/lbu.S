/* MIPS32 LBU instruction tests */
/* Based on riscv-tests structure */
/* LBU loads a byte and zero-extends to 32 bits */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic tests
   *-------------------------------------------------------------*/

  TEST_LD_OP( 2, lbu, 0x000000ff, 0, tdat )
  TEST_LD_OP( 3, lbu, 0x00000000, 1, tdat )
  TEST_LD_OP( 4, lbu, 0x000000f0, 2, tdat )
  TEST_LD_OP( 5, lbu, 0x0000000f, 3, tdat )

  /* Test with negative offset */
  TEST_LD_OP( 6, lbu, 0x000000ff, -3, tdat4 )
  TEST_LD_OP( 7, lbu, 0x00000000, -2, tdat4 )
  TEST_LD_OP( 8, lbu, 0x000000f0, -1, tdat4 )
  TEST_LD_OP( 9, lbu, 0x0000000f, 0, tdat4 )

  /* Test with positive offset */
  TEST_LD_OP( 10, lbu, 0x000000ff, 0, tdat )
  TEST_LD_OP( 11, lbu, 0x00000000, 1, tdat )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_LD_DEST_BYPASS( 12, 0, lbu, 0x000000f0, 2, tdat )
  TEST_LD_DEST_BYPASS( 13, 1, lbu, 0x0000000f, 3, tdat )
  TEST_LD_DEST_BYPASS( 14, 2, lbu, 0x00000000, 1, tdat )

  TEST_LD_SRC1_BYPASS( 15, 0, lbu, 0x000000f0, 2, tdat )
  TEST_LD_SRC1_BYPASS( 16, 1, lbu, 0x0000000f, 3, tdat )
  TEST_LD_SRC1_BYPASS( 17, 2, lbu, 0x00000000, 1, tdat )

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
