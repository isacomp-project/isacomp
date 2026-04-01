/* MIPS32 SH instruction tests */
/* Based on riscv-tests structure */
/* SH stores the least significant halfword */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic tests
   *-------------------------------------------------------------*/

  TEST_ST_OP( 2, lh, sh, 0x000000aa, 0, tdat )
  TEST_ST_OP( 3, lh, sh, 0xffffaa00, 2, tdat )
  TEST_ST_OP( 4, lh, sh, 0xffffbeef, 4, tdat )
  TEST_ST_OP( 5, lh, sh, 0xffffa00a, 6, tdat )

  /* Test with negative offset */
  TEST_ST_OP( 6, lh, sh, 0x000000aa, -6, tdat4 )
  TEST_ST_OP( 7, lh, sh, 0xffffaa00, -4, tdat4 )
  TEST_ST_OP( 8, lh, sh, 0xffffbeef, -2, tdat4 )
  TEST_ST_OP( 9, lh, sh, 0xffffa00a, 0, tdat4 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_ST_SRC12_BYPASS( 10, 0, 0, lh, sh, 0xffffccdd, 0, tdat )
  TEST_ST_SRC12_BYPASS( 11, 0, 1, lh, sh, 0xffffbccd, 2, tdat )
  TEST_ST_SRC12_BYPASS( 12, 0, 2, lh, sh, 0xffffbbcc, 4, tdat )
  TEST_ST_SRC12_BYPASS( 13, 1, 0, lh, sh, 0xffffabbc, 6, tdat )
  TEST_ST_SRC12_BYPASS( 14, 1, 1, lh, sh, 0xffffaabb, 8, tdat )
  TEST_ST_SRC12_BYPASS( 15, 2, 0, lh, sh, 0xffffdaab, 10, tdat )

  TEST_ST_SRC21_BYPASS( 16, 0, 0, lh, sh, 0x00002233, 0, tdat )
  TEST_ST_SRC21_BYPASS( 17, 0, 1, lh, sh, 0x00001223, 2, tdat )
  TEST_ST_SRC21_BYPASS( 18, 0, 2, lh, sh, 0x00001122, 4, tdat )
  TEST_ST_SRC21_BYPASS( 19, 1, 0, lh, sh, 0x00000112, 6, tdat )
  TEST_ST_SRC21_BYPASS( 20, 1, 1, lh, sh, 0x00000011, 8, tdat )
  TEST_ST_SRC21_BYPASS( 21, 2, 0, lh, sh, 0x00003001, 10, tdat )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA

  .align 1
tdat:
tdat1:  .half 0xbeef
tdat2:  .half 0xbeef
tdat3:  .half 0xbeef
tdat4:  .half 0xbeef
tdat5:  .half 0xbeef
tdat6:  .half 0xbeef
tdat7:  .half 0xbeef
tdat8:  .half 0xbeef

RVTEST_DATA_END
