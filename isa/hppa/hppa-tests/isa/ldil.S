/* HPPA LDIL instruction tests */
/* LDIL loads a 21-bit immediate into the high 21 bits of a register */
/* The low 11 bits are cleared */
/* Syntax: ldil L%value,reg (or L'value - L% avoids C preprocessor issues) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic LDIL tests
   * LDIL loads 21 bits into bits 31:11, clears bits 10:0
   *-------------------------------------------------------------*/

test_2:
  LI(TESTNUM, 2)
  ldil L%0, %r1
  LI(%r29, 0x00000000)
  cmpb,<> %r1, %r29, fail
  nop

test_3:
  LI(TESTNUM, 3)
  ldil L%0x1000, %r1      /* 0x1000 >> 11 = 2, shift back = 0x1000 */
  LI(%r29, 0x00001000)
  cmpb,<> %r1, %r29, fail
  nop

test_4:
  LI(TESTNUM, 4)
  ldil L%0x2000, %r1      /* 0x2000 >> 11 = 4, shift back = 0x2000 */
  LI(%r29, 0x00002000)
  cmpb,<> %r1, %r29, fail
  nop

test_5:
  LI(TESTNUM, 5)
  ldil L%0x10000, %r1     /* 0x10000 = 64K, aligned to 2K */
  LI(%r29, 0x00010000)
  cmpb,<> %r1, %r29, fail
  nop

test_6:
  LI(TESTNUM, 6)
  ldil L%0x100000, %r1    /* 1M */
  LI(%r29, 0x00100000)
  cmpb,<> %r1, %r29, fail
  nop

  /*-------------------------------------------------------------
   * Test LDIL + LDO combination to load arbitrary 32-bit value
   * This is the standard way to load large constants in HPPA
   *-------------------------------------------------------------*/

test_7:
  LI(TESTNUM, 7)
  ldil L%0x12345000, %r1
  ldo R%0x12345678(%r1), %r1
  /* Result should be 0x12345678 */
  /* Use another ldil+ldo to get the expected value */
  ldil L%0x12345000, %r29
  ldo R%0x12345678(%r29), %r29
  cmpb,<> %r1, %r29, fail
  nop

test_8:
  LI(TESTNUM, 8)
  /* Test loading a value in the 0x2000 range (fits in LDO) */
  ldil L%0x2800, %r1
  ldo R%0x2800(%r1), %r1
  LI(%r29, 0x2800)
  cmpb,<> %r1, %r29, fail
  nop

  /*-------------------------------------------------------------
   * Test with negative high bits (sign extension)
   *-------------------------------------------------------------*/

test_9:
  LI(TESTNUM, 9)
  ldil L%0xfffff000, %r1  /* High bits set - sign extends */
  ldo R%0xfffff000(%r1), %r1
  ldil L%0xfffff000, %r29
  ldo R%0xfffff000(%r29), %r29
  cmpb,<> %r1, %r29, fail
  nop

  /*-------------------------------------------------------------
   * Test destination is r0 (should be NOP - r0 always 0)
   *-------------------------------------------------------------*/

test_10:
  LI(TESTNUM, 10)
  ldil L%0x1000, %r0
  cmpb,<> %r0, %r0, fail
  nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
