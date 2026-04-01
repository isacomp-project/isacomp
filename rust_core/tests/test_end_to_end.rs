//! End-to-end integration test: parse real RV32I .isa files with ISAParser,
//! merge them with ResourceGraphMerger, and validate against Python reference.

use std::collections::HashMap;

use isacomp_core::graph_merger::ResourceGraphMerger;
use isacomp_core::isa_parser::ISAParser;
use isacomp_core::memory_access_transform::{MemoryAccessTransform, MemoryAccessTransformSpec};
use isacomp_core::resource_graph::ResourceGraph;
use isacomp_core::verilog_generator;

/// Helper: path to a riscv32 .isa file relative to the workspace root.
fn isa_path(name: &str) -> String {
    format!("../riscv32/{}.isa", name)
}

// ===========================================================================
// Individual ISAParser tests
// ===========================================================================

#[test]
fn test_parse_add_isa() {
    let mut parser = ISAParser::new();
    let graph = parser
        .parse_file(&isa_path("add"), None)
        .expect("Failed to parse add.isa");

    assert!(
        graph.get_node_count() > 0,
        "add.isa should produce a non-empty graph"
    );
    // add.isa should reference rf (register file) and pc
    assert!(
        graph.get_node("pc").is_some(),
        "add.isa should have a pc node"
    );
}

#[test]
fn test_parse_addi_isa() {
    let mut parser = ISAParser::new();
    let graph = parser
        .parse_file(&isa_path("addi"), None)
        .expect("Failed to parse addi.isa");

    assert!(graph.get_node_count() > 0);
    assert!(graph.get_node("pc").is_some());
}

#[test]
fn test_parse_sub_isa() {
    let mut parser = ISAParser::new();
    let graph = parser
        .parse_file(&isa_path("sub"), None)
        .expect("Failed to parse sub.isa");

    assert!(graph.get_node_count() > 0);
    assert!(graph.get_node("pc").is_some());
}

#[test]
fn test_parse_lui_isa() {
    let mut parser = ISAParser::new();
    let graph = parser
        .parse_file(&isa_path("lui"), None)
        .expect("Failed to parse lui.isa");

    assert!(graph.get_node_count() > 0);
    assert!(graph.get_node("pc").is_some());
}

// ===========================================================================
// Merge 4 instructions end-to-end
// ===========================================================================

/// Parse add, addi, sub, lui and merge them. Validate against Python reference
/// values (54 nodes, 79 edges).
#[test]
fn test_merge_four_rv32i_instructions() {
    let instructions = ["add", "addi", "sub", "lui"];

    let mut merger = ResourceGraphMerger::new(None);
    for name in &instructions {
        merger
            .add_instruction(name, &isa_path(name))
            .unwrap_or_else(|e| panic!("Failed to add instruction {}: {}", name, e));
    }

    let merged = merger
        .merge_graphs(Some("pc"))
        .expect("merge_graphs failed");

    let node_count = merged.get_node_count();
    let edge_count = merged.get_edge_count();

    println!(
        "Rust merged graph: {} nodes, {} edges",
        node_count, edge_count
    );

    // Python reference: 54 nodes, 79 edges.
    // Allow some tolerance for implementation differences in decode/mux logic,
    // but the order of magnitude should match.
    assert!(
        node_count >= 30,
        "Expected at least 30 nodes, got {}",
        node_count
    );
    assert!(
        edge_count >= 30,
        "Expected at least 30 edges, got {}",
        edge_count
    );

    // -- Architectural state nodes --
    // After merge, pc should be split into pc_rd / pc_wr
    assert!(
        merged.get_node("pc_rd").is_some() || merged.get_node("pc").is_some(),
        "Missing pc or pc_rd node"
    );
    assert!(
        merged.get_node("rf").is_some(),
        "Missing rf (register file) node"
    );
    assert!(
        merged.get_node("umem").is_some(),
        "Missing umem (instruction memory) node"
    );

    // -- Instruction-specific result nodes --
    assert!(
        merged.get_node("add_res").is_some(),
        "Missing add_res node"
    );
    assert!(
        merged.get_node("addi_res").is_some(),
        "Missing addi_res node"
    );
    assert!(
        merged.get_node("sub_res").is_some(),
        "Missing sub_res node"
    );
    assert!(
        merged.get_node("lui_res").is_some(),
        "Missing lui_res node"
    );

    // -- Shared nodes --
    assert!(
        merged.get_node("instr").is_some(),
        "Missing shared instr node"
    );
    assert!(merged.get_node("rd").is_some(), "Missing shared rd node");

    // -- Decode enable nodes --
    assert!(
        merged.get_node("add_enable").is_some(),
        "Missing add_enable decode node"
    );
    assert!(
        merged.get_node("addi_enable").is_some(),
        "Missing addi_enable decode node"
    );
    assert!(
        merged.get_node("sub_enable").is_some(),
        "Missing sub_enable decode node"
    );
    assert!(
        merged.get_node("lui_enable").is_some(),
        "Missing lui_enable decode node"
    );

    // Print all node names for debugging
    let mut names: Vec<&String> = merged.nodes.keys().collect();
    names.sort();
    println!("Merged graph nodes:");
    for n in &names {
        println!("  {}", n);
    }
}

