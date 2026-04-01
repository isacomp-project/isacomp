/* j2 (SuperH-2) Address Error Exception tests */
/* NOTE: Full exception testing requires system-level infrastructure.
 * This file contains basic tests for aligned memory access.
 * Misaligned access exception testing requires:
 * - VBR setup (LDC VBR)
 * - Stack memory setup
 * - Exception handler installation
 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Test 1: Aligned word load (should work normally)
   *-------------------------------------------------------------*/
  TEST_CASE( 2, r2, 0x1234, \
    mov.l test_2_aligned_word_addr, r1; \
    mov.w @r1, r2; \
    exts.w r2, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_aligned_word_addr: \
    .long test_2_word_data; \
  3: \
    bra 4f; \
    nop; \
    .align 2; \
  test_2_word_data: \
    .word 0x1234; \
    .word 0x0000; \
  4: \
  )

  /*-------------------------------------------------------------
   * Test 2: Aligned long load (should work normally)
   *-------------------------------------------------------------*/
  TEST_CASE( 3, r2, 0xDEADBEEF, \
    mov.l test_3_aligned_long_addr, r1; \
    mov.l @r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_3_aligned_long_addr: \
    .long test_3_long_data; \
  3: \
    bra 4f; \
    nop; \
    .align 4; \
  test_3_long_data: \
    .long 0xDEADBEEF; \
  4: \
  )

  /*-------------------------------------------------------------
   * Test 3: Aligned word store and load-back (should work normally)
   *-------------------------------------------------------------*/
  TEST_CASE( 4, r3, 0x5678, \
    mov.l test_4_store_addr, r1; \
    mov.l test_4_store_val, r2; \
    mov.w r2, @r1; \
    mov.w @r1, r3; \
    exts.w r3, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_store_addr: \
    .long test_4_store_loc; \
  test_4_store_val: \
    .long 0x5678; \
  3: \
    bra 4f; \
    nop; \
    .align 4; \
  test_4_store_loc: \
    .long 0; \
  4: \
  )

  /*-------------------------------------------------------------
   * Test 4: Aligned long store and load-back (should work normally)
   *-------------------------------------------------------------*/
  TEST_CASE( 5, r3, 0xCAFEBABE, \
    mov.l test_5_store_addr, r1; \
    mov.l test_5_store_val, r2; \
    mov.l r2, @r1; \
    mov.l @r1, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_5_store_addr: \
    .long test_5_store_loc; \
  test_5_store_val: \
    .long 0xCAFEBABE; \
  3: \
    bra 4f; \
    nop; \
    .align 4; \
  test_5_store_loc: \
    .long 0; \
  4: \
  )

  /* Note: Misaligned access tests are commented out because they
   * require exception handling infrastructure:
   *
   * - Vector Base Register (VBR) must be set up
   * - Exception handlers must be installed
   * - Stack pointer (R15) must point to valid memory
   *
   * To test address error exceptions:
   * 1. Set up VBR with ldc r0, vbr
   * 2. Install handler at VBR + 0x1C (read error) or VBR + 0x20 (write error)
   * 3. Access misaligned address (mov.w @odd_addr, r0)
   * 4. Exception handler should be called, verify by checking saved PC
   */

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
