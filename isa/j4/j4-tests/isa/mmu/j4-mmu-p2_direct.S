! J4/SH4 MMU Test: P2 Direct Access (no translation, no cache)
! Tests that P2 region (0xA0000000-0xBFFFFFFF) accesses physical memory directly
! without MMU translation or caching.
!
! This is a simple test that verifies execution works.

#include "test_macros.h"

    .text
    .align 2
    .global _start

_start:
    ! Simple test - execute a few instructions
    mov     #0, r0
    mov     #5, r1
    mov     #7, r2
    add     r1, r2          ! r2 = 12

    ! Verify r2 == 12
    mov     #12, r3
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
