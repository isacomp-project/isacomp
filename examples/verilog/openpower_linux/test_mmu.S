/* Minimal MMU test for OpenPOWER ISAComp processor */
/* Uses numeric register names (no r prefix) for gas compatibility */
/*
 * Memory layout (all page-aligned for POWER9 radix MMU):
 *   0x10000: Partition Table (16 bytes)
 *   0x11000: Process Table  (16 bytes)
 *   0x12000: PGD - Page Global Directory (4KB)
 *   0x13000: PUD - Page Upper Directory  (4KB)
 *   0x14000: PMD low region              (4KB)
 *   0x15000: PTE low region              (4KB)
 *   0x16000: PMD UART region             (4KB)
 *   0x17000: PTE UART region             (4KB)
 */

.section .text
.globl _start
_start:
    /* Phase 1: Write 'H' 'i' '\n' to UART at 0xC0002000 in real mode */
    addis   3, 0, -16384      /* r3 = 0xFFFFFFFF_C0000000 */
    ori     3, 3, 0x2000      /* r3 = 0xFFFFFFFF_C0002000 */

    /* Write 'H' = 0x48 */
    addi    4, 0, 0x48
    stb     4, 0(3)

    /* Write 'i' = 0x69 */
    addi    4, 0, 0x69
    stb     4, 0(3)

    /* Write newline = 0x0A */
    addi    4, 0, 0x0A
    stb     4, 0(3)

    /* ============================================================ */
    /* Phase 2: Set up page tables for radix MMU                    */
    /* ============================================================ */

    /* --- Set up Partition Table at 0x10000 --- */
    addis   5, 0, 1            /* r5 = 0x10000 */

    /* PATE[0] = 0 */
    addi    6, 0, 0
    std     6, 0(5)

    /* PATE[1] = Process table at 0x11000 (page-aligned!) */
    addis   6, 0, 1
    ori     6, 6, 0x1000      /* r6 = 0x11000 */
    std     6, 8(5)

    /* --- Set up Process Table Entry at 0x11000 --- */
    addis   5, 0, 1
    ori     5, 5, 0x1000      /* r5 = 0x11000 */

    /* PRTE[0] = PGD base (0x12000) | RPDS=52 (0x34) */
    /* RPDS (Root Page Dir Size) = floor(log2(8192 entries * 8)) = 16, but
     * Power ISA encodes this differently. For 13-bit index: RPDS = 52.
     * But actually RPDS is the number of significant address bits.
     * For simplicity use the raw PGD base with RPDS in low bits. */
    addis   6, 0, 1
    ori     6, 6, 0x2034      /* r6 = 0x12034 (PGD at 0x12000, RPDS=52) */
    std     6, 0(5)

    /* PRTE[1] = 0 */
    addi    6, 0, 0
    std     6, 8(5)

    /* --- Clear PGD at 0x12000 (512 entries = 4KB) --- */
    addis   5, 0, 1
    ori     5, 5, 0x2000
    addi    7, 0, 0
    addi    8, 0, 512
    mtctr   8
clear_pgd:
    std     7, 0(5)
    addi    5, 5, 8
    bdnz    clear_pgd

    /* PGD[0] -> PUD at 0x13000: Valid=1, Leaf=0, NLB=0x13 */
    /* Entry = 0x8000_0000_0001_3000 */
    addis   5, 0, 1
    ori     5, 5, 0x2000      /* PGD base = 0x12000 */
    addi    6, 0, 1
    sldi    6, 6, 63          /* r6 = 0x8000_0000_0000_0000 (V=1) */
    oris    6, 6, 0x0001
    ori     6, 6, 0x3000      /* r6 = 0x8000_0000_0001_3000 */
    std     6, 0(5)           /* PGD[0] */

    /* --- Clear PUD at 0x13000 --- */
    addis   5, 0, 1
    ori     5, 5, 0x3000
    addi    7, 0, 0
    addi    8, 0, 512
    mtctr   8
