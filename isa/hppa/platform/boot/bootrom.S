/* HPPA Linux Boot Stub — runs at physical address 0x1000
 *
 * This minimal boot stub initializes Page Zero (the PA-RISC firmware
 * interface), sets up CPU state expected by Linux, and jumps to the kernel.
 *
 * Linux kernel entry (arch/parisc/kernel/head.S:startup_continue) expects:
 *   r26 (arg0) = PDC entry point
 *   r25 (arg1) = FDT (device tree) pointer
 *   r24 (arg2) = initrd end (0 if none)
 *   r23 (arg3) = initrd start (0 if none)
 *   PSW.C=0, PSW.D=0 — flat physical address space
 *
 * ISAComp HPPA SoC constants:
 *   PDC firmware    = 0x0F000000 (ROM, outside 64MB RAM)
 *   IODC firmware   = 0x0F000400
 *   UART (NS16550A) = 0x03F00000
 *   RAM             = 64 MB (0x04000000)
 *   Kernel load     = 0x00100000
 *   FDT             = 0x00000800
 *   CPU HPA         = 0xFFFA0000
 *
 * Page Zero layout (struct zeropage from pdc.h):
 *   0x028: memc_phsize   — physical memory size
 *   0x030: mem_pdc       — PDC entry point
 *   0x034: mem_hpa       — HPA of monarch processor
 *   0x038: mem_free      — first free PA after firmware
 *   0x040: imm_hpa_str   — "SeaBIOS\0" firmware ID
 *   0x388: mem_pdc copy  — also used by common_stext
 *   0x38C: mem_10msec    — clock ticks in 10ms (for CR16 timer)
 *   0x390: imm_hpa       — HPA of initial memory module
 *   0x398: imm_spa_size  — SPA size of IMM
 *   0x39C: imm_max_mem   — bytes of memory
 *
 * struct pz_device (48 bytes):
 *   +0x00: dp            — pdc_module_path (32 bytes)
 *   +0x20: hpa           — hardware physical address
 *   +0x24: spa           — SPA address
 *   +0x28: iodc_io       — IODC entry point
 *   +0x2C: pad + cl_class
 *
 * mem_cons at 0x3A0:  hpa=0x3C0, spa=0x3C4, iodc_io=0x3C8, class=0x3CC
 * mem_boot at 0x3D0:  hpa=0x3F0, spa=0x3F4, iodc_io=0x3F8, class=0x3FC
 * mem_kbd  at 0x400:  hpa=0x420, spa=0x424, iodc_io=0x428, class=0x42C
 *
 * Build:
 *   hppa-linux-gnu-as -o bootrom.o bootrom.S
 *   hppa-linux-gnu-ld -Ttext=0x1000 -o bootrom.elf bootrom.o
 *   hppa-linux-gnu-objcopy -O binary bootrom.elf bootrom.bin
 */

	.section .text
	.global _start
