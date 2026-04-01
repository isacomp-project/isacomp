/* HPPA PDC/IODC Firmware — runs at physical address 0x80000
 *
 * Replaces Verilog testbench hacks with real PA-RISC code that executes
 * on the CPU itself.
 *
 * Two entry points:
 *   0x0F000000 — PDC entry (processor-dependent code)
 *   0x0F000400 — IODC entry (I/O-dependent code, console I/O)
 *
 * Calling convention (from real32_call_asm in kernel real2.S):
 *   Running in physical mode (PSW.C=0, PSW.D=0)
 *   r26 = arg0, r25 = arg1, r24 = arg2, r23 = arg3
 *   Stack args: sp-52=arg4, sp-56=arg5, sp-60=arg6, sp-64=arg7
 *   r2  = return address (physical addr of ric_ret in real2.S)
 *   Return: bv %r0(%r2), result in r28
 *
 * Data address translation note:
 *   All load/store ISA instructions translate via da_pa:
 *     da_pa = (psw[1] & (addr >= 0x10000000)) ? (addr - 0x10000000) : addr
 *   In physical mode (PSW.D=0), da_pa = addr (no translation).
 *   In virtual mode (PSW.D=1), da_pa = addr - PAGE_OFFSET.
 *   So firmware stores at PA and kernel reads at VA both access the same umem.
 *   No PAGE_OFFSET workaround needed.
 *
 * PDC class numbers (from linux/arch/parisc/include/uapi/asm/pdc.h):
 *   PDC_CHASSIS=2, PDC_MODEL=4, PDC_CACHE=5,
 *   PDC_COPROC=7, PDC_IODC=8, PDC_SYSTEM_MAP=22, PDC_PSW=21
 *
 * Build:
 *   hppa-linux-gnu-as -o firmware.o firmware.S
 *   hppa-linux-gnu-ld -Ttext=0x80000 -o firmware.elf firmware.o
 *   hppa-linux-gnu-objcopy -O binary firmware.elf firmware.bin
 */

	.section .text
	.global _start

/* ===================================================================
 * PDC Entry Point — address 0x80000
 * r26 = PDC class, r25 = PDC function, r24 = result buffer ptr (PA)
 * =================================================================== */
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

	/* PDC_PSW (21) */
	ldi	21, %r1
	comb,=	%r1, %r26, pdc_psw
	nop

	/* Default: PDC_BAD_PROC (-1) */
	ldi	-1, %r28
	bv	%r0(%r2)
	nop

/* -------------------------------------------------------------------
 * PDC_CHASSIS (class 2): Return PDC_OK
 * ------------------------------------------------------------------- */
pdc_chassis:
	ldi	0, %r28
	bv	%r0(%r2)
	nop

/* -------------------------------------------------------------------
 * PDC_MODEL (class 4): Write minimal model info to result buffer
 * r25 = subfunction (0=PDC_MODEL_INFO)
 * r24 = result buffer (PA)
 * struct pdc_model layout (each field is unsigned long = 4 bytes):
 *   [0]=hversion, [4]=sversion, [8]=hw_id, [12]=boot_id,
 *   [16]=sw_id, [20]=sw_cap, [24]=arch_rev, [28]=pot_key, [32]=curr_key
 * ------------------------------------------------------------------- */
pdc_model:
	/* Only handle PDC_MODEL_INFO (subfunction 0), return OK for others */
	comb,<>,n %r0, %r25, pdc_model_ret
	nop

	/* Write model info to result buffer */
	/* Use hversion=0x5020 -> bus_id=0xA (712 series, "Snake" type)
	 * bus_id = (hversion >> 11) & 0x1f = (0x5020 >> 11) & 0x1f = 0xA */
	ldil	L%0x5020, %r1
	ldo	R%0x5020(%r1), %r1
	stw	%r1, 0(%r24)		/* hversion = 0x5020 */
	stw	%r0, 4(%r24)		/* sversion = 0 */
	stw	%r0, 8(%r24)		/* hw_id = 0 */
	stw	%r0, 12(%r24)		/* boot_id = 0 */
	stw	%r0, 16(%r24)		/* sw_id = 0 */
	stw	%r0, 20(%r24)		/* sw_cap = 0 */
	ldi	4, %r1
	stw	%r1, 24(%r24)		/* arch_rev = 4 (PA-RISC 1.1) */
	stw	%r0, 28(%r24)		/* pot_key = 0 */
	stw	%r0, 32(%r24)		/* curr_key = 0 */

