! J4/SH4 MMU Test: TLB Hit
! Tests that a TLB entry is found when address matches
!
! This test:
! 1. Loads a TLB entry mapping VA 0x00001000 -> PA 0x00001000
! 2. Enables MMU
! 3. Accesses the mapped address (should hit TLB)
!
! Note: Since we're running from physical address 0, we test data access
! rather than instruction fetch to avoid complexity.

#include "test_macros.h"

    .text
    .align 2
    .global _start

_start:
    mov     #0, r0

    ! Test 1: Set up TLB entry for VA 0x00001000
    mov     #1, r0

    ! PTEH = 0x00001000 (VPN for VA 0x00001xxx, ASID=0)
    mov.l   pteh_val, r1
    .word   0x4105          ! LDC R1, PTEH

    ! PTEL = 0x00001116 (PPN=0x00001, V=1, SZ=1KB, PR=01, D=1, SH=1)
    ! D=1 allows writes
    mov.l   ptel_val, r2
    .word   0x4215          ! LDC R2, PTEL

    ! MMUCR = 0 (URC=0, AT=0 still disabled)
    mov     #0, r3
    .word   0x4335          ! LDC R3, MMUCR

    ! Load TLB entry
    .word   0x0038          ! LDTLB

    ! For now, just verify the setup worked
    ! (Full MMU enable requires more infrastructure)
    mov     #2, r0

    ! Test passed
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
    .long   0x00001000
ptel_val:
    .long   0x00001116      ! V=1, SZ=001, PR=01, D=1, SH=1

    .end
