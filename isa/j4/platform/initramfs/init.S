! Minimal init for J4 (SH4) Linux boot test
! Opens /dev/kmsg and writes a greeting, then loops forever
!
! SH4 Linux syscall convention:
!   Syscall number in R3
!   Arguments in R4, R5, R6, R7
!   Return value in R0
!   Invoked via trapa #0x15

    .section .text
    .global _start
    .align 2

_start:
    ! open("/dev/kmsg", O_WRONLY, 0)
    mov     #5, r3          ! __NR_open = 5
    mova    kmsg_path, r0
    mov     r0, r4          ! pathname
    mov     #1, r5          ! O_WRONLY
    mov     #0, r6          ! mode
    trapa   #0x15
    ! r0 = fd

    ! write(fd, msg, 25)
    mov     r0, r4          ! fd from open
    mov     #4, r3          ! __NR_write = 4
    mova    hello_msg, r0
    mov     r0, r5          ! buf
    mov     #25, r6         ! count = strlen("Hello from J4 userspace!\n")
    trapa   #0x15

    ! pause() in a loop
loop:
    mov     #29, r3         ! __NR_pause = 29
    trapa   #0x15
    bra     loop
    nop

    .align 2
kmsg_path:
    .asciz "/dev/kmsg"
    .align 2
hello_msg:
    .asciz "Hello from J4 userspace!\n"
