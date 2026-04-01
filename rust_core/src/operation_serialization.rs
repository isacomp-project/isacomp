//! Operation serialization optimization for ResourceGraphs.
//!
//! Port of `operation_serialization.py`. Implements algorithms to serialize wide
//! operations into narrower operations over multiple cycles, trading latency for area.

use log::{debug, info};
use serde_json::json;
use std::collections::HashMap;

use crate::resource_graph::{Edge, Node, ResourceGraph};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Convert an identifier to a valid Verilog/VHDL identifier by replacing
/// special characters with underscores and collapsing consecutive underscores.
fn sanitize_identifier(identifier: &str) -> String {
    let mut s = identifier
        .replace('(', "_")
        .replace(')', "_")
        .replace('[', "_")
        .replace(']', "_")
        .replace(',', "_")
        .replace(' ', "_")
        .replace('.', "_")
        .replace('\'', "_")
        .replace('{', "_")
        .replace('}', "_");
    // Collapse consecutive underscores
    while s.contains("__") {
        s = s.replace("__", "_");
    }
    // Strip trailing underscore
    while s.ends_with('_') {
        s.pop();
    }
    s
}

// ---------------------------------------------------------------------------
// SerializationSpec
// ---------------------------------------------------------------------------

/// Specification for operation serialization.
#[derive(Debug, Clone)]
pub struct SerializationSpec {
    /// ID of the operation node to serialize.
    pub operation_id: String,
    /// Width of the serialized (narrow) operation in bits. Must be a power of 2.
    pub granularity_bits: i64,
}

impl SerializationSpec {
    /// Create a new serialization spec.
    ///
    /// Returns `Err` if `granularity_bits` is not a positive power of 2.
    pub fn new(operation_id: &str, granularity_bits: i64) -> Result<Self, String> {
        if granularity_bits <= 0 || (granularity_bits & (granularity_bits - 1)) != 0 {
            return Err(format!(
                "Granularity must be a positive power of 2, got {}",
                granularity_bits
            ));
        }
        Ok(Self {
            operation_id: operation_id.to_string(),
            granularity_bits,
        })
    }
}

impl std::fmt::Display for SerializationSpec {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "Serialize {} to {}-bit granularity",
            self.operation_id, self.granularity_bits
        )
    }
}

// ---------------------------------------------------------------------------
// OperationAnalysis (internal)
// ---------------------------------------------------------------------------

/// Result of analyzing an operation node for serialization feasibility.
#[derive(Debug, Clone)]
struct OperationAnalysis {
    can_serialize: bool,
    reason: Option<String>,
    operator: Option<String>,
    operand_ids: Vec<String>,
    data_width: i64,
    destination_ids: Vec<String>,
}

// ---------------------------------------------------------------------------
// OperationSerializationTransform
// ---------------------------------------------------------------------------

/// Transforms operations to use serialized implementations.
pub struct OperationSerializationTransform<'a> {
    graph: &'a mut ResourceGraph,
}

impl<'a> OperationSerializationTransform<'a> {
    /// Create a new transform over the given graph.
    pub fn new(graph: &'a mut ResourceGraph) -> Self {
        Self { graph }
    }

    /// Apply serialization to a specific operation.
    ///
    /// Returns `true` if the operation was successfully serialized.
    pub fn apply_serialization(&mut self, spec: &SerializationSpec) -> bool {
        info!("Applying serialization: {}", spec);

        // Find the operation to serialize
        let target_node = match self.graph.nodes.get(&spec.operation_id) {
            Some(n) => n,
            None => {
                info!("  Error: Operation {} not found", spec.operation_id);
                return false;
            }
        };

        // Accept both 'operation' and 'wide_operation' types
        let op_type = target_node
            .data
            .get("type")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if op_type != "operation" && op_type != "wide_operation" {
            info!(
                "  Error: Node {} is not an operation (type={})",
                spec.operation_id, op_type
            );
            return false;
        }

        // Analyze the operation
        let analysis = self._analyze_operation(&spec.operation_id);
        if !analysis.can_serialize {
            info!(
                "  Error: Cannot serialize operation: {}",
                analysis.reason.as_deref().unwrap_or("unknown")
            );
            return false;
        }

        let operator = analysis.operator.as_deref().unwrap_or("?");
        let data_width = analysis.data_width;
        info!(
            "  Operation analysis: {} on {}-bit data",
            operator, data_width
        );

        // Calculate serialization parameters
        let num_cycles =
            ((data_width as f64) / (spec.granularity_bits as f64)).ceil() as i64;

        info!(
            "  Serializing {}-bit operation into {} cycles of {}-bit operations",
            data_width, num_cycles, spec.granularity_bits
        );

        // Create serialized implementation
        self._create_serialized_operation(&spec.operation_id, spec, &analysis, num_cycles);

        true
    }

    // -----------------------------------------------------------------------
    // Private helpers
    // -----------------------------------------------------------------------

