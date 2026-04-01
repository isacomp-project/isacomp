! J4 Boot ROM for SH4 MMU Mode
! Sets up MMU registers and jumps to Linux kernel in P1 region
!
! SH-4 Address Space Regions:
!   P0/U0: 0x00000000-0x7FFFFFFF - User/Kernel, TRANSLATED (uses TLB)
!   P1:    0x80000000-0x9FFFFFFF - Kernel, CACHED, UNTRANSLATED
!   P2:    0xA0000000-0xBFFFFFFF - Kernel, UNCACHED, UNTRANSLATED
!   P3:    0xC0000000-0xDFFFFFFF - Kernel, TRANSLATED (uses TLB)
!   P4:    0xE0000000-0xFFFFFFFF - Control regs, UNTRANSLATED
!
! Memory layout (physical addresses):
!   0x00000000  - Boot ROM (_start)
!   0x00000100  - Device Tree Blob (_fdt)
!   0x00001000  - Kernel .empty_zero_page (boot params)
!   0x00002000  - Kernel _stext (entry point)
!   0x03800000  - Initramfs (if external, otherwise embedded)
!   0x03F00000  - Peripherals (via P2: 0xA3F00000)
!
! CPU starts at P2 address 0xA0000000 (= physical 0x00000000)
! Kernel runs at P1 address 0x80002000 (= physical 0x00002000)

    ! Boot ROM code section
    .section .text.boot
    .global _start
    .align 2

_start:
    ! =========================================================================
    ! Step 1: Initialize SR for privileged mode
    ! SR bits: MD=1 (privileged), RB=0 (use bank 0), BL=1 (block interrupts)
    !          FD=0 (FPU enabled), IMASK=0xF (mask all IRQs initially)
    ! =========================================================================
    mov.l   sr_init, r0
    ldc     r0, sr

    ! =========================================================================
    ! Step 2: Set up VBR to kernel's exception vector base
    ! For SH4 Linux kernel, VBR points to start of exception handlers
    ! In P1 region (0x80000000 + physical VBR address)
    ! =========================================================================
    mov.l   vbr_init, r1
    ldc     r1, vbr

    ! =========================================================================
    ! Step 3: Initialize FPSCR for FPU
    ! DN=0, PR=0 (single precision), RM=01 (round toward zero)
    ! =========================================================================
    mov.l   fpscr_init, r1
    lds     r1, fpscr

    ! =========================================================================
    ! Step 4: Enable MMU (address translation)
    ! Use LDC instruction to write MMUCR directly (not P4 memory-mapped store).
    ! AT=1 enables address translation for P3/P0 regions via TLB.
    ! TI=1 invalidates all TLB entries (auto-clears after write).
    ! P1/P2 remain untranslated regardless of MMUCR.AT.
    ! =========================================================================
    mov.l   mmucr_init, r1
    .word   0x4135          ! LDC R1,MMUCR (J4 encoding: 0x4m35, m=1)
                            ! Set MMUCR: AT=1, TI=1 (enable MMU, flush TLB)

    ! =========================================================================
    ! Step 5: Patch boot params in empty_zero_page for external initrd
    ! Boot params are at P1 address 0x80001000 (physical 0x1000):
    !   0x80001010: INITRD_START
    !   0x80001014: INITRD_SIZE
    ! Set to 0 if using embedded initramfs
    ! =========================================================================
    mov.l   initrd_start_p1, r0
    mov.l   initrd_start_val, r1
    mov.l   r1, @r0             ! Store INITRD_START

    mov.l   initrd_size_p1, r0
    mov.l   initrd_size_val, r1
    mov.l   r1, @r0             ! Store INITRD_SIZE

    ! =========================================================================
    ! Step 5b: Copy kernel command line to boot params
    ! SH4 kernel reads command line from empty_zero_page + 0x100 = 0x80001100
    ! FDT bootargs is parsed AFTER parse_early_param(), too late for earlycon!
    ! =========================================================================
    mov.l   cmdline_dst, r0     ! r0 = destination (0x80001100)
    mov.l   cmdline_src, r1     ! r1 = source (command line string)
