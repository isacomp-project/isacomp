// ============================================================================
// Alpha64 PALcode Firmware for ISAComp Linux Boot
// ============================================================================
//
// Loaded at physical address 0 (pal_base = 0).
// Provides exception handlers and call_pal functions for Linux.
//
// Assembled with: alpha-linux-gnu-gcc -c -o palcode.o palcode.S
//
// Memory layout:
//   0x0000 - 0x05FF  Exception handlers (128-byte slots)
//   0x2000 - 0x2FFF  Privileged call_pal entries (64-byte slots)
//   0x3000 - 0x3FFF  Unprivileged call_pal entries (64-byte slots)
//   0x4000+          Extended handlers (overflow area)
//
// ============================================================================

// ============================================================================
// IPR Index Definitions
// ============================================================================

#define IPR_PAL_BASE  0x08
#define IPR_EXC_ADDR  0x09
#define IPR_PS        0x0A
#define IPR_IPL       0x0B
#define IPR_ISR       0x0C
#define IPR_HIER      0x0D
#define IPR_SIRR      0x0E
#define IPR_EXC_SUM   0x11
#define IPR_VA        0x13
#define IPR_MM_STAT   0x15
#define IPR_PTBR      0x16
#define IPR_VPTPTR    0x17
#define IPR_DTB_ASN   0x19
#define IPR_DTB_PTE   0x1A
#define IPR_DTB_TAG   0x1B
#define IPR_ITB_ASN   0x1C
#define IPR_ITB_PTE   0x1D
#define IPR_ITB_TAG   0x1E
#define IPR_WHAMI     0x20
#define IPR_PCBB      0x21
#define IPR_UNIQUE    0x22
#define IPR_SYSVAL    0x23
#define IPR_PCC       0x24
#define IPR_IMPLVER   0x25
#define IPR_AMASK_VAL 0x26
#define IPR_MCES      0x27
#define IPR_FEN       0x28
#define IPR_ITB_IA    0x83
#define IPR_ITB_IS    0x82
#define IPR_DTB_IA    0xA3
#define IPR_DTB_IS    0xA2

// PAL temp registers: PT0=0x40 .. PT23=0x57
#define PT_KSP        0x40   // pt0  - Kernel stack pointer
#define PT_USP        0x41   // pt1  - User stack pointer
#define PT_PTBR       0x42   // pt2  - Cached PTBR
#define PT_ENTSYS     0x43   // pt3  - entSys handler
#define PT_ENTINT     0x44   // pt4  - entInt handler
#define PT_ENTARITH   0x45   // pt5  - entArith handler
#define PT_ENTMM      0x46   // pt6  - entMM handler
#define PT_ENTIF      0x47   // pt7  - entIF handler
#define PT_ENTUNA     0x48   // pt8  - entUna handler
#define PT_KGP        0x49   // pt9  - Kernel GP
#define PT_PCBB       0x4A   // pt10 - PCB base
#define PT_UNIQUE     0x4B   // pt11 - TLS unique value
// Scratch PAL temps for exception handlers
#define PT_S0         0x4C   // pt12 - save $1
#define PT_S1         0x4D   // pt13 - save $2
#define PT_S2         0x4E   // pt14 - save $3
#define PT_S3         0x4F   // pt15 - save $4
#define PT_S4         0x50   // pt16 - save $22
#define PT_S5         0x51   // pt17

// ============================================================================
// PAL Instruction Macros
// ============================================================================
// GNU assembler for Alpha lacks hw_mfpr/hw_mtpr/hw_ld/hw_st/hw_rei.
// We encode them as raw .long directives.

.macro hw_mfpr ra, ipr_idx
    .long (0x19 << 26) | (\ra << 21) | (\ipr_idx)
.endm

.macro hw_mtpr ra, ipr_idx
    .long (0x1D << 26) | (\ra << 21) | (\ipr_idx)
.endm

// hw_ld/hw_st: displacement is bits [11:0] (sign-extended).
// Bits [15:12] are modifiers (ignored by our ISA - always physical quadword).
.macro hw_ld ra, disp, rb
    .long (0x1B << 26) | (\ra << 21) | (\rb << 16) | (\disp & 0xFFFF)
.endm

.macro hw_st ra, disp, rb
    .long (0x1F << 26) | (\ra << 21) | (\rb << 16) | (\disp & 0xFFFF)
.endm

.macro hw_rei
    .long (0x1E << 26)
.endm

// ============================================================================
    .text
    .set noat
    .set noreorder
// ============================================================================


// ============================================================================
// RESET Handler (offset 0x0000)
// ============================================================================
    .org 0x0000
    .globl pal_reset
pal_reset:
    hw_mtpr 31, IPR_PAL_BASE       // pal_base = 0
    lda     $1, 0x3F($31)
    hw_mtpr 1,  IPR_IPL            // IPL = max (mask all interrupts)
    hw_mtpr 31, IPR_PS             // PS = 0 (kernel mode)
    lda     $1, 1($31)
    hw_mtpr 1,  IPR_FEN            // enable FP
    lda     $1, -1($31)             // $1 = 0xFFFFFFFFFFFFFFFF
    hw_mtpr 1,  IPR_HIER           // enable all HW interrupt sources
    hw_mtpr 31, IPR_SIRR           // clear software interrupts
    hw_mtpr 31, IPR_EXC_SUM        // clear exception summary
    hw_mtpr 31, IPR_WHAMI          // CPU 0
    hw_mtpr 31, IPR_ITB_IA         // invalidate all ITB
    hw_mtpr 31, IPR_DTB_IA         // invalidate all DTB
    hw_mtpr 31, IPR_MCES           // clear machine check state
    hw_mtpr 31, PT_KSP
    hw_mtpr 31, PT_USP
    hw_mtpr 31, PT_PTBR
    // Jump to boot ROM at physical address 0x8000.
    // Use jmp (NOT hw_rei) to stay in PAL mode, since the boot ROM
    // uses HW_ST/HW_LD/HW_MTPR for physical memory access.
    // The boot ROM's final HW_REI will exit PAL mode for kernel entry.
    lda     $1, 1($31)              // $1 = 1
    sll     $1, 15, $1              // $1 = 0x8000
    jmp     $31, ($1)               // jump to boot ROM, stay in PAL mode


// ============================================================================
// MCHK - Machine Check (offset 0x0080)
// ============================================================================
    .org 0x0080
pal_mchk:
    br      $31, pal_mchk           // halt (infinite loop)


// ============================================================================
// ARITH - Arithmetic Trap (offset 0x0100)
// ============================================================================
    .org 0x0100
pal_arith:
    br      $31, ext_arith


// ============================================================================
// INTERRUPT (offset 0x0180)
// ============================================================================
    .org 0x0180
pal_interrupt:
    br      $31, ext_interrupt


