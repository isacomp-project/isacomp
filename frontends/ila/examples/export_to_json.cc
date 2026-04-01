/// \file
/// Example: Export an ILA model to JSON for use with isacomp
///
/// This example demonstrates how to export an ILA model defined using
/// the ILAng C++ API to JSON format, which can then be parsed by
/// isacomp's ila_parser.py
///
/// Compile with:
///   g++ -std=c++17 export_to_json.cc -o export_to_json -lilang
///
/// Run with:
///   ./export_to_json output.json

#include <ilang/ilang++.h>
#include <ilang/target-json/interface.h>
#include <iostream>
#include <string>

using namespace ilang;

int main(int argc, char** argv) {
  // Default output filename
  std::string output_file = "ila_model.json";
  if (argc > 1) {
    output_file = argv[1];
  }

  // Create a simple ILA model
  // This is a minimal example - replace with your actual ILA model
  auto model = Ila("simple_counter");

  // Define inputs
  auto clk = model.NewBvInput("clk", 1);
  auto reset = model.NewBvInput("reset", 1);
  auto enable = model.NewBvInput("enable", 1);

  // Define state
  auto counter = model.NewBvState("counter", 32);

  // Define fetch function (what corresponds to instruction selection)
  model.SetFetch(enable);

  // Define valid function (when instructions are valid)
  model.SetValid(enable == BvConst(1, 1));

  // Add increment instruction
  {
    auto instr = model.NewInstr("INCREMENT");

    // Decode: when enable is 1
    instr.SetDecode(enable == BvConst(1, 1));

    // Update: increment counter
    instr.SetUpdate(counter, counter + BvConst(1, 32));
  }

  // Add reset instruction
  {
    auto instr = model.NewInstr("RESET");

    // Decode: when reset is 1
    instr.SetDecode(reset == BvConst(1, 1));

    // Update: reset counter to 0
    instr.SetUpdate(counter, BvConst(0, 32));
  }

  // Export to JSON
  std::cout << "Exporting ILA model '" << model.name().str()
            << "' to " << output_file << "..." << std::endl;

  bool success = IlaSerDesMngr::SerToFile(model.get(), output_file);

  if (success) {
    std::cout << "Successfully exported ILA model to JSON!" << std::endl;
    std::cout << "You can now parse this file with isacomp:" << std::endl;
    std::cout << "  from resource_graph import ResourceGraph" << std::endl;
    std::cout << "  graph = ResourceGraph.from_ila_json_file('"
              << output_file << "')" << std::endl;
    return 0;
  } else {
    std::cerr << "Failed to export ILA model to JSON" << std::endl;
    return 1;
  }
}