_start:
	/* =============================================
	 * CPU initialization
	 * ============================================= */

	/* Disable all interruptions (clear PSW I, D, P, Q bits) */
	rsm	0x1b, %r0

	/* Clear all space registers (flat physical address space) */
	mtsp	%r0, %sr0
	mtsp	%r0, %sr1
	mtsp	%r0, %sr2
	mtsp	%r0, %sr3
	mtsp	%r0, %sr4
	mtsp	%r0, %sr5
	mtsp	%r0, %sr6
	mtsp	%r0, %sr7

	/* Set IVA (CR14) = 0; Linux will install its own IVA on startup */
	mtctl	%r0, %cr14

	/* =============================================
	 * Page Zero initialization
	 * ============================================= */

	/* memc_phsize (0x028): physical memory size = 64 MB = 0x04000000 */
	ldil	L%0x04000000, %r1
	ldo	R%0x04000000(%r1), %r1
	stw	%r1, 0x028(%r0)

	/* mem_pdc (0x030): PDC firmware entry = 0x0F000000 (ROM, outside 64MB RAM) */
	ldil	L%0x0F000000, %r1
	ldo	R%0x0F000000(%r1), %r1
	stw	%r1, 0x030(%r0)
	stw	%r1, 0x388(%r0)		/* copy at 0x388 for common_stext */

	/* mem_hpa (0x034): HPA of monarch processor = 0xFFFA0000 */
	ldil	L%0xFFFA0000, %r1
	ldo	R%0xFFFA0000(%r1), %r1
	stw	%r1, 0x034(%r0)

	/* mem_free (0x038): first free PA after firmware = 0x200000 */
	ldil	L%0x00200000, %r1
	ldo	R%0x00200000(%r1), %r1
	stw	%r1, 0x038(%r0)

	/* "SeaBIOS\0" firmware ID at 0x040 */
	ldil	L%0x53656142, %r1	/* "SeaB" */
	ldo	R%0x53656142(%r1), %r1
	stw	%r1, 0x040(%r0)
	ldil	L%0x494F5300, %r1	/* "IOS\0" */
	ldo	R%0x494F5300(%r1), %r1
	stw	%r1, 0x044(%r0)

	/* mem_10msec (0x38C): clock ticks in 10ms = 2,500,000 (250 MHz) */
	ldil	L%0x002625A0, %r1
	ldo	R%0x002625A0(%r1), %r1
	stw	%r1, 0x38C(%r0)

	/* imm_hpa (0x390) = 0 */
	stw	%r0, 0x390(%r0)

	/* imm_spa_size (0x398) and imm_max_mem (0x39C) = 63 MB
	 * UART is mapped at 0x03F00000, so RAM must end before that. */
	ldil	L%0x03F00000, %r1
	ldo	R%0x03F00000(%r1), %r1
	stw	%r1, 0x398(%r0)
	stw	%r1, 0x39C(%r0)

	/* ---- mem_cons (0x3A0): console device ---- */
	/* mem_cons.hpa (0x3C0) = UART at 0x03F00000 */
	ldil	L%0x03F00000, %r1
	ldo	R%0x03F00000(%r1), %r1
	stw	%r1, 0x3C0(%r0)
	/* mem_cons.spa (0x3C4) = 0 */
	stw	%r0, 0x3C4(%r0)
	/* mem_cons.iodc_io (0x3C8) = IODC entry at 0x0F000400 (ROM) */
	ldil	L%0x0F000400, %r1
	ldo	R%0x0F000400(%r1), %r1
	stw	%r1, 0x3C8(%r0)
	/* mem_cons.cl_class (0x3CC) = CL_DUPLEX (7) */
	ldi	7, %r1
	stw	%r1, 0x3CC(%r0)

	/* ---- mem_kbd (0x400): no keyboard ---- */
	stw	%r0, 0x420(%r0)		/* mem_kbd.hpa = 0 */
	stw	%r0, 0x428(%r0)		/* mem_kbd.iodc_io = 0 */

	/* =============================================
	 * Set up Block TLB (BTLB) for kernel equivalent mapping
	 * =============================================
	 * BTLB entry 0: covers 64MB at VA 0x10000000 → PA 0x00000000
	 *   type = I+D (0b11), slot = 0
	 * This provides permanent translation for the kernel equivalent
	 * mapping region (PAGE_OFFSET = 0x10000000). The kernel's TLB miss
	 * handler runs in physical mode but re-enters virtual mode via RFI,
	 * which requires BTLB to translate kernel code/data addresses.
	 *
	 * DIAG BTLB_INSERT encoding (opcode 0x05, sub-op 0x01):
	 *   bits[25:21] = r1 (VA base), bits[20:16] = r2 (PA base)
	 *   bits[15:11] = r3 (mask),    bits[10:6]  = r4 (params)
	 *   bits[5:0]   = 000001
	 *
	 * We use r1=VA, r8=PA, r9=mask, r16=params to match DIAG encoding.
	 */

	/* r1 = VA base = 0x10000000 (page-aligned, masked with page_mask) */
	ldil	L%0x10000000, %r1
	ldo	R%0x10000000(%r1), %r1

	/* r8 = PA base = 0x00000000 */
	copy	%r0, %r8

	/* r9 = page mask = 0xFC000000 (64MB: top 6 bits must match) */
	ldil	L%0xFC000000, %r9
	ldo	R%0xFC000000(%r9), %r9

	/* r16 = packed params: space[31:16]=0, slot[4:2]=0, type[1:0]=11 (I+D) */
	ldi	3, %r16

	/* Execute DIAG BTLB_INSERT r1,r8,r9,r16
	 * Encoding: 000101 | r1(00001) | r8(01000) | r9(01001) | r16(10000) | 000001
	 * = 000101_00001_01000_01001_10000_000001
	 * Binary → hex:
	 *   0001 0100 0010 1000 0100 1100 0000 0001
	 *   = 0x1428_4C01 */
	.word	0x14284C01

	/* =============================================
	 * Jump to Linux kernel
	 * ============================================= */

	/* r26 = PDC entry point = 0x0F000000 (ROM) */
	ldil	L%0x0F000000, %r26
	ldo	R%0x0F000000(%r26), %r26

	/* r25 = FDT pointer = 0x800 */
	ldil	L%0x00000800, %r25
	ldo	R%0x00000800(%r25), %r25

	/* r24, r23 = no initrd */
	copy	%r0, %r24
	copy	%r0, %r23

	/* Jump to kernel at 0x100000 */
	ldil	L%0x00100000, %r1
	ldo	R%0x00100000(%r1), %r1
	bv	%r0(%r1)
	nop
