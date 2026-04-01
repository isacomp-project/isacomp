/* MIPS32 CLZ instruction tests */
/* clz rd, rs - Count Leading Zeros */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic CLZ tests
   *-------------------------------------------------------------*/

  /* Test 2: All zeros -> 32 leading zeros */
  TEST_CASE( 2, $t0, 32,
    li $t1, 0x00000000;
    clz $t0, $t1;
  )

  /* Test 3: All ones -> 0 leading zeros */
  TEST_CASE( 3, $t0, 0,
    li $t1, 0xFFFFFFFF;
    clz $t0, $t1;
  )

  /* Test 4: 0x80000000 -> 0 leading zeros */
  TEST_CASE( 4, $t0, 0,
    li $t1, 0x80000000;
    clz $t0, $t1;
  )

  /* Test 5: 0x00000001 -> 31 leading zeros */
  TEST_CASE( 5, $t0, 31,
    li $t1, 0x00000001;
    clz $t0, $t1;
  )

  /* Test 6: 0x00008000 -> 16 leading zeros */
  TEST_CASE( 6, $t0, 16,
    li $t1, 0x00008000;
    clz $t0, $t1;
  )

  /* Test 7: 0x00000100 -> 23 leading zeros */
  TEST_CASE( 7, $t0, 23,
    li $t1, 0x00000100;
    clz $t0, $t1;
  )

  /* Test 8: 0x40000000 -> 1 leading zero */
  TEST_CASE( 8, $t0, 1,
    li $t1, 0x40000000;
    clz $t0, $t1;
  )

  /* Test 9: 0x00100000 -> 11 leading zeros */
  TEST_CASE( 9, $t0, 11,
    li $t1, 0x00100000;
    clz $t0, $t1;
  )

  /* Test 10: 0x0000FFFF -> 16 leading zeros */
  TEST_CASE( 10, $t0, 16,
    li $t1, 0x0000FFFF;
    clz $t0, $t1;
  )

  /* Test 11: 0x7FFFFFFF -> 1 leading zero */
  TEST_CASE( 11, $t0, 1,
    li $t1, 0x7FFFFFFF;
    clz $t0, $t1;
  )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
