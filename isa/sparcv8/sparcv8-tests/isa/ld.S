/* SPARCv8 LD instruction tests (load word) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic load tests
   *-------------------------------------------------------------*/

  /* Load from test data area */
  TEST_LD_OP( 2, ld, 0x00ff00ff, 0, tdat )
  TEST_LD_OP( 3, ld, 0xff00ff00, 0, tdat4 )
  TEST_LD_OP( 4, ld, 0x0ff00ff0, 0, tdat8 )
  TEST_LD_OP( 5, ld, 0xf00ff00f, 0, tdat12 )

  /* Load with offset */
  TEST_LD_OP( 6, ld, 0xff00ff00, 4, tdat )
  TEST_LD_OP( 7, ld, 0x0ff00ff0, 8, tdat )
  TEST_LD_OP( 8, ld, 0xf00ff00f, 12, tdat )

  /* Load with negative offset */
  TEST_LD_OP( 9, ld, 0x00ff00ff, -12, tdat12 )
  TEST_LD_OP( 10, ld, 0xff00ff00, -8, tdat12 )
  TEST_LD_OP( 11, ld, 0x0ff00ff0, -4, tdat12 )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  .align 4
tdat:
tdat0:  .word 0x00ff00ff
tdat4:  .word 0xff00ff00
tdat8:  .word 0x0ff00ff0
tdat12: .word 0xf00ff00f
SPARCV8_DATA_END
