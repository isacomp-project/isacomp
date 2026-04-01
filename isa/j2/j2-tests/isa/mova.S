/* j2 (SuperH-2) MOVA instruction tests */
/* MOVA @(disp, PC), R0 - loads effective address into R0 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Move effective address tests
   *-------------------------------------------------------------*/

  /* Test 2: Basic mova - load address and access data */
test_2:
    mova mova_data_2, r0
    mov.l @r0, r2
    mov.l expect_2, r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop
    .align 2
mova_data_2:
    .long 0x12345678
expect_2:
    .long 0x12345678

  /* Test 3: MOVA with different value */
test_3:
    mova mova_data_3, r0
    mov.l @r0, r3
    mov.l expect_3, r4
    cmp/eq r3, r4
    bf fail
    bra test_4
    nop
    .align 2
mova_data_3:
    .long 0xabcdef00
expect_3:
    .long 0xabcdef00

  /* Test 4: MOVA increment access */
test_4:
    mova mova_data_4, r0
    mov.l @r0+, r1       /* First value */
    mov.l @r0, r2        /* Second value */
    mov.l expect_4_2, r3
    cmp/eq r2, r3
    bf fail
    bra test_5
    nop
    .align 2
mova_data_4:
    .long 0xaaaaaaaa
    .long 0x55555555
expect_4_2:
    .long 0x55555555

  /* Test 5: MOVA alignment check */
test_5:
    mova mova_data_5, r0
    mov.l @r0, r2
    mov.l expect_5, r3
    cmp/eq r2, r3
    bf fail
    bra test_end
    nop
    .align 2
mova_data_5:
    .long 0x77777777
expect_5:
    .long 0x77777777

test_end:
    TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
