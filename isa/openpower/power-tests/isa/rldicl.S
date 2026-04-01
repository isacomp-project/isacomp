/* OpenPOWER RLDICL instruction tests */
/* rldicl rA, rS, SH, MB - Rotate Left Doubleword Immediate then Clear Left */
/* Rotates 64-bit value left by SH, clears bits 0 to MB-1 */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic rotation tests (MB=0, no masking)
   *-------------------------------------------------------------*/

  /* No rotation, no masking */
  TEST_ROTATE_OP64( 2, rldicl, 0x12345678, 0x9ABCDEF0, 0x12345678, 0x9ABCDEF0, 0, 0 )

  /* Rotate left by 4 bits */
  /* 0x123456789ABCDEF0 rotl 4 = 0x23456789ABCDEF01 */
  TEST_ROTATE_OP64( 3, rldicl, 0x23456789, 0xABCDEF01, 0x12345678, 0x9ABCDEF0, 4, 0 )

  /* Rotate left by 32 bits (swap words) */
  TEST_ROTATE_OP64( 4, rldicl, 0x9ABCDEF0, 0x12345678, 0x12345678, 0x9ABCDEF0, 32, 0 )

  /*-------------------------------------------------------------
   * Shift right using rldicl (srdi: rotate left by 64-n, mask from n)
   * srdi rA, rS, n == rldicl rA, rS, 64-n, n
   *-------------------------------------------------------------*/

  /* Shift right by 4: 0x123456789ABCDEF0 >> 4 = 0x0123456789ABCDEF */
  TEST_ROTATE_OP64( 5, rldicl, 0x01234567, 0x89ABCDEF, 0x12345678, 0x9ABCDEF0, 60, 4 )

  /* Shift right by 32: get upper word in lower position */
  TEST_ROTATE_OP64( 6, rldicl, 0x00000000, 0x12345678, 0x12345678, 0x9ABCDEF0, 32, 32 )

  /*-------------------------------------------------------------
   * Clear left bits (clrldi: no rotation, just masking)
   * clrldi rA, rS, n == rldicl rA, rS, 0, n
   *-------------------------------------------------------------*/

  /* Clear upper 32 bits */
  TEST_ROTATE_OP64( 7, rldicl, 0x00000000, 0x9ABCDEF0, 0x12345678, 0x9ABCDEF0, 0, 32 )

  /* Clear upper 48 bits (keep lower 16 bits) */
  TEST_ROTATE_OP64( 8, rldicl, 0x00000000, 0x0000DEF0, 0x12345678, 0x9ABCDEF0, 0, 48 )

  /* Clear upper 56 bits (keep lower 8 bits) */
  TEST_ROTATE_OP64( 9, rldicl, 0x00000000, 0x000000F0, 0x12345678, 0x9ABCDEF0, 0, 56 )

  /*-------------------------------------------------------------
   * Extract bit fields
   *-------------------------------------------------------------*/

  /* Extract bits 32-63 (lower word) */
  TEST_ROTATE_OP64( 10, rldicl, 0x00000000, 0x9ABCDEF0, 0x12345678, 0x9ABCDEF0, 0, 32 )

  /* Extract byte: rotate and mask */
  /* Get byte at position 4 (bits 32-39): rotl by 40 moves bits 32-39 to bits 56-63 */
  TEST_ROTATE_OP64( 11, rldicl, 0x00000000, 0x0000009A, 0x12345678, 0x9ABCDEF0, 40, 56 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
