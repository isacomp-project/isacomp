/* SPARCv8 BVS instruction tests (branch on overflow set, V=1) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch taken: V=1 (signed overflow occurred)
   *-------------------------------------------------------------*/

  /* Positive overflow: large positive + large positive */
  TEST_CASE( 2, %l0, 99, \
    set 0x7fffffff, %l1; \
    set 1, %l2; \
    addcc %l1, %l2, %l3; \
    bvs 1f; \
    nop; \
    set 0, %l0; \
    ba 2f; \
    nop; \
1:  set 99, %l0; \
2:  \
  )

  /* Negative overflow: large negative + large negative */
  TEST_CASE( 3, %l0, 99, \
    set 0x80000000, %l1; \
    set 0x80000000, %l2; \
    addcc %l1, %l2, %l3; \
    bvs 1f; \
    nop; \
    set 0, %l0; \
    ba 2f; \
    nop; \
1:  set 99, %l0; \
2:  \
  )

  /* Negative overflow: large negative - positive */
  TEST_CASE( 4, %l0, 99, \
    set 0x80000000, %l1; \
    set 1, %l2; \
    subcc %l1, %l2, %l3; \
    bvs 1f; \
    nop; \
    set 0, %l0; \
    ba 2f; \
    nop; \
1:  set 99, %l0; \
2:  \
  )

  /*-------------------------------------------------------------
   * Branch not taken: V=0 (no signed overflow)
   *-------------------------------------------------------------*/

  /* Simple addition without overflow */
  TEST_CASE( 5, %l0, 3, \
    set 1, %l1; \
    set 2, %l2; \
    addcc %l1, %l2, %l0; \
    bvs 1f; \
    nop; \
    ba 2f; \
    nop; \
1:  set 0, %l0; \
2:  \
  )

  /* Subtraction without overflow */
  TEST_CASE( 6, %l0, 3, \
    set 5, %l1; \
    set 2, %l2; \
    subcc %l1, %l2, %l0; \
    bvs 1f; \
    nop; \
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
