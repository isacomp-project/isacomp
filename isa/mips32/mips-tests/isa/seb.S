/* MIPS32R2 SEB instruction tests */
/* seb rd, rt - Sign Extend Byte */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic SEB tests
   *-------------------------------------------------------------*/

  /* Test 2: Positive byte (no sign extension) */
  TEST_CASE( 2, $t0, 0x00000000,
    li $t1, 0x00000000;
    seb $t0, $t1;
  )

  /* Test 3: Positive byte 0x7F */
  TEST_CASE( 3, $t0, 0x0000007F,
    li $t1, 0x0000007F;
    seb $t0, $t1;
  )

  /* Test 4: Negative byte 0x80 -> sign extended */
  TEST_CASE( 4, $t0, 0xFFFFFF80,
    li $t1, 0x00000080;
    seb $t0, $t1;
  )

  /* Test 5: Negative byte 0xFF -> sign extended */
  TEST_CASE( 5, $t0, 0xFFFFFFFF,
    li $t1, 0x000000FF;
    seb $t0, $t1;
  )

  /* Test 6: Only low byte matters */
  TEST_CASE( 6, $t0, 0x00000001,
    li $t1, 0xFFFFFF01;
    seb $t0, $t1;
  )

  /* Test 7: Only low byte matters - negative */
  TEST_CASE( 7, $t0, 0xFFFFFF81,
    li $t1, 0x00000081;
    seb $t0, $t1;
  )

  /* Test 8: 0xAB (negative) */
  TEST_CASE( 8, $t0, 0xFFFFFFAB,
    li $t1, 0x123456AB;
    seb $t0, $t1;
  )

  /* Test 9: 0x55 (positive) */
  TEST_CASE( 9, $t0, 0x00000055,
    li $t1, 0xABCDEF55;
    seb $t0, $t1;
  )

  /* Test 10: Edge case 0xFE */
  TEST_CASE( 10, $t0, 0xFFFFFFFE,
    li $t1, 0x000000FE;
    seb $t0, $t1;
  )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
