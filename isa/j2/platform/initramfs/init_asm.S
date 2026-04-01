.section .text
.global _start
_start:
    ! Write directly to UART: "Hello from J2 userspace!\n"
    ! UART TX register at 0x03F00104
    mov.l uart_addr, r1
    mov #'H', r0
    mov.l r0, @r1
    mov #'e', r0
    mov.l r0, @r1
    mov #'l', r0
    mov.l r0, @r1
    mov #'l', r0
    mov.l r0, @r1
    mov #'o', r0
    mov.l r0, @r1
    mov #' ', r0
    mov.l r0, @r1
    mov #'f', r0
    mov.l r0, @r1
    mov #'r', r0
    mov.l r0, @r1
    mov #'o', r0
    mov.l r0, @r1
    mov #'m', r0
    mov.l r0, @r1
    mov #' ', r0
    mov.l r0, @r1
    mov #'J', r0
    mov.l r0, @r1
    mov #'2', r0
    mov.l r0, @r1
    mov #' ', r0
    mov.l r0, @r1
    mov #'u', r0
    mov.l r0, @r1
    mov #'s', r0
    mov.l r0, @r1
    mov #'e', r0
    mov.l r0, @r1
    mov #'r', r0
    mov.l r0, @r1
    mov #'s', r0
    mov.l r0, @r1
    mov #'p', r0
    mov.l r0, @r1
    mov #'a', r0
    mov.l r0, @r1
    mov #'c', r0
    mov.l r0, @r1
    mov #'e', r0
    mov.l r0, @r1
    mov #'!', r0
    mov.l r0, @r1
    mov #'\n', r0
    mov.l r0, @r1

    ! Now try the syscall approach
    ! Write syscall: write(1, msg, len)
    mov #4, r3          ! syscall number for write (SH Linux)
    mov #1, r4          ! fd = stdout
    mova msg, r0
    mov r0, r5          ! buf = msg
    mov #17, r6         ! len
    trapa #0x1f         ! syscall (vector 31 for J2)

loop:
    ! pause() syscall
    mov #29, r3         ! syscall number for pause
    trapa #0x1f         ! syscall (vector 31 for J2)
    bra loop
    nop

.align 2
uart_addr:
    .long 0x03F00104
msg:
    .ascii "Hello from init!\n"
