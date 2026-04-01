//! Resource Sharing Optimization for ResourceGraph.
//!
//! This module implements algorithms to identify and share expensive resources
//! (like adders) across multiple uses by time-multiplexing them, while
//! maintaining ISA-level correctness.

use std::collections::HashMap;

use log::{debug, info, warn};
use serde_json::{json, Value};

use crate::operation_serialization::ISAStateGatingHelper;
use crate::resource_graph::{Edge, Node, ResourceGraph};

// ---------------------------------------------------------------------------
// ResourceSharingTransform
// ---------------------------------------------------------------------------

/// Implements resource sharing transformations on ResourceGraphs.
///
/// Key concepts:
/// 1. Identify multiple uses of the same resource type (e.g., multiple '+' operations)
/// 2. Insert uarch_state registers to create timing cuts
/// 3. Add uarch counter to sequence resource usage
/// 4. Gate ISA state updates to only occur when operations complete
pub struct ResourceSharingTransform<'a> {
    pub graph: &'a mut ResourceGraph,
    /// Maps resource_key -> vec of node IDs that share that resource.
    pub shared_resources: HashMap<String, Vec<String>>,
    /// Node ID of the uarch counter, if created.
    pub uarch_counter_id: Option<String>,
}

impl<'a> ResourceSharingTransform<'a> {
    /// Create a new ResourceSharingTransform.
    pub fn new(graph: &'a mut ResourceGraph) -> Self {
        Self {
            graph,
            shared_resources: HashMap::new(),
            uarch_counter_id: None,
        }
    }

    /// Identify nodes that can share the same resource.
    ///
    /// `resource_type`: type of resource to look for (e.g., `"operation"`).
    /// `resource_filter`: optional operator filter (e.g., `"+"`).
    ///
    /// Returns a map from resource key to the node IDs that could share it.
    /// Only resources with 2+ users are returned.
    pub fn identify_shareable_resources(
        &mut self,
        resource_type: &str,
        resource_filter: Option<&str>,
    ) -> HashMap<String, Vec<String>> {
        let mut resources: HashMap<String, Vec<String>> = HashMap::new();

        for (node_id, node) in &self.graph.nodes {
            let node_type = node.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
            if node_type != resource_type {
                continue;
            }

            if resource_type == "operation" {
                let operator = node
                    .data
                    .get("operator")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                if resource_filter.is_none() || resource_filter == Some(operator) {
                    let resource_key = format!("{}_{}", resource_type, operator);
                    resources
                        .entry(resource_key)
                        .or_default()
                        .push(node_id.clone());
                }
            } else {
                resources
                    .entry(resource_type.to_string())
                    .or_default()
                    .push(node_id.clone());
            }
        }

        // Only keep resources with multiple users, sorted for deterministic ordering.
        let shareable: HashMap<String, Vec<String>> = resources
            .into_iter()
            .filter(|(_, v)| v.len() > 1)
            .map(|(k, mut v)| {
                v.sort();
                (k, v)
            })
            .collect();

        self.shared_resources = shareable.clone();
        shareable
    }

    /// Apply resource sharing transformation for a specific resource key.
    ///
    /// Returns `true` if the transformation was successful.
    pub fn apply_resource_sharing(&mut self, resource_key: &str) -> bool {
        let resource_ids = match self.shared_resources.get(resource_key) {
            Some(ids) if ids.len() >= 2 => ids.clone(),
            _ => return false,
        };

        let num_sharers = resource_ids.len();
        info!("Sharing {} across {} instances", resource_key, num_sharers);

        // Step 1: Create uarch counter.
        self._create_uarch_counter(num_sharers);

        // Step 2: Insert timing cuts before each resource usage.
        for (i, resource_id) in resource_ids.iter().enumerate() {
            self._insert_timing_cut_before(resource_id, i);
        }

        // Step 3: Insert timing cuts after each resource usage (except the last).
        for (i, resource_id) in resource_ids.iter().enumerate() {
            if i < resource_ids.len() - 1 {
                self._insert_timing_cut_after(resource_id, i);
            }
        }

        // Step 4: Add control edges from counter to shared operations.
        self._add_counter_control_edges(&resource_ids);

        // Step 5: Gate ISA state updates.
        self._gate_isa_state_updates(num_sharers);

        // Step 6: Re-infer timing.
        self.graph.infer_uarch_time(true);

        // Step 7: Set proper timing for shared resources.
        self._set_shared_resource_timing(&resource_ids, num_sharers);

        true
    }

    /// Create a uarch counter that counts from 0 to `max_count - 1`.
    pub fn _create_uarch_counter(&mut self, max_count: usize) {
        let counter_width = if max_count <= 1 {
            1
        } else {
            ((max_count - 1) as f64).log2().ceil() as i64 + 1
        };

        let counter_id = "uarch_cycle_counter".to_string();

        let mut counter_data: HashMap<String, Value> = HashMap::new();
        counter_data.insert("type".to_string(), json!("uarch_counter"));
        counter_data.insert("name".to_string(), json!("uarch_cycle_counter"));
        counter_data.insert("display_name".to_string(), json!("uarch_cycle_counter"));
        counter_data.insert("bit_width".to_string(), json!(counter_width));
        counter_data.insert("max_value".to_string(), json!(max_count as i64 - 1));

        let mut counter_node = Node::with_defaults(Some(counter_id.clone()));
        counter_node.data = counter_data;
        counter_node.is_uarch_state = true;
        self.graph.add_node(counter_node);

        // Create counter increment logic.
        let incr_id = "counter_increment".to_string();
        let mut incr_data: HashMap<String, Value> = HashMap::new();
        incr_data.insert("type".to_string(), json!("operation"));
        incr_data.insert("operator".to_string(), json!("+"));
        incr_data.insert("display_name".to_string(), json!("Counter Increment"));
        incr_data.insert("bit_width".to_string(), json!(counter_width));

        let mut incr_node = Node::with_defaults(Some(incr_id.clone()));
        incr_node.data = incr_data;
        self.graph.add_node(incr_node);

        // Create literal "1" for increment.
        let one_id = "counter_one".to_string();
        let mut one_data: HashMap<String, Value> = HashMap::new();
        one_data.insert("type".to_string(), json!("literal"));
        one_data.insert("value".to_string(), json!(1));
        one_data.insert("display_name".to_string(), json!("1"));
        one_data.insert("bit_width".to_string(), json!(counter_width));

        let mut one_node = Node::with_defaults(Some(one_id.clone()));
        one_node.data = one_data;
        self.graph.add_node(one_node);

        // Counter -> increment operation.
        let mut e1_data: HashMap<String, Value> = HashMap::new();
        e1_data.insert("type".to_string(), json!("operand"));
        let e1 = Edge::new(counter_id.clone(), incr_id.clone(), None, Some(e1_data));
        self.graph.add_edge(e1);

        // Literal 1 -> increment operation.
        let mut e2_data: HashMap<String, Value> = HashMap::new();
        e2_data.insert("type".to_string(), json!("operand"));
        let e2 = Edge::new(one_id, incr_id.clone(), None, Some(e2_data));
        self.graph.add_edge(e2);

        // Increment result -> counter (feedback).
        let mut e3_data: HashMap<String, Value> = HashMap::new();
        e3_data.insert("type".to_string(), json!("assignment"));
        let e3 = Edge::new(incr_id, counter_id.clone(), None, Some(e3_data));
        self.graph.add_edge(e3);

        info!(
            "Created uarch counter: {} (0 to {})",
            counter_id,
            max_count - 1
        );

        self.uarch_counter_id = Some(counter_id);
    }