pdc_model_ret:
	ldi	0, %r28
	bv	%r0(%r2)
	nop

/* -------------------------------------------------------------------
 * PDC_CACHE (class 5): Return cache info
 * r24 = result buffer (PA)
 * struct pdc_cache_info layout (each field = unsigned long = 4 bytes):
 *   I-cache:
 *     +0x00 ic_size      +0x04 ic_conf      +0x08 ic_base
 *     +0x0c ic_stride    +0x10 ic_count     +0x14 ic_loop
 *   D-cache:
 *     +0x18 dc_size      +0x1c dc_conf      +0x20 dc_base
 *     +0x24 dc_stride    +0x28 dc_count     +0x2c dc_loop
 *   I-TLB:
 *     +0x30 it_size      +0x34 it_conf      +0x38..+0x50
 *   D-TLB:
 *     +0x54 dt_size      +0x58 dt_conf      +0x5c..+0x74
 *
 * Critical: Linux uses dc_stride (+0x24) as cache_line_size() for SLUB.
 * Values from SeaBIOS-hppa B160L configuration.
 * ------------------------------------------------------------------- */
pdc_cache:
	/* Zero 64 words (256 bytes) first */
	ldi	64, %r1
	copy	%r24, %r20
pdc_cache_loop:
	stw	%r0, 0(%r20)
	addib,<>	-1, %r1, pdc_cache_loop
	ldo	4(%r20), %r20		/* delay slot: increment pointer */

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

/* -------------------------------------------------------------------
 * PDC_COPROC (class 7): PDC_COPROC_CFG
 * r24 = result buffer (PA)
 * pdc_result[0] = ccr_functional, [1] = ccr_present
 * pdc_result[17] = revision (offset 68), [18] = model (offset 72)
 * ccr = 0xC0000000 means FPU present (coprocessor 0 & 1)
 * ------------------------------------------------------------------- */
pdc_coproc:
	/* Zero first 20 words (80 bytes) of result buffer */
	ldi	20, %r1
	copy	%r24, %r20
pdc_coproc_zero:
	stw	%r0, 0(%r20)
	addib,<>	-1, %r1, pdc_coproc_zero
	ldo	4(%r20), %r20		/* delay slot */

	/* Set ccr_functional and ccr_present = 0xC0000000 */
	ldil	L%0xC0000000, %r1
	stw	%r1, 0(%r24)		/* pdc_result[0] = ccr_functional */
	stw	%r1, 4(%r24)		/* pdc_result[1] = ccr_present */

	/* Set revision and model */
	ldi	1, %r1
	stw	%r1, 68(%r24)		/* pdc_result[17] = revision = 1 */
	stw	%r1, 72(%r24)		/* pdc_result[18] = model = 1 */

	ldi	0, %r28
	bv	%r0(%r2)
	nop

/* -------------------------------------------------------------------
 * PDC_IODC (class 8): IODC operations
 * r25 = subfunction (0=PDC_IODC_READ)
 * r24 = actcnt buffer PA
 * r23 = HPA of module
 * arg4 (sp-52) = index (0=module header)
 * arg5 (sp-56) = iodc_data buffer PA
 * arg6 (sp-60) = data_size
 *
 * IODC data byte layout (read by alloc_pa_dev in drivers.c):
 *   [0] = hversion >> 4
 *   [1] = ((hversion & 0xf) << 4) | hversion_rev
 *   [2] = spa_shift
 *   [3] = hw_type (HPHW_FIO=10)
 *   [4] = (sversion >> 16) & 0x0f
 *   [5] = (sversion >> 8) & 0xff
 *   [6] = sversion & 0xff
 * ------------------------------------------------------------------- */
