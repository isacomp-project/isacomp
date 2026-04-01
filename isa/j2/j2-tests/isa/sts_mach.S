/* j2 (SuperH-2) STS MACH,Rn instruction tests */
/* Stores the MACH register value into a register */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * STS MACH, Rn - Store from MACH register
   *-------------------------------------------------------------*/

  /* Test 2: Store MACH to register */
  TEST_CASE( 2, r3, 0x87654321, \
    mov.l test_2_val, r1; \
    lds r1, mach; \
    sts mach, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_val: \
    .long 0x87654321; \
  3: \
  )

  /* Test 3: Store to different registers */
test_3:
    mov.l test_3_val, r0
    lds r0, mach
    sts mach, r1
    sts mach, r2
    sts mach, r3
    /* All should be equal */
    cmp/eq r1, r2
    bf fail
    cmp/eq r2, r3
    bf fail
    mov.l test_3_val, r4
    cmp/eq r3, r4
    bf fail
    bra test_end
    nop
    .align 2
test_3_val:
    .long 0x11223344

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
