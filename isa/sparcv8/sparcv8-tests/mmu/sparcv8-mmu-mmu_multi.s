! SPARCv8 MMU Multiple TLB Entries Test
! Tests that multiple TLB entries work correctly
!
! Test plan:
! 1. Write 4 different TLB entries
! 2. Enable MMU
! 3. Access each mapped page and verify translation
! 4. Store unique values to each page
! 5. Disable MMU and verify physical addresses contain expected data

.text
.align 4
.globl _start

_start:
    mov 1, %l0

    ! Set context to 0
    sethi %hi(0x200), %g2
    or %g2, %lo(0x200), %g2
    sta %g0, [%g2] 0x04
    nop

    ! =========================================================
    ! Write TLB entry 0: VA 0x10000 -> PA 0x80000
    ! PPN = 0x80000 >> 12 = 0x80, PTE = (0x80 << 8) | 0xFE = 0x80FE
    ! =========================================================
    sethi %hi(0x00010000), %l1 ! VPN=0x10, idx=0
    sethi %hi(0x000080FE), %l2 ! PPN=0x80, ACC=111, valid
    or %l2, %lo(0x000080FE), %l2
    sta %l2, [%l1] 0x05
    nop

    ! =========================================================
    ! Write TLB entry 1: VA 0x11000 -> PA 0x81000
    ! PPN = 0x81000 >> 12 = 0x81, PTE = (0x81 << 8) | 0xFE = 0x81FE
    ! =========================================================
    mov 2, %l0
    sethi %hi(0x00011040), %l1 ! VPN=0x11, idx=1
    or %l1, %lo(0x00011040), %l1
    sethi %hi(0x000081FE), %l2 ! PPN=0x81, ACC=111, valid
    or %l2, %lo(0x000081FE), %l2
    sta %l2, [%l1] 0x05
    nop

    ! =========================================================
    ! Write TLB entry 2: VA 0x12000 -> PA 0x82000
    ! PPN = 0x82000 >> 12 = 0x82, PTE = (0x82 << 8) | 0xFE = 0x82FE
    ! =========================================================
    mov 3, %l0
    sethi %hi(0x00012080), %l1 ! VPN=0x12, idx=2
    or %l1, %lo(0x00012080), %l1
    sethi %hi(0x000082FE), %l2 ! PPN=0x82, ACC=111, valid
    or %l2, %lo(0x000082FE), %l2
    sta %l2, [%l1] 0x05
    nop

    ! =========================================================
    ! Write TLB entry 3: VA 0x13000 -> PA 0x83000
    ! PPN = 0x83000 >> 12 = 0x83, PTE = (0x83 << 8) | 0xFE = 0x83FE
    ! =========================================================
    mov 4, %l0
    sethi %hi(0x000130C0), %l1 ! VPN=0x13, idx=3
    or %l1, %lo(0x000130C0), %l1
    sethi %hi(0x000083FE), %l2 ! PPN=0x83, ACC=111, valid
    or %l2, %lo(0x000083FE), %l2
    sta %l2, [%l1] 0x05
    nop

    ! =========================================================
    ! Enable MMU
    ! =========================================================
    mov 5, %l0
    mov 1, %l3
    sta %l3, [%g0] 0x04
    nop

    ! =========================================================
    ! Store unique values through each translation
    ! =========================================================
    mov 6, %l0

    ! Store 0x11111111 to VA 0x10000 (-> PA 0x80000)
    sethi %hi(0x00010000), %l4
    sethi %hi(0x11111111), %l5
    or %l5, %lo(0x11111111), %l5
    st %l5, [%l4]
    nop

    ! Store 0x22222222 to VA 0x11000 (-> PA 0x81000)
    sethi %hi(0x00011000), %l4
    or %l4, %lo(0x00011000), %l4
    sethi %hi(0x22222222), %l5
    or %l5, %lo(0x22222222), %l5
    st %l5, [%l4]
    nop

    ! Store 0x33333333 to VA 0x12000 (-> PA 0x82000)
    sethi %hi(0x00012000), %l4
    or %l4, %lo(0x00012000), %l4
    sethi %hi(0x33333333), %l5
    or %l5, %lo(0x33333333), %l5
    st %l5, [%l4]
    nop

    ! Store 0x44444444 to VA 0x13000 (-> PA 0x83000)
    sethi %hi(0x00013000), %l4
    or %l4, %lo(0x00013000), %l4
    sethi %hi(0x44444444), %l5
    or %l5, %lo(0x44444444), %l5
    st %l5, [%l4]
    nop

    ! =========================================================
    ! Read back through MMU and verify
    ! =========================================================
    mov 7, %l0

    sethi %hi(0x00010000), %l4
    ld [%l4], %l6
    nop
    sethi %hi(0x11111111), %l7
    or %l7, %lo(0x11111111), %l7
    cmp %l6, %l7
    bne fail
    nop

    mov 8, %l0
    sethi %hi(0x00011000), %l4
    or %l4, %lo(0x00011000), %l4
    ld [%l4], %l6
    nop
    sethi %hi(0x22222222), %l7
    or %l7, %lo(0x22222222), %l7
    cmp %l6, %l7
    bne fail
    nop

    mov 9, %l0
    sethi %hi(0x00012000), %l4
    or %l4, %lo(0x00012000), %l4
    ld [%l4], %l6
    nop
    sethi %hi(0x33333333), %l7
    or %l7, %lo(0x33333333), %l7
    cmp %l6, %l7
    bne fail
    nop

    mov 10, %l0
    sethi %hi(0x00013000), %l4
    or %l4, %lo(0x00013000), %l4
    ld [%l4], %l6
    nop
    sethi %hi(0x44444444), %l7
    or %l7, %lo(0x44444444), %l7
    cmp %l6, %l7
    bne fail
    nop

    ! =========================================================
    ! Disable MMU
    ! =========================================================
    mov 11, %l0
    sta %g0, [%g0] 0x04
    nop

    ! =========================================================
    ! Verify data at physical addresses
    ! =========================================================
    mov 12, %l0

    sethi %hi(0x00080000), %l4
    or %l4, %lo(0x00080000), %l4
    ld [%l4], %l6
    nop
    sethi %hi(0x11111111), %l7
    or %l7, %lo(0x11111111), %l7
    cmp %l6, %l7
    bne fail
    nop

    mov 13, %l0
    sethi %hi(0x00081000), %l4
    or %l4, %lo(0x00081000), %l4
    ld [%l4], %l6
    nop
    sethi %hi(0x22222222), %l7
    or %l7, %lo(0x22222222), %l7
    cmp %l6, %l7
    bne fail
    nop

    mov 14, %l0
    sethi %hi(0x00082000), %l4
    or %l4, %lo(0x00082000), %l4
    ld [%l4], %l6
    nop
    sethi %hi(0x33333333), %l7
    or %l7, %lo(0x33333333), %l7
    cmp %l6, %l7
    bne fail
    nop

    mov 15, %l0
    sethi %hi(0x00083000), %l4
    or %l4, %lo(0x00083000), %l4
    ld [%l4], %l6
    nop
    sethi %hi(0x44444444), %l7
    or %l7, %lo(0x44444444), %l7
    cmp %l6, %l7
    bne fail
    nop

    ! Success
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
