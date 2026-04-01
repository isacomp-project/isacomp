/* j2 (SuperH-2) MOV.L Rm,@(disp,Rn) instruction tests */
/* Stores long word from Rm into (Rn+disp*4) */
/* Note: disp is scaled by 4 for long word access */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MOV.L Rm, @(disp,Rn) - Store long with displacement
   *-------------------------------------------------------------*/

  /* Test 2: Store long with disp=0 */
test_2:
    mova movl_st_buf_2, r0
    mov r0, r1        /* r1 = base address */
    mov.l movl_st_val_2, r2
    mov.l r2, @(0, r1)
    /* Read back to verify */
    mov.l @(0, r1), r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop
    .align 2
movl_st_val_2:
    .long 0x12345678
movl_st_buf_2:
    .long 0

  /* Test 3: Store long at offset 4 bytes (disp=1) */
test_3:
    mova movl_st_buf_3, r0
    mov r0, r1
    mov.l movl_st_val_3, r2
    mov.l r2, @(4, r1)   /* offset 4 bytes = disp 1 */
    /* Read back to verify */
    mov.l @(4, r1), r3
    cmp/eq r2, r3
    bf fail
    bra test_4
    nop
    .align 2
movl_st_val_3:
    .long 0xABCDEF00
movl_st_buf_3:
    .long 0
    .long 0   /* this location gets written */
    .long 0

  /* Test 4: Store long at offset 8 bytes (disp=2) */
test_4:
    mova movl_st_buf_4, r0
    mov r0, r1
    mov.l movl_st_val_4, r2
    mov.l r2, @(8, r1)   /* offset 8 bytes = disp 2 */
    /* Read back to verify */
    mov.l @(8, r1), r3
    cmp/eq r2, r3
    bf fail
    bra test_5
    nop
    .align 2
movl_st_val_4:
    .long 0xDEADBEEF
movl_st_buf_4:
    .long 0   /* offset 0 */
    .long 0   /* offset 4 */
    .long 0   /* offset 8 - gets written */

  /* Test 5: Store from different registers */
test_5:
    mova movl_st_buf_5, r0
    mov r0, r4        /* use r4 as base */
    mov.l movl_st_val_5, r5  /* r5 has value to store */
    mov.l r5, @(4, r4)
    /* Read back to verify */
    mov.l @(4, r4), r3
    cmp/eq r5, r3
    bf fail
    bra test_end
    nop
    .align 2
movl_st_val_5:
    .long 0xCAFEBABE
movl_st_buf_5:
    .long 0
    .long 0   /* this location gets written */

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
