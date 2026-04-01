/* j2 (SuperH-2) MOV.B R0,@(disp,Rn) instruction tests */
/* Stores low byte of R0 to address (Rn+disp) */
/* Note: source is always R0 for this addressing mode */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MOV.B R0, @(disp,Rn) - Store byte with displacement
   *-------------------------------------------------------------*/

  /* Test 2: Store byte with disp=0 */
test_2:
    mova movb_disp_st_area_2, r0
    mov r0, r1        /* r1 = base address */
    mov #0x42, r0     /* value to store */
    mov.b r0, @(0, r1)
    /* Read back */
    mov.b @r1, r2
    mov #0x42, r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop
    .align 2
movb_disp_st_area_2:
    .long 0

  /* Test 3: Store byte with disp=2 */
test_3:
    mova movb_disp_st_area_3, r0
    mov r0, r1
    mov #0x55, r0
    mov.b r0, @(2, r1)
    /* Read back from offset 2 */
    add #2, r1
    mov.b @r1, r2
    mov #0x55, r3
    cmp/eq r2, r3
    bf fail
    bra test_4
    nop
    .align 2
movb_disp_st_area_3:
    .long 0

  /* Test 4: Only low byte stored */
test_4:
    mova movb_disp_st_area_4, r0
    mov r0, r1
    mov.l movb_disp_st_val_4, r0  /* 0x12345678 */
    mov.b r0, @(0, r1)
    mov.b @r1, r2
    mov #0x78, r3
    cmp/eq r2, r3
    bf fail
    bra test_end
    nop
    .align 2
movb_disp_st_area_4:
    .long 0
movb_disp_st_val_4:
    .long 0x12345678

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
