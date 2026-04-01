/* MIPS32 SUBU instruction tests */
/* Based on riscv-tests structure */
/* Note: SUBU is same as SUB but doesn't trap on overflow */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Arithmetic tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2,  subu, 0x00000000, 0x00000000, 0x00000000 )
  TEST_RR_OP( 3,  subu, 0x00000000, 0x00000001, 0x00000001 )
  TEST_RR_OP( 4,  subu, 0xfffffffc, 0x00000003, 0x00000007 )

  TEST_RR_OP( 5,  subu, 0x00008000, 0x00000000, 0xffff8000 )
  TEST_RR_OP( 6,  subu, 0x80000000, 0x80000000, 0x00000000 )
  TEST_RR_OP( 7,  subu, 0x80008000, 0x80000000, 0xffff8000 )

  TEST_RR_OP( 8,  subu, 0xffff8001, 0x00000000, 0x00007fff )
  TEST_RR_OP( 9,  subu, 0x7fffffff, 0x7fffffff, 0x00000000 )
  TEST_RR_OP( 10, subu, 0x7fff8000, 0x7fffffff, 0x00007fff )

  TEST_RR_OP( 11, subu, 0x7fff8001, 0x80000000, 0x00007fff )
  TEST_RR_OP( 12, subu, 0x80007fff, 0x7fffffff, 0xffff8000 )

  TEST_RR_OP( 13, subu, 0x00000001, 0x00000000, 0xffffffff )
  TEST_RR_OP( 14, subu, 0xfffffffe, 0xffffffff, 0x00000001 )
  TEST_RR_OP( 15, subu, 0x00000000, 0xffffffff, 0xffffffff )

  /* Overflow tests (no trap in unsigned) */
  TEST_RR_OP( 16, subu, 0x7fffffff, 0x80000000, 0x00000001 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 17, subu, 2, 13, 11 )
  TEST_RR_SRC2_EQ_DEST( 18, subu, 3, 14, 11 )
  TEST_RR_SRC12_EQ_DEST( 19, subu, 0, 13 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_RR_DEST_BYPASS( 20, 0, subu, 2, 13, 11 )
  TEST_RR_DEST_BYPASS( 21, 1, subu, 3, 14, 11 )
  TEST_RR_DEST_BYPASS( 22, 2, subu, 4, 15, 11 )

  TEST_RR_SRC12_BYPASS( 23, 0, 0, subu, 2, 13, 11 )
  TEST_RR_SRC12_BYPASS( 24, 0, 1, subu, 3, 14, 11 )
  TEST_RR_SRC12_BYPASS( 25, 0, 2, subu, 4, 15, 11 )
  TEST_RR_SRC12_BYPASS( 26, 1, 0, subu, 5, 16, 11 )
  TEST_RR_SRC12_BYPASS( 27, 1, 1, subu, 6, 17, 11 )
  TEST_RR_SRC12_BYPASS( 28, 2, 0, subu, 7, 18, 11 )

  TEST_RR_SRC21_BYPASS( 29, 0, 0, subu, 2, 13, 11 )
  TEST_RR_SRC21_BYPASS( 30, 0, 1, subu, 3, 14, 11 )
  TEST_RR_SRC21_BYPASS( 31, 0, 2, subu, 4, 15, 11 )
  TEST_RR_SRC21_BYPASS( 32, 1, 0, subu, 5, 16, 11 )
  TEST_RR_SRC21_BYPASS( 33, 1, 1, subu, 6, 17, 11 )
  TEST_RR_SRC21_BYPASS( 34, 2, 0, subu, 7, 18, 11 )

  TEST_RR_ZEROSRC1( 35, subu, -15, 15 )
  TEST_RR_ZEROSRC2( 36, subu, 32, 32 )
  TEST_RR_ZEROSRC12( 37, subu, 0 )
  TEST_RR_ZERODEST( 38, subu, 16, 30 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
