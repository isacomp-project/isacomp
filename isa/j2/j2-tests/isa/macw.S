/* j2 (SuperH-2) MAC.W instruction tests */
/* MAC.W @Rm+,@Rn+ - Multiply-accumulate word */
/* Multiplies two 16-bit values from memory and adds to MACL */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MAC.W - Multiply-accumulate word (16-bit operands)
   *-------------------------------------------------------------*/

  /* Test 2: Basic MAC.W: 3 * 4 = 12 */
test_2:
    /* Clear MAC registers */
    mov #0, r0
    lds r0, macl
    /* Set up pointers */
    mova macw_data_2a, r0
    mov r0, r1
    mova macw_data_2b, r0
    mov r0, r2
    /* Execute MAC.W */
    mac.w @r2+, @r1+
    /* Check result */
    sts macl, r3
    mov #12, r4
    cmp/eq r3, r4
    bf fail
    bra test_3
    nop
    .align 2
macw_data_2a:
    .word 3
    .align 2
macw_data_2b:
    .word 4
    .align 2

  /* Test 3: MAC.W with accumulation */
test_3:
    /* Set initial MACL value to 50 */
    mov #50, r0
    lds r0, macl
    /* Set up pointers */
    mova macw_data_3a, r0
    mov r0, r1
    mova macw_data_3b, r0
    mov r0, r2
    /* Execute MAC.W: 7 * 8 = 56, 50 + 56 = 106 */
    mac.w @r2+, @r1+
    /* Check result */
    sts macl, r3
    mov #106, r4
    cmp/eq r3, r4
    bf fail
    bra test_4
    nop
    .align 2
macw_data_3a:
    .word 7
    .align 2
macw_data_3b:
    .word 8
    .align 2

  /* Test 4: Signed multiply: -3 * 4 = -12 */
test_4:
    mov #0, r0
    lds r0, macl
    mova macw_data_4a, r0
    mov r0, r1
    mova macw_data_4b, r0
    mov r0, r2
    mac.w @r2+, @r1+
    sts macl, r3
    mov #-12, r4
    cmp/eq r3, r4
    bf fail
    bra test_5
    nop
    .align 2
macw_data_4a:
    .word -3
    .align 2
macw_data_4b:
    .word 4
    .align 2

  /* Test 5: Post-increment by 2 (word size) */
test_5:
    mova macw_data_5, r0
    mov r0, r1
    mov r0, r5      /* save original */
    mova macw_data_5, r0
    mov r0, r2
    mov r0, r6      /* save original */
    mov #0, r0
    lds r0, macl
    mac.w @r2+, @r1+
    /* Check r1 incremented by 2 */
    sub r5, r1
    mov #2, r4
    cmp/eq r1, r4
    bf fail
    /* Check r2 incremented by 2 */
    sub r6, r2
    cmp/eq r2, r4
    bf fail
    bra test_end
    nop
    .align 2
macw_data_5:
    .word 10
    .align 2

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