    /// Insert uarch_state registers before a resource node to create timing
    /// separation.
    pub fn _insert_timing_cut_before(&mut self, resource_id: &str, time_slot: usize) {
        // Collect incoming edges.
        let incoming_eids: Vec<String> = self
            .graph
            .nodes
            .get(resource_id)
            .map(|n| n.incoming_edges.iter().cloned().collect())
            .unwrap_or_default();

        for eid in &incoming_eids {
            let (source_id, edge_data_clone) = match self.graph.edges.get(eid) {
                Some(e) => (e.source.clone(), e.data.clone()),
                None => continue,
            };

            // Get width of source node.
            let source_width = self._get_node_width(&source_id);

            let reg_name = format!("{}_t{}_reg", source_id, time_slot);

            let mut reg_data: HashMap<String, Value> = HashMap::new();
            reg_data.insert("type".to_string(), json!("uarch_state"));
            reg_data.insert("name".to_string(), json!(&reg_name));
            reg_data.insert("display_name".to_string(), json!(&reg_name));
            reg_data.insert("bit_width".to_string(), json!(source_width));
            reg_data.insert("time_slot".to_string(), json!(time_slot as i64));

            let mut reg_node = Node::with_defaults(Some(reg_name.clone()));
            reg_node.data = reg_data;
            reg_node.is_uarch_state = true;
            self.graph.add_node(reg_node);

            // Remove original edge.
            self.graph.remove_edge(eid);

            // source -> pipeline_reg
            let mut e1_data: HashMap<String, Value> = HashMap::new();
            e1_data.insert("type".to_string(), json!("pipeline_stage"));
            let e1 = Edge::new(source_id.clone(), reg_name.clone(), None, Some(e1_data));
            self.graph.add_edge(e1);

            // pipeline_reg -> resource
            let e2 = Edge::new(
                reg_name.clone(),
                resource_id.to_string(),
                None,
                Some(edge_data_clone),
            );
            self.graph.add_edge(e2);

            info!(
                "  Inserted pipeline register {} before {}",
                reg_name, resource_id
            );
        }
    }

    /// Insert uarch_state registers after a resource node to hold results.
    pub fn _insert_timing_cut_after(&mut self, resource_id: &str, time_slot: usize) {
        // Collect outgoing edges.
        let outgoing_eids: Vec<String> = self
            .graph
            .nodes
            .get(resource_id)
            .map(|n| n.outgoing_edges.iter().cloned().collect())
            .unwrap_or_default();

        for eid in &outgoing_eids {
            let (target_id, edge_data_clone) = match self.graph.edges.get(eid) {
                Some(e) => (e.target.clone(), e.data.clone()),
                None => continue,
            };

            let resource_width = self._get_node_width(resource_id);
            let reg_name = format!("{}_result_t{}_reg", resource_id, time_slot);

            let mut reg_data: HashMap<String, Value> = HashMap::new();
            reg_data.insert("type".to_string(), json!("uarch_state"));
            reg_data.insert("name".to_string(), json!(&reg_name));
            reg_data.insert("display_name".to_string(), json!(&reg_name));
            reg_data.insert("bit_width".to_string(), json!(resource_width));
            reg_data.insert("time_slot".to_string(), json!(time_slot as i64));

            let mut reg_node = Node::with_defaults(Some(reg_name.clone()));
            reg_node.data = reg_data;
            reg_node.is_uarch_state = true;
            self.graph.add_node(reg_node);

            // Remove original edge.
            self.graph.remove_edge(eid);

            // resource -> result_reg
            let mut e1_data: HashMap<String, Value> = HashMap::new();
            e1_data.insert("type".to_string(), json!("result_capture"));
            let e1 = Edge::new(
                resource_id.to_string(),
                reg_name.clone(),
                None,
                Some(e1_data),
            );
            self.graph.add_edge(e1);

            // result_reg -> target
            let e2 = Edge::new(reg_name.clone(), target_id, None, Some(edge_data_clone));
            self.graph.add_edge(e2);

            info!(
                "  Inserted result register {} after {}",
                reg_name, resource_id
            );
        }
    }

    /// Add control edges from counter to shared operations.
    pub fn _add_counter_control_edges(&mut self, resource_ids: &[String]) {
        let counter_id = match &self.uarch_counter_id {
            Some(id) => id.clone(),
            None => return,
        };

        for (i, resource_id) in resource_ids.iter().enumerate() {
            // Mark the resource as part of shared operation.
            if let Some(node) = self.graph.nodes.get_mut(resource_id) {
                node.data
                    .insert("shared_resource".to_string(), json!(true));
                node.data
                    .insert("time_slot".to_string(), json!(i as i64));
                let old_display = node
                    .data
                    .get("display_name")
                    .and_then(|v| v.as_str())
                    .unwrap_or(resource_id)
                    .to_string();
                node.data.insert(
                    "display_name".to_string(),
                    json!(format!("Shared {} [slot {}]", old_display, i)),
                );
            }

            // Add control edge from counter to operation.
            let mut ctrl_data: HashMap<String, Value> = HashMap::new();
            ctrl_data.insert("type".to_string(), json!("resource_control"));
            ctrl_data.insert("time_slot".to_string(), json!(i as i64));
            ctrl_data.insert(
                "condition".to_string(),
                json!(format!("counter == {}", i)),
            );
            let ctrl_edge = Edge::new(
                counter_id.clone(),
                resource_id.clone(),
                None,
                Some(ctrl_data),
            );
            self.graph.add_edge(ctrl_edge);
        }
    }

    /// Gate ISA state updates to only occur when the uarch counter reaches
    /// its max value.
    pub fn _gate_isa_state_updates(&mut self, num_sharers: usize) {
        let counter_id = match &self.uarch_counter_id {
            Some(id) => id.clone(),
            None => return,
        };

        let final_cycle = (num_sharers as i64) - 1;

        let mut helper = ISAStateGatingHelper::new(self.graph);
        let enable_node_id = helper.gate_all_isa_writes_for_operation(
            "resource_sharing",
            &counter_id,
            final_cycle,
            "resource_sharing_enable",
        );

        info!("  Created enable condition: {}", enable_node_id);
    }

