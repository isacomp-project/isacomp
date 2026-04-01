//! Unified operation sharing optimization for merged ResourceGraphs.
//!
//! Supports two modes:
//! - SPATIAL: Mux-based sharing within a single cycle (operand muxes + gated results)
//! - TEMPORAL: Time-multiplexed sharing across cycles (counter + pipeline registers + ISA gating)
//!
//! The designer explicitly selects which nodes to share — isacomp validates
//! and applies the sharing, but does not automatically discover sharing
//! opportunities.

use std::collections::HashMap;

use log::{debug, info, warn};
use serde_json::{json, Value};

use crate::operation_serialization::ISAStateGatingHelper;
use crate::resource_graph::{Edge, Node, ResourceGraph};

// ---------------------------------------------------------------------------
// SharingMode
// ---------------------------------------------------------------------------

/// Sharing strategy: spatial (mux-based, single cycle) or temporal
/// (counter-based, multi-cycle).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SharingMode {
    /// Mux-based sharing within a single cycle.  Requires mutual exclusivity.
    Spatial,
    /// Counter-based time-multiplexing across cycles.
    Temporal,
}

// ---------------------------------------------------------------------------
// OperandAnalysis
// ---------------------------------------------------------------------------

/// Result of analyzing operand patterns across multiple operations.
#[derive(Debug, Clone)]
pub struct OperandAnalysis {
    /// Whether the operations can be shared.
    pub can_share: bool,
    /// Number of operands each operation has.
    pub num_operands: usize,
    /// Operand positions that are identical across all operations: (position, node_id).
    pub shared_operands: Vec<(usize, String)>,
    /// Operand positions that differ and need a mux: (position, vec of node_ids per operation).
    pub muxed_operands: Vec<(usize, Vec<String>)>,
}

// ---------------------------------------------------------------------------
// OperationSharingTransform
// ---------------------------------------------------------------------------

/// Implements operation sharing transformations on merged ResourceGraphs.
pub struct OperationSharingTransform<'a> {
    pub graph: &'a mut ResourceGraph,
    /// Sharing mode: spatial (mux) or temporal (counter).
    pub mode: SharingMode,
    /// Maps resource_key -> vec of node IDs that share that resource (temporal mode).
    pub shared_resources: HashMap<String, Vec<String>>,
    /// Node ID of the uarch counter, if created (temporal mode).
    pub uarch_counter_id: Option<String>,
}

impl<'a> OperationSharingTransform<'a> {
    /// Create a new OperationSharingTransform.
    pub fn new(graph: &'a mut ResourceGraph) -> Self {
        Self::with_mode(graph, SharingMode::Spatial)
    }

    /// Create a new OperationSharingTransform with a specific mode.
    pub fn with_mode(graph: &'a mut ResourceGraph, mode: SharingMode) -> Self {
        Self {
            graph,
            mode,
            shared_resources: HashMap::new(),
            uarch_counter_id: None,
        }
    }

    /// Apply operation sharing for designer-selected node IDs.
    ///
    /// The designer explicitly specifies which nodes to share — isacomp
    /// validates the selection and applies sharing, but does not automatically
    /// discover sharing opportunities.
    ///
    /// Dispatches to spatial or temporal based on `self.mode`.
    ///
    /// Returns `true` if any operations were shared.
    pub fn apply_operation_sharing(&mut self, selected_node_ids: &[String]) -> bool {
        if selected_node_ids.len() < 2 {
            info!("Need at least 2 nodes for sharing (got {})", selected_node_ids.len());
            return false;
        }

        // Validate all nodes exist and are operations with the same operator.
        let mut operator: Option<String> = None;
        for node_id in selected_node_ids {
            let node = match self.graph.nodes.get(node_id) {
                Some(n) => n,
                None => {
                    info!("Node {} not found in graph", node_id);
                    return false;
                }
            };

            if node.data.get("type").and_then(|v| v.as_str()) != Some("operation") {
                info!("Node {} is not an operation", node_id);
                return false;
            }

            let node_op = node.data.get("expression")
                .and_then(|e| e.get("operator"))
                .and_then(|v| v.as_str())
                .or_else(|| node.data.get("operator").and_then(|v| v.as_str()));

            match (&operator, node_op) {
                (None, Some(op)) => operator = Some(op.to_string()),
                (Some(expected), Some(op)) if expected != op => {
                    info!("Selected operations must have the same operator (got {} and {})", expected, op);
                    return false;
                }
                (_, None) => {
                    info!("Node {} has no operator", node_id);
                    return false;
                }
                _ => {}
            }
        }

        let operator = operator.unwrap();
        let operation_ids: Vec<String> = selected_node_ids.to_vec();

        info!(
            "Sharing {} '{}' operations ({:?} mode):",
            operation_ids.len(),
            operator,
            self.mode
        );
        for op_id in &operation_ids {
            let instruction = self
                .graph
                .nodes
                .get(op_id)
                .and_then(|n| n.data.get("instruction"))
                .and_then(|v| v.as_str())
                .unwrap_or("shared");
            let display = self
                .graph
                .nodes
                .get(op_id)
                .and_then(|n| n.data.get("display_name"))
                .and_then(|v| v.as_str())
                .unwrap_or(op_id.as_str());
            info!("  {} [{}]", display, instruction);
        }

        match self.mode {
            SharingMode::Spatial => {
                // Verify mutual exclusivity: operations must belong to different
                // instructions (1-hot decoded) so they never fire simultaneously.
                if !self._check_mutual_exclusivity(&operation_ids) {
                    return false;
                }

                // Analyze operand patterns.
                let analysis = match self._analyze_operands(&operation_ids) {
                    Some(a) if a.can_share => a,
                    _ => {
                        info!(
                            "  Cannot share '{}' operations - incompatible operand patterns",
                            operator
                        );
                        return false;
                    }
                };

                // Create shared operation with muxes.
                self._create_shared_operation(&operation_ids, &analysis, &operator);

                true
            }
            SharingMode::Temporal => {
                // Set up shared_resources for temporal sharing.
                let resource_key = format!("operation_{}", operator);
                self.shared_resources
                    .insert(resource_key.clone(), operation_ids);

                // Apply temporal (counter-based) sharing.
                self._apply_temporal_sharing(&resource_key)
            }
        }
    }

    /// Verify that operations are mutually exclusive for spatial sharing.
    ///
    /// Operations are mutually exclusive when their instruction sets don't
    /// overlap.  Since instructions are 1-hot decoded, operations from
    /// different instructions can never fire simultaneously.
    pub fn _check_mutual_exclusivity(&self, operation_ids: &[String]) -> bool {
        let mut instruction_sets: Vec<(&str, std::collections::HashSet<String>)> = Vec::new();

        for op_id in operation_ids {
            let node = match self.graph.nodes.get(op_id) {
                Some(n) => n,
                None => return false,
            };

            let instruction = node
                .data
                .get("instruction")
                .and_then(|v| v.as_str())
                .unwrap_or("shared");

            if instruction == "shared" {
                info!(
                    "Cannot determine instruction set for {} — cannot verify mutual exclusivity",
                    op_id
                );
                return false;
            }

            let instr_set: std::collections::HashSet<String> =
                std::iter::once(instruction.to_string()).collect();
            instruction_sets.push((op_id.as_str(), instr_set));
        }

        // Pairwise overlap check.
        for i in 0..instruction_sets.len() {
            for j in (i + 1)..instruction_sets.len() {
                let overlap: Vec<&String> = instruction_sets[i]
                    .1
                    .intersection(&instruction_sets[j].1)
                    .collect();
                if !overlap.is_empty() {
                    info!(
                        "Operations {} and {} are NOT mutually exclusive — both active for instruction(s): {:?}",
                        instruction_sets[i].0,
                        instruction_sets[j].0,
                        overlap
                    );
                    return false;
                }
            }
        }

        true
    }

