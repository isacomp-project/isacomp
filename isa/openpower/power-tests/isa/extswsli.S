/* OpenPOWER EXTSWSLI instruction tests */
/* extswsli rA, rS, SH - Extend Sign Word and Shift Left Immediate */
/* Sign-extends low 32 bits of rS to 64 bits, then shifts left by SH */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic sign extension tests (no shift)
   *-------------------------------------------------------------*/

  /* Positive word, no shift: 0x00000001 -> 0x0000000000000001 */
  TEST_EXTSWSLI_OP64( 2, 0x00000000, 0x00000001, 0x00000001, 0 )

  /* Max positive word: 0x7FFFFFFF -> 0x000000007FFFFFFF */
  TEST_EXTSWSLI_OP64( 3, 0x00000000, 0x7FFFFFFF, 0x7FFFFFFF, 0 )

  /* Negative word (MSB set): 0x80000000 -> 0xFFFFFFFF80000000 */
  TEST_EXTSWSLI_OP64( 4, 0xFFFFFFFF, 0x80000000, 0x80000000, 0 )

  /* -1 as word: 0xFFFFFFFF -> 0xFFFFFFFFFFFFFFFF */
  TEST_EXTSWSLI_OP64( 5, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0 )

  /*-------------------------------------------------------------
   * Sign extension with shift left
   *-------------------------------------------------------------*/

  /* Positive value shifted left by 1 */
  /* 0x00000001 sign-ext -> 0x0000000000000001, << 1 = 0x0000000000000002 */
  TEST_EXTSWSLI_OP64( 6, 0x00000000, 0x00000002, 0x00000001, 1 )

  /* Positive value shifted left by 4 */
  /* 0x00000001 << 4 = 0x0000000000000010 */
  TEST_EXTSWSLI_OP64( 7, 0x00000000, 0x00000010, 0x00000001, 4 )

  /* Negative value shifted left by 1 */
  /* 0xFFFFFFFF sign-ext -> 0xFFFFFFFFFFFFFFFF, << 1 = 0xFFFFFFFFFFFFFFFE */
  TEST_EXTSWSLI_OP64( 8, 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFF, 1 )

  /* Negative value shifted left by 4 */
  /* 0xFFFFFFFF << 4 = 0xFFFFFFFFFFFFFFF0 */
  TEST_EXTSWSLI_OP64( 9, 0xFFFFFFFF, 0xFFFFFFF0, 0xFFFFFFFF, 4 )

  /* 0x80000000 shifted left by 1 */
  /* 0x80000000 sign-ext -> 0xFFFFFFFF80000000, << 1 = 0xFFFFFFFF00000000 */
  TEST_EXTSWSLI_OP64( 10, 0xFFFFFFFF, 0x00000000, 0x80000000, 1 )

  /*-------------------------------------------------------------
   * Larger shifts
   *-------------------------------------------------------------*/

  /* Shift by 32 - moves word to upper half */
  /* 0x00000001 << 32 = 0x0000000100000000 */
  TEST_EXTSWSLI_OP64( 11, 0x00000001, 0x00000000, 0x00000001, 32 )

  /* 0x7FFFFFFF << 32 = 0x7FFFFFFF00000000 */
  TEST_EXTSWSLI_OP64( 12, 0x7FFFFFFF, 0x00000000, 0x7FFFFFFF, 32 )

  /* Negative shifted by 32 */
  /* 0x80000000 sign-ext << 32 = 0x8000000000000000 */
  TEST_EXTSWSLI_OP64( 13, 0x80000000, 0x00000000, 0x80000000, 32 )

  /* Shift by 63 - max shift */
  /* 0x00000001 << 63 = 0x8000000000000000 */
  TEST_EXTSWSLI_OP64( 14, 0x80000000, 0x00000000, 0x00000001, 63 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
