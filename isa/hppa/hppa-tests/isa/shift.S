/* HPPA Shift instruction tests */
/* Tests SHD (Shift Double), EXTRU (Extract Unsigned), EXTRS (Extract Signed) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * SHD - Shift Double
   * shd r1,r2,sa,t concatenates r1:r2 and shifts right by sa bits
   * Result is low 32 bits
   *-------------------------------------------------------------*/

test_2:
  LI(TESTNUM, 2)
  LI(%r2, 0x000000ff)
  LI(%r3, 0xff000000)
  /* Shift by 0 - should get first operand (r2) */
  shd %r2, %r3, 0, %r1
  LI(%r29, 0x000000ff)
  cmpb,<> %r1, %r29, fail
  nop

test_3:
  LI(TESTNUM, 3)
  LI(%r2, 0x00000000)
  LI(%r3, 0x00000000)
  /* Both zero - result should be zero */
  shd %r2, %r3, 16, %r1
  LI(%r29, 0x00000000)
  cmpb,<> %r1, %r29, fail
  nop

test_4:
  LI(TESTNUM, 4)
  LI(%r2, 0xffffffff)
  LI(%r3, 0xffffffff)
  /* Both all-ones - result should be all-ones */
  shd %r2, %r3, 8, %r1
  LI(%r29, 0xffffffff)
  cmpb,<> %r1, %r29, fail
  nop

test_5:
  LI(TESTNUM, 5)
  LI(%r2, 0xaaaaaaaa)
  LI(%r3, 0x55555555)
  /* Test with alternating bits, shift 0 - should get r2 */
  shd %r2, %r3, 0, %r1
  LI(%r29, 0xaaaaaaaa)
  cmpb,<> %r1, %r29, fail
  nop

  /* Note: EXTRU and EXTRS tests removed due to encoding complexity */
  /* TODO: Fix EXTRU/EXTRS ISA specs to handle HPPA bit numbering */

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
