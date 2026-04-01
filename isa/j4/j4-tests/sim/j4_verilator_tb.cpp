// Verilator C++ testbench for J4 processor
#include <verilated.h>
#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <cstdint>

#include "Vj4_complete.h"

// Maximum simulation time
#define MAX_TIME 100000

vluint64_t main_time = 0;

double sc_time_stamp() {
    return main_time;
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);

    // Get plusargs
    uint32_t pass_addr = 0;
    uint32_t fail_addr = 0;

    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        if (arg.find("+pass_addr=") == 0) {
            pass_addr = std::stoul(arg.substr(11), nullptr, 0);
        } else if (arg.find("+fail_addr=") == 0) {
            fail_addr = std::stoul(arg.substr(11), nullptr, 0);
        }
    }

    // Create instance
    Vj4_complete* dut = new Vj4_complete;

    // Load memory from hex file
    std::ifstream mem_file("umem.hex");
    if (mem_file.is_open()) {
        std::string line;
        int addr = 0;
        while (std::getline(mem_file, line) && addr < 4096) {
            if (!line.empty()) {
                uint32_t data = std::stoul(line, nullptr, 16);
                dut->umem[addr] = data;
                addr++;
            }
        }
        mem_file.close();
        std::cout << "Loaded " << addr << " words from umem.hex" << std::endl;
    } else {
        std::cerr << "Error: Could not open umem.hex" << std::endl;
        return 1;
    }

    // Initialize inputs
    dut->clk = 0;
    dut->rst = 1;
    dut->reset_pc = 0;

    // Reset for a few cycles
    for (int i = 0; i < 10; i++) {
        dut->clk = !dut->clk;
        dut->eval();
        main_time++;
    }

    dut->rst = 0;

    // Run simulation
    bool passed = false;
    bool failed = false;

    while (main_time < MAX_TIME && !passed && !failed) {
        dut->clk = !dut->clk;
        dut->eval();

        // Check PC on positive edge
        if (dut->clk) {
            uint32_t pc = dut->pc_rd;

            if (pass_addr != 0 && pc == pass_addr) {
                std::cout << "TEST PASSED at time " << main_time << std::endl;
                passed = true;
            } else if (fail_addr != 0 && pc == fail_addr) {
                std::cout << "TEST FAILED at time " << main_time << std::endl;
                failed = true;
            }
        }

        main_time++;
    }

    if (!passed && !failed) {
        std::cout << "TIMEOUT at time " << main_time << std::endl;
    }

    // Cleanup
    delete dut;

    return failed ? 1 : 0;
}
