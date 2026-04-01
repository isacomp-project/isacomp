! Simple J2 Test - UART and Timer
! Uses sh-elf-gcc (bare metal toolchain)

    .section .text._start
    .global _start
    .align 2

.equ UART_BASE,   0xABCD0100
.equ UART_TX,     0x04
.equ AIC_INTPRI,  0xABCD0208
.equ PIT_PITEN,   0xABCD0200
.equ PIT_THROT,   0xABCD0210

_start:
    ! Set up stack
    mov.l   L_stack, r15

    ! Print 'H' for Hello
    mov.l   L_uart, r1
    mov     #'H', r0
    mov.l   r0, @(UART_TX, r1)

    ! Print 'i'
    mov     #'i', r0
    mov.l   r0, @(UART_TX, r1)

    ! Print newline
    mov     #10, r0
    mov.l   r0, @(UART_TX, r1)

    ! Enable AIC
    mov.l   L_aic, r2
    mov     #-1, r0
    mov.l   r0, @r2

    ! Set timer period
    mov.l   L_throt, r3
    mov.l   L_period, r0
    mov.l   r0, @r3

    ! Print 'O' for OK
    mov     #'O', r0
    mov.l   r0, @(UART_TX, r1)
    mov     #'K', r0
    mov.l   r0, @(UART_TX, r1)
    mov     #10, r0
    mov.l   r0, @(UART_TX, r1)

pass:
    bra     pass
    nop

    .align 2
L_stack:    .long 0x00011000
L_uart:     .long UART_BASE
L_aic:      .long AIC_INTPRI
L_throt:    .long PIT_THROT
L_period:   .long 5000
