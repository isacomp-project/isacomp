/* MIPS32R2 EXT instruction tests */
/* ext rt, rs, pos, size - Extract Bit Field */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic EXT tests
   * ext rt, rs, pos, size extracts 'size' bits starting at 'pos'
   *-------------------------------------------------------------*/

  /* Test 2: Extract bits 0-7 (low byte) */
  TEST_CASE( 2, $t0, 0x78,
    li $t1, 0x12345678;
    ext $t0, $t1, 0, 8;
  )

  /* Test 3: Extract bits 8-15 (second byte) */
  TEST_CASE( 3, $t0, 0x56,
    li $t1, 0x12345678;
    ext $t0, $t1, 8, 8;
  )

  /* Test 4: Extract bits 16-23 (third byte) */
  TEST_CASE( 4, $t0, 0x34,
    li $t1, 0x12345678;
    ext $t0, $t1, 16, 8;
  )

  /* Test 5: Extract bits 24-31 (high byte) */
  TEST_CASE( 5, $t0, 0x12,
    li $t1, 0x12345678;
    ext $t0, $t1, 24, 8;
  )

  /* Test 6: Extract single bit (bit 0) */
  TEST_CASE( 6, $t0, 1,
    li $t1, 0x00000001;
    ext $t0, $t1, 0, 1;
  )

  /* Test 7: Extract single bit (bit 31) */
  TEST_CASE( 7, $t0, 1,
    li $t1, 0x80000000;
    ext $t0, $t1, 31, 1;
  )

  /* Test 8: Extract low nibble */
  TEST_CASE( 8, $t0, 0xF,
    li $t1, 0x000000FF;
    ext $t0, $t1, 0, 4;
  )

  /* Test 9: Extract high nibble of low byte */
  TEST_CASE( 9, $t0, 0xA,
    li $t1, 0x000000AB;
    ext $t0, $t1, 4, 4;
  )

  /* Test 10: Extract 16 bits from middle */
  TEST_CASE( 10, $t0, 0x3456,
    li $t1, 0x12345678;
    ext $t0, $t1, 8, 16;
  )

  /* Test 11: Extract all 32 bits (special case) */
  TEST_CASE( 11, $t0, 0xABCDEF12,
    li $t1, 0xABCDEF12;
    ext $t0, $t1, 0, 32;
  )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
