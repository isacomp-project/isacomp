/* Minimal /init for HPPA Linux boot test
 * Writes "Hello from HPPA userspace!" and loops forever
 * Statically linked, no libc dependency
 *
 * PA-RISC Linux syscall convention:
 *   Syscall number in %r20
 *   Arguments in %r26, %r25, %r24, %r23
 *   Return value in %r28
 *   Invoked via: ble 0x100(%sr2, %r0)
 *                ldi NR, %r20        (in delay slot)
 *
 * Note: ble saves r31 = addr(delay_slot). The kernel gateway page
 * returns to r31 via be,n, so the delay slot instruction (ldi) executes
 * twice: once as the delay slot, and once on return. This is harmless.
 */

#define __NR_write  4
#define __NR_open   5
#define __NR_close  6
#define __NR_pause  29

	.text
	.globl _start
	.type _start, @function

_start:
	/* write(1, msg, 27) — stdout */
	ldi	1, %r26			/* arg0: fd = STDOUT_FILENO */
	ldil	L%msg, %r25
	ldo	R%msg(%r25), %r25	/* arg1: buf = &msg */
	ldi	msg_end - msg, %r24	/* arg2: count */
	ble	0x100(%sr2, %r0)
	ldi	__NR_write, %r20	/* delay slot: syscall number */

	/* open("/dev/kmsg", O_WRONLY, 0) */
	ldil	L%kmsg_path, %r26
	ldo	R%kmsg_path(%r26), %r26	/* arg0: pathname */
	ldi	1, %r25			/* arg1: O_WRONLY */
	ldi	0, %r24			/* arg2: mode */
	ble	0x100(%sr2, %r0)
	ldi	__NR_open, %r20		/* delay slot: syscall number */

	/* write(kmsg_fd, msg, 27) */
	copy	%r28, %r26		/* arg0: fd from open return */
	ldil	L%kmsg_msg, %r25
	ldo	R%kmsg_msg(%r25), %r25	/* arg1: buf (with syslog prefix) */
	ldi	kmsg_msg_end - kmsg_msg, %r24	/* arg2: count */
	ble	0x100(%sr2, %r0)
	ldi	__NR_write, %r20	/* delay slot: syscall number */

	/* Loop: pause() forever */
.Lloop:
	ble	0x100(%sr2, %r0)
	ldi	__NR_pause, %r20	/* delay slot: syscall number */
	b,n	.Lloop
	nop				/* nullified delay slot */

	.section .rodata
kmsg_path:
	.asciz	"/dev/kmsg"
	.align	4
msg:
	.ascii	"Hello from HPPA userspace!\n"
msg_end:
	.align	4
kmsg_msg:
	.ascii	"<6>Hello from HPPA userspace!\n"
kmsg_msg_end:
