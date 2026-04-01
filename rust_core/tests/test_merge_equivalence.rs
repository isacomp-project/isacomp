//! Integration tests for the Rust graph merger and resource graph operations.

use isacomp_core::resource_graph::{ResourceGraph, Node, Edge};
use isacomp_core::graph_merger;

/// Helper: merge 4 RV32I instructions using the ResourceGraphMerger.
fn merge_4_instructions() -> ResourceGraph {
    let isa_dir = "../riscv32";
    let instructions = ["add", "addi", "sub", "lui"];

    let mut merger = graph_merger::ResourceGraphMerger::new(None);
    for instr in &instructions {
        let path = format!("{}/{}.isa", isa_dir, instr);
        merger.add_instruction(instr, &path)
            .unwrap_or_else(|e| panic!("add_instruction failed for {}: {}", instr, e));
    }
    merger.merge_graphs(Some("pc"))
        .expect("merge_graphs failed")
}

/// Parse and merge 4 RV32I instructions, verify the resulting graph.
#[test]
fn test_load_python_merged_graph() {
    let merged = merge_4_instructions();

    // Should produce a merged graph with shared + per-instruction nodes
    assert!(merged.get_node_count() > 30, "Expected >30 nodes, got {}", merged.get_node_count());
    assert!(merged.get_edge_count() > 30, "Expected >30 edges, got {}", merged.get_edge_count());

    // Verify architectural state nodes exist
    assert!(merged.get_node("pc_rd").is_some(), "Missing pc_rd node");
    assert!(merged.get_node("pc_wr").is_some(), "Missing pc_wr node");
    assert!(merged.get_node("rf").is_some(), "Missing rf node");
    assert!(merged.get_node("umem").is_some(), "Missing umem node");

    // Verify instruction-specific nodes
    assert!(merged.get_node("add_res").is_some(), "Missing add_res node");
    assert!(merged.get_node("addi_res").is_some(), "Missing addi_res node");
    assert!(merged.get_node("sub_res").is_some(), "Missing sub_res node");
    assert!(merged.get_node("lui_res").is_some(), "Missing lui_res node");

    // Verify shared nodes
    assert!(merged.get_node("instr").is_some(), "Missing shared instr node");
    assert!(merged.get_node("rs1").is_some(), "Missing shared rs1 node");
    assert!(merged.get_node("rd").is_some(), "Missing shared rd node");
    assert!(merged.get_node("r1").is_some(), "Missing shared r1 node");

    // Verify decode enable nodes
    assert!(merged.get_node("add_enable").is_some(), "Missing add_enable node");
    assert!(merged.get_node("addi_enable").is_some(), "Missing addi_enable node");
    assert!(merged.get_node("sub_enable").is_some(), "Missing sub_enable node");
    assert!(merged.get_node("lui_enable").is_some(), "Missing lui_enable node");

    // Verify mux node for write data
    assert!(
        merged.get_node("rf_write_data_mux").is_some(),
        "Missing rf_write_data_mux node"
    );

    println!(
        "Merged graph: {} nodes, {} edges",
        merged.get_node_count(),
        merged.get_edge_count()
    );
}

/// Verify timing inference works on merged graph.
#[test]
fn test_timing_on_merged_graph() {
    let mut merged = merge_4_instructions();
    merged.infer_uarch_time(true);

    let nodes_with_time: Vec<_> = merged
        .nodes
        .values()
        .filter(|n| n.uarch_time.is_some())
        .collect();

    assert!(
        !nodes_with_time.is_empty(),
        "No nodes received uarch_time"
    );

    println!(
        "Timing inference: {}/{} nodes have uarch_time",
        nodes_with_time.len(),
        merged.get_node_count()
    );
}

