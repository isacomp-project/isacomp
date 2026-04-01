/* MIPS32 SRLV instruction tests */
/* Based on riscv-tests structure */
/* SRLV rd, rt, rs: rd = rt >> rs[4:0] (logical, shift amount from register) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Arithmetic tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2,  srlv, 0x80000000, 0x80000000, 0 )
  TEST_RR_OP( 3,  srlv, 0x40000000, 0x80000000, 1 )
  TEST_RR_OP( 4,  srlv, 0x01000000, 0x80000000, 7 )
  TEST_RR_OP( 5,  srlv, 0x00020000, 0x80000000, 14 )
  TEST_RR_OP( 6,  srlv, 0x00000001, 0x80000001, 31 )

  TEST_RR_OP( 7,  srlv, 0xffffffff, 0xffffffff, 0 )
  TEST_RR_OP( 8,  srlv, 0x7fffffff, 0xffffffff, 1 )
  TEST_RR_OP( 9,  srlv, 0x01ffffff, 0xffffffff, 7 )
  TEST_RR_OP( 10, srlv, 0x0003ffff, 0xffffffff, 14 )
  TEST_RR_OP( 11, srlv, 0x00000001, 0xffffffff, 31 )

  TEST_RR_OP( 12, srlv, 0x21212121, 0x21212121, 0 )
  TEST_RR_OP( 13, srlv, 0x10909090, 0x21212121, 1 )
  TEST_RR_OP( 14, srlv, 0x00424242, 0x21212121, 7 )
  TEST_RR_OP( 15, srlv, 0x00008484, 0x21212121, 14 )
  TEST_RR_OP( 16, srlv, 0x00000000, 0x21212121, 31 )

  /* Verify that shifts only use bottom five bits */
  TEST_RR_OP( 17, srlv, 0x21212121, 0x21212121, 0xffffffe0 )
  TEST_RR_OP( 18, srlv, 0x10909090, 0x21212121, 0xffffffe1 )
  TEST_RR_OP( 19, srlv, 0x00424242, 0x21212121, 0xffffffe7 )
  TEST_RR_OP( 20, srlv, 0x00008484, 0x21212121, 0xffffffee )
  TEST_RR_OP( 21, srlv, 0x00000000, 0x21212121, 0xffffffff )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 22, srlv, 0x01000000, 0x80000000, 7 )
  TEST_RR_SRC2_EQ_DEST( 23, srlv, 0x00020000, 0x80000000, 14 )
  TEST_RR_SRC12_EQ_DEST( 24, srlv, 0, 7 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_RR_DEST_BYPASS( 25, 0, srlv, 0x01000000, 0x80000000, 7 )
  TEST_RR_DEST_BYPASS( 26, 1, srlv, 0x00020000, 0x80000000, 14 )
  TEST_RR_DEST_BYPASS( 27, 2, srlv, 0x00000001, 0x80000000, 31 )

  TEST_RR_SRC12_BYPASS( 28, 0, 0, srlv, 0x01000000, 0x80000000, 7 )
  TEST_RR_SRC12_BYPASS( 29, 0, 1, srlv, 0x00020000, 0x80000000, 14 )
  TEST_RR_SRC12_BYPASS( 30, 0, 2, srlv, 0x00000001, 0x80000000, 31 )
  TEST_RR_SRC12_BYPASS( 31, 1, 0, srlv, 0x01000000, 0x80000000, 7 )
  TEST_RR_SRC12_BYPASS( 32, 1, 1, srlv, 0x00020000, 0x80000000, 14 )
  TEST_RR_SRC12_BYPASS( 33, 2, 0, srlv, 0x00000001, 0x80000000, 31 )

  TEST_RR_SRC21_BYPASS( 34, 0, 0, srlv, 0x01000000, 0x80000000, 7 )
  TEST_RR_SRC21_BYPASS( 35, 0, 1, srlv, 0x00020000, 0x80000000, 14 )
  TEST_RR_SRC21_BYPASS( 36, 0, 2, srlv, 0x00000001, 0x80000000, 31 )
  TEST_RR_SRC21_BYPASS( 37, 1, 0, srlv, 0x01000000, 0x80000000, 7 )
  TEST_RR_SRC21_BYPASS( 38, 1, 1, srlv, 0x00020000, 0x80000000, 14 )
  TEST_RR_SRC21_BYPASS( 39, 2, 0, srlv, 0x00000001, 0x80000000, 31 )

  TEST_RR_ZEROSRC1( 40, srlv, 0, 15 )
  TEST_RR_ZEROSRC2( 41, srlv, 32, 32 )
  TEST_RR_ZEROSRC12( 42, srlv, 0 )
  TEST_RR_ZERODEST( 43, srlv, 1024, 2048 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