// ============================================================================
// D_FAULT / DTB_MISS (offset 0x0200)
// Page walk for data TLB miss. Starts inline, continues in extended area.
// KSEG addresses (VA[42]==1) are always identity-mapped.
// If PTBR not set (early boot), identity-map the faulting address.
// ============================================================================
    .org 0x0200
pal_dtb_miss:
    hw_mtpr 1,  PT_S0              // save $1
    hw_mtpr 2,  PT_S1              // save $2
    hw_mtpr 3,  PT_S2              // save $3
    hw_mtpr 4,  PT_S3              // save $4
    hw_mfpr 1,  IPR_VA             // $1 = faulting virtual address
    // Check MM_STAT for ACV (bit 1). ACV means TLB hit but no permission.
    hw_mfpr 2,  IPR_MM_STAT        // $2 = mm_stat (bit0=WR, bit1=ACV)
    srl     $2, 1, $3              // $3 = ACV bit
    blbs    $3, ext_dtb_acv        // ACV → dispatch to entMM handler
    // KSEG check: VA[42:41]==0b10 = kernel linear map (0xFFFFFC00_...)
    // VA[42:41]==0b11 = vmalloc area (0xFFFFFFFC_...) → must page walk
    srl     $1, 41, $3
    and     $3, 3, $3              // $3 = VA[42:41]
    cmpeq   $3, 2, $3              // $3 = 1 if VA[42:41]==0b10 (kernel linear map)
    bne     $3, dtb_identity_map   // kernel linear map → identity map
    // Read PTBR from PCB in memory (not cached PT_PTBR) because the kernel's
    // init_new_context/switch_mm may update pcb.ptbr without calling swpctx.
    hw_mfpr 2,  PT_PCBB            // $2 = current PCB physical address
    beq     $2, dtb_identity_map   // no PCB → identity map (early boot)
    hw_ld   2,  16, 2              // $2 = PCB[16] = PTBR (PFN)
    beq     $2, dtb_identity_map   // PTBR not set → identity map
    sll     $2, 13, $2             // $2 = PTBR PA (PFN << 13)
    hw_mfpr 3,  PT_ENTMM           // $3 = entMM handler address
    bne     $3, ext_dtb_miss_walk  // entMM set → page walk (extended area)
    // entMM not set (early boot): fall through to identity map
dtb_identity_map:
    // Identity-map VA=PA: PTE with PFN = VA>>13, KRE|KWE|ASM|V
    srl     $1, 13, $3              // $3 = VPN = VA >> 13
    sll     $3, 32, $2              // $2 = PFN in [63:32]
    lda     $4, 0x1111($31)         // $4 = V(1)|ASM(0x10)|KRE(0x100)|KWE(0x1000) = 0x1111
    bis     $2, $4, $2              // $2 = complete PTE
    hw_mtpr 3,  IPR_DTB_TAG         // install tag = VPN
    hw_mtpr 2,  IPR_DTB_PTE         // install PTE
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 4,  PT_S3
    hw_rei


// ============================================================================
// ITB_MISS (offset 0x0280)
// Page walk for instruction TLB miss.
// Fast paths:
//   1. KSEG (VA[42:41]==0b10): kernel linear map → identity map (always safe)
//   2. No PCB or PTBR=0: early boot → identity map
// Otherwise: 3-level page table walk.
// 26 instructions (max 32 in this 128-byte slot).
// ============================================================================
    .org 0x0280
pal_itb_miss:
    hw_mtpr 1,  PT_S0
    hw_mtpr 2,  PT_S1
    hw_mtpr 3,  PT_S2
    hw_mtpr 4,  PT_S3
    hw_mfpr 1,  IPR_VA             // $1 = faulting VA (= faulting PC)
    // KSEG fast path: VA[42:41]==0b10 → kernel linear map, identity map
    // Mirrors DTB miss handler. Prevents ext_itb_miss_fault before entMM is set.
    srl     $1, 41, $3             // $3 = VA >> 41
    and     $3, 3, $3              // $3 = VA[42:41]
    cmpeq   $3, 2, $3             // $3 = 1 if VA[42:41]==0b10 (KSEG linear map)
    bne     $3, 1f                 // KSEG → identity map
    // Read PTBR from PCB in memory
    hw_mfpr 2,  PT_PCBB            // $2 = current PCB physical address
    beq     $2, 1f                 // no PCB → identity map (early boot)
    hw_ld   2,  16, 2              // $2 = PCB[16] = PTBR (PFN)
    beq     $2, 1f                 // PTBR not set → identity map
    sll     $2, 13, $2             // $2 = PTBR PA (PFN << 13)
    br      $31, ext_itb_miss_walk // do page walk (in extended area)
1:  // Identity map: PFN = VA >> 13, KRE=1, ASM=1, V=1
    srl     $1, 13, $3              // $3 = VPN
    sll     $3, 32, $2              // $2 = PFN in [63:32]
    lda     $4, 0x0111($31)         // V(1)|ASM(0x10)|KRE(0x100) = 0x111
    bis     $2, $4, $2
    hw_mtpr 3,  IPR_ITB_TAG
    hw_mtpr 2,  IPR_ITB_PTE
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 4,  PT_S3
    hw_rei


// ============================================================================
// ITB_ACV - Instruction Access Violation (offset 0x0300)
// ============================================================================
    .org 0x0300
pal_itb_acv:
    br      $31, ext_itb_acv


// ============================================================================
// DTB_MISS_NATIVE (offset 0x0380)
// ============================================================================
    .org 0x0380
pal_dtb_miss_native:
    br      $31, ext_dtb_miss_native


// ============================================================================
// UNALIGN (offset 0x0400)
// ============================================================================
    .org 0x0400
pal_unalign:
    br      $31, ext_unalign


// ============================================================================
// OPCDEC - Opcode Decode Fault (offset 0x0480)
// ============================================================================
    .org 0x0480
pal_opcdec:
    br      $31, ext_opcdec


// ============================================================================
// FEN - Floating Point Disabled (offset 0x0500)
// ============================================================================
    .org 0x0500
pal_fen:
    br      $31, ext_fen


// ============================================================================
// ============================================================================
// PRIVILEGED CALL_PAL ENTRY POINTS
// Base: pal_base + 0x2000 + func[5:0] * 64
// ============================================================================
// ============================================================================

// halt (0x00) @ 0x2000
// Lower IPL to 0 to unmask interrupts, then return to caller.
// The kernel's idle loop calls pal_halt; on the next cycle after hw_rei,
// a pending interrupt (e.g., timer) will be taken.
    .org 0x2000
pal_halt:
    hw_mtpr 31, IPR_IPL            // IPL = 0 (unmask all interrupts)
    hw_rei                          // return; interrupt check on next cycle

// cflush (0x01) @ 0x2040
    .org 0x2040
    hw_rei

// draina (0x02) @ 0x2080
    .org 0x2080
    hw_rei

// rdmces (0x10) @ 0x2400
    .org 0x2400
    hw_mfpr 0, IPR_MCES
    hw_rei

