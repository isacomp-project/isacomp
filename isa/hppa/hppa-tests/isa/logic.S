/* HPPA Logic instruction tests */
/* Tests ANDCM (And Complement) and COPY */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * ANDCM - And Complement
   * andcm r1,r2,t computes t = r1 AND (NOT r2)
   * Useful for clearing bits
   *-------------------------------------------------------------*/

test_2:
  LI(TESTNUM, 2)
  LI(%r2, 0xffffffff)
  LI(%r3, 0x00000000)
  andcm %r2, %r3, %r1
  LI(%r29, 0xffffffff)    /* 0xffffffff AND NOT 0 = 0xffffffff */
  cmpb,<> %r1, %r29, fail
  nop

test_3:
  LI(TESTNUM, 3)
  LI(%r2, 0xffffffff)
  LI(%r3, 0xffffffff)
  andcm %r2, %r3, %r1
  LI(%r29, 0x00000000)    /* 0xffffffff AND NOT 0xffffffff = 0 */
  cmpb,<> %r1, %r29, fail
  nop

test_4:
  LI(TESTNUM, 4)
  LI(%r2, 0xff00ff00)
  LI(%r3, 0xf0f0f0f0)
  andcm %r2, %r3, %r1
  LI(%r29, 0x0f000f00)    /* ff00ff00 AND NOT f0f0f0f0 = ff00ff00 AND 0f0f0f0f */
  cmpb,<> %r1, %r29, fail
  nop

test_5:
  LI(TESTNUM, 5)
  /* Clear bit 0 using andcm */
  LI(%r2, 0x0000000f)
  LI(%r3, 0x00000001)     /* Mask to clear bit 0 */
  andcm %r2, %r3, %r1
  LI(%r29, 0x0000000e)
  cmpb,<> %r1, %r29, fail
  nop

test_6:
  LI(TESTNUM, 6)
  /* Clear high byte using andcm */
  LI(%r2, 0xff345678)
  LI(%r3, 0xff000000)     /* Mask to clear high byte */
  andcm %r2, %r3, %r1
  LI(%r29, 0x00345678)
  cmpb,<> %r1, %r29, fail
  nop

  /*-------------------------------------------------------------
   * COPY - Copy register
   * copy r,t copies r to t (actually OR r,r0,t)
   *-------------------------------------------------------------*/

test_7:
  LI(TESTNUM, 7)
  LI(%r2, 0x12345678)
  copy %r2, %r1
  LI(%r29, 0x12345678)
  cmpb,<> %r1, %r29, fail
  nop

test_8:
  LI(TESTNUM, 8)
  LI(%r2, 0x00000000)
  copy %r2, %r1
  LI(%r29, 0x00000000)
  cmpb,<> %r1, %r29, fail
  nop

test_9:
  LI(TESTNUM, 9)
  LI(%r2, 0xffffffff)
  copy %r2, %r1
  LI(%r29, 0xffffffff)
  cmpb,<> %r1, %r29, fail
  nop

test_10:
  LI(TESTNUM, 10)
  /* Copy r0 - should always be 0 */
  LI(%r1, 0xdeadbeef)     /* Set r1 to something first */
  copy %r0, %r1
  LI(%r29, 0x00000000)
  cmpb,<> %r1, %r29, fail
  nop

test_11:
  LI(TESTNUM, 11)
  /* Copy to r0 - should be NOP */
  LI(%r2, 0x12345678)
  copy %r2, %r0
  cmpb,<> %r0, %r0, fail  /* r0 should still be 0 */
  nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
