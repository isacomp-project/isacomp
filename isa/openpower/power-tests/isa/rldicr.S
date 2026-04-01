/* OpenPOWER RLDICR instruction tests */
/* rldicr rA, rS, SH, ME - Rotate Left Doubleword Immediate then Clear Right */
/* Rotates 64-bit value left by SH, clears bits ME+1 to 63 */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic rotation tests (ME=63, no masking)
   *-------------------------------------------------------------*/

  /* No rotation, no masking */
  TEST_ROTATE_OP64( 2, rldicr, 0x12345678, 0x9ABCDEF0, 0x12345678, 0x9ABCDEF0, 0, 63 )

  /* Rotate left by 4 bits */
  TEST_ROTATE_OP64( 3, rldicr, 0x23456789, 0xABCDEF01, 0x12345678, 0x9ABCDEF0, 4, 63 )

  /* Rotate left by 32 bits (swap words) */
  TEST_ROTATE_OP64( 4, rldicr, 0x9ABCDEF0, 0x12345678, 0x12345678, 0x9ABCDEF0, 32, 63 )

  /*-------------------------------------------------------------
   * Shift left using rldicr (sldi: rotate left by n, mask ends at 63-n)
   * sldi rA, rS, n == rldicr rA, rS, n, 63-n
   *-------------------------------------------------------------*/

  /* Shift left by 4: 0x123456789ABCDEF0 << 4 = 0x23456789ABCDEF00 */
  TEST_ROTATE_OP64( 5, rldicr, 0x23456789, 0xABCDEF00, 0x12345678, 0x9ABCDEF0, 4, 59 )

  /* Shift left by 32: move lower word to upper */
  TEST_ROTATE_OP64( 6, rldicr, 0x9ABCDEF0, 0x00000000, 0x12345678, 0x9ABCDEF0, 32, 31 )

  /* Shift left by 1 */
  TEST_ROTATE_OP64( 7, rldicr, 0x2468ACF1, 0x3579BDE0, 0x12345678, 0x9ABCDEF0, 1, 62 )

  /*-------------------------------------------------------------
   * Clear right bits (clrrdi: no rotation, just masking)
   * clrrdi rA, rS, n == rldicr rA, rS, 0, 63-n
   *-------------------------------------------------------------*/

  /* Clear lower 32 bits */
  TEST_ROTATE_OP64( 8, rldicr, 0x12345678, 0x00000000, 0x12345678, 0x9ABCDEF0, 0, 31 )

  /* Clear lower 48 bits (keep upper 16 bits) */
  TEST_ROTATE_OP64( 9, rldicr, 0x12340000, 0x00000000, 0x12345678, 0x9ABCDEF0, 0, 15 )

  /* Clear lower 56 bits (keep upper 8 bits) */
  TEST_ROTATE_OP64( 10, rldicr, 0x12000000, 0x00000000, 0x12345678, 0x9ABCDEF0, 0, 7 )

  /*-------------------------------------------------------------
   * Extract and position bit fields
   *-------------------------------------------------------------*/

  /* Move lower byte to upper byte position */
  /* Shift 0x..F0 left by 56, result = 0xF000000000000000 */
  TEST_ROTATE_OP64( 11, rldicr, 0xF0000000, 0x00000000, 0x00000000, 0x000000F0, 56, 7 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