// wrmces (0x11) @ 0x2440
    .org 0x2440
    hw_mtpr 16, IPR_MCES
    hw_rei

// wrfen (0x2B) @ 0x2AC0
    .org 0x2AC0
    hw_mtpr 16, IPR_FEN
    hw_rei

// wrvptptr (0x2D) @ 0x2B40
    .org 0x2B40
    hw_mtpr 16, IPR_VPTPTR
    hw_rei

// swpctx (0x30) @ 0x2C00
    .org 0x2C00
    br      $31, ext_swpctx

// wrval (0x31) @ 0x2C40
    .org 0x2C40
    hw_mtpr 16, IPR_SYSVAL
    hw_rei

// rdval (0x32) @ 0x2C80
    .org 0x2C80
    hw_mfpr 0, IPR_SYSVAL
    hw_rei

// tbi (0x33) @ 0x2CC0
    .org 0x2CC0
    br      $31, ext_tbi

// wrent (0x34) @ 0x2D00
    .org 0x2D00
    br      $31, ext_wrent

// swpipl (0x35) @ 0x2D40
    .org 0x2D40
    hw_mfpr 0, IPR_IPL
    hw_mtpr 16, IPR_IPL
    hw_rei

// rdps (0x36) @ 0x2D80
    .org 0x2D80
    hw_mfpr 0, IPR_PS
    hw_rei

// wrkgp (0x37) @ 0x2DC0
    .org 0x2DC0
    hw_mtpr 16, PT_KGP
    hw_rei

// wrusp (0x38) @ 0x2E00
    .org 0x2E00
    hw_mtpr 16, PT_USP
    hw_rei

// rdusp (0x3A) @ 0x2E80
    .org 0x2E80
    hw_mfpr 0, PT_USP
    hw_rei

// whami (0x3C) @ 0x2F00
    .org 0x2F00
    hw_mfpr 0, IPR_WHAMI
    hw_rei

// retsys (0x3D) @ 0x2F40
    .org 0x2F40
    br      $31, ext_retsys

// wtint (0x3E) @ 0x2F80
// Wait for interrupt: lower IPL and return, same as halt.
    .org 0x2F80
    hw_mtpr 31, IPR_IPL            // IPL = 0 (unmask all interrupts)
    hw_rei                          // return; interrupt taken on next cycle

// rti (0x3F) @ 0x2FC0
    .org 0x2FC0
    br      $31, ext_rti


// ============================================================================
// ============================================================================
// UNPRIVILEGED CALL_PAL ENTRY POINTS
// Base: pal_base + 0x3000 + func[5:0] * 64
// ============================================================================
// ============================================================================

// bpt (0x80) @ 0x3000
    .org 0x3000
    br      $31, ext_bpt

// bugchk (0x81) @ 0x3040
    .org 0x3040
    br      $31, ext_bugchk

// callsys (0x83) @ 0x30C0
    .org 0x30C0
    br      $31, ext_callsys

// imb (0x86) @ 0x3180
    .org 0x3180
    hw_rei

// rduniq (0x9E) @ 0x3780
    .org 0x3780
    hw_mfpr 0, PT_UNIQUE
    hw_rei

// wruniq (0x9F) @ 0x37C0
    .org 0x37C0
    hw_mtpr 16, PT_UNIQUE
    hw_rei

// gentrap (0xAA) @ 0x3A80
    .org 0x3A80
    br      $31, ext_gentrap


// ============================================================================
// ============================================================================
// EXTENDED HANDLERS (offset 0x4000+)
// ============================================================================
// ============================================================================
    .org 0x4000

// ============================================================================
// DTB_MISS page walk L1 continuation + L2 load + L3
// Entry (dtb_miss_l1_cont): $1=VA, $2=L1 PTE (valid), $4=mask(0x1FF8)
// ============================================================================
// ============================================================================
// DTB_MISS page walk (moved from inline slot to extended area)
// Entry: $1=VA, $2=PTBR PA
// ============================================================================
ext_dtb_miss_walk:
    lda     $4, 0x1FF8($31)         // $4 = index mask
    srl     $1, 30, $3
    and     $3, $4, $3              // $3 = L1 byte offset
    addq    $2, $3, $3              // $3 = L1 PTE physical address
    hw_ld   2, 0, 3                 // $2 = L1 PTE
    blbc    $2, ext_dtb_miss_fault  // bit 0 (Valid) clear → page fault
dtb_miss_l1_cont:
    srl     $2, 32, $3              // $3 = PFN from L1 PTE
    sll     $3, 13, $2              // $2 = L2 base (PFN << 13)
    srl     $1, 20, $3
    and     $3, $4, $3
    addq    $2, $3, $3              // $3 = L2 PTE physical address
dtb_miss_l2_load:
    hw_ld   2, 0, 3              // $2 = L2 PTE
dtb_miss_l2_cont:
    blbc    $2, ext_dtb_miss_fault
    // PFN → L3 base
    srl     $2, 32, $3
    sll     $3, 13, $2              // $2 = L3 base
    // L3: byte_offset = (VA >> 10) & 0x1FF8  [VA[22:13] * 8]
    srl     $1, 10, $3
    and     $3, $4, $3
    addq    $2, $3, $3
    hw_ld   2, 0, 3              // $2 = L3 PTE (final)
    blbc    $2, ext_dtb_miss_fault
    // Install in DTB: tag must be VPN = VA >> 13
    srl     $1, 13, $1              // $1 = VPN
    hw_mtpr 1,  IPR_DTB_TAG
    hw_mtpr 2,  IPR_DTB_PTE
    // Restore and retry
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 4,  PT_S3
    hw_rei


// ============================================================================
// ITB_MISS page walk L2/L3 continuation
// Entry: $1=VA, $2=L2 PTE (just loaded), $4=mask(0x1FF8)
// ============================================================================
// Extended: ITB miss page table walk (moved from slot area to avoid overflow)
ext_itb_miss_walk:
    lda     $4, 0x1FF8($31)
    // L1
    srl     $1, 30, $3
    and     $3, $4, $3
    addq    $2, $3, $3
    hw_ld   2, 0, 3
    blbc    $2, ext_itb_miss_fault
    srl     $2, 32, $3
    sll     $3, 13, $2
    // L2
    srl     $1, 20, $3
    and     $3, $4, $3
    addq    $2, $3, $3
    hw_ld   2, 0, 3
itb_miss_l2_cont:
    blbc    $2, ext_itb_miss_fault
    srl     $2, 32, $3
    sll     $3, 13, $2
    srl     $1, 10, $3
    and     $3, $4, $3
    addq    $2, $3, $3
    hw_ld   2, 0, 3
    blbc    $2, ext_itb_miss_fault
    // Install in ITB: tag = VPN = VA >> 13
    srl     $1, 13, $1
    hw_mtpr 1,  IPR_ITB_TAG
    hw_mtpr 2,  IPR_ITB_PTE
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 4,  PT_S3
    hw_rei


