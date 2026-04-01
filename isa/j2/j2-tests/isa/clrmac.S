/* j2 (SuperH-2) CLRMAC instruction tests */
/* CLRMAC clears both MACH and MACL registers to 0 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * CLRMAC - Clear MAC registers
   *-------------------------------------------------------------*/

  /* Test 2: Clear MAC after setting values */
test_2:
    /* Set MACH and MACL to non-zero values */
    mov #-1, r0
    lds r0, mach
    lds r0, macl
    /* Execute CLRMAC */
    clrmac
    /* Check MACL is 0 */
    sts macl, r1
    mov #0, r2
    cmp/eq r1, r2
    bf fail
    /* Check MACH is 0 */
    sts mach, r1
    cmp/eq r1, r2
    bf fail
    bra test_3
    nop

  /* Test 3: Clear MAC with different values */
test_3:
    /* Set specific values */
    mov.l clrmac_val_3, r0
    lds r0, mach
    mov.l clrmac_val_3b, r0
    lds r0, macl
    /* Execute CLRMAC */
    clrmac
    /* Check both are 0 */
    sts macl, r1
    mov #0, r2
    cmp/eq r1, r2
    bf fail
    sts mach, r1
    cmp/eq r1, r2
    bf fail
    bra test_4
    nop
    .align 2
clrmac_val_3:
    .long 0x12345678
clrmac_val_3b:
    .long 0x9ABCDEF0

  /* Test 4: Clear MAC when already zero (should remain zero) */
test_4:
    mov #0, r0
    lds r0, mach
    lds r0, macl
    clrmac
    sts macl, r1
    mov #0, r2
    cmp/eq r1, r2
    bf fail
    sts mach, r1
    cmp/eq r1, r2
    bf fail
    bra test_end
    nop

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