    /// Analyze operand patterns to determine if operations can be shared.
    ///
    /// Returns `None` if there are no operations or analysis fails.
    pub fn _analyze_operands(&self, operation_ids: &[String]) -> Option<OperandAnalysis> {
        if operation_ids.is_empty() {
            return None;
        }

        // For each operation, collect ordered list of operand source node IDs.
        let mut operand_sets: Vec<Vec<String>> = Vec::new();

        for op_id in operation_ids {
            let node = self.graph.nodes.get(op_id)?;
            let mut operands: Vec<String> = Vec::new();

            // Collect edges whose type == "operand", ordered by the edge data
            // (position or insertion order).
            let mut operand_edges: Vec<(&String, &Edge)> = node
                .incoming_edges
                .iter()
                .filter_map(|eid| {
                    let edge = self.graph.edges.get(eid)?;
                    if edge.data.get("type").and_then(|v| v.as_str()) == Some("operand") {
                        Some((eid, edge))
                    } else {
                        None
                    }
                })
                .collect();

            // Sort by operand_position if available, otherwise by edge id for stability.
            operand_edges.sort_by(|a, b| {
                let pos_a = a
                    .1
                    .data
                    .get("operand_position")
                    .and_then(|v| v.as_i64())
                    .unwrap_or(0);
                let pos_b = b
                    .1
                    .data
                    .get("operand_position")
                    .and_then(|v| v.as_i64())
                    .unwrap_or(0);
                pos_a.cmp(&pos_b).then_with(|| a.0.cmp(b.0))
            });

            for (_eid, edge) in &operand_edges {
                operands.push(edge.source.clone());
            }

            operand_sets.push(operands);
        }

        if operand_sets.is_empty() {
            return Some(OperandAnalysis {
                can_share: false,
                num_operands: 0,
                shared_operands: Vec::new(),
                muxed_operands: Vec::new(),
            });
        }

        // Check all operations have the same number of operands.
        let num_operands = operand_sets[0].len();
        if operand_sets.iter().any(|ops| ops.len() != num_operands) {
            return Some(OperandAnalysis {
                can_share: false,
                num_operands: 0,
                shared_operands: Vec::new(),
                muxed_operands: Vec::new(),
            });
        }

        // Analyze which operand positions can be shared vs. need a mux.
        let mut shared_operands: Vec<(usize, String)> = Vec::new();
        let mut muxed_operands: Vec<(usize, Vec<String>)> = Vec::new();

        for pos in 0..num_operands {
            let operands_at_pos: Vec<String> =
                operand_sets.iter().map(|ops| ops[pos].clone()).collect();

            if operands_at_pos
                .iter()
                .all(|op| *op == operands_at_pos[0])
            {
                // All the same - can be shared directly.
                shared_operands.push((pos, operands_at_pos[0].clone()));
            } else {
                // Different - needs a mux.
                muxed_operands.push((pos, operands_at_pos));
            }
        }

        Some(OperandAnalysis {
            can_share: true,
            num_operands,
            shared_operands,
            muxed_operands,
        })
    }

    /// Create a shared operation with input multiplexing.
    pub fn _create_shared_operation(
        &mut self,
        operation_ids: &[String],
        analysis: &OperandAnalysis,
        operator: &str,
    ) {
        // Create shared operation node.
        let shared_op_name = format!("shared_{}_op", operator);

        let mut shared_op_data: HashMap<String, Value> = HashMap::new();
        shared_op_data.insert("type".to_string(), json!("operation"));
        shared_op_data.insert("name".to_string(), json!(shared_op_name));
        shared_op_data.insert(
            "display_name".to_string(),
            json!(format!("shared {}", operator)),
        );
        shared_op_data.insert("operation".to_string(), json!(operator));
        shared_op_data.insert(
            "expression".to_string(),
            json!({
                "type": "binary_op",
                "operator": operator,
                "left": {"type": "identifier", "name": "operand1"},
                "right": {"type": "identifier", "name": "operand2"}
            }),
        );

        let mut shared_op_node = Node::with_defaults(Some(shared_op_name.clone()));
        shared_op_node.data = shared_op_data;
        self.graph.add_node(shared_op_node);

        info!("  Created shared operation: {}", shared_op_name);

        // Create operand connections.
        self._create_operand_connections(&shared_op_name, analysis, operation_ids);

        // Route shared result to all original destinations.
        self._route_shared_results(&shared_op_name, operation_ids);

        // Remove original operation nodes.
        for op_id in operation_ids {
            self._remove_operation_node(op_id);
        }
    }

    /// Create operand connections for shared operation.
    pub fn _create_operand_connections(
        &mut self,
        shared_op_id: &str,
        analysis: &OperandAnalysis,
        operation_ids: &[String],
    ) {
        // Handle shared operands (direct connections).
        for (pos, operand_node_id) in &analysis.shared_operands {
            let operand_name = format!("operand{}", pos + 1);
            let mut edge_data: HashMap<String, Value> = HashMap::new();
            edge_data.insert("type".to_string(), json!("operand"));
            edge_data.insert("operand_position".to_string(), json!(*pos));
            edge_data.insert("operand_name".to_string(), json!(operand_name));

            let edge = Edge::new(
                operand_node_id.clone(),
                shared_op_id.to_string(),
                None,
                Some(edge_data),
            );
            self.graph.add_edge(edge);

            info!("    Shared operand {}: {}", pos + 1, operand_node_id);
        }

        // Handle muxed operands.
        for (pos, operand_id_list) in &analysis.muxed_operands {
            let mux_name = format!("operand{}_mux", pos + 1);
            self._create_operand_mux(
                &mux_name,
                operand_id_list,
                operation_ids,
                shared_op_id,
                *pos,
            );
        }
    }