// ============================================================================
// Extended: ARITH handler
// ============================================================================
ext_arith:
    hw_mtpr 1,  PT_S0
    hw_mtpr 2,  PT_S1
    hw_mtpr 3,  PT_S2
    hw_mtpr 22, PT_S4
    // Read PS and encode current IPL in PS[7:4] for exception frame
    hw_mfpr 1,  IPR_PS
    hw_mfpr 2,  IPR_IPL
    sll     $2, 4, $2
    bis     $1, $2, $1
    // Check user/kernel
    srl     $1, 3, $3
    blbc    $3, 1f
    hw_mtpr 30, PT_USP
    hw_mfpr 30, PT_KSP
1:  lda     $30, -48($30)
    // Convert SP to PA
    mov     $30, $22
    sll     $22, 22, $22
    srl     $22, 22, $22
    // Build frame
    hw_st   1,  0, 22             // PS
    hw_mfpr 1,  IPR_EXC_ADDR
    hw_st   1,  8, 22             // PC
    hw_st   29, 16, 22            // GP
    hw_st   16, 24, 22            // a0 (original)
    hw_st   17, 32, 22            // a1 (original)
    hw_st   18, 40, 22            // a2 (original)
    hw_mtpr 30, PT_KSP
    // Set handler args
    hw_mfpr 16, IPR_EXC_SUM        // a0 = exc_sum
    hw_mfpr 17, IPR_EXC_ADDR       // a1 = exc_addr
    mov     $31, $18                 // a2 = 0
    // Dispatch
    hw_mtpr 31, IPR_PS
    hw_mfpr 29, PT_KGP
    hw_mfpr 1,  PT_ENTARITH
    hw_mtpr 1,  IPR_EXC_ADDR
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 22, PT_S4
    hw_rei


// ============================================================================
// Extended: INTERRUPT handler
// ============================================================================
ext_interrupt:
    hw_mtpr 1,  PT_S0
    hw_mtpr 2,  PT_S1
    hw_mtpr 3,  PT_S2
    hw_mtpr 22, PT_S4
    // Read PS and encode pre-interrupt IPL in PS[7:4] for exception frame
    hw_mfpr 1,  IPR_PS
    hw_mfpr 2,  IPR_IPL
    sll     $2, 4, $2
    bis     $1, $2, $1
    srl     $1, 3, $3
    blbc    $3, 1f
    hw_mtpr 30, PT_USP
    hw_mfpr 30, PT_KSP
1:  lda     $30, -48($30)
    mov     $30, $22
    sll     $22, 22, $22
    srl     $22, 22, $22
    hw_st   1,  0, 22             // PS
    hw_mfpr 1,  IPR_EXC_ADDR
    hw_st   1,  8, 22             // PC
    hw_st   29, 16, 22            // GP
    hw_st   16, 24, 22            // a0
    hw_st   17, 32, 22            // a1
    hw_st   18, 40, 22            // a2
    hw_mtpr 30, PT_KSP
    // Classify interrupt from ISR
    hw_mfpr 17, IPR_ISR             // a1 = ISR
    // Check timer (ISR bit 4)
    and     $17, 0x10, $1
    bne     $1, 2f
    lda     $16, 3($31)              // a0 = 3 (device interrupt)
    br      $31, 3f
2:  lda     $16, 1($31)              // a0 = 1 (clock interrupt)
    // Acknowledge timer: write-1-to-clear STATUS at PA 0x80010018
    ldah    $3, -0x7FFF($31)         // $3 = 0x...80010000 (timer base PA)
    hw_st   16, 0x18, 3              // store 1 to PA 0x80010018 (TIMER_STATUS)
3:  mov     $31, $18                 // a2 = 0
    hw_mtpr 31, IPR_PS
    // Raise IPL to 7 to prevent re-entrant interrupts after hw_rei
    lda     $1, 7($31)
    hw_mtpr 1,  IPR_IPL
    hw_mfpr 29, PT_KGP
    hw_mfpr 1,  PT_ENTINT
    hw_mtpr 1,  IPR_EXC_ADDR
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 22, PT_S4
    hw_rei


// ============================================================================
// Extended: DTB_MISS fault (page not present in page table)
// ============================================================================
ext_dtb_miss_fault:
    // ---- EV67-style prefetch suppression ----
    // The GENERIC kernel uses ldl/ldq $31,disp(Rb) as prefetch (EV67+ feature).
    // On EV56, these are real memory loads that fault on unmapped addresses.
    // Detect load-to-$31 instructions and silently skip them.
    // At entry: $1-$4 are scratch (originals saved in PT_S0-PT_S3).
    hw_mfpr 1,  IPR_EXC_ADDR      // $1 = faulting instruction VA (KSEG)
    sll     $1, 22, $2
    srl     $2, 22, $2             // $2 = PA (clear KSEG bits 63:42)
    hw_ld   3,  0, 2              // $3 = qword at PA (contains the instruction)
    and     $1, 4, $4              // check bit 2 of address
    beq     $4, 1f
    srl     $3, 32, $3             // instruction is in upper 32 bits
1:  // $3 = 32-bit faulting instruction (zero-extended)
    srl     $3, 21, $4
    and     $4, 0x1F, $4           // $4 = Ra field (bits 25:21)
    cmpeq   $4, 31, $4
    beq     $4, ext_dtb_miss_fault_real   // Ra != 31 → real fault
    // Ra is $31 — check opcode is a load: ldl(0x28), ldq(0x29), lds(0x22), ldt(0x23)
    srl     $3, 26, $4             // $4 = opcode (6 bits)
    subq    $4, 0x28, $3
    cmpule  $3, 1, $3              // opcode in {0x28, 0x29}?
    bne     $3, ext_dtb_prefetch_skip
    subq    $4, 0x22, $3
    cmpule  $3, 1, $3              // opcode in {0x22, 0x23}?
    beq     $3, ext_dtb_miss_fault_real   // not a recognized load → real fault
ext_dtb_prefetch_skip:
    // Load-to-$31 (prefetch). Skip instruction and return.
    lda     $1, 4($1)              // advance exc_addr past faulting instr
    hw_mtpr 1,  IPR_EXC_ADDR
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 4,  PT_S3
    hw_rei
    // ---- End prefetch suppression ----

ext_dtb_miss_fault_real:
    // Restore page-walk scratch first
    hw_mfpr 3,  PT_S2
    hw_mfpr 4,  PT_S3
    // Now use $1/$2/$3/$22 for frame building
    hw_mtpr 3,  PT_S2              // re-save $3 (now restored to original)
    hw_mtpr 22, PT_S4
    // Read PS and encode current IPL in PS[7:4] for exception frame
    hw_mfpr 1,  IPR_PS
    hw_mfpr 2,  IPR_IPL
    sll     $2, 4, $2
    bis     $1, $2, $1
    srl     $1, 3, $3
    blbc    $3, 1f
    hw_mtpr 30, PT_USP
    hw_mfpr 30, PT_KSP
