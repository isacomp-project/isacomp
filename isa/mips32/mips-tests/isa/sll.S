/* MIPS32 SLL instruction tests */
/* Based on riscv-tests structure */
/* Note: MIPS SLL uses immediate shamt, not a register like RISC-V */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Arithmetic tests
   *-------------------------------------------------------------*/

  TEST_SHIFT_OP( 2,  sll, 0x00000001, 0x00000001, 0  )
  TEST_SHIFT_OP( 3,  sll, 0x00000002, 0x00000001, 1  )
  TEST_SHIFT_OP( 4,  sll, 0x00000080, 0x00000001, 7  )
  TEST_SHIFT_OP( 5,  sll, 0x00004000, 0x00000001, 14 )
  TEST_SHIFT_OP( 6,  sll, 0x80000000, 0x00000001, 31 )

  TEST_SHIFT_OP( 7,  sll, 0xffffffff, 0xffffffff, 0  )
  TEST_SHIFT_OP( 8,  sll, 0xfffffffe, 0xffffffff, 1  )
  TEST_SHIFT_OP( 9,  sll, 0xffffff80, 0xffffffff, 7  )
  TEST_SHIFT_OP( 10, sll, 0xffffc000, 0xffffffff, 14 )
  TEST_SHIFT_OP( 11, sll, 0x80000000, 0xffffffff, 31 )

  TEST_SHIFT_OP( 12, sll, 0x21212121, 0x21212121, 0  )
  TEST_SHIFT_OP( 13, sll, 0x42424242, 0x21212121, 1  )
  TEST_SHIFT_OP( 14, sll, 0x90909080, 0x21212121, 7  )
  TEST_SHIFT_OP( 15, sll, 0x48484000, 0x21212121, 14 )
  TEST_SHIFT_OP( 16, sll, 0x80000000, 0x21212121, 31 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_SHIFT_SRC1_EQ_DEST( 17, sll, 0x00000080, 0x00000001, 7  )

  /*-------------------------------------------------------------
   * Zero destination test
   *-------------------------------------------------------------*/

  TEST_SHIFT_ZERODEST( 18, sll, 0x00001000, 4 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