/// Test round-trip serialization on merged graph.
#[test]
fn test_roundtrip_merged_graph() {
    let merged = merge_4_instructions();

    // Round-trip
    let json = merged.to_json();
    let graph2 = ResourceGraph::from_json(&json).expect("round-trip failed");

    assert_eq!(merged.get_node_count(), graph2.get_node_count());
    assert_eq!(merged.get_edge_count(), graph2.get_edge_count());

    for nid in merged.nodes.keys() {
        assert!(
            graph2.get_node(nid).is_some(),
            "Node '{}' missing after round-trip",
            nid
        );
    }

    println!("Round-trip preserves all {} nodes and {} edges",
        merged.get_node_count(), merged.get_edge_count());
}

/// Test split_arch_state_nodes on a simple graph.
#[test]
fn test_split_arch_state_nodes_integration() {
    let mut graph = ResourceGraph::new();

    // Create an architectural state node 'pc'
    let mut pc_data = std::collections::HashMap::new();
    pc_data.insert("type".into(), serde_json::json!("isa_state"));
    pc_data.insert("name".into(), serde_json::json!("pc"));
    pc_data.insert("bit_width".into(), serde_json::json!(32));

    let pc_node = Node::new(
        Some("pc".into()), Some(pc_data),
        true, false, None, false, None, None, true, false, 0, false, false, None, None,
    );
    graph.add_node(pc_node);

    // Create a literal node
    let mut lit_data = std::collections::HashMap::new();
    lit_data.insert("type".into(), serde_json::json!("literal"));
    lit_data.insert("value".into(), serde_json::json!(4));
    let lit_node = Node::new(
        Some("4".into()), Some(lit_data),
        false, false, None, false, None, None, false, false, 0, false, false, None, None,
    );
    graph.add_node(lit_node);

    // Create operation node
    let mut op_data = std::collections::HashMap::new();
    op_data.insert("type".into(), serde_json::json!("operation"));
    op_data.insert("display_name".into(), serde_json::json!("(pc + 4)"));
    let op_node = Node::new(
        Some("(pc + 4)".into()), Some(op_data),
        false, false, None, false, None, None, false, false, 0, false, false, None, None,
    );
    graph.add_node(op_node);

    // Create edges: pc -> (pc+4) (read), (pc+4) -> pc (assignment/write)
    let read_edge = Edge::new(
        "pc".into(), "(pc + 4)".into(), None,
        Some({
            let mut d = std::collections::HashMap::new();
            d.insert("type".into(), serde_json::json!("operand"));
            d.insert("position".into(), serde_json::json!("left"));
            d
        }),
    );
    graph.add_edge(read_edge);

    let lit_edge = Edge::new(
        "4".into(), "(pc + 4)".into(), None,
        Some({
            let mut d = std::collections::HashMap::new();
            d.insert("type".into(), serde_json::json!("operand"));
            d.insert("position".into(), serde_json::json!("right"));
            d
        }),
    );
    graph.add_edge(lit_edge);

    let write_edge = Edge::new(
        "(pc + 4)".into(), "pc".into(), None,
        Some({
            let mut d = std::collections::HashMap::new();
            d.insert("type".into(), serde_json::json!("assignment"));
            d
        }),
    );
    graph.add_edge(write_edge);

    assert_eq!(graph.get_node_count(), 3);
    assert_eq!(graph.get_edge_count(), 3);

    // Split arch state nodes
    graph_merger::split_arch_state_nodes(&mut graph);

    // Now should have pc_rd and pc_wr instead of pc
    assert!(graph.get_node("pc").is_none(), "Original pc should be removed");
    assert!(graph.get_node("pc_rd").is_some(), "pc_rd should exist");
    assert!(graph.get_node("pc_wr").is_some(), "pc_wr should exist");

    // Read edge (operand) should now come from pc_rd
    let op_node = graph.get_node("(pc + 4)").unwrap();
    let has_rd_input = op_node.incoming_edges.iter().any(|eid| {
        graph.get_edge(eid).map(|e| e.source == "pc_rd").unwrap_or(false)
    });
    assert!(has_rd_input, "Operation should read from pc_rd");

    // Write edge (assignment) should now go to pc_wr
    let wr_node = graph.get_node("pc_wr").unwrap();
    assert!(!wr_node.incoming_edges.is_empty(), "pc_wr should have incoming assignment");

    println!("split_arch_state_nodes works correctly");
}
