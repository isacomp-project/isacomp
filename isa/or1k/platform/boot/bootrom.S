/*
 * OpenRISC OR1K Boot ROM for ISAComp Linux Platform
 *
 * Memory Map:
 *   0x00000000 - 0x00000FFF  Exception vectors (4KB)
 *   0x00001000 - 0x00001FFF  Boot ROM code
 *   0x00002000 - 0x03EFFFFF  Linux kernel image
 *   0x03F00000 - 0x03FFFFFF  Device tree blob + initramfs
 *   0x90000000 - 0x900001FF  I/O: UART, PIC, Timer
 *
 * Boot sequence:
 *   1. Set up stack pointer (R1)
 *   2. Clear BSS
 *   3. Pass parameters to kernel
 *   4. Jump to kernel entry point
 *
 * OpenRISC Linux boot protocol:
 *   R3 = pointer to FDT (flattened device tree)
 *   R4 = 0 (unused)
 *   R5 = 0 (unused)
 */

    .section .text
    .global _start
    .org 0x100

/* Reset vector */
_reset:
    /* Disable MMU and interrupts for boot */
    l.mfspr r1, r0, 17          /* Read SR (SPR group 0, index 17) */
    l.andi  r1, r1, 0xFFF0      /* Clear SM, TEE, IEE, DCE */
    l.ori   r1, r1, 0x0001      /* Set SM (supervisor mode) */
    l.ori   r1, r1, 0x4000      /* Set FO (fixed one) */
    l.mtspr r0, r1, 17          /* Write SR */

    /* Set up stack pointer (top of memory - 64KB for boot stack) */
    l.movhi r1, 0x03F0           /* R1 = 0x03F00000 */

    /* Set R3 = device tree blob pointer */
    l.movhi r3, 0x03F0           /* DTB at 0x03F00000 */
    l.ori   r3, r3, 0x0000

    /* Clear R4, R5 (unused boot params) */
    l.addi  r4, r0, 0
    l.addi  r5, r0, 0

    /* Jump to kernel entry point at 0x2000 */
    l.movhi r6, 0x0000
    l.ori   r6, r6, 0x2000
    l.jr    r6
    l.nop

/* Bus error vector */
    .org 0x200
_bus_error:
    l.nop
    l.j _bus_error
    l.nop

/* Data page fault vector */
    .org 0x300
_data_page_fault:
    l.nop
    l.j _data_page_fault
    l.nop

/* Instruction page fault vector */
    .org 0x400
_insn_page_fault:
    l.nop
    l.j _insn_page_fault
    l.nop

/* Tick timer vector */
    .org 0x500
_tick_timer:
    l.nop
    l.j _tick_timer
    l.nop

/* Alignment vector */
    .org 0x600
_alignment:
    l.nop
    l.j _alignment
    l.nop

/* Illegal instruction vector */
    .org 0x700
_illegal_insn:
    l.nop
    l.j _illegal_insn
    l.nop

/* External interrupt vector */
    .org 0x800
_external_interrupt:
    l.nop
    l.j _external_interrupt
    l.nop

/* DTLB miss vector */
    .org 0x900
_dtlb_miss:
    l.nop
    l.j _dtlb_miss
    l.nop

/* ITLB miss vector */
    .org 0xA00
_itlb_miss:
    l.nop
    l.j _itlb_miss
    l.nop

/* Range exception vector */
    .org 0xB00
_range:
    l.nop
    l.j _range
    l.nop

/* System call vector */
    .org 0xC00
_syscall:
    l.nop
    l.j _syscall
    l.nop

/* Floating point vector */
    .org 0xD00
_float:
    l.nop
    l.j _float
    l.nop

/* Trap vector */
    .org 0xE00
_trap:
    l.nop
    l.j _trap
    l.nop
