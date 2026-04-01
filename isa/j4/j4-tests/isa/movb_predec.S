/* j2 (SuperH-2) MOV.B Rm,@-Rn instruction tests */
/* Decrements Rn by 1, then stores low byte of Rm to @Rn */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MOV.B Rm, @-Rn - Store byte with pre-decrement
   *-------------------------------------------------------------*/

  /* Test 2: Store byte 0x12 with pre-decrement */
test_2:
    mova movb_predec_area_2, r0
    add #4, r0        /* point to end+1 of area */
    mov r0, r1        /* r1 = destination pointer */
    mov #0x12, r2     /* value to store */
    mov.b r2, @-r1    /* pre-dec and store */
    /* Read back and verify */
    mov.b @r1, r3
    mov #0x12, r4
    cmp/eq r3, r4
    bf fail
    bra test_3
    nop
    .align 2
movb_predec_area_2:
    .long 0           /* storage area */

  /* Test 3: Check pre-decrement by 1 */
test_3:
    mova movb_predec_area_3, r0
    add #4, r0
    mov r0, r1
    mov r0, r4        /* save original */
    mov #0x55, r2
    mov.b r2, @-r1
    /* r1 should be r4 - 1 */
    sub r1, r4        /* r4 = original - r1 */
    mov #1, r3
    cmp/eq r4, r3
    bf fail
    bra test_4
    nop
    .align 2
movb_predec_area_3:
    .long 0

  /* Test 4: Multiple pre-decrement stores */
test_4:
    mova movb_predec_area_4, r0
    add #4, r0
    mov r0, r1
    mov #0x33, r2
    mov.b r2, @-r1    /* store 0x33 */
    mov #0x22, r2
    mov.b r2, @-r1    /* store 0x22 */
    mov #0x11, r2
    mov.b r2, @-r1    /* store 0x11 */
    /* Read back first byte */
    mov.b @r1, r3
    mov #0x11, r4
    cmp/eq r3, r4
    bf fail
    bra test_end
    nop
    .align 2
movb_predec_area_4:
    .long 0

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
