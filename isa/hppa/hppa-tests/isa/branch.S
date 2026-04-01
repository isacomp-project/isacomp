/* HPPA Branch instruction tests */
/* Tests basic CMPB conditions */
/* Note: HPPA syntax uses comma-separated condition: cmpb,= cmpb,<> cmpb,< etc */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * CMPB,<> (not equal) - basic test that's already used by other tests
   *-------------------------------------------------------------*/

test_2:
  LI(TESTNUM, 2)
  /* Test that equal values don't branch */
  LI(%r2, 5)
  LI(%r3, 5)
  cmpb,<> %r2, %r3, fail   /* Should NOT branch (5 == 5) */
  nop

test_3:
  LI(TESTNUM, 3)
  /* Test that unequal values do branch (by testing the inverse) */
  LI(%r2, 5)
  LI(%r3, 10)
  cmpb,= %r2, %r3, fail    /* Should NOT branch (5 != 10) */
  nop

test_4:
  LI(TESTNUM, 4)
  /* Test CMPB,= with equal values */
  LI(%r2, 0)
  LI(%r3, 0)
  cmpb,= %r2, %r3, test_5  /* Should branch (0 == 0) */
  nop
  b fail
  nop

test_5:
  LI(TESTNUM, 5)
  /* Test with zero register */
  cmpb,= %r0, %r0, test_6  /* Should branch (r0 == r0) */
  nop
  b fail
  nop

test_6:
  LI(TESTNUM, 6)
  /* All tests passed */

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
