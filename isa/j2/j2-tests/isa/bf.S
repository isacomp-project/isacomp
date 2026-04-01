/* j2 (SuperH-2) BF instruction tests */
/* BF disp - branches if T=0 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch if False tests
   *-------------------------------------------------------------*/

  /* Test 2: T=0, BF should branch */
test_2:
    clrt            /* Clear T=0 */
    bf 1f
    nop
    bra fail        /* Should not reach here */
    nop
1:  bra test_3      /* Continue to next test */
    nop

  /* Test 3: T=1, BF should NOT branch */
test_3:
    sett            /* Set T=1 */
    bf 1f
    nop
    bra test_4      /* Should continue here */
    nop
1:  bra fail        /* Should not reach here */
    nop

  /* Test 4: Compare not equal, BF should branch */
test_4:
    mov #5, r1
    mov #6, r2
    cmp/eq r1, r2   /* T=0 (not equal) */
    bf 1f
    nop
    bra fail
    nop
1:  bra test_5
    nop

  /* Test 5: Compare equal, BF should NOT branch */
test_5:
    mov #5, r1
    mov #5, r2
    cmp/eq r1, r2   /* T=1 (equal) */
    bf 1f
    nop
    bra test_end    /* Should continue here */
    nop
1:  bra fail
    nop

test_end:
    TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
