# Minimal /init for Alpha64 initramfs
# Uses PC-relative addressing - NO GP/GOT required.
#
# Strategy: `br $27, 1f` stores the address of the next sequential instruction
# (= &hello_msg) into $27 and jumps over the string data to 1:. The string
# address is then available directly as $27 without any TLB/page table
# access to a separate data segment or GOT.
#
# Alpha Linux syscall ABI:
#   v0  ($0)  = syscall number
#   a0-a5 ($16-$21) = arguments
#   call_pal 0x83 = callsys (PAL_callsys)
#
# Build: alpha-linux-gnu-gcc -nostdlib -static -o init init.S && alpha-linux-gnu-strip init

#include <asm/pal.h>
#include <asm/unistd.h>

	.set noat
	.set noreorder

	.text
	.globl _start
	.ent _start
_start:
	# Branch over the string data.
	# $27 = address of the instruction after this br = &hello_msg
	br	$27, 1f

	# ---- String data (in code segment, skipped by the br above) ----
hello_msg:
	.ascii	"\n\n=== Hello from Alpha64 ISAComp userspace! ===\n\n"
	.equ	hello_len, . - hello_msg
	.align	2		# pad to 4-byte boundary for instructions

	# ----------------------------------------------------------------
1:	# $27 = &hello_msg (set by the br above)

	# write(1, hello_msg, hello_len)
	lda	$0, __NR_write($31)	# syscall number
	lda	$16, 1($31)		# fd = STDOUT_FILENO
	lda	$17, 0($27)		# a1 = &hello_msg (mov $27 -> $17)
	lda	$18, hello_len($31)	# a2 = byte count
	call_pal PAL_callsys

	# Infinite sched_yield() loop keeps PID 1 alive
yield_loop:
	lda	$0, __NR_sched_yield($31)
	call_pal PAL_callsys
	br	$31, yield_loop

	.end _start
