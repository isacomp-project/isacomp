/* MIPS32 BGEZAL instruction tests */
/* bgezal rs, offset - Branch on Greater Than or Equal to Zero and Link */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch taken tests - verify link register set
   *-------------------------------------------------------------*/

  /* Test 2: Branch on zero, verify link */
test_2:
    li TESTNUM, 2
    li $t1, 0
    la $t2, ret_addr2
    bgezal $t1, 1f
    nop
ret_addr2:
    j cont2
    nop
1:  /* Check that $ra points to instruction after delay slot */
    bne $ra, $t2, fail
    nop
    jr $ra
    nop
cont2:

  /* Test 3: Branch on positive, verify link */
test_3:
    li TESTNUM, 3
    li $t1, 1
    la $t2, ret_addr3
    bgezal $t1, 1f
    nop
ret_addr3:
    j cont3
    nop
1:  bne $ra, $t2, fail
    nop
    jr $ra
    nop
cont3:

  /* Test 4: Branch on large positive */
test_4:
    li TESTNUM, 4
    li $t1, 0x7FFFFFFF
    la $t2, ret_addr4
    bgezal $t1, 1f
    nop
ret_addr4:
    j cont4
    nop
1:  bne $ra, $t2, fail
    nop
    jr $ra
    nop
cont4:

  /*-------------------------------------------------------------
   * Branch not taken tests - link still set
   *-------------------------------------------------------------*/

  /* Test 5: Branch on -1 (not taken), but link still set */
test_5:
    li TESTNUM, 5
    li $t1, -1
    la $t3, ret_addr5
    bgezal $t1, fail
    nop
ret_addr5:
    /* ra should point after delay slot even when not taken */
    bne $ra, $t3, fail
    nop

  /* Test 6: Branch on 0x80000000 (not taken) */
test_6:
    li TESTNUM, 6
    li $t1, 0x80000000
    la $t3, ret_addr6
    bgezal $t1, fail
    nop
ret_addr6:
    bne $ra, $t3, fail
    nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
