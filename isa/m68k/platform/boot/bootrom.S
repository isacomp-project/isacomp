/* M68K Boot ROM for ISAComp Linux Boot
 *
 * Sets up the processor for Linux boot:
 * 1. Initialize exception vectors
 * 2. Set up VBR (for 68010+)
 * 3. Set up A0 to point to bootinfo records
 * 4. Jump to kernel entry point at _stext (0x1000)
 *
 * Memory layout:
 *   0x00000000 - 0x000003FF: Exception vectors (1KB)
 *   0x00000400 - 0x000004FF: Boot ROM code
 *   0x00000500 - 0x000007FF: Bootinfo records
 *   0x00001000: Kernel _stext
 *
 * M68K Linux boot protocol:
 *   - A0 points to bootinfo records (bi_record array)
 *   - Bootinfo provides: machtype, cputype, fputype, mmutype, memchunk, cmdline
 *   - Kernel reads these to configure itself
 *
 * M68K Reset Sequence:
 *   - SSP loaded from 0x00000000
 *   - PC loaded from 0x00000004
 *   - Supervisor mode, all interrupts masked (SR = 0x2700)
 */

    .text
    .global _vectors
    .global _start

/* Bootinfo record tags (from asm/bootinfo.h) */
    .equ BI_LAST,         0x0000
    .equ BI_MACHTYPE,     0x0001
    .equ BI_CPUTYPE,      0x0002
    .equ BI_FPUTYPE,      0x0003
    .equ BI_MMUTYPE,      0x0004
    .equ BI_MEMCHUNK,     0x0005
    .equ BI_COMMAND_LINE, 0x0007

/* Machine type */
    .equ MACH_ISACOMP,    15

/* CPU types (bit masks) */
    .equ CPU_68030,       0x02
    .equ CPU_68040,       0x04

/* FPU types */
    .equ FPU_68882,       0x02

/* MMU types */
    .equ MMU_68030,       0x02
    .equ MMU_68040,       0x04

/* Memory */
    .equ RAM_BASE,        0x00000000
    .equ RAM_SIZE,        0x04000000

/* Exception Vector Table (1KB at address 0) */
    .section .vectors, "ax"
_vectors:
    .long   0x03FFFFF0          /* 0: Initial SSP (top of 64MB RAM) */
    .long   _boot_entry         /* 1: Initial PC (reset vector) */
    .long   _bus_error          /* 2: Bus Error */
    .long   _address_error      /* 3: Address Error */
    .long   _illegal_instr      /* 4: Illegal Instruction */
    .long   _zero_divide        /* 5: Zero Divide */
    .long   _chk_instr          /* 6: CHK Instruction */
    .long   _trapv_instr        /* 7: TRAPV Instruction */
    .long   _privilege_viol     /* 8: Privilege Violation */
    .long   _trace              /* 9: Trace */
    .long   _line_1010          /* 10: Line 1010 Emulator */
    .long   _line_1111          /* 11: Line 1111 Emulator */
    .long   _reserved           /* 12: Reserved */
    .long   _coproc_viol        /* 13: Coprocessor Protocol Violation */
    .long   _format_error       /* 14: Format Error */
    .long   _uninit_int         /* 15: Uninitialized Interrupt */

    /* Vectors 16-23: Reserved */
    .rept 8
    .long   _reserved
    .endr

    /* Vector 24: Spurious Interrupt */
    .long   _spurious_int

    /* Vectors 25-31: Autovector Interrupts (Level 1-7) */
    .long   _autovec_1          /* 25: Level 1 */
    .long   _autovec_2          /* 26: Level 2 */
    .long   _autovec_3          /* 27: Level 3 */
    .long   _autovec_4          /* 28: Level 4 */
    .long   _autovec_5          /* 29: Level 5 */
    .long   _autovec_6          /* 30: Level 6 */
    .long   _autovec_7          /* 31: Level 7 (NMI) */

    /* Vectors 32-47: TRAP #0-15 */
    .rept 16
    .long   _trap_handler
    .endr

    /* Vectors 48-63: Reserved */
    .rept 16
    .long   _reserved
    .endr

    /* Vectors 64-255: User Interrupt Vectors */
    .rept 192
    .long   _user_interrupt
    .endr

/* Boot ROM Code Section */
    .section .text.boot, "ax"
    .align 4

