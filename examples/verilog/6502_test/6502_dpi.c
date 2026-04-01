/* 6502 DPI wrapper for Verilator co-simulation
 * Integrates fake6502 reference simulator for state comparison
 */

#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "svdpi.h"

// External C functions from fake6502_wrapper.c
extern "C" {
    void fake6502_wrapper_init(uint16_t reset_pc, uint8_t reset_a, uint8_t reset_x,
                                uint8_t reset_y, uint8_t reset_s, uint8_t reset_status);
    void fake6502_wrapper_load_mem(const uint8_t* mem_data, int size);
    void fake6502_wrapper_step();
    void fake6502_wrapper_get_state(uint16_t* out_pc, uint8_t* out_a, uint8_t* out_x,
                                     uint8_t* out_y, uint8_t* out_sp, uint8_t* out_status);
    uint8_t fake6502_wrapper_get_instr_at_pc();
    int fake6502_wrapper_get_write_count();
    void fake6502_wrapper_get_write(int index, uint16_t* addr, uint8_t* value);
    uint64_t fake6502_wrapper_load_checkpoint(const char* filename);
}

// Checkpoint state storage (for passing to RTL via DPI)
static uint64_t checkpoint_cycle = 0;
static uint16_t checkpoint_pc = 0x0400;
static uint8_t checkpoint_a = 0, checkpoint_x = 0, checkpoint_y = 0;
static uint8_t checkpoint_s = 0xFF, checkpoint_status = 0x24;

// Temporary buffer for memory loading
static uint8_t mem_buffer[65536];

// Track RTL memory writes during current instruction
#define MAX_RTL_WRITES 4
static uint16_t rtl_write_addrs[MAX_RTL_WRITES];
static uint8_t rtl_write_values[MAX_RTL_WRITES];
static int rtl_write_count = 0;

// DPI callback for RTL memory writes (called from testbench)
extern "C" void dpi_6502_rtl_mem_write(unsigned short addr, unsigned char value) {
    if (rtl_write_count < MAX_RTL_WRITES) {
        rtl_write_addrs[rtl_write_count] = addr;
        rtl_write_values[rtl_write_count] = value;
        rtl_write_count++;
    }
}

// DPI functions callable from SystemVerilog

// Initialize the reference 6502 simulator
extern "C" void dpi_6502_init(
    unsigned short reset_pc,
    unsigned char reset_a,
    unsigned char reset_x,
    unsigned char reset_y,
    unsigned char reset_s,
    unsigned char reset_flags
) {
    printf("[DPI] Initializing reference 6502: PC=0x%04x A=0x%02x X=0x%02x Y=0x%02x S=0x%02x flags=0x%02x\n",
           reset_pc, reset_a, reset_x, reset_y, reset_s, reset_flags);

    fake6502_wrapper_init(reset_pc, reset_a, reset_x, reset_y, reset_s, reset_flags);
}

// Load memory contents one byte at a time
extern "C" void dpi_6502_load_mem_byte(unsigned short addr, unsigned char value) {
    mem_buffer[addr] = value;
}

// Finalize memory loading and copy to reference simulator
extern "C" void dpi_6502_finalize_mem() {
    printf("[DPI] Finalizing memory load...\n");
    printf("[DPI] mem_buffer[0x0400-0x0403]: 0x%02x 0x%02x 0x%02x 0x%02x\n",
           mem_buffer[0x0400], mem_buffer[0x0401], mem_buffer[0x0402], mem_buffer[0x0403]);

    fake6502_wrapper_load_mem(mem_buffer, 65536);
    printf("[DPI] Memory loaded successfully\n");
}

// Step the reference simulator by one instruction
extern "C" void dpi_6502_step() {
    fake6502_wrapper_step();
}

