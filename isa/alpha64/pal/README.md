# Alpha PALcode Support

This directory contains the ISA specifications for Alpha's Privileged Architecture Library (PALcode) support, including virtual memory translation and exception handling.

## Overview

PALcode is Alpha's mechanism for implementing privileged operations. Unlike other architectures where these are hardwired, Alpha implements them in firmware that runs in a special CPU mode with access to internal processor registers (IPRs).

## Files

### Core PAL Instructions

| File | Description |
|------|-------------|
| `ipr_defs.isa` | Internal Processor Register definitions |
| `call_pal.isa` | CALL_PAL instruction - gateway to PALcode |
| `hw_mfpr.isa` | HW_MFPR - read from processor register |
| `hw_mtpr.isa` | HW_MTPR - write to processor register |
| `hw_rei.isa` | HW_REI - return from exception/interrupt |
| `hw_ld.isa` | HW_LD - physical memory load |
| `hw_st.isa` | HW_ST - physical memory store |

### MMU/TLB Aspects

| File | Description |
|------|-------------|
| `itb.isa` | ITB (Instruction TLB) lookup aspect |
| `dtb_load.isa` | DTB lookup aspect for load instructions |
| `dtb_store.isa` | DTB lookup aspect for store instructions |
| `mmu.isa` | MMU translation documentation |
| `tbi.isa` | TLB invalidation notes |

### Exception/Interrupt Handling

| File | Description |
|------|-------------|
| `exception.isa` | Exception dispatch and PAL entry points |
| `interrupt.isa` | Interrupt handling and priority logic |

### Examples (examples/)

| File | Description |
|------|-------------|
| `ldq_vm.isa` | LDQ with DTB translation |
| `stq_vm.isa` | STQ with DTB translation |
| `addq_vm.isa` | ADDQ with ITB translation for fetch |

## Key Concepts

### PAL Mode

When `pal_mode == 1`, the processor:
- Can execute HW_MFPR, HW_MTPR, HW_REI, HW_LD, HW_ST
- Has access to all IPRs including TLB control
- Uses physical addressing (bypasses TLB)

### IPR Categories

1. **Core State** (0x08-0x0F): pal_base, exc_addr, ps, ipl, etc.
2. **Exception/Interrupt** (0x10-0x12): exc_sum, exc_mask, isr, etc.
3. **Virtual Memory** (0x13-0x1F): va, ptbr, vptptr, dtb/itb control
4. **System** (0x20-0x26): whami, pcbb, unique, sysval, pcc
5. **PAL Temps** (0x40-0x57): pt0-pt23 scratch registers

### TLB Structure

- 32-entry Data TLB (DTB)
- 32-entry Instruction TLB (ITB)
- Each entry: tag (VPN), PTE, valid bit
- Write to DTB_PTE/DTB_TAG triggers TLB update

### Linux PALcode Entry Points

| Function | Code | Description |
|----------|------|-------------|
| halt | 0x00 | Stop processor |
| callsys | 0x83 | System call |
| retsys | 0x3F | Return from syscall |
| rti | 0x3D | Return from interrupt |
| swpctx | 0x30 | Swap process context |
| tbi | 0x33 | TLB invalidate |
| wrent | 0x34 | Write entry point |
| imb | 0x86 | Instruction memory barrier |

## Usage

To use PALcode in a full system:

1. Load PALcode binary at physical address in `pal_base`
2. Initialize IPRs (ptbr, entry points in pt3-pt8, etc.)
3. User/kernel code uses `CALL_PAL #function` to invoke
4. PALcode executes, modifies state, returns via `HW_REI`

## Virtual Memory

Alpha uses a 3-level page table for 43-bit virtual addresses:
- 8KB pages (13-bit offset)
- 1024 entries per level (10 bits each)
- 64-bit PTEs with PFN, permissions, valid bit

### TLB Architecture

Unlike RISC-V which does a hardware page table walk on TLB miss, Alpha has an **architectural TLB** that traps to PALcode on miss:

```
Instruction Fetch:
  1. Check ITB for VPN match
  2. If hit: Use PTE.PFN for physical address
  3. If miss: Trap to PAL_itb_miss (0x140)
  4. PALcode walks page table, fills ITB via HW_MTPR
  5. Return via HW_REI to retry instruction

Data Access:
  1. Check DTB for VPN match
  2. If hit: Check permissions (KRE/KWE or URE/UWE based on mode)
  3. If miss: Trap to PAL_dtb_miss (0x200)
  4. If permission fault: Trap to PAL_dfault (0x280)
  5. PALcode handles fault, returns via HW_REI
```

### TLB Entry Format

```
Tag:  VPN[29:0] (30 bits for 43-bit VA with 13-bit offset)
PTE:  [63:32] PFN
      [15]    UWE (User Write Enable)
      [14]    URE (User Read Enable)
      [11]    KWE (Kernel Write Enable)
      [10]    KRE (Kernel Read Enable)
      [4]     FOE (Fault on Execute)
      [3]     FOW (Fault on Write)
      [2]     FOR (Fault on Read)
      [1]     ASM (Address Space Match - global)
      [0]     V   (Valid)
```

### Using the MMU Aspects

The ITB/DTB aspects can be included in instructions:

```
// For instruction fetch (all instructions):
// Include itb.isa which provides pc_pa (physical PC)

// For loads:
// Include dtb_load.isa which provides addr_pa (physical address)

// For stores:
// Include dtb_store.isa which provides store_addr_pa

// In PAL mode, all addresses are physical (identity mapped)
```

See `examples/` directory for complete instruction implementations.

## Exception Dispatch

All exceptions trap to PALcode entry points at `pal_base + offset`:

| Offset | Exception | Description |
|--------|-----------|-------------|
| 0x000 | RESET | Processor reset |
| 0x040 | MCHK | Machine check |
| 0x080 | ARITH | Arithmetic (overflow, etc.) |
| 0x0C0 | INTERRUPT | External interrupt |
| 0x100 | DFAULT | Data fault |
| 0x140 | ITB_MISS | Instruction TLB miss |
| 0x180 | ITB_ACV | Instruction access violation |
| 0x200 | DTB_MISS | Data TLB miss |
| 0x240 | DTB_DOUBLE | Nested TLB miss |
| 0x280 | DFAULT | Data permission fault |
| 0x2C0 | UNALIGN | Unaligned access |

## Interrupt Handling

Interrupts are checked at instruction boundaries:

1. Check ISR (Interrupt Summary Register) for pending interrupts
2. Compare pending interrupt priority against IPL
3. If pending > IPL and not in PAL mode, trap to 0x0C0
4. PALcode reads ISR to identify source, handles interrupt
5. Returns via HW_REI with appropriate IPL