    /// Create operand multiplexer for differing operands.
    ///
    /// Creates a `one_hot_mux` node with select inputs from instruction enables.
    pub fn _create_operand_mux(
        &mut self,
        mux_name: &str,
        operand_ids: &[String],
        operation_ids: &[String],
        shared_op_id: &str,
        position: usize,
    ) {
        // Create the mux node.
        let mut mux_data: HashMap<String, Value> = HashMap::new();
        mux_data.insert("type".to_string(), json!("one_hot_mux"));
        mux_data.insert("name".to_string(), json!(mux_name));
        mux_data.insert("display_name".to_string(), json!(mux_name));
        mux_data.insert("operand_position".to_string(), json!(position));
        mux_data.insert(
            "num_inputs".to_string(),
            json!(operand_ids.len()),
        );

        let mut mux_node = Node::with_defaults(Some(mux_name.to_string()));
        mux_node.data = mux_data;
        mux_node.is_uarch_state = true;
        self.graph.add_node(mux_node);

        info!("    Created operand mux: {}", mux_name);

        // Connect mux inputs from different operands.
        for (i, (operand_id, op_id)) in operand_ids.iter().zip(operation_ids.iter()).enumerate() {
            let enable_signal = self._get_instruction_enable(op_id);

            // Connect data input: operand -> mux
            let mut input_data: HashMap<String, Value> = HashMap::new();
            input_data.insert("type".to_string(), json!("mux_input"));
            input_data.insert("input_index".to_string(), json!(i));
            input_data.insert("enable_signal".to_string(), json!(enable_signal));

            let input_edge = Edge::new(
                operand_id.clone(),
                mux_name.to_string(),
                None,
                Some(input_data),
            );
            self.graph.add_edge(input_edge);

            // Connect select input: enable_node -> mux (if the enable node exists)
            if self.graph.nodes.contains_key(&enable_signal) {
                let mut select_data: HashMap<String, Value> = HashMap::new();
                select_data.insert("type".to_string(), json!("mux_select"));
                select_data.insert("input_index".to_string(), json!(i));
                select_data.insert("select_for".to_string(), json!(operand_id));

                let select_edge = Edge::new(
                    enable_signal.clone(),
                    mux_name.to_string(),
                    None,
                    Some(select_data),
                );
                self.graph.add_edge(select_edge);
            }

            info!("      Input {}: {} (when {})", i, operand_id, enable_signal);
        }

        // Connect mux output to shared operation.
        let mut output_data: HashMap<String, Value> = HashMap::new();
        output_data.insert("type".to_string(), json!("operand"));
        output_data.insert("operand_position".to_string(), json!(position));
        output_data.insert(
            "operand_name".to_string(),
            json!(format!("operand{}", position + 1)),
        );

        let output_edge = Edge::new(
            mux_name.to_string(),
            shared_op_id.to_string(),
            None,
            Some(output_data),
        );
        self.graph.add_edge(output_edge);
    }

    /// Get the instruction enable signal name for an operation.
    pub fn _get_instruction_enable(&self, operation_id: &str) -> String {
        if let Some(node) = self.graph.nodes.get(operation_id) {
            let instruction = node
                .data
                .get("instruction")
                .and_then(|v| v.as_str())
                .unwrap_or("shared");

            if instruction == "shared" {
                "default_enable".to_string()
            } else {
                format!("{}_enable", instruction)
            }
        } else {
            "default_enable".to_string()
        }
    }

    /// Route shared operation result to all original destinations.
    pub fn _route_shared_results(&mut self, shared_op_id: &str, operation_ids: &[String]) {
        // Collect all original result destinations: (target_node_id, original_operation_id).
        let mut result_destinations: Vec<(String, String)> = Vec::new();

        for op_id in operation_ids {
            if let Some(node) = self.graph.nodes.get(op_id) {
                let outgoing: Vec<String> = node.outgoing_edges.iter().cloned().collect();
                for eid in &outgoing {
                    if let Some(edge) = self.graph.edges.get(eid) {
                        if edge.data.get("type").and_then(|v| v.as_str()) == Some("assignment") {
                            result_destinations.push((edge.target.clone(), op_id.clone()));
                        }
                    }
                }
            }
        }

        info!(
            "    Routing shared result to {} destinations:",
            result_destinations.len()
        );

        // Create edges from shared operation to all destinations.
        for (dest_node_id, orig_op_id) in &result_destinations {
            let enable_signal = self._get_instruction_enable(orig_op_id);

            let mut edge_data: HashMap<String, Value> = HashMap::new();
            edge_data.insert("type".to_string(), json!("assignment"));
            edge_data.insert("gated_by".to_string(), json!(enable_signal));
            edge_data.insert("original_operation".to_string(), json!(orig_op_id));

            let result_edge = Edge::new(
                shared_op_id.to_string(),
                dest_node_id.clone(),
                None,
                Some(edge_data),
            );
            self.graph.add_edge(result_edge);

            let dest_instruction = self
                .graph
                .nodes
                .get(dest_node_id)
                .and_then(|n| n.data.get("instruction"))
                .and_then(|v| v.as_str())
                .unwrap_or("shared");
            info!(
                "      -> {} [{}] (when {})",
                dest_node_id, dest_instruction, enable_signal
            );
        }
    }

    /// Remove an original operation node and its edges.
    pub fn _remove_operation_node(&mut self, operation_id: &str) {
        info!("    Removing original operation: {}", operation_id);

        // Collect all edge IDs connected to this node.
        let edge_ids: Vec<String> = if let Some(node) = self.graph.nodes.get(operation_id) {
            node.incoming_edges
                .iter()
                .chain(node.outgoing_edges.iter())
                .cloned()
                .collect()
        } else {
            return;
        };

        // Remove edges first.
        for eid in &edge_ids {
            self.graph.remove_edge(eid);
        }

        // Remove the node.
        self.graph.nodes.remove(operation_id);
    }

    // ===================================================================== //
    //  Temporal sharing methods (counter-based time-multiplexing)
    // ===================================================================== //

