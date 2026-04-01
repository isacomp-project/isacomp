/* MIPS32 LL instruction tests */
/* ll rt, offset(base) - Load Linked */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic LL tests - similar to LW but sets link bit
   *-------------------------------------------------------------*/

  /* Test 2: Load aligned word */
  TEST_LD_OP( 2, ll, 0x00ff00ff, 0, tdat )

  /* Test 3: Load with positive offset */
  TEST_LD_OP( 3, ll, 0xff00ff00, 4, tdat )

  /* Test 4: Load with larger offset */
  TEST_LD_OP( 4, ll, 0x0ff00ff0, 8, tdat )

  /* Test 5: Load with negative offset */
  TEST_LD_OP( 5, ll, 0x00ff00ff, -12, tdat4 )

  /* Test 6: Load from address computed with offset */
  TEST_LD_OP( 6, ll, 0xf00ff00f, 12, tdat )

  /*-------------------------------------------------------------
   * Bypass tests
   *-------------------------------------------------------------*/

  TEST_LD_DEST_BYPASS( 7, 0, ll, 0x00ff00ff, 0, tdat )
  TEST_LD_DEST_BYPASS( 8, 1, ll, 0xff00ff00, 4, tdat )
  TEST_LD_DEST_BYPASS( 9, 2, ll, 0x0ff00ff0, 8, tdat )

  TEST_LD_SRC1_BYPASS( 10, 0, ll, 0x00ff00ff, 0, tdat )
  TEST_LD_SRC1_BYPASS( 11, 1, ll, 0xff00ff00, 4, tdat )
  TEST_LD_SRC1_BYPASS( 12, 2, ll, 0x0ff00ff0, 8, tdat )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
  .align 2
tdat:
tdat1: .word 0x00ff00ff
tdat2: .word 0xff00ff00
tdat3: .word 0x0ff00ff0
tdat4: .word 0xf00ff00f
RVTEST_DATA_END
