/* MIPS32 LHU instruction tests */
/* Based on riscv-tests structure */
/* LHU loads a halfword and zero-extends to 32 bits */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic tests
   *-------------------------------------------------------------*/

  TEST_LD_OP( 2, lhu, 0x000000ff, 0, tdat )
  TEST_LD_OP( 3, lhu, 0x0000ff00, 2, tdat )
  TEST_LD_OP( 4, lhu, 0x00000ff0, 4, tdat )
  TEST_LD_OP( 5, lhu, 0x0000f00f, 6, tdat )

  /* Test with negative offset */
  TEST_LD_OP( 6, lhu, 0x000000ff, -6, tdat4 )
  TEST_LD_OP( 7, lhu, 0x0000ff00, -4, tdat4 )
  TEST_LD_OP( 8, lhu, 0x00000ff0, -2, tdat4 )
  TEST_LD_OP( 9, lhu, 0x0000f00f, 0, tdat4 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_LD_DEST_BYPASS( 10, 0, lhu, 0x00000ff0, 4, tdat )
  TEST_LD_DEST_BYPASS( 11, 1, lhu, 0x0000f00f, 6, tdat )
  TEST_LD_DEST_BYPASS( 12, 2, lhu, 0x0000ff00, 2, tdat )

  TEST_LD_SRC1_BYPASS( 13, 0, lhu, 0x00000ff0, 4, tdat )
  TEST_LD_SRC1_BYPASS( 14, 1, lhu, 0x0000f00f, 6, tdat )
  TEST_LD_SRC1_BYPASS( 15, 2, lhu, 0x0000ff00, 2, tdat )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA

  .align 1
tdat:
tdat1:  .half 0x00ff
tdat2:  .half 0xff00
tdat3:  .half 0x0ff0
tdat4:  .half 0xf00f

RVTEST_DATA_END
