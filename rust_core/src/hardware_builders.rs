//! Hardware builder utilities for ResourceGraph pipeline optimizations.
//!
//! Provides common building blocks: comparators, literals, stall logic,
//! pipeline registers, and array access analysis.

use crate::resource_graph::{Edge, Node, ResourceGraph};
use serde_json::{json, Value};
use std::collections::HashMap;

// =========================================================================
// Array access analysis
// =========================================================================

/// Information about an array access (read or write).
#[derive(Debug, Clone)]
pub struct ArrayAccessInfo {
    pub node_id: String,
    pub base_resource: String,
    pub index: String,
    pub index_node_id: Option<String>,
    pub access_type: AccessType,
    pub access_key: String,
    pub uarch_time: i64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AccessType {
    Read,
    Write,
    ReadWrite,
    Unknown,
}

/// Parse an array access node name to extract base resource and index.
///
/// Examples:
///   "rf[rs]" -> Some(("rf", "rs"))
///   "rf[rd]_wr" -> Some(("rf", "rd"))
///   "p0_rf[rs]_rd" -> Some(("rf", "rs"))
pub fn parse_array_access_name(node_name: &str) -> Option<(String, String)> {
    if !node_name.contains('[') || !node_name.contains(']') {
        return None;
    }

    let mut working = node_name.to_string();

    // Strip dual-issue prefix if present
    if working.starts_with("p0_") || working.starts_with("p1_") {
        working = working[3..].to_string();
    }

    // Handle instruction-specific names like "add_imm_rf[rt]_spec"
    if working.ends_with("_spec") {
        let parts: Vec<&str> = working.split('_').collect();
        for (i, part) in parts.iter().enumerate() {
            if part.contains('[') {
                let resource_part = parts[i..].join("_").replace("_spec", "");
                let base = resource_part.split('[').next()?;
                let idx = resource_part.split('[').nth(1)?.split(']').next()?;
                return Some((base.to_string(), idx.to_string()));
            }
        }
    }

    // Normal case: strip suffixes like _rd, _wr
    let clean = working.replace("_rd", "").replace("_wr", "");
    if clean.contains('[') && clean.contains(']') {
        let base = clean.split('[').next()?;
        let idx = clean.split('[').nth(1)?.split(']').next()?;
        return Some((base.to_string(), idx.to_string()));
    }

    None
}

/// Classify an array access node as Read, Write, or ReadWrite based on edges.
pub fn classify_access_type(node: &Node, graph: &ResourceGraph) -> AccessType {
    let mut has_incoming_assignment = false;
    let mut has_outgoing_assignment = false;
    let mut has_outgoing_pipeline = false;

    for eid in &node.incoming_edges {
        if let Some(edge) = graph.edges.get(eid) {
            let et = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
            if et == "assignment" {
                has_incoming_assignment = true;
            }
        }
    }

    for eid in &node.outgoing_edges {
        if let Some(edge) = graph.edges.get(eid) {
            let et = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
            if et == "assignment" {
                has_outgoing_assignment = true;
            } else if et == "pipeline_input" {
                has_outgoing_pipeline = true;
            }
        }
    }

    if has_incoming_assignment && !has_outgoing_assignment && !has_outgoing_pipeline {
        AccessType::Write
    } else if (has_outgoing_assignment || has_outgoing_pipeline) && !has_incoming_assignment {
        AccessType::Read
    } else if has_incoming_assignment && (has_outgoing_assignment || has_outgoing_pipeline) {
        AccessType::ReadWrite
    } else {
        AccessType::Unknown
    }
}

/// Find the node that provides the index for an array access.
pub fn find_index_node<'a>(
    array_access_node: &Node,
    graph: &'a ResourceGraph,
) -> Option<&'a str> {
    let node_name = array_access_node.data.get("name")
        .and_then(|v| v.as_str())
        .unwrap_or(&array_access_node.id);

    let (base_resource, _) = parse_array_access_name(node_name)?;

    for eid in &array_access_node.incoming_edges {
        if let Some(edge) = graph.edges.get(eid) {
            let et = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
            if et == "array_index" && edge.source != base_resource {
                return Some(edge.source.as_str());
            }
        }
    }
    None
}

/// Get all array accesses in the graph, optionally filtered by resource name.
pub fn get_all_array_accesses(
    graph: &ResourceGraph,
    resource_name: Option<&str>,
) -> Vec<ArrayAccessInfo> {
    let mut accesses = Vec::new();

    let mut sorted_ids: Vec<&String> = graph.nodes.keys().collect();
    sorted_ids.sort();

    for node_id in sorted_ids {
        let node = &graph.nodes[node_id];
        let nt = node.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
        if nt != "array_access" {
            continue;
        }

        let node_name = node.data.get("name")
            .and_then(|v| v.as_str())
            .unwrap_or(node_id);

        let (base_resource, index) = match parse_array_access_name(node_name) {
            Some(pair) => pair,
            None => continue,
        };

        if let Some(filter) = resource_name {
            if base_resource != filter {
                continue;
            }
        }

        let access_type = classify_access_type(node, graph);
        let index_node_id = find_index_node(node, graph).map(|s| s.to_string());
        let uarch_time = node.uarch_time.unwrap_or(0);
        let access_key = format!("{}[{}]", base_resource, index);

        accesses.push(ArrayAccessInfo {
            node_id: node_id.clone(),
            base_resource,
            index,
            index_node_id,
            access_type,
            access_key,
            uarch_time,
        });
    }

    accesses
}

