/* OpenPOWER CMPB instruction tests */
/* cmpb rA, rS, rB - Compare Bytes */
/* Each byte of rA is 0xFF if corresponding bytes of rS and rB match */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic byte comparison tests (32-bit)
   *-------------------------------------------------------------*/

  /* All bytes equal: result is 0xFFFFFFFF */
  TEST_CMPB_OP( 2, 0xFFFFFFFF, 0x12345678, 0x12345678 )

  /* No bytes equal: result is 0x00000000 */
  TEST_CMPB_OP( 3, 0x00000000, 0x12345678, 0x87654321 )

  /* Only first byte equal */
  TEST_CMPB_OP( 4, 0x000000FF, 0x12345678, 0x00000078 )

  /* Only last byte equal */
  TEST_CMPB_OP( 5, 0xFF000000, 0x12345678, 0x12000000 )

  /* Two bytes equal (bytes 0 and 2) */
  TEST_CMPB_OP( 6, 0x00FF00FF, 0x12345678, 0x00340078 )

  /* Alternating bytes equal */
  TEST_CMPB_OP( 7, 0xFF00FF00, 0xAABBCCDD, 0xAA00CC00 )

  /* Zero values */
  TEST_CMPB_OP( 8, 0xFFFFFFFF, 0x00000000, 0x00000000 )

  /* All 0xFF values */
  TEST_CMPB_OP( 9, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF )

  /*-------------------------------------------------------------
   * 64-bit byte comparison tests
   *-------------------------------------------------------------*/

  /* All 8 bytes equal */
  TEST_CMPB_OP64( 10, 0xFFFFFFFF, 0xFFFFFFFF, 0x12345678, 0x9ABCDEF0, 0x12345678, 0x9ABCDEF0 )

  /* No bytes equal */
  TEST_CMPB_OP64( 11, 0x00000000, 0x00000000, 0x12345678, 0x9ABCDEF0, 0xFEDCBA98, 0x76543210 )

  /* Upper word matches only */
  TEST_CMPB_OP64( 12, 0xFFFFFFFF, 0x00000000, 0x12345678, 0x00000000, 0x12345678, 0xFFFFFFFF )

  /* Lower word matches only */
  TEST_CMPB_OP64( 13, 0x00000000, 0xFFFFFFFF, 0x00000000, 0x12345678, 0xFFFFFFFF, 0x12345678 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
