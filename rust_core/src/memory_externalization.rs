//! Memory externalization: marks internal memories for external port generation.
//!
//! Port of `memory_externalization.py`. The Verilog generator uses the metadata
//! set here to emit external ports with valid-ready handshake protocol.

use serde_json::{json, Value};
use std::collections::HashMap;

use crate::resource_graph::{Edge, Node, ResourceGraph};

// ---------------------------------------------------------------------------
// MemoryExternalizationSpec
// ---------------------------------------------------------------------------

/// Specification for externalizing a memory.
#[derive(Debug, Clone)]
pub struct MemoryExternalizationSpec {
    pub memory_name: String,
    pub create_read_port: bool,
    pub create_write_port: bool,
    pub variable_latency: bool,
}

impl MemoryExternalizationSpec {
    pub fn new(memory_name: &str) -> Self {
        Self {
            memory_name: memory_name.to_string(),
            create_read_port: true,
            create_write_port: true,
            variable_latency: false,
        }
    }
}

// ---------------------------------------------------------------------------
// MemoryPortInfo
// ---------------------------------------------------------------------------

/// Information about an externalized memory port.
#[derive(Debug, Clone)]
pub struct MemoryPortInfo {
    pub memory_name: String,
    pub port_type: String, // "read" or "write"
    pub addr_width: i64,
    pub data_width: i64,
}

impl MemoryPortInfo {
    /// Get the signal definitions for this port.
    pub fn get_port_signals(&self, variable_latency: bool) -> HashMap<String, PortSignal> {
        let mut signals = HashMap::new();
        let prefix = format!("{}_{}_", self.memory_name, self.port_type);

        if self.port_type == "read" {
            signals.insert(
                format!("{prefix}req_addr"),
                PortSignal { direction: "output".into(), width: self.addr_width },
            );
            signals.insert(
                format!("{prefix}req_valid"),
                PortSignal { direction: "output".into(), width: 1 },
            );
            signals.insert(
                format!("{prefix}resp_data"),
                PortSignal { direction: "input".into(), width: self.data_width },
            );
            if variable_latency {
                signals.insert(
                    format!("{prefix}resp_ready"),
                    PortSignal { direction: "input".into(), width: 1 },
                );
            }
        } else {
            // write
            signals.insert(
                format!("{prefix}req_addr"),
                PortSignal { direction: "output".into(), width: self.addr_width },
            );
            signals.insert(
                format!("{prefix}req_data"),
                PortSignal { direction: "output".into(), width: self.data_width },
            );
            signals.insert(
                format!("{prefix}req_we"),
                PortSignal { direction: "output".into(), width: if self.data_width < 8 { 1 } else { self.data_width / 8 } },
            );
            signals.insert(
                format!("{prefix}req_valid"),
                PortSignal { direction: "output".into(), width: 1 },
            );
            if variable_latency {
                signals.insert(
                    format!("{prefix}resp_ready"),
                    PortSignal { direction: "input".into(), width: 1 },
                );
            }
        }

        signals
    }
}

#[derive(Debug, Clone)]
pub struct PortSignal {
    pub direction: String,
    pub width: i64,
}

// ---------------------------------------------------------------------------
// apply_memory_externalization
// ---------------------------------------------------------------------------

/// Mark a memory for externalization. The Verilog generator will use the
/// existing graph structure to generate the appropriate external ports.
pub fn apply_memory_externalization(
    graph: &mut ResourceGraph,
    spec: &MemoryExternalizationSpec,
) -> bool {
    let memory_name = &spec.memory_name;

    // Find the memory node
    let memory_node_id = {
        let mut found = None;
        for node in graph.nodes.values() {
            let name_match = node.data.get("name").and_then(|v| v.as_str()) == Some(memory_name);
            let is_mem = node
                .data
                .get("is_memory")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            if name_match && is_mem {
                found = Some(node.id.clone());
                break;
            }
        }
        found
    };

    let memory_node_id = match memory_node_id {
        Some(id) => id,
        None => {
            log::error!("Memory '{}' not found in graph", memory_name);
            return false;
        }
    };

    // Mark the memory node as externalized
    {
        let node = graph.nodes.get_mut(&memory_node_id).unwrap();
        node.data.insert("externalized".into(), json!(true));
        node.data
            .insert("externalize_read".into(), json!(spec.create_read_port));
        node.data
            .insert("externalize_write".into(), json!(spec.create_write_port));
        node.data
            .insert("use_valid_ready".into(), json!(spec.variable_latency));

        if spec.variable_latency {
            node.variable_latency = true;
            node.data
                .insert("memory_variable_latency".into(), json!(true));
        }
    }

    // Create combined byte enable for write ports
    if spec.create_write_port {
        create_combined_byte_enable(graph, memory_name);
    }

    true
}

