! J4 UART Test
! Simple test program that prints a message to UART
! This validates the testbench UART handling works correctly

.section .text
.global _start
.align 2

_start:
    ! UART TX register at 0x03F00104
    mov.l   uart_tx_addr, r1

    ! Print "J4 UART OK\n"
    mov     #'J', r0
    mov.l   r0, @r1
    mov     #'4', r0
    mov.l   r0, @r1
    mov     #' ', r0
    mov.l   r0, @r1
    mov     #'U', r0
    mov.l   r0, @r1
    mov     #'A', r0
    mov.l   r0, @r1
    mov     #'R', r0
    mov.l   r0, @r1
    mov     #'T', r0
    mov.l   r0, @r1
    mov     #' ', r0
    mov.l   r0, @r1
    mov     #'O', r0
    mov.l   r0, @r1
    mov     #'K', r0
    mov.l   r0, @r1
    mov     #'\n', r0
    mov.l   r0, @r1

pass:
    ! Signal test passed by jumping to pass label
    bra     pass
    nop

fail:
    ! Should never reach here
    bra     fail
    nop

.align 2
uart_tx_addr:
    .long   0x03F00104

.size _start, . - _start
