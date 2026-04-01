//! Multi-cycle operation support for ResourceGraphs.
//!
//! Implements `set_memory_variable_latency` and `wire_memory_start_signal`
//! needed by the pipeline creation scripts.

use crate::hardware_builders;
use crate::resource_graph::{Edge, Node, ResourceGraph};
use serde_json::{json, Value};
use std::collections::HashMap;

/// Set a memory to have variable (unknown) latency.
///
/// Creates start, idle, and complete control signal nodes.
pub fn set_memory_variable_latency(
    graph: &mut ResourceGraph,
    memory_name: &str,
    enable: bool,
    min_latency: i64,
    max_latency: i64,
) -> bool {
    log::info!("\n=== Setting Memory Variable Latency ===");
    log::info!("Memory: {}", memory_name);
    log::info!("Enable variable latency: {}", enable);

    let mem_exists = graph.nodes.contains_key(memory_name);
    if !mem_exists {
        log::info!("ERROR: Memory {} not found in graph", memory_name);
        return false;
    }

    // Check if this is a memory node
    {
        let memory = &graph.nodes[memory_name];
        let is_memory = memory.data.get("is_memory").and_then(|v| v.as_bool()).unwrap_or(false)
            || memory.data.get("type").and_then(|v| v.as_str()).unwrap_or("").contains("mem");
        if !is_memory {
            log::info!("ERROR: Node {} is not a memory", memory_name);
            return false;
        }
    }

    if enable {
        // Check if already variable latency
        if graph.nodes[memory_name].variable_latency {
            log::info!("  Memory already has variable latency (no change needed)");
            return true;
        }

        // Set variable latency attributes
        {
            let memory = graph.nodes.get_mut(memory_name).unwrap();
            memory.variable_latency = true;
            memory.latency = 0;
            memory.data.insert("variable_latency".into(), json!(true));
            memory.data.insert("has_complete_output".into(), json!(true));
            memory.data.insert("min_latency".into(), json!(min_latency));
            memory.data.insert("max_latency".into(), json!(max_latency));
        }
        log::info!("  Latency range: {}-{} cycles", min_latency, max_latency);

        // Create control signal nodes
        create_memory_latency_signals(graph, memory_name);

        log::info!("  Variable latency enabled for memory {}", memory_name);
    } else {
        if !graph.nodes[memory_name].variable_latency {
            log::info!("  Memory already has fixed/combinational latency (no change needed)");
            return true;
        }

        remove_memory_latency_signals(graph, memory_name);

        let memory = graph.nodes.get_mut(memory_name).unwrap();
        memory.variable_latency = false;
        memory.latency = 0;
        memory.data.insert("variable_latency".into(), json!(false));
        memory.data.insert("has_complete_output".into(), json!(false));

        log::info!("  Variable latency disabled for memory {}", memory_name);
    }

    true
}