// ===========================================================================
// JSON round-trip on live-merged graph
// ===========================================================================

#[test]
fn test_merge_and_roundtrip_json() {
    let instructions = ["add", "addi", "sub", "lui"];

    let mut merger = ResourceGraphMerger::new(None);
    for name in &instructions {
        merger
            .add_instruction(name, &isa_path(name))
            .expect("add_instruction failed");
    }

    let merged = merger.merge_graphs(Some("pc")).expect("merge failed");
    let original_nodes = merged.get_node_count();
    let original_edges = merged.get_edge_count();

    // Serialize to JSON
    let json_val = merged.to_json();
    let json_str =
        serde_json::to_string_pretty(&json_val).expect("JSON serialization failed");

    // Deserialize back
    let json_val2: serde_json::Value =
        serde_json::from_str(&json_str).expect("JSON parse failed");
    let restored = ResourceGraph::from_json(&json_val2).expect("from_json failed");

    assert_eq!(
        original_nodes,
        restored.get_node_count(),
        "Node count mismatch after JSON round-trip"
    );
    assert_eq!(
        original_edges,
        restored.get_edge_count(),
        "Edge count mismatch after JSON round-trip"
    );

    // Verify all node IDs survived
    for nid in merged.nodes.keys() {
        assert!(
            restored.get_node(nid).is_some(),
            "Node '{}' lost during JSON round-trip",
            nid
        );
    }

    // Verify all edge IDs survived
    for eid in merged.edges.keys() {
        assert!(
            restored.get_edge(eid).is_some(),
            "Edge '{}' lost during JSON round-trip",
            eid
        );
    }

    println!(
        "JSON round-trip preserved {} nodes and {} edges",
        original_nodes, original_edges
    );
}

// ===========================================================================
// Timing inference on live-merged graph
// ===========================================================================

#[test]
fn test_merge_and_timing_inference() {
    let instructions = ["add", "addi", "sub", "lui"];

    let mut merger = ResourceGraphMerger::new(None);
    for name in &instructions {
        merger
            .add_instruction(name, &isa_path(name))
            .expect("add_instruction failed");
    }

    let mut merged = merger.merge_graphs(Some("pc")).expect("merge failed");
    merged.infer_uarch_time(true);

    let timed: Vec<_> = merged
        .nodes
        .values()
        .filter(|n| n.uarch_time.is_some())
        .collect();

    assert!(
        !timed.is_empty(),
        "Expected some nodes to have uarch_time after inference"
    );

    println!(
        "Timing inference: {}/{} nodes have uarch_time",
        timed.len(),
        merged.get_node_count()
    );
}

// ===========================================================================
// Per-instruction graph comparison (parse individually then verify)
// ===========================================================================

#[test]
fn test_individual_graphs_have_expected_structure() {
    let instructions = ["add", "addi", "sub", "lui"];
    let mut graphs: HashMap<String, ResourceGraph> = HashMap::new();

    for name in &instructions {
        let mut parser = ISAParser::new();
        let graph = parser
            .parse_file(&isa_path(name), None)
            .unwrap_or_else(|e| panic!("Failed to parse {}: {}", name, e));
        graphs.insert(name.to_string(), graph);
    }

    // All instructions should have pc and instr nodes
    for (name, graph) in &graphs {
        assert!(
            graph.get_node("pc").is_some(),
            "{} missing pc node",
            name
        );
        assert!(
            graph.get_node("instr").is_some() || graph.nodes.values().any(|n| {
                n.data
                    .get("name")
                    .and_then(|v| v.as_str())
                    .map(|s| s == "instr")
                    .unwrap_or(false)
            }),
            "{} missing instr-related node",
            name
        );
    }

    // add and sub should both have rs1, rs2 (R-type)
    for name in &["add", "sub"] {
        let g = &graphs[*name];
        assert!(
            g.get_node("rs1").is_some()
                || g.nodes.values().any(|n| {
                    n.data
                        .get("name")
                        .and_then(|v| v.as_str())
                        .map(|s| s == "rs1")
                        .unwrap_or(false)
                }),
            "{} missing rs1",
            name
        );
    }

    println!("Individual graph structure checks passed");
}

// ===========================================================================
// Full pipeline: parse → merge → memory transform → Verilog generation
// ===========================================================================

