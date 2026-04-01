/* j2 (J2-specific) SHLD instruction tests */
/* SHLD Rm,Rn - Shift Logical Dynamic */
/* If Rm >= 0: shift Rn left by Rm[4:0] */
/* If Rm < 0: shift Rn right logical by (0 - Rm[4:0]) */
/* Note: SHLD is a J2/SH3 extension, must use manual encoding */
/* Encoding: 0100nnnnmmmm1101 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * SHLD - Shift Logical Dynamic
   *-------------------------------------------------------------*/

  /* Test 2: Left shift by 1 */
  /* SHLD r2, r1 = 0x412D */
test_2:
    mov #4, r1         /* value to shift */
    mov #1, r2         /* shift amount */
    .word 0x412D       /* SHLD r2, r1: r1 = 4 << 1 = 8 */
    mov #8, r3
    cmp/eq r1, r3
    bf fail
    bra test_3
    nop

  /* Test 3: Left shift by 4 */
  /* SHLD r2, r1 = 0x412D */
test_3:
    mov #1, r1
    mov #4, r2
    .word 0x412D       /* SHLD r2, r1: r1 = 1 << 4 = 16 */
    mov #16, r3
    cmp/eq r1, r3
    bf fail
    bra test_4
    nop

  /* Test 4: Right logical shift by 1 (Rm=-1) - positive value */
  /* SHLD r2, r1 = 0x412D */
test_4:
    mov #4, r1
    mov #-1, r2        /* shift right by 1 */
    .word 0x412D       /* SHLD r2, r1: r1 = 4 >> 1 = 2 */
    mov #2, r3
    cmp/eq r1, r3
    bf fail
    bra test_5
    nop

  /* Test 5: Right shift fills with zeros (unlike SHAD) - 0x80000000 >> 1 = 0x40000000 */
  /* SHLD r2, r1 = 0x412D */
test_5:
    mov.l shld_val_5, r1   /* 0x80000000 */
    mov #-1, r2            /* shift right by 1 */
    .word 0x412D       /* SHLD r2, r1 */
    mov.l shld_exp_5, r3   /* 0x40000000 (zero filled, not sign extended) */
    cmp/eq r1, r3
    bf fail
    bra test_6
    nop
    .align 2
shld_val_5:
    .long 0x80000000
shld_exp_5:
    .long 0x40000000

  /* Test 6: Right logical shift by 4 */
  /* SHLD r2, r1 = 0x412D */
test_6:
    mov.l shld_val_6, r1   /* 0xFFFFFFF0 */
    mov #-4, r2            /* shift right by 4 */
    .word 0x412D       /* SHLD r2, r1 */
    mov.l shld_exp_6, r3   /* 0x0FFFFFFF (zeros filled in) */
    cmp/eq r1, r3
    bf fail
    bra test_7
    nop
    .align 2
shld_val_6:
    .long 0xfffffff0
shld_exp_6:
    .long 0x0fffffff

  /* Test 7: Shift by 0 (no change) */
  /* SHLD r2, r1 = 0x412D */
test_7:
    mov.l shld_val_7, r1
    mov #0, r2
    .word 0x412D       /* SHLD r2, r1 */
    mov.l shld_val_7, r3
    cmp/eq r1, r3
    bf fail
    bra test_8
    nop
    .align 2
shld_val_7:
    .long 0x12345678

  /* Test 8: Left shift by 31 */
  /* SHLD r2, r1 = 0x412D */
test_8:
    mov #1, r1
    mov #31, r2
    .word 0x412D       /* SHLD r2, r1 */
    mov.l shld_exp_8, r3
    cmp/eq r1, r3
    bf fail
    bra test_end
    nop
    .align 2
shld_exp_8:
    .long 0x80000000

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
