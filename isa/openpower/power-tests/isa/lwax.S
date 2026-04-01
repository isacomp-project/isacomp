/* OpenPOWER LWAX instruction tests */
/* lwax rD, rA, rB - Load Word Algebraic Indexed */
/* Sign-extends the 32-bit word loaded from memory to 64 bits */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic sign-extension tests (word to doubleword)
   *-------------------------------------------------------------*/

  /* Load positive word (0x00000001) - no sign extension needed */
  TEST_LDX_SYM_OP64( 2, lwax, 0x00000000, 0x00000001, tdat, 0 )

  /* Load positive word (0x7FFFFFFF) - max positive */
  TEST_LDX_SYM_OP64( 3, lwax, 0x00000000, 0x7FFFFFFF, tdat, 4 )

  /* Load negative word (0x80000000) - sign extends to 0xFFFFFFFF80000000 */
  TEST_LDX_SYM_OP64( 4, lwax, 0xFFFFFFFF, 0x80000000, tdat, 8 )

  /* Load negative word (0xFFFFFFFF = -1) - sign extends */
  TEST_LDX_SYM_OP64( 5, lwax, 0xFFFFFFFF, 0xFFFFFFFF, tdat, 12 )

  /* Load word at different offsets */
  TEST_LDX_SYM_OP64( 6, lwax, 0x00000000, 0x12345678, tdat, 16 )
  TEST_LDX_SYM_OP64( 7, lwax, 0xFFFFFFFF, 0xDEADBEEF, tdat, 20 )

  /*-------------------------------------------------------------
   * Index register tests
   *-------------------------------------------------------------*/

  TEST_LDX_SYM_OP64( 8, lwax, 0x00000000, 0x00000001, tdat, 0 )
  TEST_LDX_SYM_OP64( 9, lwax, 0xFFFFFFFF, 0x80000000, tdat, 8 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA

  .balign 8
tdat:
  .long 0x00000001    /* offset 0: positive */
  .long 0x7FFFFFFF    /* offset 4: max positive */
  .long 0x80000000    /* offset 8: min negative (sign extends) */
  .long 0xFFFFFFFF    /* offset 12: -1 (sign extends) */
  .long 0x12345678    /* offset 16: positive */
  .long 0xDEADBEEF    /* offset 20: negative (sign extends) */

RVTEST_DATA_END