    /// Apply temporal (counter-based) resource sharing for a resource key.
    fn _apply_temporal_sharing(&mut self, resource_key: &str) -> bool {
        let resource_ids = match self.shared_resources.get(resource_key) {
            Some(ids) if ids.len() >= 2 => ids.clone(),
            _ => return false,
        };

        let num_sharers = resource_ids.len();
        info!("Temporal sharing {} across {} instances", resource_key, num_sharers);

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
                if let Some(time_slot) = Self::extract_time_slot_from_name(node_id) {
                    if node_id.contains("result_t") && node_id.contains("_reg") {
                        if let Some(node) = self.graph.nodes.get_mut(node_id) {
                            node.uarch_time = Some(time_slot + 1);
                            info!(
                                "  Set {} timing to {} (result register)",
                                node_id,
                                time_slot + 1
                            );
                        }
                    } else if node_id.contains("_reg") && !node_id.contains("result") {
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

        // Counter increment logic at time 0.
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
        for _pass in 0..3 {
            self._propagate_isa_state_timing(&node_ids);
        }

        self._propagate_aggregate_timing(&node_ids);
        self._final_timing_pass(&node_ids);

        let final_time = self.graph.get_max_uarch_time();
        info!("  Resource sharing sequence: 0 to {} cycles", final_time);
    }

    /// Propagate timing from assignment sources to ISA state write targets.
    fn _propagate_isa_state_timing(&mut self, node_ids: &[String]) {
        for node_id in node_ids {
            let mut max_incoming_time: Option<i64> = None;
            let mut _source_id: Option<String> = None;

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

                if src_id.contains("result") && src_id.contains("reg") {
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
        for node_id in node_ids {
            let current_time = self
                .graph
                .nodes
                .get(node_id)
                .and_then(|n| n.uarch_time);

            if current_time.is_some() {
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
    pub fn extract_time_slot_from_name(name: &str) -> Option<i64> {
        let mut parts = name.split("_t");
        parts.next();
        for part in parts {
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
            if let Some(w) = node.data.get("bit_width").and_then(|v| v.as_i64()) {
                return w;
            }
            if let Some(w) = node.data.get("width").and_then(|v| v.as_i64()) {
                return w;
            }
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
        32
    }

    /// Generate a summary of the sharing transformation.
    pub fn get_transformation_summary(&self) -> String {
        let mut summary = String::new();
        summary.push_str("Operation Sharing Transformation Summary:\n");
        summary.push_str(&"=".repeat(50));
        summary.push_str("\n\n");
        summary.push_str(&format!("Mode: {:?}\n\n", self.mode));

        if self.shared_resources.is_empty() {
            summary.push_str("No shared resources.\n");
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
// Standalone function
// ---------------------------------------------------------------------------

/// Apply operation sharing to designer-selected nodes.
///
/// `mode` defaults to `SharingMode::Spatial` when not specified.
///
/// Returns `true` if any operations were shared.
pub fn apply_operation_sharing(
    graph: &mut ResourceGraph,
    selected_node_ids: &[String],
    mode: SharingMode,
) -> bool {
    let mut transform = OperationSharingTransform::with_mode(graph, mode);
    let success = transform.apply_operation_sharing(selected_node_ids);

    if success && mode == SharingMode::Temporal {
        info!("\nTransformation Summary:");
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

    // -----------------------------------------------------------------------
    // Helper: create an operation node with binary_op expression
    // -----------------------------------------------------------------------
    fn make_operation_node(id: &str, operator: &str, instruction: &str) -> Node {
        let mut node = Node::with_defaults(Some(id.to_string()));
        node.data.insert("type".to_string(), json!("operation"));
        node.data.insert("name".to_string(), json!(id));
        node.data.insert("display_name".to_string(), json!(id));
        node.data.insert("instruction".to_string(), json!(instruction));
        node.data.insert(
            "expression".to_string(),
            json!({
                "type": "binary_op",
                "operator": operator,
                "left":  {"type": "identifier", "name": "left"},
                "right": {"type": "identifier", "name": "right"}
            }),
        );
        node
    }

    /// Create a simple variable node.
    fn make_var_node(id: &str) -> Node {
        let mut node = Node::with_defaults(Some(id.to_string()));
        node.data.insert("type".to_string(), json!("var"));
        node.data.insert("name".to_string(), json!(id));
        node
    }

    /// Create an operand edge (source → operation, with position).
    fn make_operand_edge(source: &str, target: &str, position: usize) -> Edge {
        let mut data: HashMap<String, Value> = HashMap::new();
        data.insert("type".to_string(), json!("operand"));
        data.insert("operand_position".to_string(), json!(position));
        Edge::new(source.to_string(), target.to_string(), None, Some(data))
    }

    /// Create an assignment edge (operation → destination).
    fn make_assignment_edge(source: &str, target: &str) -> Edge {
        let mut data: HashMap<String, Value> = HashMap::new();
        data.insert("type".to_string(), json!("assignment"));
        Edge::new(source.to_string(), target.to_string(), None, Some(data))
    }

    /// Build a test graph with two add operations having distinct operands:
    ///
    ///   a ─operand0─> add_op1 ─assignment─> dest1
    ///   b ─operand1─> add_op1
    ///   c ─operand0─> add_op2 ─assignment─> dest2
    ///   d ─operand1─> add_op2
    ///
    /// Also adds `add_enable` and `sub_enable` nodes so the mux select works.
    fn make_sharing_graph() -> ResourceGraph {
        let mut g = ResourceGraph::new();

        // Operand source nodes
        g.add_node(make_var_node("a"));
        g.add_node(make_var_node("b"));
        g.add_node(make_var_node("c"));
        g.add_node(make_var_node("d"));

        // Destination nodes
        g.add_node(make_var_node("dest1"));
        g.add_node(make_var_node("dest2"));

        // Operation nodes
        g.add_node(make_operation_node("add_op1", "+", "add"));
        g.add_node(make_operation_node("add_op2", "+", "sub"));

        // Enable nodes (so mux select edges get created)
        g.add_node(make_var_node("add_enable"));
        g.add_node(make_var_node("sub_enable"));

        // Operand edges
        g.add_edge(make_operand_edge("a", "add_op1", 0));
        g.add_edge(make_operand_edge("b", "add_op1", 1));
        g.add_edge(make_operand_edge("c", "add_op2", 0));
        g.add_edge(make_operand_edge("d", "add_op2", 1));

        // Assignment edges
        g.add_edge(make_assignment_edge("add_op1", "dest1"));
        g.add_edge(make_assignment_edge("add_op2", "dest2"));

        g
    }

    // -----------------------------------------------------------------------
    // 1. test_no_operations_to_share
    // -----------------------------------------------------------------------
    #[test]
    fn test_no_operations_to_share() {
        // Empty selection → returns false
        let mut g = ResourceGraph::new();
        let mut t = OperationSharingTransform::new(&mut g);
        assert!(!t.apply_operation_sharing(&[]));

        // Graph with a single add operation → returns false
        let mut g2 = ResourceGraph::new();
        g2.add_node(make_var_node("a"));
        g2.add_node(make_var_node("b"));
        g2.add_node(make_operation_node("add_op1", "+", "add"));
        g2.add_edge(make_operand_edge("a", "add_op1", 0));
        g2.add_edge(make_operand_edge("b", "add_op1", 1));

        let mut t2 = OperationSharingTransform::new(&mut g2);
        assert!(!t2.apply_operation_sharing(&["add_op1".to_string()]));
        // Original node should remain untouched.
        assert!(g2.nodes.contains_key("add_op1"));
    }

    // -----------------------------------------------------------------------
    // 2. test_share_two_add_operations
    // -----------------------------------------------------------------------
    #[test]
    fn test_share_two_add_operations() {
        let mut g = make_sharing_graph();

        let selected = vec!["add_op1".to_string(), "add_op2".to_string()];
        let mut t = OperationSharingTransform::new(&mut g);
        let result = t.apply_operation_sharing(&selected);
        assert!(result, "Should return true when sharing occurs");

        // Shared operation node should exist.
        assert!(
            g.nodes.contains_key("shared_+_op"),
            "shared_+_op node must be created"
        );

        let shared = g.nodes.get("shared_+_op").unwrap();
        assert_eq!(
            shared.data.get("type").unwrap(),
            &json!("operation"),
            "shared node type"
        );
        assert_eq!(
            shared.data.get("operation").unwrap(),
            &json!("+"),
            "shared node operation"
        );

        // Original operation nodes should be gone.
        assert!(
            !g.nodes.contains_key("add_op1"),
            "add_op1 must be removed"
        );
        assert!(
            !g.nodes.contains_key("add_op2"),
            "add_op2 must be removed"
        );

        // Operand muxes should be created (both operand positions differ).
        assert!(
            g.nodes.contains_key("operand1_mux"),
            "operand1_mux must exist"
        );
        assert!(
            g.nodes.contains_key("operand2_mux"),
            "operand2_mux must exist"
        );

        // Verify operand mux data.
        let mux1 = g.nodes.get("operand1_mux").unwrap();
        assert_eq!(mux1.data.get("type").unwrap(), &json!("one_hot_mux"));
        assert_eq!(mux1.data.get("num_inputs").unwrap(), &json!(2));
        assert!(mux1.is_uarch_state);

        // Verify mux → shared op connection (operand edge from operand1_mux → shared_+_op).
        let mux1_to_shared: Vec<&Edge> = g
            .edges
            .values()
            .filter(|e| e.source == "operand1_mux" && e.target == "shared_+_op")
            .collect();
        assert_eq!(mux1_to_shared.len(), 1, "one edge from mux1 to shared op");
        assert_eq!(
            mux1_to_shared[0].data.get("type").unwrap(),
            &json!("operand")
        );

        // Verify data inputs to mux: a → operand1_mux and c → operand1_mux.
        let a_to_mux: Vec<&Edge> = g
            .edges
            .values()
            .filter(|e| e.source == "a" && e.target == "operand1_mux")
            .collect();
        assert_eq!(a_to_mux.len(), 1);
        assert_eq!(
            a_to_mux[0].data.get("type").unwrap(),
            &json!("mux_input")
        );

        let c_to_mux: Vec<&Edge> = g
            .edges
            .values()
            .filter(|e| e.source == "c" && e.target == "operand1_mux")
            .collect();
        assert_eq!(c_to_mux.len(), 1);

        // Verify select inputs to mux from enable nodes.
        let add_en_to_mux: Vec<&Edge> = g
            .edges
            .values()
            .filter(|e| e.source == "add_enable" && e.target == "operand1_mux")
            .collect();
        assert_eq!(add_en_to_mux.len(), 1);
        assert_eq!(
            add_en_to_mux[0].data.get("type").unwrap(),
            &json!("mux_select")
        );

        // Result routing: shared_+_op → dest1 and shared_+_op → dest2.
        let shared_to_dest1: Vec<&Edge> = g
            .edges
            .values()
            .filter(|e| e.source == "shared_+_op" && e.target == "dest1")
            .collect();
        assert_eq!(shared_to_dest1.len(), 1);
        assert_eq!(
            shared_to_dest1[0].data.get("type").unwrap(),
            &json!("assignment")
        );

        let shared_to_dest2: Vec<&Edge> = g
            .edges
            .values()
            .filter(|e| e.source == "shared_+_op" && e.target == "dest2")
            .collect();
        assert_eq!(shared_to_dest2.len(), 1);
    }

    // -----------------------------------------------------------------------
    // 3. test_shared_operands_no_mux
    // -----------------------------------------------------------------------
    #[test]
    fn test_shared_operands_no_mux() {
        // Two add ops sharing the exact same operands → no mux needed.
        let mut g = ResourceGraph::new();

        g.add_node(make_var_node("a"));
        g.add_node(make_var_node("b"));
        g.add_node(make_var_node("dest1"));
        g.add_node(make_var_node("dest2"));
        g.add_node(make_operation_node("add_op1", "+", "add"));
        g.add_node(make_operation_node("add_op2", "+", "sub"));

        // Both ops use the same sources: a (pos 0) and b (pos 1).
        g.add_edge(make_operand_edge("a", "add_op1", 0));
        g.add_edge(make_operand_edge("b", "add_op1", 1));
        g.add_edge(make_operand_edge("a", "add_op2", 0));
        g.add_edge(make_operand_edge("b", "add_op2", 1));

        g.add_edge(make_assignment_edge("add_op1", "dest1"));
        g.add_edge(make_assignment_edge("add_op2", "dest2"));

        let selected = vec!["add_op1".to_string(), "add_op2".to_string()];
        let mut t = OperationSharingTransform::new(&mut g);
        assert!(t.apply_operation_sharing(&selected));

        // Shared op should exist.
        assert!(g.nodes.contains_key("shared_+_op"));

        // No muxes should be created since all operands are identical.
        assert!(
            !g.nodes.contains_key("operand1_mux"),
            "No mux for operand 1"
        );
        assert!(
            !g.nodes.contains_key("operand2_mux"),
            "No mux for operand 2"
        );

        // Direct connections: a → shared_+_op and b → shared_+_op.
        let a_to_shared: Vec<&Edge> = g
            .edges
            .values()
            .filter(|e| e.source == "a" && e.target == "shared_+_op")
            .collect();
        assert_eq!(a_to_shared.len(), 1);
        assert_eq!(
            a_to_shared[0].data.get("type").unwrap(),
            &json!("operand")
        );
        assert_eq!(
            a_to_shared[0].data.get("operand_position").unwrap(),
            &json!(0)
        );

        let b_to_shared: Vec<&Edge> = g
            .edges
            .values()
            .filter(|e| e.source == "b" && e.target == "shared_+_op")
            .collect();
        assert_eq!(b_to_shared.len(), 1);
        assert_eq!(
            b_to_shared[0].data.get("operand_position").unwrap(),
            &json!(1)
        );

        // Originals removed.
        assert!(!g.nodes.contains_key("add_op1"));
        assert!(!g.nodes.contains_key("add_op2"));
    }

    // -----------------------------------------------------------------------
    // 4. test_mixed_shared_and_muxed
    // -----------------------------------------------------------------------
    #[test]
    fn test_mixed_shared_and_muxed() {
        // Operand 0 is the same (a), operand 1 differs (b vs d).
        let mut g = ResourceGraph::new();

        g.add_node(make_var_node("a"));
        g.add_node(make_var_node("b"));
        g.add_node(make_var_node("d"));
        g.add_node(make_var_node("dest1"));
        g.add_node(make_var_node("dest2"));
        g.add_node(make_operation_node("add_op1", "+", "add"));
        g.add_node(make_operation_node("add_op2", "+", "sub"));
        g.add_node(make_var_node("add_enable"));
        g.add_node(make_var_node("sub_enable"));

        // Same source for position 0.
        g.add_edge(make_operand_edge("a", "add_op1", 0));
        g.add_edge(make_operand_edge("a", "add_op2", 0));

        // Different sources for position 1.
        g.add_edge(make_operand_edge("b", "add_op1", 1));
        g.add_edge(make_operand_edge("d", "add_op2", 1));

        g.add_edge(make_assignment_edge("add_op1", "dest1"));
        g.add_edge(make_assignment_edge("add_op2", "dest2"));

        let selected = vec!["add_op1".to_string(), "add_op2".to_string()];
        let mut t = OperationSharingTransform::new(&mut g);
        assert!(t.apply_operation_sharing(&selected));

        assert!(g.nodes.contains_key("shared_+_op"));

        // Operand 0 is shared → direct connection, no mux.
        assert!(
            !g.nodes.contains_key("operand1_mux"),
            "No mux for shared operand 1"
        );
        let a_to_shared: Vec<&Edge> = g
            .edges
            .values()
            .filter(|e| e.source == "a" && e.target == "shared_+_op")
            .collect();
        assert_eq!(a_to_shared.len(), 1, "Direct a → shared_+_op");

        // Operand 1 differs → mux created.
        assert!(
            g.nodes.contains_key("operand2_mux"),
            "Mux for differing operand 2"
        );
        let mux2 = g.nodes.get("operand2_mux").unwrap();
        assert_eq!(mux2.data.get("type").unwrap(), &json!("one_hot_mux"));

        // b and d should feed into operand2_mux.
        let b_to_mux: Vec<&Edge> = g
            .edges
            .values()
            .filter(|e| e.source == "b" && e.target == "operand2_mux")
            .collect();
        assert_eq!(b_to_mux.len(), 1);

        let d_to_mux: Vec<&Edge> = g
            .edges
            .values()
            .filter(|e| e.source == "d" && e.target == "operand2_mux")
            .collect();
        assert_eq!(d_to_mux.len(), 1);

        // operand2_mux → shared_+_op
        let mux_to_shared: Vec<&Edge> = g
            .edges
            .values()
            .filter(|e| e.source == "operand2_mux" && e.target == "shared_+_op")
            .collect();
        assert_eq!(mux_to_shared.len(), 1);
    }

    // -----------------------------------------------------------------------
    // 5. test_multiple_operator_types
    // -----------------------------------------------------------------------
    #[test]
    fn test_multiple_operator_types() {
        let mut g = ResourceGraph::new();

        // Source/dest nodes.
        for name in &["a", "b", "c", "d", "e", "f", "g", "h",
                       "dest1", "dest2", "dest3", "dest4"] {
            g.add_node(make_var_node(name));
        }

        // Enable nodes.
        g.add_node(make_var_node("add_enable"));
        g.add_node(make_var_node("sub_enable"));
        g.add_node(make_var_node("and_enable"));
        g.add_node(make_var_node("or_enable"));

        // Two add operations.
        g.add_node(make_operation_node("add_op1", "+", "add"));
        g.add_node(make_operation_node("add_op2", "+", "sub"));
        g.add_edge(make_operand_edge("a", "add_op1", 0));
        g.add_edge(make_operand_edge("b", "add_op1", 1));
        g.add_edge(make_operand_edge("c", "add_op2", 0));
        g.add_edge(make_operand_edge("d", "add_op2", 1));
        g.add_edge(make_assignment_edge("add_op1", "dest1"));
        g.add_edge(make_assignment_edge("add_op2", "dest2"));

        // Two or operations.
        g.add_node(make_operation_node("or_op1", "|", "and"));
        g.add_node(make_operation_node("or_op2", "|", "or"));
        g.add_edge(make_operand_edge("e", "or_op1", 0));
        g.add_edge(make_operand_edge("f", "or_op1", 1));
        g.add_edge(make_operand_edge("g", "or_op2", 0));
        g.add_edge(make_operand_edge("h", "or_op2", 1));
        g.add_edge(make_assignment_edge("or_op1", "dest3"));
        g.add_edge(make_assignment_edge("or_op2", "dest4"));

        // Share adds explicitly
        let add_ids = vec!["add_op1".to_string(), "add_op2".to_string()];
        let mut t = OperationSharingTransform::new(&mut g);
        assert!(t.apply_operation_sharing(&add_ids));

        // Share ors explicitly
        let or_ids = vec!["or_op1".to_string(), "or_op2".to_string()];
        let mut t2 = OperationSharingTransform::new(&mut g);
        assert!(t2.apply_operation_sharing(&or_ids));

        // Both shared ops should exist.
        assert!(
            g.nodes.contains_key("shared_+_op"),
            "shared add must exist"
        );
        assert!(
            g.nodes.contains_key("shared_|_op"),
            "shared or must exist"
        );

        // All originals should be removed.
        assert!(!g.nodes.contains_key("add_op1"));
        assert!(!g.nodes.contains_key("add_op2"));
        assert!(!g.nodes.contains_key("or_op1"));
        assert!(!g.nodes.contains_key("or_op2"));

        // Check the two shared ops have the correct operation field.
        assert_eq!(
            g.nodes.get("shared_+_op").unwrap().data.get("operation").unwrap(),
            &json!("+")
        );
        assert_eq!(
            g.nodes.get("shared_|_op").unwrap().data.get("operation").unwrap(),
            &json!("|")
        );
    }

    // -----------------------------------------------------------------------
    // 6. test_result_routing
    // -----------------------------------------------------------------------
    #[test]
    fn test_result_routing() {
        let mut g = make_sharing_graph();

        let selected = vec!["add_op1".to_string(), "add_op2".to_string()];
        let mut t = OperationSharingTransform::new(&mut g);
        t.apply_operation_sharing(&selected);

        // shared_+_op → dest1 should be gated by add_enable.
        let to_dest1: Vec<&Edge> = g
            .edges
            .values()
            .filter(|e| e.source == "shared_+_op" && e.target == "dest1")
            .collect();
        assert_eq!(to_dest1.len(), 1);
        assert_eq!(
            to_dest1[0].data.get("gated_by").unwrap(),
            &json!("add_enable"),
            "dest1 result gated by add_enable"
        );
        assert_eq!(
            to_dest1[0].data.get("original_operation").unwrap(),
            &json!("add_op1"),
            "original_operation tracks source"
        );

        // shared_+_op → dest2 should be gated by sub_enable.
        let to_dest2: Vec<&Edge> = g
            .edges
            .values()
            .filter(|e| e.source == "shared_+_op" && e.target == "dest2")
            .collect();
        assert_eq!(to_dest2.len(), 1);
        assert_eq!(
            to_dest2[0].data.get("gated_by").unwrap(),
            &json!("sub_enable"),
            "dest2 result gated by sub_enable"
        );
        assert_eq!(
            to_dest2[0].data.get("original_operation").unwrap(),
            &json!("add_op2"),
            "original_operation tracks source"
        );
    }

    // -----------------------------------------------------------------------
    // 7. test_instruction_enable_names
    // -----------------------------------------------------------------------
    #[test]
    fn test_instruction_enable_names() {
        let mut g = ResourceGraph::new();

        // Node with instruction field.
        g.add_node(make_operation_node("op_add", "+", "add"));
        // Node with instruction field "slli".
        g.add_node(make_operation_node("op_slli", "+", "slli"));
        // Node without instruction field (falls back to "shared").
        let mut no_instr = Node::with_defaults(Some("op_no_instr".to_string()));
        no_instr.data.insert("type".to_string(), json!("operation"));
        g.add_node(no_instr);

        let t = OperationSharingTransform::new(&mut g);

        assert_eq!(t._get_instruction_enable("op_add"), "add_enable");
        assert_eq!(t._get_instruction_enable("op_slli"), "slli_enable");
        assert_eq!(
            t._get_instruction_enable("op_no_instr"),
            "default_enable",
            "Missing instruction field → default_enable"
        );
        assert_eq!(
            t._get_instruction_enable("nonexistent_node"),
            "default_enable",
            "Nonexistent node → default_enable"
        );
    }

    // -----------------------------------------------------------------------
    // 8. test_operand_analysis_incompatible_count
    // -----------------------------------------------------------------------
    #[test]
    fn test_operand_analysis_incompatible_count() {
        // op1 has 2 operands, op2 has 1 operand → can_share = false.
        let mut g = ResourceGraph::new();
        g.add_node(make_var_node("a"));
        g.add_node(make_var_node("b"));
        g.add_node(make_var_node("c"));
        g.add_node(make_operation_node("op1", "+", "add"));
        g.add_node(make_operation_node("op2", "+", "sub"));

        // op1: 2 operands.
        g.add_edge(make_operand_edge("a", "op1", 0));
        g.add_edge(make_operand_edge("b", "op1", 1));

        // op2: only 1 operand.
        g.add_edge(make_operand_edge("c", "op2", 0));

        let t = OperationSharingTransform::new(&mut g);

        let analysis = t._analyze_operands(&["op1".to_string(), "op2".to_string()]);
        assert!(analysis.is_some());
        let a = analysis.unwrap();
        assert!(!a.can_share, "Different operand counts → cannot share");
    }

    // -----------------------------------------------------------------------
    // 9. test_standalone_function
    // -----------------------------------------------------------------------
    #[test]
    fn test_standalone_function() {
        let mut g = make_sharing_graph();

        let selected = vec!["add_op1".to_string(), "add_op2".to_string()];
        let result = apply_operation_sharing(&mut g, &selected, SharingMode::Spatial);
        assert!(result, "Standalone function should return true");

        // Verify the sharing happened via the standalone API.
        assert!(g.nodes.contains_key("shared_+_op"));
        assert!(!g.nodes.contains_key("add_op1"));
        assert!(!g.nodes.contains_key("add_op2"));

        // Verify result edges exist.
        let result_edges: Vec<&Edge> = g
            .edges
            .values()
            .filter(|e| e.source == "shared_+_op" && e.data.get("type") == Some(&json!("assignment")))
            .collect();
        assert_eq!(result_edges.len(), 2, "Two result edges from shared op");
    }

    // -----------------------------------------------------------------------
    // 10. test_original_nodes_removed
    // -----------------------------------------------------------------------
    #[test]
    fn test_original_nodes_removed() {
        let mut g = make_sharing_graph();

        // Verify originals exist before.
        assert!(g.nodes.contains_key("add_op1"));
        assert!(g.nodes.contains_key("add_op2"));

        // Count edges connected to originals before sharing.
        let edges_to_op1_before: usize = g
            .edges
            .values()
            .filter(|e| e.source == "add_op1" || e.target == "add_op1")
            .count();
        assert!(
            edges_to_op1_before > 0,
            "add_op1 should have edges before sharing"
        );

        let selected = vec!["add_op1".to_string(), "add_op2".to_string()];
        apply_operation_sharing(&mut g, &selected, SharingMode::Spatial);

        // Original nodes gone.
        assert!(
            !g.nodes.contains_key("add_op1"),
            "add_op1 removed"
        );
        assert!(
            !g.nodes.contains_key("add_op2"),
            "add_op2 removed"
        );

        // No edges should reference the removed nodes.
        let edges_referencing_originals: Vec<&Edge> = g
            .edges
            .values()
            .filter(|e| {
                e.source == "add_op1"
                    || e.target == "add_op1"
                    || e.source == "add_op2"
                    || e.target == "add_op2"
            })
            .collect();
        assert!(
            edges_referencing_originals.is_empty(),
            "No edges should reference removed operation nodes, but found: {:?}",
            edges_referencing_originals
                .iter()
                .map(|e| format!("{} -> {}", e.source, e.target))
                .collect::<Vec<_>>()
        );

        // The source and destination nodes should still exist.
        for name in &["a", "b", "c", "d", "dest1", "dest2"] {
            assert!(
                g.nodes.contains_key(*name),
                "{} should still be in the graph",
                name
            );
        }
    }

    // -----------------------------------------------------------------------
    // 11. test_mutual_exclusivity_rejection
    // -----------------------------------------------------------------------
    #[test]
    fn test_mutual_exclusivity_rejection() {
        // Two operations from the SAME instruction → not mutually exclusive.
        let mut g = ResourceGraph::new();

        g.add_node(make_var_node("a"));
        g.add_node(make_var_node("b"));
        g.add_node(make_var_node("c"));
        g.add_node(make_var_node("d"));
        g.add_node(make_var_node("dest1"));
        g.add_node(make_var_node("dest2"));

        // Both operations belong to the same instruction "add".
        g.add_node(make_operation_node("add_op1", "+", "add"));
        g.add_node(make_operation_node("add_op2", "+", "add"));

        g.add_edge(make_operand_edge("a", "add_op1", 0));
        g.add_edge(make_operand_edge("b", "add_op1", 1));
        g.add_edge(make_operand_edge("c", "add_op2", 0));
        g.add_edge(make_operand_edge("d", "add_op2", 1));
        g.add_edge(make_assignment_edge("add_op1", "dest1"));
        g.add_edge(make_assignment_edge("add_op2", "dest2"));

        let selected = vec!["add_op1".to_string(), "add_op2".to_string()];
        let mut t = OperationSharingTransform::new(&mut g);
        let result = t.apply_operation_sharing(&selected);

        assert!(
            !result,
            "Should reject sharing operations from the same instruction"
        );

        // Original nodes should still exist (nothing was changed).
        assert!(g.nodes.contains_key("add_op1"));
        assert!(g.nodes.contains_key("add_op2"));
    }

    // -----------------------------------------------------------------------
    // 12. test_mutual_exclusivity_shared_instruction_rejection
    // -----------------------------------------------------------------------
    #[test]
    fn test_mutual_exclusivity_shared_instruction_rejection() {
        // An operation with instruction="shared" has unknown exclusivity.
        let mut g = ResourceGraph::new();

        g.add_node(make_var_node("a"));
        g.add_node(make_var_node("b"));
        g.add_node(make_var_node("c"));
        g.add_node(make_var_node("d"));
        g.add_node(make_var_node("dest1"));
        g.add_node(make_var_node("dest2"));

        g.add_node(make_operation_node("add_op1", "+", "add"));
        g.add_node(make_operation_node("add_op2", "+", "shared"));

        g.add_edge(make_operand_edge("a", "add_op1", 0));
        g.add_edge(make_operand_edge("b", "add_op1", 1));
        g.add_edge(make_operand_edge("c", "add_op2", 0));
        g.add_edge(make_operand_edge("d", "add_op2", 1));
        g.add_edge(make_assignment_edge("add_op1", "dest1"));
        g.add_edge(make_assignment_edge("add_op2", "dest2"));

        let selected = vec!["add_op1".to_string(), "add_op2".to_string()];
        let mut t = OperationSharingTransform::new(&mut g);
        let result = t.apply_operation_sharing(&selected);

        assert!(
            !result,
            "Should reject sharing when an operation has unknown instruction set"
        );
    }

    // ===================================================================== //
    //  Temporal sharing tests
    // ===================================================================== //

    /// Helper: build a graph for temporal sharing tests (two add operations
    /// with operands and destinations, no instruction enables needed).
    fn make_temporal_sharing_graph() -> ResourceGraph {
        let mut graph = ResourceGraph::new();

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

        let mut add1 = Node::with_defaults(Some("add1".to_string()));
        add1.data.insert("type".to_string(), json!("operation"));
        add1.data.insert("operator".to_string(), json!("+"));
        add1.data.insert("display_name".to_string(), json!("add1"));
        add1.data.insert("bit_width".to_string(), json!(32));
        graph.add_node(add1);

        let mut dest1 = Node::with_defaults(Some("dest1".to_string()));
        dest1.data.insert("type".to_string(), json!("var"));
        dest1.data.insert("name".to_string(), json!("dest1"));
        dest1.data.insert("bit_width".to_string(), json!(32));
        dest1.is_arch_state = true;
        graph.add_node(dest1);

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

        let mut add2 = Node::with_defaults(Some("add2".to_string()));
        add2.data.insert("type".to_string(), json!("operation"));
        add2.data.insert("operator".to_string(), json!("+"));
        add2.data.insert("display_name".to_string(), json!("add2"));
        add2.data.insert("bit_width".to_string(), json!(32));
        graph.add_node(add2);

        let mut dest2 = Node::with_defaults(Some("dest2".to_string()));
        dest2.data.insert("type".to_string(), json!("var"));
        dest2.data.insert("name".to_string(), json!("dest2"));
        dest2.data.insert("bit_width".to_string(), json!(32));
        dest2.is_arch_state = true;
        graph.add_node(dest2);

        let mut e1_data: HashMap<String, Value> = HashMap::new();
        e1_data.insert("type".to_string(), json!("operand"));
        graph.add_edge(Edge::new(
            "src_a".to_string(), "add1".to_string(),
            Some("e_src_a_add1".to_string()), Some(e1_data),
        ));

        let mut e2_data: HashMap<String, Value> = HashMap::new();
        e2_data.insert("type".to_string(), json!("operand"));
        graph.add_edge(Edge::new(
            "src_b".to_string(), "add1".to_string(),
            Some("e_src_b_add1".to_string()), Some(e2_data),
        ));

        let mut e3_data: HashMap<String, Value> = HashMap::new();
        e3_data.insert("type".to_string(), json!("assignment"));
        graph.add_edge(Edge::new(
            "add1".to_string(), "dest1".to_string(),
            Some("e_add1_dest1".to_string()), Some(e3_data),
        ));

        let mut e4_data: HashMap<String, Value> = HashMap::new();
        e4_data.insert("type".to_string(), json!("operand"));
        graph.add_edge(Edge::new(
            "src_c".to_string(), "add2".to_string(),
            Some("e_src_c_add2".to_string()), Some(e4_data),
        ));

        let mut e5_data: HashMap<String, Value> = HashMap::new();
        e5_data.insert("type".to_string(), json!("operand"));
        graph.add_edge(Edge::new(
            "src_d".to_string(), "add2".to_string(),
            Some("e_src_d_add2".to_string()), Some(e5_data),
        ));

        let mut e6_data: HashMap<String, Value> = HashMap::new();
        e6_data.insert("type".to_string(), json!("assignment"));
        graph.add_edge(Edge::new(
            "add2".to_string(), "dest2".to_string(),
            Some("e_add2_dest2".to_string()), Some(e6_data),
        ));

        graph
    }

    // -----------------------------------------------------------------------
    // 13. test_temporal_sharing_creates_counter
    // -----------------------------------------------------------------------
    #[test]
    fn test_temporal_sharing_creates_counter() {
        let mut graph = make_temporal_sharing_graph();
        let selected = vec!["add1".to_string(), "add2".to_string()];
        let success = apply_operation_sharing(&mut graph, &selected, SharingMode::Temporal);
        assert!(success, "Temporal sharing should succeed");

        // Counter should exist.
        assert!(
            graph.nodes.contains_key("uarch_cycle_counter"),
            "Counter node must be created"
        );
        let counter = &graph.nodes["uarch_cycle_counter"];
        assert_eq!(
            counter.data.get("type").and_then(|v| v.as_str()),
            Some("uarch_counter")
        );
        assert_eq!(
            counter.data.get("max_value").and_then(|v| v.as_i64()),
            Some(1),
            "max_value should be num_sharers - 1 = 1"
        );
    }

    // -----------------------------------------------------------------------
    // 14. test_temporal_sharing_marks_resources
    // -----------------------------------------------------------------------
    #[test]
    fn test_temporal_sharing_marks_resources() {
        let mut graph = make_temporal_sharing_graph();
        let selected = vec!["add1".to_string(), "add2".to_string()];
        apply_operation_sharing(&mut graph, &selected, SharingMode::Temporal);

        // Both operations should be marked as shared with time slots.
        assert_eq!(
            graph.nodes["add1"]
                .data
                .get("shared_resource")
                .and_then(|v| v.as_bool()),
            Some(true)
        );
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
    }

    // -----------------------------------------------------------------------
    // 15. test_temporal_sharing_pipeline_registers
    // -----------------------------------------------------------------------
    #[test]
    fn test_temporal_sharing_pipeline_registers() {
        let mut graph = make_temporal_sharing_graph();
        let selected = vec!["add1".to_string(), "add2".to_string()];
        apply_operation_sharing(&mut graph, &selected, SharingMode::Temporal);

        // Input pipeline registers for time slot 0.
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

        // Input pipeline registers for time slot 1.
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
    }

    // -----------------------------------------------------------------------
    // 16. test_temporal_sharing_control_edges
    // -----------------------------------------------------------------------
    #[test]
    fn test_temporal_sharing_control_edges() {
        let mut graph = make_temporal_sharing_graph();
        let selected = vec!["add1".to_string(), "add2".to_string()];
        apply_operation_sharing(&mut graph, &selected, SharingMode::Temporal);

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
    // 17. test_temporal_extract_time_slot
    // -----------------------------------------------------------------------
    #[test]
    fn test_extract_time_slot() {
        assert_eq!(
            OperationSharingTransform::extract_time_slot_from_name("foo_t0_reg"),
            Some(0)
        );
        assert_eq!(
            OperationSharingTransform::extract_time_slot_from_name("bar_t2_reg"),
            Some(2)
        );
        assert_eq!(
            OperationSharingTransform::extract_time_slot_from_name("baz_result_t3_reg"),
            Some(3)
        );
        assert_eq!(
            OperationSharingTransform::extract_time_slot_from_name("no_slot_here"),
            None
        );
        assert_eq!(
            OperationSharingTransform::extract_time_slot_from_name("a_type_node"),
            None
        );
    }

    // -----------------------------------------------------------------------
    // 18. test_temporal_get_node_width
    // -----------------------------------------------------------------------
    #[test]
    fn test_get_node_width() {
        let mut graph = ResourceGraph::new();

        let mut n1 = Node::with_defaults(Some("n1".to_string()));
        n1.data.insert("bit_width".to_string(), json!(16));
        graph.add_node(n1);

        let mut n2 = Node::with_defaults(Some("n2".to_string()));
        n2.data.insert("width".to_string(), json!(8));
        graph.add_node(n2);

        let n3 = Node::with_defaults(Some("n3".to_string()));
        graph.add_node(n3);

        let transform = OperationSharingTransform::new(&mut graph);
        assert_eq!(transform._get_node_width("n1"), 16);
        assert_eq!(transform._get_node_width("n2"), 8);
        assert_eq!(transform._get_node_width("n3"), 32, "Fallback to 32");
        assert_eq!(transform._get_node_width("nonexistent"), 32);
    }

    // -----------------------------------------------------------------------
    // 19. test_temporal_standalone_function
    // -----------------------------------------------------------------------
    #[test]
    fn test_temporal_standalone() {
        let mut graph = make_temporal_sharing_graph();
        let selected = vec!["add1".to_string(), "add2".to_string()];
        let success = apply_operation_sharing(&mut graph, &selected, SharingMode::Temporal);
        assert!(success, "Temporal standalone should succeed");
        assert!(graph.nodes.contains_key("uarch_cycle_counter"));
        assert_eq!(
            graph.nodes["add1"]
                .data
                .get("shared_resource")
                .and_then(|v| v.as_bool()),
            Some(true)
        );
    }

    // -----------------------------------------------------------------------
    // 20. test_transformation_summary
    // -----------------------------------------------------------------------
    #[test]
    fn test_transformation_summary() {
        let mut graph = make_temporal_sharing_graph();
        let mut transform = OperationSharingTransform::with_mode(&mut graph, SharingMode::Temporal);

        // Before sharing — no resources.
        let empty_summary = transform.get_transformation_summary();
        assert!(
            empty_summary.contains("No shared resources"),
            "Summary before sharing should mention no shared resources"
        );

        // After sharing.
        let selected = vec!["add1".to_string(), "add2".to_string()];
        let _success = transform.apply_operation_sharing(&selected);

        let summary = transform.get_transformation_summary();
        assert!(
            summary.contains("operation_+"),
            "Summary should mention the resource key"
        );
        assert!(
            summary.contains("Temporal"),
            "Summary should mention the mode"
        );
    }
}
