/* j4 (SuperH-4) MOV instruction tests */

#include "test_macros.h"

J4TEST_CODE_BEGIN

  /* Basic MOV Rm,Rn tests */
test_2:
    mov.l test_2_src, r1
    mov r1, r2
    mov.l test_2_data, r3
    cmp/eq r2, r3
    bt test_2_pass
    nop
    bra fail
    nop
test_2_pass:
    bra test_3
    nop
    .align 2
test_2_src:
    .long 0x12345678
test_2_data:
    .long 0x12345678

test_3:
    mov.l test_3_src, r4
    mov r4, r5
    mov.l test_3_data, r6
    cmp/eq r5, r6
    bt test_3_pass
    nop
    bra fail
    nop
test_3_pass:
    bra test_4
    nop
    .align 2
test_3_src:
    .long 0xDEADBEEF
test_3_data:
    .long 0xDEADBEEF

test_4:
    mov.l test_4_src, r7
    mov r7, r8
    mov.l test_4_data, r9
    cmp/eq r8, r9
    bt test_4_pass
    nop
    bra fail
    nop
test_4_pass:
    bra pass
    nop
    .align 2
test_4_src:
    .long 0x00000000
test_4_data:
    .long 0x00000000

  TEST_PASSFAIL

J4TEST_CODE_END

J4TEST_PASS
J4TEST_FAIL

J4TEST_DATA_BEGIN
  TEST_DATA
J4TEST_DATA_END
