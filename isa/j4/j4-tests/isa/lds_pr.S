/* j2 (SuperH-2) LDS to PR instruction tests */
/* LDS Rm, PR - loads register value to procedure register */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Load to PR tests
   *-------------------------------------------------------------*/

  /* Test 2: LDS and STS PR roundtrip */
  TEST_CASE( 2, r2, 0x00000055, \
    mov #0x55, r1; \
    lds r1, pr; \
    sts pr, r2; \
  )

  /* Test 3: LDS to PR with zero */
  TEST_CASE( 3, r2, 0x00000000, \
    mov #0, r1; \
    lds r1, pr; \
    sts pr, r2; \
  )

  /* Test 4: LDS to PR with -1 */
  TEST_CASE( 4, r2, 0xffffffff, \
    mov #-1, r1; \
    lds r1, pr; \
    sts pr, r2; \
  )

  /* Test 5: LDS PR overwrite */
  TEST_CASE( 5, r3, 0x00000033, \
    mov #0x55, r1; \
    lds r1, pr; \
    mov #0x33, r2; \
    lds r2, pr; \
    sts pr, r3; \
  )

  /* Test 6: Use LDS PR for custom return */
test_6:
    mov.l lds_target_6, r0
    lds r0, pr
    mov #5, r2
    rts
    nop
    mov #0, r2           /* Should not execute */
    .align 2
lds_target_6:
    .long lds_6_dest
    .align 2
lds_6_dest:
    /* Verify r2 = 5 */
    mov #5, r3
    cmp/eq r2, r3
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
