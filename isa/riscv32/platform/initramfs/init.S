# Minimal /init for RISC-V 32 initramfs
# Writes to /dev/kmsg which uses the printk console path (direct UART polling)

.section .text
.global _start
_start:
    # First write to stdout (fd 1) - may or may not work
    li   a7, 64           # __NR_write
    li   a0, 1            # fd = stdout
    lla  a1, msg
    li   a2, 29           # len
    ecall

    # Open /dev/kmsg for guaranteed output via printk console path
    li   a7, 56           # __NR_openat
    li   a0, -100         # AT_FDCWD
    lla  a1, kmsg_path
    li   a2, 1            # O_WRONLY
    li   a3, 0
    ecall

    # write(fd, msg, 29)
    mv   s0, a0           # save fd
    li   a7, 64           # __NR_write
    mv   a0, s0
    lla  a1, msg
    li   a2, 29
    ecall

    # close(fd)
    li   a7, 57           # __NR_close
    mv   a0, s0
    ecall

loop:
    # sched_yield()
    li   a7, 124          # __NR_sched_yield
    ecall
    j    loop

.section .rodata
kmsg_path:
    .asciz "/dev/kmsg"
msg:
    .ascii "Hello from RISC-V userspace!\n"