    /// Set appropriate timing for shared resources and related nodes.
    pub fn _set_shared_resource_timing(&mut self, resource_ids: &[String], _num_sharers: usize) {
        // Set counter timing to 0.
        if let Some(counter_id) = &self.uarch_counter_id {
            if let Some(node) = self.graph.nodes.get_mut(counter_id) {
                node.uarch_time = Some(0);
            }
        }

        // Set timing for shared operations based on their time slots.
        for (i, resource_id) in resource_ids.iter().enumerate() {
            if let Some(node) = self.graph.nodes.get_mut(resource_id) {
                node.uarch_time = Some(i as i64);
                info!("  Set {} timing to {} (time slot)", resource_id, i);
            }
        }

        // Set timing for pipeline registers based on their function.
        let node_ids: Vec<String> = self.graph.nodes.keys().cloned().collect();
        for node_id in &node_ids {
            let node_type = self
                .graph
                .nodes
                .get(node_id)
                .and_then(|n| n.data.get("type"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();

            if node_type == "uarch_state" && node_id.contains("_t") {
                // Try to extract the time slot from the node name.
                if let Some(time_slot) = Self::extract_time_slot_from_name(node_id) {
                    if node_id.contains("result_t") && node_id.contains("_reg") {
                        // Result registers: time = slot + 1 (after operation).
                        if let Some(node) = self.graph.nodes.get_mut(node_id) {
                            node.uarch_time = Some(time_slot + 1);
                            info!(
                                "  Set {} timing to {} (result register)",
                                node_id,
                                time_slot + 1
                            );
                        }
                    } else if node_id.contains("_reg") && !node_id.contains("result") {
                        // Input registers: time = slot number.
                        if let Some(node) = self.graph.nodes.get_mut(node_id) {
                            node.uarch_time = Some(time_slot);
                            info!(
                                "  Set {} timing to {} (input register)",
                                node_id, time_slot
                            );
                        }
                    }
                }
            }
        }

        // Counter increment logic at time 0 (always running).
        for node_id in &node_ids {
            let is_counter_incr = self
                .graph
                .nodes
                .get(node_id)
                .map(|n| {
                    n.data.get("type").and_then(|v| v.as_str()) == Some("operation")
                        && n.data.get("display_name").and_then(|v| v.as_str())
                            == Some("Counter Increment")
                })
                .unwrap_or(false);

            let is_counter_one = node_id == "counter_one"
                && self
                    .graph
                    .nodes
                    .get(node_id)
                    .map(|n| n.data.get("type").and_then(|v| v.as_str()) == Some("literal"))
                    .unwrap_or(false);

            if is_counter_incr || is_counter_one {
                if let Some(node) = self.graph.nodes.get_mut(node_id) {
                    node.uarch_time = Some(0);
                }
            }
        }

        // Set ISA state updates based on max incoming assignment time.
        // We need multiple passes to propagate correctly.
        for _pass in 0..3 {
            self._propagate_isa_state_timing(&node_ids);
        }

        // Special handling for aggregate variables with outgoing bit_access edges.
        self._propagate_aggregate_timing(&node_ids);

        // Final pass: update nodes depending on aggregates.
        self._final_timing_pass(&node_ids);

        // Calculate final time for summary.
        let final_time = self.graph.get_max_uarch_time();
        info!("  Resource sharing sequence: 0 to {} cycles", final_time);
    }

    /// Propagate timing from assignment sources to ISA state write targets.
    fn _propagate_isa_state_timing(&mut self, node_ids: &[String]) {
        for node_id in node_ids {
            let mut max_incoming_time: Option<i64> = None;
            let mut _source_id: Option<String> = None;

            // Collect incoming edge info without borrowing graph mutably.
            let incoming_eids: Vec<String> = self
                .graph
                .nodes
                .get(node_id)
                .map(|n| n.incoming_edges.iter().cloned().collect())
                .unwrap_or_default();

            for eid in &incoming_eids {
                let edge = match self.graph.edges.get(eid) {
                    Some(e) => e,
                    None => continue,
                };
                if edge.data.get("type").and_then(|v| v.as_str()) != Some("assignment") {
                    continue;
                }

                let src_id = edge.source.clone();

                // Check if the source is a result register.
                if src_id.contains("result") && src_id.contains("reg") {
                    // Trace back to the operation feeding the result register.
                    let result_reg_incoming: Vec<String> = self
                        .graph
                        .nodes
                        .get(&src_id)
                        .map(|n| n.incoming_edges.iter().cloned().collect())
                        .unwrap_or_default();

                    let mut found_op = false;
                    for r_eid in &result_reg_incoming {
                        if let Some(r_edge) = self.graph.edges.get(r_eid) {
                            let op_src = &r_edge.source;
                            let is_operation = self
                                .graph
                                .nodes
                                .get(op_src)
                                .map(|n| {
                                    n.data.get("type").and_then(|v| v.as_str())
                                        == Some("operation")
                                })
                                .unwrap_or(false);
                            if is_operation {
                                let op_time = self
                                    .graph
                                    .nodes
                                    .get(op_src)
                                    .and_then(|n| n.uarch_time);
                                if let Some(t) = op_time {
                                    if max_incoming_time.map_or(true, |m| t > m) {
                                        max_incoming_time = Some(t);
                                        _source_id = Some(op_src.clone());
                                    }
                                }
                                found_op = true;
                                break;
                            }
                        }
                    }

                    if !found_op {
                        // Fallback to result register time.
                        warn!(
                            "  WARNING: Could not find operation for result register {}",
                            src_id
                        );
                        let reg_time = self
                            .graph
                            .nodes
                            .get(&src_id)
                            .and_then(|n| n.uarch_time);
                        if let Some(t) = reg_time {
                            if max_incoming_time.map_or(true, |m| t > m) {
                                max_incoming_time = Some(t);
                                _source_id = Some(src_id.clone());
                            }
                        }
                    }
                } else {
                    // Check if source has timing.
                    let src_time = self
                        .graph
                        .nodes
                        .get(&src_id)
                        .and_then(|n| n.uarch_time);
                    if let Some(t) = src_time {
                        if max_incoming_time.map_or(true, |m| t > m) {
                            max_incoming_time = Some(t);
                            _source_id = Some(src_id.clone());
                        }
                    }
                }
            }

            // Apply the max incoming time.
            if let Some(t) = max_incoming_time {
                if let Some(node) = self.graph.nodes.get_mut(node_id) {
                    let current = node.uarch_time;
                    if current.is_none() || current.unwrap() < t {
                        node.uarch_time = Some(t);
                        debug!("  Set {} timing to {} (ISA state update)", node_id, t);
                    }
                }
            }
        }
    }

    /// Handle aggregate variables that have outgoing bit_access edges.
    fn _propagate_aggregate_timing(&mut self, node_ids: &[String]) {
        for node_id in node_ids {
            let current_time = self
                .graph
                .nodes
                .get(node_id)
                .and_then(|n| n.uarch_time);

            if current_time.is_some() && current_time != Some(0) {
                continue;
            }

            // Collect bit_access targets and their times.
            let outgoing_eids: Vec<String> = self
                .graph
                .nodes
                .get(node_id)
                .map(|n| n.outgoing_edges.iter().cloned().collect())
                .unwrap_or_default();

            let mut max_slice_time: Option<i64> = None;
            let mut has_bit_access = false;

            for eid in &outgoing_eids {
                if let Some(edge) = self.graph.edges.get(eid) {
                    if edge.data.get("type").and_then(|v| v.as_str()) == Some("bit_access") {
                        has_bit_access = true;
                        if let Some(target_time) = self
                            .graph
                            .nodes
                            .get(&edge.target)
                            .and_then(|n| n.uarch_time)
                        {
                            if max_slice_time.map_or(true, |m| target_time > m) {
                                max_slice_time = Some(target_time);
                            }
                        }
                    }
                }
            }

            if has_bit_access {
                if let Some(t) = max_slice_time {
                    if t > 0 {
                        if let Some(node) = self.graph.nodes.get_mut(node_id) {
                            node.uarch_time = Some(t);
                            info!(
                                "  Set {} timing to {} (aggregate of bit slices)",
                                node_id, t
                            );
                        }
                    }
                }
            }
        }
    }

    /// Final timing pass: update unset nodes and nodes depending on aggregates.
    fn _final_timing_pass(&mut self, node_ids: &[String]) {
        // Update nodes with None timing from their assignment sources.
        for node_id in node_ids {
            let current_time = self
                .graph
                .nodes
                .get(node_id)
                .and_then(|n| n.uarch_time);

            if current_time.is_some() {
                continue; // Only handle truly unset nodes.
            }

            let incoming_eids: Vec<String> = self
                .graph
                .nodes
                .get(node_id)
                .map(|n| n.incoming_edges.iter().cloned().collect())
                .unwrap_or_default();

            for eid in &incoming_eids {
                if let Some(edge) = self.graph.edges.get(eid) {
                    if edge.data.get("type").and_then(|v| v.as_str()) == Some("assignment") {
                        if let Some(src_time) = self
                            .graph
                            .nodes
                            .get(&edge.source)
                            .and_then(|n| n.uarch_time)
                        {
                            if let Some(node) = self.graph.nodes.get_mut(node_id) {
                                node.uarch_time = Some(src_time);
                                info!(
                                    "  Set {} timing to {} (updated from {})",
                                    node_id, src_time, edge.source
                                );
                            }
                            break;
                        }
                    }
                }
            }
        }

        // Update nodes at time 0 that depend on aggregates now having proper timing.
        for node_id in node_ids {
            let current_time = self
                .graph
                .nodes
                .get(node_id)
                .and_then(|n| n.uarch_time);

            if current_time != Some(0) {
                continue;
            }

            let incoming_eids: Vec<String> = self
                .graph
                .nodes
                .get(node_id)
                .map(|n| n.incoming_edges.iter().cloned().collect())
                .unwrap_or_default();

            for eid in &incoming_eids {
                if let Some(edge) = self.graph.edges.get(eid) {
                    if edge.data.get("type").and_then(|v| v.as_str()) != Some("assignment") {
                        continue;
                    }
                    let src_id = edge.source.clone();
                    let src_time = self
                        .graph
                        .nodes
                        .get(&src_id)
                        .and_then(|n| n.uarch_time);
                    if let Some(t) = src_time {
                        if t <= 0 {
                            continue;
                        }
                        // Check if source is an aggregate (has bit_access edges).
                        let is_aggregate = self
                            .graph
                            .nodes
                            .get(&src_id)
                            .map(|n| {
                                n.outgoing_edges.iter().any(|oeid| {
                                    self.graph
                                        .edges
                                        .get(oeid)
                                        .map(|e| {
                                            e.data.get("type").and_then(|v| v.as_str())
                                                == Some("bit_access")
                                        })
                                        .unwrap_or(false)
                                })
                            })
                            .unwrap_or(false);
                        if is_aggregate {
                            if let Some(node) = self.graph.nodes.get_mut(node_id) {
                                node.uarch_time = Some(t);
                                info!(
                                    "  Set {} timing to {} (updated from aggregate {})",
                                    node_id, t, src_id
                                );
                            }
                            break;
                        }
                    }
                }
            }
        }
    }

    /// Extract time slot number from a node name like `"foo_t2_reg"` -> `Some(2)`.
    fn extract_time_slot_from_name(name: &str) -> Option<i64> {
        // Find `_t<digits>` in the name.
        let mut parts = name.split("_t");
        parts.next(); // skip prefix
        for part in parts {
            // Take leading digits.
            let digits: String = part.chars().take_while(|c| c.is_ascii_digit()).collect();
            if !digits.is_empty() {
                if let Ok(val) = digits.parse::<i64>() {
                    return Some(val);
                }
            }
        }
        None
    }

    /// Get the bit width of a node, with fallback to 32.
    pub fn _get_node_width(&self, node_id: &str) -> i64 {
        if let Some(node) = self.graph.nodes.get(node_id) {
            // Check bit_width.
            if let Some(w) = node.data.get("bit_width").and_then(|v| v.as_i64()) {
                return w;
            }
            // Check width.
            if let Some(w) = node.data.get("width").and_then(|v| v.as_i64()) {
                return w;
            }
            // For bit_slice nodes, calculate from range.
            if node.data.get("type").and_then(|v| v.as_str()) == Some("bit_slice") {
                if let Some(expr) = node.data.get("expression") {
                    if let Some(range) = expr.get("range").and_then(|v| v.as_array()) {
                        if range.len() == 2 {
                            let high = range[0].as_i64().unwrap_or(31);
                            let low = range[1].as_i64().unwrap_or(0);
                            return high - low + 1;
                        }
                    }
                }
            }
            // For arrays/isa_state, check dimensions.
            if let Some(dims) = node.data.get("dimensions").and_then(|v| v.as_array()) {
                if !dims.is_empty() {
                    if let Some(first) = dims[0].as_array() {
                        if first.len() == 2 {
                            let high = first[0].as_i64().unwrap_or(31);
                            let low = first[1].as_i64().unwrap_or(0);
                            return high - low + 1;
                        }
                    }
                }
            }
        }
        32 // Default
    }

    /// Generate a summary of the resource sharing transformation.
    pub fn get_transformation_summary(&self) -> String {
        let mut summary = String::new();
        summary.push_str("Resource Sharing Transformation Summary:\n");
        summary.push_str(&"=".repeat(50));
        summary.push_str("\n\n");

        if self.shared_resources.is_empty() {
            summary.push_str("No shareable resources identified.\n");
            return summary;
        }

        for (resource_key, node_ids) in &self.shared_resources {
            summary.push_str(&format!("Resource: {}\n", resource_key));
            summary.push_str(&format!(
                "  Shared across {} instances:\n",
                node_ids.len()
            ));
            for nid in node_ids {
                summary.push_str(&format!("    - {}\n", nid));
            }
            summary.push('\n');
        }

        if let Some(counter_id) = &self.uarch_counter_id {
            let max_val = self
                .graph
                .nodes
                .get(counter_id)
                .and_then(|n| n.data.get("max_value"))
                .and_then(|v| v.as_i64())
                .unwrap_or(0);
            summary.push_str(&format!(
                "Uarch Counter: {} (0 to {})\n",
                counter_id, max_val
            ));
            summary.push_str(&format!(
                "ISA updates gated to occur only when counter = {}\n\n",
                max_val
            ));
        }

        // Show timing after transformation.
        let max_time = self.graph.get_max_uarch_time();
        summary.push_str(&format!(
            "Pipeline depth after sharing: {} cycles\n",
            max_time
        ));

        for time in 0..=max_time {
            let nodes_at_time = self.graph.get_nodes_at_time(time);
            summary.push_str(&format!(
                "  Time {}: {} nodes\n",
                time,
                nodes_at_time.len()
            ));
        }

        summary
    }
}

// ---------------------------------------------------------------------------
// Standalone functions
// ---------------------------------------------------------------------------

/// Convenience function to apply resource sharing to addition operations.
pub fn apply_adder_sharing(graph: &mut ResourceGraph) -> bool {
    let mut transform = ResourceSharingTransform::new(graph);

    let resources = transform.identify_shareable_resources("operation", Some("+"));

    if !resources.contains_key("operation_+") {
        info!("No addition operations found to share");
        return false;
    }

    let count = resources["operation_+"].len();
    info!("Found {} addition operations to share:", count);
    for nid in &resources["operation_+"] {
        info!("  - {}", nid);
    }

    let success = transform.apply_resource_sharing("operation_+");

    if success {
        info!("Transformation Summary:");
        info!("{}", transform.get_transformation_summary());
    }

    success
}

/// General function to apply resource sharing to any resource type.
pub fn apply_resource_sharing_to_graph(
    graph: &mut ResourceGraph,
    resource_type: &str,
    resource_filter: Option<&str>,
) -> bool {
    let mut transform = ResourceSharingTransform::new(graph);

    let resources = transform.identify_shareable_resources(resource_type, resource_filter);

    if resources.is_empty() {
        info!("No {} resources found to share", resource_type);
        return false;
    }

    // Apply sharing to the first resource type found.
    let resource_key = resources.keys().next().unwrap().clone();
    info!("Applying resource sharing to {}", resource_key);

    let success = transform.apply_resource_sharing(&resource_key);

    if success {
        info!("Transformation Summary:");
        info!("{}", transform.get_transformation_summary());
    }

    success
}

/// Apply resource sharing to a specific set of user-selected nodes.
pub fn apply_resource_sharing_to_selected_nodes(
    graph: &mut ResourceGraph,
    selected_node_ids: &[String],
) -> bool {
    if selected_node_ids.len() < 2 {
        info!(
            "Need at least 2 nodes selected for resource sharing (got {})",
            selected_node_ids.len()
        );
        return false;
    }

    // Validate that all selected nodes exist and are of the same type.
    let mut node_type: Option<String> = None;
    let mut operator: Option<String> = None;

    for node_id in selected_node_ids {
        let node = match graph.nodes.get(node_id) {
            Some(n) => n,
            None => {
                info!("Node {} not found in graph", node_id);
                return false;
            }
        };

        let current_type = node
            .data
            .get("type")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        match &node_type {
            None => {
                node_type = Some(current_type.clone());
                if current_type == "operation" {
                    operator = node
                        .data
                        .get("operator")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string());
                }
            }
            Some(nt) => {
                if current_type != *nt {
                    info!(
                        "Selected nodes must be of the same type (got {} and {})",
                        nt, current_type
                    );
                    return false;
                }
                if current_type == "operation" {
                    let current_op = node
                        .data
                        .get("operator")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string());
                    if current_op != operator {
                        info!(
                            "Selected operations must have the same operator (got {:?} and {:?})",
                            operator, current_op
                        );
                        return false;
                    }
                }
            }
        }
    }

