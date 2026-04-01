/* j2 (SuperH-2) STS GBR,Rn instruction tests */
/* Stores the GBR register value into a register */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * STS GBR, Rn - Store from GBR register
   *-------------------------------------------------------------*/

  /* Test 2: Store GBR to register */
  TEST_CASE( 2, r3, 0xabcd0000, \
    mov.l test_2_val, r1; \
    ldc r1, gbr; \
    stc gbr, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_val: \
    .long 0xabcd0000; \
  3: \
  )

  /* Test 3: Store to multiple registers */
test_3:
    mov.l test_3_val, r0
    ldc r0, gbr
    stc gbr, r1
    stc gbr, r2
    cmp/eq r1, r2
    bf fail
    cmp/eq r0, r1
    bf fail
    bra test_end
    nop
    .align 2
test_3_val:
    .long 0x55aa55aa

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
