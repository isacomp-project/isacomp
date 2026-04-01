/* MIPS32 LH instruction tests */
/* Based on riscv-tests structure */
/* LH loads a halfword and sign-extends to 32 bits */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic tests
   *-------------------------------------------------------------*/

  TEST_LD_OP( 2, lh, 0x000000ff, 0, tdat )
  TEST_LD_OP( 3, lh, 0xffffff00, 2, tdat )
  TEST_LD_OP( 4, lh, 0x00000ff0, 4, tdat )
  TEST_LD_OP( 5, lh, 0xfffff00f, 6, tdat )

  /* Test with negative offset */
  TEST_LD_OP( 6, lh, 0x000000ff, -6, tdat4 )
  TEST_LD_OP( 7, lh, 0xffffff00, -4, tdat4 )
  TEST_LD_OP( 8, lh, 0x00000ff0, -2, tdat4 )
  TEST_LD_OP( 9, lh, 0xfffff00f, 0, tdat4 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_LD_DEST_BYPASS( 10, 0, lh, 0x00000ff0, 4, tdat )
  TEST_LD_DEST_BYPASS( 11, 1, lh, 0xfffff00f, 6, tdat )
  TEST_LD_DEST_BYPASS( 12, 2, lh, 0xffffff00, 2, tdat )

  TEST_LD_SRC1_BYPASS( 13, 0, lh, 0x00000ff0, 4, tdat )
  TEST_LD_SRC1_BYPASS( 14, 1, lh, 0xfffff00f, 6, tdat )
  TEST_LD_SRC1_BYPASS( 15, 2, lh, 0xffffff00, 2, tdat )

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