fn create_memory_latency_signals(graph: &mut ResourceGraph, memory_name: &str) {
    let start_id = format!("{}_start", memory_name);
    let idle_id = format!("{}_idle", memory_name);
    let complete_id = format!("{}_complete", memory_name);

    // Create start signal node
    let mut start_data: HashMap<String, Value> = HashMap::new();
    start_data.insert("type".into(), json!("control_signal"));
    start_data.insert("signal_type".into(), json!("start"));
    start_data.insert("memory".into(), json!(memory_name));
    start_data.insert("direction".into(), json!("input"));
    start_data.insert("description".into(), json!(format!("Start signal for {} (new access begun)", memory_name)));
    start_data.insert("bit_width".into(), json!(1));
    let start_node = Node::new(
        Some(start_id.clone()), Some(start_data),
        false, false, None, false, None, None, false, false, 0, false, true, None, None,
    );
    graph.add_node(start_node);

    // Edge: start -> memory
    let mut se_data: HashMap<String, Value> = HashMap::new();
    se_data.insert("type".into(), json!("control"));
    se_data.insert("signal_type".into(), json!("start"));
    let se = Edge::new(start_id.clone(), memory_name.to_string(), None, Some(se_data));
    graph.add_edge(se);

    // Create idle signal node
    let mut idle_data: HashMap<String, Value> = HashMap::new();
    idle_data.insert("type".into(), json!("control_signal"));
    idle_data.insert("signal_type".into(), json!("idle"));
    idle_data.insert("memory".into(), json!(memory_name));
    idle_data.insert("direction".into(), json!("output"));
    idle_data.insert("description".into(), json!(format!("Idle signal for {} (ready for new request)", memory_name)));
    idle_data.insert("bit_width".into(), json!(1));
    let idle_node = Node::new(
        Some(idle_id.clone()), Some(idle_data),
        false, false, None, false, None, None, false, false, 0, false, true, None, None,
    );
    graph.add_node(idle_node);

    // Edge: memory -> idle
    let mut ie_data: HashMap<String, Value> = HashMap::new();
    ie_data.insert("type".into(), json!("control"));
    ie_data.insert("signal_type".into(), json!("idle"));
    let ie = Edge::new(memory_name.to_string(), idle_id.clone(), None, Some(ie_data));
    graph.add_edge(ie);

    // Create complete signal node
    let mut complete_data: HashMap<String, Value> = HashMap::new();
    complete_data.insert("type".into(), json!("control_signal"));
    complete_data.insert("signal_type".into(), json!("complete"));
    complete_data.insert("memory".into(), json!(memory_name));
    complete_data.insert("direction".into(), json!("output"));
    complete_data.insert("description".into(), json!(format!("Completion signal for {}", memory_name)));
    complete_data.insert("bit_width".into(), json!(1));
    let complete_node = Node::new(
        Some(complete_id.clone()), Some(complete_data),
        false, false, None, false, None, None, false, false, 0, false, true, None, None,
    );
    graph.add_node(complete_node);

    // Edge: memory -> complete
    let mut ce_data: HashMap<String, Value> = HashMap::new();
    ce_data.insert("type".into(), json!("control"));
    ce_data.insert("signal_type".into(), json!("complete"));
    let ce = Edge::new(memory_name.to_string(), complete_id.clone(), None, Some(ce_data));
    graph.add_edge(ce);

    // Update memory metadata
    let memory = graph.nodes.get_mut(memory_name).unwrap();
    memory.data.insert("start_signal".into(), json!(&start_id));
    memory.data.insert("idle_signal".into(), json!(&idle_id));
    memory.data.insert("complete_signal".into(), json!(&complete_id));
    memory.data.insert("has_start_input".into(), json!(true));
    memory.data.insert("has_idle_output".into(), json!(true));

    log::info!("  Created control signals: {}, {}, {}", start_id, idle_id, complete_id);
}

fn remove_memory_latency_signals(graph: &mut ResourceGraph, memory_name: &str) {
    let signal_ids: Vec<String> = {
        let memory = &graph.nodes[memory_name];
        vec![
            memory.data.get("start_signal").and_then(|v| v.as_str()).map(|s| s.to_string()),
            memory.data.get("idle_signal").and_then(|v| v.as_str()).map(|s| s.to_string()),
            memory.data.get("complete_signal").and_then(|v| v.as_str()).map(|s| s.to_string()),
        ].into_iter().flatten().collect()
    };

    for signal_id in &signal_ids {
        if graph.nodes.contains_key(signal_id) {
            graph.remove_node(signal_id);
            log::info!("  Removed signal node: {}", signal_id);
        }
    }

    let memory = graph.nodes.get_mut(memory_name).unwrap();
    memory.data.remove("start_signal");
    memory.data.remove("idle_signal");
    memory.data.remove("complete_signal");
    memory.data.remove("has_start_input");
    memory.data.remove("has_idle_output");
}

