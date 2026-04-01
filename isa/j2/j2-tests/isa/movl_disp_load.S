/* j2 (SuperH-2) MOV.L @(disp,Rm),Rn instruction tests */
/* Loads long word from (Rm+disp*4) into Rn */
/* Note: disp is scaled by 4 for long word access */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MOV.L @(disp,Rm), Rn - Load long with displacement
   *-------------------------------------------------------------*/

  /* Test 2: Load long with disp=0 */
test_2:
    mova movl_disp_data_2, r0
    mov r0, r1        /* r1 = base address */
    mov.l @(0, r1), r2
    mov.l movl_disp_exp_2, r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop
    .align 2
movl_disp_data_2:
    .long 0x12345678
movl_disp_exp_2:
    .long 0x12345678

  /* Test 3: Load long at offset 4 bytes (disp=1) */
test_3:
    mova movl_disp_data_3, r0
    mov r0, r1
    mov.l @(4, r1), r2   /* offset 4 bytes = disp 1 */
    mov.l movl_disp_exp_3, r3
    cmp/eq r2, r3
    bf fail
    bra test_4
    nop
    .align 2
movl_disp_data_3:
    .long 0x11111111  /* offset 0 */
    .long 0x22222222  /* offset 4 - this is what we load */
    .long 0x33333333  /* offset 8 */
movl_disp_exp_3:
    .long 0x22222222

  /* Test 4: Load long at offset 8 bytes (disp=2) */
test_4:
    mova movl_disp_data_4, r0
    mov r0, r1
    mov.l @(8, r1), r2   /* offset 8 bytes = disp 2 */
    mov.l movl_disp_exp_4, r3
    cmp/eq r2, r3
    bf fail
    bra test_5
    nop
    .align 2
movl_disp_data_4:
    .long 0xAAAAAAAA  /* offset 0 */
    .long 0xBBBBBBBB  /* offset 4 */
    .long 0xCCCCCCCC  /* offset 8 - this is what we load */
movl_disp_exp_4:
    .long 0xCCCCCCCC

  /* Test 5: Load with different register */
test_5:
    mova movl_disp_data_5, r0
    mov r0, r4        /* use r4 as base */
    mov.l @(4, r4), r5  /* load into r5 */
    mov.l movl_disp_exp_5, r3
    cmp/eq r5, r3
    bf fail
    bra test_end
    nop
    .align 2
movl_disp_data_5:
    .long 0xDEADBEEF  /* offset 0 */
    .long 0xCAFEBABE  /* offset 4 */
movl_disp_exp_5:
    .long 0xCAFEBABE

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
