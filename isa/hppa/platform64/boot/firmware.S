/* HPPA 2.0 PDC/IODC Firmware — runs at physical address 0x80000
 *
 * Two entry points:
 *   0x0F000000 — PDC entry (processor-dependent code)
 *   0x0F000400 — IODC entry (I/O-dependent code, console I/O)
 *
 * Calling convention:
 *   Running in physical mode (PSW.C=0, PSW.D=0)
 *   r26 = arg0, r25 = arg1, r24 = arg2, r23 = arg3
 *   Stack args: sp-52=arg4, sp-56=arg5, sp-60=arg6, sp-64=arg7
 *   r2  = return address
 *   Return: bv %r0(%r2), result in r28
 *
 * PDC class numbers (from linux/arch/parisc/include/uapi/asm/pdc.h):
 *   PDC_CHASSIS=2, PDC_MODEL=4, PDC_CACHE=5,
 *   PDC_COPROC=7, PDC_IODC=8, PDC_SYSTEM_MAP=22, PDC_PSW=21
 */

	.section .text
	.global _start

_start:
pdc_entry:
	/* Dispatch on r26 (PDC class number) */

	/* PDC_CHASSIS (2) */
	ldi	2, %r1
	comb,=	%r1, %r26, pdc_chassis
	nop

	/* PDC_MODEL (4) */
	ldi	4, %r1
	comb,=	%r1, %r26, pdc_model
	nop

	/* PDC_CACHE (5) */
	ldi	5, %r1
	comb,=	%r1, %r26, pdc_cache
	nop

	/* PDC_COPROC (7) */
	ldi	7, %r1
	comb,=	%r1, %r26, pdc_coproc
	nop

	/* PDC_IODC (8) */
	ldi	8, %r1
	comb,=	%r1, %r26, pdc_iodc
	nop

	/* PDC_SYSTEM_MAP (22) */
	ldi	22, %r1
	comb,=	%r1, %r26, pdc_system_map
	nop

	/* PDC_ADD_VALID (12) */
	ldi	12, %r1
	comb,=	%r1, %r26, pdc_add_valid
	nop

	/* PDC_BLOCK_TLB (18) */
	ldi	18, %r1
	comb,=	%r1, %r26, pdc_btlb
	nop

	/* PDC_TLB (19) */
	ldi	19, %r1
	comb,=	%r1, %r26, pdc_tlb
	nop

	/* PDC_MEM (20) */
	ldi	20, %r1
	comb,=	%r1, %r26, pdc_mem
	nop

	/* PDC_PSW (21) */
	ldi	21, %r1
	comb,=	%r1, %r26, pdc_psw
	nop

	/* Default: PDC_BAD_PROC (-1) */
	ldi	-1, %r28
	bv	%r0(%r2)
	nop

/* PDC_CHASSIS (class 2): Return PDC_OK */
pdc_chassis:
	ldi	0, %r28
	bv	%r0(%r2)
	nop

/* PDC_MODEL (class 4): Write minimal model info
 * Key difference for PA-RISC 2.0: arch_rev = 8 (not 4)
 * hversion = 0x6000 → bus_id=0xC (Snake type, like HP 715/64)
 * Sub-options: r25=0 (INFO), r25=7 (CAPABILITIES) */
pdc_model:
	/* r25=7: PDC_MODEL_CAPABILITIES — return OS32 (narrow firmware) */
	ldi	7, %r1
	comb,=,n %r1, %r25, pdc_model_caps
	nop
	/* r25!=0 and r25!=7: unknown sub-option, skip data write */
	comb,<>,n %r0, %r25, pdc_model_ret
	nop

	/* r25=0: PDC_MODEL_INFO */
	/* hversion=0x6000 → bus_id = (0x6000>>11) & 0x1f = 0x0C (Snake) */
	ldil	L%0x6000, %r1
	ldo	R%0x6000(%r1), %r1
	stw	%r1, 0(%r24)		/* hversion = 0x6000 */
	stw	%r0, 4(%r24)		/* sversion = 0 */
	stw	%r0, 8(%r24)		/* hw_id = 0 */
	stw	%r0, 12(%r24)		/* boot_id = 0 */
	stw	%r0, 16(%r24)		/* sw_id = 0 */
	stw	%r0, 20(%r24)		/* sw_cap = 0 */
	ldi	8, %r1
	stw	%r1, 24(%r24)		/* arch_rev = 8 (PA-RISC 2.0) */
	stw	%r0, 28(%r24)		/* pot_key = 0 */
	stw	%r0, 32(%r24)		/* curr_key = 0 */
	b	pdc_model_ret
	nop

/* PDC_MODEL_CAPABILITIES (sub 7): Tell kernel we are narrow (32-bit) firmware.
 * PDC_MODEL_OS32 = 2, PDC_MODEL_OS64 = 1.
 * Kernel uses this to decide real32_call vs real64_call for PDC. */
pdc_model_caps:
	ldi	2, %r1			/* PDC_MODEL_OS32 */
	stw	%r1, 0(%r24)

pdc_model_ret:
	ldi	0, %r28
	bv	%r0(%r2)
	nop

