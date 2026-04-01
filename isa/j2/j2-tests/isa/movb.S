/* j2 (SuperH-2) MOV.B load instruction tests */
/* MOV.B @Rm, Rn loads sign-extended 8-bit value from memory */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Load byte tests
   *-------------------------------------------------------------*/

  /* Test 2: Load positive byte 0x12 */
test_2:
    mova movb_data_2, r0
    mov.b @r0, r2
    mov #0x12, r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop
    .align 2
movb_data_2:
    .byte 0x12
    .align 2

  /* Test 3: Load negative byte 0x80 -> sign extends to 0xFFFFFF80 */
test_3:
    mova movb_data_3, r0
    mov.b @r0, r2
    mov #-128, r3        /* 0xFFFFFF80 */
    cmp/eq r2, r3
    bf fail
    bra test_4
    nop
    .align 2
movb_data_3:
    .byte 0x80
    .align 2

  /* Test 4: Load 0xFF -> sign extends to 0xFFFFFFFF */
test_4:
    mova movb_data_4, r0
    mov.b @r0, r2
    mov #-1, r3
    cmp/eq r2, r3
    bf fail
    bra test_5
    nop
    .align 2
movb_data_4:
    .byte 0xff
    .align 2

  /* Test 5: Load zero */
test_5:
    mova movb_data_5, r0
    mov.b @r0, r2
    mov #0, r3
    cmp/eq r2, r3
    bf fail
    bra test_6
    nop
    .align 2
movb_data_5:
    .byte 0x00
    .align 2

  /* Test 6: Load 0x7F (max positive byte) */
test_6:
    mova movb_data_6, r0
    mov.b @r0, r2
    mov #0x7f, r3
    cmp/eq r2, r3
    bf fail
    bra test_end
    nop
    .align 2
movb_data_6:
    .byte 0x7f
    .align 2

test_end:
    TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