    let nt = node_type.unwrap_or_default();
    let op_str = operator
        .as_deref()
        .map(|o| format!(" (operator: {})", o))
        .unwrap_or_default();
    info!(
        "Sharing {} selected {} nodes{}",
        selected_node_ids.len(),
        nt,
        op_str
    );

    let mut transform = ResourceSharingTransform::new(graph);

    // Set up shared resources with just the selected nodes.
    let resource_key = if let Some(ref op) = operator {
        format!("{}_{}", nt, op)
    } else {
        nt.clone()
    };
    transform
        .shared_resources
        .insert(resource_key.clone(), selected_node_ids.to_vec());

    let success = transform.apply_resource_sharing(&resource_key);

    if success {
        info!("Transformation Summary:");
        info!("{}", transform.get_transformation_summary());
    }

    success
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// Build a graph with two '+' operations, each with two operands and one
    /// destination, connected by operand/assignment edges.
    ///
    /// Layout:
    ///   src_a --operand--> add1 --assignment--> dest1
    ///   src_b --operand--/
    ///
    ///   src_c --operand--> add2 --assignment--> dest2
    ///   src_d --operand--/
    fn make_resource_sharing_graph() -> ResourceGraph {
        let mut graph = ResourceGraph::new();

        // --- add1 operands ---
        let mut src_a = Node::with_defaults(Some("src_a".to_string()));
        src_a.data.insert("type".to_string(), json!("var"));
        src_a.data.insert("name".to_string(), json!("src_a"));
        src_a.data.insert("bit_width".to_string(), json!(32));
        src_a.is_arch_state = true;
        graph.add_node(src_a);

        let mut src_b = Node::with_defaults(Some("src_b".to_string()));
        src_b.data.insert("type".to_string(), json!("var"));
        src_b.data.insert("name".to_string(), json!("src_b"));
        src_b.data.insert("bit_width".to_string(), json!(32));
        src_b.is_arch_state = true;
        graph.add_node(src_b);

        // --- add1 ---
        let mut add1 = Node::with_defaults(Some("add1".to_string()));
        add1.data.insert("type".to_string(), json!("operation"));
        add1.data.insert("operator".to_string(), json!("+"));
        add1.data.insert("display_name".to_string(), json!("add1"));
        add1.data.insert("bit_width".to_string(), json!(32));
        graph.add_node(add1);

        // --- add1 destination ---
        let mut dest1 = Node::with_defaults(Some("dest1".to_string()));
        dest1.data.insert("type".to_string(), json!("var"));
        dest1.data.insert("name".to_string(), json!("dest1"));
        dest1.data.insert("bit_width".to_string(), json!(32));
        dest1.is_arch_state = true;
        graph.add_node(dest1);

        // --- add2 operands ---
        let mut src_c = Node::with_defaults(Some("src_c".to_string()));
        src_c.data.insert("type".to_string(), json!("var"));
        src_c.data.insert("name".to_string(), json!("src_c"));
        src_c.data.insert("bit_width".to_string(), json!(32));
        src_c.is_arch_state = true;
        graph.add_node(src_c);

        let mut src_d = Node::with_defaults(Some("src_d".to_string()));
        src_d.data.insert("type".to_string(), json!("var"));
        src_d.data.insert("name".to_string(), json!("src_d"));
        src_d.data.insert("bit_width".to_string(), json!(32));
        src_d.is_arch_state = true;
        graph.add_node(src_d);

        // --- add2 ---
        let mut add2 = Node::with_defaults(Some("add2".to_string()));
        add2.data.insert("type".to_string(), json!("operation"));
        add2.data.insert("operator".to_string(), json!("+"));
        add2.data.insert("display_name".to_string(), json!("add2"));
        add2.data.insert("bit_width".to_string(), json!(32));
        graph.add_node(add2);

        // --- add2 destination ---
        let mut dest2 = Node::with_defaults(Some("dest2".to_string()));
        dest2.data.insert("type".to_string(), json!("var"));
        dest2.data.insert("name".to_string(), json!("dest2"));
        dest2.data.insert("bit_width".to_string(), json!(32));
        dest2.is_arch_state = true;
        graph.add_node(dest2);

        // --- Edges: operands into add1 ---
        let mut e1_data: HashMap<String, Value> = HashMap::new();
        e1_data.insert("type".to_string(), json!("operand"));
        graph.add_edge(Edge::new(
            "src_a".to_string(),
            "add1".to_string(),
            Some("e_src_a_add1".to_string()),
            Some(e1_data),
        ));

        let mut e2_data: HashMap<String, Value> = HashMap::new();
        e2_data.insert("type".to_string(), json!("operand"));
        graph.add_edge(Edge::new(
            "src_b".to_string(),
            "add1".to_string(),
            Some("e_src_b_add1".to_string()),
            Some(e2_data),
        ));

        // --- Edge: add1 -> dest1 ---
        let mut e3_data: HashMap<String, Value> = HashMap::new();
        e3_data.insert("type".to_string(), json!("assignment"));
        graph.add_edge(Edge::new(
            "add1".to_string(),
            "dest1".to_string(),
            Some("e_add1_dest1".to_string()),
            Some(e3_data),
        ));

        // --- Edges: operands into add2 ---
        let mut e4_data: HashMap<String, Value> = HashMap::new();
        e4_data.insert("type".to_string(), json!("operand"));
        graph.add_edge(Edge::new(
            "src_c".to_string(),
            "add2".to_string(),
            Some("e_src_c_add2".to_string()),
            Some(e4_data),
        ));

        let mut e5_data: HashMap<String, Value> = HashMap::new();
        e5_data.insert("type".to_string(), json!("operand"));
        graph.add_edge(Edge::new(
            "src_d".to_string(),
            "add2".to_string(),
            Some("e_src_d_add2".to_string()),
            Some(e5_data),
        ));

        // --- Edge: add2 -> dest2 ---
        let mut e6_data: HashMap<String, Value> = HashMap::new();
        e6_data.insert("type".to_string(), json!("assignment"));
        graph.add_edge(Edge::new(
            "add2".to_string(),
            "dest2".to_string(),
            Some("e_add2_dest2".to_string()),
            Some(e6_data),
        ));

        graph
    }

