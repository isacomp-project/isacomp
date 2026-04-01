/* OpenPOWER FCTID instruction tests */
/* fctid frt, frb - Floating Convert To Integer Doubleword */
/* Converts double-precision float to 64-bit signed integer */
/* Uses current rounding mode (FPSCR) */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic float to integer conversion tests
   * Input is IEEE 754 double, output is 64-bit signed integer in FPR
   *-------------------------------------------------------------*/

  /* Convert 1.0 to 1 */
test_2:
  li TESTNUM, 2
  /* Load 1.0 = 0x3ff0000000000000 */
  lis %r9, 0x3ff0
  sldi %r9, %r9, 32
  std %r9, -8(%r1)
  lfd %f0, -8(%r1)
  fctid %f2, %f0
  stfd %f2, -8(%r1)
  ld %r8, -8(%r1)
  li %r25, 1
  cmpd %cr0, %r8, %r25
  bne %cr0, fail

  /* Convert 2.0 to 2 */
test_3:
  li TESTNUM, 3
  lis %r9, 0x4000
  sldi %r9, %r9, 32
  std %r9, -8(%r1)
  lfd %f0, -8(%r1)
  fctid %f2, %f0
  stfd %f2, -8(%r1)
  ld %r8, -8(%r1)
  li %r25, 2
  cmpd %cr0, %r8, %r25
  bne %cr0, fail

  /* Convert 0.0 to 0 */
test_4:
  li TESTNUM, 4
  li %r9, 0
  std %r9, -8(%r1)
  lfd %f0, -8(%r1)
  fctid %f2, %f0
  stfd %f2, -8(%r1)
  ld %r8, -8(%r1)
  li %r25, 0
  cmpd %cr0, %r8, %r25
  bne %cr0, fail

  /* Convert -1.0 to -1 */
test_5:
  li TESTNUM, 5
  lis %r9, 0xbff0
  sldi %r9, %r9, 32
  std %r9, -8(%r1)
  lfd %f0, -8(%r1)
  fctid %f2, %f0
  stfd %f2, -8(%r1)
  ld %r8, -8(%r1)
  li %r25, -1
  cmpd %cr0, %r8, %r25
  bne %cr0, fail

  /* Convert 10.0 to 10 */
test_6:
  li TESTNUM, 6
  lis %r9, 0x4024
  sldi %r9, %r9, 32
  std %r9, -8(%r1)
  lfd %f0, -8(%r1)
  fctid %f2, %f0
  stfd %f2, -8(%r1)
  ld %r8, -8(%r1)
  li %r25, 10
  cmpd %cr0, %r8, %r25
  bne %cr0, fail

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
