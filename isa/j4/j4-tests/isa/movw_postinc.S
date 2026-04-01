/* j2 (SuperH-2) MOV.W @Rm+,Rn instruction tests */
/* Loads word from @Rm into Rn with sign extension, then increments Rm by 2 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MOV.W @Rm+, Rn - Load word with post-increment
   *-------------------------------------------------------------*/

  /* Test 2: Load positive word 0x1234 */
test_2:
    mova movw_postinc_data_2, r0
    mov r0, r1
    mov.w @r1+, r2
    mov.l movw_postinc_exp_2, r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop
    .align 2
movw_postinc_data_2:
    .word 0x1234
    .align 2
movw_postinc_exp_2:
    .long 0x00001234

  /* Test 3: Load negative word 0x8000, sign extends to 0xFFFF8000 */
test_3:
    mova movw_postinc_data_3, r0
    mov r0, r1
    mov.w @r1+, r2
    mov.l movw_postinc_exp_3, r3
    cmp/eq r2, r3
    bf fail
    bra test_4
    nop
    .align 2
movw_postinc_data_3:
    .word 0x8000
    .align 2
movw_postinc_exp_3:
    .long 0xffff8000

  /* Test 4: Check post-increment by 2 */
test_4:
    mova movw_postinc_data_4, r0
    mov r0, r1
    mov r0, r4      /* save original address */
    mov.w @r1+, r2
    /* r1 should be r4 + 2 */
    sub r4, r1
    mov #2, r3
    cmp/eq r1, r3
    bf fail
    bra test_5
    nop
    .align 2
movw_postinc_data_4:
    .word 0x5555
    .align 2

  /* Test 5: Multiple post-increment loads */
test_5:
    mova movw_postinc_data_5, r0
    mov r0, r1
    mov.w @r1+, r2    /* load 0x1111 */
    mov.w @r1+, r3    /* load 0x2222 */
    /* Check values */
    mov.l movw_postinc_exp_5a, r5
    cmp/eq r2, r5
    bf fail
    mov.l movw_postinc_exp_5b, r5
    cmp/eq r3, r5
    bf fail
    bra test_end
    nop
    .align 2
movw_postinc_data_5:
    .word 0x1111, 0x2222
    .align 2
movw_postinc_exp_5a:
    .long 0x00001111
movw_postinc_exp_5b:
    .long 0x00002222

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
