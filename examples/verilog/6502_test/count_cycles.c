/* Quick cycle counter for Dormann test using fake6502 */

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>

#define FAKE6502_USE_STDINT
#define FAKE6502_NOT_STATIC
#include "../../isa/6502/fake6502/fake6502.h"

static uint8_t memory[65536];

uint8 read6502(ushort address) {
    return memory[address];
}

void write6502(ushort address, uint8 value) {
    memory[address] = value;
}

int main() {
    // Load memory from hex file
    FILE *f = fopen("imem.hex", "r");
    if (!f) {
        printf("ERROR: Cannot open imem.hex\n");
        return 1;
    }

    char line[16];
    int addr = 0;
    while (fgets(line, sizeof(line), f) && addr < 65536) {
        unsigned int val;
        if (sscanf(line, "%x", &val) == 1) {
            memory[addr++] = (uint8_t)val;
        }
    }
    fclose(f);
    printf("Loaded %d bytes\n", addr);

    // Initialize CPU state (same as testbench)
    pc = 0x0400;
    a = 0x00;
    x = 0x00;
    y = 0x00;
    sp = 0xFF;
    status = 0x24;  // I flag set

    uint16_t pass_pc = 0x3469;
    uint16_t fail_pc = 0x3463;
    uint64_t cycles = 0;
    uint64_t instructions = 0;

    printf("Starting at PC=0x%04x\n", pc);
    printf("Pass address: 0x%04x\n", pass_pc);
    printf("Fail address: 0x%04x\n", fail_pc);

    while (1) {
        uint16_t prev_pc = pc;

        step6502();
        instructions++;
        cycles += clockticks6502;

        // Progress every 1M instructions
        if (instructions % 1000000 == 0) {
            printf("Instructions: %luM, Cycles: %lu, PC=0x%04x\n",
                   instructions / 1000000, cycles, pc);
        }

        // Check termination
        if (pc == pass_pc) {
            printf("\n*** PASS *** at PC=0x%04x\n", pc);
            printf("Total instructions: %lu\n", instructions);
            printf("Total cycles: %lu\n", cycles);
            return 0;
        }

        if (pc == fail_pc) {
            printf("\n*** FAIL *** at PC=0x%04x\n", pc);
            printf("Total instructions: %lu\n", instructions);
            printf("Total cycles: %lu\n", cycles);
            return 1;
        }

        // Detect infinite loop (same PC twice)
        if (pc == prev_pc) {
            printf("\n*** STUCK *** at PC=0x%04x\n", pc);
            printf("Total instructions: %lu\n", instructions);
            printf("Total cycles: %lu\n", cycles);
            return 1;
        }

        // Safety limit
        if (instructions > 100000000) {
            printf("\n*** TIMEOUT *** after 100M instructions\n");
            printf("Final PC=0x%04x\n", pc);
            return 1;
        }
    }
}
