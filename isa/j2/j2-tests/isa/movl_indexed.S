/* j2 (SuperH-2) MOV.L indexed load instruction tests */
/* MOV.L @(R0, Rm), Rn loads from memory at Rm + R0 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Load long indexed tests
   *-------------------------------------------------------------*/

  /* Test 2: Indexed load with offset 0 */
test_2:
    mova movli_data_2, r0
    mov r0, r1
    mov #0, r0
    mov.l @(r0, r1), r3
    mov.l movli_expect_2, r4
    cmp/eq r3, r4
    bf fail
    bra test_3
    nop
    .align 2
movli_data_2:
    .long 0x12345678
movli_expect_2:
    .long 0x12345678

  /* Test 3: Indexed load with offset 4 */
test_3:
    mova movli_data_3, r0
    mov r0, r1
    mov #4, r0
    mov.l @(r0, r1), r3
    mov.l movli_expect_3, r4
    cmp/eq r3, r4
    bf fail
    bra test_4
    nop
    .align 2
movli_data_3:
    .long 0x11111111
    .long 0xabcdef00
movli_expect_3:
    .long 0xabcdef00

  /* Test 4: Indexed load with offset 8 */
test_4:
    mova movli_data_4, r0
    mov r0, r1
    mov #8, r0
    mov.l @(r0, r1), r3
    mov.l movli_expect_4, r4
    cmp/eq r3, r4
    bf fail
    bra test_5
    nop
    .align 2
movli_data_4:
    .long 0x11111111
    .long 0x22222222
    .long 0x55555555
movli_expect_4:
    .long 0x55555555

  /* Test 5: Indexed array access offset 12 */
test_5:
    mova movli_data_5, r0
    mov r0, r1
    mov #12, r0
    mov.l @(r0, r1), r4
    mov.l movli_expect_5, r5
    cmp/eq r4, r5
    bf fail
    bra test_end
    nop
    .align 2
movli_data_5:
    .long 0x11111111
    .long 0x22222222
    .long 0x33333333
    .long 0x44444444
movli_expect_5:
    .long 0x44444444

test_end:
    TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
