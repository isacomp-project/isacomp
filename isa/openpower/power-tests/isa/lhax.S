/* OpenPOWER LHAX instruction tests */
/* lhax rD, rA, rB - Load Halfword Algebraic Indexed */
/* Sign-extends the halfword loaded from memory */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic sign-extension tests
   *-------------------------------------------------------------*/

  /* Load positive halfword (0x0001) - no sign extension needed */
  TEST_LDX_SYM_OP( 2, lhax, 0x00000001, tdat, 0 )

  /* Load positive halfword (0x7FFF) - max positive */
  TEST_LDX_SYM_OP( 3, lhax, 0x00007FFF, tdat, 2 )

  /* Load negative halfword (0x8000) - sign extends to 0xFFFF8000 */
  TEST_LDX_SYM_OP( 4, lhax, 0xFFFF8000, tdat, 4 )

  /* Load negative halfword (0xFFFF = -1) - sign extends */
  TEST_LDX_SYM_OP( 5, lhax, 0xFFFFFFFF, tdat, 6 )

  /* Load halfword at different offsets */
  TEST_LDX_SYM_OP( 6, lhax, 0x00001234, tdat, 8 )
  TEST_LDX_SYM_OP( 7, lhax, 0xFFFFABCD, tdat, 10 )

  /*-------------------------------------------------------------
   * Index register tests (rB as offset)
   *-------------------------------------------------------------*/

  TEST_LDX_SYM_OP( 8, lhax, 0x00000001, tdat, 0 )
  TEST_LDX_SYM_OP( 9, lhax, 0x00007FFF, tdat, 2 )
  TEST_LDX_SYM_OP( 10, lhax, 0xFFFF8000, tdat, 4 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA

  .balign 4
tdat:
  .hword 0x0001    /* offset 0: positive */
  .hword 0x7FFF    /* offset 2: max positive */
  .hword 0x8000    /* offset 4: min negative (sign extends) */
  .hword 0xFFFF    /* offset 6: -1 (sign extends) */
  .hword 0x1234    /* offset 8: positive */
  .hword 0xABCD    /* offset 10: negative (sign extends) */

RVTEST_DATA_END
