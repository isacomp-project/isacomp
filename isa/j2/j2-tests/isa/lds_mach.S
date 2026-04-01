/* j2 (SuperH-2) LDS Rm,MACH instruction tests */
/* Loads a register value into the MACH register */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * LDS Rm, MACH - Load to MACH register
   *-------------------------------------------------------------*/

  /* Test 2: Load 0x12345678 to MACH */
  TEST_CASE( 2, r3, 0x12345678, \
    mov.l test_2_val, r1; \
    lds r1, mach; \
    sts mach, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_val: \
    .long 0x12345678; \
  3: \
  )

  /* Test 3: Load 0 to MACH */
  TEST_CASE( 3, r3, 0x00000000, \
    mov #0, r1; \
    lds r1, mach; \
    sts mach, r3; \
  )

  /* Test 4: Load -1 (0xFFFFFFFF) to MACH */
  TEST_CASE( 4, r3, 0xffffffff, \
    mov #-1, r1; \
    lds r1, mach; \
    sts mach, r3; \
  )

  /* Test 5: MACH persists through other operations */
test_5:
    mov.l test_5_val, r1
    lds r1, mach
    /* Do some other operations */
    mov #5, r2
    mov #10, r3
    add r2, r3
    /* Check MACH still has original value */
    sts mach, r4
    mov.l test_5_val, r5
    cmp/eq r4, r5
    bf fail
    bra test_end
    nop
    .align 2
test_5_val:
    .long 0xaabbccdd

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
