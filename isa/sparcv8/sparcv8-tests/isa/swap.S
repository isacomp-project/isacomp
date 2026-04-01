/* SPARCv8 SWAP instruction tests (atomic swap) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * SWAP: Atomic swap memory and register
   * temp <- mem[addr], mem[addr] <- rd, rd <- temp
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: Basic swap - read value from memory
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set tdat0, %l2
    set 0x12345678, %l1
    swap [%l2], %l1
    /* l1 should now contain original memory value (0xAAAA5555) */
    set 0xAAAA5555, %l3
    cmp %l1, %l3
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: Verify swap wrote to memory
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set tdat4, %l2
    set 0xDEADBEEF, %l1
    swap [%l2], %l1
    /* Now load from same location to verify */
    ld [%l2], %l3
    set 0xDEADBEEF, %l4
    cmp %l3, %l4
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Swap with offset
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set tdat0, %l2
    set 0x11223344, %l1
    swap [%l2 + 8], %l1    /* Swap at tdat8 */
    /* l1 should have original value from tdat8 */
    set 0xCCCCDDDD, %l3
    cmp %l1, %l3
    be test_4_pass
    nop
    ba fail
    nop
test_4_pass:

  /*-------------------------------------------------------------
   * Test 5: Swap returns old value, stores new value
   * Swap same location twice
   *-------------------------------------------------------------*/
test_5:
    mov 5, TESTNUM
    set tdat12, %l2
    set 0x11111111, %l1
    swap [%l2], %l1        /* l1 <- old, mem <- 0x11111111 */
    /* l1 should have original 0xEEEEFFFF */
    set 0xEEEEFFFF, %l3
    cmp %l1, %l3
    bne fail
    nop
    /* Now swap again with different value */
    set 0x22222222, %l1
    swap [%l2], %l1        /* l1 <- 0x11111111, mem <- 0x22222222 */
    set 0x11111111, %l3
    cmp %l1, %l3
    be test_5_pass
    nop
    ba fail
    nop
test_5_pass:

  /*-------------------------------------------------------------
   * Test 6: Swap with %g0 as destination
   * Store 0 to memory, discard loaded value
   *-------------------------------------------------------------*/
test_6:
    mov 6, TESTNUM
    set tdat16, %l2
    swap [%l2], %g0        /* Store 0, discard old value */
    /* Verify memory is now 0 */
    ld [%l2], %l1
    cmp %l1, 0
    be test_6_pass
    nop
    ba fail
    nop
test_6_pass:

  /*-------------------------------------------------------------
   * Test 7: Swap with negative offset
   *-------------------------------------------------------------*/
test_7:
    mov 7, TESTNUM
    set tdat8, %l2
    set 0x55667788, %l1
    swap [%l2 - 4], %l1    /* Swap at tdat4 (after test_3 modified it) */
    /* l1 should have 0xDEADBEEF from test_3 */
    set 0xDEADBEEF, %l3
    cmp %l1, %l3
    be test_7_pass
    nop
    ba fail
    nop
test_7_pass:

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  .align 4
tdat:
tdat0:  .word 0xAAAA5555
tdat4:  .word 0xBBBB6666
tdat8:  .word 0xCCCCDDDD
tdat12: .word 0xEEEEFFFF
tdat16: .word 0x12345678
SPARCV8_DATA_END
