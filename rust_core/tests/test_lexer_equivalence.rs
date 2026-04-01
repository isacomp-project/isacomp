//! Integration tests for the ISA lexer and parser.

use isacomp_core::isa_lexer::ISALexer;
use isacomp_core::resource_graph::ResourceGraph;
use std::fs;

/// Verify the Rust lexer tokenizes a real ISA file correctly.
#[test]
fn test_lexer_matches_python_on_riscv64_add() {
    let isa_text =
        fs::read_to_string("tests/fixtures/riscv64_add.isa").expect("Missing fixture file");

    let lexer = ISALexer::new();
    let tokens = lexer.tokenize(&isa_text).expect("Rust lexer failed");

    // Verify we get a reasonable number of tokens
    assert!(
        tokens.len() > 50,
        "Expected >50 tokens, got {}",
        tokens.len()
    );

    // Verify key token types are present
    let type_names: Vec<String> = tokens.iter().map(|t| format!("{}", t.type_)).collect();
    assert!(type_names.contains(&"ISA_STATE".to_string()), "Missing ISA_STATE token");
    assert!(type_names.contains(&"IDENTIFIER".to_string()), "Missing IDENTIFIER token");
    assert!(type_names.contains(&"EQUALS".to_string()), "Missing EQUALS token");

    // Verify key identifiers are tokenized
    let values: Vec<&str> = tokens.iter().map(|t| t.value.as_str()).collect();
    assert!(values.contains(&"pc"), "Missing 'pc' identifier");
    assert!(values.contains(&"rf"), "Missing 'rf' identifier");
    assert!(values.contains(&"umem"), "Missing 'umem' identifier");

    println!("Lexer produced {} tokens from riscv64_add.isa", tokens.len());
}

/// Verify a parsed ISA file produces a correct resource graph.
#[test]
fn test_resource_graph_from_parsed_isa() {
    let isa_text =
        fs::read_to_string("tests/fixtures/riscv64_add.isa").expect("Missing fixture file");

    let mut parser = isacomp_core::isa_parser::ISAParser::new();
    let graph = parser.parse(&isa_text, None, false).expect("Parser failed");

    assert_eq!(graph.get_node_count(), 22, "Expected 22 nodes");
    assert_eq!(graph.get_edge_count(), 27, "Expected 27 edges");

    // Verify key nodes exist
    assert!(graph.get_node("pc").is_some(), "Missing 'pc' node");
    assert!(graph.get_node("rf").is_some(), "Missing 'rf' node");
    assert!(graph.get_node("instr").is_some(), "Missing 'instr' node");
    assert!(graph.get_node("res").is_some(), "Missing 'res' node");

    // Verify pc is architectural state
    let pc = graph.get_node("pc").unwrap();
    assert!(pc.is_arch_state, "pc should be architectural state");

    // Verify rf is architectural state
    let rf = graph.get_node("rf").unwrap();
    assert!(rf.is_arch_state, "rf should be architectural state");

    // Test round-trip: to_json -> from_json
    let json = graph.to_json();
    let graph2 = ResourceGraph::from_json(&json).expect("round-trip failed");
    assert_eq!(graph2.get_node_count(), 22);
    assert_eq!(graph2.get_edge_count(), 27);

    println!(
        "Resource graph parsed: {} nodes, {} edges",
        graph.get_node_count(),
        graph.get_edge_count()
    );
}

/// Test timing inference on a parsed graph.
#[test]
fn test_timing_inference_on_parsed_graph() {
    let isa_text =
        fs::read_to_string("tests/fixtures/riscv64_add.isa").expect("Missing fixture file");

    let mut parser = isacomp_core::isa_parser::ISAParser::new();
    let mut graph = parser.parse(&isa_text, None, false).expect("Parser failed");

    graph.infer_uarch_time(true);

    // All nodes should now have a uarch_time
    for (id, node) in &graph.nodes {
        assert!(
            node.uarch_time.is_some(),
            "Node '{}' missing uarch_time after inference",
            id
        );
    }

    // PC read should be at time 0
    let pc = graph.get_node("pc").unwrap();
    assert_eq!(pc.uarch_time, Some(0), "pc should be at time 0");

    println!("Timing inference passed on {} nodes", graph.get_node_count());
}