/// Wire the start signal for a variable latency memory.
///
/// Creates: start = idle && access_enable
/// where access_enable = OR of all read/write enables.
pub fn wire_memory_start_signal(graph: &mut ResourceGraph, memory_name: &str) -> bool {
    let mem_exists = graph.nodes.contains_key(memory_name);
    if !mem_exists {
        log::info!("ERROR: Memory {} not found", memory_name);
        return false;
    }

    if !graph.nodes[memory_name].variable_latency {
        log::info!("ERROR: Memory {} is not variable latency", memory_name);
        return false;
    }

    // Get signal IDs
    let (start_signal_id, idle_signal_id) = {
        let memory = &graph.nodes[memory_name];
        let start = memory.data.get("start_signal").and_then(|v| v.as_str()).map(|s| s.to_string());
        let idle = memory.data.get("idle_signal").and_then(|v| v.as_str()).map(|s| s.to_string());
        match (start, idle) {
            (Some(s), Some(i)) => (s, i),
            _ => {
                log::info!("ERROR: Memory {} missing start or idle signal", memory_name);
                return false;
            }
        }
    };

    if !graph.nodes.contains_key(&start_signal_id) || !graph.nodes.contains_key(&idle_signal_id) {
        log::info!("ERROR: Could not find start or idle signal nodes");
        return false;
    }

    // Find read and write accesses
    let (read_accesses, write_accesses) = hardware_builders::get_reads_and_writes(graph, Some(memory_name));
    log::info!("  Found {} read accesses, {} write accesses", read_accesses.len(), write_accesses.len());

    // Find write enable node (validity-gated preferred)
    let write_enable_id: Option<String> = {
        let mut result = None;
        // First look for validity-gated version
        let mut sorted_ids: Vec<&String> = graph.nodes.keys().collect();
        sorted_ids.sort();
        for nid in &sorted_ids {
            if nid.contains(&format!("{}_write_enable", memory_name)) && nid.contains("valid_gated") {
                result = Some((*nid).clone());
                break;
            }
        }
        if result.is_none() {
            let we_id = format!("{}_write_enable", memory_name);
            if graph.nodes.contains_key(&we_id) {
                result = Some(we_id);
            }
        }
        result
    };

    // Find read enable nodes
    let mut read_enable_ids: Vec<String> = Vec::new();
    for access in &read_accesses {
        let node = &graph.nodes[&access.node_id];

        // Check node data for read_enable
        if let Some(re_id) = node.data.get("read_enable").and_then(|v| v.as_str()) {
            if graph.nodes.contains_key(re_id) {
                read_enable_ids.push(re_id.to_string());
                continue;
            }
        }

        // Check explicit rd_enable pattern
        let rd_enable_id = format!("{}_{}_rd_enable", memory_name, access.index);
        if graph.nodes.contains_key(&rd_enable_id) {
            read_enable_ids.push(rd_enable_id);
            continue;
        }

        // Look for instruction enables connected to this read
        let incoming: Vec<String> = node.incoming_edges.iter().cloned().collect();
        for eid in &incoming {
            if let Some(edge) = graph.edges.get(eid) {
                let source_id = &edge.source;
                if source_id.to_lowercase().contains("enable") {
                    if let Some(src_node) = graph.nodes.get(source_id) {
                        let bw = src_node.data.get("bit_width").and_then(|v| v.as_i64()).unwrap_or(32);
                        if bw == 1 && !read_enable_ids.contains(source_id) {
                            read_enable_ids.push(source_id.clone());
                        }
                    }
                }
            }
        }
    }

    if let Some(ref we) = write_enable_id {
        log::info!("  Found write enable: {}", we);
    }
    log::info!("  Found {} read enable signals", read_enable_ids.len());

    if write_enable_id.is_none() && read_enable_ids.is_empty() {
        log::info!("  Warning: Could not find any memory access enables for {}", memory_name);
        return false;
    }

    // Gate read enables with Memory stage validity
    // Find the pipeline validity signal whose stage name contains "Memory".
    // This matches IDs of the form "PIPE_{stage}_valid_PIPE", e.g.:
    // - PIPE_Memory_valid_PIPE          (5-stage)
    // - PIPE_MemoryWriteback_valid_PIPE (4-stage)
    // - PIPE_ExecuteMemoryWriteback_valid_PIPE (3-stage)
    let memory_valid_id: Option<String> = {
        let mut result = None;
        for nid in graph.nodes.keys() {
            if nid.starts_with("PIPE_") && nid.ends_with("_valid_PIPE") {
                let stage_name = &nid["PIPE_".len()..nid.len() - "_valid_PIPE".len()];
                if stage_name.contains("Memory") {
                    result = Some(nid.clone());
                    break;
                }
            }
        }
        result
    };

    let mut gated_read_enable_ids: Vec<String> = Vec::new();
    if let Some(ref valid_id) = memory_valid_id {
        for re_id in &read_enable_ids {
            let gated_id = format!("{}_valid_gated", re_id);
            if !graph.nodes.contains_key(&gated_id) {
                // Copy pipe_time from source node
                let (pt, ut) = {
                    let src = &graph.nodes[re_id];
                    (src.pipe_time, src.uarch_time)
                };

                let mut data: HashMap<String, Value> = HashMap::new();
                data.insert("type".into(), json!("logical_and"));
                data.insert("description".into(), json!("Memory read enable gated with validity"));
                data.insert("pipeline_component".into(), json!(true));
                data.insert("bit_width".into(), json!(1));
                let node = Node::new(
                    Some(gated_id.clone()), Some(data),
                    false, false, None, false, pt, ut, false, false, 0, false, true, None, None,
                );
                graph.add_node(node);

                let mut e1d: HashMap<String, Value> = HashMap::new();
                e1d.insert("type".into(), json!("logic_input"));
                e1d.insert("operand_position".into(), json!(0));
                let e1 = Edge::new(re_id.clone(), gated_id.clone(), None, Some(e1d));
                graph.add_edge(e1);

                let mut e2d: HashMap<String, Value> = HashMap::new();
                e2d.insert("type".into(), json!("logic_input"));
                e2d.insert("operand_position".into(), json!(1));
                let e2 = Edge::new(valid_id.clone(), gated_id.clone(), None, Some(e2d));
                graph.add_edge(e2);

                log::info!("  Gated read enable {} with Memory validity", re_id);
            }
            gated_read_enable_ids.push(gated_id);
        }
    } else {
        gated_read_enable_ids = read_enable_ids.clone();
    }

    // Check for RW cache
    let has_rw_cache = graph.nodes.values().any(|n| {
        n.data.get("type").and_then(|v| v.as_str()) == Some("read_write_cache")
            && n.data.get("memory_name").and_then(|v| v.as_str()) == Some(memory_name)
    });

    // Build all enables list
    let mut all_enables: Vec<String> = Vec::new();
    if let Some(ref we_id) = write_enable_id {
        if !has_rw_cache {
            all_enables.push(we_id.clone());
        } else {
            log::info!("  Skipping {} (stores go through RW cache write-through)", we_id);
        }
    }
    all_enables.extend(gated_read_enable_ids);

    // Create access_enable OR gate
    let or_gate_id = format!("{}_access_enable", memory_name);
    {
        // Copy pipe_time from first input
        let (pt, ut) = all_enables.first()
            .and_then(|id| graph.nodes.get(id))
            .map(|n| (n.pipe_time, n.uarch_time))
            .unwrap_or((None, None));

        let mut data: HashMap<String, Value> = HashMap::new();
        data.insert("type".into(), json!("logical_or"));
        data.insert("description".into(), json!(format!("Memory access enable for {}: any read or write", memory_name)));
        data.insert("pipeline_component".into(), json!(true));
        data.insert("bit_width".into(), json!(1));
        let node = Node::new(
            Some(or_gate_id.clone()), Some(data),
            false, false, None, false, pt, ut, false, false, 0, false, true, None, None,
        );
        graph.add_node(node);
    }

    for (i, enable_id) in all_enables.iter().enumerate() {
        let mut ed: HashMap<String, Value> = HashMap::new();
        ed.insert("type".into(), json!("logic_input"));
        ed.insert("operand_position".into(), json!(i));
        let e = Edge::new(enable_id.clone(), or_gate_id.clone(), None, Some(ed));
        graph.add_edge(e);
    }
    log::info!("  Created {} OR with {} initial input(s)", or_gate_id, all_enables.len());

    // Wire start signal
    let is_instruction_memory = memory_name == "imem";

    if is_instruction_memory {
        // imem: start = idle
        let mut ed: HashMap<String, Value> = HashMap::new();
        ed.insert("type".into(), json!("operand"));
        ed.insert("description".into(), json!(format!("Start condition for {}: always fetch when idle", memory_name)));
        let e = Edge::new(idle_signal_id.clone(), start_signal_id.clone(), None, Some(ed));
        graph.add_edge(e);
        log::info!("  Wired {} = {} (instruction memory always fetches)", start_signal_id, idle_signal_id);
    } else {
        // dmem: start = idle && access_enable
        let and_gate_id = format!("{}_start_condition", memory_name);
        let mut and_data: HashMap<String, Value> = HashMap::new();
        and_data.insert("type".into(), json!("logical_and"));
        and_data.insert("description".into(), json!(format!("Start condition for {}: idle && access_enable", memory_name)));
        and_data.insert("pipeline_component".into(), json!(true));
        and_data.insert("bit_width".into(), json!(1));
        let and_node = Node::new(
            Some(and_gate_id.clone()), Some(and_data),
            false, false, None, false, None, None, false, false, 0, false, true, None, None,
        );
        graph.add_node(and_node);

        // idle -> AND
        let mut e1d: HashMap<String, Value> = HashMap::new();
        e1d.insert("type".into(), json!("logic_input"));
        e1d.insert("operand_position".into(), json!(0));
        let e1 = Edge::new(idle_signal_id.clone(), and_gate_id.clone(), None, Some(e1d));
        graph.add_edge(e1);

        // access_enable -> AND
        let mut e2d: HashMap<String, Value> = HashMap::new();
        e2d.insert("type".into(), json!("logic_input"));
        e2d.insert("operand_position".into(), json!(1));
        let e2 = Edge::new(or_gate_id.clone(), and_gate_id.clone(), None, Some(e2d));
        graph.add_edge(e2);

        // AND -> start
        let mut e3d: HashMap<String, Value> = HashMap::new();
        e3d.insert("type".into(), json!("operand"));
        e3d.insert("description".into(), json!(format!("Start condition for {}", memory_name)));
        let e3 = Edge::new(and_gate_id.clone(), start_signal_id.clone(), None, Some(e3d));
        graph.add_edge(e3);

        log::info!("  Wired {} = {} && {}", start_signal_id, idle_signal_id, or_gate_id);
    }

    // Store access_enable on memory node
    let memory = graph.nodes.get_mut(memory_name).unwrap();
    memory.data.insert("access_enable_signal".into(), json!(&or_gate_id));

    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_set_memory_variable_latency() {
        let mut graph = ResourceGraph::new();
        let mut data: HashMap<String, Value> = HashMap::new();
        data.insert("type".into(), json!("memory"));
        data.insert("is_memory".into(), json!(true));
        let mem = Node::new(
            Some("umem".into()), Some(data),
            false, false, None, false, None, None, false, false, 0, false, true, None, None,
        );
        graph.add_node(mem);

        let result = set_memory_variable_latency(&mut graph, "umem", true, 1, 1);
        assert!(result);
        assert!(graph.nodes["umem"].variable_latency);
        assert!(graph.nodes.contains_key("umem_start"));
        assert!(graph.nodes.contains_key("umem_idle"));
        assert!(graph.nodes.contains_key("umem_complete"));

        // Disable
        let result = set_memory_variable_latency(&mut graph, "umem", false, 1, 1);
        assert!(result);
        assert!(!graph.nodes["umem"].variable_latency);
        assert!(!graph.nodes.contains_key("umem_start"));
    }

    #[test]
    fn test_set_memory_variable_latency_not_found() {
        let mut graph = ResourceGraph::new();
        let result = set_memory_variable_latency(&mut graph, "missing", true, 1, 1);
        assert!(!result);
    }
}