// ---------------------------------------------------------------------------
// create_combined_byte_enable
// ---------------------------------------------------------------------------

/// Create combined byte enable mux nodes for each write port of an externalized
/// memory. Finds write port nodes, checks for per-instruction byte enables, and
/// creates a priority mux for each port.
fn create_combined_byte_enable(graph: &mut ResourceGraph, memory_name: &str) {
    // Find write port node(s) for this memory.
    // We need to collect IDs first to avoid borrow issues.
    let write_port_ids: Vec<String> = graph
        .nodes
        .values()
        .filter(|n| n.data.get("type").and_then(|v| v.as_str()) == Some("memory_write_port"))
        .filter(|n| {
            // Check outgoing edges for memory_write type targeting our memory
            for eid in &n.outgoing_edges {
                if let Some(edge) = graph.edges.get(eid) {
                    if edge.data.get("type").and_then(|v| v.as_str()) == Some("memory_write") {
                        if let Some(target) = graph.nodes.get(&edge.target) {
                            let target_name =
                                target.data.get("name").and_then(|v| v.as_str()).unwrap_or("");
                            if target_name == memory_name || target.id == memory_name {
                                return true;
                            }
                        }
                    }
                }
            }
            false
        })
        .map(|n| n.id.clone())
        .collect();

    for wp_id in &write_port_ids {
        let store_byte_enables: HashMap<String, String> = {
            let wp = &graph.nodes[wp_id];
            match wp.data.get("store_byte_enables") {
                Some(Value::Object(map)) => map
                    .iter()
                    .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                    .collect(),
                _ => continue,
            }
        };

        if store_byte_enables.is_empty() {
            continue;
        }

        // Build mux_inputs: (enable_node_id, byte_enable_node_id)
        let mut mux_inputs: Vec<(String, String)> = Vec::new();

        for (instr_name, be_node_id) in &store_byte_enables {
            let enable_patterns = [
                format!("{instr_name}_enable"),
                format!("{instr_name}_enable_and"),
                instr_name.replace('.', "_") + "_enable",
            ];
            let enable_node_id = enable_patterns
                .iter()
                .find(|p| graph.nodes.contains_key(p.as_str()))
                .cloned();

            if let Some(en_id) = enable_node_id {
                if graph.nodes.contains_key(be_node_id.as_str()) {
                    mux_inputs.push((en_id, be_node_id.clone()));
                }
            }
        }

        if mux_inputs.is_empty() {
            continue;
        }

        // Determine port_id and combined_be_id
        let port_id = if wp_id.ends_with("_wr") {
            &wp_id[..wp_id.len() - 3]
        } else {
            wp_id.as_str()
        };
        let combined_be_id = format!("{port_id}_byte_enable");

        // Get byte enable width from first byte enable node
        let be_width = graph
            .nodes
            .get(&mux_inputs[0].1)
            .and_then(|n| n.data.get("bit_width"))
            .and_then(|v| v.as_i64())
            .unwrap_or(4);

        // Create the combined byte enable mux node
        let mux_inputs_json: Vec<Value> = mux_inputs
            .iter()
            .map(|(en, be)| json!([en, be]))
            .collect();
        let default_value = (1i64 << be_width) - 1;

        let mut be_node = Node::with_defaults(Some(combined_be_id.clone()));
        be_node.data.insert("type".into(), json!("byte_enable_mux"));
        be_node.data.insert("name".into(), json!(&combined_be_id));
        be_node.data.insert("bit_width".into(), json!(be_width));
        be_node
            .data
            .insert("mux_inputs".into(), Value::Array(mux_inputs_json));
        be_node
            .data
            .insert("default_value".into(), json!(default_value));
        graph.add_node(be_node);

        // Add edges from enable and byte_enable nodes to the mux
        for (enable_node_id, be_node_id) in &mux_inputs {
            let mut edata1 = HashMap::new();
            edata1.insert("type".into(), json!("mux_select"));
            let e1 = Edge::new(
                enable_node_id.clone(),
                combined_be_id.clone(),
                None,
                Some(edata1),
            );
            graph.add_edge(e1);

            let mut edata2 = HashMap::new();
            edata2.insert("type".into(), json!("mux_input"));
            let e2 = Edge::new(
                be_node_id.clone(),
                combined_be_id.clone(),
                None,
                Some(edata2),
            );
            graph.add_edge(e2);
        }

        // Store combined byte enable node ID on the write port
        graph
            .nodes
            .get_mut(wp_id)
            .unwrap()
            .data
            .insert("combined_byte_enable".into(), json!(&combined_be_id));
    }
}

