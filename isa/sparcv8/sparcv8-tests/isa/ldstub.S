/* SPARCv8 LDSTUB instruction tests (atomic load-store unsigned byte) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * LDSTUB: Atomic load-store unsigned byte
   * rd <- zero_extend(mem[addr][byte])
   * mem[addr][byte] <- 0xFF
   * Used for implementing spinlocks
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: Basic ldstub - load byte and set to 0xFF
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set tdat0, %l2
    ldstub [%l2], %l1     /* Load byte, set to 0xFF */
    /* l1 should have zero-extended original byte (0x12) */
    cmp %l1, 0x12
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: Verify ldstub wrote 0xFF to memory
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set tdat4, %l2
    ldstub [%l2], %l1
    /* Now load byte from same location to verify it's 0xFF */
    ldub [%l2], %l3
    cmp %l3, 0xFF
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: LDSTUB at byte offset 1
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set tdat8, %l2
    ldstub [%l2 + 1], %l1  /* Load byte at offset 1 */
    /* Should get byte 1 of 0xAABBCCDD = 0xBB (big-endian) */
    cmp %l1, 0xBB
    be test_4_pass
    nop
    ba fail
    nop
test_4_pass:

  /*-------------------------------------------------------------
   * Test 5: LDSTUB at byte offset 2
   *-------------------------------------------------------------*/
test_5:
    mov 5, TESTNUM
    set tdat12, %l2
    ldstub [%l2 + 2], %l1  /* Load byte at offset 2 */
    /* Should get byte 2 of 0x11223344 = 0x33 (big-endian) */
    cmp %l1, 0x33
    be test_5_pass
    nop
    ba fail
    nop
test_5_pass:

  /*-------------------------------------------------------------
   * Test 6: LDSTUB at byte offset 3
   *-------------------------------------------------------------*/
test_6:
    mov 6, TESTNUM
    set tdat16, %l2
    ldstub [%l2 + 3], %l1  /* Load byte at offset 3 */
    /* Should get byte 3 of 0x55667788 = 0x88 (big-endian) */
    cmp %l1, 0x88
    be test_6_pass
    nop
    ba fail
    nop
test_6_pass:

  /*-------------------------------------------------------------
   * Test 7: LDSTUB to %g0 still writes 0xFF
   *-------------------------------------------------------------*/
test_7:
    mov 7, TESTNUM
    set tdat20, %l2
    ldstub [%l2], %g0     /* Discard loaded value, but write 0xFF */
    /* Verify byte is now 0xFF */
    ldub [%l2], %l1
    cmp %l1, 0xFF
    be test_7_pass
    nop
    ba fail
    nop
test_7_pass:

  /*-------------------------------------------------------------
   * Test 8: LDSTUB twice - second should return 0xFF
   *-------------------------------------------------------------*/
test_8:
    mov 8, TESTNUM
    set tdat24, %l2
    ldstub [%l2], %l1     /* First: get original, set to 0xFF */
    ldstub [%l2], %l3     /* Second: get 0xFF */
    cmp %l3, 0xFF
    be test_8_pass
    nop
    ba fail
    nop
test_8_pass:

  /*-------------------------------------------------------------
   * Test 9: LDSTUB original value is zero-extended
   *-------------------------------------------------------------*/
test_9:
    mov 9, TESTNUM
    set tdat28, %l2
    ldstub [%l2], %l1     /* Load 0xFE, should be 0x000000FE */
    set 0x000000FE, %l3
    cmp %l1, %l3
    be test_9_pass
    nop
    ba fail
    nop
test_9_pass:

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  .align 4
tdat:
tdat0:  .word 0x12345678
tdat4:  .word 0x9ABCDEF0
tdat8:  .word 0xAABBCCDD
tdat12: .word 0x11223344
tdat16: .word 0x55667788
tdat20: .word 0x00112233
tdat24: .word 0x44556677
tdat28: .word 0xFEDCBA98
SPARCV8_DATA_END
