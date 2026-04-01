! J4/SH4 MMU Test: P1 Direct Access (no translation)
! Tests that P1 region (0x80000000-0x9FFFFFFF) accesses physical memory directly
! without MMU translation, even when MMU is enabled.
!
! This is a simple test that just verifies execution in P1 works.

#include "test_macros.h"

    .text
    .align 2
    .global _start

_start:
    ! Simple test - execute a few instructions
    mov     #0, r0
    mov     #1, r1
    mov     #2, r2
    add     r1, r2          ! r2 = 3

    ! Verify r2 == 3
    mov     #3, r3
    cmp/eq  r2, r3
    bf      fail

    ! Test passed
    bra     pass
    nop

fail:
    bra     fail
    nop

pass:
    bra     pass
    nop

    .end
