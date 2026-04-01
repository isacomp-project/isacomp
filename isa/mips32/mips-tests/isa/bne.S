/* MIPS32 BNE instruction tests */
/* Based on riscv-tests structure */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch taken tests
   *-------------------------------------------------------------*/

  TEST_BR2_OP_TAKEN( 2, bne, 0, 1 )
  TEST_BR2_OP_TAKEN( 3, bne, 1, 0 )
  TEST_BR2_OP_TAKEN( 4, bne, -1, 1 )
  TEST_BR2_OP_TAKEN( 5, bne, 1, -1 )

  /*-------------------------------------------------------------
   * Branch not taken tests
   *-------------------------------------------------------------*/

  TEST_BR2_OP_NOTTAKEN( 6, bne, 0, 0 )
  TEST_BR2_OP_NOTTAKEN( 7, bne, 1, 1 )
  TEST_BR2_OP_NOTTAKEN( 8, bne, -1, -1 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_BR2_SRC12_BYPASS( 9,  0, 0, bne, 0, 0 )
  TEST_BR2_SRC12_BYPASS( 10, 0, 1, bne, 0, 0 )
  TEST_BR2_SRC12_BYPASS( 11, 0, 2, bne, 0, 0 )
  TEST_BR2_SRC12_BYPASS( 12, 1, 0, bne, 0, 0 )
  TEST_BR2_SRC12_BYPASS( 13, 1, 1, bne, 0, 0 )
  TEST_BR2_SRC12_BYPASS( 14, 2, 0, bne, 0, 0 )

  TEST_BR2_SRC21_BYPASS( 15, 0, 0, bne, 0, 0 )
  TEST_BR2_SRC21_BYPASS( 16, 0, 1, bne, 0, 0 )
  TEST_BR2_SRC21_BYPASS( 17, 0, 2, bne, 0, 0 )
  TEST_BR2_SRC21_BYPASS( 18, 1, 0, bne, 0, 0 )
  TEST_BR2_SRC21_BYPASS( 19, 1, 1, bne, 0, 0 )
  TEST_BR2_SRC21_BYPASS( 20, 2, 0, bne, 0, 0 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
