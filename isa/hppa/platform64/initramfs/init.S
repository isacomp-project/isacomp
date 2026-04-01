/* Minimal /init for HPPA Linux boot test
 * Writes "Hello from HPPA userspace!" then exits
 * Statically linked, no libc dependency
 *
 * PA-RISC Linux syscall convention:
 *   Syscall number in %r20
 *   Arguments in %r26, %r25, %r24, %r23
 *   Return value in %r28
 *   Invoked via: ble 0x100(%sr2, %r0)
 *                ldi NR, %r20        (in delay slot)
 */

#define __NR_exit   1
#define __NR_write  4

	.text
	.globl _start
	.type _start, @function

_start:
	/* write(1, msg, count) — stdout (fd 1 = kernel console) */
	ldi	1, %r26			/* arg0: fd = STDOUT_FILENO */
	ldil	L%msg, %r25
	ldo	R%msg(%r25), %r25	/* arg1: buf = &msg */
	ldi	msg_end - msg, %r24	/* arg2: count */
	ble	0x100(%sr2, %r0)
	ldi	__NR_write, %r20	/* delay slot: syscall number */

	/* exit(42) — should cause kernel panic */
	ldi	42, %r26		/* arg0: exit code */
	ble	0x100(%sr2, %r0)
	ldi	__NR_exit, %r20		/* delay slot: syscall number */

	/* Should not reach here */
	b,n	.
	nop

	.section .rodata
msg:
	.ascii	"Hello from HPPA userspace!\n"
msg_end:
