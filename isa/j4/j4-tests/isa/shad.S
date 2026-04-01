/* j2 (J2-specific) SHAD instruction tests */
/* SHAD Rm,Rn - Shift Arithmetic Dynamic */
/* If Rm >= 0: shift Rn left by Rm[4:0] */
/* If Rm < 0: shift Rn right arithmetic by (0 - Rm[4:0]) */
/* Note: SHAD is a J2/SH3 extension, must use manual encoding */
/* Encoding: 0100nnnnmmmm1100 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * SHAD - Shift Arithmetic Dynamic
   *-------------------------------------------------------------*/

  /* Test 2: Left shift by 1 */
  /* SHAD r2, r1 = 0x412C */
test_2:
    mov #4, r1         /* value to shift */
    mov #1, r2         /* shift amount */
    .word 0x412C       /* SHAD r2, r1: r1 = 4 << 1 = 8 */
    mov #8, r3
    cmp/eq r1, r3
    bf fail
    bra test_3
    nop

  /* Test 3: Left shift by 4 */
  /* SHAD r2, r1 = 0x412C */
test_3:
    mov #1, r1
    mov #4, r2
    .word 0x412C       /* SHAD r2, r1: r1 = 1 << 4 = 16 */
    mov #16, r3
    cmp/eq r1, r3
    bf fail
    bra test_4
    nop

  /* Test 4: Right arithmetic shift by 1 (Rm=-1) - positive value */
  /* SHAD r2, r1 = 0x412C */
test_4:
    mov #4, r1
    mov #-1, r2        /* shift right by 1 */
    .word 0x412C       /* SHAD r2, r1: r1 = 4 >> 1 = 2 */
    mov #2, r3
    cmp/eq r1, r3
    bf fail
    bra test_5
    nop

  /* Test 5: Right arithmetic shift preserves sign (0x80000000 >> 1 = 0xC0000000) */
  /* SHAD r2, r1 = 0x412C */
test_5:
    mov.l shad_val_5, r1   /* 0x80000000 */
    mov #-1, r2            /* shift right by 1 */
    .word 0x412C       /* SHAD r2, r1 */
    mov.l shad_exp_5, r3   /* 0xC0000000 (sign extended) */
    cmp/eq r1, r3
    bf fail
    bra test_6
    nop
    .align 2
shad_val_5:
    .long 0x80000000
shad_exp_5:
    .long 0xc0000000

  /* Test 6: Right arithmetic shift by 4 on negative */
  /* SHAD r2, r1 = 0x412C */
test_6:
    mov.l shad_val_6, r1   /* 0xFFFFFFF0 (-16) */
    mov #-4, r2            /* shift right by 4 */
    .word 0x412C       /* SHAD r2, r1 */
    mov #-1, r3            /* 0xFFFFFFFF (sign extended) */
    cmp/eq r1, r3
    bf fail
    bra test_7
    nop
    .align 2
shad_val_6:
    .long 0xfffffff0

  /* Test 7: Shift by 0 (no change) */
  /* SHAD r2, r1 = 0x412C */
test_7:
    mov.l shad_val_7, r1
    mov #0, r2
    .word 0x412C       /* SHAD r2, r1 */
    mov.l shad_val_7, r3
    cmp/eq r1, r3
    bf fail
    bra test_8
    nop
    .align 2
shad_val_7:
    .long 0x12345678

  /* Test 8: Left shift by 31 */
  /* SHAD r2, r1 = 0x412C */
test_8:
    mov #1, r1
    mov #31, r2
    .word 0x412C       /* SHAD r2, r1 */
    mov.l shad_exp_8, r3
    cmp/eq r1, r3
    bf fail
    bra test_end
    nop
    .align 2
shad_exp_8:
    .long 0x80000000

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
