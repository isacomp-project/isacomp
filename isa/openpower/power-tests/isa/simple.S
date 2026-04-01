/* OpenPOWER Simple Test */
/* Basic test to verify infrastructure works */

    .section .text
    .globl _start
    .globl pass
    .globl fail

_start:
    /* Initialize stack pointer */
    lis %r1, 0x1000

    /* Test 1: Simple add */
    li %r3, 5
    li %r4, 7
    add %r5, %r3, %r4       /* r5 = 12 */

    /* Check result */
    li %r6, 12
    cmpw %cr0, %r5, %r6
    bne %cr0, fail

    /* Test 2: addi */
    li %r3, 10
    addi %r4, %r3, 20       /* r4 = 30 */

    li %r6, 30
    cmpw %cr0, %r4, %r6
    bne %cr0, fail

    /* Test 3: Logical OR */
    li %r3, 0x0F
    li %r4, 0xF0
    or %r5, %r3, %r4        /* r5 = 0xFF */

    li %r6, 0xFF
    cmpw %cr0, %r5, %r6
    bne %cr0, fail

    /* Test 4: Logical AND */
    li %r3, 0xFF
    li %r4, 0x0F
    and %r5, %r3, %r4       /* r5 = 0x0F */

    li %r6, 0x0F
    cmpw %cr0, %r5, %r6
    bne %cr0, fail

    /* All tests passed */
    b pass

pass:
    b pass               /* Loop forever on pass */

fail:
    b fail               /* Loop forever on fail */

    .section .data
    .balign 8
