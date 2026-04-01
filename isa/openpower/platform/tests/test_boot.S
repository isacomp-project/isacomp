/*
 * OpenPOWER ISAComp Minimal Boot Test
 * ====================================
 * Tests basic CPU operation by writing "Hello from ISAComp OpenPOWER!\n"
 * to the UART at 0xC0002000.
 *
 * This is a raw big-endian PowerPC64 program loaded at address 0.
 * No boot wrapper, no endian swap needed - just raw big-endian instructions.
 *
 * UART 16550 register layout (Microwatt-compatible, reg-shift=2):
 *   base+0x00: THR (Transmit Holding Register, write)
 *   base+0x14: LSR (Line Status Register, read)
 *     bit 5: THRE (Transmitter Holding Register Empty)
 */

    .section .text.boot
    .globl _start

_start:
    /* Set up stack pointer (r1) at 1MB */
    lis     1, 0x0010       /* r1 = 0x00100000 */
    ori     1, 1, 0x0000

    /* Load UART base address into r3 */
    lis     3, 0xC000       /* r3 = 0xC0002000 */
    ori     3, 3, 0x2000

    /* Load message pointer into r4 */
    bl      1f
1:  mflr    4
    addi    4, 4, (message - 1b)

    /* Print loop */
print_loop:
    lbz     5, 0(4)         /* Load byte from message */
    cmpwi   5, 0            /* Check for null terminator */
    beq     done

    /* Wait for UART TX ready (LSR bit 5) */
wait_tx:
    lbz     6, 0x14(3)      /* Read LSR (reg 5 * 4 = 0x14) */
    andi.   7, 6, 0x20      /* Check THRE bit */
    beq     wait_tx

    /* Write character to UART THR */
    stb     5, 0(3)         /* Write char to THR */

    addi    4, 4, 1         /* Next character */
    b       print_loop

done:
    /* Spin loop - done */
    b       done

    .section .rodata
message:
    .ascii  "Hello from ISAComp OpenPOWER!\r\n"
    .byte   0