/* PDC_CACHE (class 5): Return cache info */
pdc_cache:
	/* Sub-option dispatch: R25 = option */
	/* PDC_CACHE_RET_SPID (R25=2): return space_bits=0 (no hashing) */
	ldi	2, %r1
	comb,=	%r1, %r25, pdc_cache_ret_spid
	nop

	/* PDC_CACHE_INFO (R25=0): fall through to cache info */
	/* Zero 64 words (256 bytes) first */
	ldi	64, %r1
	copy	%r24, %r20
pdc_cache_loop:
	stw	%r0, 0(%r20)
	addib,<>	-1, %r1, pdc_cache_loop
	ldo	4(%r20), %r20

	/* I-cache: 1KB, stride=32, count=32, loop=1 */
	ldil	L%0x400, %r1
	ldo	R%0x400(%r1), %r1
	stw	%r1, 0(%r24)		/* ic_size = 1024 */

	ldil	L%0x41402000, %r1
	ldo	R%0x41402000(%r1), %r1
	stw	%r1, 4(%r24)		/* ic_conf (cc_wt=1) */

	ldi	32, %r1
	stw	%r1, 12(%r24)		/* ic_stride = 32 */
	stw	%r1, 16(%r24)		/* ic_count = 32 */
	ldi	1, %r1
	stw	%r1, 20(%r24)		/* ic_loop = 1 */

	/* D-cache: 1KB, stride=32, count=32, loop=1 */
	ldil	L%0x400, %r1
	ldo	R%0x400(%r1), %r1
	stw	%r1, 24(%r24)		/* dc_size = 1024 */

	ldil	L%0x41402000, %r1
	ldo	R%0x41402000(%r1), %r1
	stw	%r1, 28(%r24)		/* dc_conf (cc_wt=1) */

	ldi	32, %r1
	stw	%r1, 36(%r24)		/* dc_stride = 32 */
	stw	%r1, 40(%r24)		/* dc_count = 32 */
	ldi	1, %r1
	stw	%r1, 44(%r24)		/* dc_loop = 1 */

	/* I-TLB: 120 entries */
	ldi	120, %r1
	stw	%r1, 48(%r24)		/* it_size = 120 */

	/* D-TLB: 120 entries */
	stw	%r1, 84(%r24)		/* dt_size = 120 */

	ldi	0, %r28
	bv	%r0(%r2)
	nop

/* PDC_CACHE_RET_SPID (sub-option 2): Return space ID bits = 0 (hashing disabled) */
pdc_cache_ret_spid:
	stw	%r0, 0(%r24)		/* space_bits = 0 */
	ldi	0, %r28			/* success */
	bv	%r0(%r2)
	nop

/* PDC_COPROC (class 7): FPU present */
pdc_coproc:
	ldi	20, %r1
	copy	%r24, %r20
pdc_coproc_zero:
	stw	%r0, 0(%r20)
	addib,<>	-1, %r1, pdc_coproc_zero
	ldo	4(%r20), %r20

	ldil	L%0xC0000000, %r1
	stw	%r1, 0(%r24)		/* ccr_functional */
	stw	%r1, 4(%r24)		/* ccr_present */

	ldi	1, %r1
	stw	%r1, 68(%r24)		/* revision = 1 */
	stw	%r1, 72(%r24)		/* model = 1 */

	ldi	0, %r28
	bv	%r0(%r2)
	nop

/* PDC_IODC (class 8): IODC operations */
pdc_iodc:
	comb,<>,n %r0, %r25, pdc_iodc_err
	nop

	ldw	-52(%r30), %r20		/* r20 = index */
	comb,<>,n %r0, %r20, pdc_iodc_err
	nop

	ldil	L%0x03F00000, %r1
	ldo	R%0x03F00000(%r1), %r1
	comb,<>,n %r1, %r23, pdc_iodc_err
	nop

	ldw	-56(%r30), %r20		/* r20 = iodc_data PA */

	stw	%r0, 0(%r20)
	stw	%r0, 4(%r20)
	stw	%r0, 8(%r20)
	stw	%r0, 12(%r20)
	stw	%r0, 16(%r20)
	stw	%r0, 20(%r20)
	stw	%r0, 24(%r20)
	stw	%r0, 28(%r20)

	ldil	L%0x08c0000a, %r1
	ldo	R%0x08c0000a(%r1), %r1
	stw	%r1, 0(%r20)

	ldil	L%0x00008d00, %r1
	ldo	R%0x00008d00(%r1), %r1
	stw	%r1, 4(%r20)

	ldi	32, %r1
	stw	%r1, 0(%r24)

	ldi	0, %r28
	bv	%r0(%r2)
	nop

pdc_iodc_err:
	ldi	-3, %r28
	bv	%r0(%r2)
	nop

