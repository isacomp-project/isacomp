# Minimal /init for OpenRISC OR1K initramfs
# Tests interrupt-driven stdout path (tty/8250 driver)
#
# OR1K syscall ABI: r11=syscall_nr, r3-r8=args, l.sys 0 to invoke
# Uses generic Linux syscall numbers (same as RISC-V, ARM64, etc.)

.section .text
.global _start
_start:
    # Write to stdout (fd 1) - goes through tty/8250 interrupt-driven path
    # Message is 160 chars = 10x FIFO fills, needs 9+ UART THR-empty interrupts
    l.ori  r11, r0, 64          # __NR_write
    l.ori  r3, r0, 1            # fd = stdout
    l.movhi r4, hi(msg)
    l.ori  r4, r4, lo(msg)
    l.ori  r5, r0, 160          # len
    l.sys  0
    l.nop

loop:
    # sched_yield()
    l.ori  r11, r0, 124         # __NR_sched_yield
    l.sys  0
    l.nop
    l.j    loop
    l.nop

.section .rodata
msg:
    .ascii "Hello from OpenRISC userspace! This is a longer message to test that the UART interrupt-driven path works correctly for multiple FIFO refills. (160 chars)\n\0"
