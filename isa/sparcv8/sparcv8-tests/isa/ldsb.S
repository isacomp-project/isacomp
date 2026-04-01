/* SPARCv8 LDSB instruction tests (load signed byte) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic load signed byte tests
   * SPARCv8 is big-endian
   *-------------------------------------------------------------*/

  /* Positive bytes (no sign extension) */
  TEST_LD_OP( 2, ldsb, 0x00000000, 0, tdat )   /* 0x00 -> 0x00000000 */
  TEST_LD_OP( 3, ldsb, 0x00000011, 1, tdat )   /* 0x11 -> 0x00000011 */
  TEST_LD_OP( 4, ldsb, 0x00000022, 2, tdat )   /* 0x22 -> 0x00000022 */
  TEST_LD_OP( 5, ldsb, 0x00000033, 3, tdat )   /* 0x33 -> 0x00000033 */

  /* Negative bytes (sign extension) */
  TEST_LD_OP( 6, ldsb, 0xffffffaa, 0, tdat4 )  /* 0xaa -> 0xffffffaa */
  TEST_LD_OP( 7, ldsb, 0xffffffbb, 1, tdat4 )
  TEST_LD_OP( 8, ldsb, 0xffffffcc, 2, tdat4 )
  TEST_LD_OP( 9, ldsb, 0xffffffdd, 3, tdat4 )

  /* 0xff -> -1 */
  TEST_LD_OP( 10, ldsb, 0xffffffff, 0, tdat8 )
  /* 0x7f -> 127 (no sign extension) */
  TEST_LD_OP( 11, ldsb, 0x0000007f, 3, tdat8 )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  .align 4
tdat:
tdat0:  .word 0x00112233
tdat4:  .word 0xaabbccdd
tdat8:  .word 0xff00007f
SPARCV8_DATA_END
