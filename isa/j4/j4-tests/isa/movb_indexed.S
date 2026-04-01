/* j2 (SuperH-2) MOV.B @(R0,Rm),Rn instruction tests */
/* Loads byte from (R0+Rm) into Rn with sign extension */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MOV.B @(R0,Rm), Rn - Load byte indexed
   *-------------------------------------------------------------*/

  /* Test 2: Load byte with R0=0 (simple case) */
test_2:
    mova movb_idx_data_2, r0
    mov r0, r1        /* r1 = base address */
    mov #0, r0        /* r0 = 0 offset */
    mov.b @(r0, r1), r2
    mov #0x12, r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop
    .align 2
movb_idx_data_2:
    .byte 0x12
    .align 2

  /* Test 3: Load byte with offset */
test_3:
    mova movb_idx_data_3, r0
    mov r0, r1        /* r1 = base address */
    mov #2, r0        /* r0 = 2 offset */
    mov.b @(r0, r1), r2
    mov #0x33, r3
    cmp/eq r2, r3
    bf fail
    bra test_4
    nop
    .align 2
movb_idx_data_3:
    .byte 0x11, 0x22, 0x33, 0x44
    .align 2

  /* Test 4: Sign extension for negative byte */
test_4:
    mova movb_idx_data_4, r0
    mov r0, r1
    mov #0, r0
    mov.b @(r0, r1), r2
    mov #-128, r3     /* 0xFFFFFF80 */
    cmp/eq r2, r3
    bf fail
    bra test_5
    nop
    .align 2
movb_idx_data_4:
    .byte 0x80
    .align 2

  /* Test 5: Load 0xFF -> -1 */
test_5:
    mova movb_idx_data_5, r0
    mov r0, r1
    mov #0, r0
    mov.b @(r0, r1), r2
    mov #-1, r3
    cmp/eq r2, r3
    bf fail
    bra test_end
    nop
    .align 2
movb_idx_data_5:
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
