/* j2 (SuperH-2) MOV.L load instruction tests */
/* MOV.L @Rm, Rn loads 32-bit value from memory */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Load long tests
   *-------------------------------------------------------------*/

  /* Test 2: Basic mov.l load */
test_2:
    mova movl_data_2, r0
    mov.l @r0, r2
    mov.l movl_expect_2, r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop
    .align 2
movl_data_2:
    .long 0x12345678
movl_expect_2:
    .long 0x12345678

  /* Test 3: Load zero */
test_3:
    mova movl_data_3, r0
    mov.l @r0, r2
    mov #0, r3
    cmp/eq r2, r3
    bf fail
    bra test_4
    nop
    .align 2
movl_data_3:
    .long 0x00000000

  /* Test 4: Load -1 */
test_4:
    mova movl_data_4, r0
    mov.l @r0, r2
    mov #-1, r3
    cmp/eq r2, r3
    bf fail
    bra test_5
    nop
    .align 2
movl_data_4:
    .long 0xffffffff

  /* Test 5: Load from array second element */
test_5:
    mova movl_data_5, r0
    add #4, r0
    mov.l @r0, r3
    mov.l movl_expect_5, r4
    cmp/eq r3, r4
    bf fail
    bra test_6
    nop
    .align 2
movl_data_5:
    .long 0x11111111
    .long 0xabcdef00
movl_expect_5:
    .long 0xabcdef00

  /* Test 6: Load with different register */
test_6:
    mova movl_data_6, r0
    mov r0, r4
    mov.l @r4, r5
    mov.l movl_expect_6, r6
    cmp/eq r5, r6
    bf fail
    bra test_end
    nop
    .align 2
movl_data_6:
    .long 0x5a5a5a5a
movl_expect_6:
    .long 0x5a5a5a5a

test_end:
    TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
