/* j2 (SuperH-2) MOV.L post-increment load instruction tests */
/* MOV.L @Rm+, Rn loads from memory and increments Rm by 4 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Load long post-increment tests
   *-------------------------------------------------------------*/

  /* Test 2: Basic post-increment load */
test_2:
    mova movlpi_data_2, r0
    mov.l @r0+, r2
    mov.l movlpi_expect_2, r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop
    .align 2
movlpi_data_2:
    .long 0x12345678
movlpi_expect_2:
    .long 0x12345678

  /* Test 3: Post-increment updates pointer by 4 */
test_3:
    mova movlpi_data_3, r0
    mov r0, r1
    mov.l @r0+, r2
    sub r1, r0
    mov r0, r1
    /* r1 should be 4 */
    mov #4, r3
    cmp/eq r1, r3
    bf fail
    bra test_4
    nop
    .align 2
movlpi_data_3:
    .long 0x11111111

  /* Test 4: Multiple post-increment loads */
test_4:
    mova movlpi_data_4, r0
    mov.l @r0+, r2       /* Load first */
    mov.l @r0+, r3       /* Load second */
    mov.l movlpi_expect_4, r4
    cmp/eq r3, r4
    bf fail
    bra test_5
    nop
    .align 2
movlpi_data_4:
    .long 0x11111111
    .long 0xabcdef00
movlpi_expect_4:
    .long 0xabcdef00

  /* Test 5: Array traversal */
test_5:
    mova movlpi_data_5, r0
    mov.l @r0+, r2
    mov.l @r0+, r3
    mov.l @r0+, r4
    mov.l @r0+, r5
    mov.l movlpi_expect_5, r6
    cmp/eq r5, r6
    bf fail
    bra test_6
    nop
    .align 2
movlpi_data_5:
    .long 0x11111111
    .long 0x22222222
    .long 0x33333333
    .long 0x44444444
movlpi_expect_5:
    .long 0x44444444

  /* Test 6: Final pointer value after 3 loads */
test_6:
    mova movlpi_data_6, r0
    mov r0, r1
    mov.l @r0+, r2
    mov.l @r0+, r2
    mov.l @r0+, r2
    sub r1, r0
    mov r0, r3
    /* r3 should be 12 */
    mov #12, r4
    cmp/eq r3, r4
    bf fail
    bra test_end
    nop
    .align 2
movlpi_data_6:
    .long 0x11111111
    .long 0x22222222
    .long 0x33333333

test_end:
    TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
