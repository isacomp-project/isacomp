/* j2 (SuperH-2) JSR instruction tests */
/* JSR @Rn - jump to subroutine, saving return address in PR */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Jump to subroutine tests
   *-------------------------------------------------------------*/

  /* Test 2: Basic jsr and rts */
test_2:
    mov #0, r2
    mov.l jsr_sub_2, r0
    jsr @r0
    nop
    /* Should return here with r2 = 5 */
    mov #5, r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop
    .align 2
jsr_sub_2:
    .long sub_2_code
    .align 2
sub_2_code:
    mov #5, r2
    rts
    nop

  /* Test 3: JSR delay slot executes */
test_3:
    mov #0, r2
    mov.l jsr_sub_3, r0
    jsr @r0
    mov #10, r2          /* Delay slot - should execute */
    /* Should return here with r2 = 10 */
    mov #10, r3
    cmp/eq r2, r3
    bf fail
    bra test_4
    nop
    .align 2
jsr_sub_3:
    .long sub_3_code
    .align 2
sub_3_code:
    rts
    nop

  /* Test 4: JSR return value from subroutine */
test_4:
    mov #0, r2
    mov.l jsr_sub_4, r0
    jsr @r0
    nop
    /* Subroutine sets r1, we copy to r2 */
    mov r1, r2
    mov #7, r3
    cmp/eq r2, r3
    bf fail
    bra test_end
    nop
    .align 2
jsr_sub_4:
    .long sub_4_code
    .align 2
sub_4_code:
    mov #7, r1
    rts
    nop

test_end:
    TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
