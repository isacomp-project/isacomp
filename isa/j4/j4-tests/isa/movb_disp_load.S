/* j2 (SuperH-2) MOV.B @(disp,Rm),R0 instruction tests */
/* Loads byte from (Rm+disp) into R0 with sign extension */
/* Note: destination is always R0 for this addressing mode */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MOV.B @(disp,Rm), R0 - Load byte with displacement
   *-------------------------------------------------------------*/

  /* Test 2: Load byte with disp=0 */
test_2:
    mova movb_disp_data_2, r0
    mov r0, r1        /* r1 = base address */
    mov.b @(0, r1), r0
    mov #0x12, r2
    cmp/eq r0, r2
    bf fail
    bra test_3
    nop
    .align 2
movb_disp_data_2:
    .byte 0x12
    .align 2

  /* Test 3: Load byte with disp=2 */
test_3:
    mova movb_disp_data_3, r0
    mov r0, r1
    mov.b @(2, r1), r0
    mov #0x33, r2
    cmp/eq r0, r2
    bf fail
    bra test_4
    nop
    .align 2
movb_disp_data_3:
    .byte 0x11, 0x22, 0x33, 0x44
    .align 2

  /* Test 4: Sign extension for 0x80 */
test_4:
    mova movb_disp_data_4, r0
    mov r0, r1
    mov.b @(0, r1), r0
    mov #-128, r2
    cmp/eq r0, r2
    bf fail
    bra test_5
    nop
    .align 2
movb_disp_data_4:
    .byte 0x80
    .align 2

  /* Test 5: Sign extension for 0xFF */
test_5:
    mova movb_disp_data_5, r0
    mov r0, r1
    mov.b @(0, r1), r0
    mov #-1, r2
    cmp/eq r0, r2
    bf fail
    bra test_end
    nop
    .align 2
movb_disp_data_5:
    .byte 0xff
    .align 2

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