pdc_iodc:
	/* Only handle PDC_IODC_READ (subfunction 0) */
	comb,<>,n %r0, %r25, pdc_iodc_err
	nop

	/* Load arg4 (index) from stack */
	ldw	-52(%r30), %r20		/* r20 = index */

	/* Only handle index 0 (module header) */
	comb,<>,n %r0, %r20, pdc_iodc_err
	nop

	/* Check HPA: only know about UART at 0x03F00000 */
	ldil	L%0x03F00000, %r1
	ldo	R%0x03F00000(%r1), %r1
	comb,<>,n %r1, %r23, pdc_iodc_err
	nop

	/* Load iodc_data buffer from arg5 (sp-56) */
	ldw	-56(%r30), %r20		/* r20 = iodc_data PA */

	/* Zero first 32 bytes */
	stw	%r0, 0(%r20)
	stw	%r0, 4(%r20)
	stw	%r0, 8(%r20)
	stw	%r0, 12(%r20)
	stw	%r0, 16(%r20)
	stw	%r0, 20(%r20)
	stw	%r0, 24(%r20)
	stw	%r0, 28(%r20)

	/* Write IODC header for serial port:
	 * hversion=0x8c, hw_type=HPHW_FIO(10), sversion=0x8d
	 * sversion=0x8d means registers at HPA+0 (not HPA+0x800)
	 * Bytes: [0]=0x08, [1]=0xc0, [2]=0x00, [3]=0x0a
	 * As big-endian word: 0x08c0000a */
	ldil	L%0x08c0000a, %r1
	ldo	R%0x08c0000a(%r1), %r1
	stw	%r1, 0(%r20)

	/* Bytes: [4]=0x00, [5]=0x00, [6]=0x8d, [7]=0x00
	 * As big-endian word: 0x00008d00 */
	ldil	L%0x00008d00, %r1
	ldo	R%0x00008d00(%r1), %r1
	stw	%r1, 4(%r20)

	/* Write actcnt = 32 (bytes returned) */
	ldi	32, %r1
	stw	%r1, 0(%r24)

	ldi	0, %r28			/* PDC_OK */
	bv	%r0(%r2)
	nop

pdc_iodc_err:
	ldi	-3, %r28		/* PDC_ERROR */
	bv	%r0(%r2)
	nop

/* -------------------------------------------------------------------
 * PDC_SYSTEM_MAP (class 11): Hardware device enumeration
 * r25 = subfunction (0=PDC_FIND_MODULE, 1=PDC_FIND_ADDRESS)
 * r24 = result buffer PA (pdc_system_map_mod_info)
 * r23 = module_path buffer PA
 * arg4 (sp-52) = mod_index
 *
 * pdc_system_map_mod_info:
 *   [0] mod_addr  — physical address of module
 *   [4] mod_pgs   — pages of I/O space
 *   [8] add_addrs — additional addresses
 *
 * device_path (in module_path buffer):
 *   [0] flags     (byte)
 *   [1..6] bc[6]  (bytes, bus converter path)
 *   [7] mod       (byte, module number)
 *
 * We enumerate one device: UART at 0x03F00000
 * ------------------------------------------------------------------- */
pdc_system_map:
	/* Only handle PDC_FIND_MODULE (subfunction 0) */
	comb,<>,n %r0, %r25, pdc_sysmap_err
	nop

	/* Load mod_index from arg4 (sp-52) */
	ldw	-52(%r30), %r20		/* r20 = mod_index */

	/* Only mod_index 0 is valid (UART) */
	comb,<>,n %r0, %r20, pdc_sysmap_err
	nop

	/* Fill pdc_system_map_mod_info (result buffer at r24) */
	/* mod_addr = 0x03F00000 (UART HPA) */
	ldil	L%0x03F00000, %r1
	ldo	R%0x03F00000(%r1), %r1
	stw	%r1, 0(%r24)		/* mod_addr */
	ldi	1, %r1
	stw	%r1, 4(%r24)		/* mod_pgs = 1 */
	stw	%r0, 8(%r24)		/* add_addrs = 0 */

	/* Fill module_path (at r23): device_path = {0,0,0,0,0,0,0,0} */
	stw	%r0, 0(%r23)
	stw	%r0, 4(%r23)

	ldi	0, %r28			/* PDC_OK */
	bv	%r0(%r2)
	nop

