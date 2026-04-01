/* j2 (SuperH-2) MOV.W R0,@(disp,Rn) instruction tests */
/* Stores low word of R0 to address (Rn+disp*2) */
/* Note: source is always R0, disp is scaled by 2 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MOV.W R0, @(disp,Rn) - Store word with displacement
   *-------------------------------------------------------------*/

  /* Test 2: Store word with disp=0 */
test_2:
    mova movw_disp_st_area_2, r0
    mov r0, r1        /* r1 = base address */
    mov.l movw_disp_st_val_2, r0
    mov.w r0, @(0, r1)
    /* Read back */
    mov.w @r1, r2
    mov.l movw_disp_st_val_2, r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop
    .align 2
movw_disp_st_area_2:
    .long 0
movw_disp_st_val_2:
    .long 0x1234

  /* Test 3: Store word at offset 4 bytes (disp=4) */
test_3:
    mova movw_disp_st_area_3, r0
    mov r0, r1
    mov.l movw_disp_st_val_3, r0
    mov.w r0, @(4, r1)  /* offset 4 bytes */
    /* Read back from offset 4 */
    add #4, r1
    mov.w @r1, r2
    mov.l movw_disp_st_val_3, r3
    cmp/eq r2, r3
    bf fail
    bra test_4
    nop
    .align 2
movw_disp_st_area_3:
    .long 0
    .long 0   /* more space for offset 4 */
movw_disp_st_val_3:
    .long 0x5678

  /* Test 4: Only low word stored */
test_4:
    mova movw_disp_st_area_4, r0
    mov r0, r1
    mov.l movw_disp_st_val_4, r0  /* 0x12345678 */
    mov.w r0, @(0, r1)
    mov.w @r1, r2
    mov.l movw_disp_st_exp_4, r3
    cmp/eq r2, r3
    bf fail
    bra test_end
    nop
    .align 2
movw_disp_st_area_4:
    .long 0
movw_disp_st_val_4:
    .long 0x12345678
movw_disp_st_exp_4:
    .long 0x00005678

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