clear_pud:
    std     7, 0(5)
    addi    5, 5, 8
    bdnz    clear_pud

    /* PUD[0] -> PMD at 0x14000 (for low addresses) */
    addis   5, 0, 1
    ori     5, 5, 0x3000      /* PUD base = 0x13000 */
    addi    6, 0, 1
    sldi    6, 6, 63          /* V=1 */
    oris    6, 6, 0x0001
    ori     6, 6, 0x4000      /* NLB -> 0x14000 */
    std     6, 0(5)           /* PUD[0] */

    /* PUD[3] -> PMD at 0x16000 (for UART: EA[38:30]=3 for 0xC0002000) */
    addis   5, 0, 1
    ori     5, 5, 0x3000
    addi    6, 0, 1
    sldi    6, 6, 63          /* V=1 */
    oris    6, 6, 0x0001
    ori     6, 6, 0x6000      /* NLB -> 0x16000 */
    std     6, 24(5)          /* PUD[3] at offset 3*8=24 */

    /* --- Clear PMD at 0x14000 (low region) --- */
    addis   5, 0, 1
    ori     5, 5, 0x4000
    addi    7, 0, 0
    addi    8, 0, 512
    mtctr   8
clear_pmd_low:
    std     7, 0(5)
    addi    5, 5, 8
    bdnz    clear_pmd_low

    /* PMD[0] -> PTE at 0x15000 */
    addis   5, 0, 1
    ori     5, 5, 0x4000      /* PMD base = 0x14000 */
    addi    6, 0, 1
    sldi    6, 6, 63
    oris    6, 6, 0x0001
    ori     6, 6, 0x5000
    std     6, 0(5)

    /* --- Clear PTE at 0x15000, then identity-map first 32 pages --- */
    addis   5, 0, 1
    ori     5, 5, 0x5000
    addi    7, 0, 0
    addi    8, 0, 512
    mtctr   8
clear_pte_low:
    std     7, 0(5)
    addi    5, 5, 8
    bdnz    clear_pte_low

    /* Fill PTE[0..31]: identity map first 32 pages (128KB) */
    /* PTE leaf: V=1(bit63), L=1(bit62), RPN[56:12], perms */
    addis   5, 0, 1
    ori     5, 5, 0x5000      /* PTE base = 0x15000 */
    addi    8, 0, 32          /* 32 pages */
    mtctr   8
    addi    9, 0, 0           /* page number */
    /* Build V=1|L=1 = bits 63,62 = 0xC000_0000_0000_0000 */
    addi    10, 0, 3          /* 0x3 */
    sldi    10, 10, 62        /* 0xC000_0000_0000_0000 */

fill_pte_low:
    sldi    6, 9, 12          /* PA = page_num << 12 */
    or      6, 6, 10          /* Add V=1, L=1 */
    ori     6, 6, 0x01BF      /* perms = rwx */
    std     6, 0(5)
    addi    5, 5, 8
    addi    9, 9, 1
    bdnz    fill_pte_low

    /* --- Clear PMD at 0x16000 (UART region) --- */
    addis   5, 0, 1
    ori     5, 5, 0x6000
    addi    7, 0, 0
    addi    8, 0, 512
    mtctr   8
clear_pmd_uart:
    std     7, 0(5)
    addi    5, 5, 8
    bdnz    clear_pmd_uart

    /* PMD[0] -> PTE at 0x17000 */
    addis   5, 0, 1
    ori     5, 5, 0x6000      /* PMD base = 0x16000 */
    addi    6, 0, 1
    sldi    6, 6, 63
    oris    6, 6, 0x0001
    ori     6, 6, 0x7000
    std     6, 0(5)

    /* --- Clear PTE at 0x17000, then map UART page --- */
    addis   5, 0, 1
    ori     5, 5, 0x7000
    addi    7, 0, 0
    addi    8, 0, 512
    mtctr   8
