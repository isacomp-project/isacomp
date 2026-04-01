#include <ilang/ilang++.h>
#include <iostream>
#include "riscvIla.hpp"

using namespace ilang;

int main() {
  // Create the Rocket RISC-V ILA model
  riscvILA_user rocket(0);  // pc_init_val = 0
  rocket.addInstructions(); // Add all 37 base integer instructions

  // Export full model to JSON
  std::string output_file = "rocket_full.json";
  if (ExportIlaPortable(rocket.model, output_file)) {
    std::cout << "✓ Rocket full model exported to: " << output_file << std::endl;
  } else {
    std::cerr << "✗ Rocket export failed!" << std::endl;
    return 1;
  }

  return 0;
}
