#include "Vcpu_6502_test_tb.h"
#include "verilated.h"

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);

    // Create model with context for timing
    VerilatedContext* contextp = new VerilatedContext;
    contextp->commandArgs(argc, argv);

    Vcpu_6502_test_tb* top = new Vcpu_6502_test_tb{contextp};

    // Run the simulation using event-driven mode
    while (!contextp->gotFinish()) {
        // Advance time using event-driven timing
        top->eval();
        contextp->timeInc(1);  // Advance 1ps at a time
    }

    top->final();
    delete top;
    delete contextp;
    return 0;
}
