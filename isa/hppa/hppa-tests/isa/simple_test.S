/* Simple HPPA test to verify assembly works */

    .text
    .align 4
    .globl _start
_start:
    /* Initialize test number register */
    ldo 0(%r0), %r28

    /* Test 1: Simple add */
    ldo 5(%r0), %r2
    ldo 3(%r0), %r3
    add %r2, %r3, %r1
    /* r1 should now be 8 */

    ldo 8(%r0), %r29
    cmpb,= %r1, %r29, pass
    nop

    b fail
    nop

pass:
    b pass
    nop

fail:
    b fail
    nop
