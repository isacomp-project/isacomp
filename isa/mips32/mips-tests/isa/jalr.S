/* MIPS32 JALR instruction tests */
/* Based on riscv-tests structure */
/* JALR rd, rs: jump to rs, save return address in rd */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic tests
   *-------------------------------------------------------------*/

test_2:
  li TESTNUM, 2
  li $t0, 0
  la $t1, target_2
  la $t2, ret_addr_2

  jalr $ra, $t1
  nop
ret_addr_2:
  j cont_2
  nop

target_2:
  /* Return address should be pc+8 (instruction after delay slot) */
  bne $ra, $t2, fail
  nop
  jr $ra
  nop
cont_2:

  /*-------------------------------------------------------------
   * Test with different destination register
   *-------------------------------------------------------------*/

test_3:
  li TESTNUM, 3
  la $t1, target_3
  la $t2, ret_addr_3

  jalr $t3, $t1
  nop
ret_addr_3:
  j cont_3
  nop

target_3:
  /* Return address should be pc+8 (instruction after delay slot) */
  bne $t3, $t2, fail
  nop
  jr $t3
  nop
cont_3:

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_JALR_SRC1_BYPASS( 4, 0 )
  TEST_JALR_SRC1_BYPASS( 5, 1 )
  TEST_JALR_SRC1_BYPASS( 6, 2 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
