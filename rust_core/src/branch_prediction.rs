//! Not-taken branch prediction pass for ResourceGraph.
//!
//! Implements static not-taken branch prediction:
//! - Predicts branches as not-taken (PC+4 early in pipeline)
//! - Creates predicted_pc and recovery mux
//! - Connects control_hazard_flush to recovery mux
//! - Gates architectural state updates with validity

use crate::resource_graph::{Edge, Node, ResourceGraph};
use serde_json::{json, Value};
use std::collections::HashMap;

/// Apply not-taken branch prediction to a resource graph.
///
/// Args:
///   - `pc_node_id`: PC write node (e.g., "pc_wr")
///   - `pc_mux_id`: PC mux node (e.g., "pc_wr_mux")
///   - `not_taken_input_id`: Not-taken path node (e.g., "pc_add_4")
///   - `taken_input_id`: Representative taken path node (e.g., "jal_jump_dest")
pub fn apply_branch_prediction_not_taken(
    graph: &mut ResourceGraph,
    pc_node_id: Option<&str>,
    pc_mux_id: Option<&str>,
    not_taken_input_id: Option<&str>,
    _taken_input_id: Option<&str>,
) -> bool {
    log::info!("\n{}", "=".repeat(70));
    log::info!("APPLYING BRANCH PREDICTION PASS");
    log::info!("{}", "=".repeat(70));

    // Step 1: Find PC node
    let pc_id = find_pc_node(graph, pc_node_id);
    let pc_id = match pc_id {
        Some(id) => id,
        None => {
            log::info!("Could not find PC node - branch prediction not applicable");
            return false;
        }
    };
    log::info!("  Found PC node: {}", pc_id);

    // Get PC width from pc_rd node
    let pc_width: Option<i64> = graph.nodes.get("pc_rd")
        .and_then(|n| n.data.get("bit_width"))
        .and_then(|v| v.as_i64());
    if let Some(w) = pc_width {
        log::info!("  PC width: {} bits", w);
    }

    // Step 2: Find PC mux
    let mux_id = find_pc_mux(graph, &pc_id, pc_mux_id);
    let mux_id = match mux_id {
        Some(id) => id,
        None => {
            log::info!("Could not find PC mux - branch prediction not applicable");
            return false;
        }
    };
    log::info!("  Found PC mux: {}", mux_id);

    // Step 3: Find not-taken input (PC+4)
    let not_taken_id = find_not_taken_input(graph, &mux_id, not_taken_input_id);
    let not_taken_id = match not_taken_id {
        Some(id) => id,
        None => {
            log::info!("Could not find not-taken input - branch prediction not applicable");
            return false;
        }
    };
    log::info!("  Not-taken path: {}", not_taken_id);

    // Step 4: Create predicted_pc node
    let predicted_pc_id = "predicted_pc".to_string();
    {
        let mut data: HashMap<String, Value> = HashMap::new();
        data.insert("type".into(), json!("var"));
        data.insert("name".into(), json!("predicted_pc"));
        data.insert("display_name".into(), json!("Predicted PC (not-taken)"));
        data.insert("description".into(), json!("Predicted next PC = PC + 4 (not-taken speculation)"));
        if let Some(w) = pc_width {
            data.insert("bit_width".into(), json!(w));
        }
        let node = Node::new(
            Some(predicted_pc_id.clone()), Some(data),
            false, false, None, false, Some(0), Some(0), false, false, 0, false, true, None, None,
        );
        graph.add_node(node);
    }

    // Connect not_taken -> predicted_pc
    {
        let mut ed: HashMap<String, Value> = HashMap::new();
        ed.insert("type".into(), json!("assignment"));
        ed.insert("description".into(), json!("Speculative not-taken prediction"));
        let e = Edge::new(not_taken_id.clone(), predicted_pc_id.clone(), None, Some(ed));
        graph.add_edge(e);
    }
    log::info!("  Created predicted PC node: {}", predicted_pc_id);

    // Step 5: Find edge from mux to pc and redirect through recovery mux
    let mux_to_pc_edge_id: Option<String> = {
        let pc_node = &graph.nodes[&pc_id];
        pc_node.incoming_edges.iter()
            .find(|eid| {
                graph.edges.get(*eid)
                    .map(|e| e.source == mux_id)
                    .unwrap_or(false)
            })
            .cloned()
    };

    if let Some(ref old_edge_id) = mux_to_pc_edge_id {
        // Remove direct edge from mux to PC
        graph.remove_edge(old_edge_id);
        log::info!("  Removed direct edge from {} to {}", mux_id, pc_id);

        // Create recovery mux
        let recovery_mux_id = "pc_recovery_mux".to_string();
        {
            let mut data: HashMap<String, Value> = HashMap::new();
            data.insert("type".into(), json!("ternary_op"));
            data.insert("name".into(), json!("pc_recovery_mux"));
            data.insert("display_name".into(), json!("PC recovery mux (predicted vs actual)"));
            data.insert("operator".into(), json!("?:"));
            data.insert("description".into(), json!("Selects predicted PC normally, actual target on misprediction"));
            if let Some(w) = pc_width {
                data.insert("bit_width".into(), json!(w));
            }
            let node = Node::new(
                Some(recovery_mux_id.clone()), Some(data),
                false, false, None, false, Some(0), Some(0), false, false, 0, false, true, None, None,
            );
            graph.add_node(node);
        }

        // predicted_pc -> recovery_mux (ternary_false = normal path)
        {
            let mut ed: HashMap<String, Value> = HashMap::new();
            ed.insert("type".into(), json!("ternary_false"));
            ed.insert("description".into(), json!("Normal (predicted) PC"));
            let e = Edge::new(predicted_pc_id.clone(), recovery_mux_id.clone(), None, Some(ed));
            graph.add_edge(e);
        }

        // pc_mux -> recovery_mux (ternary_true = misprediction recovery)
        {
            let mut ed: HashMap<String, Value> = HashMap::new();
            ed.insert("type".into(), json!("ternary_true"));
            ed.insert("description".into(), json!("Actual PC on misprediction"));
            let e = Edge::new(mux_id.clone(), recovery_mux_id.clone(), None, Some(ed));
            graph.add_edge(e);
        }

        // recovery_mux -> pc
        {
            let mut ed: HashMap<String, Value> = HashMap::new();
            ed.insert("type".into(), json!("assignment"));
            ed.insert("description".into(), json!("PC update with prediction and recovery"));
            let e = Edge::new(recovery_mux_id.clone(), pc_id.clone(), None, Some(ed));
            graph.add_edge(e);
        }

        log::info!("  Created recovery mux: {}", recovery_mux_id);
        log::info!("  Connected {} -> {} -> {}", predicted_pc_id, recovery_mux_id, pc_id);

        // Step 6: Connect control_hazard_flush to recovery mux condition
        if graph.nodes.contains_key("control_hazard_flush") {
            let mut ed: HashMap<String, Value> = HashMap::new();
            ed.insert("type".into(), json!("ternary_condition"));
            ed.insert("description".into(), json!("Control hazard (misprediction) triggers PC recovery"));
            let e = Edge::new("control_hazard_flush".into(), recovery_mux_id.clone(), None, Some(ed));
            graph.add_edge(e);
            log::info!("  Connected control_hazard_flush to PC recovery mux condition");
        } else {
            log::info!("  Warning: control_hazard_flush node not found");
        }
    } else {
        log::info!("  Warning: Could not find edge from mux to PC, predicted_pc not connected!");
    }

    // Step 7: Create validity tracking nodes
    let max_time = graph.get_max_uarch_time();
    let mut gated_count = 0;

    for time in 0..=max_time {
        let validity_id = format!("stage_{}_valid", time);
        let mut data: HashMap<String, Value> = HashMap::new();
        data.insert("type".into(), json!("validity_bit"));
        data.insert("name".into(), json!(&validity_id));
        data.insert("display_name".into(), json!(format!("Stage {} validity", time)));
        data.insert("uarch_stage".into(), json!(time));
        data.insert("bit_width".into(), json!(1));
        let node = Node::new(
            Some(validity_id.clone()), Some(data),
            false, false, None, true, Some(time), Some(time), false, false, 0, false, true, None, None,
        );
        graph.add_node(node);
    }

    // Step 8: Gate architectural state updates with validity
    let arch_state_writes: Vec<(String, i64)> = graph.nodes.iter()
        .filter(|(nid, n)| {
            n.is_arch_state
                && !nid.ends_with("_rd")
                && n.incoming_edges.iter().any(|eid| {
                    graph.edges.get(eid)
                        .map(|e| {
                            let et = e.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                            et == "assignment" || et == "write_data" || et == "write_address"
                        })
                        .unwrap_or(false)
                })
        })
        .map(|(nid, n)| (nid.clone(), n.uarch_time.unwrap_or(0)))
        .collect();

    for (node_id, write_time) in &arch_state_writes {
        let validity_id = format!("stage_{}_valid", write_time);
        if graph.nodes.contains_key(&validity_id) {
            let mut ed: HashMap<String, Value> = HashMap::new();
            ed.insert("type".into(), json!("validity_check"));
            ed.insert("description".into(), json!(format!("Gate write to {} with stage {} validity", node_id, write_time)));
            let e = Edge::new(validity_id.clone(), node_id.clone(), None, Some(ed));
            graph.add_edge(e);
            gated_count += 1;
        }
    }
    log::info!("  Gated {} architectural state nodes with validity", gated_count);

    // Step 9: Re-infer timing
    graph.infer_uarch_time(true);

    log::info!("\nBranch prediction pass completed successfully");
    log::info!("{}", "=".repeat(70));
    true
}

