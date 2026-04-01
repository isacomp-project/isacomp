/* j2 (SuperH-2) DMULS.L instruction tests */
/* DMULS.L performs signed 32x32->64 multiply, result in MACH:MACL */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * DMULS.L - Double multiply signed
   *-------------------------------------------------------------*/

  /* Test 2: 3 * 4 = 12 (low 32 bits) */
  TEST_CASE( 2, r3, 0x0000000c, \
    mov #3, r1; \
    mov #4, r2; \
    dmuls.l r2, r1; \
    sts macl, r3; \
  )

  /* Test 3: Check MACH is 0 for small positive result */
  TEST_CASE( 3, r3, 0x00000000, \
    mov #10, r1; \
    mov #20, r2; \
    dmuls.l r2, r1; \
    sts mach, r3; \
  )

  /* Test 4: -3 * 4 = -12 (MACL = 0xFFFFFFF4) */
  TEST_CASE( 4, r3, 0xfffffff4, \
    mov #-3, r1; \
    mov #4, r2; \
    dmuls.l r2, r1; \
    sts macl, r3; \
  )

  /* Test 5: Check MACH is -1 for small negative result */
  TEST_CASE( 5, r3, 0xffffffff, \
    mov #-10, r1; \
    mov #20, r2; \
    dmuls.l r2, r1; \
    sts mach, r3; \
  )

  /* Test 6: -3 * -4 = 12 */
  TEST_CASE( 6, r3, 0x0000000c, \
    mov #-3, r1; \
    mov #-4, r2; \
    dmuls.l r2, r1; \
    sts macl, r3; \
  )

  /* Test 7: Large multiply: 0x10000 * 0x10000 = 0x100000000 */
  /* MACL = 0, MACH = 1 */
test_7:
    mov.l test_7_val, r1
    mov.l test_7_val, r2
    dmuls.l r2, r1
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
test_7_val:
    .long 0x00010000

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
