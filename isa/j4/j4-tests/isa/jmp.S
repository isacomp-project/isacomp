/* j2 (SuperH-2) JMP instruction tests */
/* JMP @Rn - jump to address in register with delay slot */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Jump tests
   *-------------------------------------------------------------*/

  /* Test 2: Basic jmp - value preserved after jump */
test_2:
    mov #5, r2
    mov.l jmp_target_2, r0
    jmp @r0
    nop
    mov #0, r2           /* Should not execute */
    .align 2
jmp_target_2:
    .long jmp_2_dest
    .align 2
jmp_2_dest:
    /* Verify r2 = 5 */
    mov #5, r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop

  /* Test 3: JMP delay slot executes */
test_3:
    mov #0, r2
    mov.l jmp_target_3, r0
    jmp @r0
    mov #10, r2          /* Delay slot - should execute */
    mov #0, r2           /* Should not execute */
    .align 2
jmp_target_3:
    .long jmp_3_dest
    .align 2
jmp_3_dest:
    /* Verify r2 = 10 */
    mov #10, r3
    cmp/eq r2, r3
    bf fail
    bra test_4
    nop

  /* Test 4: JMP forward skip */
test_4:
    mov #7, r3
    mov.l jmp_target_4, r0
    jmp @r0
    nop
    mov #0, r3           /* Should not execute */
    mov #0, r3           /* Should not execute */
    .align 2
jmp_target_4:
    .long jmp_4_dest
    .align 2
jmp_4_dest:
    /* Verify r3 = 7 */
    mov #7, r4
    cmp/eq r3, r4
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
