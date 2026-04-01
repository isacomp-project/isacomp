! SPARCv8 MMU Context Test
! Tests that TLB entries only match when context matches
!
! Test plan:
! 1. Set context to 5, write TLB entry
! 2. Enable MMU, verify access works with context 5
! 3. Change context to 6, access same VA
! 4. Should trap (TLB entry context doesn't match)

.text
.align 4
.globl _start

_start:
    mov 1, %l0

    ! =========================================================
    ! Test 1: Set up TBR
    ! =========================================================
    sethi %hi(0x00001000), %l1
    or %l1, %lo(0x00001000), %l1
    mov %l1, %tbr
    nop

    ! =========================================================
    ! Test 2: Set context to 5
    ! =========================================================
    mov 2, %l0

    sethi %hi(0x200), %l2
    or %l2, %lo(0x200), %l2
    mov 5, %l3
    sta %l3, [%l2] 0x04
    nop

    ! =========================================================
    ! Test 3: Write TLB entry (will be tagged with context 5)
    ! Map VA 0x60000 -> PA 0x70000
    ! =========================================================
    mov 3, %l0

    ! TLB address: VPN = 0x00060, index = 2
    sethi %hi(0x00060080), %l4
    or %l4, %lo(0x00060080), %l4

    ! PTE: PPN = 0x70 (PA 0x70000 >> 12), ACC = 111 (all), ET = 10
    ! PTE = (0x70 << 8) | 0xFE = 0x70FE
    sethi %hi(0x000070FE), %l5
    or %l5, %lo(0x000070FE), %l5

    sta %l5, [%l4] 0x05
    nop

    ! =========================================================
    ! Test 4: Enable MMU
    ! =========================================================
    mov 4, %l0

    mov 1, %l6
    sta %l6, [%g0] 0x04
    nop

    ! =========================================================
    ! Test 5: Access with correct context (5) - should work
    ! =========================================================
    mov 5, %l0

    sethi %hi(0x00060000), %l7
    or %l7, %lo(0x00060000), %l7

    ! Store magic value
    sethi %hi(0xCAFEBABE), %o0
    or %o0, %lo(0xCAFEBABE), %o0
    st %o0, [%l7]
    nop

    ! Load it back
    ld [%l7], %o1
    nop

    ! Verify
    cmp %o0, %o1
    bne fail
    nop

    ! =========================================================
    ! Test 6: Change context to 6
    ! =========================================================
    mov 6, %l0

    mov 6, %o2
    sta %o2, [%l2] 0x04
    nop

    ! =========================================================
    ! Test 7: Access same VA with wrong context - should trap
    ! The TLB entry has context 5, but we're now context 6
    ! =========================================================
    mov 7, %l0

    mov 0x44, %g1 ! Magic marker

    ! This should trap (context mismatch = TLB miss)
    ld [%l7], %o3
    nop

    ! If we get here, trap didn't happen - fail
    ba fail
    nop

! =========================================================
! Trap handlers at 0x1000
! =========================================================
.section .trap, "ax"
.align 4096

! Trap 0x00
trap_00:
    ba fail
    nop
    nop
    nop

! Fill entries 0x01-0x08
.rept 8
    ba fail
    nop
    nop
    nop
.endr

! Trap 0x09 - data_access_exception
trap_09:
    ! Verify we came from context test
    cmp %g1, 0x44
    bne fail
    nop

    ! Disable MMU
    sta %g0, [%g0] 0x04
    nop

    ! Success - context isolation works
    ba pass
    nop

.rept 246
    ba fail
    nop
    nop
    nop
.endr

.text
.globl pass
pass:
    ba pass
    nop

.globl fail
fail:
    ba fail
    nop

.data
.align 4
