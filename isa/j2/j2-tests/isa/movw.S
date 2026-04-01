/* j2 (SuperH-2) MOV.W load instruction tests */
/* MOV.W @Rm, Rn loads sign-extended 16-bit value from memory */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Load word tests
   *-------------------------------------------------------------*/

  /* Test 2: Load positive word 0x1234 */
test_2:
    mova movw_data_2, r0
    mov.w @r0, r2
    mov.l movw_expect_2, r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop
    .align 2
movw_data_2:
    .word 0x1234
    .align 2
movw_expect_2:
    .long 0x00001234

  /* Test 3: Load 0x8000 -> sign extends to 0xFFFF8000 */
test_3:
    mova movw_data_3, r0
    mov.w @r0, r2
    mov.l movw_expect_3, r3
    cmp/eq r2, r3
    bf fail
    bra test_4
    nop
    .align 2
movw_data_3:
    .word 0x8000
    .align 2
movw_expect_3:
    .long 0xffff8000

  /* Test 4: Load 0xFFFF -> sign extends to 0xFFFFFFFF */
test_4:
    mova movw_data_4, r0
    mov.w @r0, r2
    mov #-1, r3
    cmp/eq r2, r3
    bf fail
    bra test_5
    nop
    .align 2
movw_data_4:
    .word 0xffff
    .align 2

  /* Test 5: Load zero */
test_5:
    mova movw_data_5, r0
    mov.w @r0, r2
    mov #0, r3
    cmp/eq r2, r3
    bf fail
    bra test_6
    nop
    .align 2
movw_data_5:
    .word 0x0000
    .align 2

  /* Test 6: Load 0x7FFF (max positive word) */
test_6:
    mova movw_data_6, r0
    mov.w @r0, r2
    mov.l movw_expect_6, r3
    cmp/eq r2, r3
    bf fail
    bra test_end
    nop
    .align 2
movw_data_6:
    .word 0x7fff
    .align 2
movw_expect_6:
    .long 0x00007fff

test_end:
    TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
