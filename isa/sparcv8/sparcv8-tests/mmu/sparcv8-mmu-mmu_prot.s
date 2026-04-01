! SPARCv8 MMU Protection Violation Test
! Tests that accessing page without permission causes trap
!
! Test plan:
! 1. Set up TBR for trap handlers
! 2. Write TLB entry with execute-only permissions (ACC=100)
! 3. Enable MMU
! 4. Try to read from page - should trap (protection violation)
! 5. Trap handler verifies and signals pass

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
    ! Test 2: Write TLB entry with execute-only permission
    ! Map VA 0x30000 -> PA 0x40000
    ! ACC = 100 (execute only - no read permission)
    ! =========================================================
    mov 2, %l0

    ! TLB address: VPN = 0x00030, index = 1
    ! Address = 0x00030000 | (1 << 6) = 0x00030040
    sethi %hi(0x00030040), %l1
    or %l1, %lo(0x00030040), %l1

    ! PTE: PPN = 0x40 (PA 0x40000 >> 12), ACC = 100, C=1, M=0, R=0, ET=10
    ! PTE = (0x40 << 8) | 0x80 | 0x10 | 0x02 = 0x4092
    sethi %hi(0x00004092), %l2
    or %l2, %lo(0x00004092), %l2

    ! Write TLB entry
    sta %l2, [%l1] 0x05
    nop

    ! =========================================================
    ! Test 3: Set context to 0
    ! =========================================================
    mov 3, %l0

    sethi %hi(0x200), %l3
    or %l3, %lo(0x200), %l3
    sta %g0, [%l3] 0x04
    nop

    ! =========================================================
    ! Test 4: Enable MMU
    ! =========================================================
    mov 4, %l0

    mov 1, %l4
    sta %l4, [%g0] 0x04
    nop

    ! =========================================================
    ! Test 5: Try to read from execute-only page
    ! Should cause protection violation trap (trap 0x09)
    ! =========================================================
    mov 5, %l0

    sethi %hi(0x00030000), %l5
    or %l5, %lo(0x00030000), %l5

    ! Mark that we're about to take a trap
    mov 0x43, %g1 ! Magic marker for protection test

    ! This should trap - page is execute-only, no read permission
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

! Trap 0x00 - reset
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
    ! Verify we came from protection test
    cmp %g1, 0x43
    bne fail
    nop

    ! Disable MMU
    mov %g0, %l4
    sta %l4, [%g0] 0x04
    nop

    ! Success - protection trap worked
    ba pass
    nop

! Fill remaining trap entries
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
