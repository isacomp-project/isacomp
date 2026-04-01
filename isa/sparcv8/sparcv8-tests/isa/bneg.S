/* SPARCv8 BNEG instruction tests (branch on negative, N=1) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch taken: N=1 (result is negative)
   *-------------------------------------------------------------*/

  /* Negative constant */
  TEST_CASE( 2, %l0, 99, \
    set 0x80000000, %l1; \
    orcc %l1, %g0, %l3; \
    bneg 1f; \
    nop; \
    set 0, %l0; \
    ba 2f; \
    nop; \
1:  set 99, %l0; \
2:  \
  )

  /* Subtraction yielding negative */
  TEST_CASE( 3, %l0, 99, \
    set 2, %l1; \
    set 5, %l2; \
    subcc %l1, %l2, %l3; \
    bneg 1f; \
    nop; \
    set 0, %l0; \
    ba 2f; \
    nop; \
1:  set 99, %l0; \
2:  \
  )

  /* All ones is negative */
  TEST_CASE( 4, %l0, 99, \
    set 0xffffffff, %l1; \
    orcc %l1, %g0, %l3; \
    bneg 1f; \
    nop; \
    set 0, %l0; \
    ba 2f; \
    nop; \
1:  set 99, %l0; \
2:  \
  )

  /*-------------------------------------------------------------
   * Branch not taken: N=0 (result is positive or zero)
   *-------------------------------------------------------------*/

  /* Positive result */
  TEST_CASE( 5, %l0, 5, \
    set 3, %l1; \
    set 2, %l2; \
    addcc %l1, %l2, %l0; \
    bneg 1f; \
    nop; \
    ba 2f; \
    nop; \
1:  set 0, %l0; \
2:  \
  )

  /* Zero result */
  TEST_CASE( 6, %l0, 0, \
    set 5, %l1; \
    set 5, %l2; \
    subcc %l1, %l2, %l0; \
    bneg 1f; \
    nop; \
    ba 2f; \
    nop; \
1:  set 99, %l0; \
2:  \
  )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