/* PDC_SYSTEM_MAP (class 22): Device enumeration */
pdc_system_map:
	comb,<>,n %r0, %r25, pdc_sysmap_err
	nop

	ldw	-52(%r30), %r20
	comb,<>,n %r0, %r20, pdc_sysmap_err
	nop

	ldil	L%0x03F00000, %r1
	ldo	R%0x03F00000(%r1), %r1
	stw	%r1, 0(%r24)		/* mod_addr = UART HPA */
	ldi	1, %r1
	stw	%r1, 4(%r24)		/* mod_pgs = 1 */
	stw	%r0, 8(%r24)		/* add_addrs = 0 */

	stw	%r0, 0(%r23)
	stw	%r0, 4(%r23)

	ldi	0, %r28
	bv	%r0(%r2)
	nop

pdc_sysmap_err:
	ldi	-5, %r28
	bv	%r0(%r2)
	nop

/* PDC_ADD_VALID (class 12): Check if physical address is valid
 * r25 = physical address to check
 * Return 0 (valid) if within 64MB RAM, -3 (invalid) otherwise */
pdc_add_valid:
	ldil	L%0x04000000, %r1
	ldo	R%0x04000000(%r1), %r1
	comb,>>=,n %r1, %r25, pdc_add_valid_ok
	nop
	ldi	-3, %r28
	bv	%r0(%r2)
	nop
pdc_add_valid_ok:
	ldi	0, %r28
	bv	%r0(%r2)
	nop

/* PDC_BLOCK_TLB (class 18): Block TLB management
 * r25 = subcall: 0=INFO, 1=INSERT, 2=PURGE, 3=PURGE_ALL */
pdc_btlb:
	comb,=,n %r0, %r25, pdc_btlb_info
	nop
	ldi	3, %r1
	comb,=,n %r1, %r25, pdc_btlb_purge_all
	nop
	/* Subcalls 1 (INSERT) and 2 (PURGE): just return OK */
	ldi	0, %r28
	bv	%r0(%r2)
	nop

pdc_btlb_info:
	/* struct pdc_btlb_info written to r24:
	 * [0]  min_size = 1      (4KB min)
	 * [4]  max_size = 16384  (64MB max = 16384*4KB)
	 * [8]  fixed = 0
	 * [12] variable = 0
	 * [16] combined = 8      (8 combined BTLB entries)
	 * [20] finfo = 0
	 * [24] vinfo = 0 */
	ldi	1, %r1
	stw	%r1, 0(%r24)
	ldil	L%16384, %r1
	ldo	R%16384(%r1), %r1
	stw	%r1, 4(%r24)
	stw	%r0, 8(%r24)
	stw	%r0, 12(%r24)
	ldi	8, %r1
	stw	%r1, 16(%r24)
	stw	%r0, 20(%r24)
	stw	%r0, 24(%r24)
	ldi	0, %r28
	bv	%r0(%r2)
	nop

pdc_btlb_purge_all:
	/* Just return success — let the ISA hardware handle BTLB state */
	ldi	0, %r28
	bv	%r0(%r2)
	nop

/* PDC_TLB (class 19): TLB info
 * r25 = 0: return TLB info */
pdc_tlb:
	comb,<>,n %r0, %r25, pdc_tlb_ret
	nop
	/* min_size = 1 (4KB), max_size = 1 (4KB) */
	ldi	1, %r1
	stw	%r1, 0(%r24)
	stw	%r1, 4(%r24)
pdc_tlb_ret:
	ldi	0, %r28
	bv	%r0(%r2)
	nop

/* PDC_MEM (class 20): Memory/PDT management
 * We don't support Page Deallocation Table (PDT).
 * Memory discovery uses FDT instead.
 * Return PDC_BAD_OPTION (-2) for all sub-options. */
pdc_mem:
	ldi	-2, %r28
	bv	%r0(%r2)
	nop

/* PDC_PSW (class 21): PSW mask handling */
pdc_psw:
	comb,<>,n %r0, %r25, pdc_psw_ret
	nop

	/* Return endian + wide mask: PDC_PSW_ENDIAN_BIT | PDC_PSW_WIDE_BIT = 3 */
	ldi	3, %r1
	stw	%r1, 0(%r24)

pdc_psw_ret:
	ldi	0, %r28
	bv	%r0(%r2)
	nop

/* Padding to IODC entry at offset 0x400 */
	.org	0x400

/* IODC Entry Point — address 0x0F000400 */
iodc_entry:
	ldi	2, %r1
	comb,=	%r1, %r25, iodc_cin
	nop

	ldi	3, %r1
	comb,=	%r1, %r25, iodc_cout
	nop

	ldi	0, %r28
	bv	%r0(%r2)
	nop

iodc_cin:
	ldi	0, %r28
	bv	%r0(%r2)
	nop

iodc_cout:
	ldw	-60(%r30), %r20		/* buf_pa */
	ldw	-64(%r30), %r21		/* count */

	ldil	L%0x03F00000, %r22
	ldo	R%0x03F00000(%r22), %r22

	comb,=,n %r0, %r21, iodc_cout_done
	nop

	copy	%r21, %r28

iodc_cout_loop:
	ldb	0(%r20), %r1
	stb	%r1, 0(%r22)
	addib,<>	-1, %r21, iodc_cout_loop
	ldo	1(%r20), %r20

iodc_cout_done:
	ldw	-52(%r30), %r20
	stw	%r28, 0(%r20)

	bv	%r0(%r2)
	nop
