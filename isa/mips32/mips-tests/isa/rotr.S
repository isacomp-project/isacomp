/* MIPS32R2 ROTR instruction tests */
/* rotr rd, rt, sa - Rotate Right */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic ROTR tests
   *-------------------------------------------------------------*/

  /* Test 2: Rotate by 0 (no change) */
  TEST_CASE( 2, $t0, 0x12345678,
    li $t1, 0x12345678;
    rotr $t0, $t1, 0;
  )

  /* Test 3: Rotate by 4 */
  TEST_CASE( 3, $t0, 0x81234567,
    li $t1, 0x12345678;
    rotr $t0, $t1, 4;
  )

  /* Test 4: Rotate by 8 */
  TEST_CASE( 4, $t0, 0x78123456,
    li $t1, 0x12345678;
    rotr $t0, $t1, 8;
  )

  /* Test 5: Rotate by 16 */
  TEST_CASE( 5, $t0, 0x56781234,
    li $t1, 0x12345678;
    rotr $t0, $t1, 16;
  )

  /* Test 6: Rotate by 24 */
  TEST_CASE( 6, $t0, 0x34567812,
    li $t1, 0x12345678;
    rotr $t0, $t1, 24;
  )

  /* Test 7: Rotate by 1 */
  TEST_CASE( 7, $t0, 0x8000000F,
    li $t1, 0x0000001F;
    rotr $t0, $t1, 1;
  )

  /* Test 8: Rotate by 31 */
  TEST_CASE( 8, $t0, 0x0000003E,
    li $t1, 0x0000001F;
    rotr $t0, $t1, 31;
  )

  /* Test 9: Rotate 0x80000001 by 1 */
  TEST_CASE( 9, $t0, 0xC0000000,
    li $t1, 0x80000001;
    rotr $t0, $t1, 1;
  )

  /* Test 10: Rotate all ones (stays same) */
  TEST_CASE( 10, $t0, 0xFFFFFFFF,
    li $t1, 0xFFFFFFFF;
    rotr $t0, $t1, 17;
  )

  /* Test 11: Rotate zero (stays same) */
  TEST_CASE( 11, $t0, 0x00000000,
    li $t1, 0x00000000;
    rotr $t0, $t1, 13;
  )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
