/* Run fake6502 to a checkpoint and dump state */

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

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

int main(int argc, char** argv) {
    uint64_t target_cycles = 26000000;  // Default: 26M cycles

    if (argc > 1) {
        target_cycles = strtoull(argv[1], NULL, 0);
    }

    // Load memory
    FILE *f = fopen("imem.hex", "r");
    if (!f) { printf("ERROR: Cannot open imem.hex\n"); return 1; }

    char line[16];
    int addr = 0;
    while (fgets(line, sizeof(line), f) && addr < 65536) {
        unsigned int val;
        if (sscanf(line, "%x", &val) == 1) {
            memory[addr++] = (uint8_t)val;
        }
    }
    fclose(f);

    // Initialize CPU
    pc = 0x0400;
    a = 0x00;
    x = 0x00;
    y = 0x00;
    sp = 0xFF;
    status = 0x24;

    printf("Running fake6502 to %lu cycles...\n", target_cycles);

    uint64_t instructions = 0;
    while (instructions < target_cycles) {
        step6502();
        instructions++;

        if (instructions % 1000000 == 0) {
            printf("  %luM cycles, PC=0x%04x\n", instructions / 1000000, pc);
        }
    }

    printf("\nCheckpoint at %lu cycles:\n", instructions);
    printf("  PC=0x%04x A=0x%02x X=0x%02x Y=0x%02x S=0x%02x P=0x%02x\n",
           pc, a, x, y, sp, status);

    // Write checkpoint file
    FILE *ckpt = fopen("checkpoint.hex", "w");
    if (!ckpt) { printf("ERROR: Cannot create checkpoint.hex\n"); return 1; }

    // First line: CPU state (PC, A, X, Y, S, P, cycle_count)
    fprintf(ckpt, "%04x %02x %02x %02x %02x %02x %lu\n",
            pc, a, x, y, sp, status, instructions);

    // Rest: full memory dump
    for (int i = 0; i < 65536; i++) {
        fprintf(ckpt, "%02x\n", memory[i]);
    }
    fclose(ckpt);

    printf("Checkpoint saved to checkpoint.hex\n");

    return 0;
}
