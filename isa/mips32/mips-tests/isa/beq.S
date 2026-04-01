/* MIPS32 BEQ instruction tests */
/* Based on riscv-tests structure */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch taken tests
   *-------------------------------------------------------------*/

  TEST_BR2_OP_TAKEN( 2, beq, 0, 0 )
  TEST_BR2_OP_TAKEN( 3, beq, 1, 1 )
  TEST_BR2_OP_TAKEN( 4, beq, -1, -1 )

  /*-------------------------------------------------------------
   * Branch not taken tests
   *-------------------------------------------------------------*/

  TEST_BR2_OP_NOTTAKEN( 5, beq, 0, 1 )
  TEST_BR2_OP_NOTTAKEN( 6, beq, 1, 0 )
  TEST_BR2_OP_NOTTAKEN( 7, beq, -1, 1 )
  TEST_BR2_OP_NOTTAKEN( 8, beq, 1, -1 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_BR2_SRC12_BYPASS( 9,  0, 0, beq, 0, -1 )
  TEST_BR2_SRC12_BYPASS( 10, 0, 1, beq, 0, -1 )
  TEST_BR2_SRC12_BYPASS( 11, 0, 2, beq, 0, -1 )
  TEST_BR2_SRC12_BYPASS( 12, 1, 0, beq, 0, -1 )
  TEST_BR2_SRC12_BYPASS( 13, 1, 1, beq, 0, -1 )
  TEST_BR2_SRC12_BYPASS( 14, 2, 0, beq, 0, -1 )

  TEST_BR2_SRC21_BYPASS( 15, 0, 0, beq, 0, -1 )
  TEST_BR2_SRC21_BYPASS( 16, 0, 1, beq, 0, -1 )
  TEST_BR2_SRC21_BYPASS( 17, 0, 2, beq, 0, -1 )
  TEST_BR2_SRC21_BYPASS( 18, 1, 0, beq, 0, -1 )
  TEST_BR2_SRC21_BYPASS( 19, 1, 1, beq, 0, -1 )
  TEST_BR2_SRC21_BYPASS( 20, 2, 0, beq, 0, -1 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
