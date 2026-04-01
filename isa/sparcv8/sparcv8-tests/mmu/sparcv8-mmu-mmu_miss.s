! SPARCv8 MMU TLB Miss Test
! Tests that accessing unmapped addresses causes trap
!
! Test plan:
! 1. Set up TBR to point to trap handlers
! 2. Enable MMU (without any TLB entries)
! 3. Access unmapped address - should trap
! 4. Trap handler verifies trap type and signals pass

.text
.align 4
.globl _start

_start:
    ! Initialize test number
    mov 1, %l0

    ! =========================================================
    ! Test 1: Set up TBR to point to trap table at 0x1000
    ! =========================================================
    sethi %hi(0x00001000), %l1
    or %l1, %lo(0x00001000), %l1
    mov %l1, %tbr
    nop

    ! =========================================================
    ! Test 2: Set context register to 0
    ! Address = 0x200 (context register offset)
    ! =========================================================
    mov 2, %l0

    sethi %hi(0x200), %l2
    or %l2, %lo(0x200), %l2
    mov %g0, %l3
    sta %l3, [%l2] 0x04
    nop

    ! =========================================================
    ! Test 3: Enable MMU (no TLB entries set up)
    ! =========================================================
    mov 3, %l0

    mov 1, %l4
    sta %l4, [%g0] 0x04
    nop

    ! =========================================================
    ! Test 4: Access unmapped address - should cause TLB miss
    ! The load should trap to data_access_exception (trap 0x09)
    ! =========================================================
    mov 4, %l0

    ! Try to load from VA 0x50000 (no TLB entry)
    sethi %hi(0x00050000), %l5
    or %l5, %lo(0x00050000), %l5

    ! Mark that we're about to take a trap
    mov 0x42, %g1 ! Magic marker

    ! This should trap
    ld [%l5], %l6
    nop

    ! If we get here, trap didn't happen - fail
    ba fail
    nop

! =========================================================
! Trap handlers at 0x1000
! =========================================================
.section .trap, "ax"
.align 4096

! Trap 0x00 - reset (shouldn't happen)
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

! Trap 0x09 - data_access_exception (TLB miss or protection)
trap_09:
    ! Verify we came from the expected test
    cmp %g1, 0x42
    bne fail
    nop

    ! Disable MMU
    mov %g0, %l4
    sta %l4, [%g0] 0x04
    nop

    ! Success - TLB miss trap worked
    ba pass
    nop

! Fill remaining trap entries with fail handlers
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
