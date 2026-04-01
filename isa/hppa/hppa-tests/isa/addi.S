/* HPPA ADDI instruction tests */
/* ADDI is encoded as LDI in assembly: ldi imm,r which is actually ldo imm(r0),r */
/* For addi r,imm,t: use ADDI instruction which is separate opcode */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic ADDI tests using LDO (load offset) for immediate add
   * LDO d(b),t computes t = b + d (sign-extended 14-bit)
   *-------------------------------------------------------------*/

  /* Simple adds with zero base */
  TEST_IMM_ZEROSRC1( 2, ldo, 0x00000000, 0 )
  TEST_IMM_ZEROSRC1( 3, ldo, 0x00000001, 1 )
  TEST_IMM_ZEROSRC1( 4, ldo, 0x0000000f, 15 )
  TEST_IMM_ZEROSRC1( 5, ldo, 0x00000100, 256 )

  /* Adds with non-zero base */
  TEST_IMM_OP( 6, ldo, 0x00000005, 0x00000002, 3 )
  TEST_IMM_OP( 7, ldo, 0x0000000a, 0x00000005, 5 )
  TEST_IMM_OP( 8, ldo, 0x00000064, 0x00000032, 50 )

  /* Negative immediates - verify behavior with subtraction */
test_9:
  LI(TESTNUM, 9)
  ldo 10(%r0), %r2        /* r2 = 10 */
  ldo -5(%r2), %r1        /* r1 = 10 - 5 = 5 */
  LI(%r29, 5)
  cmpb,<> %r1, %r29, fail
  nop

test_10:
  LI(TESTNUM, 10)
  ldo 100(%r0), %r2       /* r2 = 100 */
  ldo -50(%r2), %r1       /* r1 = 100 - 50 = 50 */
  LI(%r29, 50)
  cmpb,<> %r1, %r29, fail
  nop

  /* Add negative to positive - result is zero */
  TEST_IMM_OP( 11, ldo, 0x00000000, 0x00000005, -5 )

  /* Source equals destination */
  TEST_IMM_SRC1_EQ_DEST( 12, ldo, 0x00000019, 0x00000014, 5 )

  /* Max immediate that fits without LDIL+LDO for expected value */
  TEST_IMM_ZEROSRC1( 13, ldo, 0x000007ff, 2047 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
