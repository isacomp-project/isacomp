/* MIPS32 MOVN instruction tests */
/* movn rd, rs, rt - Move if Not Zero */
/* rd = rs if rt != 0 */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic MOVN tests - move when rt is not zero
   *-------------------------------------------------------------*/

  /* Test 2: rt = 1, should move */
  TEST_CASE( 2, $t0, 42,
    li $t0, 0;
    li $t1, 42;
    li $t2, 1;
    movn $t0, $t1, $t2;
  )

  /* Test 3: rt = 0, should not move */
  TEST_CASE( 3, $t0, 100,
    li $t0, 100;
    li $t1, 42;
    li $t2, 0;
    movn $t0, $t1, $t2;
  )

  /* Test 4: rt = 0xFFFFFFFF, should move */
  TEST_CASE( 4, $t0, 0x12345678,
    li $t0, 0;
    li $t1, 0x12345678;
    li $t2, 0xFFFFFFFF;
    movn $t0, $t1, $t2;
  )

  /* Test 5: rt = 0x80000000, should move */
  TEST_CASE( 5, $t0, 0xABCDEF,
    li $t0, 0;
    li $t1, 0xABCDEF;
    li $t2, 0x80000000;
    movn $t0, $t1, $t2;
  )

  /* Test 6: rt = 0, should not move */
  TEST_CASE( 6, $t0, 999,
    li $t0, 999;
    li $t1, 111;
    li $t2, 0;
    movn $t0, $t1, $t2;
  )

  /* Test 7: rt = 100, should move */
  TEST_CASE( 7, $t0, 25,
    li $t0, 50;
    li $t1, 25;
    li $t2, 100;
    movn $t0, $t1, $t2;
  )

  /* Test 8: Source equals dest when moving */
  TEST_CASE( 8, $t1, 77,
    li $t1, 77;
    li $t2, 1;
    movn $t1, $t1, $t2;
  )

  /* Test 9: Move to zero register (no effect) */
test_9:
    li TESTNUM, 9
    li $t1, 42
    li $t2, 1
    movn $zero, $t1, $t2
    bne $zero, $zero, fail
    nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
