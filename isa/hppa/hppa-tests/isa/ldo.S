/* HPPA LDO (Load Offset/Immediate) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic immediate load tests (LDI = LDO imm(r0))
   *-------------------------------------------------------------*/

  TEST_IMM_ZEROSRC1( 2, ldo, 0x00000000, 0 )
  TEST_IMM_ZEROSRC1( 3, ldo, 0x00000001, 1 )
  TEST_IMM_ZEROSRC1( 4, ldo, 0x00000064, 100 )
  TEST_IMM_ZEROSRC1( 5, ldo, 0x000000ff, 255 )
  TEST_IMM_ZEROSRC1( 6, ldo, 0x00000400, 1024 )

  /*-------------------------------------------------------------
   * Register + offset tests
   *-------------------------------------------------------------*/

  TEST_IMM_OP( 7, ldo, 0x00000005, 0x00000000, 5 )
  TEST_IMM_OP( 8, ldo, 0x00000010, 0x0000000a, 6 )
  TEST_IMM_OP( 9, ldo, 0x00000100, 0x000000f0, 16 )

  /*-------------------------------------------------------------
   * Source equals dest tests
   *-------------------------------------------------------------*/

  TEST_IMM_SRC1_EQ_DEST( 10, ldo, 0x00000019, 0x00000014, 5 )
  TEST_IMM_SRC1_EQ_DEST( 11, ldo, 0x00000064, 0x00000000, 100 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
