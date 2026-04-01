/* OpenPOWER RLWINM instruction tests */
/* rlwinm rA, rS, SH, MB, ME - Rotate Left Word Immediate then AND with Mask */
/* Rotates 32-bit word left by SH, then ANDs with mask from MB to ME */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic rotation tests (full mask MB=0, ME=31)
   *-------------------------------------------------------------*/

  /* No rotation: value unchanged */
  TEST_ROTATE_OP( 2, rlwinm, 0x12345678, 0x12345678, 0, 0, 31 )

  /* Rotate left by 4 bits */
  /* 0x12345678 rotl 4 = 0x23456781 */
  TEST_ROTATE_OP( 3, rlwinm, 0x23456781, 0x12345678, 4, 0, 31 )

  /* Rotate left by 8 bits */
  /* 0x12345678 rotl 8 = 0x34567812 */
  TEST_ROTATE_OP( 4, rlwinm, 0x34567812, 0x12345678, 8, 0, 31 )

  /* Rotate left by 16 bits (swap halfwords) */
  /* 0x12345678 rotl 16 = 0x56781234 */
  TEST_ROTATE_OP( 5, rlwinm, 0x56781234, 0x12345678, 16, 0, 31 )

  /* Rotate left by 24 bits */
  /* 0x12345678 rotl 24 = 0x78123456 */
  TEST_ROTATE_OP( 6, rlwinm, 0x78123456, 0x12345678, 24, 0, 31 )

  /*-------------------------------------------------------------
   * Shift left using rlwinm (MB=0, ME=31-SH)
   * slwi rA, rS, n == rlwinm rA, rS, n, 0, 31-n
   *-------------------------------------------------------------*/

  /* Shift left by 1: slwi r8, r9, 1 */
  TEST_ROTATE_OP( 7, rlwinm, 0x00000002, 0x00000001, 1, 0, 30 )

  /* Shift left by 4: 0x12345678 << 4 = 0x23456780 */
  TEST_ROTATE_OP( 8, rlwinm, 0x23456780, 0x12345678, 4, 0, 27 )

  /* Shift left by 8 */
  TEST_ROTATE_OP( 9, rlwinm, 0x34567800, 0x12345678, 8, 0, 23 )

  /*-------------------------------------------------------------
   * Shift right using rlwinm (MB=SH, ME=31)
   * srwi rA, rS, n == rlwinm rA, rS, 32-n, n, 31
   *-------------------------------------------------------------*/

  /* Shift right by 4: 0x12345678 >> 4 = 0x01234567 */
  TEST_ROTATE_OP( 10, rlwinm, 0x01234567, 0x12345678, 28, 4, 31 )

  /* Shift right by 8: 0x12345678 >> 8 = 0x00123456 */
  TEST_ROTATE_OP( 11, rlwinm, 0x00123456, 0x12345678, 24, 8, 31 )

  /* Shift right by 16: 0x12345678 >> 16 = 0x00001234 */
  TEST_ROTATE_OP( 12, rlwinm, 0x00001234, 0x12345678, 16, 16, 31 )

  /*-------------------------------------------------------------
   * Clear left bits using rlwinm (clrlwi: SH=0)
   * clrlwi rA, rS, n == rlwinm rA, rS, 0, n, 31
   *-------------------------------------------------------------*/

  /* Clear upper 16 bits */
  TEST_ROTATE_OP( 13, rlwinm, 0x00005678, 0x12345678, 0, 16, 31 )

  /* Clear upper 24 bits */
  TEST_ROTATE_OP( 14, rlwinm, 0x00000078, 0x12345678, 0, 24, 31 )

  /*-------------------------------------------------------------
   * Clear right bits using rlwinm (clrrwi: SH=0)
   * clrrwi rA, rS, n == rlwinm rA, rS, 0, 0, 31-n
   *-------------------------------------------------------------*/

  /* Clear lower 4 bits */
  TEST_ROTATE_OP( 15, rlwinm, 0x12345670, 0x12345678, 0, 0, 27 )

  /* Clear lower 8 bits */
  TEST_ROTATE_OP( 16, rlwinm, 0x12345600, 0x12345678, 0, 0, 23 )

  /*-------------------------------------------------------------
   * Extract bit field
   *-------------------------------------------------------------*/

  /* Extract bits 8-15 (second byte) */
  /* 0x12345678, rotate right 8 (= rotl 24), mask 24-31 */
  TEST_ROTATE_OP( 17, rlwinm, 0x00000056, 0x12345678, 24, 24, 31 )

  /* Extract bits 16-23 (third byte) */
  TEST_ROTATE_OP( 18, rlwinm, 0x00000034, 0x12345678, 16, 24, 31 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
