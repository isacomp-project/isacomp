/* MIPS32R2 INS instruction tests */
/* ins rt, rs, pos, size - Insert Bit Field */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic INS tests
   * ins rt, rs, pos, size inserts 'size' bits from rs into rt at 'pos'
   *-------------------------------------------------------------*/

  /* Test 2: Insert low byte */
  TEST_CASE( 2, $t0, 0x000000AB,
    li $t0, 0x00000000;
    li $t1, 0x000000AB;
    ins $t0, $t1, 0, 8;
  )

  /* Test 3: Insert second byte */
  TEST_CASE( 3, $t0, 0x0000AB00,
    li $t0, 0x00000000;
    li $t1, 0x000000AB;
    ins $t0, $t1, 8, 8;
  )

  /* Test 4: Insert third byte */
  TEST_CASE( 4, $t0, 0x00AB0000,
    li $t0, 0x00000000;
    li $t1, 0x000000AB;
    ins $t0, $t1, 16, 8;
  )

  /* Test 5: Insert high byte */
  TEST_CASE( 5, $t0, 0xAB000000,
    li $t0, 0x00000000;
    li $t1, 0x000000AB;
    ins $t0, $t1, 24, 8;
  )

  /* Test 6: Preserve other bits */
  TEST_CASE( 6, $t0, 0xFFFFABFF,
    li $t0, 0xFFFFFFFF;
    li $t1, 0x000000AB;
    ins $t0, $t1, 8, 8;
  )

  /* Test 7: Insert single bit to 0 */
  TEST_CASE( 7, $t0, 0xFFFFFFFE,
    li $t0, 0xFFFFFFFF;
    li $t1, 0x00000000;
    ins $t0, $t1, 0, 1;
  )

  /* Test 8: Insert single bit to 1 */
  TEST_CASE( 8, $t0, 0x00000001,
    li $t0, 0x00000000;
    li $t1, 0x00000001;
    ins $t0, $t1, 0, 1;
  )

  /* Test 9: Insert 16 bits in middle */
  TEST_CASE( 9, $t0, 0x12ABCD78,
    li $t0, 0x12345678;
    li $t1, 0x0000ABCD;
    ins $t0, $t1, 8, 16;
  )

  /* Test 10: Insert 4 bits */
  TEST_CASE( 10, $t0, 0x1234567F,
    li $t0, 0x12345678;
    li $t1, 0x0000000F;
    ins $t0, $t1, 0, 4;
  )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
