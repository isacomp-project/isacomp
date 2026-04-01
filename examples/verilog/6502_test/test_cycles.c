#include <stdio.h>
#include <stdint.h>
#include <string.h>

// From fake6502_wrapper
extern void fake6502_wrapper_init(uint16_t reset_pc, uint8_t reset_a, uint8_t reset_x,
                                  uint8_t reset_y, uint8_t reset_s, uint8_t reset_status);
extern void fake6502_wrapper_load_mem(const uint8_t* mem_data, int size);
extern void fake6502_wrapper_step();
extern void fake6502_wrapper_get_state(uint16_t* out_pc, uint8_t* out_a, uint8_t* out_x,
                                       uint8_t* out_y, uint8_t* out_sp, uint8_t* out_status);

int main() {
    uint8_t mem[65536] = {0};
    
    // Load the hex file
    FILE* f = fopen("imem.hex", "r");
    if (!f) { printf("Cannot open imem.hex\n"); return 1; }
    
    int addr = 0;
    char line[256];
    while (fgets(line, sizeof(line), f) && addr < 65536) {
        unsigned int val;
        if (sscanf(line, "%x", &val) == 1) {
            mem[addr++] = val;
        }
    }
    fclose(f);
    printf("Loaded %d bytes\n", addr);
    
    fake6502_wrapper_load_mem(mem, 65536);
    fake6502_wrapper_init(0x0400, 0, 0, 0, 0xFF, 0x24);
    
    uint16_t pc;
    uint8_t a, x, y, sp, status;
    int cycles = 0;
    int max_cycles = 100000000;
    
    while (cycles < max_cycles) {
        fake6502_wrapper_get_state(&pc, &a, &x, &y, &sp, &status);
        
        if (pc == 0x3469) {
            printf("PASS at cycle %d (PC=0x%04x)\n", cycles, pc);
            return 0;
        }
        if (pc == 0x3463) {
            printf("FAIL at cycle %d (PC=0x%04x)\n", cycles, pc);
            return 1;
        }
        
        fake6502_wrapper_step();
        cycles++;
        
        if (cycles % 1000000 == 0) {
            printf("Cycle %d: PC=0x%04x\n", cycles, pc);
        }
    }
    
    printf("Timeout at cycle %d\n", cycles);
    return 1;
}
