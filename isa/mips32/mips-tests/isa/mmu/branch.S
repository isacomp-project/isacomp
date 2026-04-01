/* MIPS32 BGEZ/BLTZ/BGTZ/BLEZ Tests */
/* Tests REGIMM format branch instructions */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * BGEZ tests - Branch if Greater than or Equal to Zero
   *-------------------------------------------------------------*/

  /* Test 2: BGEZ with positive - should branch */
test_2:
    li TESTNUM, 2
    li $t1, 5
    bgez $t1, test_2_pass
    nop
    j fail
    nop
test_2_pass:

  /* Test 3: BGEZ with zero - should branch */
test_3:
    li TESTNUM, 3
    li $t1, 0
    bgez $t1, test_3_pass
    nop
    j fail
    nop
test_3_pass:

  /* Test 4: BGEZ with negative - should NOT branch */
test_4:
    li TESTNUM, 4
    li $t1, -5
    bgez $t1, fail
    nop

  /*-------------------------------------------------------------
   * BLTZ tests - Branch if Less Than Zero
   *-------------------------------------------------------------*/

  /* Test 5: BLTZ with negative - should branch */
test_5:
    li TESTNUM, 5
    li $t1, -5
    bltz $t1, test_5_pass
    nop
    j fail
    nop
test_5_pass:

  /* Test 6: BLTZ with zero - should NOT branch */
test_6:
    li TESTNUM, 6
    li $t1, 0
    bltz $t1, fail
    nop

  /* Test 7: BLTZ with positive - should NOT branch */
test_7:
    li TESTNUM, 7
    li $t1, 5
    bltz $t1, fail
    nop

  /*-------------------------------------------------------------
   * BGTZ tests - Branch if Greater Than Zero
   *-------------------------------------------------------------*/

  /* Test 8: BGTZ with positive - should branch */
test_8:
    li TESTNUM, 8
    li $t1, 5
    bgtz $t1, test_8_pass
    nop
    j fail
    nop
test_8_pass:

  /* Test 9: BGTZ with zero - should NOT branch */
test_9:
    li TESTNUM, 9
    li $t1, 0
    bgtz $t1, fail
    nop

  /* Test 10: BGTZ with negative - should NOT branch */
test_10:
    li TESTNUM, 10
    li $t1, -5
    bgtz $t1, fail
    nop

  /*-------------------------------------------------------------
   * BLEZ tests - Branch if Less than or Equal to Zero
   *-------------------------------------------------------------*/

  /* Test 11: BLEZ with negative - should branch */
test_11:
    li TESTNUM, 11
    li $t1, -5
    blez $t1, test_11_pass
    nop
    j fail
    nop
test_11_pass:

  /* Test 12: BLEZ with zero - should branch */
test_12:
    li TESTNUM, 12
    li $t1, 0
    blez $t1, test_12_pass
    nop
    j fail
    nop
test_12_pass:

  /* Test 13: BLEZ with positive - should NOT branch */
test_13:
    li TESTNUM, 13
    li $t1, 5
    blez $t1, fail
    nop

  /*-------------------------------------------------------------
   * Edge cases
   *-------------------------------------------------------------*/

  /* Test 14: BGEZ with max positive */
test_14:
    li TESTNUM, 14
    li $t1, 0x7FFFFFFF
    bgez $t1, test_14_pass
    nop
    j fail
    nop
test_14_pass:

  /* Test 15: BLTZ with min negative */
test_15:
    li TESTNUM, 15
    li $t1, 0x80000000   /* -2^31 */
    bltz $t1, test_15_pass
    nop
    j fail
    nop
test_15_pass:

  /* Test 16: BGTZ with max positive */
test_16:
    li TESTNUM, 16
    li $t1, 0x7FFFFFFF
    bgtz $t1, test_16_pass
    nop
    j fail
    nop
test_16_pass:

  /* Test 17: BLEZ with min negative */
test_17:
    li TESTNUM, 17
    li $t1, 0x80000000
    blez $t1, test_17_pass
    nop
    j fail
    nop
test_17_pass:

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
