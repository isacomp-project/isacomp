/* SPARCv8 UDIVcc instruction tests (unsigned divide with condition codes) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * UDIVcc: Unsigned divide Y:rs1 / operand2 -> rd
   * Sets icc based on result
   * icc.v set if overflow (result doesn't fit in 32 bits)
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: Simple positive division (Y=0)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    mov 0, %l1
    wr %l1, %g0, %y       /* Y = 0 */
    nop; nop; nop         /* Wait for Y write */
    set 20, %l1
    set 4, %l2
    udivcc %l1, %l2, %l0  /* 20 / 4 = 5 */
    cmp %l0, 5
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: Division with remainder (truncates toward zero)
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    mov 0, %l1
    wr %l1, %g0, %y       /* Y = 0 */
    nop; nop; nop
    set 23, %l1
    set 5, %l2
    udivcc %l1, %l2, %l0  /* 23 / 5 = 4 */
    cmp %l0, 4
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Result is zero - Z flag should be set
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    mov 0, %l1
    wr %l1, %g0, %y       /* Y = 0 */
    nop; nop; nop
    set 3, %l1
    set 10, %l2
    udivcc %l1, %l2, %l0  /* 3 / 10 = 0 */
    be test_4_pass        /* Z should be set */
    nop
    ba fail
    nop
test_4_pass:

  /*-------------------------------------------------------------
   * Test 5: Divide by one
   *-------------------------------------------------------------*/
test_5:
    mov 5, TESTNUM
    mov 0, %l1
    wr %l1, %g0, %y       /* Y = 0 */
    nop; nop; nop
    set 42, %l1
    set 1, %l2
    udivcc %l1, %l2, %l0  /* 42 / 1 = 42 */
    cmp %l0, 42
    be test_5_pass
    nop
    ba fail
    nop
test_5_pass:

  /*-------------------------------------------------------------
   * Test 6: UDIVcc with immediate operand
   *-------------------------------------------------------------*/
test_6:
    mov 6, TESTNUM
    mov 0, %l1
    wr %l1, %g0, %y       /* Y = 0 */
    nop; nop; nop
    set 100, %l1
    udivcc %l1, 10, %l0   /* 100 / 10 = 10 */
    cmp %l0, 10
    be test_6_pass
    nop
    ba fail
    nop
test_6_pass:

  /*-------------------------------------------------------------
   * Test 7: Large dividend, result with bit 31 set - N flag set
   *-------------------------------------------------------------*/
test_7:
    mov 7, TESTNUM
    mov 0, %l1
    wr %l1, %g0, %y       /* Y = 0 */
    nop; nop; nop
    set 0x80000000, %l1
    set 1, %l2
    udivcc %l1, %l2, %l0  /* 0x80000000 / 1 = 0x80000000 */
    bneg test_7_pass      /* N should be set */
    nop
    ba fail
    nop
test_7_pass:

  /*-------------------------------------------------------------
   * Test 8: UDIVcc result to %g0 discards result
   *-------------------------------------------------------------*/
test_8:
    mov 8, TESTNUM
    mov 0, %l1
    wr %l1, %g0, %y
    nop; nop; nop
    set 20, %l1
    set 4, %l2
    udivcc %l1, %l2, %g0  /* Result discarded */
    cmp %g0, 0
    be test_8_pass
    nop
    ba fail
    nop
test_8_pass:

  /*-------------------------------------------------------------
   * Test 9: Result non-zero - Z should be clear
   *-------------------------------------------------------------*/
test_9:
    mov 9, TESTNUM
    mov 0, %l1
    wr %l1, %g0, %y
    nop; nop; nop
    set 15, %l1
    set 3, %l2
    udivcc %l1, %l2, %l0  /* 15 / 3 = 5 */
    bne test_9_pass       /* Z should be clear */
    nop
    ba fail
    nop
test_9_pass:

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
