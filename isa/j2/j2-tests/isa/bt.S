/* j2 (SuperH-2) BT instruction tests */
/* BT disp - branches if T=1 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch if True tests
   *-------------------------------------------------------------*/

  /* Test 2: T=1, BT should branch */
test_2:
    sett            /* Set T=1 */
    bt 1f
    nop
    bra fail        /* Should not reach here */
    nop
1:  bra test_3      /* Continue to next test */
    nop

  /* Test 3: T=0, BT should NOT branch */
test_3:
    clrt            /* Clear T=0 */
    bt 1f
    nop
    bra test_4      /* Should continue here */
    nop
1:  bra fail        /* Should not reach here */
    nop

  /* Test 4: Compare equal, BT should branch */
test_4:
    mov #5, r1
    mov #5, r2
    cmp/eq r1, r2   /* T=1 (equal) */
    bt 1f
    nop
    bra fail
    nop
1:  bra test_5
    nop

  /* Test 5: Compare not equal, BT should NOT branch */
test_5:
    mov #5, r1
    mov #6, r2
    cmp/eq r1, r2   /* T=0 (not equal) */
    bt 1f
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