1:  lda     $30, -48($30)
    mov     $30, $22
    sll     $22, 22, $22
    srl     $22, 22, $22
    hw_st   1,  0, 22
    hw_mfpr 1,  IPR_EXC_ADDR
    hw_st   1,  8, 22
    hw_st   29, 16, 22
    hw_st   16, 24, 22
    hw_st   17, 32, 22
    hw_st   18, 40, 22
    hw_mtpr 30, PT_KSP
    // a0=VA, a1=mmcsr (0=TNV), a2=cause (mm_stat bit0: 0=read, 1=write)
    hw_mfpr 16, IPR_VA
    hw_mfpr 18, IPR_MM_STAT
    and     $18, 1, $18             // a2 = cause (bit 0: 0=read, 1=write)
    mov     $31, $17                // a1 = 0 (TNV - translation not valid)
    hw_mtpr 31, IPR_PS
    hw_mfpr 29, PT_KGP
    hw_mfpr 1,  PT_ENTMM
    hw_mtpr 1,  IPR_EXC_ADDR
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 22, PT_S4
    hw_rei


// ============================================================================
// Extended: DTB_ACV handler (access control violation on data access)
// Entry: $1=VA (from IPR_VA), $2=mm_stat (from IPR_MM_STAT), $3/$4 saved
// Dispatches to kernel entMM with mmcsr=1 (ACV), cause=mm_stat[0] (0=rd,1=wr)
// ============================================================================
ext_dtb_acv:
    hw_mtpr 22, PT_S4
    hw_mfpr 3,  IPR_MM_STAT        // $3 = mm_stat (need bit 0 for cause)
    and     $3, 1, $3               // $3 = cause (0=read, 1=write)
    // Read PS and encode current IPL in PS[7:4] for exception frame
    hw_mfpr 1,  IPR_PS
    hw_mfpr 2,  IPR_IPL
    sll     $2, 4, $2
    bis     $1, $2, $1
    srl     $1, 3, $2
    blbc    $2, 1f
    hw_mtpr 30, PT_USP
    hw_mfpr 30, PT_KSP
1:  lda     $30, -48($30)
    mov     $30, $22
    sll     $22, 22, $22
    srl     $22, 22, $22
    hw_st   1,  0, 22             // PS
    hw_mfpr 1,  IPR_EXC_ADDR
    hw_st   1,  8, 22             // PC
    hw_st   29, 16, 22            // GP
    hw_st   16, 24, 22            // a0
    hw_st   17, 32, 22            // a1
    hw_st   18, 40, 22            // a2
    hw_mtpr 30, PT_KSP
    // Set up entMM args: a0=VA, a1=1 (ACV), a2=cause (0=read, 1=write)
    hw_mfpr 16, IPR_VA              // a0 = faulting VA
    lda     $17, 1($31)             // a1 = 1 (ACV)
    mov     $3, $18                 // a2 = cause (saved from mm_stat[0])
    hw_mtpr 31, IPR_PS
    hw_mfpr 29, PT_KGP
    hw_mfpr 1,  PT_ENTMM
    hw_mtpr 1,  IPR_EXC_ADDR
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 22, PT_S4
    hw_rei


// ============================================================================
// Extended: ITB_MISS fault (page not present in page table)
// ============================================================================
ext_itb_miss_fault:
    hw_mfpr 3,  PT_S2
    hw_mfpr 4,  PT_S3
    hw_mtpr 3,  PT_S2
    hw_mtpr 22, PT_S4
    // Read PS and encode current IPL in PS[7:4] for exception frame
    hw_mfpr 1,  IPR_PS
    hw_mfpr 2,  IPR_IPL
    sll     $2, 4, $2
    bis     $1, $2, $1
    srl     $1, 3, $3
    blbc    $3, 1f
    hw_mtpr 30, PT_USP
    hw_mfpr 30, PT_KSP
1:  lda     $30, -48($30)
    mov     $30, $22
    sll     $22, 22, $22
    srl     $22, 22, $22
    hw_st   1,  0, 22
    hw_mfpr 1,  IPR_EXC_ADDR
    hw_st   1,  8, 22
    hw_st   29, 16, 22
    hw_st   16, 24, 22
    hw_st   17, 32, 22
    hw_st   18, 40, 22
    hw_mtpr 30, PT_KSP
    // a0=VA, a1=1(ACV), a2=-1(ifetch)
    hw_mfpr 16, IPR_VA
    lda     $17, 1($31)
    lda     $18, -1($31)
    hw_mtpr 31, IPR_PS
    hw_mfpr 29, PT_KGP
    hw_mfpr 1,  PT_ENTMM
    hw_mtpr 1,  IPR_EXC_ADDR
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 22, PT_S4
    hw_rei


// ============================================================================
// Extended: ITB_ACV handler
// ============================================================================
ext_itb_acv:
    hw_mtpr 1,  PT_S0
    hw_mtpr 2,  PT_S1
    hw_mtpr 3,  PT_S2
    hw_mtpr 22, PT_S4
    // Read PS and encode current IPL in PS[7:4] for exception frame
    hw_mfpr 1,  IPR_PS
    hw_mfpr 2,  IPR_IPL
    sll     $2, 4, $2
    bis     $1, $2, $1
    srl     $1, 3, $3
    blbc    $3, 1f
    hw_mtpr 30, PT_USP
    hw_mfpr 30, PT_KSP
1:  lda     $30, -48($30)
    mov     $30, $22
    sll     $22, 22, $22
    srl     $22, 22, $22
    hw_st   1,  0, 22
    hw_mfpr 1,  IPR_EXC_ADDR
    hw_st   1,  8, 22
    hw_st   29, 16, 22
    hw_st   16, 24, 22
    hw_st   17, 32, 22
    hw_st   18, 40, 22
    hw_mtpr 30, PT_KSP
    hw_mfpr 16, IPR_VA              // a0 = VA
    lda     $17, 1($31)              // a1 = 1 (ACV)
    lda     $18, -1($31)             // a2 = -1 (ifetch)
    hw_mtpr 31, IPR_PS
    hw_mfpr 29, PT_KGP
    hw_mfpr 1,  PT_ENTMM
    hw_mtpr 1,  IPR_EXC_ADDR
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 22, PT_S4
    hw_rei


// ============================================================================
// Extended: DTB_MISS_NATIVE handler
// ============================================================================
ext_dtb_miss_native:
    hw_mtpr 1,  PT_S0
    hw_mtpr 2,  PT_S1
    hw_mtpr 3,  PT_S2
    hw_mtpr 22, PT_S4
    // Read PS and encode current IPL in PS[7:4] for exception frame
    hw_mfpr 1,  IPR_PS
    hw_mfpr 2,  IPR_IPL
    sll     $2, 4, $2
    bis     $1, $2, $1
    srl     $1, 3, $3
    blbc    $3, 1f
    hw_mtpr 30, PT_USP
    hw_mfpr 30, PT_KSP
