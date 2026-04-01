/* j2 (SuperH-2) ADDV instruction tests */
/* ADDV adds with overflow detection, sets T=1 if overflow */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * ADDV - Add with overflow flag
   *-------------------------------------------------------------*/

  /* Test 2: No overflow: 1 + 2 = 3, T=0 */
  TEST_CASE( 2, r3, 0x00000003, \
    mov #1, r1; \
    mov #2, r2; \
    addv r2, r1; \
    mov r1, r3; \
  )

  /* Test 3: Check T=0 after no overflow */
test_3:
    mov #10, r1
    mov #20, r2
    addv r2, r1
    bt fail           /* T should be 0 (no overflow) */
    bra test_4
    nop

  /* Test 4: Positive overflow: 0x7FFFFFFF + 1 = 0x80000000, T=1 */
test_4:
    mov.l test_4_val, r1
    mov #1, r2
    addv r2, r1
    bf fail           /* T should be 1 (overflow) */
    bra test_5
    nop
    .align 2
test_4_val:
    .long 0x7fffffff

  /* Test 5: Negative overflow: 0x80000000 + (-1) = 0x7FFFFFFF, T=1 */
test_5:
    mov.l test_5_val, r1
    mov #-1, r2
    addv r2, r1
    bf fail           /* T should be 1 (overflow) */
    bra test_6
    nop
    .align 2
test_5_val:
    .long 0x80000000

  /* Test 6: Large values no overflow: 0x40000000 + 0x3FFFFFFF = 0x7FFFFFFF */
test_6:
    mov.l test_6_val1, r1
    mov.l test_6_val2, r2
    addv r2, r1
    bt fail           /* T should be 0 (no overflow) */
    mov.l test_6_expected, r3
    cmp/eq r1, r3
    bf fail
    bra test_end
    nop
    .align 2
test_6_val1:
    .long 0x40000000
test_6_val2:
    .long 0x3fffffff
test_6_expected:
    .long 0x7fffffff

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