    /// Analyze an operation to determine if it can be serialized.
    fn _analyze_operation(&self, operation_id: &str) -> OperationAnalysis {
        let node = match self.graph.nodes.get(operation_id) {
            Some(n) => n,
            None => {
                return OperationAnalysis {
                    can_serialize: false,
                    reason: Some("node not found".to_string()),
                    operator: None,
                    operand_ids: Vec::new(),
                    data_width: 0,
                    destination_ids: Vec::new(),
                };
            }
        };

        // Check expression type
        let expr = node.data.get("expression");
        let expr_type = expr
            .and_then(|e| e.get("type"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if expr_type != "binary_op" {
            return OperationAnalysis {
                can_serialize: false,
                reason: Some("not a binary operation".to_string()),
                operator: None,
                operand_ids: Vec::new(),
                data_width: 0,
                destination_ids: Vec::new(),
            };
        }

        let operator = expr
            .and_then(|e| e.get("operator"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        // Only certain operators are serializable
        let serializable_ops = ["+", "-", "|", "&", "^"];
        if !serializable_ops.contains(&operator.as_str()) {
            return OperationAnalysis {
                can_serialize: false,
                reason: Some(format!("operator {} not serializable", operator)),
                operator: Some(operator),
                operand_ids: Vec::new(),
                data_width: 0,
                destination_ids: Vec::new(),
            };
        }

        // Determine operands from incoming edges
        let incoming_edge_ids: Vec<String> = node.incoming_edges.iter().cloned().collect();
        let mut operand_ids = Vec::new();
        for eid in &incoming_edge_ids {
            if let Some(edge) = self.graph.edges.get(eid) {
                let edge_type = edge
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                if edge_type == "operand" {
                    operand_ids.push(edge.source.clone());
                }
            }
        }

        if operand_ids.len() != 2 {
            return OperationAnalysis {
                can_serialize: false,
                reason: Some(format!("expected 2 operands, got {}", operand_ids.len())),
                operator: Some(operator),
                operand_ids,
                data_width: 0,
                destination_ids: Vec::new(),
            };
        }

        // Assume 32-bit operations (could be inferred from operand types)
        let data_width: i64 = 32;

        let destination_ids = self._get_result_destinations(operation_id);

        OperationAnalysis {
            can_serialize: true,
            reason: None,
            operator: Some(operator),
            operand_ids,
            data_width,
            destination_ids,
        }
    }

    /// Get IDs of nodes that receive the operation result via assignment edges.
    fn _get_result_destinations(&self, operation_id: &str) -> Vec<String> {
        let mut destinations = Vec::new();
        if let Some(node) = self.graph.nodes.get(operation_id) {
            let outgoing_ids: Vec<String> = node.outgoing_edges.iter().cloned().collect();
            for eid in &outgoing_ids {
                if let Some(edge) = self.graph.edges.get(eid) {
                    let edge_type = edge
                        .data
                        .get("type")
                        .and_then(|v| v.as_str())
                        .unwrap_or("");
                    if edge_type == "assignment" {
                        destinations.push(edge.target.clone());
                    }
                }
            }
        }
        destinations
    }

    /// Orchestrate creation of the full serialized operation.
    fn _create_serialized_operation(
        &mut self,
        original_id: &str,
        spec: &SerializationSpec,
        analysis: &OperationAnalysis,
        num_cycles: i64,
    ) {
        let operator = analysis.operator.as_deref().unwrap_or("?").to_string();
        let operand_ids = analysis.operand_ids.clone();
        let data_width = analysis.data_width;
        let destination_ids = analysis.destination_ids.clone();
        let final_cycle = num_cycles - 1;

        // Create serialization counter
        let counter_id = self._create_serialization_counter(&spec.operation_id, num_cycles);

        // Create narrow operation unit
        let narrow_op_id = self._create_narrow_operation_unit(spec, &operator);

        // Create temporary storage for partial results
        let partial_storage_id =
            self._create_partial_result_storage(spec, data_width, final_cycle);

        // Create bit slice extraction logic
        let slice_nodes =
            self._create_bit_slice_logic(spec, &operand_ids, data_width);

        // Create mux logic to select which slice to process
        self._create_slice_selection_muxes(
            spec,
            &slice_nodes,
            &narrow_op_id,
            &counter_id,
            num_cycles,
        );

        // Create result accumulation logic
        let completion_id = self._create_result_accumulation(
            spec,
            &narrow_op_id,
            &partial_storage_id,
            &counter_id,
            &destination_ids,
            num_cycles,
        );

        // Create control logic and enable gating
        self._create_serialization_control(
            spec,
            &counter_id,
            num_cycles,
            &completion_id,
            &destination_ids,
        );

        // Update destination nodes: set uarch_time for arch state destinations
        for dest_id in &destination_ids {
            if let Some(dest) = self.graph.nodes.get_mut(dest_id) {
                if dest.is_arch_state {
                    dest.uarch_time = Some(final_cycle);
                    info!("    - Updated {} uarch_time to {}", dest_id, final_cycle);
                }
            }
        }

        // Remove original operation
        self._remove_original_operation(original_id);

        info!("  Created serialized implementation:");
        info!("    - Serialization counter: {}", counter_id);
        info!(
            "    - Narrow {} unit: {} ({}-bit)",
            operator, narrow_op_id, spec.granularity_bits
        );
        info!("    - Partial result storage: {}", partial_storage_id);
        info!("    - Control logic for {} cycles", num_cycles);
        info!("    - Enable/gating logic: {}", completion_id);
    }

    /// Create a counter node for serialization cycles.
    ///
    /// Returns the counter node ID.
    fn _create_serialization_counter(
        &mut self,
        operation_id: &str,
        num_cycles: i64,
    ) -> String {
        let counter_name = format!("{}_serial_counter", operation_id);
        let counter_width = ((num_cycles + 1) as f64).log2().ceil() as i64;

        let mut counter_data = HashMap::new();
        counter_data.insert("type".to_string(), json!("serialization_counter"));
        counter_data.insert("name".to_string(), json!(counter_name));
        counter_data.insert(
            "display_name".to_string(),
            json!(format!("{} serialization counter", operation_id)),
        );
        counter_data.insert("bit_width".to_string(), json!(counter_width));
        counter_data.insert("max_count".to_string(), json!(num_cycles - 1));
        counter_data.insert("operation_id".to_string(), json!(operation_id));

        let mut node = Node::with_defaults(Some(counter_name.clone()));
        node.data = counter_data;
        node.is_uarch_state = true;
        node.uarch_time = Some(0); // Counter starts at cycle 0
        self.graph.add_node(node);

        counter_name
    }

    /// Create a narrow operation unit node.
    ///
    /// Returns the narrow operation unit node ID.
    fn _create_narrow_operation_unit(
        &mut self,
        spec: &SerializationSpec,
        operator: &str,
    ) -> String {
        let unit_name = format!("{}_narrow_{}", spec.operation_id, operator);

        let mut unit_data = HashMap::new();
        unit_data.insert("type".to_string(), json!("narrow_operation_unit"));
        unit_data.insert("name".to_string(), json!(unit_name));
        unit_data.insert(
            "display_name".to_string(),
            json!(format!("{}-bit {} unit", spec.granularity_bits, operator)),
        );
        unit_data.insert("operation".to_string(), json!(operator));
        unit_data.insert("bit_width".to_string(), json!(spec.granularity_bits));
        unit_data.insert(
            "original_operation".to_string(),
            json!(spec.operation_id),
        );

        let mut node = Node::with_defaults(Some(unit_name.clone()));
        node.data = unit_data;
        node.is_uarch_state = true;
        node.uarch_time = Some(0); // Combinational logic, operates every cycle
        self.graph.add_node(node);

        unit_name
    }

    /// Create storage for partial results during serialization.
    ///
    /// Returns the partial result storage node ID.
    fn _create_partial_result_storage(
        &mut self,
        spec: &SerializationSpec,
        data_width: i64,
        final_cycle: i64,
    ) -> String {
        let storage_name = format!("{}_partial_result", spec.operation_id);

        let mut storage_data = HashMap::new();
        storage_data.insert("type".to_string(), json!("partial_result_storage"));
        storage_data.insert("name".to_string(), json!(storage_name));
        storage_data.insert(
            "display_name".to_string(),
            json!(format!("{} partial result", spec.operation_id)),
        );
        storage_data.insert("bit_width".to_string(), json!(data_width));
        storage_data.insert("operation_id".to_string(), json!(spec.operation_id));

        let mut node = Node::with_defaults(Some(storage_name.clone()));
        node.data = storage_data;
        node.is_uarch_state = true;
        node.uarch_time = Some(final_cycle); // Result ready at final cycle
        self.graph.add_node(node);

        storage_name
    }

    /// Create bit slice extraction logic for operands.
    ///
    /// Returns a map from operand name (`"operand_a"`, `"operand_b"`) to a
    /// list of slice node IDs (one per slice).
    fn _create_bit_slice_logic(
        &mut self,
        spec: &SerializationSpec,
        operand_ids: &[String],
        data_width: i64,
    ) -> HashMap<String, Vec<String>> {
        let mut slice_nodes: HashMap<String, Vec<String>> = HashMap::new();
        slice_nodes.insert("operand_a".to_string(), Vec::new());
        slice_nodes.insert("operand_b".to_string(), Vec::new());

        let num_slices =
            ((data_width as f64) / (spec.granularity_bits as f64)).ceil() as i64;

        let operand_names = ["operand_a", "operand_b"];

        for i in 0..num_slices {
            let low_bit = i * spec.granularity_bits;
            let high_bit =
                std::cmp::min((i + 1) * spec.granularity_bits - 1, data_width - 1);

            for (j, operand_name) in operand_names.iter().enumerate() {
                let operand_id = &operand_ids[j];
                let slice_name = format!("{}_{}_slice_{}", spec.operation_id, operand_name, i);

                let mut slice_data = HashMap::new();
                slice_data.insert("type".to_string(), json!("bit_slice_extractor"));
                slice_data.insert("name".to_string(), json!(slice_name));
                slice_data.insert(
                    "display_name".to_string(),
                    json!(format!("{}[{}:{}]", operand_id, high_bit, low_bit)),
                );
                slice_data.insert("source_operand".to_string(), json!(operand_id));
                slice_data.insert("slice_index".to_string(), json!(i));
                slice_data.insert("high_bit".to_string(), json!(high_bit));
                slice_data.insert("low_bit".to_string(), json!(low_bit));
                slice_data.insert(
                    "slice_width".to_string(),
                    json!(high_bit - low_bit + 1),
                );
                slice_data.insert("operation_id".to_string(), json!(spec.operation_id));

                let mut node = Node::with_defaults(Some(slice_name.clone()));
                node.data = slice_data;
                node.is_uarch_state = true;
                self.graph.add_node(node);

                // Connect operand to slice extractor
                let mut edge_data = HashMap::new();
                edge_data.insert("type".to_string(), json!("bit_slice"));
                edge_data.insert("slice_index".to_string(), json!(i));
                let edge = Edge::new(
                    operand_id.clone(),
                    slice_name.clone(),
                    None,
                    Some(edge_data),
                );
                self.graph.add_edge(edge);

                slice_nodes
                    .get_mut(*operand_name)
                    .unwrap()
                    .push(slice_name);
            }
        }

        info!(
            "    - Created {} bit slice extractors for each operand",
            num_slices
        );
        slice_nodes
    }

    /// Create mux logic to select which bit slice to process based on counter value.
    fn _create_slice_selection_muxes(
        &mut self,
        spec: &SerializationSpec,
        slice_nodes: &HashMap<String, Vec<String>>,
        narrow_op_id: &str,
        counter_id: &str,
        num_cycles: i64,
    ) {
        for operand_name in &["operand_a", "operand_b"] {
            let mux_name =
                format!("{}_{}_mux", spec.operation_id, operand_name);

            let mut mux_data = HashMap::new();
            mux_data.insert("type".to_string(), json!("mux"));
            mux_data.insert("name".to_string(), json!(mux_name));
            mux_data.insert(
                "display_name".to_string(),
                json!(format!("{} slice selector", operand_name)),
            );
            mux_data.insert("selector".to_string(), json!(counter_id));
            mux_data.insert("num_inputs".to_string(), json!(num_cycles));
            mux_data.insert("operation_id".to_string(), json!(spec.operation_id));

            let mut mux_node = Node::with_defaults(Some(mux_name.clone()));
            mux_node.data = mux_data;
            mux_node.is_uarch_state = true;
            self.graph.add_node(mux_node);

            // Connect all slices to the mux
            if let Some(slices) = slice_nodes.get(*operand_name) {
                for (i, slice_id) in slices.iter().enumerate() {
                    let mut edge_data = HashMap::new();
                    edge_data.insert("type".to_string(), json!("mux_input"));
                    edge_data.insert("input_index".to_string(), json!(i));
                    let edge = Edge::new(
                        slice_id.clone(),
                        mux_name.clone(),
                        None,
                        Some(edge_data),
                    );
                    self.graph.add_edge(edge);
                }
            }

            // Connect counter to mux as selector
            let mut selector_data = HashMap::new();
            selector_data.insert("type".to_string(), json!("mux_selector"));
            let selector_edge = Edge::new(
                counter_id.to_string(),
                mux_name.clone(),
                None,
                Some(selector_data),
            );
            self.graph.add_edge(selector_edge);

            // Connect mux output to narrow operation
            let position = if *operand_name == "operand_a" {
                "left"
            } else {
                "right"
            };
            let mut op_edge_data = HashMap::new();
            op_edge_data.insert("type".to_string(), json!("operand"));
            op_edge_data.insert("position".to_string(), json!(position));
            let mux_to_op_edge = Edge::new(
                mux_name,
                narrow_op_id.to_string(),
                None,
                Some(op_edge_data),
            );
            self.graph.add_edge(mux_to_op_edge);
        }

        debug!("    - Created slice selection muxes");
    }

    /// Create result accumulation and final assignment logic.
    ///
    /// Returns the completion node ID.
    fn _create_result_accumulation(
        &mut self,
        spec: &SerializationSpec,
        narrow_op_id: &str,
        partial_storage_id: &str,
        counter_id: &str,
        destination_ids: &[String],
        num_cycles: i64,
    ) -> String {
        // Create result accumulator
        let accumulator_name =
            format!("{}_result_accumulator", spec.operation_id);

        let mut accumulator_data = HashMap::new();
        accumulator_data.insert("type".to_string(), json!("result_accumulator"));
        accumulator_data.insert("name".to_string(), json!(accumulator_name));
        accumulator_data.insert(
            "display_name".to_string(),
            json!(format!("{} result accumulator", spec.operation_id)),
        );
        accumulator_data.insert("operation_id".to_string(), json!(spec.operation_id));

        let mut acc_node = Node::with_defaults(Some(accumulator_name.clone()));
        acc_node.data = accumulator_data;
        acc_node.is_uarch_state = true;
        acc_node.uarch_time = Some(0); // Accumulates results every cycle
        self.graph.add_node(acc_node);

        // Connect narrow operation to accumulator
        let mut narrow_edge_data = HashMap::new();
        narrow_edge_data.insert("type".to_string(), json!("partial_result"));
        narrow_edge_data.insert("operation_id".to_string(), json!(spec.operation_id));
        let narrow_edge = Edge::new(
            narrow_op_id.to_string(),
            accumulator_name.clone(),
            None,
            Some(narrow_edge_data),
        );
        self.graph.add_edge(narrow_edge);

        // Connect accumulator to partial storage
        let mut storage_edge_data = HashMap::new();
        storage_edge_data.insert("type".to_string(), json!("accumulation"));
        storage_edge_data.insert("operation_id".to_string(), json!(spec.operation_id));
        let storage_edge = Edge::new(
            accumulator_name.clone(),
            partial_storage_id.to_string(),
            None,
            Some(storage_edge_data),
        );
        self.graph.add_edge(storage_edge);

        // Create completion signal node
        let completion_name = format!("{}_complete", counter_id);
        let mut completion_data = HashMap::new();
        completion_data.insert("type".to_string(), json!("serialization_completion"));
        completion_data.insert("name".to_string(), json!(completion_name));
        completion_data.insert(
            "display_name".to_string(),
            json!(format!("{} serialization complete", spec.operation_id)),
        );
        completion_data.insert("counter_id".to_string(), json!(counter_id));
        completion_data.insert("max_count".to_string(), json!(num_cycles - 1));
        completion_data.insert("operation_id".to_string(), json!(spec.operation_id));

        let mut completion_node =
            Node::with_defaults(Some(completion_name.clone()));
        completion_node.data = completion_data;
        completion_node.is_uarch_state = true;
        completion_node.uarch_time = Some(num_cycles - 1); // Fires at final cycle
        self.graph.add_node(completion_node);

        // Connect counter to completion signal
        let mut completion_edge_data = HashMap::new();
        completion_edge_data.insert("type".to_string(), json!("completion_check"));
        completion_edge_data.insert(
            "condition".to_string(),
            json!(format!("{} == {}", counter_id, num_cycles - 1)),
        );
        let completion_edge = Edge::new(
            counter_id.to_string(),
            completion_name.clone(),
            None,
            Some(completion_edge_data),
        );
        self.graph.add_edge(completion_edge);

        // Connect partial storage to final destinations
        for dest_id in destination_ids {
            let mut final_edge_data = HashMap::new();
            final_edge_data.insert("type".to_string(), json!("serialized_result"));
            final_edge_data.insert("operation_id".to_string(), json!(spec.operation_id));
            let final_edge = Edge::new(
                partial_storage_id.to_string(),
                dest_id.clone(),
                None,
                Some(final_edge_data),
            );
            self.graph.add_edge(final_edge);
        }

        info!("    - Created result accumulation logic");
        completion_name
    }

    /// Create control logic for serialization with proper enable/gating nodes.
    fn _create_serialization_control(
        &mut self,
        spec: &SerializationSpec,
        counter_id: &str,
        num_cycles: i64,
        _completion_id: &str,
        _destination_ids: &[String],
    ) {
        let final_cycle = num_cycles - 1;

        // Use shared ISA gating helper
        let mut gating_helper = ISAStateGatingHelper::new(self.graph);

        // Create enable comparator and gate all ISA writes
        let enable_id = gating_helper.gate_all_isa_writes_for_operation(
            &spec.operation_id,
            counter_id,
            final_cycle,
            "serialization_enable",
        );

        info!("    - Created enable condition: {}", enable_id);
        info!(
            "    - Created enable/gating control (fires when counter == {})",
            final_cycle
        );
    }

    /// Remove the original wide operation and all its connected edges.
    fn _remove_original_operation(&mut self, operation_id: &str) {
        info!("    - Removing original operation: {}", operation_id);

        // Collect all edge IDs connected to this node
        let edge_ids: Vec<String> = if let Some(node) = self.graph.nodes.get(operation_id) {
            node.incoming_edges
                .iter()
                .chain(node.outgoing_edges.iter())
                .cloned()
                .collect()
        } else {
            return;
        };

        // Remove each edge
        for eid in &edge_ids {
            self.graph.remove_edge(eid);
        }

        // Remove the node
        self.graph.nodes.remove(operation_id);
    }
}

// ---------------------------------------------------------------------------
// ISAStateGatingHelper
// ---------------------------------------------------------------------------

/// Helper for creating ISA state write gating logic.
///
/// This provides common functionality for gating ISA state writes to ensure
/// atomicity of multi-cycle operations (serialization, multi-cycle latency,
/// resource sharing).
pub struct ISAStateGatingHelper<'a> {
    graph: &'a mut ResourceGraph,
}

impl<'a> ISAStateGatingHelper<'a> {
    /// Create a new gating helper over the given graph.
    pub fn new(graph: &'a mut ResourceGraph) -> Self {
        Self { graph }
    }

    /// Create an enable comparator that checks if `counter == final_value`.
    ///
    /// Returns the enable node ID.
    pub fn create_enable_comparator(
        &mut self,
        operation_id: &str,
        counter_id: &str,
        final_value: i64,
        enable_type: &str,
    ) -> String {
        let safe_id = sanitize_identifier(operation_id);
        let enable_node_id = format!("{}_enable", safe_id);

        // Create or reuse literal node for the final value
        let literal_id = final_value.to_string();
        if !self.graph.nodes.contains_key(&literal_id) {
            let mut literal_data = HashMap::new();
            literal_data.insert("type".to_string(), json!("literal"));
            literal_data.insert("value".to_string(), json!(final_value));
            literal_data.insert("display_name".to_string(), json!(literal_id));

            let mut literal_node =
                Node::with_defaults(Some(literal_id.clone()));
            literal_node.data = literal_data;
            self.graph.add_node(literal_node);
        }

        // Create enable condition expression (counter == final_value)
        let enable_expr = json!({
            "type": "binary_op",
            "operator": "==",
            "left": {"type": "identifier", "name": counter_id},
            "right": {"type": "literal", "value": final_value}
        });

        let mut enable_data = HashMap::new();
        enable_data.insert("type".to_string(), json!("operation"));
        enable_data.insert("operator".to_string(), json!("=="));
        enable_data.insert(
            "display_name".to_string(),
            json!(format!("{} == {}", counter_id, final_value)),
        );
        enable_data.insert("expression".to_string(), enable_expr);
        enable_data.insert("enable_condition".to_string(), json!(true));
        enable_data.insert(enable_type.to_string(), json!(true));

        let mut enable_node =
            Node::with_defaults(Some(enable_node_id.clone()));
        enable_node.data = enable_data;
        enable_node.uarch_time = Some(final_value); // Enable fires at final cycle
        self.graph.add_node(enable_node);

        // Connect counter to enable node
        let mut counter_edge_data = HashMap::new();
        counter_edge_data.insert("type".to_string(), json!("operand"));
        counter_edge_data.insert("position".to_string(), json!("left"));
        let counter_edge = Edge::new(
            counter_id.to_string(),
            enable_node_id.clone(),
            None,
            Some(counter_edge_data),
        );
        self.graph.add_edge(counter_edge);

        // Connect literal to enable node
        let mut literal_edge_data = HashMap::new();
        literal_edge_data.insert("type".to_string(), json!("operand"));
        literal_edge_data.insert("position".to_string(), json!("right"));
        let literal_edge = Edge::new(
            literal_id,
            enable_node_id.clone(),
            None,
            Some(literal_edge_data),
        );
        self.graph.add_edge(literal_edge);

        enable_node_id
    }

    /// Find all ISA state write nodes in the graph.
    ///
    /// An ISA write is an architectural state node with incoming assignment edges.
    /// Returns a list of node IDs.
    pub fn find_all_isa_writes(&self) -> Vec<String> {
        let mut isa_writes = Vec::new();
        for (node_id, node) in &self.graph.nodes {
            if !node.is_arch_state {
                continue;
            }
            // Check if this node has incoming assignment edges (indicating a write)
            let has_write = node.incoming_edges.iter().any(|eid| {
                self.graph
                    .edges
                    .get(eid)
                    .map(|e| {
                        e.data
                            .get("type")
                            .and_then(|v| v.as_str())
                            == Some("assignment")
                    })
                    .unwrap_or(false)
            });
            if has_write {
                isa_writes.push(node_id.clone());
            }
        }
        isa_writes
    }

    /// Gate ISA state writes with an enable condition.
    pub fn gate_isa_writes(
        &mut self,
        write_ids: &[String],
        enable_id: &str,
        gate_condition_str: &str,
        final_cycle: i64,
    ) {
        // Build the enable expression for metadata
        // We need the counter_id from the enable node's data to build the expression.
        // The enable node's display_name has the form "counter_id == final_value".
        let enable_expr = if let Some(enable_node) = self.graph.nodes.get(enable_id) {
            enable_node
                .data
                .get("expression")
                .cloned()
                .unwrap_or(json!(null))
        } else {
            json!(null)
        };

        for write_id in write_ids {
            // Update uarch_time to final cycle
            if let Some(write_node) = self.graph.nodes.get_mut(write_id) {
                write_node.uarch_time = Some(final_cycle);
                write_node
                    .data
                    .insert("enable".to_string(), enable_expr.clone());
                write_node.data.insert(
                    "gate_condition".to_string(),
                    json!(gate_condition_str),
                );
            }

            // Find and mark assignment edges as gated
            let incoming_ids: Vec<String> = self
                .graph
                .nodes
                .get(write_id)
                .map(|n| n.incoming_edges.iter().cloned().collect())
                .unwrap_or_default();

            for eid in &incoming_ids {
                if let Some(edge) = self.graph.edges.get_mut(eid) {
                    let is_assignment = edge
                        .data
                        .get("type")
                        .and_then(|v| v.as_str())
                        == Some("assignment");
                    if is_assignment {
                        edge.data.insert("gated".to_string(), json!(true));
                        edge.data.insert(
                            "gate_condition".to_string(),
                            json!(gate_condition_str),
                        );
                        edge.data
                            .insert("enable".to_string(), enable_expr.clone());
                    }
                }
            }

            // Create write_enable edge from enable node to ISA write node
            let mut we_data = HashMap::new();
            we_data.insert("type".to_string(), json!("write_enable"));
            let we_edge = Edge::new(
                enable_id.to_string(),
                write_id.clone(),
                None,
                Some(we_data),
            );
            self.graph.add_edge(we_edge);
        }
    }

    /// Complete workflow: create enable comparator and gate all ISA writes.
    ///
    /// Returns the enable node ID.
    pub fn gate_all_isa_writes_for_operation(
        &mut self,
        operation_id: &str,
        counter_id: &str,
        final_cycle: i64,
        enable_type: &str,
    ) -> String {
        // Create enable comparator
        let enable_id = self.create_enable_comparator(
            operation_id,
            counter_id,
            final_cycle,
            enable_type,
        );

        // Find all ISA writes
        let isa_writes = self.find_all_isa_writes();

        if isa_writes.is_empty() {
            info!("    - No ISA state writes to gate");
            return enable_id;
        }

        info!(
            "    - Gating all {} ISA state writes for atomicity:",
            isa_writes.len()
        );

        // Create gate condition string
        let gate_condition_str =
            format!("{} == {}", counter_id, final_cycle);

        // Gate all ISA writes
        self.gate_isa_writes(&isa_writes, &enable_id, &gate_condition_str, final_cycle);

        for write_id in &isa_writes {
            info!(
                "      - Gated ISA write: {} (cycle {})",
                write_id, final_cycle
            );
        }

        enable_id
    }
}

// ---------------------------------------------------------------------------
// Standalone entry point
// ---------------------------------------------------------------------------

/// Apply operation serialization to a ResourceGraph.
///
/// Returns `true` if any operations were serialized, `false` otherwise.
pub fn apply_operation_serialization(
    graph: &mut ResourceGraph,
    specs: &[SerializationSpec],
) -> bool {
    let mut serialized_any = false;

    for spec in specs {
        // We need to re-borrow graph each iteration because
        // OperationSerializationTransform holds a &mut reference.
        let mut transform = OperationSerializationTransform::new(graph);
        if transform.apply_serialization(spec) {
            serialized_any = true;
        }
    }

    // Re-infer uarch_time to propagate timing changes throughout the graph
    if serialized_any {
        info!("Re-inferring uarch_time after serialization...");
        graph.infer_uarch_time(true);
        info!("Uarch_time inference complete");
    }

    serialized_any
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    /// Helper: build a minimal graph with one binary operation node and two
    /// operands, plus an arch-state destination.
    fn build_test_graph() -> ResourceGraph {
        let mut graph = ResourceGraph::new();

        // Operand A
        let mut op_a = Node::with_defaults(Some("r1".to_string()));
        op_a.is_arch_state = true;
        op_a.uarch_time = Some(0);
        graph.add_node(op_a);

        // Operand B
        let mut op_b = Node::with_defaults(Some("r2".to_string()));
        op_b.is_arch_state = true;
        op_b.uarch_time = Some(0);
        graph.add_node(op_b);

        // Operation node
        let mut op_data = HashMap::new();
        op_data.insert("type".to_string(), json!("operation"));
        op_data.insert(
            "expression".to_string(),
            json!({
                "type": "binary_op",
                "operator": "+",
                "left": {"type": "identifier", "name": "r1"},
                "right": {"type": "identifier", "name": "r2"}
            }),
        );
        let mut op_node = Node::with_defaults(Some("(r1 + r2)".to_string()));
        op_node.data = op_data;
        graph.add_node(op_node);

        // Destination
        let mut dest = Node::with_defaults(Some("r3".to_string()));
        dest.is_arch_state = true;
        graph.add_node(dest);

        // Operand edges
        let mut e1_data = HashMap::new();
        e1_data.insert("type".to_string(), json!("operand"));
        let e1 = Edge::new(
            "r1".to_string(),
            "(r1 + r2)".to_string(),
            None,
            Some(e1_data),
        );
        graph.add_edge(e1);

        let mut e2_data = HashMap::new();
        e2_data.insert("type".to_string(), json!("operand"));
        let e2 = Edge::new(
            "r2".to_string(),
            "(r1 + r2)".to_string(),
            None,
            Some(e2_data),
        );
        graph.add_edge(e2);

        // Assignment edge
        let mut ea_data = HashMap::new();
        ea_data.insert("type".to_string(), json!("assignment"));
        let ea = Edge::new(
            "(r1 + r2)".to_string(),
            "r3".to_string(),
            None,
            Some(ea_data),
        );
        graph.add_edge(ea);

        graph
    }

    #[test]
    fn test_serialization_spec_valid() {
        let spec = SerializationSpec::new("(r1 + r2)", 8);
        assert!(spec.is_ok());
        let spec = spec.unwrap();
        assert_eq!(spec.operation_id, "(r1 + r2)");
        assert_eq!(spec.granularity_bits, 8);
    }

    #[test]
    fn test_serialization_spec_invalid() {
        assert!(SerializationSpec::new("op", 3).is_err());
        assert!(SerializationSpec::new("op", 0).is_err());
        assert!(SerializationSpec::new("op", -1).is_err());
    }

    #[test]
    fn test_analyze_operation() {
        let graph = build_test_graph();
        let transform = OperationSerializationTransform {
            graph: &mut { graph },
        };
        let analysis = transform._analyze_operation("(r1 + r2)");
        assert!(analysis.can_serialize);
        assert_eq!(analysis.operator.as_deref(), Some("+"));
        assert_eq!(analysis.operand_ids.len(), 2);
        assert_eq!(analysis.data_width, 32);
        assert_eq!(analysis.destination_ids, vec!["r3"]);
    }

    #[test]
    fn test_apply_serialization() {
        let mut graph = build_test_graph();
        let spec = SerializationSpec::new("(r1 + r2)", 8).unwrap();
        let mut transform = OperationSerializationTransform::new(&mut graph);
        let result = transform.apply_serialization(&spec);
        assert!(result);

        // Original operation should be removed
        assert!(!graph.nodes.contains_key("(r1 + r2)"));

        // Counter, narrow op, partial result, completion should exist
        assert!(graph.nodes.contains_key("(r1 + r2)_serial_counter"));
        assert!(graph.nodes.contains_key("(r1 + r2)_narrow_+"));
        assert!(graph.nodes.contains_key("(r1 + r2)_partial_result"));
        assert!(graph
            .nodes
            .contains_key("(r1 + r2)_serial_counter_complete"));

        // Operand slices should exist (32/8 = 4 slices * 2 operands = 8 slice nodes)
        assert!(graph
            .nodes
            .contains_key("(r1 + r2)_operand_a_slice_0"));
        assert!(graph
            .nodes
            .contains_key("(r1 + r2)_operand_b_slice_3"));

        // Muxes should exist
        assert!(graph.nodes.contains_key("(r1 + r2)_operand_a_mux"));
        assert!(graph.nodes.contains_key("(r1 + r2)_operand_b_mux"));
    }

    #[test]
    fn test_apply_serialization_missing_node() {
        let mut graph = build_test_graph();
        let spec = SerializationSpec::new("nonexistent", 8).unwrap();
        let mut transform = OperationSerializationTransform::new(&mut graph);
        assert!(!transform.apply_serialization(&spec));
    }

    #[test]
    fn test_apply_operation_serialization_standalone() {
        let mut graph = build_test_graph();
        let specs = vec![SerializationSpec::new("(r1 + r2)", 8).unwrap()];
        let result = apply_operation_serialization(&mut graph, &specs);
        assert!(result);
        // The original operation should be gone
        assert!(!graph.nodes.contains_key("(r1 + r2)"));
    }

    #[test]
    fn test_isa_state_gating_find_writes() {
        let mut graph = build_test_graph();
        let helper = ISAStateGatingHelper::new(&mut graph);
        let writes = helper.find_all_isa_writes();
        // r3 has an incoming assignment edge and is_arch_state
        assert!(writes.contains(&"r3".to_string()));
    }

    #[test]
    fn test_sanitize_identifier() {
        assert_eq!(sanitize_identifier("(r1 + r2)"), "_r1_+_r2");
        assert_eq!(sanitize_identifier("foo[3:0]"), "foo_3:0");
        assert_eq!(sanitize_identifier("a__b___c"), "a_b_c");
    }

    #[test]
    fn test_serialization_creates_counter() {
        let mut graph = build_test_graph();
        let spec = SerializationSpec::new("(r1 + r2)", 8).unwrap();
        let mut transform = OperationSerializationTransform::new(&mut graph);
        let result = transform.apply_serialization(&spec);
        assert!(result);

        let counter = graph.nodes.get("(r1 + r2)_serial_counter").unwrap();
        // type should be serialization_counter
        assert_eq!(
            counter.data.get("type").and_then(|v| v.as_str()),
            Some("serialization_counter")
        );
        // 32-bit / 8-bit = 4 cycles, ceil_log2(4+1) = 3 bits
        let bit_width = counter.data.get("bit_width").and_then(|v| v.as_i64()).unwrap();
        let num_cycles: i64 = 4;
        let expected_width = ((num_cycles + 1) as f64).log2().ceil() as i64;
        assert_eq!(bit_width, expected_width, "Counter bit_width should match ceil_log2(num_cycles+1)");
        // max_count = num_cycles - 1 = 3
        assert_eq!(
            counter.data.get("max_count").and_then(|v| v.as_i64()),
            Some(3),
            "Counter max_count should be num_cycles - 1"
        );
    }

    #[test]
    fn test_serialization_creates_narrow_unit() {
        let mut graph = build_test_graph();
        let spec = SerializationSpec::new("(r1 + r2)", 8).unwrap();
        let mut transform = OperationSerializationTransform::new(&mut graph);
        let result = transform.apply_serialization(&spec);
        assert!(result);

        let narrow_op = graph.nodes.get("(r1 + r2)_narrow_+").unwrap();
        // Operator should be "+"
        assert_eq!(
            narrow_op.data.get("operation").and_then(|v| v.as_str()),
            Some("+"),
            "Narrow operation should have correct operator"
        );
        // bit_width should equal granularity (8)
        assert_eq!(
            narrow_op.data.get("bit_width").and_then(|v| v.as_i64()),
            Some(8),
            "Narrow operation bit_width should equal granularity"
        );
    }

    #[test]
    fn test_serialization_creates_bit_slices() {
        let mut graph = build_test_graph();
        let spec = SerializationSpec::new("(r1 + r2)", 8).unwrap();
        let mut transform = OperationSerializationTransform::new(&mut graph);
        let result = transform.apply_serialization(&spec);
        assert!(result);

        // 32-bit / 8-bit = 4 slices per operand, 2 operands = 8 total bit_slice_extractor nodes
        let num_slices = 4;
        let mut slice_count = 0;
        for (_id, node) in &graph.nodes {
            if node.data.get("type").and_then(|v| v.as_str()) == Some("bit_slice_extractor") {
                slice_count += 1;
            }
        }
        assert_eq!(
            slice_count,
            num_slices * 2,
            "Should have 2 * num_slices bit_slice_extractor nodes"
        );
    }

    #[test]
    fn test_serialization_creates_muxes() {
        let mut graph = build_test_graph();
        let spec = SerializationSpec::new("(r1 + r2)", 8).unwrap();
        let mut transform = OperationSerializationTransform::new(&mut graph);
        let result = transform.apply_serialization(&spec);
        assert!(result);

        // 2 mux nodes should exist (one per operand)
        assert!(
            graph.nodes.contains_key("(r1 + r2)_operand_a_mux"),
            "Operand A mux should exist"
        );
        assert!(
            graph.nodes.contains_key("(r1 + r2)_operand_b_mux"),
            "Operand B mux should exist"
        );

        // Each mux should have edges from slices and from the counter
        for mux_name in &["(r1 + r2)_operand_a_mux", "(r1 + r2)_operand_b_mux"] {
            let mux_node = graph.nodes.get(*mux_name).unwrap();
            let mut has_mux_input = false;
            let mut has_mux_selector = false;
            for eid in &mux_node.incoming_edges {
                if let Some(edge) = graph.edges.get(eid) {
                    let edge_type = edge.data.get("type").and_then(|v| v.as_str());
                    match edge_type {
                        Some("mux_input") => has_mux_input = true,
                        Some("mux_selector") => has_mux_selector = true,
                        _ => {}
                    }
                }
            }
            assert!(has_mux_input, "Mux {} should have mux_input edges", mux_name);
            assert!(has_mux_selector, "Mux {} should have mux_selector edge", mux_name);
        }
    }

    #[test]
    fn test_serialization_removes_original() {
        let mut graph = build_test_graph();
        let spec = SerializationSpec::new("(r1 + r2)", 8).unwrap();
        let mut transform = OperationSerializationTransform::new(&mut graph);
        let result = transform.apply_serialization(&spec);
        assert!(result);

        // Original operation node should be gone
        assert!(
            !graph.nodes.contains_key("(r1 + r2)"),
            "Original operation node should be removed after serialization"
        );
    }

    #[test]
    fn test_serialization_result_accumulation() {
        let mut graph = build_test_graph();
        let spec = SerializationSpec::new("(r1 + r2)", 8).unwrap();
        let mut transform = OperationSerializationTransform::new(&mut graph);
        let result = transform.apply_serialization(&spec);
        assert!(result);

        // result_accumulator and completion nodes should exist
        assert!(
            graph.nodes.contains_key("(r1 + r2)_result_accumulator"),
            "Result accumulator should exist"
        );
        assert!(
            graph.nodes.contains_key("(r1 + r2)_serial_counter_complete"),
            "Completion node should exist"
        );

        // partial_result_storage should be connected to destination (r3)
        let partial = graph.nodes.get("(r1 + r2)_partial_result").unwrap();
        let mut connected_to_dest = false;
        for eid in &partial.outgoing_edges {
            if let Some(edge) = graph.edges.get(eid) {
                if edge.target == "r3" {
                    connected_to_dest = true;
                }
            }
        }
        assert!(
            connected_to_dest,
            "Partial result storage should be connected to destination r3"
        );
    }

    #[test]
    fn test_non_serializable_operator() {
        let mut graph = ResourceGraph::new();

        // Operand A
        let mut op_a = Node::with_defaults(Some("a".to_string()));
        op_a.is_arch_state = true;
        op_a.uarch_time = Some(0);
        graph.add_node(op_a);

        // Operand B
        let mut op_b = Node::with_defaults(Some("b".to_string()));
        op_b.is_arch_state = true;
        op_b.uarch_time = Some(0);
        graph.add_node(op_b);

        // Operation node with "==" operator (not serializable)
        let mut op_data = HashMap::new();
        op_data.insert("type".to_string(), json!("operation"));
        op_data.insert(
            "expression".to_string(),
            json!({
                "type": "binary_op",
                "operator": "==",
                "left": {"type": "identifier", "name": "a"},
                "right": {"type": "identifier", "name": "b"}
            }),
        );
        let mut op_node = Node::with_defaults(Some("(a == b)".to_string()));
        op_node.data = op_data;
        graph.add_node(op_node);

        // Operand edges
        let mut e1_data = HashMap::new();
        e1_data.insert("type".to_string(), json!("operand"));
        graph.add_edge(Edge::new("a".to_string(), "(a == b)".to_string(), None, Some(e1_data)));

        let mut e2_data = HashMap::new();
        e2_data.insert("type".to_string(), json!("operand"));
        graph.add_edge(Edge::new("b".to_string(), "(a == b)".to_string(), None, Some(e2_data)));

        let transform = OperationSerializationTransform {
            graph: &mut graph,
        };
        let analysis = transform._analyze_operation("(a == b)");
        assert!(
            !analysis.can_serialize,
            "Operation with == operator should not be serializable"
        );
    }

    #[test]
    fn test_gating_creates_enable() {
        let mut graph = build_test_graph();

        // First apply serialization to create the counter
        let spec = SerializationSpec::new("(r1 + r2)", 8).unwrap();
        let mut transform = OperationSerializationTransform::new(&mut graph);
        transform.apply_serialization(&spec);

        // The gating logic is created as part of serialization.
        // Check that the enable comparator node exists.
        let safe_id = sanitize_identifier("(r1 + r2)");
        let enable_id = format!("{}_enable", safe_id);
        assert!(
            graph.nodes.contains_key(&enable_id),
            "Enable comparator node should exist: {}",
            enable_id
        );

        let enable_node = graph.nodes.get(&enable_id).unwrap();
        // Should have operator "=="
        assert_eq!(
            enable_node.data.get("operator").and_then(|v| v.as_str()),
            Some("=="),
            "Enable comparator should have == operator"
        );

        // Should have operand edges from counter and literal
        let mut has_counter_operand = false;
        let mut has_literal_operand = false;
        for eid in &enable_node.incoming_edges {
            if let Some(edge) = graph.edges.get(eid) {
                if edge.source == "(r1 + r2)_serial_counter" {
                    has_counter_operand = true;
                }
                // The literal node ID is the final_value as string
                if edge.source == "3" {
                    has_literal_operand = true;
                }
            }
        }
        assert!(has_counter_operand, "Enable should have operand from counter");
        assert!(has_literal_operand, "Enable should have operand from literal (final value)");
    }
}