fn find_pc_node(graph: &ResourceGraph, explicit_id: Option<&str>) -> Option<String> {
    if let Some(id) = explicit_id {
        if graph.nodes.contains_key(id) {
            return Some(id.to_string());
        }
    }
    for candidate in &["pc_wr", "pc"] {
        if graph.nodes.contains_key(*candidate) {
            return Some(candidate.to_string());
        }
    }
    None
}

fn find_pc_mux(graph: &ResourceGraph, pc_id: &str, explicit_id: Option<&str>) -> Option<String> {
    if let Some(id) = explicit_id {
        if graph.nodes.contains_key(id) {
            return Some(id.to_string());
        }
    }
    // Look for mux or ternary feeding the PC node
    let pc_node = graph.nodes.get(pc_id)?;
    for eid in &pc_node.incoming_edges {
        if let Some(edge) = graph.edges.get(eid) {
            let et = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
            if et == "assignment" {
                if let Some(src_node) = graph.nodes.get(&edge.source) {
                    let src_type = src_node.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                    if src_type == "multiplexer" || src_type == "ternary_op" {
                        return Some(edge.source.clone());
                    }
                }
            }
        }
    }
    None
}

fn find_not_taken_input(
    graph: &ResourceGraph,
    mux_id: &str,
    explicit_id: Option<&str>,
) -> Option<String> {
    if let Some(id) = explicit_id {
        if graph.nodes.contains_key(id) {
            return Some(id.to_string());
        }
    }
    let mux_node = graph.nodes.get(mux_id)?;
    // Priority 1: look for pc_add_4 or (pc + N) style input among mux inputs
    // This is the speculative PC+4 computation (not-taken prediction).
    // Must be an exact match like "(pc + 4)" not a substring of a larger expression.
    for eid in &mux_node.incoming_edges {
        if let Some(edge) = graph.edges.get(eid) {
            let src = &edge.source;
            if src == "pc_add_4"
                || src == "(pc + 4)"
                || src == "(pc + 2)"
                || (src.starts_with("(pc + ") && src.ends_with(")") && !src.contains("?"))
                || (src.starts_with("pc_add_") && !src.contains("branch"))
            {
                return Some(src.clone());
            }
        }
    }
    // Priority 1.5: Search the graph for a standalone PC+4 node.
    // In some mergers (e.g. MIPS), the (pc + 4) node exists in the graph but
    // is embedded inside branch ternary expressions rather than being a direct
    // mux input.  Use it for the not-taken prediction anyway.
    for candidate in &["pc_add_4", "(pc + 4)", "(pc + 2)", "pc_plus_4"] {
        if graph.nodes.contains_key(*candidate) {
            return Some(candidate.to_string());
        }
    }

    // Priority 2: default input or ternary_false
    for eid in &mux_node.incoming_edges {
        if let Some(edge) = graph.edges.get(eid) {
            let et = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
            if et == "mux_default_input" || et == "ternary_false" {
                return Some(edge.source.clone());
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_find_pc_node() {
        let mut graph = ResourceGraph::new();
        let pc = Node::new(Some("pc_wr".into()), None, true, false, None, false, None, None, false, false, 0, false, true, None, None);
        graph.add_node(pc);
        assert_eq!(find_pc_node(&graph, None), Some("pc_wr".to_string()));
        assert_eq!(find_pc_node(&graph, Some("pc_wr")), Some("pc_wr".to_string()));
    }
}