    // -----------------------------------------------------------------------
    // 1. identify_shareable_resources: no shareable resources
    // -----------------------------------------------------------------------
    #[test]
    fn test_identify_no_shareable() {
        let mut graph = ResourceGraph::new();

        // Single add operation -- not shareable (need >= 2).
        let mut add = Node::with_defaults(Some("only_add".to_string()));
        add.data.insert("type".to_string(), json!("operation"));
        add.data.insert("operator".to_string(), json!("+"));
        graph.add_node(add);

        let mut transform = ResourceSharingTransform::new(&mut graph);
        let result = transform.identify_shareable_resources("operation", Some("+"));
        assert!(
            result.is_empty(),
            "A single operation should not be shareable"
        );
    }

    // -----------------------------------------------------------------------
    // 2. identify_shareable_resources: two adds
    // -----------------------------------------------------------------------
    #[test]
    fn test_identify_two_adds() {
        let mut graph = make_resource_sharing_graph();
        let mut transform = ResourceSharingTransform::new(&mut graph);
        let result = transform.identify_shareable_resources("operation", Some("+"));

        assert!(
            result.contains_key("operation_+"),
            "Should find operation_+ key"
        );
        let ids = &result["operation_+"];
        assert_eq!(ids.len(), 2, "Should find exactly 2 add operations");
        assert!(ids.contains(&"add1".to_string()));
        assert!(ids.contains(&"add2".to_string()));
    }

