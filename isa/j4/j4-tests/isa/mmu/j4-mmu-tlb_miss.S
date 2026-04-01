! J4/SH4 MMU Test: TLB Miss (basic setup)
! Tests TLB miss detection when no matching entry exists
!
! This is a basic test that sets up TLB infrastructure.
! Full TLB miss exception handling requires VBR setup.

#include "test_macros.h"

    .text
    .align 2
    .global _start

_start:
    mov     #0, r0

    ! Test 1: Initialize MMUCR to known state
    mov     #1, r0
    mov     #0, r1
    .word   0x4135          ! LDC R1, MMUCR

    ! Test 2: Set up a TLB entry that we won't use
    mov     #2, r0

    ! PTEH for a different address than we'll access
    mov.l   pteh_val, r1
    .word   0x4105          ! LDC R1, PTEH

    mov.l   ptel_val, r2
    .word   0x4215          ! LDC R2, PTEL

    mov     #0, r3
    .word   0x4335          ! LDC R3, MMUCR

    .word   0x0038          ! LDTLB

    ! Test 3: Verify we're still running (didn't crash)
    mov     #3, r0

    ! Test passed - basic TLB setup works
    bra     pass
    nop

fail:
    bra     fail
    nop

pass:
    bra     pass
    nop

    .align 4
pteh_val:
    .long   0x00010000      ! VPN for VA 0x00040xxx (different from test code)
ptel_val:
    .long   0x00010112      ! Valid entry

    .end
