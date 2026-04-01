#include <ilang/ilang++.h>
#include <iostream>
#include "riscvIla.hpp"

using namespace ilang;

int main() {
  // Create the Piccolo RISC-V ILA model
  riscvILA_user piccolo;
  piccolo.addInstructions(); // Add all 37 base integer instructions

  // Export full model to JSON
  std::string output_file = "piccolo_full.json";
  if (ExportIlaPortable(piccolo.model, output_file)) {
    std::cout << "✓ Piccolo full model exported to: " << output_file << std::endl;
  } else {
    std::cerr << "✗ Piccolo export failed!" << std::endl;
    return 1;
  }

  return 0;
}