// ---------------------------------------------------------------------------
// get_externalized_memories
// ---------------------------------------------------------------------------

/// Get list of memory names that have been marked for externalization.
pub fn get_externalized_memories(graph: &ResourceGraph) -> Vec<String> {
    graph
        .nodes
        .values()
        .filter(|n| {
            n.data
                .get("is_memory")
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
                && n.data
                    .get("externalized")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false)
        })
        .map(|n| {
            n.data
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or(&n.id)
                .to_string()
        })
        .collect()
}

// ---------------------------------------------------------------------------
// create_memory_stall_signals
// ---------------------------------------------------------------------------

/// Create stall condition signals for an externalized memory.
/// Returns the stall condition node ID, or None if not applicable.
pub fn create_memory_stall_signals(
    graph: &mut ResourceGraph,
    memory_name: &str,
) -> Option<String> {
    // Find the memory node
    let memory_node_id = {
        let mut found = None;
        for node in graph.nodes.values() {
            let name_match = node.data.get("name").and_then(|v| v.as_str()) == Some(memory_name);
            let is_mem = node
                .data
                .get("is_memory")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            let is_ext = node
                .data
                .get("externalized")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            if name_match && is_mem && is_ext {
                found = Some(node.id.clone());
                break;
            }
        }
        found
    };

    let memory_node_id = memory_node_id?;

    let use_valid_ready = graph.nodes[&memory_node_id]
        .data
        .get("use_valid_ready")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let mem_var_lat = graph.nodes[&memory_node_id]
        .data
        .get("memory_variable_latency")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    if !use_valid_ready && !mem_var_lat {
        return None;
    }

    let ext_read = graph.nodes[&memory_node_id]
        .data
        .get("externalize_read")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let ext_write = graph.nodes[&memory_node_id]
        .data
        .get("externalize_write")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);

    let mut stall_conditions: Vec<String> = Vec::new();

    // Read stall
    if ext_read {
        let not_id = format!("{memory_name}_not_read_resp_ready");
        let mut not_node = Node::with_defaults(Some(not_id.clone()));
        not_node.data.insert("type".into(), json!("operation"));
        not_node.data.insert("operation".into(), json!("not"));
        not_node.data.insert("bit_width".into(), json!(1));
        graph.add_node(not_node);

        let stall_id = format!("{memory_name}_read_stall");
        let mut stall_node = Node::with_defaults(Some(stall_id.clone()));
        stall_node.data.insert("type".into(), json!("operation"));
        stall_node.data.insert("operation".into(), json!("and"));
        stall_node.data.insert("bit_width".into(), json!(1));
        graph.add_node(stall_node);

        stall_conditions.push(stall_id);
    }

    // Write stall
    if ext_write {
        let not_id = format!("{memory_name}_not_write_resp_ready");
        let mut not_node = Node::with_defaults(Some(not_id.clone()));
        not_node.data.insert("type".into(), json!("operation"));
        not_node.data.insert("operation".into(), json!("not"));
        not_node.data.insert("bit_width".into(), json!(1));
        graph.add_node(not_node);

        let stall_id = format!("{memory_name}_write_stall");
        let mut stall_node = Node::with_defaults(Some(stall_id.clone()));
        stall_node.data.insert("type".into(), json!("operation"));
        stall_node.data.insert("operation".into(), json!("and"));
        stall_node.data.insert("bit_width".into(), json!(1));
        graph.add_node(stall_node);

        stall_conditions.push(stall_id);
    }

    if stall_conditions.is_empty() {
        return None;
    }

    let stall_signal_id = if stall_conditions.len() == 1 {
        stall_conditions[0].clone()
    } else {
        let stall_or_id = format!("{memory_name}_stall_condition");
        let mut stall_or = Node::with_defaults(Some(stall_or_id.clone()));
        stall_or.data.insert("type".into(), json!("operation"));
        stall_or.data.insert("operation".into(), json!("or"));
        stall_or.data.insert("bit_width".into(), json!(1));
        graph.add_node(stall_or);

        for (i, cond_id) in stall_conditions.iter().enumerate() {
            let mut edata = HashMap::new();
            edata.insert("type".into(), json!("operand"));
            edata.insert("operand_index".into(), json!(i));
            let edge = Edge::new(cond_id.clone(), stall_or_id.clone(), None, Some(edata));
            graph.add_edge(edge);
        }

        stall_or_id
    };

    // Store stall condition reference on memory node
    graph
        .nodes
        .get_mut(&memory_node_id)
        .unwrap()
        .data
        .insert("stall_condition_node".into(), json!(&stall_signal_id));

    Some(stall_signal_id)
}