cmdline_copy:
    mov.b   @r1+, r2            ! Load byte from source, increment
    mov.b   r2, @r0             ! Store byte to destination
    add     #1, r0              ! Increment destination pointer
    tst     r2, r2              ! Check if null terminator
    bf      cmdline_copy        ! Loop if not null

    ! =========================================================================
    ! Step 6: Set up bank1 R7 for exception handling
    ! SH-4 Linux exception handler uses bank1 R7 as pointer to current task
    ! It adds 0x2000 (THREAD_SIZE) to R7 to get kernel stack pointer
    ! For init task, R7 should be init_thread_union (0x80276000)
    ! =========================================================================
    mov.l   init_thread_addr, r1
    ldc     r1, r7_bank         ! Bank1 R7 = init_thread_union

    ! =========================================================================
    ! Step 7: Set up kernel boot arguments
    ! R4 = FDT pointer (in P1 region)
    ! R5, R6, R7 = 0 (unused by kernel)
    ! =========================================================================
    mov.l   fdt_addr_p1, r4     ! R4 = FDT address in P1 region
    mov     #0, r5
    mov     #0, r6
    mov     #0, r7

    ! =========================================================================
    ! TEST: Output 'B' to UART to verify UART emulation works
    ! UART TX is at P2 address 0xA3F00104
    ! =========================================================================
    mov.l   uart_tx_addr, r0
    mov     #0x42, r1           ! 'B' character
    mov.l   r1, @r0             ! Write to UART TX
    mov     #0x4F, r1           ! 'O' character
    mov.l   r1, @r0
    mov     #0x4F, r1           ! 'O' character
    mov.l   r1, @r0
    mov     #0x54, r1           ! 'T' character
    mov.l   r1, @r0
    mov     #0x0a, r1           ! newline
    mov.l   r1, @r0

    ! =========================================================================
    ! Step 7: Jump to kernel entry point in P1 region
    ! Kernel entry is at P1 address 0x80002000 (physical 0x2000)
    ! P1 is cached, untranslated - ideal for kernel execution
    ! =========================================================================
    mov.l   kernel_addr_p1, r0
    jmp     @r0
    nop                         ! delay slot

    .align 4

! SR: MD=1 (bit 30), RB=0 (bit 29), BL=1 (bit 28), IMASK=0xF (bits 7:4)
! MD=1 is CRITICAL for privileged kernel execution
! RB=0 so R0-R7 access goes to bank0 (rf[], not rf_bank[])
! BL=1 blocks exceptions during boot
sr_init:
    .long   0x500000F0

! VBR in P1 region - kernel exception handlers
! For Linux 6.x kernel with MEMORY_START=0, vbr_base is at 0x80007000
vbr_init:
    .long   0x80007000

! FPSCR initial value
fpscr_init:
    .long   0x00040001

! MMUCR: AT=1 (enable), TI=1 (invalidate TLB)
! Address in P4 region (control space)
mmucr_addr:
    .long   0xFF000010
mmucr_init:
    .long   0x00000005          ! AT=1, TI=1 (bit 2 write clears TLB)

! Initrd parameters (in P1 region)
initrd_start_p1:
    .long   0x80001010          ! P1 address of INITRD_START
initrd_start_val:
    .long   0                   ! 0 = use embedded initramfs (CONFIG_INITRAMFS_SOURCE)

initrd_size_p1:
    .long   0x80001014          ! P1 address of INITRD_SIZE
initrd_size_val:
    .long   0                   ! 0 = use embedded initramfs

! FDT physical address (kernel does phys_to_virt() to get P1 0x80000100)
fdt_addr_p1:
    .long   0x00000100

! Kernel entry in P1 region (physical 0x2000 -> P1 0x80002000)
kernel_addr_p1:
    .long   0x80002000

! UART TX address in P2 region (physical 0x03F00104)
uart_tx_addr:
    .long   0xA3F00104

! init_thread_union address (kernel's init task thread info)
! This is used by exception handler to get kernel stack pointer
init_thread_addr:
    .long   0x802d4000

! Command line destination in boot params (COMMAND_LINE = PARAM + 0x100)
cmdline_dst:
    .long   0x80001100

! Command line source pointer
cmdline_src:
    .long   cmdline_str

! Kernel command line string
! earlycon: uartlite at P2 address 0xA3F00100 for early serial output
! console: ttyUL0 for normal console after driver probe
! lpj: skip timer calibration delay
! random.trust_bootloader: trust rng-seed from device tree
    .align 2
cmdline_str:
    .asciz  "earlycon=uartlite,mmio,0xa3f00100 console=ttyUL0,115200 lpj=250000 random.trust_bootloader=1"

    .size _start, . - _start
