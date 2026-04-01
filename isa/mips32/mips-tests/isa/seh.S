/* MIPS32R2 SEH instruction tests */
/* seh rd, rt - Sign Extend Halfword */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic SEH tests
   *-------------------------------------------------------------*/

  /* Test 2: Zero */
  TEST_CASE( 2, $t0, 0x00000000,
    li $t1, 0x00000000;
    seh $t0, $t1;
  )

  /* Test 3: Positive halfword 0x7FFF */
  TEST_CASE( 3, $t0, 0x00007FFF,
    li $t1, 0x00007FFF;
    seh $t0, $t1;
  )

  /* Test 4: Negative halfword 0x8000 -> sign extended */
  TEST_CASE( 4, $t0, 0xFFFF8000,
    li $t1, 0x00008000;
    seh $t0, $t1;
  )

  /* Test 5: Negative halfword 0xFFFF -> sign extended */
  TEST_CASE( 5, $t0, 0xFFFFFFFF,
    li $t1, 0x0000FFFF;
    seh $t0, $t1;
  )

  /* Test 6: Only low halfword matters */
  TEST_CASE( 6, $t0, 0x00000001,
    li $t1, 0xFFFF0001;
    seh $t0, $t1;
  )

  /* Test 7: Only low halfword matters - negative */
  TEST_CASE( 7, $t0, 0xFFFF8001,
    li $t1, 0x00008001;
    seh $t0, $t1;
  )

  /* Test 8: 0xABCD (negative) */
  TEST_CASE( 8, $t0, 0xFFFFABCD,
    li $t1, 0x1234ABCD;
    seh $t0, $t1;
  )

  /* Test 9: 0x5555 (positive) */
  TEST_CASE( 9, $t0, 0x00005555,
    li $t1, 0xABCD5555;
    seh $t0, $t1;
  )

  /* Test 10: Edge case 0xFFFE */
  TEST_CASE( 10, $t0, 0xFFFFFFFE,
    li $t1, 0x0000FFFE;
    seh $t0, $t1;
  )

  /* Test 11: 0x1234 (positive) */
  TEST_CASE( 11, $t0, 0x00001234,
    li $t1, 0x00001234;
    seh $t0, $t1;
  )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
