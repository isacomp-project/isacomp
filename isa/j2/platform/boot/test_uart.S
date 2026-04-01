! Test Boot ROM - UART Output Test
! Writes "Hello UART!\n" directly to UART TX register to verify testbench detection
!
! UART TX register: 0x03F00104 (within internal memory range)

    .section .text.boot
    .global _start
    .align 2

_start:
    ! Load UART TX address into R0
    mov.l   uart_tx, r0

    ! Write 'H' (0x48)
    mov     #0x48, r1
    mov.l   r1, @r0

    ! Write 'e' (0x65)
    mov     #0x65, r1
    mov.l   r1, @r0

    ! Write 'l' (0x6C)
    mov     #0x6C, r1
    mov.l   r1, @r0

    ! Write 'l' (0x6C)
    mov     #0x6C, r1
    mov.l   r1, @r0

    ! Write 'o' (0x6F)
    mov     #0x6F, r1
    mov.l   r1, @r0

    ! Write ' ' (0x20)
    mov     #0x20, r1
    mov.l   r1, @r0

    ! Write 'U' (0x55)
    mov     #0x55, r1
    mov.l   r1, @r0

    ! Write 'A' (0x41)
    mov     #0x41, r1
    mov.l   r1, @r0

    ! Write 'R' (0x52)
    mov     #0x52, r1
    mov.l   r1, @r0

    ! Write 'T' (0x54)
    mov     #0x54, r1
    mov.l   r1, @r0

    ! Write '!' (0x21)
    mov     #0x21, r1
    mov.l   r1, @r0

    ! Write newline (0x0A)
    mov     #0x0A, r1
    mov.l   r1, @r0

    ! Infinite loop
loop:
    bra     loop
    nop

    .align 2
uart_tx:
    .long   0x03F00104

    .size _start, . - _start
