/* MIPS32 CLO instruction tests */
/* clo rd, rs - Count Leading Ones */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic CLO tests
   *-------------------------------------------------------------*/

  /* Test 2: All ones -> 32 leading ones */
  TEST_CASE( 2, $t0, 32,
    li $t1, 0xFFFFFFFF;
    clo $t0, $t1;
  )

  /* Test 3: All zeros -> 0 leading ones */
  TEST_CASE( 3, $t0, 0,
    li $t1, 0x00000000;
    clo $t0, $t1;
  )

  /* Test 4: 0x80000000 -> 1 leading one */
  TEST_CASE( 4, $t0, 1,
    li $t1, 0x80000000;
    clo $t0, $t1;
  )

  /* Test 5: 0xFFFFFFFE -> 31 leading ones */
  TEST_CASE( 5, $t0, 31,
    li $t1, 0xFFFFFFFE;
    clo $t0, $t1;
  )

  /* Test 6: 0xFFFF0000 -> 16 leading ones */
  TEST_CASE( 6, $t0, 16,
    li $t1, 0xFFFF0000;
    clo $t0, $t1;
  )

  /* Test 7: 0xFFFFFE00 -> 23 leading ones */
  TEST_CASE( 7, $t0, 23,
    li $t1, 0xFFFFFE00;
    clo $t0, $t1;
  )

  /* Test 8: 0xC0000000 -> 2 leading ones */
  TEST_CASE( 8, $t0, 2,
    li $t1, 0xC0000000;
    clo $t0, $t1;
  )

  /* Test 9: 0xFFF00000 -> 12 leading ones */
  TEST_CASE( 9, $t0, 12,
    li $t1, 0xFFF00000;
    clo $t0, $t1;
  )

  /* Test 10: 0x7FFFFFFF -> 0 leading ones */
  TEST_CASE( 10, $t0, 0,
    li $t1, 0x7FFFFFFF;
    clo $t0, $t1;
  )

  /* Test 11: 0xE0000000 -> 3 leading ones */
  TEST_CASE( 11, $t0, 3,
    li $t1, 0xE0000000;
    clo $t0, $t1;
  )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