    // -----------------------------------------------------------------------
    // 3. identify_shareable_resources: filter by operator
    // -----------------------------------------------------------------------
    #[test]
    fn test_identify_with_filter() {
        let mut graph = make_resource_sharing_graph();

        // Add OR operations so the graph has a mix.
        let mut or1 = Node::with_defaults(Some("or1".to_string()));
        or1.data.insert("type".to_string(), json!("operation"));
        or1.data.insert("operator".to_string(), json!("|"));
        graph.add_node(or1);

        let mut or2 = Node::with_defaults(Some("or2".to_string()));
        or2.data.insert("type".to_string(), json!("operation"));
        or2.data.insert("operator".to_string(), json!("|"));
        graph.add_node(or2);

        // Filter by "+" -- should only find the two adds.
        let mut transform = ResourceSharingTransform::new(&mut graph);
        let result = transform.identify_shareable_resources("operation", Some("+"));
        assert!(result.contains_key("operation_+"));
        assert!(!result.contains_key("operation_|"));
        assert_eq!(result["operation_+"].len(), 2);

        // Filter by "|" -- should only find the two ORs.
        let result_or = transform.identify_shareable_resources("operation", Some("|"));
        assert!(result_or.contains_key("operation_|"));
        assert!(!result_or.contains_key("operation_+"));
        assert_eq!(result_or["operation_|"].len(), 2);

        // No filter -- should find both groups.
        let result_all = transform.identify_shareable_resources("operation", None);
        assert!(result_all.contains_key("operation_+"));
        assert!(result_all.contains_key("operation_|"));
    }

    // -----------------------------------------------------------------------
    // 4. _create_uarch_counter
    // -----------------------------------------------------------------------
    #[test]
    fn test_create_uarch_counter() {
        let mut graph = ResourceGraph::new();
        {
            let mut transform = ResourceSharingTransform::new(&mut graph);
            transform._create_uarch_counter(3);

            // Check the transform's recorded counter ID while borrow is active.
            assert_eq!(
                transform.uarch_counter_id.as_deref(),
                Some("uarch_cycle_counter")
            );
        }
        // Transform dropped -- now we can inspect the graph directly.

        // Counter node should exist.
        assert!(
            graph.nodes.contains_key("uarch_cycle_counter"),
            "Counter node must exist"
        );
        let counter = &graph.nodes["uarch_cycle_counter"];
        assert_eq!(
            counter.data.get("type").and_then(|v| v.as_str()),
            Some("uarch_counter")
        );
        assert_eq!(
            counter.data.get("max_value").and_then(|v| v.as_i64()),
            Some(2),
            "max_value should be max_count - 1 = 2"
        );
        assert!(counter.is_uarch_state);

        // Counter increment node should exist.
        assert!(
            graph.nodes.contains_key("counter_increment"),
            "Increment node must exist"
        );
        let incr = &graph.nodes["counter_increment"];
        assert_eq!(
            incr.data.get("type").and_then(|v| v.as_str()),
            Some("operation")
        );
        assert_eq!(
            incr.data.get("operator").and_then(|v| v.as_str()),
            Some("+")
        );

        // Literal "1" node should exist.
        assert!(
            graph.nodes.contains_key("counter_one"),
            "Literal one node must exist"
        );
        let one = &graph.nodes["counter_one"];
        assert_eq!(
            one.data.get("type").and_then(|v| v.as_str()),
            Some("literal")
        );
        assert_eq!(one.data.get("value").and_then(|v| v.as_i64()), Some(1));

        // Feedback edges: counter -> increment, counter_one -> increment,
        // increment -> counter.
        let has_counter_to_incr = graph.edges.values().any(|e| {
            e.source == "uarch_cycle_counter"
                && e.target == "counter_increment"
                && e.data.get("type").and_then(|v| v.as_str()) == Some("operand")
        });
        assert!(has_counter_to_incr, "Edge counter -> increment must exist");

        let has_one_to_incr = graph.edges.values().any(|e| {
            e.source == "counter_one"
                && e.target == "counter_increment"
                && e.data.get("type").and_then(|v| v.as_str()) == Some("operand")
        });
        assert!(has_one_to_incr, "Edge one -> increment must exist");

        let has_incr_to_counter = graph.edges.values().any(|e| {
            e.source == "counter_increment"
                && e.target == "uarch_cycle_counter"
                && e.data.get("type").and_then(|v| v.as_str()) == Some("assignment")
        });
        assert!(
            has_incr_to_counter,
            "Feedback edge increment -> counter must exist"
        );
    }

