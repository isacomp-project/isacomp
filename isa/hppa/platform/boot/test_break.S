/* HPPA Minimal BREAK/Trap Test
 * Loads at physical address 0x100000
 *
 * Test sequence:
 *   1. Set IVA (CR14) = 0x100100 (our trap handler table)
 *   2. Execute BREAK 0,0 → trap 9
 *   3. CPU redirects to CR14 + (9*32) = 0x100100 + 0x120 = 0x100220
 *   4. Trap handler at 0x100220 writes 'TRAP\n' to UART and halts
 *
 * Memory map:
 *   0x100000 = _start (main program)
 *   0x100100 = trap handler table base (IVA = 0x100100)
 *   0x100220 = trap 9 handler (0x100100 + 9*32 = 0x100100 + 0x120)
 *
 * UART: 16550 at 0x03f00000, byte writes to offset 0 (THR)
 */

	.section .text
	.global _start

/* ================================================================
 * _start: runs at 0x100000
 * ================================================================ */
_start:
	/* Set IVA (CR14) = 0x100100 */
	ldil	L%0x100100, %r1
	ldo	R%0x100100(%r1), %r1
	mtctl	%r1, %cr14

	/* Enable PSW.Q via SSM so trap saves state correctly */
	ssm	8, %r0

	/* Execute BREAK 0,0 → trap 9 (break instruction) */
	.word	0x00000000		/* BREAK 0,0: op=0x00, func=0x00 */

	/* Should NOT reach here - if we do, write 'F' (fail) to UART */
	ldil	L%0x03f00000, %r1
	ldo	R%0x03f00000(%r1), %r1
	ldi	70, %r2			/* 'F' */
	stb	%r2, 0(%r1)
	b	.
	nop

/* ================================================================
 * Pad to 0x100100 = trap handler table base
 * ================================================================ */
	.org	0x100
trap_table:

/* Traps 0-8: 9 * 32 bytes = 0x120 bytes of stubs */
trap0: b . ; nop ; .space 24
trap1: b . ; nop ; .space 24
trap2: b . ; nop ; .space 24
trap3: b . ; nop ; .space 24
trap4: b . ; nop ; .space 24
trap5: b . ; nop ; .space 24
trap6: b . ; nop ; .space 24
trap7: b . ; nop ; .space 24
trap8: b . ; nop ; .space 24

/* ================================================================
 * Trap 9 handler at offset 0x120 from IVA = 0x100220
 * ================================================================ */
	.org	(0x100 + 0x120)
trap9_handler:
	/* Write 'T' 'R' 'A' 'P' '\n' to UART */
	ldil	L%0x03f00000, %r1
	ldo	R%0x03f00000(%r1), %r1
	ldi	84, %r2			/* 'T' */
	stb	%r2, 0(%r1)
	ldi	82, %r2			/* 'R' */
	stb	%r2, 0(%r1)
	ldi	65, %r2			/* 'A' */
	stb	%r2, 0(%r1)
	ldi	80, %r2			/* 'P' */
	stb	%r2, 0(%r1)
	ldi	10, %r2			/* newline */
	stb	%r2, 0(%r1)
	/* Halt */
	b	.
	nop