/// Get separate lists of read and write accesses.
pub fn get_reads_and_writes(
    graph: &ResourceGraph,
    resource_name: Option<&str>,
) -> (Vec<ArrayAccessInfo>, Vec<ArrayAccessInfo>) {
    let all = get_all_array_accesses(graph, resource_name);
    let reads = all.iter()
        .filter(|a| a.access_type == AccessType::Read || a.access_type == AccessType::ReadWrite)
        .cloned()
        .collect();
    let writes = all.iter()
        .filter(|a| a.access_type == AccessType::Write || a.access_type == AccessType::ReadWrite)
        .cloned()
        .collect();
    (reads, writes)
}

// =========================================================================
// Comparator builder
// =========================================================================

/// Create an index comparator node (e.g., rd == rs).
pub fn create_index_comparator(
    graph: &mut ResourceGraph,
    comp_id: &str,
    left_node_id: &str,
    right_node_id: &str,
    operator: &str,
    display_name: Option<&str>,
    extra_metadata: Option<HashMap<String, Value>>,
) -> String {
    let default_display = format!("{} {} {}", left_node_id, operator, right_node_id);
    let display = display_name.unwrap_or(&default_display);

    let mut comp_data: HashMap<String, Value> = HashMap::new();
    comp_data.insert("type".into(), json!("operation"));
    comp_data.insert("operator".into(), json!(operator));
    comp_data.insert("operation".into(), json!(format!("{} {} {}", left_node_id, operator, right_node_id)));
    comp_data.insert("display_name".into(), json!(display));
    comp_data.insert("bit_width".into(), json!(1));

    if let Some(extra) = extra_metadata {
        for (k, v) in extra {
            comp_data.insert(k, v);
        }
    }

    let comp_node = Node::new(
        Some(comp_id.to_string()), Some(comp_data),
        false, false, None, false, None, None, false, false, 0, false, true, None, None,
    );
    graph.add_node(comp_node);

    // Connect operands
    let mut left_data: HashMap<String, Value> = HashMap::new();
    left_data.insert("type".into(), json!("operand"));
    left_data.insert("position".into(), json!("left"));
    left_data.insert("operand_index".into(), json!(0));
    let left_edge = Edge::new(left_node_id.to_string(), comp_id.to_string(), None, Some(left_data));
    graph.add_edge(left_edge);

    let mut right_data: HashMap<String, Value> = HashMap::new();
    right_data.insert("type".into(), json!("operand"));
    right_data.insert("position".into(), json!("right"));
    right_data.insert("operand_index".into(), json!(1));
    let right_edge = Edge::new(right_node_id.to_string(), comp_id.to_string(), None, Some(right_data));
    graph.add_edge(right_edge);

    comp_id.to_string()
}

// =========================================================================
// Literal builder
// =========================================================================

/// Create or reuse a literal node with the given value.
pub fn create_or_get_literal(
    graph: &mut ResourceGraph,
    value: i64,
) -> String {
    let literal_id = value.to_string();
    if graph.nodes.contains_key(&literal_id) {
        return literal_id;
    }

    let mut data: HashMap<String, Value> = HashMap::new();
    data.insert("type".into(), json!("literal"));
    data.insert("value".into(), json!(value));
    data.insert("display_name".into(), json!(value.to_string()));

    let node = Node::new(
        Some(literal_id.clone()), Some(data),
        false, false, None, false, None, None, false, false, 0, false, true, None, None,
    );
    graph.add_node(node);
    literal_id
}

// =========================================================================
// Stall logic builder
// =========================================================================

/// Create or get a stall controller for a pipeline stage.
pub fn create_or_get_stall_controller(
    graph: &mut ResourceGraph,
    controller_id: &str,
    stage_name: &str,
    pipeline_prefix: &str,
) -> String {
    if graph.nodes.contains_key(controller_id) {
        return controller_id.to_string();
    }

    let mut data: HashMap<String, Value> = HashMap::new();
    data.insert("type".into(), json!("pipeline_stall_controller"));
    data.insert("name".into(), json!(controller_id));
    data.insert("display_name".into(), json!(format!("Stall controller for {}", stage_name)));
    data.insert("stage_name".into(), json!(stage_name));
    data.insert("stall_type".into(), json!("hazard_detection"));
    data.insert("pipeline_component".into(), json!(true));
    data.insert("pipeline_prefix".into(), json!(pipeline_prefix));
    data.insert("bit_width".into(), json!(1));

    let node = Node::new(
        Some(controller_id.to_string()), Some(data),
        false, false, None, false, None, None, false, false, 0, false, true, None, None,
    );
    graph.add_node(node);
    controller_id.to_string()
}