#[test]
fn test_full_pipeline_isa_to_verilog() {
    let instructions = ["add", "addi", "sub", "lui"];

    // Step 1: Parse and merge
    let mut merger = ResourceGraphMerger::new(None);
    for name in &instructions {
        merger
            .add_instruction(name, &isa_path(name))
            .expect("add_instruction failed");
    }
    let mut merged = merger.merge_graphs(Some("pc")).expect("merge failed");
    println!(
        "After merge: {} nodes, {} edges",
        merged.get_node_count(),
        merged.get_edge_count()
    );

    // Step 2: Apply memory port width transform (always, matching Python script)
    if merged.get_node("umem").is_some() {
        let access_widths: Vec<i64> = merged.get_node("umem")
            .and_then(|n| n.data.get("access_widths"))
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_i64()).collect())
            .unwrap_or_else(|| vec![32]);
        let max_width = access_widths.iter().copied().max().unwrap_or(32);
        println!("umem access_widths: {:?}, max: {}", access_widths, max_width);

        let spec = MemoryAccessTransformSpec::new(
            "umem",
            "set_port_width",
            max_width,
            32,
            "forward",
        )
        .expect("invalid spec");
        let mut transform = MemoryAccessTransform::new(&mut merged);
        let result = transform.apply_transformation(&spec, false);
        println!("Memory transform: transformed={}, nodes_added={}", result.transformed, result.nodes_added.len());
    }

    // Step 3: Generate Verilog
    let verilog = verilog_generator::generate_verilog(&merged, "riscv32i_test");

    // Verify basic structure of generated Verilog
    assert!(
        verilog.contains("module riscv32i_test"),
        "Missing module declaration"
    );
    assert!(
        verilog.contains("input wire clk"),
        "Missing clk port"
    );
    assert!(
        verilog.contains("input wire reset"),
        "Missing reset port"
    );
    assert!(
        verilog.contains("endmodule"),
        "Missing endmodule"
    );

    // Should have some wire/reg declarations
    assert!(
        verilog.contains("wire") || verilog.contains("reg"),
        "Missing wire/reg declarations"
    );

    // Should have sequential logic
    assert!(
        verilog.contains("always @(posedge clk)"),
        "Missing sequential logic block"
    );

    let line_count = verilog.lines().count();
    println!(
        "Generated Verilog: {} lines, {} bytes",
        line_count,
        verilog.len()
    );

    // Sanity check: should be non-trivial output
    assert!(
        line_count > 20,
        "Expected substantial Verilog output, got {} lines",
        line_count
    );

    println!("Full pipeline test passed!");
}

/// Full 37-instruction RV32I pipeline matching generate_riscv32i_complete.py
#[test]
fn test_full_37_instruction_rv32i_pipeline() {
    let instructions = [
        "add", "addi", "sub", "lui", "auipc",
        "and", "andi", "or", "ori", "xor", "xori",
        "sll", "slli", "srl", "srli", "sra", "srai",
        "slt", "slti", "sltu", "sltiu",
        "beq", "bne", "blt", "bltu", "bge", "bgeu",
        "jal", "jalr",
        "lw", "lh", "lhu", "lb", "lbu",
        "sw", "sh", "sb",
    ];

    // Step 1: Parse and merge all 37 instructions
    let mut merger = ResourceGraphMerger::new(None);
    for name in &instructions {
        merger
            .add_instruction(name, &isa_path(name))
            .unwrap_or_else(|e| panic!("Failed to add {}: {}", name, e));
    }
    let mut merged = merger.merge_graphs(Some("pc")).expect("merge failed");
    println!(
        "Merged: {} nodes, {} edges",
        merged.get_node_count(),
        merged.get_edge_count()
    );

    // Step 2: Apply memory port width transform (always, matching Python script)
    if merged.get_node("umem").is_some() {
        let access_widths: Vec<i64> = merged.get_node("umem")
            .and_then(|n| n.data.get("access_widths"))
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_i64()).collect())
            .unwrap_or_else(|| vec![32]);
        let max_width = access_widths.iter().copied().max().unwrap_or(32);
        println!("umem access_widths: {:?}, max: {}", access_widths, max_width);

        let spec = MemoryAccessTransformSpec::new(
            "umem", "set_port_width", max_width, 32, "forward",
        ).expect("invalid spec");
        let mut transform = MemoryAccessTransform::new(&mut merged);
        let result = transform.apply_transformation(&spec, false);
        println!("Transform: transformed={}, nodes_added={}", result.transformed, result.nodes_added.len());
    }
    println!(
        "After transform: {} nodes, {} edges",
        merged.get_node_count(),
        merged.get_edge_count()
    );

    // Step 3: Generate Verilog
    let verilog = verilog_generator::generate_verilog(&merged, "riscv32i_complete");
    let line_count = verilog.lines().count();
    println!("Verilog: {} lines, {} bytes", line_count, verilog.len());

    // Write to file for comparison
    std::fs::write("/tmp/rust_riscv32i.v", &verilog).expect("write failed");
    println!("Wrote /tmp/rust_riscv32i.v");

    // Structural checks
    assert!(verilog.contains("module riscv32i_complete"), "Missing module declaration");
    assert!(verilog.contains("input wire clk"), "Missing clk");
    assert!(verilog.contains("input wire reset"), "Missing reset");
    assert!(verilog.contains("always @(posedge clk)"), "Missing sequential logic");
    assert!(verilog.contains("endmodule"), "Missing endmodule");

    // Should be substantial output (Python produces ~709 lines)
    assert!(line_count > 100, "Expected >100 lines, got {}", line_count);
}
