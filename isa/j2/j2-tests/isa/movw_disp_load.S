/* j2 (SuperH-2) MOV.W @(disp,Rm),R0 instruction tests */
/* Loads word from (Rm+disp*2) into R0 with sign extension */
/* Note: destination is always R0, disp is scaled by 2 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MOV.W @(disp,Rm), R0 - Load word with displacement
   *-------------------------------------------------------------*/

  /* Test 2: Load word with disp=0 */
test_2:
    mova movw_disp_data_2, r0
    mov r0, r1        /* r1 = base address */
    mov.w @(0, r1), r0
    mov.l movw_disp_exp_2, r2
    cmp/eq r0, r2
    bf fail
    bra test_3
    nop
    .align 2
movw_disp_data_2:
    .word 0x1234
    .word 0       /* padding */
movw_disp_exp_2:
    .long 0x00001234

  /* Test 3: Load word at offset 4 bytes (disp=4) */
test_3:
    mova movw_disp_data_3, r0
    mov r0, r1
    mov.w @(4, r1), r0   /* offset 4 bytes */
    mov.l movw_disp_exp_3, r2
    cmp/eq r0, r2
    bf fail
    bra test_4
    nop
    .align 2
movw_disp_data_3:
    .word 0x1111  /* offset 0 */
    .word 0x2222  /* offset 2 */
    .word 0x3333  /* offset 4 - this is what we load */
    .word 0x4444  /* offset 6 */
movw_disp_exp_3:
    .long 0x00003333

  /* Test 4: Sign extension for 0x8000 */
test_4:
    mova movw_disp_data_4, r0
    mov r0, r1
    mov.w @(0, r1), r0
    mov.l movw_disp_exp_4, r2
    cmp/eq r0, r2
    bf fail
    bra test_5
    nop
    .align 2
movw_disp_data_4:
    .word 0x8000
    .word 0       /* padding */
movw_disp_exp_4:
    .long 0xffff8000

  /* Test 5: Sign extension for 0xFFFF */
test_5:
    mova movw_disp_data_5, r0
    mov r0, r1
    mov.w @(0, r1), r0
    mov #-1, r2
    cmp/eq r0, r2
    bf fail
    bra test_end
    nop
    .align 2
movw_disp_data_5:
    .word 0xffff
    .word 0       /* padding */

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
