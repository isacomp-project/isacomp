! J4 Boot ROM
! Sets up R4 with FDT pointer and jumps to Linux kernel
! For NOMMU boot - similar to J2 but with J4-specific initialization
!
! Memory layout (defined by linker script):
!   0x00000000  - Padding (first 4KB, not in vmlinux.bin)
!   0x00001000  - Kernel .empty_zero_page (boot params)
!   0x00002000  - Kernel _stext (entry point)
!   After kernel - FDT
!   After FDT   - Boot ROM (_start)
!   0x03800000  - Initrd (loaded by testbench)
!
! Boot ROM is placed after the kernel and FDT in memory.
! The testbench starts the CPU at _start, which sets up
! R4 (FDT pointer), patches initrd params, and jumps to kernel.

    ! Padding section for addresses 0x0000-0x0FFF
    .section .padding, "a"
    .global _padding
_padding:
    .space 0x1000, 0x00

    ! Boot ROM code
    .section .text.boot
    .global _start
    .align 2

_start:
    ! Set up VBR to kernel's vbr_base
    ! This must be done before any TRAPA or exception can occur
    mov.l   vbr_init, r1
    ldc     r1, vbr

    ! Initialize FPSCR for J4 (SH-4) FPU
    ! Set reasonable defaults: DN=0 (denormal as denormal), PR=0 (single precision)
    ! RM=00 (round to nearest), FR=0 (use bank 0)
    mov.l   fpscr_init, r1
    lds     r1, fpscr

    ! Patch boot params in empty_zero_page for external initrd
    ! Boot params are at 0x1000 (empty_zero_page):
    !   0x1010: INITRD_START
    !   0x1014: INITRD_SIZE
    mov.l   initrd_start_addr, r0
    mov.l   initrd_start_val, r1
    mov.l   r1, @r0             ! Store INITRD_START

    mov.l   initrd_size_addr, r0
    mov.l   initrd_size_val, r1
    mov.l   r1, @r0             ! Store INITRD_SIZE

    ! Set up R4 = FDT pointer (required by Linux boot protocol)
    mov.l   fdt_addr, r4

    ! R5, R6, R7 = 0 (unused)
    mov     #0, r5
    mov     #0, r6
    mov     #0, r7

    ! Jump to kernel entry point
    mov.l   kernel_addr, r0
    jmp     @r0
    nop                     ! delay slot

    .align 2
vbr_init:
    .long   0x518c          ! Kernel's vbr_base address (6.6 kernel)
fpscr_init:
    .long   0x00040001      ! FPSCR: DN=0, PR=0, SZ=0, FR=0, RM=01 (round toward zero)
initrd_start_addr:
    .long   0x00001010      ! Address of INITRD_START in empty_zero_page
initrd_start_val:
    .long   0x00000000      ! External initrd disabled (using embedded initramfs)
initrd_size_addr:
    .long   0x00001014      ! Address of INITRD_SIZE in empty_zero_page
initrd_size_val:
    .long   0x00000000      ! External initrd disabled (using embedded initramfs)
fdt_addr:
    .long   _fdt
kernel_addr:
    .long   _kernel

    .size _start, . - _start