    // -----------------------------------------------------------------------
    // 5. _insert_timing_cut_before
    // -----------------------------------------------------------------------
    #[test]
    fn test_insert_timing_cut_before() {
        let mut graph = make_resource_sharing_graph();
        {
            let mut transform = ResourceSharingTransform::new(&mut graph);
            transform._insert_timing_cut_before("add1", 0);
        }

        // Pipeline register nodes for the two operand edges into add1.
        assert!(
            graph.nodes.contains_key("src_a_t0_reg"),
            "Pipeline register for src_a -> add1 must exist"
        );
        assert!(
            graph.nodes.contains_key("src_b_t0_reg"),
            "Pipeline register for src_b -> add1 must exist"
        );

        // The registers should be uarch_state.
        let reg_a = &graph.nodes["src_a_t0_reg"];
        assert!(reg_a.is_uarch_state);
        assert_eq!(
            reg_a.data.get("type").and_then(|v| v.as_str()),
            Some("uarch_state")
        );
        assert_eq!(
            reg_a.data.get("time_slot").and_then(|v| v.as_i64()),
            Some(0)
        );

        // Original edges should have been removed.
        assert!(
            !graph.edges.contains_key("e_src_a_add1"),
            "Original edge src_a -> add1 should be removed"
        );
        assert!(
            !graph.edges.contains_key("e_src_b_add1"),
            "Original edge src_b -> add1 should be removed"
        );

        // New edges: source -> reg, reg -> resource.
        let edges_to_reg_a: Vec<_> = graph
            .edges
            .values()
            .filter(|e| e.target == "src_a_t0_reg" && e.source == "src_a")
            .collect();
        assert_eq!(
            edges_to_reg_a.len(),
            1,
            "Should have one edge src_a -> src_a_t0_reg"
        );
        assert_eq!(
            edges_to_reg_a[0]
                .data
                .get("type")
                .and_then(|v| v.as_str()),
            Some("pipeline_stage")
        );

        let edges_reg_a_to_add1: Vec<_> = graph
            .edges
            .values()
            .filter(|e| e.source == "src_a_t0_reg" && e.target == "add1")
            .collect();
        assert_eq!(
            edges_reg_a_to_add1.len(),
            1,
            "Should have one edge src_a_t0_reg -> add1"
        );
        // The edge from reg to resource should carry the original operand type.
        assert_eq!(
            edges_reg_a_to_add1[0]
                .data
                .get("type")
                .and_then(|v| v.as_str()),
            Some("operand")
        );
    }

    // -----------------------------------------------------------------------
    // 6. _insert_timing_cut_after
    // -----------------------------------------------------------------------
    #[test]
    fn test_insert_timing_cut_after() {
        let mut graph = make_resource_sharing_graph();
        {
            let mut transform = ResourceSharingTransform::new(&mut graph);
            transform._insert_timing_cut_after("add1", 0);
        }

        // Result register for the assignment edge out of add1.
        assert!(
            graph.nodes.contains_key("add1_result_t0_reg"),
            "Result register for add1 -> dest1 must exist"
        );

        let reg = &graph.nodes["add1_result_t0_reg"];
        assert!(reg.is_uarch_state);
        assert_eq!(
            reg.data.get("type").and_then(|v| v.as_str()),
            Some("uarch_state")
        );
        assert_eq!(
            reg.data.get("time_slot").and_then(|v| v.as_i64()),
            Some(0)
        );

        // Original edge removed.
        assert!(
            !graph.edges.contains_key("e_add1_dest1"),
            "Original edge add1 -> dest1 should be removed"
        );

        // New edges: resource -> result_reg, result_reg -> target.
        let edges_add1_to_reg: Vec<_> = graph
            .edges
            .values()
            .filter(|e| e.source == "add1" && e.target == "add1_result_t0_reg")
            .collect();
        assert_eq!(
            edges_add1_to_reg.len(),
            1,
            "Should have one edge add1 -> add1_result_t0_reg"
        );
        assert_eq!(
            edges_add1_to_reg[0]
                .data
                .get("type")
                .and_then(|v| v.as_str()),
            Some("result_capture")
        );

        let edges_reg_to_dest: Vec<_> = graph
            .edges
            .values()
            .filter(|e| e.source == "add1_result_t0_reg" && e.target == "dest1")
            .collect();
        assert_eq!(
            edges_reg_to_dest.len(),
            1,
            "Should have one edge add1_result_t0_reg -> dest1"
        );
        assert_eq!(
            edges_reg_to_dest[0]
                .data
                .get("type")
                .and_then(|v| v.as_str()),
            Some("assignment"),
            "Forwarded edge should carry the original assignment type"
        );
    }

    // -----------------------------------------------------------------------
    // 7. _add_counter_control_edges
    // -----------------------------------------------------------------------
    #[test]
    fn test_add_counter_control_edges() {
        let mut graph = make_resource_sharing_graph();
        let resource_ids = vec!["add1".to_string(), "add2".to_string()];
        {
            let mut transform = ResourceSharingTransform::new(&mut graph);
            transform._create_uarch_counter(2);
            transform._add_counter_control_edges(&resource_ids);
        }

        // Each resource should have a resource_control edge from the counter.
        for (i, rid) in resource_ids.iter().enumerate() {
            let ctrl_edges: Vec<_> = graph
                .edges
                .values()
                .filter(|e| {
                    e.source == "uarch_cycle_counter"
                        && e.target == *rid
                        && e.data.get("type").and_then(|v| v.as_str())
                            == Some("resource_control")
                })
                .collect();
            assert_eq!(
                ctrl_edges.len(),
                1,
                "Resource {} should have exactly one control edge from counter",
                rid
            );
            assert_eq!(
                ctrl_edges[0]
                    .data
                    .get("time_slot")
                    .and_then(|v| v.as_i64()),
                Some(i as i64)
            );
        }

        // Each resource node should be marked as shared.
        for (i, rid) in resource_ids.iter().enumerate() {
            let node = &graph.nodes[rid];
            assert_eq!(
                node.data
                    .get("shared_resource")
                    .and_then(|v| v.as_bool()),
                Some(true),
                "{} should have shared_resource = true",
                rid
            );
            assert_eq!(
                node.data.get("time_slot").and_then(|v| v.as_i64()),
                Some(i as i64),
                "{} should have time_slot = {}",
                rid,
                i
            );
        }
    }

    // -----------------------------------------------------------------------
    // 8. apply_resource_sharing: full workflow
    // -----------------------------------------------------------------------
    #[test]
    fn test_apply_resource_sharing_full() {
        let mut graph = make_resource_sharing_graph();
        {
            let mut transform = ResourceSharingTransform::new(&mut graph);

            // Identify shareable resources.
            let resources = transform.identify_shareable_resources("operation", Some("+"));
            assert!(resources.contains_key("operation_+"));

            // Apply sharing.
            let success = transform.apply_resource_sharing("operation_+");
            assert!(success, "apply_resource_sharing should succeed");
        }

        // Counter should exist.
        assert!(graph.nodes.contains_key("uarch_cycle_counter"));
        let counter = &graph.nodes["uarch_cycle_counter"];
        assert_eq!(
            counter.data.get("type").and_then(|v| v.as_str()),
            Some("uarch_counter")
        );

        // Original operation nodes should still exist, but with time_slot data.
        assert!(graph.nodes.contains_key("add1"));
        assert!(graph.nodes.contains_key("add2"));
        assert_eq!(
            graph.nodes["add1"]
                .data
                .get("time_slot")
                .and_then(|v| v.as_i64()),
            Some(0)
        );
        assert_eq!(
            graph.nodes["add2"]
                .data
                .get("time_slot")
                .and_then(|v| v.as_i64()),
            Some(1)
        );

        // Pipeline registers should exist (timing cut before each resource).
        // add1 has 2 operand inputs -> 2 _t0_reg nodes.
        // add2 has 2 operand inputs -> 2 _t1_reg nodes.
        let t0_regs: Vec<_> = graph
            .nodes
            .keys()
            .filter(|k| k.contains("_t0_reg") && !k.contains("result"))
            .collect();
        assert_eq!(
            t0_regs.len(),
            2,
            "Should have 2 input pipeline registers for time_slot 0"
        );

        let t1_regs: Vec<_> = graph
            .nodes
            .keys()
            .filter(|k| k.contains("_t1_reg") && !k.contains("result"))
            .collect();
        assert_eq!(
            t1_regs.len(),
            2,
            "Should have 2 input pipeline registers for time_slot 1"
        );

        // Result register for add1 (timing cut after, only for non-last resource).
        let result_regs: Vec<_> = graph
            .nodes
            .keys()
            .filter(|k| k.contains("result_t0_reg"))
            .collect();
        assert_eq!(
            result_regs.len(),
            1,
            "Should have 1 result register (only add1, not add2)"
        );

        // Resource control edges should exist.
        let ctrl_edges: Vec<_> = graph
            .edges
            .values()
            .filter(|e| {
                e.data.get("type").and_then(|v| v.as_str()) == Some("resource_control")
            })
            .collect();
        assert_eq!(
            ctrl_edges.len(),
            2,
            "Should have 2 resource_control edges (one per shared resource)"
        );
    }