1:  lda     $30, -48($30)
    mov     $30, $22
    sll     $22, 22, $22
    srl     $22, 22, $22
    hw_st   1,  0, 22
    hw_mfpr 1,  IPR_EXC_ADDR
    hw_st   1,  8, 22
    hw_st   29, 16, 22
    hw_st   16, 24, 22
    hw_st   17, 32, 22
    hw_st   18, 40, 22
    hw_mtpr 30, PT_KSP
    hw_mfpr 16, IPR_VA
    hw_mfpr 17, IPR_MM_STAT
    lda     $18, -1($31)
    hw_mtpr 31, IPR_PS
    hw_mfpr 29, PT_KGP
    hw_mfpr 1,  PT_ENTMM
    hw_mtpr 1,  IPR_EXC_ADDR
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 22, PT_S4
    hw_rei


// ============================================================================
// Extended: UNALIGN handler
// ============================================================================
ext_unalign:
    hw_mtpr 1,  PT_S0
    hw_mtpr 2,  PT_S1
    hw_mtpr 3,  PT_S2
    hw_mtpr 22, PT_S4
    // Read PS and encode current IPL in PS[7:4] for exception frame
    hw_mfpr 1,  IPR_PS
    hw_mfpr 2,  IPR_IPL
    sll     $2, 4, $2
    bis     $1, $2, $1
    srl     $1, 3, $3
    blbc    $3, 1f
    hw_mtpr 30, PT_USP
    hw_mfpr 30, PT_KSP
1:  lda     $30, -48($30)
    mov     $30, $22
    sll     $22, 22, $22
    srl     $22, 22, $22
    hw_st   1,  0, 22
    hw_mfpr 1,  IPR_EXC_ADDR
    hw_st   1,  8, 22
    hw_st   29, 16, 22
    hw_st   16, 24, 22
    hw_st   17, 32, 22
    hw_st   18, 40, 22
    hw_mtpr 30, PT_KSP
    hw_mfpr 16, IPR_VA
    hw_mfpr 17, IPR_MM_STAT
    mov     $31, $18
    hw_mtpr 31, IPR_PS
    hw_mfpr 29, PT_KGP
    hw_mfpr 1,  PT_ENTUNA
    hw_mtpr 1,  IPR_EXC_ADDR
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 22, PT_S4
    hw_rei


// ============================================================================
// Extended: OPCDEC handler
// ============================================================================
ext_opcdec:
    hw_mtpr 1,  PT_S0
    hw_mtpr 2,  PT_S1
    hw_mtpr 3,  PT_S2
    hw_mtpr 22, PT_S4
    // Read PS and encode current IPL in PS[7:4] for exception frame
    hw_mfpr 1,  IPR_PS
    hw_mfpr 2,  IPR_IPL
    sll     $2, 4, $2
    bis     $1, $2, $1
    srl     $1, 3, $3
    blbc    $3, 1f
    hw_mtpr 30, PT_USP
    hw_mfpr 30, PT_KSP
1:  lda     $30, -48($30)
    mov     $30, $22
    sll     $22, 22, $22
    srl     $22, 22, $22
    hw_st   1,  0, 22
    hw_mfpr 1,  IPR_EXC_ADDR
    hw_st   1,  8, 22
    hw_st   29, 16, 22
    hw_st   16, 24, 22
    hw_st   17, 32, 22
    hw_st   18, 40, 22
    hw_mtpr 30, PT_KSP
    lda     $16, 4($31)              // a0 = 4 (OPCDEC)
    mov     $31, $17
    mov     $31, $18
    hw_mtpr 31, IPR_PS
    hw_mfpr 29, PT_KGP
    hw_mfpr 1,  PT_ENTIF
    hw_mtpr 1,  IPR_EXC_ADDR
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 22, PT_S4
    hw_rei


// ============================================================================
// Extended: FEN handler
// ============================================================================
ext_fen:
    hw_mtpr 1,  PT_S0
    hw_mtpr 2,  PT_S1
    hw_mtpr 3,  PT_S2
    hw_mtpr 22, PT_S4
    // Read PS and encode current IPL in PS[7:4] for exception frame
    hw_mfpr 1,  IPR_PS
    hw_mfpr 2,  IPR_IPL
    sll     $2, 4, $2
    bis     $1, $2, $1
    srl     $1, 3, $3
    blbc    $3, 1f
    hw_mtpr 30, PT_USP
    hw_mfpr 30, PT_KSP
1:  lda     $30, -48($30)
    mov     $30, $22
    sll     $22, 22, $22
    srl     $22, 22, $22
    hw_st   1,  0, 22
    hw_mfpr 1,  IPR_EXC_ADDR
    hw_st   1,  8, 22
    hw_st   29, 16, 22
    hw_st   16, 24, 22
    hw_st   17, 32, 22
    hw_st   18, 40, 22
    hw_mtpr 30, PT_KSP
    lda     $16, 3($31)               // a0 = 3 (FEN)
    mov     $31, $17
    mov     $31, $18
    hw_mtpr 31, IPR_PS
    hw_mfpr 29, PT_KGP
    hw_mfpr 1,  PT_ENTIF
    hw_mtpr 1,  IPR_EXC_ADDR
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 22, PT_S4
    hw_rei


// ============================================================================
// Extended: wrent - Write System Entry Point
// a0 ($16) = handler address, a1 ($17) = which entry (0-5)
// ============================================================================
ext_wrent:
    hw_mtpr 1,  PT_S0              // save $1 (used as scratch for cmpeq)
    beq     $17, 1f                  // 0 → entInt
    cmpeq   $17, 1, $1
    bne     $1, 2f                   // 1 → entArith
    cmpeq   $17, 2, $1
    bne     $1, 3f                   // 2 → entMM
    cmpeq   $17, 3, $1
    bne     $1, 4f                   // 3 → entIF
    cmpeq   $17, 4, $1
    bne     $1, 5f                   // 4 → entUna
    cmpeq   $17, 5, $1
    bne     $1, 6f                   // 5 → entSys
    // 6+ → entDbg or unknown: store in PT_ENTDBG (pt17) and return
    hw_mtpr 16, PT_S5              // pt17 = entDbg (we don't dispatch to it)
    hw_mfpr 1,  PT_S0
    hw_rei
1:  hw_mtpr 16, PT_ENTINT
    hw_mfpr 1,  PT_S0
    hw_rei
2:  hw_mtpr 16, PT_ENTARITH
    hw_mfpr 1,  PT_S0
    hw_rei
3:  hw_mtpr 16, PT_ENTMM
    hw_mfpr 1,  PT_S0
    hw_rei
4:  hw_mtpr 16, PT_ENTIF
    hw_mfpr 1,  PT_S0
    hw_rei
5:  hw_mtpr 16, PT_ENTUNA
    hw_mfpr 1,  PT_S0
    hw_rei
6:  hw_mtpr 16, PT_ENTSYS
    hw_mfpr 1,  PT_S0
    hw_rei