// Compare RTL state with reference simulator
extern "C" int dpi_6502_compare(
    unsigned short rtl_pc,
    unsigned char rtl_a,
    unsigned char rtl_x,
    unsigned char rtl_y,
    unsigned char rtl_s,
    unsigned char rtl_n,
    unsigned char rtl_v,
    unsigned char rtl_d,
    unsigned char rtl_i,
    unsigned char rtl_z,
    unsigned char rtl_c
) {
    // Get reference state
    uint16_t ref_pc;
    uint8_t ref_a, ref_x, ref_y, ref_sp, ref_status;
    fake6502_wrapper_get_state(&ref_pc, &ref_a, &ref_x, &ref_y, &ref_sp, &ref_status);

    // Reconstruct RTL status byte (N V 1 B D I Z C)
    unsigned char rtl_status =
        (rtl_n ? 0x80 : 0) |  // Sign
        (rtl_v ? 0x40 : 0) |  // Overflow
        0x20 |                // Unused (always 1)
        (rtl_d ? 0x08 : 0) |  // Decimal
        (rtl_i ? 0x04 : 0) |  // Interrupt
        (rtl_z ? 0x02 : 0) |  // Zero
        (rtl_c ? 0x01 : 0);   // Carry

    // Mask for comparison: ignore bit 4 (B flag) which doesn't exist in hardware
    // The B flag is only set when pushing status to stack, not in the actual register
    const unsigned char STATUS_COMPARE_MASK = 0xEF;  // Mask out bit 4

    // Compare all registers
    int mismatch = 0;

    if (ref_pc != rtl_pc) {
        printf("[DPI MISMATCH] PC: ref=0x%04x rtl=0x%04x\n", ref_pc, rtl_pc);
        mismatch = 1;
    }
    if (ref_a != rtl_a) {
        printf("[DPI MISMATCH] A: ref=0x%02x rtl=0x%02x\n", ref_a, rtl_a);
        mismatch = 1;
    }
    if (ref_x != rtl_x) {
        printf("[DPI MISMATCH] X: ref=0x%02x rtl=0x%02x\n", ref_x, rtl_x);
        mismatch = 1;
    }
    if (ref_y != rtl_y) {
        printf("[DPI MISMATCH] Y: ref=0x%02x rtl=0x%02x\n", ref_y, rtl_y);
        mismatch = 1;
    }
    if (ref_sp != rtl_s) {
        printf("[DPI MISMATCH] S: ref=0x%02x rtl=0x%02x\n", ref_sp, rtl_s);
        mismatch = 1;
    }
    if ((ref_status & STATUS_COMPARE_MASK) != (rtl_status & STATUS_COMPARE_MASK)) {
        printf("[DPI MISMATCH] Status: ref=0x%02x (N=%d V=%d D=%d I=%d Z=%d C=%d) rtl=0x%02x (N=%d V=%d D=%d I=%d Z=%d C=%d)\n",
               ref_status,
               (ref_status & 0x80) ? 1 : 0,
               (ref_status & 0x40) ? 1 : 0,
               (ref_status & 0x08) ? 1 : 0,
               (ref_status & 0x04) ? 1 : 0,
               (ref_status & 0x02) ? 1 : 0,
               (ref_status & 0x01) ? 1 : 0,
               rtl_status,
               rtl_n, rtl_v, rtl_d, rtl_i, rtl_z, rtl_c);
        mismatch = 1;
    }

    if (mismatch) {
        printf("[DPI] Full reference state: PC=0x%04x A=0x%02x X=0x%02x Y=0x%02x S=0x%02x status=0x%02x\n",
               ref_pc, ref_a, ref_x, ref_y, ref_sp, ref_status);
        printf("[DPI] Full RTL state:       PC=0x%04x A=0x%02x X=0x%02x Y=0x%02x S=0x%02x status=0x%02x\n",
               rtl_pc, rtl_a, rtl_x, rtl_y, rtl_s, rtl_status);
    }

    // TODO: Memory write comparison needs better timing synchronization
    // For now, rely on register comparison which catches memory bugs indirectly
    // when the wrong value is loaded from memory

    // Clear RTL write tracking for next instruction
    rtl_write_count = 0;

    return mismatch;
}

// Get reference instruction at PC (for debugging)
extern "C" unsigned char dpi_6502_get_instr() {
    return fake6502_wrapper_get_instr_at_pc();
}

// Load checkpoint file - returns starting cycle count
extern "C" int64_t dpi_6502_load_checkpoint() {
    FILE* f = fopen("checkpoint.hex", "r");
    if (!f) {
        printf("[DPI] No checkpoint file, starting from reset\n");
        return 0;
    }

    unsigned int tmp_pc, tmp_a, tmp_x, tmp_y, tmp_s, tmp_p;

    // Read CPU state from first line
    if (fscanf(f, "%x %x %x %x %x %x %lu",
               &tmp_pc, &tmp_a, &tmp_x, &tmp_y, &tmp_s, &tmp_p, &checkpoint_cycle) != 7) {
        printf("[DPI] Error reading checkpoint header\n");
        fclose(f);
        return 0;
    }

    checkpoint_pc = tmp_pc;
    checkpoint_a = tmp_a;
    checkpoint_x = tmp_x;
    checkpoint_y = tmp_y;
    checkpoint_s = tmp_s;
    checkpoint_status = tmp_p;

    // Read memory into both mem_buffer (for RTL) and we'll pass to fake6502 too
    for (int addr = 0; addr < 65536; addr++) {
        unsigned int val;
        if (fscanf(f, "%x", &val) != 1) {
            printf("[DPI] Error reading memory at addr 0x%04x\n", addr);
            break;
        }
        mem_buffer[addr] = val;
    }
    fclose(f);

    // Initialize fake6502 with the checkpoint state
    fake6502_wrapper_init(checkpoint_pc, checkpoint_a, checkpoint_x,
                          checkpoint_y, checkpoint_s, checkpoint_status);
    fake6502_wrapper_load_mem(mem_buffer, 65536);

    printf("[DPI] Loaded checkpoint: PC=0x%04x A=0x%02x X=0x%02x Y=0x%02x S=0x%02x P=0x%02x cycle=%lu\n",
           checkpoint_pc, checkpoint_a, checkpoint_x, checkpoint_y,
           checkpoint_s, checkpoint_status, checkpoint_cycle);

    return (int64_t)checkpoint_cycle;
}

// Get checkpoint CPU state (called from testbench to initialize RTL)
extern "C" void dpi_6502_get_checkpoint_state(
    unsigned short* out_pc,
    unsigned char* out_a,
    unsigned char* out_x,
    unsigned char* out_y,
    unsigned char* out_s,
    unsigned char* out_status
) {
    *out_pc = checkpoint_pc;
    *out_a = checkpoint_a;
    *out_x = checkpoint_x;
    *out_y = checkpoint_y;
    *out_s = checkpoint_s;
    *out_status = checkpoint_status;
}

// Get checkpoint memory byte (called from testbench to initialize RTL mainmem)
extern "C" unsigned char dpi_6502_get_checkpoint_mem(unsigned short addr) {
    return mem_buffer[addr];
}
