/* j2 (SuperH-2) Full Exception Handling Tests */
/* Tests complete exception flow: trigger -> handler -> verify */

#include "test_macros.h"

/* SH-2 Exception mechanics:
 * - Exception pushes SR and PC to stack (R15)
 * - Sets SR.MD=1, SR.BL=1
 * - Reads handler ADDRESS from VBR + vector*4
 * - Jumps to that handler address
 *
 * Memory layout:
 *   0x000:       Entry point (jump to main_code)
 *   0x100-0x1FF: Vector table (VBR=0x100)
 *   0x200-0x2FF: Exception handlers
 *   0x300+:      Main test code
 *   0x2000:      Stack area
 */

  .text
  .globl _start

  /*-------------------------------------------------------------
   * Entry point at address 0 - jump to main test code
   *-------------------------------------------------------------*/
_start:
  bra main_code
  nop

  /*-------------------------------------------------------------
   * Vector Table at 0x100 (VBR will be set to 0x100)
   * Each entry is a 32-bit pointer to the handler
   *-------------------------------------------------------------*/
  .org 0x100
vector_table:
  .long 0               /* Vector 0: Power-on reset PC (unused) */
  .long 0               /* Vector 1: Power-on reset SP (unused) */
  .long 0               /* Vector 2: Manual reset PC */
  .long 0               /* Vector 3: Manual reset SP */
  .long handler_illegal /* Vector 4: Illegal instruction */
  .long 0               /* Vector 5: Reserved */
  .long 0               /* Vector 6: Slot illegal */
  .long handler_addr_read  /* Vector 7: Address error (read) */
  .long handler_addr_read  /* Vector 8: Address error (write) */
  .long 0               /* Vector 9-31: Reserved */
  .long 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
  .long 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
  .long 0, 0
  .long handler_trap0   /* Vector 32: TRAPA #0 */
  .long handler_trap1   /* Vector 33: TRAPA #1 */
  .long handler_trap2   /* Vector 34: TRAPA #2 */

  /*-------------------------------------------------------------
   * Exception Handlers (at 0x200)
   *-------------------------------------------------------------*/
  .org 0x200

handler_illegal:
  /* Illegal instruction - skip it */
  mov.l @r15, r0
  add #2, r0
  mov.l r0, @r15
  rte
  nop

  .align 2
handler_addr_read:
  mov #0x77, r10       /* Mark handler called */
  /* Skip offending instruction */
  mov.l @r15, r0
  add #2, r0
  mov.l r0, @r15
  rte
  nop

  .align 2
handler_trap0:
  mov #0x42, r8        /* Mark handler 0 called */
  /* Skip TRAPA instruction */
  mov.l @r15, r0
  add #2, r0
  mov.l r0, @r15
  rte
  nop

  .align 2
handler_trap1:
  mov #0x43, r9        /* Mark handler 1 called */
  mov.l @r15, r0
  add #2, r0
  mov.l r0, @r15
  rte
  nop

  .align 2
handler_trap2:
  /* Don't modify T - just skip instruction */
  mov.l @r15, r0
  add #2, r0
  mov.l r0, @r15
  rte
  nop

  /*-------------------------------------------------------------
   * Main Test Code (at 0x300)
   *-------------------------------------------------------------*/
  .org 0x300
main_code:
  /* Set VBR to 0x100 (where vector table is) */
  mov.l vbr_value, r0
  ldc r0, vbr

  /* Set up stack pointer to 0x2000 (grows down) */
  mov.l stack_addr, r15

  /* Initialize test result registers */
  mov #0, r8     /* handler 0 flag */
  mov #0, r9     /* handler 1 flag */
  mov #0, r10    /* addr error flag */

  /*-------------------------------------------------------------
   * Test 1: TRAPA #0 - basic exception
   *-------------------------------------------------------------*/
test_1:
  mov #1, r1
  trapa #0

  /* Verify handler set r8 = 0x42 */
  mov #0x42, r0
  cmp/eq r0, r8
  bf fail_jmp
  nop

  /*-------------------------------------------------------------
   * Test 2: TRAPA #1 - different vector
   *-------------------------------------------------------------*/
test_2:
  mov #2, r1
  trapa #1

  /* Verify handler set r9 = 0x43 */
  mov #0x43, r0
  cmp/eq r0, r9
  bf fail_jmp
  nop

  /*-------------------------------------------------------------
   * Test 3: Stack restored after exception
   *-------------------------------------------------------------*/
test_3:
  mov #3, r1
  mov.l stack_addr, r0
  cmp/eq r0, r15
  bf fail_jmp
  nop

  /*-------------------------------------------------------------
   * Test 4: T flag preserved across exception
   *-------------------------------------------------------------*/
test_4:
  mov #4, r1
  sett              /* Set T flag */
  trapa #2          /* Handler won't modify T */
  bt pass           /* T should still be set */
  nop

fail_jmp:
  bra fail
  nop

  .align 2
vbr_value:
  .long 0x00000100
stack_addr:
  .long 0x00002000

pass:
  bra pass
  nop

fail:
  bra fail
  nop

  .data
  .align 2
