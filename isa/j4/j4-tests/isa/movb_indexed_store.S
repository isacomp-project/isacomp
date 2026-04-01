/* j2 (SuperH-2) MOV.B Rm,@(R0,Rn) instruction tests */
/* Stores low byte of Rm to address (R0+Rn) */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MOV.B Rm, @(R0,Rn) - Store byte indexed
   *-------------------------------------------------------------*/

  /* Test 2: Store byte with R0=0 */
test_2:
    mova movb_idx_st_area_2, r0
    mov r0, r1        /* r1 = base address */
    mov #0, r0        /* r0 = 0 offset */
    mov #0x42, r2     /* value to store */
    mov.b r2, @(r0, r1)
    /* Read back */
    mov.b @r1, r3
    mov #0x42, r4
    cmp/eq r3, r4
    bf fail
    bra test_3
    nop
    .align 2
movb_idx_st_area_2:
    .long 0

  /* Test 3: Store byte with offset */
test_3:
    mova movb_idx_st_area_3, r0
    mov r0, r1        /* r1 = base address */
    mov #1, r0        /* r0 = 1 offset */
    mov #0x55, r2
    mov.b r2, @(r0, r1)
    /* Read back from offset 1 */
    add #1, r1
    mov.b @r1, r3
    mov #0x55, r4
    cmp/eq r3, r4
    bf fail
    bra test_4
    nop
    .align 2
movb_idx_st_area_3:
    .long 0

  /* Test 4: Only low byte is stored */
test_4:
    mova movb_idx_st_area_4, r0
    mov r0, r1
    mov #0, r0
    mov.l movb_idx_st_val_4, r2  /* 0x12345678 */
    mov.b r2, @(r0, r1)
    /* Should only store 0x78 */
    mov.b @r1, r3
    mov #0x78, r4
    cmp/eq r3, r4
    bf fail
    bra test_end
    nop
    .align 2
movb_idx_st_area_4:
    .long 0
movb_idx_st_val_4:
    .long 0x12345678

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
