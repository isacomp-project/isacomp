/* MIPS32R2 ROTRV instruction tests */
/* rotrv rd, rt, rs - Rotate Right Variable */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic ROTRV tests
   *-------------------------------------------------------------*/

  /* Test 2: Rotate by 0 (no change) */
  TEST_CASE( 2, $t0, 0x12345678,
    li $t1, 0x12345678;
    li $t2, 0;
    rotrv $t0, $t1, $t2;
  )

  /* Test 3: Rotate by 4 */
  TEST_CASE( 3, $t0, 0x81234567,
    li $t1, 0x12345678;
    li $t2, 4;
    rotrv $t0, $t1, $t2;
  )

  /* Test 4: Rotate by 8 */
  TEST_CASE( 4, $t0, 0x78123456,
    li $t1, 0x12345678;
    li $t2, 8;
    rotrv $t0, $t1, $t2;
  )

  /* Test 5: Rotate by 16 */
  TEST_CASE( 5, $t0, 0x56781234,
    li $t1, 0x12345678;
    li $t2, 16;
    rotrv $t0, $t1, $t2;
  )

  /* Test 6: Rotate by 24 */
  TEST_CASE( 6, $t0, 0x34567812,
    li $t1, 0x12345678;
    li $t2, 24;
    rotrv $t0, $t1, $t2;
  )

  /* Test 7: Only low 5 bits of shift amount used */
  TEST_CASE( 7, $t0, 0x12345678,
    li $t1, 0x12345678;
    li $t2, 32;
    rotrv $t0, $t1, $t2;
  )

  /* Test 8: Only low 5 bits: 36 & 31 = 4 */
  TEST_CASE( 8, $t0, 0x81234567,
    li $t1, 0x12345678;
    li $t2, 36;
    rotrv $t0, $t1, $t2;
  )

  /* Test 9: Rotate by 1 */
  TEST_CASE( 9, $t0, 0x8000000F,
    li $t1, 0x0000001F;
    li $t2, 1;
    rotrv $t0, $t1, $t2;
  )

  /* Test 10: Rotate all ones (stays same) */
  TEST_CASE( 10, $t0, 0xFFFFFFFF,
    li $t1, 0xFFFFFFFF;
    li $t2, 17;
    rotrv $t0, $t1, $t2;
  )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