pdc_sysmap_err:
	ldi	-5, %r28		/* PDC_NE_MOD (no more modules) */
	bv	%r0(%r2)
	nop

/* -------------------------------------------------------------------
 * PDC_PSW (class 21): PSW mask handling
 * r25 = 0 (PDC_PSW_MASK): write endian bit mask to result[0]
 * r25 = 1 (PDC_PSW_GET_DEFAULTS): return 0
 * r25 = 2 (PDC_PSW_SET_DEFAULTS): return OK
 * r24 = result buffer (PA)
 * ------------------------------------------------------------------- */
pdc_psw:
	/* Check for PDC_PSW_MASK (subfunction 0) */
	comb,<>,n %r0, %r25, pdc_psw_ret
	nop

	/* Return endian mask: PDC_PSW_ENDIAN_BIT = 1 */
	ldi	1, %r1
	stw	%r1, 0(%r24)		/* result[0] = supported PSW bits mask */

pdc_psw_ret:
	ldi	0, %r28
	bv	%r0(%r2)
	nop

/* ===================================================================
 * Padding to IODC entry at offset 0x400 (address 0x80400)
 * (Bumped from 0x200 to fit PDC_SYSTEM_MAP + PDC_IODC handlers)
 * =================================================================== */
	.org	0x400

/* ===================================================================
 * IODC Entry Point — address 0x80400
 * Called via real32_call(PAGE0->mem_cons.iodc_io, ...)
 *
 * r26 = HPA (device hardware address)
 * r25 = IODC function code (ENTRY_IO_CIN=2, ENTRY_IO_COUT=3)
 * r24 = spa, r23 = layers pointer
 * sp-52 = retbuf ptr (arg4), sp-56 = 0 (arg5)
 * sp-60 = buf_pa (arg6), sp-64 = count (arg7)
 *
 * r30 = sp (physical mode stack pointer)
 * r2  = return address
 * =================================================================== */
iodc_entry:
	/* Dispatch on r25 (IODC function code) */

	/* ENTRY_IO_CIN (2) */
	ldi	2, %r1
	comb,=	%r1, %r25, iodc_cin
	nop

	/* ENTRY_IO_COUT (3) */
	ldi	3, %r1
	comb,=	%r1, %r25, iodc_cout
	nop

	/* Default: return 0 */
	ldi	0, %r28
	bv	%r0(%r2)
	nop

/* -------------------------------------------------------------------
 * IODC ENTRY_IO_CIN (function 2): Console input — return 0 (no input)
 * ------------------------------------------------------------------- */
iodc_cin:
	ldi	0, %r28
	bv	%r0(%r2)
	nop

/* -------------------------------------------------------------------
 * IODC ENTRY_IO_COUT (function 3): Console output to UART
 * sp-60 = buf_pa (physical address of output buffer)
 * sp-64 = count  (number of bytes to write)
 * sp-52 = retbuf (write bytes-written count here)
 * UART THR at 0x03F00000
 * ------------------------------------------------------------------- */
iodc_cout:
	/* Load buf_pa and count from stack */
	ldw	-60(%r30), %r20		/* r20 = buf_pa (arg6) */
	ldw	-64(%r30), %r21		/* r21 = count  (arg7) */

	/* Load UART THR address: 0x03F00000 */
	ldil	L%0x03F00000, %r22
	ldo	R%0x03F00000(%r22), %r22

	/* If count == 0, skip loop */
	comb,=,n %r0, %r21, iodc_cout_done
	nop

	/* Save original count for return value */
	copy	%r21, %r28

	/* Output loop: read byte from buf, write to UART THR */
iodc_cout_loop:
	ldb	0(%r20), %r1		/* r1 = *buf */
	stb	%r1, 0(%r22)		/* UART THR = byte */
	addib,<>	-1, %r21, iodc_cout_loop
	ldo	1(%r20), %r20		/* delay slot: buf++ */

	/* Write bytes-written to retbuf (arg4 at sp-52) */
iodc_cout_done:
	ldw	-52(%r30), %r20		/* r20 = retbuf_pa (arg4) */
	stw	%r28, 0(%r20)		/* retbuf[0] = bytes written */

	bv	%r0(%r2)
	nop
