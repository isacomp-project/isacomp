/* Pure C wrapper for fake6502 to avoid C++ keyword collisions */

#include <stdint.h>
#include <string.h>

#define FAKE6502_USE_STDINT
#define FAKE6502_NOT_STATIC
#include "../../isa/6502/fake6502/fake6502.h"

// Shared memory
static uint8_t fake6502_mem[65536];

// Track all memory writes during an instruction (max 3 for BRK)
#define MAX_WRITES_PER_INSN 4
static uint16_t write_addrs[MAX_WRITES_PER_INSN];
static uint8_t write_values[MAX_WRITES_PER_INSN];
static int write_count = 0;

// Memory access functions required by fake6502
uint8 read6502(ushort address) {
    return fake6502_mem[address];
}

void write6502(ushort address, uint8 value) {
    // Track this write for later comparison with RTL
    if (write_count < MAX_WRITES_PER_INSN) {
        write_addrs[write_count] = address;
        write_values[write_count] = value;
        write_count++;
    }
    fake6502_mem[address] = value;
}

// Function to get write count (called before step)
void fake6502_wrapper_clear_writes() {
    write_count = 0;
}

// Function to get writes (called after step)
int fake6502_wrapper_get_write_count() {
    return write_count;
}

void fake6502_wrapper_get_write(int index, uint16_t* addr, uint8_t* value) {
    if (index < write_count) {
        *addr = write_addrs[index];
        *value = write_values[index];
    }
}

// Wrapper functions that will be called from C++ DPI code
void fake6502_wrapper_init(uint16_t reset_pc, uint8_t reset_a, uint8_t reset_x,
                            uint8_t reset_y, uint8_t reset_s, uint8_t reset_status) {
    // Don't call reset6502() - it does a full reset sequence
    // Just set the registers directly to match RTL initial state
    pc = reset_pc;
    a = reset_a;
    x = reset_x;
    y = reset_y;
    sp = reset_s;
    status = reset_status;
}

void fake6502_wrapper_load_mem(const uint8_t* mem_data, int size) {
    fprintf(stderr, "[FAKE6502] load_mem called with ptr=%p size=%d\n", (void*)mem_data, size);

    if (!mem_data) {
        fprintf(stderr, "[FAKE6502] ERROR: mem_data is NULL!\n");
        return;
    }

    if (size > 65536) size = 65536;

    // Copy byte by byte for first few to test
    for (int i = 0; i < size; i++) {
        fake6502_mem[i] = mem_data[i];
    }

    // Debug: verify memory loaded correctly
    fprintf(stderr, "[FAKE6502] Memory at 0x0400: 0x%02x 0x%02x 0x%02x 0x%02x\n",
           fake6502_mem[0x0400], fake6502_mem[0x0401], fake6502_mem[0x0402], fake6502_mem[0x0403]);
    fprintf(stderr, "[FAKE6502] Memory at 0xFFFE (IRQ vector): 0x%02x 0x%02x\n",
           fake6502_mem[0xFFFE], fake6502_mem[0xFFFF]);
}

void fake6502_wrapper_step() {
    // Clear write tracking before executing instruction
    write_count = 0;

    step6502();

    // Debug output disabled for performance
    // Uncomment for debugging:
    // printf("[FAKE6502] Executed at PC 0x%04x -> PC now 0x%04x\n", pc_before, pc);
}

void fake6502_wrapper_get_state(uint16_t* out_pc, uint8_t* out_a, uint8_t* out_x,
                                 uint8_t* out_y, uint8_t* out_sp, uint8_t* out_status) {
    *out_pc = pc;
    *out_a = a;
    *out_x = x;
    *out_y = y;
    *out_sp = sp;
    *out_status = status;
}

uint8_t fake6502_wrapper_get_instr_at_pc() {
    return fake6502_mem[pc];
}

// Load checkpoint file and return the starting cycle count
uint64_t fake6502_wrapper_load_checkpoint(const char* filename) {
    FILE* f = fopen(filename, "r");
    if (!f) {
        fprintf(stderr, "[FAKE6502] No checkpoint file '%s', starting from reset\n", filename);
        return 0;
    }

    uint64_t start_cycle;
    unsigned int tmp_pc, tmp_a, tmp_x, tmp_y, tmp_s, tmp_p;

    // Read CPU state from first line
    if (fscanf(f, "%x %x %x %x %x %x %lu",
               &tmp_pc, &tmp_a, &tmp_x, &tmp_y, &tmp_s, &tmp_p, &start_cycle) != 7) {
        fprintf(stderr, "[FAKE6502] Error reading checkpoint header\n");
        fclose(f);
        return 0;
    }

    pc = tmp_pc;
    a = tmp_a;
    x = tmp_x;
    y = tmp_y;
    sp = tmp_s;
    status = tmp_p;

    // Read memory
    for (int addr = 0; addr < 65536; addr++) {
        unsigned int val;
        if (fscanf(f, "%x", &val) != 1) {
            fprintf(stderr, "[FAKE6502] Error reading memory at addr 0x%04x\n", addr);
            break;
        }
        fake6502_mem[addr] = val;
    }

    fclose(f);

    fprintf(stderr, "[FAKE6502] Loaded checkpoint: PC=0x%04x A=0x%02x X=0x%02x Y=0x%02x S=0x%02x P=0x%02x cycle=%lu\n",
            pc, a, x, y, sp, status, start_cycle);

    return start_cycle;
}
