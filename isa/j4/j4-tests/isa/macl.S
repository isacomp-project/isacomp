/* j2 (SuperH-2) MAC.L instruction tests */
/* MAC.L @Rm+,@Rn+ - Multiply-accumulate long */
/* Multiplies two 32-bit values from memory and adds to MACH:MACL */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * MAC.L - Multiply-accumulate long
   *-------------------------------------------------------------*/

  /* Test 2: Basic MAC.L: 3 * 4 = 12, accumulated to MACL */
test_2:
    /* Clear MAC registers first */
    mov #0, r0
    lds r0, mach
    lds r0, macl
    /* Set up pointers */
    mova macl_data_2a, r0
    mov r0, r1
    mova macl_data_2b, r0
    mov r0, r2
    /* Execute MAC.L */
    mac.l @r2+, @r1+
    /* Check result */
    sts macl, r3
    mov #12, r4
    cmp/eq r3, r4
    bf fail
    bra test_3
    nop
    .align 2
macl_data_2a:
    .long 3
macl_data_2b:
    .long 4

  /* Test 3: MAC.L with accumulation */
test_3:
    /* Set initial MAC value to 100 */
    mov #100, r0
    lds r0, macl
    mov #0, r0
    lds r0, mach
    /* Set up pointers */
    mova macl_data_3a, r0
    mov r0, r1
    mova macl_data_3b, r0
    mov r0, r2
    /* Execute MAC.L: 5 * 6 = 30, 100 + 30 = 130 */
    mac.l @r2+, @r1+
    /* Check result */
    sts macl, r3
    mov.l macl_expected_3, r4
    cmp/eq r3, r4
    bf fail
    bra test_4
    nop
    .align 2
macl_data_3a:
    .long 5
macl_data_3b:
    .long 6
macl_expected_3:
    .long 130

  /* Test 4: Post-increment check */
test_4:
    mova macl_data_4, r0
    mov r0, r1
    mov r0, r5      /* save original */
    mova macl_data_4, r0
    mov r0, r2
    mov r0, r6      /* save original */
    mov #0, r0
    lds r0, macl
    lds r0, mach
    mac.l @r2+, @r1+
    /* Check r1 incremented by 4 */
    sub r5, r1
    mov #4, r4
    cmp/eq r1, r4
    bf fail
    /* Check r2 incremented by 4 */
    sub r6, r2
    cmp/eq r2, r4
    bf fail
    bra test_end
    nop
    .align 2
macl_data_4:
    .long 2

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