    // -----------------------------------------------------------------------
    // 9. apply_adder_sharing convenience function
    // -----------------------------------------------------------------------
    #[test]
    fn test_apply_adder_sharing_standalone() {
        let mut graph = make_resource_sharing_graph();
        let success = apply_adder_sharing(&mut graph);
        assert!(success, "apply_adder_sharing should succeed on two-add graph");

        // Counter created.
        assert!(graph.nodes.contains_key("uarch_cycle_counter"));

        // Both adds still exist with shared_resource set.
        assert_eq!(
            graph.nodes["add1"]
                .data
                .get("shared_resource")
                .and_then(|v| v.as_bool()),
            Some(true)
        );
        assert_eq!(
            graph.nodes["add2"]
                .data
                .get("shared_resource")
                .and_then(|v| v.as_bool()),
            Some(true)
        );

        // Should fail on a graph with only one add.
        let mut single_graph = ResourceGraph::new();
        let mut add = Node::with_defaults(Some("only_add".to_string()));
        add.data.insert("type".to_string(), json!("operation"));
        add.data.insert("operator".to_string(), json!("+"));
        single_graph.add_node(add);

        let fail = apply_adder_sharing(&mut single_graph);
        assert!(!fail, "apply_adder_sharing should fail with a single add");
    }

    // -----------------------------------------------------------------------
    // 10. apply_resource_sharing_to_selected_nodes
    // -----------------------------------------------------------------------
    #[test]
    fn test_selected_nodes_sharing() {
        // --- Valid: select both adds ---
        let mut graph = make_resource_sharing_graph();
        let selected = vec!["add1".to_string(), "add2".to_string()];
        let success = apply_resource_sharing_to_selected_nodes(&mut graph, &selected);
        assert!(
            success,
            "Should succeed when selecting two matching operation nodes"
        );
        assert!(graph.nodes.contains_key("uarch_cycle_counter"));

        // --- Invalid: fewer than 2 nodes ---
        let mut graph2 = make_resource_sharing_graph();
        let single = vec!["add1".to_string()];
        let fail_single = apply_resource_sharing_to_selected_nodes(&mut graph2, &single);
        assert!(
            !fail_single,
            "Should fail with fewer than 2 selected nodes"
        );

        // --- Invalid: non-existent node ---
        let mut graph3 = make_resource_sharing_graph();
        let missing = vec!["add1".to_string(), "nonexistent".to_string()];
        let fail_missing = apply_resource_sharing_to_selected_nodes(&mut graph3, &missing);
        assert!(!fail_missing, "Should fail when a selected node is missing");

        // --- Invalid: mixed operator types ---
        let mut graph4 = make_resource_sharing_graph();
        // Change add2's operator to something different.
        graph4
            .nodes
            .get_mut("add2")
            .unwrap()
            .data
            .insert("operator".to_string(), json!("-"));
        let mixed = vec!["add1".to_string(), "add2".to_string()];
        let fail_mixed = apply_resource_sharing_to_selected_nodes(&mut graph4, &mixed);
        assert!(
            !fail_mixed,
            "Should fail when selected operations have different operators"
        );
    }

    // -----------------------------------------------------------------------
    // 11. _get_node_width
    // -----------------------------------------------------------------------
    #[test]
    fn test_get_node_width() {
        let mut graph = ResourceGraph::new();

        // Node with bit_width.
        let mut n1 = Node::with_defaults(Some("n1".to_string()));
        n1.data.insert("bit_width".to_string(), json!(16));
        graph.add_node(n1);

        // Node with width (no bit_width).
        let mut n2 = Node::with_defaults(Some("n2".to_string()));
        n2.data.insert("width".to_string(), json!(8));
        graph.add_node(n2);

        // Node with bit_slice expression.
        let mut n3 = Node::with_defaults(Some("n3".to_string()));
        n3.data.insert("type".to_string(), json!("bit_slice"));
        n3.data.insert(
            "expression".to_string(),
            json!({"range": [15, 4]}),
        );
        graph.add_node(n3);

        // Node with no width info -> fallback to 32.
        let n4 = Node::with_defaults(Some("n4".to_string()));
        graph.add_node(n4);

        let transform = ResourceSharingTransform::new(&mut graph);
        assert_eq!(transform._get_node_width("n1"), 16);
        assert_eq!(transform._get_node_width("n2"), 8);
        assert_eq!(
            transform._get_node_width("n3"),
            12,
            "bit_slice [15:4] -> 15 - 4 + 1 = 12"
        );
        assert_eq!(
            transform._get_node_width("n4"),
            32,
            "Fallback width should be 32"
        );
        assert_eq!(
            transform._get_node_width("nonexistent"),
            32,
            "Missing node should return fallback width 32"
        );
    }

    // -----------------------------------------------------------------------
    // 12. extract_time_slot_from_name
    // -----------------------------------------------------------------------
    #[test]
    fn test_extract_time_slot() {
        assert_eq!(
            ResourceSharingTransform::extract_time_slot_from_name("foo_t0_reg"),
            Some(0)
        );
        assert_eq!(
            ResourceSharingTransform::extract_time_slot_from_name("bar_t2_reg"),
            Some(2)
        );
        assert_eq!(
            ResourceSharingTransform::extract_time_slot_from_name("baz_result_t3_reg"),
            Some(3)
        );
        assert_eq!(
            ResourceSharingTransform::extract_time_slot_from_name("src_a_t10_reg"),
            Some(10)
        );
        assert_eq!(
            ResourceSharingTransform::extract_time_slot_from_name("no_slot_here"),
            None,
            "Name without _t<digit> pattern should return None"
        );
        // Edge case: _t followed by non-digit.
        assert_eq!(
            ResourceSharingTransform::extract_time_slot_from_name("a_type_node"),
            None,
            "_type does not contain a leading digit after _t"
        );
    }

    // -----------------------------------------------------------------------
    // 13. get_transformation_summary
    // -----------------------------------------------------------------------
    #[test]
    fn test_transformation_summary() {
        let mut graph = make_resource_sharing_graph();
        let mut transform = ResourceSharingTransform::new(&mut graph);

        // Before any sharing -- empty summary.
        let empty_summary = transform.get_transformation_summary();
        assert!(
            empty_summary.contains("No shareable resources"),
            "Summary before sharing should mention no shareable resources"
        );

        // After sharing.
        let _resources = transform.identify_shareable_resources("operation", Some("+"));
        let _success = transform.apply_resource_sharing("operation_+");

        let summary = transform.get_transformation_summary();
        assert!(
            !summary.is_empty(),
            "Summary after sharing must be non-empty"
        );
        assert!(
            summary.contains("operation_+"),
            "Summary should mention the resource key"
        );
        assert!(
            summary.contains("Uarch Counter"),
            "Summary should mention the uarch counter"
        );
        assert!(
            summary.contains("Pipeline depth"),
            "Summary should mention pipeline depth"
        );
    }
}
