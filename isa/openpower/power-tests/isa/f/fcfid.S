/* OpenPOWER FCFID instruction tests */
/* fcfid frt, frb - Floating Convert From Integer Doubleword */
/* Converts 64-bit signed integer to double-precision float */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic integer to float conversion tests
   * The FPR contains the integer value in binary format
   * Result is IEEE 754 double-precision
   *-------------------------------------------------------------*/

  /* Convert 1 to 1.0 */
  /* Input: 0x0000000000000001, Output: 1.0 = 0x3ff0000000000000 */
test_2:
  li TESTNUM, 2
  li %r9, 1
  std %r9, -8(%r1)
  lfd %f0, -8(%r1)
  fcfid %f2, %f0
  stfd %f2, -8(%r1)
  ld %r8, -8(%r1)
  lis %r25, 0x3ff0
  sldi %r25, %r25, 32
  cmpd %cr0, %r8, %r25
  bne %cr0, fail

  /* Convert 2 to 2.0 */
  /* 2.0 = 0x4000000000000000 */
test_3:
  li TESTNUM, 3
  li %r9, 2
  std %r9, -8(%r1)
  lfd %f0, -8(%r1)
  fcfid %f2, %f0
  stfd %f2, -8(%r1)
  ld %r8, -8(%r1)
  lis %r25, 0x4000
  sldi %r25, %r25, 32
  cmpd %cr0, %r8, %r25
  bne %cr0, fail

  /* Convert 0 to 0.0 */
test_4:
  li TESTNUM, 4
  li %r9, 0
  std %r9, -8(%r1)
  lfd %f0, -8(%r1)
  fcfid %f2, %f0
  stfd %f2, -8(%r1)
  ld %r8, -8(%r1)
  li %r25, 0
  cmpd %cr0, %r8, %r25
  bne %cr0, fail

  /* Convert -1 to -1.0 */
  /* -1.0 = 0xbff0000000000000 */
test_5:
  li TESTNUM, 5
  li %r9, -1
  std %r9, -8(%r1)
  lfd %f0, -8(%r1)
  fcfid %f2, %f0
  stfd %f2, -8(%r1)
  ld %r8, -8(%r1)
  lis %r25, 0xbff0
  sldi %r25, %r25, 32
  cmpd %cr0, %r8, %r25
  bne %cr0, fail

  /* Convert 10 to 10.0 */
  /* 10.0 = 0x4024000000000000 */
test_6:
  li TESTNUM, 6
  li %r9, 10
  std %r9, -8(%r1)
  lfd %f0, -8(%r1)
  fcfid %f2, %f0
  stfd %f2, -8(%r1)
  ld %r8, -8(%r1)
  lis %r25, 0x4024
  sldi %r25, %r25, 32
  cmpd %cr0, %r8, %r25
  bne %cr0, fail

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
