/* j2 (SuperH-2) MOV.B @Rm+,Rn instruction tests */
/* Loads byte from @Rm into Rn with sign extension, then increments Rm by 1 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MOV.B @Rm+, Rn - Load byte with post-increment
   *-------------------------------------------------------------*/

  /* Test 2: Load positive byte 0x12, check sign extension */
test_2:
    mova movb_postinc_data_2, r0
    mov r0, r1
    mov.b @r1+, r2
    mov #0x12, r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop
    .align 2
movb_postinc_data_2:
    .byte 0x12
    .align 2

  /* Test 3: Load negative byte 0x80, sign extends to 0xFFFFFF80 */
test_3:
    mova movb_postinc_data_3, r0
    mov r0, r1
    mov.b @r1+, r2
    mov #-128, r3
    cmp/eq r2, r3
    bf fail
    bra test_4
    nop
    .align 2
movb_postinc_data_3:
    .byte 0x80
    .align 2

  /* Test 4: Check post-increment by 1 */
test_4:
    mova movb_postinc_data_4, r0
    mov r0, r1
    mov r0, r4      /* save original address */
    mov.b @r1+, r2
    /* r1 should be r4 + 1 */
    sub r4, r1
    mov #1, r3
    cmp/eq r1, r3
    bf fail
    bra test_5
    nop
    .align 2
movb_postinc_data_4:
    .byte 0x55
    .align 2

  /* Test 5: Multiple post-increment loads */
test_5:
    mova movb_postinc_data_5, r0
    mov r0, r1
    mov.b @r1+, r2    /* load 0x11 */
    mov.b @r1+, r3    /* load 0x22 */
    mov.b @r1+, r4    /* load 0x33 */
    /* Check values */
    mov #0x11, r5
    cmp/eq r2, r5
    bf fail
    mov #0x22, r5
    cmp/eq r3, r5
    bf fail
    mov #0x33, r5
    cmp/eq r4, r5
    bf fail
    bra test_end
    nop
    .align 2
movb_postinc_data_5:
    .byte 0x11, 0x22, 0x33, 0x44
    .align 2

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
