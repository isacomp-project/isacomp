! J4/SH4 MMU Test: LDTLB instruction
! Tests loading a TLB entry from PTEH/PTEL registers
!
! J4 custom MMU instruction encodings:
!   LDC Rm, PTEH:  0x4m05
!   LDC Rm, PTEL:  0x4m15
!   LDC Rm, MMUCR: 0x4m35
!   LDTLB:         0x0038

#include "test_macros.h"

    .text
    .align 2
    .global _start

_start:
    ! R0 = test number
    mov     #0, r0

    ! Test 1: Load a TLB entry
    mov     #1, r0

    ! Set up PTEH = 0x00001000  (VPN = 0x4, ASID = 0)
    mov.l   pteh_val, r1
    .word   0x4105          ! LDC R1, PTEH

    ! Set up PTEL = 0x00001112  (PPN = 4, V=1, SZ=1KB, PR=01, SH=1)
    mov.l   ptel_val, r2
    .word   0x4215          ! LDC R2, PTEL

    ! Set MMUCR.URC = 0 (write to entry 0)
    mov     #0, r3
    .word   0x4335          ! LDC R3, MMUCR

    ! Execute LDTLB
    .word   0x0038          ! LDTLB

    ! Test 2: Load another TLB entry at index 1
    mov     #2, r0

    ! Set up different PTEH (VPN = 0x8, ASID = 0)
    mov.l   pteh_val2, r1
    .word   0x4105          ! LDC R1, PTEH

    ! Set up PTEL (PPN = 0x8)
    mov.l   ptel_val2, r2
    .word   0x4215          ! LDC R2, PTEL

    ! Set MMUCR.URC = 1 (write to entry 1)
    mov.l   mmucr_urc1, r3
    .word   0x4335          ! LDC R3, MMUCR

    ! Execute LDTLB
    .word   0x0038          ! LDTLB

    ! Test passed - jump to pass
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
    .long   0x00001000      ! VPN=0x000004 (VA 0x00001xxx), ASID=0
pteh_val2:
    .long   0x00002000      ! VPN=0x000008 (VA 0x00002xxx), ASID=0
ptel_val:
    .long   0x00001112      ! PPN=4, V=1, SZ=001(1KB), PR=01, SH=1
ptel_val2:
    .long   0x00002112      ! PPN=8, V=1, SZ=001(1KB), PR=01, SH=1
mmucr_urc1:
    .long   0x00040000      ! URC=1 (bits 23:18)

    .end
