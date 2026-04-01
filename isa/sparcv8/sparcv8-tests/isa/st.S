/* SPARCv8 ST instruction tests (store word) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic store tests
   *-------------------------------------------------------------*/

  TEST_ST_OP( 2, st, ld, 0x00aa00aa, 0, tdat )
  TEST_ST_OP( 3, st, ld, 0xaa00aa00, 0, tdat4 )
  TEST_ST_OP( 4, st, ld, 0x0aa00aa0, 0, tdat8 )
  TEST_ST_OP( 5, st, ld, 0xa00aa00a, 0, tdat12 )

  /* Store with positive offset */
  TEST_ST_OP( 6, st, ld, 0x12345678, 4, tdat )
  TEST_ST_OP( 7, st, ld, 0x87654321, 8, tdat )

  /* Store with negative offset */
  TEST_ST_OP( 8, st, ld, 0xdeadbeef, -4, tdat8 )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  .align 4
tdat:
tdat0:  .word 0xdeadbeef
tdat4:  .word 0xdeadbeef
tdat8:  .word 0xdeadbeef
tdat12: .word 0xdeadbeef
SPARCV8_DATA_END
