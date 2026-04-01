! J4/SH4 MMU Test: Verify Address Translation Actually Works
!
! This test proves that TLB translation actually changes addresses by:
! 1. Writing 0xDEADBEEF to physical address 0x00002000 (with MMU off)
! 2. Setting up UTLB: VA 0x00003000 -> PA 0x00002000 (non-identity!)
! 3. Enabling MMU (MMUCR.AT=1)
! 4. Reading from VA 0x00003000
! 5. Verifying we get 0xDEADBEEF (proves translation worked)
!
! If translation doesn't work, reading VA 0x3000 would get whatever
! is at PA 0x3000 (not 0xDEADBEEF), and the test would fail.

    .text
    .align 2
    .global _start

_start:
    ! ============================================================
    ! Step 1: Write marker to physical address 0x2000 (MMU off)
    ! ============================================================
    mov.l   phys_addr, r1       ! r1 = 0x00002000
    mov.l   marker_val, r2      ! r2 = 0xDEADBEEF
    mov.l   r2, @r1             ! Store marker at PA 0x2000

    ! Verify the write (sanity check)
    mov.l   @r1, r3
    cmp/eq  r2, r3
    bf      fail

    ! ============================================================
    ! Step 2: Set up TLB entry for VA 0x3000 -> PA 0x2000
    ! This is the KEY non-identity mapping that proves translation
    ! ============================================================

    ! PTEH = 0x00003000 (VPN for VA 0x3xxx, ASID=0)
    ! VPN is bits [31:10] of virtual address
    mov.l   pteh_val, r4
    .word   0x4405              ! LDC R4, PTEH

    ! PTEL = physical page + attributes
    ! PPN[28:10] = 0x00002 (physical page 2 = address 0x2000 for 1KB pages)
    ! Format: PPN | 0 | SZ1 | PR[1:0] | SZ0 | C | D | SH | WT | V
    ! We want: PPN=2, V=1, SZ=00(1KB), PR=10(RW), D=1, SH=1
    ! PTEL = 0x00002116
    mov.l   ptel_val, r5
    .word   0x4515              ! LDC R5, PTEL

    ! MMUCR = URC=12 (0xC), AT=0
    ! URC=12 overwrites the pre-loaded identity mapping for VPN=0xC
    ! MMUCR format: URC is bits [21:18]
    ! URC=12 (0xC) means MMUCR = 0xC << 18 = 0x00300000
    mov.l   mmucr_urc12, r6
    .word   0x4635              ! LDC R6, MMUCR

    ! Load TLB entry using LDTLB (writes to UTLB[URC=12])
    .word   0x0038              ! LDTLB

    ! ============================================================
    ! Step 3: Enable MMU (set MMUCR.AT=1, preserve URC=12)
    ! ============================================================
    mov.l   mmucr_enable, r6    ! URC=12 | AT=1 = 0x00300001
    .word   0x4635              ! LDC R6, MMUCR

    ! ============================================================
    ! Step 4: Read from VA 0x3000 (should translate to PA 0x2000)
    ! ============================================================
    mov.l   virt_addr, r7       ! r7 = 0x00003000 (virtual address)
    mov.l   @r7, r8             ! Read from VA 0x3000
                                ! If translation works: gets PA 0x2000 data
                                ! If translation fails: gets PA 0x3000 data

    ! ============================================================
    ! Step 5: Verify we got the marker (proves translation worked!)
    ! ============================================================
    mov.l   marker_val, r9
    cmp/eq  r8, r9              ! r8 should == 0xDEADBEEF
    bf      fail                ! FAIL if translation didn't work

    ! ============================================================
    ! Step 6: Additional test - write via VA, read via PA
    ! ============================================================
    mov.l   marker2_val, r10    ! r10 = 0xCAFEBABE
    mov.l   r10, @r7            ! Write to VA 0x3000 (-> PA 0x2000)

    ! Disable MMU to read physical memory directly
    mov     #0, r6
    .word   0x4635              ! LDC R6, MMUCR

    ! Read from PA 0x2000 - should have our new marker
    mov.l   @r1, r11
    cmp/eq  r10, r11            ! Should be 0xCAFEBABE
    bf      fail                ! FAIL if write via VA didn't reach PA

    ! ============================================================
    ! All tests passed!
    ! ============================================================
    bra     pass
    nop

fail:
    bra     fail
    nop

pass:
    bra     pass
    nop

    .align 4
phys_addr:
    .long   0x00002000          ! Physical address for test
virt_addr:
    .long   0x00003000          ! Virtual address (maps to PA 0x2000)
marker_val:
    .long   0xDEADBEEF          ! First marker
marker2_val:
    .long   0xCAFEBABE          ! Second marker
pteh_val:
    .long   0x00003000          ! PTEH: VPN=0xC (VA 0x3xxx with 1KB pages)
ptel_val:
    .long   0x00002146          ! PTEL: PPN=8, V=1, SZ=00(1KB), PR=2, D=1, SH=1
                                ! PPN=8 in bits[28:10] -> 8<<10=0x2000
                                ! V=1 in bit[8] -> 0x100
                                ! PR=2 in bits[6:5] -> 0x40
                                ! D=1 in bit[2] -> 0x04
                                ! SH=1 in bit[1] -> 0x02
mmucr_urc12:
    .long   0x00300000          ! MMUCR: URC=12 (0xC << 18), AT=0
mmucr_enable:
    .long   0x00300001          ! MMUCR: URC=12 | AT=1

    .end
