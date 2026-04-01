/* j2 (SuperH-2) MOV.W Rm,@(R0,Rn) instruction tests */
/* Stores low word of Rm to address (R0+Rn) */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MOV.W Rm, @(R0,Rn) - Store word indexed
   *-------------------------------------------------------------*/

  /* Test 2: Store word with R0=0 */
test_2:
    mova movw_idx_st_area_2, r0
    mov r0, r1        /* r1 = base address */
    mov #0, r0        /* r0 = 0 offset */
    mov.l movw_idx_st_val_2, r2
    mov.w r2, @(r0, r1)
    /* Read back */
    mov.w @r1, r3
    mov.l movw_idx_st_val_2, r4
    cmp/eq r3, r4
    bf fail
    bra test_3
    nop
    .align 2
movw_idx_st_area_2:
    .long 0
movw_idx_st_val_2:
    .long 0x1234

  /* Test 3: Store word with offset */
test_3:
    mova movw_idx_st_area_3, r0
    mov r0, r1        /* r1 = base address */
    mov #2, r0        /* r0 = 2 offset */
    mov.l movw_idx_st_val_3, r2
    mov.w r2, @(r0, r1)
    /* Read back from offset 2 */
    add #2, r1
    mov.w @r1, r3
    mov.l movw_idx_st_val_3, r4
    cmp/eq r3, r4
    bf fail
    bra test_4
    nop
    .align 2
movw_idx_st_area_3:
    .long 0
movw_idx_st_val_3:
    .long 0x5678

  /* Test 4: Only low word is stored */
test_4:
    mova movw_idx_st_area_4, r0
    mov r0, r1
    mov #0, r0
    mov.l movw_idx_st_val_4, r2  /* 0x12345678 */
    mov.w r2, @(r0, r1)
    /* Should only store 0x5678 */
    mov.w @r1, r3
    mov.l movw_idx_st_exp_4, r4
    cmp/eq r3, r4
    bf fail
    bra test_end
    nop
    .align 2
movw_idx_st_area_4:
    .long 0
movw_idx_st_val_4:
    .long 0x12345678
movw_idx_st_exp_4:
    .long 0x00005678

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
