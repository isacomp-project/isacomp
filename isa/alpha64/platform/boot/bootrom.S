// Alpha64 Boot ROM
// =================
// Loaded at physical address 0x8000. Called by PALcode RESET handler
// after IPR initialization, while still in PAL mode.
//
// Purpose:
//   1. Build HWRPB (Hardware Restart Parameter Block) at 0x10000000
//   2. Set kernel command line at KERNEL_START - 0x6000 (0x0100A000)
//   3. Set a0 = HWRPB physical address
//   4. HW_REI to kernel at KSEG VA 0xFFFFFC0001010000
//
// Runs in PAL mode - uses hw_st for physical memory writes,
// hw_mtpr/hw_mfpr for IPR access, hw_rei to exit to kernel.

// =========================================================================
// Hardware instruction macros (PAL-mode only)
// These encode privileged instructions that alpha-linux-gnu-as
// does not directly support. Use register NUMBERS (0-31).
// =========================================================================

// HW_MFPR - Read Internal Processor Register
// Format: opcode[31:26]=0x19, ra[25:21], unused[20:16]=0, index[15:0]
.macro HW_MFPR ra, idx
.long (0x19 << 26) | (\ra << 21) | (\idx)
.endm

// HW_MTPR - Write Internal Processor Register
// Format: opcode[31:26]=0x1D, ra[25:21], unused[20:16]=0, index[15:0]
.macro HW_MTPR ra, idx
.long (0x1D << 26) | (\ra << 21) | (\idx)
.endm

// HW_LD - Physical memory load (bypasses TLB)
// Format: opcode[31:26]=0x1B, ra[25:21], rb[20:16], disp[15:0]
.macro HW_LD ra, disp, rb
.long (0x1B << 26) | (\ra << 21) | (\rb << 16) | (\disp & 0xFFFF)
.endm

// HW_ST - Physical memory store (bypasses TLB)
// Format: opcode[31:26]=0x1F, ra[25:21], rb[20:16], disp[15:0]
.macro HW_ST ra, disp, rb
.long (0x1F << 26) | (\ra << 21) | (\rb << 16) | (\disp & 0xFFFF)
.endm

// HW_REI - Return from exception/interrupt (exits PAL mode)
// Format: opcode[31:26]=0x1E, rest=0
.macro HW_REI
.long (0x1E << 26)
.endm

// =========================================================================
// Register aliases (numeric, for use with HW macros)
// =========================================================================
// $0 (v0) = 0    - return value / temp
// $1 (t0) = 1    - base address register
// $2 (t1) = 2    - data value register
// $3 (t2) = 3    - temp
// $4 (t3) = 4    - temp
// $16 (a0) = 16  - argument 0 (HWRPB address to kernel)
// $17 (a1) = 17  - argument 1 (command line address)
// $18 (a2) = 18  - argument 2 (0)
// $29 (gp) = 29  - global pointer
// $30 (sp) = 30  - stack pointer
// $31 (zero) = 31

// =========================================================================
// IPR indices (from ipr_defs.isa)
// =========================================================================
#define IPR_EXC_ADDR  0x0009
#define IPR_PS        0x000A
#define IPR_IPL       0x000B

// =========================================================================
// Memory layout constants
// =========================================================================
#define HWRPB_BASE     0x10000000   // HWRPB physical address
#define KERNEL_START   0x01010000   // Kernel entry physical address (matches vmlinux .text)
#define CMDLINE_ADDR   0x0100A000   // KERNEL_START - 0x6000
#define INIT_SP        0x00F00000   // Initial kernel stack (below kernel)

// =========================================================================
// Boot ROM entry point
// =========================================================================
    .text
    .globl _bootrom_entry
    .ent _bootrom_entry