clear_pte_uart:
    std     7, 0(5)
    addi    5, 5, 8
    bdnz    clear_pte_uart

    /* PTE[2] = identity map 0xC0002000 page */
    /* RPN = 0xC0002, entry at PTE offset 2*8=16 */
    addis   5, 0, 1
    ori     5, 5, 0x7000      /* PTE base = 0x17000 */
    addi    6, 0, 3
    sldi    6, 6, 62          /* V=1, L=1 */
    oris    6, 6, 0xC000
    ori     6, 6, 0x21BF      /* RPN = 0xC0002, perms */
    std     6, 16(5)          /* PTE[2] */

    /* ============================================================ */
    /* Phase 3: Write 'M' to UART, then set PTCR and PIDR          */
    /* ============================================================ */
    addis   3, 0, -16384
    ori     3, 3, 0x2000      /* r3 = UART */
    addi    4, 0, 0x4D        /* 'M' */
    stb     4, 0(3)

    /* PIDR (SPR 48) = 0 */
    addi    6, 0, 0
    mtspr   48, 6

    /* PTCR (SPR 464) = 0x10000 */
    addis   6, 0, 1           /* r6 = 0x10000 */
    mtspr   464, 6

    /* Write another 'M' */
    addi    4, 0, 0x4D
    stb     4, 0(3)

    /* Write newline */
    addi    4, 0, 0x0A
    stb     4, 0(3)

    /* ============================================================ */
    /* Phase 4: Enable MMU via rfid                                 */
    /* SRR0 = virtual_mode_entry                                    */
    /* SRR1 = MSR with SF=1, IR=1, DR=1 = 0x8000_0000_0000_0030    */
    /* ============================================================ */

    /* Load address of virtual_mode_entry into SRR0 */
    /* Since identity mapped, VA == PA */
    addi    6, 0, virtual_mode_entry@l
    mtspr   26, 6             /* SRR0 = virtual_mode_entry */

    /* SRR1 = 0x8000_0000_0000_0030 */
    addi    6, 0, 1
    sldi    6, 6, 63          /* SF = 1 */
    ori     6, 6, 0x0030      /* IR=1, DR=1 */
    mtspr   27, 6             /* SRR1 */

    rfid

    .balign 16
virtual_mode_entry:
    /* MMU is on! Write 'U' via virtual UART address */
    /* Must use 0x00000000_C0002000 (not sign-extended 0xFFFFFFFF_C0002000) */
    /* because page tables only map the positive 32-bit address range */
    addi    3, 0, 0           /* r3 = 0 */
    oris    3, 3, 0xC000      /* r3 = 0x00000000_C0000000 */
    ori     3, 3, 0x2000      /* r3 = 0x00000000_C0002000 */

    addi    4, 0, 0x55        /* 'U' */
    stb     4, 0(3)

    addi    4, 0, 0x21        /* '!' */
    stb     4, 0(3)

    addi    4, 0, 0x0A        /* '\n' */
    stb     4, 0(3)

    /* Test data load from virtual address 0 */
    addi    5, 0, 0
    ld      6, 0(5)

    /* Write 'O' 'K' '\n' */
    addi    4, 0, 0x4F        /* 'O' */
    stb     4, 0(3)
    addi    4, 0, 0x4B        /* 'K' */
    stb     4, 0(3)
    addi    4, 0, 0x0A
    stb     4, 0(3)

done_loop:
    b       done_loop

    /* ============================================================ */
    /* Exception Handlers                                           */
    /* ============================================================ */
    .org 0x300
dsi_handler:
    addis   3, 0, -16384
    ori     3, 3, 0x2000
    addi    4, 0, 0x44        /* 'D' */
    stb     4, 0(3)
    addi    4, 0, 0x53        /* 'S' */
    stb     4, 0(3)
    addi    4, 0, 0x49        /* 'I' */
    stb     4, 0(3)
    addi    4, 0, 0x0A
    stb     4, 0(3)
dsi_loop:
    b       dsi_loop

    .org 0x400
isi_handler:
    addis   3, 0, -16384
    ori     3, 3, 0x2000
    addi    4, 0, 0x49        /* 'I' */
    stb     4, 0(3)
    addi    4, 0, 0x53        /* 'S' */
    stb     4, 0(3)
    addi    4, 0, 0x49        /* 'I' */
    stb     4, 0(3)
    addi    4, 0, 0x0A
    stb     4, 0(3)
isi_loop:
    b       isi_loop
