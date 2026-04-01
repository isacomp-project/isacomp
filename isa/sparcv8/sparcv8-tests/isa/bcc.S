/* SPARCv8 BCC instruction tests (branch on carry clear, C=0) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch taken: C=0 (no carry/borrow)
   *-------------------------------------------------------------*/

  /* Addition without carry */
  TEST_CASE( 2, %l0, 3, \
    set 1, %l1; \
    set 2, %l2; \
    addcc %l1, %l2, %l0; \
    bcc 1f; \
    nop; \
    set 0, %l0; \
1:  \
  )

  /* Subtraction without borrow */
  TEST_CASE( 3, %l0, 3, \
    set 5, %l1; \
    set 2, %l2; \
    subcc %l1, %l2, %l0; \
    bcc 1f; \
    nop; \
    set 0, %l0; \
1:  \
  )

  /*-------------------------------------------------------------
   * Branch not taken: C=1 (carry/borrow occurred)
   *-------------------------------------------------------------*/

  /* Addition with carry (overflow unsigned) */
  TEST_CASE( 4, %l0, 99, \
    set 0xffffffff, %l1; \
    set 1, %l2; \
    addcc %l1, %l2, %l3; \
    bcc 1f; \
    nop; \
    set 99, %l0; \
    ba 2f; \
    nop; \
1:  set 0, %l0; \
2:  \
  )

  /* Subtraction with borrow */
  TEST_CASE( 5, %l0, 99, \
    set 0, %l1; \
    set 1, %l2; \
    subcc %l1, %l2, %l3; \
    bcc 1f; \
    nop; \
    set 99, %l0; \
    ba 2f; \
    nop; \
1:  set 0, %l0; \
2:  \
  )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
