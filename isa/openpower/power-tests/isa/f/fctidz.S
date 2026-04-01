/* OpenPOWER FCTIDZ instruction tests */
/* fctidz frt, frb - Floating Convert To Integer Doubleword with round toward Zero */
/* Converts double-precision float to 64-bit signed integer, truncating */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic truncation tests
   *-------------------------------------------------------------*/

  /* Convert 1.9 to 1 (truncate) */
  /* 1.9 = 0x3ffe666666666666 */
test_2:
  li TESTNUM, 2
  lis %r9, 0x3ffe
  ori %r9, %r9, 0x6666
  sldi %r9, %r9, 32
  oris %r9, %r9, 0x6666
  ori %r9, %r9, 0x6666
  std %r9, -8(%r1)
  lfd %f0, -8(%r1)
  fctidz %f2, %f0
  stfd %f2, -8(%r1)
  ld %r8, -8(%r1)
  li %r25, 1
  cmpd %cr0, %r8, %r25
  bne %cr0, fail

  /* Convert 1.1 to 1 */
test_3:
  li TESTNUM, 3
  lis %r9, 0x3ff1
  ori %r9, %r9, 0x9999
  sldi %r9, %r9, 32
  oris %r9, %r9, 0x9999
  ori %r9, %r9, 0x999a
  std %r9, -8(%r1)
  lfd %f0, -8(%r1)
  fctidz %f2, %f0
  stfd %f2, -8(%r1)
  ld %r8, -8(%r1)
  li %r25, 1
  cmpd %cr0, %r8, %r25
  bne %cr0, fail

  /* Convert -1.9 to -1 (toward zero = less negative) */
test_4:
  li TESTNUM, 4
  lis %r9, 0xbffe
  ori %r9, %r9, 0x6666
  sldi %r9, %r9, 32
  oris %r9, %r9, 0x6666
  ori %r9, %r9, 0x6666
  std %r9, -8(%r1)
  lfd %f0, -8(%r1)
  fctidz %f2, %f0
  stfd %f2, -8(%r1)
  ld %r8, -8(%r1)
  li %r25, -1
  cmpd %cr0, %r8, %r25
  bne %cr0, fail

  /* Convert 2.5 to 2 */
  /* 2.5 = 0x4004000000000000 */
test_5:
  li TESTNUM, 5
  lis %r9, 0x4004
  sldi %r9, %r9, 32
  std %r9, -8(%r1)
  lfd %f0, -8(%r1)
  fctidz %f2, %f0
  stfd %f2, -8(%r1)
  ld %r8, -8(%r1)
  li %r25, 2
  cmpd %cr0, %r8, %r25
  bne %cr0, fail

  /* Convert 0.5 to 0 */
  /* 0.5 = 0x3fe0000000000000 */
test_6:
  li TESTNUM, 6
  lis %r9, 0x3fe0
  sldi %r9, %r9, 32
  std %r9, -8(%r1)
  lfd %f0, -8(%r1)
  fctidz %f2, %f0
  stfd %f2, -8(%r1)
  ld %r8, -8(%r1)
  li %r25, 0
  cmpd %cr0, %r8, %r25
  bne %cr0, fail

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
