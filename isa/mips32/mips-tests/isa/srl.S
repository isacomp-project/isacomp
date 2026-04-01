/* MIPS32 SRL instruction tests */
/* Based on riscv-tests structure */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Arithmetic tests (logical shift right)
   *-------------------------------------------------------------*/

  TEST_SHIFT_OP( 2,  srl, 0x80000000, 0x80000000, 0 )
  TEST_SHIFT_OP( 3,  srl, 0x40000000, 0x80000000, 1 )
  TEST_SHIFT_OP( 4,  srl, 0x01000000, 0x80000000, 7 )
  TEST_SHIFT_OP( 5,  srl, 0x00020000, 0x80000000, 14 )
  TEST_SHIFT_OP( 6,  srl, 0x00000001, 0x80000001, 31 )

  TEST_SHIFT_OP( 7,  srl, 0xffffffff, 0xffffffff, 0 )
  TEST_SHIFT_OP( 8,  srl, 0x7fffffff, 0xffffffff, 1 )
  TEST_SHIFT_OP( 9,  srl, 0x01ffffff, 0xffffffff, 7 )
  TEST_SHIFT_OP( 10, srl, 0x0003ffff, 0xffffffff, 14 )
  TEST_SHIFT_OP( 11, srl, 0x00000001, 0xffffffff, 31 )

  TEST_SHIFT_OP( 12, srl, 0x21212121, 0x21212121, 0 )
  TEST_SHIFT_OP( 13, srl, 0x10909090, 0x21212121, 1 )
  TEST_SHIFT_OP( 14, srl, 0x00424242, 0x21212121, 7 )
  TEST_SHIFT_OP( 15, srl, 0x00008484, 0x21212121, 14 )
  TEST_SHIFT_OP( 16, srl, 0x00000000, 0x21212121, 31 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_SHIFT_SRC1_EQ_DEST( 17, srl, 0x01000000, 0x80000000, 7 )

  /*-------------------------------------------------------------
   * Zero dest tests
   *-------------------------------------------------------------*/

  TEST_SHIFT_ZERODEST( 18, srl, 0x80000000, 14 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
