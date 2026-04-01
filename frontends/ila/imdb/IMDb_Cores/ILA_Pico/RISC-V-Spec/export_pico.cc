#include <ilang/ilang++.h>
#include <iostream>
#include "riscvIla.hpp"

using namespace ilang;

int main() {
  // Create the Pico RISC-V ILA model
  riscvILA_user pico(0);  // pc_init_val = 0
  pico.addInstructions(); // Add all 37 base integer instructions

  // Export full model to JSON
  std::string output_file = "pico_full.json";
  if (ExportIlaPortable(pico.model, output_file)) {
    std::cout << "✓ Pico full model exported to: " << output_file << std::endl;
  } else {
    std::cerr << "✗ Pico export failed!" << std::endl;
    return 1;
  }

  return 0;
}
