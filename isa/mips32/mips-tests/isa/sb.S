/* MIPS32 SB instruction tests */
/* Based on riscv-tests structure */
/* SB stores the least significant byte */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic tests
   *-------------------------------------------------------------*/

  TEST_ST_OP( 2, lb, sb, 0xffffffaa, 0, tdat )
  TEST_ST_OP( 3, lb, sb, 0x00000000, 1, tdat )
  TEST_ST_OP( 4, lb, sb, 0xffffffa0, 2, tdat )
  TEST_ST_OP( 5, lb, sb, 0x0000000a, 3, tdat )

  /* Test with negative offset */
  TEST_ST_OP( 6, lb, sb, 0xffffffaa, -3, tdat8 )
  TEST_ST_OP( 7, lb, sb, 0x00000000, -2, tdat8 )
  TEST_ST_OP( 8, lb, sb, 0xffffffa0, -1, tdat8 )
  TEST_ST_OP( 9, lb, sb, 0x0000000a, 0, tdat8 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_ST_SRC12_BYPASS( 10, 0, 0, lb, sb, 0xffffffdd, 0, tdat )
  TEST_ST_SRC12_BYPASS( 11, 0, 1, lb, sb, 0xffffffcd, 1, tdat )
  TEST_ST_SRC12_BYPASS( 12, 0, 2, lb, sb, 0xffffffcc, 2, tdat )
  TEST_ST_SRC12_BYPASS( 13, 1, 0, lb, sb, 0xffffffbc, 3, tdat )
  TEST_ST_SRC12_BYPASS( 14, 1, 1, lb, sb, 0xffffffbb, 4, tdat )
  TEST_ST_SRC12_BYPASS( 15, 2, 0, lb, sb, 0xffffffab, 5, tdat )

  TEST_ST_SRC21_BYPASS( 16, 0, 0, lb, sb, 0x00000033, 0, tdat )
  TEST_ST_SRC21_BYPASS( 17, 0, 1, lb, sb, 0x00000023, 1, tdat )
  TEST_ST_SRC21_BYPASS( 18, 0, 2, lb, sb, 0x00000022, 2, tdat )
  TEST_ST_SRC21_BYPASS( 19, 1, 0, lb, sb, 0x00000012, 3, tdat )
  TEST_ST_SRC21_BYPASS( 20, 1, 1, lb, sb, 0x00000011, 4, tdat )
  TEST_ST_SRC21_BYPASS( 21, 2, 0, lb, sb, 0x00000001, 5, tdat )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA

tdat:
tdat1:  .byte 0xef
tdat2:  .byte 0xef
tdat3:  .byte 0xef
tdat4:  .byte 0xef
tdat5:  .byte 0xef
tdat6:  .byte 0xef
tdat7:  .byte 0xef
tdat8:  .byte 0xef

RVTEST_DATA_END
