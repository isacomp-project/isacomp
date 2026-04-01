/* MIPS32 SRA instruction tests */
/* Based on riscv-tests structure */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Arithmetic tests (arithmetic shift right - sign extends)
   *-------------------------------------------------------------*/

  TEST_SHIFT_OP( 2,  sra, 0x80000000, 0x80000000, 0 )
  TEST_SHIFT_OP( 3,  sra, 0xc0000000, 0x80000000, 1 )
  TEST_SHIFT_OP( 4,  sra, 0xff000000, 0x80000000, 7 )
  TEST_SHIFT_OP( 5,  sra, 0xfffe0000, 0x80000000, 14 )
  TEST_SHIFT_OP( 6,  sra, 0xffffffff, 0x80000001, 31 )

  TEST_SHIFT_OP( 7,  sra, 0x7fffffff, 0x7fffffff, 0 )
  TEST_SHIFT_OP( 8,  sra, 0x3fffffff, 0x7fffffff, 1 )
  TEST_SHIFT_OP( 9,  sra, 0x00ffffff, 0x7fffffff, 7 )
  TEST_SHIFT_OP( 10, sra, 0x0001ffff, 0x7fffffff, 14 )
  TEST_SHIFT_OP( 11, sra, 0x00000000, 0x7fffffff, 31 )

  TEST_SHIFT_OP( 12, sra, 0x81818181, 0x81818181, 0 )
  TEST_SHIFT_OP( 13, sra, 0xc0c0c0c0, 0x81818181, 1 )
  TEST_SHIFT_OP( 14, sra, 0xff030303, 0x81818181, 7 )
  TEST_SHIFT_OP( 15, sra, 0xfffe0606, 0x81818181, 14 )
  TEST_SHIFT_OP( 16, sra, 0xffffffff, 0x81818181, 31 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_SHIFT_SRC1_EQ_DEST( 17, sra, 0xff000000, 0x80000000, 7 )

  /*-------------------------------------------------------------
   * Zero dest tests
   *-------------------------------------------------------------*/

  TEST_SHIFT_ZERODEST( 18, sra, 0x80000000, 14 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
