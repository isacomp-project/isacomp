/* j2 (SuperH-2) MOV.W @(R0,Rm),Rn instruction tests */
/* Loads word from (R0+Rm) into Rn with sign extension */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MOV.W @(R0,Rm), Rn - Load word indexed
   *-------------------------------------------------------------*/

  /* Test 2: Load word with R0=0 */
test_2:
    mova movw_idx_data_2, r0
    mov r0, r1        /* r1 = base address */
    mov #0, r0        /* r0 = 0 offset */
    mov.w @(r0, r1), r2
    mov.l movw_idx_exp_2, r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop
    .align 2
movw_idx_data_2:
    .word 0x1234
    .align 2
movw_idx_exp_2:
    .long 0x00001234

  /* Test 3: Load word with offset */
test_3:
    mova movw_idx_data_3, r0
    mov r0, r1        /* r1 = base address */
    mov #2, r0        /* r0 = 2 offset (second word) */
    mov.w @(r0, r1), r2
    mov.l movw_idx_exp_3, r3
    cmp/eq r2, r3
    bf fail
    bra test_4
    nop
    .align 2
movw_idx_data_3:
    .word 0x1111, 0x2222
    .align 2
movw_idx_exp_3:
    .long 0x00002222

  /* Test 4: Sign extension for negative word */
test_4:
    mova movw_idx_data_4, r0
    mov r0, r1
    mov #0, r0
    mov.w @(r0, r1), r2
    mov.l movw_idx_exp_4, r3
    cmp/eq r2, r3
    bf fail
    bra test_5
    nop
    .align 2
movw_idx_data_4:
    .word 0x8000
    .align 2
movw_idx_exp_4:
    .long 0xffff8000

  /* Test 5: Load 0xFFFF -> -1 */
test_5:
    mova movw_idx_data_5, r0
    mov r0, r1
    mov #0, r0
    mov.w @(r0, r1), r2
    mov #-1, r3
    cmp/eq r2, r3
    bf fail
    bra test_end
    nop
    .align 2
movw_idx_data_5:
    .word 0xffff
    .align 2

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