_bootrom_entry:

    // =====================================================================
    // Step 1: Load HWRPB base address into $1 (t0)
    // Build 0x10000000 using ldah (load address high)
    // ldah loads imm16 << 16 into register, so 0x1000 << 16 = 0x10000000
    // =====================================================================
    ldah    $1, 0x1000($31)     // $1 = 0x10000000

    // =====================================================================
    // Step 2: Build HWRPB structure field by field
    // Each field is stored with HW_ST at offset from $1
    // =====================================================================

    // --- Offset 0x000: phys_addr (self-pointer = 0x10000000) ---
    // $1 already has the value
    or      $1, $31, $2         // $2 = $1 = 0x10000000
    HW_ST   2, 0x000, 1

    // --- Offset 0x008: id = "HWRPB\0\0\0" = 0x0000004250525748 ---
    // Build this constant: ASCII H=0x48, W=0x57, R=0x52, P=0x50, B=0x42
    // Little-endian quadword: bytes [H,W,R,P,B,0,0,0]
    // = 0x00_00_00_42_50_52_57_48
    //
    // Strategy: build in pieces
    // Low 32 bits: 0x50525748
    // High 32 bits: 0x00000042
    ldah    $2, 0x5052($31)     // $2 = 0x50520000
    lda     $2, 0x5748($2)      // $2 = 0x50525748
    ldah    $3, 0x0000($31)     // $3 = 0
    lda     $3, 0x0042($3)      // $3 = 0x42
    sll     $3, 32, $3          // $3 = 0x0000004200000000
    bis     $2, $3, $2          // $2 = 0x0000004250525748
    HW_ST   2, 0x008, 1

    // --- Offset 0x010: revision = 7 ---
    lda     $2, 7($31)          // $2 = 7
    HW_ST   2, 0x010, 1

    // --- Offset 0x018: size = 0x1A8 ---
    lda     $2, 0x1A8($31)      // $2 = 0x1A8
    HW_ST   2, 0x018, 1

    // --- Offset 0x020: cpuid = 0 ---
    HW_ST   31, 0x020, 1

    // --- Offset 0x028: pagesize = 8192 = 0x2000 ---
    lda     $2, 0x2000($31)     // $2 = 8192
    HW_ST   2, 0x028, 1

    // --- Offset 0x030: pa_bits = 40 ---
    lda     $2, 40($31)
    HW_ST   2, 0x030, 1

    // --- Offset 0x038: max_asn = 127 (EV5-class: 7-bit ASN) ---
    lda     $2, 127($31)
    HW_ST   2, 0x038, 1

    // --- Offset 0x040: sys_serial_num = "MILO" ---
    // Kernel checks strncmp(hwrpb->ssn, "MILO", 4) to detect SRM console.
    // Setting to "MILO" tells kernel we're NOT running under SRM,
    // preventing it from trying to call CRB dispatch routines.
    // "MILO" in little-endian: M=0x4D, I=0x49, L=0x4C, O=0x4F
    ldah    $2, 0x4F4C($31)     // $2 = 0x4F4C0000
    lda     $2, 0x494D($2)      // $2 = 0x4F4C494D = "MILO"
    HW_ST   2, 0x040, 1
    HW_ST   31, 0x048, 1

    // --- Offset 0x050: sys_type = 100 (ISAComp platform) ---
    lda     $2, 100($31)
    HW_ST   2, 0x050, 1

    // --- Offset 0x058: sys_variation = 0 ---
    HW_ST   31, 0x058, 1

    // --- Offset 0x060: sys_revision = 0 ---
    HW_ST   31, 0x060, 1

    // --- Offset 0x068: intr_freq = 1024 ---
    lda     $2, 1024($31)
    HW_ST   2, 0x068, 1

    // --- Offset 0x070: cycle_freq = 50000000 (0x02FAF080) ---
    // Build: 0x02FA << 16 = 0x02FA0000, then add 0xF080
    // But lda sign-extends, so 0xF080 = -0x0F80 in signed.
    // ldah $2, 0x02FB($31) gives 0x02FB0000, lda $2, -0x0F80($2) = 0x02FAF080
    ldah    $2, 0x02FB($31)     // $2 = 0x02FB0000
    lda     $2, -0x0F80($2)     // $2 = 0x02FB0000 - 0x0F80 = 0x02FAF080
    HW_ST   2, 0x070, 1

    // --- Offset 0x078: vptb = 0xFFFFFE0000000000 ---
    // Build: -0x200000000000 = 0xFFFFFE0000000000
    // Strategy: load -2 into reg, shift left 45 bits? No...
    // 0xFFFFFE00_00000000: top 48 bits = 0xFFFFFE, bottom 16 = 0
    // Load -512 (0xFFFFFFFFFFFFFE00) and shift left 32
    // Actually: load -1 into $2, shift left 41 → 0xFFFFFE0000000000
    // -1 << 41 = 0xFFFFFE0000000000? Let's check:
    // -1 = 0xFFFFFFFFFFFFFFFF, << 41 = top 23 bits of orig, low 41 = 0
    // = 0xFFFFFFE000000000 — that's wrong.
    // We need 0xFFFFFE0000000000.
    // 0xFFFFFE = 0x1000000 - 0x200 = nope.
    // 0xFFFFFE0000000000 / 0x10000000000 (2^40) = 0xFFFFFE = 16777214
    // Hmm, let's just build it:
    // Load -2 into a reg (0xFFFFFFFFFFFFFFFE), shift left 40
    // -2 << 40 = 0xFFFFFE0000000000  ← yes!
    lda     $2, -2($31)         // $2 = 0xFFFFFFFFFFFFFFFE
    sll     $2, 40, $2          // $2 = 0xFFFFFE0000000000
    HW_ST   2, 0x078, 1

    // --- Offset 0x080: res1 = 0 ---
    HW_ST   31, 0x080, 1

    // --- Offset 0x088: tbhint_off = 0 ---
    HW_ST   31, 0x088, 1

    // --- Offset 0x090: nr_processors = 1 ---
    lda     $2, 1($31)
    HW_ST   2, 0x090, 1

    // --- Offset 0x098: processor_size = 0x1E0 ---
    // Actual percpu_struct is 0x280 bytes, but we only initialize
    // fields up to offset 0xD0. For single-CPU, this just needs
    // to not overlap CTB at 0x400 (per-CPU starts at 0x200).
    lda     $2, 0x1E0($31)
    HW_ST   2, 0x098, 1

    // --- Offset 0x0A0: processor_offset = 0x200 ---
    lda     $2, 0x200($31)
    HW_ST   2, 0x0A0, 1

    // --- Offset 0x0A8: ctb_nr = 1 ---
    lda     $2, 1($31)
    HW_ST   2, 0x0A8, 1

    // --- Offset 0x0B0: ctb_size = 0x30 ---
    lda     $2, 0x30($31)
    HW_ST   2, 0x0B0, 1

    // --- Offset 0x0B8: ctb_offset = 0x400 ---
    lda     $2, 0x400($31)
    HW_ST   2, 0x0B8, 1

    // --- Offset 0x0C0: crb_offset = 0x500 ---
    lda     $2, 0x500($31)
    HW_ST   2, 0x0C0, 1

    // --- Offset 0x0C8: mddt_offset = 0x600 ---
    lda     $2, 0x600($31)
    HW_ST   2, 0x0C8, 1

    // --- Offsets 0x0D0 - 0x0F8: zero fields ---
    HW_ST   31, 0x0D0, 1       // cdb_offset
    HW_ST   31, 0x0D8, 1       // frut_offset
    HW_ST   31, 0x0E0, 1       // save_term
    HW_ST   31, 0x0E8, 1       // save_term_data
    HW_ST   31, 0x0F0, 1       // restore_term
    HW_ST   31, 0x0F8, 1       // restore_term_data

    // --- Offset 0x100: restart = 0x8000 (boot ROM address) ---
    lda     $2, 0x8000($31)
    // lda sign-extends 0x8000 to 0xFFFFFFFFFFFF8000, fix it:
    sll     $2, 48, $2          // Clear high 48 bits (shift left)
    srl     $2, 48, $2          // Shift back: keep low 16 bits = 0x8000
    HW_ST   2, 0x100, 1

    // --- Offset 0x108: restart_data = 0 ---
    HW_ST   31, 0x108, 1

    // --- Offset 0x110: reserve_for_hw = 0 ---
    HW_ST   31, 0x110, 1

    // --- Offset 0x118: nr_mem_desc = 0 ---
    HW_ST   31, 0x118, 1

    // --- Offset 0x120: mddt_cluster_cnt = 2 ---
    lda     $2, 2($31)
    HW_ST   2, 0x120, 1

    // --- Offset 0x1A0: checksum = 0 ---
    HW_ST   31, 0x1A0, 1

    // =====================================================================
    // Step 3: Build Per-CPU Slot (at HWRPB + 0x200)
    // Need base address in a register for offsets > 0x1FF
    // =====================================================================
    lda     $3, 0x200($1)       // $3 = HWRPB + 0x200

    // hwpcb[0..15] = 0 (16 quadwords = 128 bytes, 0x00-0x7F)
    // pcb_struct: KSP(0x00), USP(0x08), PTBR(0x10), PCC/ASN(0x18),
    //             UNIQUE(0x20), FLAGS(0x28), res1(0x30), res2(0x38)
    HW_ST   31, 0x00, 3
    HW_ST   31, 0x08, 3
    HW_ST   31, 0x10, 3
    HW_ST   31, 0x18, 3
    HW_ST   31, 0x20, 3
    HW_ST   31, 0x28, 3
    HW_ST   31, 0x30, 3
    HW_ST   31, 0x38, 3
    HW_ST   31, 0x40, 3
    HW_ST   31, 0x48, 3
    HW_ST   31, 0x50, 3
    HW_ST   31, 0x58, 3
    HW_ST   31, 0x60, 3
    HW_ST   31, 0x68, 3
    HW_ST   31, 0x70, 3
    HW_ST   31, 0x78, 3

    // percpu_struct fields start at 0x80 (after hwpcb[16])
    // flags (state_flags) = 1 (valid)
    lda     $2, 1($31)
    HW_ST   2, 0x80, 3

    // pal_mem_size = 0x8000 (offset 0x88)
    lda     $2, 0x8000($31)
    sll     $2, 48, $2          // Fix sign extension: clear high bits
    srl     $2, 48, $2          // Keep low 16 bits = 0x8000
    HW_ST   2, 0x88, 3

    // pal_scratch_size = 0x4000 (offset 0x90)
    lda     $2, 0x4000($31)
    HW_ST   2, 0x90, 3

    // pal_mem_pa = 0, pal_scratch_pa = 0 (offsets 0x98, 0xA0)
    HW_ST   31, 0x98, 3
    HW_ST   31, 0xA0, 3

    // pal_revision = 1 (offset 0xA8)
    lda     $2, 1($31)
    HW_ST   2, 0xA8, 3

    // type = 5 (EV5-class, matches max_asn=127) (offset 0xB0)
    lda     $2, 5($31)
    HW_ST   2, 0xB0, 3

    // variation = 0, revision = 0, serial_no[2] = 0 (offsets 0xB8-0xD0)
    HW_ST   31, 0xB8, 3
    HW_ST   31, 0xC0, 3
    HW_ST   31, 0xC8, 3
    HW_ST   31, 0xD0, 3

    // logout_area_pa = 0, logout_area_len = 0 (offsets 0xD8, 0xE0)
    HW_ST   31, 0xD8, 3
    HW_ST   31, 0xE0, 3

    // halt_PCBB through halt_reason = 0 (offsets 0xE8-0x118)
    HW_ST   31, 0xE8, 3        // halt_PCBB
    HW_ST   31, 0xF0, 3        // halt_PC
    HW_ST   31, 0xF8, 3        // halt_PS
    HW_ST   31, 0x100, 3       // halt_arg
    HW_ST   31, 0x108, 3       // halt_ra
    HW_ST   31, 0x110, 3       // halt_pv
    HW_ST   31, 0x118, 3       // halt_reason

    // =====================================================================
    // Step 4: Build CTB (Console Terminal Block) at HWRPB + 0x400
    // =====================================================================
    lda     $3, 0x400($1)       // $3 = HWRPB + 0x400

    // type = 4 (serial console)
    lda     $2, 4($31)
    HW_ST   2, 0x00, 3

    // id = 0, reserved = 0, dev_dep_len = 0, ipl = 0, tx_irq = 0
    HW_ST   31, 0x08, 3
    HW_ST   31, 0x10, 3
    HW_ST   31, 0x18, 3
    HW_ST   31, 0x20, 3
    HW_ST   31, 0x28, 3

    // =====================================================================
    // Step 5: Build CRB (Console Routine Block) at HWRPB + 0x500
    // =====================================================================
    lda     $3, 0x500($1)       // $3 = HWRPB + 0x500

    // All zero (no console dispatch routines)
    HW_ST   31, 0x00, 3        // dispatch_va
    HW_ST   31, 0x08, 3        // dispatch_pa
    HW_ST   31, 0x10, 3        // fixup_va
    HW_ST   31, 0x18, 3        // fixup_pa
    HW_ST   31, 0x20, 3        // nr_pages
    HW_ST   31, 0x28, 3        // pages[0]

    // =====================================================================
    // Step 6: Build MDDT (Memory Data Descriptor Table) at HWRPB + 0x600
    // =====================================================================
    lda     $3, 0x600($1)       // $3 = HWRPB + 0x600

    // memdesc_struct layout:
    //   +0x00: chksum
    //   +0x08: optional_pa
    //   +0x10: numclusters
    //   +0x18: cluster[0] (0x38 bytes = 7 quadwords per cluster)
    //   +0x50: cluster[1]
    //
    // memclust_struct (each cluster):
    //   +0x00: start_pfn
    //   +0x08: numpages
    //   +0x10: numtested
    //   +0x18: bitmap_va
    //   +0x20: bitmap_pa
    //   +0x28: bitmap_chksum
    //   +0x30: usage

    // chksum = 0
    HW_ST   31, 0x00, 3

    // optional_pa = 0
    HW_ST   31, 0x08, 3

    // numclusters = 2
    lda     $2, 2($31)
    HW_ST   2, 0x10, 3

    // --- Cluster 0: PALcode/firmware region (not included in kernel memory) ---
    // start_pfn = 0
    HW_ST   31, 0x18, 3
    // numpages = 8 (reserve pages 0-7: PA 0x0000 to 0xFFFF, PALcode/firmware)
    lda     $2, 8($31)
    HW_ST   2, 0x20, 3
    // numtested = 0
    HW_ST   31, 0x28, 3
    // bitmap_va = 0, bitmap_pa = 0, bitmap_chksum = 0
    HW_ST   31, 0x30, 3
    HW_ST   31, 0x38, 3
    HW_ST   31, 0x40, 3
    // usage = 1 (console/PAL reserved - bit 0 set)
    lda     $2, 1($31)
    HW_ST   2, 0x48, 3

    // --- Cluster 1: Available memory (PA 0x10000 onwards) ---
    // start_pfn = 8
    lda     $2, 8($31)
    HW_ST   2, 0x50, 3
    // numpages = 8184 (= 8192 - 8, for 64MB simulation memory)
    lda     $2, 8184($31)       // $2 = 0x1FF8 = 8184
    HW_ST   2, 0x58, 3
    // numtested = 8184
    HW_ST   2, 0x60, 3
    // bitmap_va = 0, bitmap_pa = 0, bitmap_chksum = 0
    HW_ST   31, 0x68, 3
    HW_ST   31, 0x70, 3
    HW_ST   31, 0x78, 3
    // usage = 0 (available memory)
    HW_ST   31, 0x80, 3

    // =====================================================================
    // Step 7: Store kernel command line at CMDLINE_ADDR (0x00FFA000)
    //
    // aboot places command line at KERNEL_START - 0x6000
    // We store a simple string: "console=ttyS0 root=/dev/ram0"
    // =====================================================================
    // 0x0100A000 = 0x01010000 - 0x6000
    ldah    $3, 0x0101($31)     // $3 = 0x01010000
    lda     $3, -0x6000($3)     // $3 = 0x0100A000

    // Store command line string "console=ttyS0 root=/dev/ram0\0"
    // as quadwords (little-endian)
    // "console=" = 0x3D656C6F736E6F63
    ldah    $2, 0x3D65($31)
    lda     $2, 0x6C6F($2)
    sll     $2, 32, $4
    ldah    $2, 0x736E($31)
    lda     $2, 0x6F63($2)
    sll     $2, 32, $2          // Keep low 32 bits: clear high
    srl     $2, 32, $2          // Shift back
    bis     $4, $2, $2
    HW_ST   2, 0x00, 3

    // "ttyS0 ro" = 0x6F72203053797474
    ldah    $2, 0x6F72($31)
    lda     $2, 0x2030($2)
    sll     $2, 32, $4
    ldah    $2, 0x5379($31)
    lda     $2, 0x7474($2)
    sll     $2, 32, $2          // Keep low 32 bits: clear high
    srl     $2, 32, $2          // Shift back
    bis     $4, $2, $2
    HW_ST   2, 0x08, 3

    // "ot=/dev/" = 0x2F7665642F3D746F
    ldah    $2, 0x2F76($31)
    lda     $2, 0x6564($2)
    sll     $2, 32, $4
    ldah    $2, 0x2F3D($31)
    lda     $2, 0x746F($2)
    sll     $2, 32, $2          // Keep low 32 bits: clear high
    srl     $2, 32, $2          // Shift back
    bis     $4, $2, $2
    HW_ST   2, 0x10, 3

    // "ram0\0\0\0\0" = 0x000000006D6172
    // Actually "ram0" = 0x306D6172, padded = 0x00000000306D6172
    ldah    $2, 0x306D($31)
    lda     $2, 0x6172($2)
    sll     $2, 32, $2          // Keep low 32 bits: clear high
    srl     $2, 32, $2          // Shift back only
    HW_ST   2, 0x18, 3

    // Null terminate rest
    HW_ST   31, 0x20, 3

    // =====================================================================
    // Step 8: Set up registers for kernel entry
    // =====================================================================

    // a0 ($16) = HWRPB physical address
    or      $1, $31, $16        // $16 = 0x10000000

    // a1 ($17) = 0 (kernel reads command line from fixed offset)
    or      $31, $31, $17       // $17 = 0

    // a2 ($18) = 0
    or      $31, $31, $18       // $18 = 0

    // gp ($29) = 0 (kernel sets its own)
    or      $31, $31, $29       // $29 = 0

    // sp ($30) = initial kernel stack
    ldah    $30, 0x00F0($31)    // $30 = 0x00F00000
    lda     $30, 0($30)

    // =====================================================================
    // Step 9: Set exc_addr to kernel entry and hw_rei to jump there
    // This exits PAL mode and transfers control to the kernel.
    // =====================================================================

    // Set exc_addr = KSEG kernel VA (0xFFFFFC0001010000)
    // KSEG base: -1 << 42 = 0xFFFFFC0000000000
    lda     $3, -1($31)         // $3 = 0xFFFFFFFFFFFFFFFF
    sll     $3, 42, $3          // $3 = 0xFFFFFC0000000000
    ldah    $2, 0x0101($31)     // $2 = 0x01010000
    bis     $3, $2, $2          // $2 = 0xFFFFFC0001010000
    HW_MTPR 2, IPR_EXC_ADDR

    // Set PS = 0 (kernel mode) and IPL = 0 (unmask interrupts)
    HW_MTPR 31, IPR_PS
    HW_MTPR 31, IPR_IPL

    // Jump to kernel - exits PAL mode
    HW_REI

    .end _bootrom_entry
