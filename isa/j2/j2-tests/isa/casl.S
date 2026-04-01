/* j2 (J2-specific) CAS.L instruction tests */
/* CAS.L Rm,Rn,@R0 - Compare and Swap */
/* If @R0 == Rn, then @R0 = Rm and T = 1 */
/* Else Rn = @R0 and T = 0 */
/* Note: CAS.L is J2-specific, must use manual encoding */
/* Encoding: 0010nnnnmmmm0011 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * CAS.L - Compare and Swap (atomic)
   *-------------------------------------------------------------*/

  /* Test 2: Successful swap (memory matches Rn) */
  /* CAS.L r2, r1, @r0 = 0x2123 */
test_2:
    /* Set up memory with value 0x12345678 */
    mova casl_data_2, r0
    mov r0, r4            /* save address */
    /* Load expected value into Rn */
    mov.l casl_exp_2, r1  /* Rn = 0x12345678 (expected value) */
    /* Load new value into Rm */
    mov.l casl_new_2, r2  /* Rm = 0xDEADBEEF (new value) */
    /* Point R0 to memory */
    mov r4, r0
    /* Execute CAS.L r2, r1, @r0 */
    .word 0x2123
    /* T should be 1 (swap succeeded) */
    bf fail
    /* Memory should now be 0xDEADBEEF */
    mov r4, r0
    mov.l @r0, r3
    mov.l casl_new_2, r5
    cmp/eq r3, r5
    bf fail
    bra test_3
    nop
    .align 2
casl_data_2:
    .long 0x12345678
casl_exp_2:
    .long 0x12345678
casl_new_2:
    .long 0xdeadbeef

  /* Test 3: Failed swap (memory doesn't match Rn) */
  /* CAS.L r2, r1, @r0 = 0x2123 */
test_3:
    /* Set up memory with value 0xAAAAAAAA */
    mova casl_data_3, r0
    mov r0, r4            /* save address */
    /* Load wrong expected value into Rn */
    mov.l casl_wrong_3, r1  /* Rn = 0xBBBBBBBB (wrong) */
    /* Load new value into Rm */
    mov.l casl_new_3, r2  /* Rm = 0xCCCCCCCC */
    /* Point R0 to memory */
    mov r4, r0
    /* Execute CAS.L r2, r1, @r0 */
    .word 0x2123
    /* T should be 0 (swap failed) */
    bt fail
    /* Memory should still be 0xAAAAAAAA */
    mov r4, r0
    mov.l @r0, r3
    mov.l casl_orig_3, r5
    cmp/eq r3, r5
    bf fail
    /* Rn should now contain 0xAAAAAAAA (actual memory value) */
    mov.l casl_orig_3, r5
    cmp/eq r1, r5
    bf fail
    bra test_4
    nop
    .align 2
casl_data_3:
    .long 0xaaaaaaaa
casl_wrong_3:
    .long 0xbbbbbbbb
casl_new_3:
    .long 0xcccccccc
casl_orig_3:
    .long 0xaaaaaaaa

  /* Test 4: Swap with zero */
  /* CAS.L r2, r1, @r0 = 0x2123 */
test_4:
    mova casl_data_4, r0
    mov r0, r4
    mov #0, r1            /* Rn = 0 (expected) */
    mov #42, r2           /* Rm = 42 (new value) */
    mov r4, r0
    .word 0x2123          /* CAS.L r2, r1, @r0 */
    bf fail               /* T should be 1 */
    /* Check memory is now 42 */
    mov r4, r0
    mov.l @r0, r3
    mov #42, r5
    cmp/eq r3, r5
    bf fail
    bra test_end
    nop
    .align 2
casl_data_4:
    .long 0

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