// ============================================================================
// Extended: tbi - TLB Invalidate
// a0 ($16) = type, a1 ($17) = VA (for single-entry)
// Negative: -1=all, -2=ITLB, -3=DTLB
// Positive: 1=single ITB, 2=single DTB, 3=single both
// ============================================================================
ext_tbi:
    hw_mtpr 1,  PT_S0              // save $1 (used as scratch)
    blt     $16, tbi_all
    // Single invalidate
    and     $16, 1, $1
    beq     $1, tbi_s_dtb
    hw_mtpr 17, IPR_ITB_IS          // invalidate ITB entry
tbi_s_dtb:
    and     $16, 2, $1
    beq     $1, tbi_done
    hw_mtpr 17, IPR_DTB_IS          // invalidate DTB entry
tbi_done:
    hw_mfpr 1,  PT_S0
    hw_rei

tbi_all:
    // a0 < 0: invalidate all
    addq    $16, 2, $1
    beq     $1, tbi_all_itb          // -2 → ITB only
    addq    $16, 3, $1
    beq     $1, tbi_all_dtb          // -3 → DTB only
    // -1 or other: both
    hw_mtpr 31, IPR_ITB_IA
    hw_mtpr 31, IPR_DTB_IA
    hw_mfpr 1,  PT_S0
    hw_rei
tbi_all_itb:
    hw_mtpr 31, IPR_ITB_IA
    hw_mfpr 1,  PT_S0
    hw_rei
tbi_all_dtb:
    hw_mtpr 31, IPR_DTB_IA
    hw_mfpr 1,  PT_S0
    hw_rei


// ============================================================================
// Extended: rti - Return from Trap/Interrupt
// Pop 48-byte frame from kernel stack, restore PS/PC/GP/a0-a2, hw_rei
// ============================================================================
ext_rti:
    hw_mtpr 1,  PT_S0              // save $1 (used as scratch for frame read)
    hw_mtpr 2,  PT_S1              // save $2 (used as scratch for frame read)
    hw_mtpr 3,  PT_S2              // save $3 (for mode check)
    hw_mtpr 22, PT_S4              // save $22 (for PA conversion)
    // Use $30 directly as frame pointer.  The kernel passes $30 pointing to
    // the PAL frame base (after popping its own frame with addq sp,0xb8,sp).
    // Do NOT load from PT_KSP: after a nested kernel-mode exception (e.g.
    // timer interrupt during syscall), PT_KSP no longer points to this frame.
    mov     $30, $22
    sll     $22, 22, $22
    srl     $22, 22, $22
    // Read frame
    hw_ld   1,  0, 22             // PS
    hw_ld   2,  8, 22             // return PC
    hw_ld   29, 16, 22            // GP
    hw_ld   16, 24, 22            // a0
    hw_ld   17, 32, 22            // a1
    hw_ld   18, 40, 22            // a2
    // Pop frame
    lda     $30, 48($30)
    // Extract and restore IPL from PS[7:4]
    srl     $1, 4, $3
    and     $3, 0xF, $3
    hw_mtpr 3,  IPR_IPL
    // Restore PS and set return address
    hw_mtpr 1,  IPR_PS
    hw_mtpr 2,  IPR_EXC_ADDR
    // Check if returning to user mode
    srl     $1, 3, $3
    blbc    $3, 1f
    // User return: save kernel SP for next user-to-kernel transition
    hw_mtpr 30, PT_KSP
    hw_mfpr 30, PT_USP
    br      $31, 2f
1:  // Kernel return: do NOT update PT_KSP.
    // PT_KSP retains the correct value from the original user-to-kernel entry.
2:  hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 22, PT_S4
    hw_rei


// ============================================================================
// Extended: retsys - Return from System Call
// Similar to rti but always returns to user mode
// ============================================================================
ext_retsys:
    hw_mtpr 1,  PT_S0
    hw_mtpr 2,  PT_S1
    hw_mtpr 3,  PT_S2
    hw_mtpr 22, PT_S4
    // Use $30 directly as frame pointer (same fix as ext_rti)
    mov     $30, $22
    sll     $22, 22, $22
    srl     $22, 22, $22
    hw_ld   1,  0, 22             // PS
    hw_ld   2,  8, 22             // return PC
    hw_ld   29, 16, 22            // GP
    hw_ld   16, 24, 22
    hw_ld   17, 32, 22
    hw_ld   18, 40, 22
    lda     $30, 48($30)
    // Extract and restore IPL from PS[7:4]
    srl     $1, 4, $3
    and     $3, 0xF, $3
    hw_mtpr 3,  IPR_IPL
    hw_mtpr 1,  IPR_PS
    hw_mtpr 2,  IPR_EXC_ADDR
    // Save KSP, restore USP (always returning to user)
    hw_mtpr 30, PT_KSP
    hw_mfpr 30, PT_USP
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 22, PT_S4
    hw_rei


// ============================================================================
// Extended: swpctx - Swap Process Context
// a0 ($16) = new PCB physical address
// Returns: v0 ($0) = old PCB physical address
// PCB layout: [0]=KSP, [8]=USP, [16]=PTBR, [24]=ASN, [32]=UNIQUE, [40]=FEN
// ============================================================================
ext_swpctx:
    hw_mtpr 1,  PT_S0
    hw_mtpr 2,  PT_S1
    // Get old PCBB
    hw_mfpr 0,  PT_PCBB             // v0 = old PCB (return value)
    mov     $0, $2                    // $2 = old PCB PA
    beq     $2, swpctx_load_new      // no old PCB → skip save (early boot)
    // Save current state to old PCB
    // Use actual $30 (sp) as the kernel SP to save, because do_switch_stack
    // in the kernel adjusts $30 before calling swpctx but PT_KSP is stale.
    hw_st   30, 0, 2               // PCB[0] = KSP (from actual $30)
    hw_mtpr 30, PT_KSP             // Also update PT_KSP shadow to match
    hw_mfpr 1,  PT_USP
    hw_st   1,  8, 2               // PCB[8] = USP
    // Note: Do NOT save PTBR, UNIQUE, or FEN back to old PCB.
    // The kernel manages these fields and writes them to the PCB before
    // calling swpctx. Saving the current (old) values would clobber
    // the new values the kernel just wrote, especially during self-swap
    // (activate_mm reloads with the same PCB but updated PTBR).
