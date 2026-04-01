/* j2 (SuperH-2) DMULU.L instruction tests */
/* DMULU.L performs unsigned 32x32->64 multiply, result in MACH:MACL */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * DMULU.L - Double multiply unsigned
   *-------------------------------------------------------------*/

  /* Test 2: 3 * 4 = 12 */
  TEST_CASE( 2, r3, 0x0000000c, \
    mov #3, r1; \
    mov #4, r2; \
    dmulu.l r2, r1; \
    sts macl, r3; \
  )

  /* Test 3: Check MACH is 0 for small result */
  TEST_CASE( 3, r3, 0x00000000, \
    mov #10, r1; \
    mov #20, r2; \
    dmulu.l r2, r1; \
    sts mach, r3; \
  )

  /* Test 4: 0xFFFFFFFF * 2 = 0x1FFFFFFFE */
  /* MACL = 0xFFFFFFFE, MACH = 1 */
test_4:
    mov #-1, r1       /* 0xFFFFFFFF as unsigned */
    mov #2, r2
    dmulu.l r2, r1
    sts macl, r3
    mov.l test_4_expected, r4
    cmp/eq r3, r4
    bf fail
    sts mach, r3
    mov #1, r4
    cmp/eq r3, r4
    bf fail
    bra test_5
    nop
    .align 2
test_4_expected:
    .long 0xfffffffe

  /* Test 5: Large multiply: 0x10000 * 0x10000 = 0x100000000 */
test_5:
    mov.l test_5_val, r1
    mov.l test_5_val, r2
    dmulu.l r2, r1
    sts mach, r3
    mov #1, r4
    cmp/eq r3, r4
    bf fail
    sts macl, r3
    mov #0, r4
    cmp/eq r3, r4
    bf fail
    bra test_6
    nop
    .align 2
test_5_val:
    .long 0x00010000

  /* Test 6: 0x80000000 * 2 = 0x100000000 (unsigned) */
test_6:
    mov.l test_6_val, r1
    mov #2, r2
    dmulu.l r2, r1
    sts mach, r3
    mov #1, r4
    cmp/eq r3, r4
    bf fail
    sts macl, r3
    mov #0, r4
    cmp/eq r3, r4
    bf fail
    bra test_end
    nop
    .align 2
test_6_val:
    .long 0x80000000

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
