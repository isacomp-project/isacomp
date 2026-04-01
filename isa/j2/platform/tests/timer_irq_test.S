! J2 Timer Interrupt Test
! Tests the JCORE AIC and PIT integration
!
! Memory Map:
!   0x00000000: Program start
!   0x00001000: Stack (grows down)
!   0xABCD0100: UARTLite
!   0xABCD0200: AIC (INTPRI at +0x08)
!   0xABCD0200: PIT (PITEN at +0x00, THROT at +0x10)
!
! Expected behavior:
! 1. Initialize stack pointer
! 2. Set up VBR for interrupt vectors
! 3. Enable AIC by writing 0xffffffff to INTPRI
! 4. Configure PIT with IRQ 0x48, priority, and enable
! 5. Wait for timer interrupt
! 6. In interrupt handler, print character and disable timer
! 7. Return from exception

    .section .text
    .global _start
    .align 2

! Constants
.equ UART_BASE,   0xABCD0100
.equ UART_TX,     0x04          ! TX FIFO offset
.equ UART_STAT,   0x08          ! Status register offset

.equ AIC_BASE,    0xABCD0200
.equ AIC_INTPRI,  0x08          ! Priority register offset

.equ PIT_BASE,    0xABCD0200
.equ PIT_PITEN,   0x00          ! Enable register
.equ PIT_THROT,   0x10          ! Throttle/period register

.equ STACK_TOP,   0x00001000
.equ VBR_BASE,    0x00000400    ! Vector table base

! PIT enable value: enable=1, irq=0x48, priority=0xC
! Bit layout: e..pppp.iiiiiiii........
.equ PIT_ENABLE_VAL, 0x04C48000

_start:
    ! Initialize stack pointer
    mov.l   stack_addr, r15

    ! Set up VBR (Vector Base Register)
    mov.l   vbr_addr, r0
    ldc     r0, vbr

    ! Print 'S' for start
    mov.l   uart_addr, r1
    mov     #'S', r0
    mov.l   r0, @(UART_TX, r1)

    ! Enable interrupts in AIC by setting INTPRI = 0xffffffff
    mov.l   aic_addr, r2
    mov     #-1, r0             ! 0xffffffff
    mov.l   r0, @(AIC_INTPRI, r2)

    ! Print 'A' for AIC enabled
    mov     #'A', r0
    mov.l   r0, @(UART_TX, r1)

    ! Configure and start timer
    ! First set throttle value (period)
    mov.l   pit_addr, r3
    mov.l   pit_period, r0
    mov.l   r0, @(PIT_THROT, r3)

    ! Enable timer with IRQ 0x48
    mov.l   pit_enable, r0
    mov.l   r0, @(PIT_PITEN, r3)

    ! Print 'T' for timer started
    mov     #'T', r0
    mov.l   r0, @(UART_TX, r1)

    ! Enable interrupts in SR (clear BL bit, set IMASK low)
    stc     sr, r0
    mov.l   sr_mask, r4
    and     r4, r0              ! Clear BL (bit 29)
    mov.l   sr_imask, r4
    and     r4, r0              ! Clear IMASK bits
    ldc     r0, sr

    ! Print 'W' for waiting
    mov     #'W', r0
    mov.l   r0, @(UART_TX, r1)

    ! Wait loop - will be interrupted by timer
    mov     #0, r8              ! Counter
wait_loop:
    add     #1, r8
    mov.l   max_wait, r0
    cmp/hi  r0, r8
    bf      wait_loop

    ! If we get here, timeout - print 'X' and halt
    mov     #'X', r0
    mov.l   r0, @(UART_TX, r1)
    bra     halt
    nop

halt:
    sleep
    bra     halt
    nop

! Pass - reached when interrupt handler completes
pass:
    ! Print 'P' for pass
    mov.l   uart_addr, r1
    mov     #'P', r0
    mov.l   r0, @(UART_TX, r1)
    mov     #'\n', r0
    mov.l   r0, @(UART_TX, r1)

pass_halt:
    bra     pass_halt
    nop

    .align 2
stack_addr:     .long STACK_TOP
vbr_addr:       .long VBR_BASE
uart_addr:      .long UART_BASE
aic_addr:       .long AIC_BASE
pit_addr:       .long PIT_BASE
pit_period:     .long 1000          ! Timer period (cycles)
pit_enable:     .long PIT_ENABLE_VAL
sr_mask:        .long 0xDFFFFFFF    ! Clear BL bit (bit 29)
sr_imask:       .long 0xFFFFFF0F    ! Clear IMASK (bits 4-7)
max_wait:       .long 100000        ! Max wait iterations

! ============================================================================
! Interrupt Vector Table (at VBR_BASE)
! ============================================================================
    .section .vectors, "ax"
    .org 0x400

! Vectors 0-15: Reserved/exceptions
    .rept 16
    .long exception_handler
    .endr

! Vectors 16-63: Interrupts (AIC1 range)
    .rept 48
    .long irq_handler
    .endr

! Vectors 64-71: More interrupts
    .rept 8
    .long irq_handler
    .endr

! Vector 72 (0x48): Timer interrupt
    .long timer_handler

! Vectors 73-127: More interrupts
    .rept 55
    .long irq_handler
    .endr

! ============================================================================
! Exception/Interrupt Handlers
! ============================================================================
    .section .text
    .align 2

exception_handler:
    ! Generic exception - print 'E' and halt
    mov.l   uart_addr_h, r1
    mov     #'E', r0
    mov.l   r0, @(UART_TX, r1)
    bra     halt
    nop

irq_handler:
    ! Generic IRQ - print 'I' and return
    mov.l   uart_addr_h, r1
    mov     #'I', r0
    mov.l   r0, @(UART_TX, r1)
    rte
    nop

timer_handler:
    ! Timer interrupt handler
    ! Save registers
    mov.l   r0, @-r15
    mov.l   r1, @-r15
    mov.l   r2, @-r15

    ! Print '!' for timer interrupt
    mov.l   uart_addr_h, r1
    mov     #'!', r0
    mov.l   r0, @(UART_TX, r1)

    ! Disable timer
    mov.l   pit_addr_h, r2
    mov     #0, r0
    mov.l   r0, @(PIT_PITEN, r2)

    ! Restore registers
    mov.l   @r15+, r2
    mov.l   @r15+, r1
    mov.l   @r15+, r0

    ! Return from exception - will return to pass label
    ! Modify return PC on stack to go to pass
    mov.l   pass_addr, r0
    mov.l   r0, @r15            ! Overwrite saved PC

    rte
    nop

    .align 2
uart_addr_h:    .long UART_BASE
pit_addr_h:     .long PIT_BASE
pass_addr:      .long pass

! ============================================================================
! Linker script expects these
! ============================================================================
    .section .data
    .section .bss
