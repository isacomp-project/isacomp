! J4/SH4 MMU Test: Address Translation Verification
!
! This test verifies that TLB translation is actually working by:
! 1. Writing a known value to physical address X
! 2. Setting up TLB to map VA Y -> PA X (where Y != X)
! 3. Enabling the MMU
! 4. Reading from VA Y and verifying we get the value from PA X
!
! Test setup:
! - Write 0xDEADBEEF to PA 0x00002000 (physical, with MMU off)
! - Setup UTLB: VPN 0x00003 -> PPN 0x00002 (VA 0x3000 -> PA 0x2000)
! - Enable MMU (MMUCR.AT=1)
! - Read from VA 0x00003000
! - Should get 0xDEADBEEF if translation is working
!
! Note: Code runs in P1/P2 region (not translated) to avoid complexity
! Only data access is translated.

#include "test_macros.h"

    .text
    .align 2
    .global _start

_start:
    ! First, we run in P2 region (0xA0000000-0xBFFFFFFF) which is not translated
    ! This allows us to set up memory and TLB before enabling MMU

    ! Step 1: Write marker value to physical address 0x2000
    mov.l   pa_addr, r1         ! r1 = 0x00002000 (physical address)
    mov.l   marker_val, r2      ! r2 = 0xDEADBEEF
    mov.l   r2, @r1             ! Write marker to PA 0x2000

    ! Step 2: Verify the write worked (read it back)
    mov.l   @r1, r3             ! Read back from PA
    cmp/eq  r2, r3              ! Compare
    bf      fail                ! Fail if mismatch

    ! Step 3: Set up TLB entry for VA 0x3000 -> PA 0x2000
    ! PTEH format: VPN[31:10] | reserved[9:8] | ASID[7:0]
    ! For VA 0x3000 with 1KB pages: VPN = 0x3000 >> 10 = 0x0C
    ! But we store full VPN including upper bits
    mov.l   pteh_val, r4        ! PTEH = 0x00003000 (VPN for VA 0x3xxx)
    .word   0x4405              ! LDC R4, PTEH

    ! PTEL format: PPN[28:10] | reserved | SZ1 | PR[1:0] | SZ0 | C | D | SH | WT | V
    ! For PA 0x2000: PPN = 0x00002 (19 bits)
    ! V=1, SZ=00 (1KB), PR=10 (RW), C=0, D=1, SH=1, WT=0
    ! PTEL = (PPN << 10) | 0x116 = 0x00002116
    mov.l   ptel_val, r5        ! PTEL = 0x00002116
    .word   0x4515              ! LDC R5, PTEL

    ! Set MMUCR.URC=0 (use UTLB entry 0)
    mov     #0, r6
    .word   0x4635              ! LDC R6, MMUCR

    ! Load TLB entry
    .word   0x0038              ! LDTLB

    ! Step 4: Enable MMU (set MMUCR.AT=1)
    mov     #1, r6              ! AT=1
    .word   0x4635              ! LDC R6, MMUCR

    ! Step 5: Read from VA 0x3000 (should translate to PA 0x2000)
    mov.l   va_addr, r7         ! r7 = 0x00003000 (virtual address)
    mov.l   @r7, r8             ! Read from VA - should get data from PA 0x2000

    ! Step 6: Verify we got the marker value
    mov.l   marker_val, r9
    cmp/eq  r8, r9              ! r8 should equal 0xDEADBEEF
    bf      fail                ! Fail if translation didn't work

    ! Step 7: Additional verification - write via VA, read via PA
    mov.l   marker2_val, r10    ! r10 = 0xCAFEBABE
    mov.l   r10, @r7            ! Write to VA 0x3000

    ! Disable MMU to read physical memory directly
    mov     #0, r6
    .word   0x4635              ! LDC R6, MMUCR

    ! Read from PA 0x2000
    mov.l   @r1, r11            ! r11 = memory at PA 0x2000
    cmp/eq  r10, r11            ! Should be 0xCAFEBABE
    bf      fail                ! Fail if write via VA didn't reach PA

    ! All tests passed!
    bra     pass
    nop

fail:
    bra     fail
    nop

pass:
    bra     pass
    nop

    .align 4
pa_addr:
    .long   0x00002000          ! Physical address for test data
va_addr:
    .long   0x00003000          ! Virtual address (maps to PA 0x2000)
marker_val:
    .long   0xDEADBEEF          ! Test marker value
marker2_val:
    .long   0xCAFEBABE          ! Second marker value
pteh_val:
    .long   0x00003000          ! PTEH: VPN for VA 0x3000, ASID=0
ptel_val:
    .long   0x00002116          ! PTEL: PPN=0x2, V=1, SZ=0, PR=2, D=1, SH=1

    .end