// =========================================================================
// Pipeline register builder
// =========================================================================

/// Create a pipeline register node.
pub fn create_pipeline_register(
    graph: &mut ResourceGraph,
    register_id: &str,
    stage_name: Option<&str>,
    pipeline_prefix: &str,
    pipe_time: Option<i64>,
    extra_metadata: Option<HashMap<String, Value>>,
) -> String {
    let display = stage_name
        .map(|s| format!("Pipeline register for {}", s))
        .unwrap_or_else(|| format!("Pipeline register {}", register_id));

    let mut data: HashMap<String, Value> = HashMap::new();
    data.insert("type".into(), json!("pipeline_register"));
    data.insert("name".into(), json!(register_id));
    data.insert("display_name".into(), json!(display));
    data.insert("pipeline_component".into(), json!(true));
    data.insert("pipeline_prefix".into(), json!(pipeline_prefix));

    if let Some(sn) = stage_name {
        data.insert("stage_name".into(), json!(sn));
    }
    if let Some(extra) = extra_metadata {
        for (k, v) in extra {
            data.insert(k, v);
        }
    }

    let node = Node::new(
        Some(register_id.to_string()), Some(data),
        false, false, None, true, // is_uarch_state
        pipe_time, pipe_time, // uarch_time, pipe_time
        false, false, 0, false, true, None, None,
    );
    graph.add_node(node);
    register_id.to_string()
}

/// Insert a pipeline register in the middle of an edge.
/// Removes the original edge and creates source->register and register->target edges.
/// Returns (input_edge_id, output_edge_id).
pub fn insert_register_on_edge(
    graph: &mut ResourceGraph,
    edge_id: &str,
    register_id: &str,
    stall_controller_id: Option<&str>,
) -> Option<(String, String)> {
    let (source, target, original_type) = {
        let edge = graph.edges.get(edge_id)?;
        (
            edge.source.clone(),
            edge.target.clone(),
            edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        )
    };

    // Remove original edge
    graph.remove_edge(edge_id);

    // Create input edge: source -> register
    let mut input_data: HashMap<String, Value> = HashMap::new();
    input_data.insert("type".into(), json!("pipeline_input"));
    input_data.insert("pipeline_component".into(), json!(true));
    input_data.insert("original_type".into(), json!(&original_type));
    if let Some(sc) = stall_controller_id {
        input_data.insert("gated_by".into(), json!(format!("{}_enable", sc)));
    }
    let input_edge = Edge::new(source, register_id.to_string(), None, Some(input_data));
    let input_id = input_edge.id.clone();
    graph.add_edge(input_edge);

    // Create output edge: register -> target
    let mut output_data: HashMap<String, Value> = HashMap::new();
    output_data.insert("type".into(), json!(&original_type));
    output_data.insert("pipeline_component".into(), json!(true));
    output_data.insert("from_pipeline_reg".into(), json!(true));
    output_data.insert("original_type".into(), json!(&original_type));
    let output_edge = Edge::new(register_id.to_string(), target, None, Some(output_data));
    let output_id = output_edge.id.clone();
    graph.add_edge(output_edge);

    Some((input_id, output_id))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_array_access_name() {
        assert_eq!(parse_array_access_name("rf[rs]"), Some(("rf".into(), "rs".into())));
        assert_eq!(parse_array_access_name("rf[rd]_wr"), Some(("rf".into(), "rd".into())));
        assert_eq!(parse_array_access_name("p0_rf[rs]_rd"), Some(("rf".into(), "rs".into())));
        assert_eq!(parse_array_access_name("no_brackets"), None);
    }

    #[test]
    fn test_create_literal() {
        let mut graph = ResourceGraph::new();
        let id = create_or_get_literal(&mut graph, 42);
        assert_eq!(id, "42");
        assert!(graph.nodes.contains_key("42"));
        // Reuse
        let id2 = create_or_get_literal(&mut graph, 42);
        assert_eq!(id, id2);
    }

    #[test]
    fn test_create_comparator() {
        let mut graph = ResourceGraph::new();
        // Create two dummy nodes
        let n1 = Node::new(Some("rd".into()), None, false, false, None, false, None, None, false, false, 0, false, true, None, None);
        let n2 = Node::new(Some("rs".into()), None, false, false, None, false, None, None, false, false, 0, false, true, None, None);
        graph.add_node(n1);
        graph.add_node(n2);

        let cid = create_index_comparator(&mut graph, "rd_eq_rs", "rd", "rs", "==", None, None);
        assert_eq!(cid, "rd_eq_rs");
        assert!(graph.nodes.contains_key("rd_eq_rs"));
    }
}
