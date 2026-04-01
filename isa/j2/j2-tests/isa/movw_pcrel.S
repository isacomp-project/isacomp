/* j2 (SuperH-2) MOV.W PC-relative load instruction tests */
/* MOV.W @(disp, PC), Rn loads word from PC-relative address */
/* Result is sign-extended from 16-bit to 32-bit */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Load word PC-relative tests with sign extension
   *-------------------------------------------------------------*/

  /* Test 2: Basic PC-relative word load (positive) */
test_2:
    mov.w movwpc_data_2, r2
    mov.l movwpc_expect_2, r3
    cmp/eq r2, r3
    bf fail
    bra test_3
    nop
    .align 2
movwpc_data_2:
    .word 0x1234
    .word 0       /* padding */
movwpc_expect_2:
    .long 0x00001234

  /* Test 3: PC-relative load zero */
test_3:
    mov.w movwpc_data_3, r2
    mov #0, r3
    cmp/eq r2, r3
    bf fail
    bra test_4
    nop
    .align 2
movwpc_data_3:
    .word 0x0000
    .word 0       /* padding */

  /* Test 4: PC-relative load with sign extension (negative) */
test_4:
    mov.w movwpc_data_4, r2
    mov.l movwpc_expect_4, r3
    cmp/eq r2, r3
    bf fail
    bra test_5
    nop
    .align 2
movwpc_data_4:
    .word 0x8000  /* sign bit set */
    .word 0       /* padding */
movwpc_expect_4:
    .long 0xffff8000

  /* Test 5: PC-relative load 0xFFFF (sign extends to -1) */
test_5:
    mov.w movwpc_data_5, r2
    mov #-1, r3
    cmp/eq r2, r3
    bf fail
    bra test_6
    nop
    .align 2
movwpc_data_5:
    .word 0xffff
    .word 0       /* padding */

  /* Test 6: PC-relative load 0x7FFF (max positive, no sign extension) */
test_6:
    mov.w movwpc_data_6, r2
    mov.l movwpc_expect_6, r3
    cmp/eq r2, r3
    bf fail
    bra test_end
    nop
    .align 2
movwpc_data_6:
    .word 0x7fff
    .word 0       /* padding */
movwpc_expect_6:
    .long 0x00007fff

test_end:
    TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
