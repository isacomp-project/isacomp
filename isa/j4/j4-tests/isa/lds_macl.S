/* j2 (SuperH-2) LDS Rm,MACL instruction tests */
/* Loads a register value into the MACL register */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * LDS Rm, MACL - Load to MACL register
   *-------------------------------------------------------------*/

  /* Test 2: Load 0xDEADBEEF to MACL */
  TEST_CASE( 2, r3, 0xdeadbeef, \
    mov.l test_2_val, r1; \
    lds r1, macl; \
    sts macl, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_val: \
    .long 0xdeadbeef; \
  3: \
  )

  /* Test 3: Load 0 to MACL */
  TEST_CASE( 3, r3, 0x00000000, \
    mov #0, r1; \
    lds r1, macl; \
    sts macl, r3; \
  )

  /* Test 4: Load immediate value to MACL */
  TEST_CASE( 4, r3, 0x0000007f, \
    mov #127, r1; \
    lds r1, macl; \
    sts macl, r3; \
  )

  /* Test 5: MACL and MACH are independent */
test_5:
    mov.l test_5_macl, r1
    mov.l test_5_mach, r2
    lds r1, macl
    lds r2, mach
    /* Check MACL */
    sts macl, r3
    cmp/eq r3, r1
    bf fail
    /* Check MACH */
    sts mach, r4
    cmp/eq r4, r2
    bf fail
    bra test_end
    nop
    .align 2
test_5_macl:
    .long 0x11111111
test_5_mach:
    .long 0x22222222

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