_boot_entry:
    /* Disable interrupts and enter supervisor mode */
    move.w  #0x2700, %sr

    /* Set up VBR to point to our vector table (68010+ only) */
    lea.l   _vectors, %a0
    movec   %a0, %vbr

    /* Set up stack pointer at top of RAM */
    lea.l   0x03FFFFF0, %sp

    /* Set A0 to point to bootinfo records at _end.
     * The kernel's setup_arch reads bootinfo from _end.
     * The bootinfo data is placed there by gen_hex.py during image creation.
     * Must match _end from linux/System.map. */
    lea.l   0x001ae000, %a0

    /* Clear other registers */
    moveq   #0, %d0
    moveq   #0, %d1
    moveq   #0, %d2
    moveq   #0, %d3
    moveq   #0, %d4
    moveq   #0, %d5
    moveq   #0, %d6
    moveq   #0, %d7
    move.l  %d0, %a1
    move.l  %d0, %a2
    move.l  %d0, %a3
    move.l  %d0, %a4
    move.l  %d0, %a5
    move.l  %d0, %a6

    /* Jump to kernel _stext at 0x1000 */
    jmp     0x00001000

/* Exception Handlers (minimal stubs that halt) */
    .align 4
_bus_error:
_address_error:
_illegal_instr:
_zero_divide:
_chk_instr:
_trapv_instr:
_privilege_viol:
_trace:
_line_1010:
_line_1111:
_reserved:
_coproc_viol:
_format_error:
_uninit_int:
_spurious_int:
    /* Print error character and halt */
    move.l  #0x10000104, %a0    /* UART TX address */
    move.b  #'!', (%a0)         /* Print '!' to indicate error */
_halt:
    stop    #0x2700             /* Halt with interrupts disabled */
    bra.s   _halt

/* Autovector interrupt handlers */
_autovec_1:
_autovec_2:
_autovec_3:
_autovec_4:
_autovec_5:
_autovec_6:
_autovec_7:
    rte

/* TRAP handler */
_trap_handler:
    rte

/* User interrupt handler */
_user_interrupt:
    rte

/* =========================================================================
 * Bootinfo Records
 * Format: struct bi_record { __be16 tag; __be16 size; __be32 data[]; }
 * Size includes the 4-byte header (tag + size fields)
 * Size must be a multiple of 4 bytes
 * ========================================================================= */
    .section .bootinfo, "a"
    .align 4
_bootinfo:
    /* BI_MACHTYPE: machine type = MACH_ISACOMP (15) */
    .short  BI_MACHTYPE         /* tag = 0x0001 */
    .short  8                   /* size = 4 (header) + 4 (data) = 8 */
    .long   MACH_ISACOMP        /* data = 15 */

    /* BI_CPUTYPE: CPU_68030 (ISA is 68030-class with PMOVE-based MMU) */
    .short  BI_CPUTYPE          /* tag = 0x0002 */
    .short  8                   /* size = 8 */
    .long   CPU_68030           /* data = 0x02 */

    /* BI_FPUTYPE: FPU_68882 (for emulation compatibility) */
    .short  BI_FPUTYPE          /* tag = 0x0003 */
    .short  8                   /* size = 8 */
    .long   FPU_68882           /* data = 0x02 */

    /* BI_MMUTYPE: MMU_68030 (PMOVE-based ATC with TT0/TT1) */
    .short  BI_MMUTYPE          /* tag = 0x0004 */
    .short  8                   /* size = 8 */
    .long   MMU_68030           /* data = 0x02 */

    /* BI_MEMCHUNK: memory at 0x00000000, size 64MB */
    .short  BI_MEMCHUNK         /* tag = 0x0005 */
    .short  12                  /* size = 4 (header) + 8 (two longs) = 12 */
    .long   RAM_BASE            /* start = 0x00000000 */
    .long   RAM_SIZE            /* size = 0x04000000 */

    /* BI_COMMAND_LINE: kernel parameters */
    .short  BI_COMMAND_LINE     /* tag = 0x0007 */
    .short  20                  /* size = 4 + 16 (string + pad) = 20 */
    .ascii  "console=ttyGF0"
    .byte   0                   /* null terminator */
    /* Pad to make record size a multiple of 4 */
    .balign 4, 0

    /* BI_LAST: end of records */
    .short  BI_LAST             /* tag = 0x0000 */
    .short  4                   /* size = 4 (header only) */