swpctx_load_new:
    // Load new state from new PCB (a0 = $16)
    hw_ld   30, 0, 16              // new KSP -> directly into $30 (sp)
    hw_mtpr 30, PT_KSP             // Also update PT_KSP shadow
    hw_ld   1,  8, 16              // new USP
    hw_mtpr 1,  PT_USP
    hw_ld   1,  16, 16             // new PTBR (PFN from PCB)
    hw_mtpr 1,  IPR_PTBR           // hardware PTBR = PFN
    sll     $1, 13, $1             // convert PFN to physical address
    hw_mtpr 1,  PT_PTBR            // cached copy = PA (for page table walk)
    hw_ld   1,  24, 16             // new PCC(lo32) | ASN(hi32)
    srl     $1, 32, $1             // extract ASN from high 32 bits
    hw_mtpr 1,  IPR_DTB_ASN
    hw_mtpr 1,  IPR_ITB_ASN
    hw_ld   1,  32, 16             // new UNIQUE
    hw_mtpr 1,  PT_UNIQUE
    hw_ld   1,  40, 16             // new FEN
    hw_mtpr 1,  IPR_FEN
    // Update PCBB
    hw_mtpr 16, PT_PCBB
    hw_mtpr 16, IPR_PCBB
    // Flush TLBs
    hw_mtpr 31, IPR_DTB_IA
    hw_mtpr 31, IPR_ITB_IA
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_rei


// ============================================================================
// Extended: callsys - System Call Entry
// ============================================================================
ext_callsys:
    hw_mtpr 1,  PT_S0
    hw_mtpr 2,  PT_S1
    hw_mtpr 3,  PT_S2
    hw_mtpr 22, PT_S4
    // Read PS and encode current IPL in PS[7:4] for exception frame
    hw_mfpr 1,  IPR_PS
    hw_mfpr 2,  IPR_IPL
    sll     $2, 4, $2
    bis     $1, $2, $1
    // callsys always comes from user mode
    hw_mtpr 30, PT_USP
    hw_mfpr 30, PT_KSP
    lda     $30, -48($30)
    mov     $30, $22
    sll     $22, 22, $22
    srl     $22, 22, $22
    hw_st   1,  0, 22             // PS
    hw_mfpr 1,  IPR_EXC_ADDR
    hw_st   1,  8, 22             // PC
    hw_st   29, 16, 22            // GP
    hw_st   16, 24, 22            // a0
    hw_st   17, 32, 22            // a1
    hw_st   18, 40, 22            // a2
    hw_mtpr 30, PT_KSP
    // a0-a5 ($16-$21) already have syscall args, v0 ($0) has syscall number
    // Kernel entSys expects these as-is
    hw_mtpr 31, IPR_PS
    hw_mfpr 29, PT_KGP
    hw_mfpr 1,  PT_ENTSYS
    hw_mtpr 1,  IPR_EXC_ADDR
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 22, PT_S4
    hw_rei


// ============================================================================
// Extended: bpt - Breakpoint Trap
// ============================================================================
ext_bpt:
    hw_mtpr 1,  PT_S0
    hw_mtpr 2,  PT_S1
    hw_mtpr 3,  PT_S2
    hw_mtpr 22, PT_S4
    // Read PS and encode current IPL in PS[7:4] for exception frame
    hw_mfpr 1,  IPR_PS
    hw_mfpr 2,  IPR_IPL
    sll     $2, 4, $2
    bis     $1, $2, $1
    srl     $1, 3, $3
    blbc    $3, 1f
    hw_mtpr 30, PT_USP
    hw_mfpr 30, PT_KSP
1:  lda     $30, -48($30)
    mov     $30, $22
    sll     $22, 22, $22
    srl     $22, 22, $22
    hw_st   1,  0, 22
    hw_mfpr 1,  IPR_EXC_ADDR
    hw_st   1,  8, 22
    hw_st   29, 16, 22
    hw_st   16, 24, 22
    hw_st   17, 32, 22
    hw_st   18, 40, 22
    hw_mtpr 30, PT_KSP
    mov     $31, $16                  // a0 = 0 (BPT)
    mov     $31, $17
    mov     $31, $18
    hw_mtpr 31, IPR_PS
    hw_mfpr 29, PT_KGP
    hw_mfpr 1,  PT_ENTIF
    hw_mtpr 1,  IPR_EXC_ADDR
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 22, PT_S4
    hw_rei


// ============================================================================
// Extended: bugchk - Bug Check Trap
// ============================================================================
ext_bugchk:
    hw_mtpr 1,  PT_S0
    hw_mtpr 2,  PT_S1
    hw_mtpr 3,  PT_S2
    hw_mtpr 22, PT_S4
    // Read PS and encode current IPL in PS[7:4] for exception frame
    hw_mfpr 1,  IPR_PS
    hw_mfpr 2,  IPR_IPL
    sll     $2, 4, $2
    bis     $1, $2, $1
    srl     $1, 3, $3
    blbc    $3, 1f
    hw_mtpr 30, PT_USP
    hw_mfpr 30, PT_KSP
1:  lda     $30, -48($30)
    mov     $30, $22
    sll     $22, 22, $22
    srl     $22, 22, $22
    hw_st   1,  0, 22
    hw_mfpr 1,  IPR_EXC_ADDR
    hw_st   1,  8, 22
    hw_st   29, 16, 22
    hw_st   16, 24, 22
    hw_st   17, 32, 22
    hw_st   18, 40, 22
    hw_mtpr 30, PT_KSP
    lda     $16, 1($31)              // a0 = 1 (BUGCHK)
    mov     $31, $17
    mov     $31, $18
    hw_mtpr 31, IPR_PS
    hw_mfpr 29, PT_KGP
    hw_mfpr 1,  PT_ENTIF
    hw_mtpr 1,  IPR_EXC_ADDR
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 22, PT_S4
    hw_rei


// ============================================================================
// Extended: gentrap - General Trap
// ============================================================================
ext_gentrap:
    hw_mtpr 1,  PT_S0
    hw_mtpr 2,  PT_S1
    hw_mtpr 3,  PT_S2
    hw_mtpr 22, PT_S4
    // Read PS and encode current IPL in PS[7:4] for exception frame
    hw_mfpr 1,  IPR_PS
    hw_mfpr 2,  IPR_IPL
    sll     $2, 4, $2
    bis     $1, $2, $1
    srl     $1, 3, $3
    blbc    $3, 1f
    hw_mtpr 30, PT_USP
    hw_mfpr 30, PT_KSP
1:  lda     $30, -48($30)
    mov     $30, $22
    sll     $22, 22, $22
    srl     $22, 22, $22
    hw_st   1,  0, 22
    hw_mfpr 1,  IPR_EXC_ADDR
    hw_st   1,  8, 22
    hw_st   29, 16, 22
    hw_st   16, 24, 22
    hw_st   17, 32, 22
    hw_st   18, 40, 22
    hw_mtpr 30, PT_KSP
    lda     $16, 2($31)              // a0 = 2 (GENTRAP)
    mov     $31, $17
    mov     $31, $18
    hw_mtpr 31, IPR_PS
    hw_mfpr 29, PT_KGP
    hw_mfpr 1,  PT_ENTIF
    hw_mtpr 1,  IPR_EXC_ADDR
    hw_mfpr 1,  PT_S0
    hw_mfpr 2,  PT_S1
    hw_mfpr 3,  PT_S2
    hw_mfpr 22, PT_S4
    hw_rei


// ============================================================================
// End of PALcode
// ============================================================================
