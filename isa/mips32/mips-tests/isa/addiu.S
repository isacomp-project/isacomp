/* MIPS32 ADDIU instruction tests */
/* Based on riscv-tests structure */
/* Note: ADDIU is same as ADDI but doesn't trap on overflow */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Arithmetic tests
   *-------------------------------------------------------------*/

  TEST_IMM_OP( 2,  addiu, 0x00000000, 0x00000000, 0x000 )
  TEST_IMM_OP( 3,  addiu, 0x00000002, 0x00000001, 0x001 )
  TEST_IMM_OP( 4,  addiu, 0x0000000a, 0x00000003, 0x007 )

  /* Sign extension tests */
  TEST_IMM_OP( 5,  addiu, 0xfffff800, 0x00000000, -2048 )
  TEST_IMM_OP( 6,  addiu, 0x80000000, 0x80000000, 0x000 )
  TEST_IMM_OP( 7,  addiu, 0x7ffff800, 0x80000000, -2048 )

  TEST_IMM_OP( 8,  addiu, 0x000007ff, 0x00000000, 0x7ff )
  TEST_IMM_OP( 9,  addiu, 0x7fffffff, 0x7fffffff, 0x000 )
  TEST_IMM_OP( 10, addiu, 0x800007fe, 0x7fffffff, 0x7ff )

  TEST_IMM_OP( 11, addiu, 0x800007ff, 0x80000000, 0x7ff )
  TEST_IMM_OP( 12, addiu, 0x7ffff7ff, 0x7fffffff, -2048 )

  TEST_IMM_OP( 13, addiu, 0xffffffff, 0x00000000, -1 )
  TEST_IMM_OP( 14, addiu, 0x00000000, 0xffffffff, 0x001 )
  TEST_IMM_OP( 15, addiu, 0xfffffffe, 0xffffffff, -1 )

  /* Overflow tests (no trap in unsigned) */
  TEST_IMM_OP( 16, addiu, 0x80000000, 0x7fffffff, 0x001 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_IMM_SRC1_EQ_DEST( 17, addiu, 24, 13, 11 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_IMM_DEST_BYPASS( 18, 0, addiu, 24, 13, 11 )
  TEST_IMM_DEST_BYPASS( 19, 1, addiu, 23, 13, 10 )
  TEST_IMM_DEST_BYPASS( 20, 2, addiu, 22, 13, 9 )

  TEST_IMM_SRC1_BYPASS( 21, 0, addiu, 24, 13, 11 )
  TEST_IMM_SRC1_BYPASS( 22, 1, addiu, 23, 13, 10 )
  TEST_IMM_SRC1_BYPASS( 23, 2, addiu, 22, 13, 9 )

  TEST_IMM_ZEROSRC1( 24, addiu, 32, 32 )
  TEST_IMM_ZERODEST( 25, addiu, 33, 50 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
