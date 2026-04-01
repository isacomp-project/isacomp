/* j2 (SuperH-2) MOV.L PC-relative load instruction tests */
/* MOV.L @(disp, PC), Rn loads from PC-relative address */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Load long PC-relative tests
   *-------------------------------------------------------------*/

  /* Test 2: Basic PC-relative load */
test_2:
    mov.l movlpc_data_2, r2
    mov.l movlpc_expect_2, r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop
    .align 2
movlpc_data_2:
    .long 0x12345678
movlpc_expect_2:
    .long 0x12345678

  /* Test 3: PC-relative load zero */
test_3:
    mov.l movlpc_data_3, r2
    mov #0, r3
    cmp/eq r2, r3
    bf fail
    bra test_4
    nop
    .align 2
movlpc_data_3:
    .long 0x00000000

  /* Test 4: PC-relative load -1 */
test_4:
    mov.l movlpc_data_4, r2
    mov #-1, r3
    cmp/eq r2, r3
    bf fail
    bra test_5
    nop
    .align 2
movlpc_data_4:
    .long 0xffffffff

  /* Test 5: Multiple PC-relative loads */
test_5:
    mov.l movlpc_data_5a, r3
    mov.l movlpc_data_5b, r4
    mov.l movlpc_expect_5, r5
    cmp/eq r4, r5
    bf fail
    bra test_6
    nop
    .align 2
movlpc_data_5a:
    .long 0xabcdef00
movlpc_data_5b:
    .long 0x5a5a5a5a
movlpc_expect_5:
    .long 0x5a5a5a5a

  /* Test 6: Another PC-relative pattern */
test_6:
    mov.l movlpc_data_6, r2
    mov.l movlpc_expect_6, r3
    cmp/eq r2, r3
    bf fail
    bra test_end
    nop
    .align 2
movlpc_data_6:
    .long 0x77777777
movlpc_expect_6:
    .long 0x77777777

test_end:
    TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
