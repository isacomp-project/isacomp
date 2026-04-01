! SPARCv8 MMU Basic Test
! Tests TLB configuration and basic address translation
!
! Test plan:
! 1. Write TLB entry mapping VA 0x10000 -> PA 0x20000
! 2. Enable MMU
! 3. Store a value to VA 0x10000 (should go to PA 0x20000)
! 4. Load back from VA 0x10000 and verify
! 5. Disable MMU and read directly from PA 0x20000 to verify

.text
.align 4
.globl _start

_start:
    ! Initialize test number in %l0
    mov 1, %l0

    ! =========================================================
    ! Test 1: Write TLB entry
    ! Map VA 0x00010000 -> PA 0x00020000
    ! TLB entry 0, ACC=111 (all access), valid PTE
    ! =========================================================

    ! Build TLB write address: VPN in [31:12], index in [11:6]
    ! VPN = 0x00010 (for VA 0x10000), index = 0
    ! Address = 0x00010000 | (0 << 6) = 0x00010000
    sethi %hi(0x00010000), %l1     ! Address with VPN and index
    or %l1, %lo(0x00010000), %l1

    ! Build PTE data: PPN in [31:8], ACC in [4:2], ET in [1:0]
    ! PPN = 0x000020 (for PA 0x20000), ACC=111, C=1, M=1, R=1, ET=10
    ! PTE = (0x000020 << 8) | 0x80 | 0x40 | 0x20 | 0x1C | 0x02
    !     = 0x00002000 | 0xFE = 0x000020FE
    sethi %hi(0x000020FE), %l2
    or %l2, %lo(0x000020FE), %l2

    ! Write TLB entry using STA to ASI 0x05
    ! sta %l2, [%l1 + %g0] 0x05
    sta %l2, [%l1] 0x05
    nop

    ! =========================================================
    ! Test 2: Enable MMU
    ! Write 1 to MMU Control Register (address offset 0x000)
    ! =========================================================
    mov 2, %l0

    ! Address for MMU Control = 0x000 (reg_sel = 0)
    mov %g0, %l3

    ! Data = 1 (enable MMU)
    mov 1, %l4

    ! Write MMU control via STA to ASI 0x04
    sta %l4, [%l3] 0x04
    nop

    ! =========================================================
    ! Test 3: Store value through MMU translation
    ! Store to VA 0x10000 (should go to PA 0x20000)
    ! =========================================================
    mov 3, %l0

    ! Address = VA 0x10000
    sethi %hi(0x00010000), %l5
    or %l5, %lo(0x00010000), %l5

    ! Value to store = 0xDEADBEEF
    sethi %hi(0xDEADBEEF), %l6
    or %l6, %lo(0xDEADBEEF), %l6

    ! Store to translated address
    st %l6, [%l5]
    nop

    ! =========================================================
    ! Test 4: Load back through MMU and verify
    ! Load from VA 0x10000, should get 0xDEADBEEF
    ! =========================================================
    mov 4, %l0

    ld [%l5], %l7
    nop

    ! Verify loaded value
    sethi %hi(0xDEADBEEF), %o0
    or %o0, %lo(0xDEADBEEF), %o0
    cmp %l7, %o0
    bne fail
    nop

    ! =========================================================
    ! Test 5: Disable MMU and read from physical address
    ! =========================================================
    mov 5, %l0

    ! Disable MMU
    mov %g0, %l4
    sta %l4, [%g0] 0x04
    nop

    ! Read directly from PA 0x20000
    sethi %hi(0x00020000), %o1
    or %o1, %lo(0x00020000), %o1
    ld [%o1], %o2
    nop

    ! Verify it's the same value (confirms translation worked)
    cmp %o2, %o0
    bne fail
    nop

    ! =========================================================
    ! All tests passed
    ! =========================================================
    ba pass
    nop

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
