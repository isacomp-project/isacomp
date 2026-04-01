/* j2 (SuperH-2) MOV.W Rm,@-Rn instruction tests */
/* Decrements Rn by 2, then stores low word of Rm to @Rn */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MOV.W Rm, @-Rn - Store word with pre-decrement
   *-------------------------------------------------------------*/

  /* Test 2: Store word 0x1234 with pre-decrement */
test_2:
    mova movw_predec_area_2, r0
    add #4, r0        /* point past the area */
    mov r0, r1        /* r1 = destination pointer */
    mov.l movw_predec_val_2, r2
    mov.w r2, @-r1    /* pre-dec and store */
    /* Read back and verify */
    mov.w @r1, r3
    mov.l movw_predec_val_2, r4
    cmp/eq r3, r4
    bf fail
    bra test_3
    nop
    .align 2
movw_predec_area_2:
    .long 0
movw_predec_val_2:
    .long 0x1234

  /* Test 3: Check pre-decrement by 2 */
test_3:
    mova movw_predec_area_3, r0
    add #4, r0
    mov r0, r1
    mov r0, r4        /* save original */
    mov.l movw_predec_val_3, r2
    mov.w r2, @-r1
    /* r1 should be r4 - 2 */
    sub r1, r4
    mov #2, r3
    cmp/eq r4, r3
    bf fail
    bra test_4
    nop
    .align 2
movw_predec_area_3:
    .long 0
movw_predec_val_3:
    .long 0x5555

  /* Test 4: Multiple pre-decrement stores */
test_4:
    mova movw_predec_area_4, r0
    add #8, r0
    mov r0, r1
    mov.l movw_predec_val_4b, r2
    mov.w r2, @-r1
    mov.l movw_predec_val_4a, r2
    mov.w r2, @-r1
    /* Read back first word */
    mov.w @r1, r3
    mov.l movw_predec_val_4a, r4
    cmp/eq r3, r4
    bf fail
    bra test_end
    nop
    .align 2
movw_predec_area_4:
    .long 0, 0
movw_predec_val_4a:
    .long 0x1111
movw_predec_val_4b:
    .long 0x2222

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
