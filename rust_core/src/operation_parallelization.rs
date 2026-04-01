//! Operation parallelization optimization for ResourceGraphs.
//!
//! Port of `operation_parallelization.py`. Implements algorithms to detect
//! serialized operations (from `operation_serialization`) and parallelize them
//! back into wide operations, trading area for reduced latency.
//!
//! This is the inverse of operation serialization — it detects serialized
//! narrow operations and combines them into wide parallel operations, enabling
//! flexible design space exploration of area vs. latency trade-offs.

use log::info;
use serde_json::{json, Value};
use std::collections::HashMap;

use crate::resource_graph::{Edge, Node, ResourceGraph};

// ---------------------------------------------------------------------------
// ParallelizationSpec
// ---------------------------------------------------------------------------

/// Specification for operation parallelization.
#[derive(Debug, Clone)]
pub struct ParallelizationSpec {
    /// The original operation ID.
    pub operation_id: String,

    // Analysis results
    /// Number of serialized cycles (determined during analysis).
    pub num_cycles: Option<usize>,
    /// Whether this operation can be parallelized.
    pub can_parallelize: bool,
    /// Reason if parallelization is not possible.
    pub reason: String,

    // Serialization pattern fields
    /// ID of the serialization counter node.
    pub serialization_counter_id: Option<String>,
    /// Width of the narrow (serialized) operation in bits.
    pub narrow_width: Option<i64>,
    /// Width of the wide (parallelized) operation in bits.
    pub wide_width: Option<i64>,
    /// Node ID of the narrow operation unit.
    pub narrow_operation_node_id: Option<String>,
}

impl ParallelizationSpec {
    /// Create a new `ParallelizationSpec` for the given operation.
    pub fn new(operation_id: &str) -> Self {
        Self {
            operation_id: operation_id.to_string(),
            num_cycles: None,
            can_parallelize: false,
            reason: String::new(),
            serialization_counter_id: None,
            narrow_width: None,
            wide_width: None,
            narrow_operation_node_id: None,
        }
    }
}

impl std::fmt::Display for ParallelizationSpec {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        if self.can_parallelize {
            write!(
                f,
                "Parallelize {}: {}x{}-bit -> {}-bit",
                self.operation_id,
                self.num_cycles.unwrap_or(0),
                self.narrow_width.unwrap_or(0),
                self.wide_width.unwrap_or(0),
            )
        } else {
            write!(
                f,
                "Cannot parallelize {}: {}",
                self.operation_id, self.reason
            )
        }
    }
}

// ---------------------------------------------------------------------------
// OperationParallelizationTransform
// ---------------------------------------------------------------------------

/// Transforms serialized operations back into wide parallel operations.
pub struct OperationParallelizationTransform<'a> {
    graph: &'a mut ResourceGraph,
}

impl<'a> OperationParallelizationTransform<'a> {
    /// Create a new transform operating on the given graph.
    pub fn new(graph: &'a mut ResourceGraph) -> Self {
        Self { graph }
    }

    // =====================================================================
    // PHASE 1: ANALYSIS
    // =====================================================================

    /// Detect serialized operations in the graph.
    ///
    /// Returns a list of `ParallelizationSpec` objects for each detected
    /// serialization pattern.
    pub fn detect_serialized_operations(&self) -> Vec<ParallelizationSpec> {
        info!("Phase 1: ANALYSIS - Detecting serialized operations");

        let mut parallelization_specs = Vec::new();

        // Find all serialization counters
        let serialization_counters = self._find_serialization_counters();

        info!(
            "Found {} serialization counter(s)",
            serialization_counters.len()
        );

        for (counter_id, counter_data) in &serialization_counters {
            info!("Analyzing serialization: {}", counter_id);

            // Create spec for this serialization
            let operation_id = counter_data
                .get("operation_id")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let mut spec = ParallelizationSpec::new(operation_id);
            spec.serialization_counter_id = Some(counter_id.clone());

            // Analyze the serialization structure
            let analysis = self._analyze_serialization_structure(counter_id, &counter_data, &spec);

            if analysis.can_parallelize {
                spec.can_parallelize = true;
                spec.num_cycles = analysis.num_cycles;
                spec.narrow_width = analysis.narrow_width;
                spec.wide_width = analysis.wide_width;
                spec.narrow_operation_node_id = analysis.narrow_operation_node_id;
                info!("  Can parallelize: {}", spec);
            } else {
                spec.can_parallelize = false;
                spec.reason = analysis.reason;
                info!("  Cannot parallelize: {}", spec.reason);
            }

            parallelization_specs.push(spec);
        }

        let parallelizable_count = parallelization_specs
            .iter()
            .filter(|s| s.can_parallelize)
            .count();
        info!(
            "Analysis complete: {}/{} operations can be parallelized",
            parallelizable_count,
            parallelization_specs.len()
        );

        parallelization_specs
    }

    /// Find all serialization counter nodes in the graph.
    fn _find_serialization_counters(&self) -> Vec<(String, HashMap<String, Value>)> {
        let mut counters = Vec::new();
        for (node_id, node) in &self.graph.nodes {
            if node
                .data
                .get("type")
                .and_then(|v| v.as_str())
                == Some("serialization_counter")
            {
                counters.push((node_id.clone(), node.data.clone()));
            }
        }
        counters
    }

    /// Analyze the serialization structure to determine if it can be parallelized.
    fn _analyze_serialization_structure(
        &self,
        counter_id: &str,
        counter_data: &HashMap<String, Value>,
        _spec: &ParallelizationSpec,
    ) -> AnalysisResult {
        let mut result = AnalysisResult::default();

        // Extract serialization parameters
        let max_count = counter_data
            .get("max_count")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        let num_cycles = (max_count + 1) as usize;

        let operation_id = counter_data
            .get("operation_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");

        // Find the narrow operation unit
        let narrow_op = self._find_narrow_operation_unit(operation_id);
        let (narrow_op_id, narrow_op_data) = match narrow_op {
            Some(v) => v,
            None => {
                result.reason = "Narrow operation unit not found".to_string();
                return result;
            }
        };

        let narrow_width = narrow_op_data
            .get("bit_width")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        if narrow_width == 0 {
            result.reason = "Cannot determine narrow operation width".to_string();
            return result;
        }

        let wide_width = narrow_width * num_cycles as i64;
        let operator = narrow_op_data
            .get("operation")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        // Find bit slice extractors
        let slices = self._find_bit_slice_extractors(operation_id);
        if slices.is_empty() {
            result.reason = "Bit slice extractors not found".to_string();
            return result;
        }

        // Verify slices match expected pattern (two operands)
        let expected_slices = num_cycles * 2;
        if slices.len() != expected_slices {
            result.reason = format!(
                "Expected {} slices, found {}",
                expected_slices,
                slices.len()
            );
            return result;
        }

        // Check for cross-iteration dependencies (would prevent unrolling)
        if self._has_cross_iteration_dependencies(counter_id, &narrow_op_id) {
            result.reason = "Cross-iteration dependencies detected".to_string();
            return result;
        }

        // All checks passed
        result.can_parallelize = true;
        result.num_cycles = Some(num_cycles);
        result.narrow_width = Some(narrow_width);
        result.wide_width = Some(wide_width);
        result.narrow_operation_node_id = Some(narrow_op_id.clone());

        info!(
            "    Operator: {}, {}x{}-bit -> {}-bit",
            operator, num_cycles, narrow_width, wide_width
        );

        result
    }

    /// Find the narrow operation unit for a serialized operation.
    fn _find_narrow_operation_unit(
        &self,
        operation_id: &str,
    ) -> Option<(String, HashMap<String, Value>)> {
        for (node_id, node) in &self.graph.nodes {
            if node
                .data
                .get("type")
                .and_then(|v| v.as_str())
                == Some("narrow_operation_unit")
            {
                if node
                    .data
                    .get("original_operation")
                    .and_then(|v| v.as_str())
                    == Some(operation_id)
                {
                    return Some((node_id.clone(), node.data.clone()));
                }
            }
        }
        None
    }

    /// Find all bit slice extractor node IDs for an operation.
    fn _find_bit_slice_extractors(&self, operation_id: &str) -> Vec<String> {
        let mut slices = Vec::new();
        for (node_id, node) in &self.graph.nodes {
            if node
                .data
                .get("type")
                .and_then(|v| v.as_str())
                == Some("bit_slice_extractor")
            {
                if node
                    .data
                    .get("operation_id")
                    .and_then(|v| v.as_str())
                    == Some(operation_id)
                {
                    slices.push(node_id.clone());
                }
            }
        }
        slices
    }

    /// Check if there are dependencies between iterations that would prevent
    /// unrolling.
    ///
    /// For now, we assume serialized operations don't have cross-iteration
    /// dependencies. A more sophisticated analysis could check for feedback
    /// loops.
    fn _has_cross_iteration_dependencies(
        &self,
        _counter_id: &str,
        _narrow_op_id: &str,
    ) -> bool {
        // TODO: Implement more sophisticated dependency analysis.
        // For now, assume no cross-iteration dependencies for standard
        // serialized ops.
        false
    }

    // =====================================================================
    // PHASE 2: PLANNING
    // =====================================================================

    /// Filter and prioritize parallelization specifications.
    ///
    /// Returns a list of specs that should actually be parallelized.
    pub fn plan_parallelization(
        &self,
        specs: &[ParallelizationSpec],
    ) -> Vec<ParallelizationSpec> {
        info!("Phase 2: PLANNING - Creating parallelization plan");

        let unrollable_specs: Vec<ParallelizationSpec> = specs
            .iter()
            .filter(|s| s.can_parallelize)
            .cloned()
            .collect();

        if unrollable_specs.is_empty() {
            info!("No operations to parallelize");
            return Vec::new();
        }

        info!(
            "Planning to parallelize {} operation(s):",
            unrollable_specs.len()
        );
        for spec in &unrollable_specs {
            info!("  - {}", spec);
        }

        unrollable_specs
    }

    // =====================================================================
    // PHASE 3: STRUCTURE CREATION
    // =====================================================================

    /// Create the structure for a wide parallel operation.
    ///
    /// Returns a map from role keys (e.g., `"operation"`) to node IDs.
    pub fn create_wide_operation_structure(
        &mut self,
        spec: &ParallelizationSpec,
    ) -> HashMap<String, String> {
        info!(
            "Phase 3: STRUCTURE - Creating wide parallel operation for {}",
            spec.operation_id
        );

        let mut structure: HashMap<String, String> = HashMap::new();

        // Get operator from narrow operation
        let (operator, bit_width) = {
            let narrow_op_id = spec
                .narrow_operation_node_id
                .as_deref()
                .unwrap_or("");
            let narrow_op_data = self
                .graph
                .nodes
                .get(narrow_op_id)
                .map(|n| &n.data);
            let operator = narrow_op_data
                .and_then(|d| d.get("operation"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let bit_width = spec.wide_width.unwrap_or(0);
            (operator, bit_width)
        };

        let op_id = format!("{}_wide", spec.operation_id);

        // Build expression from original operand sources
        let operand_sources = self._find_original_operand_sources(&spec.operation_id);

        let mut expression = serde_json::Map::new();
        expression.insert("type".to_string(), json!("binary_op"));
        expression.insert("operator".to_string(), json!(operator));
        if operand_sources.len() >= 2 {
            expression.insert("left".to_string(), json!(operand_sources[0].1));
            expression.insert("right".to_string(), json!(operand_sources[1].1));
        } else if operand_sources.len() == 1 {
            expression.insert("left".to_string(), json!(operand_sources[0].1));
            expression.insert("right".to_string(), json!(operand_sources[0].1));
        }

        // Create the wide operation node
        let mut op_node = Node::with_defaults(Some(op_id.clone()));
        op_node.is_uarch_state = false;
        op_node.uarch_time = Some(0); // Completes in single cycle
        op_node
            .data
            .insert("type".to_string(), json!("wide_operation"));
        op_node
            .data
            .insert("name".to_string(), json!(op_id));
        op_node.data.insert(
            "display_name".to_string(),
            json!(format!("{}-bit {}", bit_width, operator)),
        );
        op_node
            .data
            .insert("operation".to_string(), json!(operator));
        op_node
            .data
            .insert("bit_width".to_string(), json!(bit_width));
        op_node
            .data
            .insert("original_operation".to_string(), json!(spec.operation_id));
        op_node
            .data
            .insert("parallelized_from".to_string(), json!("serialization"));
        op_node
            .data
            .insert("expression".to_string(), Value::Object(expression));

        info!("  Created wide operation: {} ({}-bit {})", op_id, bit_width, operator);

        self.graph.add_node(op_node);
        structure.insert("operation".to_string(), op_id);

        structure
    }

    // =====================================================================
    // PHASE 5: CONNECTION / WIRING
    // =====================================================================

    /// Connect the wide parallel operation to its inputs and outputs.
    pub fn wire_wide_operation(
        &mut self,
        spec: &ParallelizationSpec,
        structure: &HashMap<String, String>,
    ) {
        info!("Phase 5: CONNECTION - Wiring wide operation");

        let op_node_id = match structure.get("operation") {
            Some(id) => id.clone(),
            None => {
                info!("  Warning: No operation node in structure");
                return;
            }
        };

        // Find original operand sources (before bit slicing)
        let operand_sources = self._find_original_operand_sources(&spec.operation_id);

        if operand_sources.len() != 2 {
            info!(
                "  Warning: Expected 2 operand sources, found {}",
                operand_sources.len()
            );
        }

        // Connect operands directly to wide operation
        for (i, (operand_name, source_node_id)) in operand_sources.iter().enumerate() {
            let position = if i == 0 { "left" } else { "right" };
            let mut edge_data = HashMap::new();
            edge_data.insert("type".to_string(), json!("operand"));
            edge_data.insert("position".to_string(), json!(position));
            edge_data.insert("operand_name".to_string(), json!(operand_name));

            let edge = Edge::new(
                source_node_id.clone(),
                op_node_id.clone(),
                None,
                Some(edge_data),
            );
            self.graph.add_edge(edge);
            info!("  Connected {} -> {} ({})", source_node_id, op_node_id, position);
        }

        // Find result destinations (where the partial result went)
        let result_destinations = self._find_result_destinations(&spec.operation_id);

        // Connect wide operation to destinations
        for dest_id in &result_destinations {
            let mut edge_data = HashMap::new();
            edge_data.insert("type".to_string(), json!("assignment"));
            edge_data.insert("unrolled_result".to_string(), json!(true));

            let edge = Edge::new(
                op_node_id.clone(),
                dest_id.clone(),
                None,
                Some(edge_data),
            );
            self.graph.add_edge(edge);
            info!("  Connected {} -> {}", op_node_id, dest_id);
        }

        info!(
            "  Wired {} inputs and {} outputs",
            operand_sources.len(),
            result_destinations.len()
        );
    }

    /// Find the original operand sources (before bit slicing).
    ///
    /// Returns a list of `(operand_name, source_node_id)` tuples.
    fn _find_original_operand_sources(
        &self,
        operation_id: &str,
    ) -> Vec<(String, String)> {
        let mut sources: Vec<(String, String)> = Vec::new();

        // Find bit slice extractors
        let slices = self._find_bit_slice_extractors(operation_id);

        // Group slices by operand
        let mut operand_slices: HashMap<String, Vec<String>> = HashMap::new();
        for slice_id in &slices {
            if let Some(node) = self.graph.nodes.get(slice_id) {
                let source_operand = node
                    .data
                    .get("source_operand")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                operand_slices
                    .entry(source_operand)
                    .or_default()
                    .push(slice_id.clone());
            }
        }

        // For each operand, trace back to the original source
        for (operand_name, slice_node_ids) in &operand_slices {
            if let Some(first_slice_id) = slice_node_ids.first() {
                if let Some(slice_node) = self.graph.nodes.get(first_slice_id) {
                    // Find the source of the slice (should be the original operand)
                    for edge_id in &slice_node.incoming_edges {
                        if let Some(edge) = self.graph.edges.get(edge_id) {
                            if edge
                                .data
                                .get("type")
                                .and_then(|v| v.as_str())
                                == Some("bit_slice")
                            {
                                sources.push((
                                    operand_name.clone(),
                                    edge.source.clone(),
                                ));
                                break;
                            }
                        }
                    }
                }
            }
        }

        sources
    }

    /// Find where the serialized result goes.
    fn _find_result_destinations(&self, operation_id: &str) -> Vec<String> {
        let mut destinations = Vec::new();

        // Find partial result storage
        for (_node_id, node) in &self.graph.nodes {
            if node
                .data
                .get("type")
                .and_then(|v| v.as_str())
                == Some("partial_result_storage")
            {
                if node
                    .data
                    .get("operation_id")
                    .and_then(|v| v.as_str())
                    == Some(operation_id)
                {
                    // Find what the partial result connects to
                    for edge_id in &node.outgoing_edges {
                        if let Some(edge) = self.graph.edges.get(edge_id) {
                            destinations.push(edge.target.clone());
                        }
                    }
                    break;
                }
            }
        }

        destinations
    }

    // =====================================================================
    // PHASE 6: CLEANUP
    // =====================================================================

    /// Remove all the serialization infrastructure that is no longer needed.
    pub fn cleanup_infrastructure(&mut self, spec: &ParallelizationSpec) {
        info!("Phase 6: CLEANUP - Removing serialization infrastructure");

        let removable_types = [
            "serialization_counter",
            "narrow_operation_unit",
            "bit_slice_extractor",
            "mux",
            "partial_result_storage",
            "result_accumulator",
            "serialization_completion",
        ];

        // Collect node IDs to remove (collect first, then mutate)
        let nodes_to_remove: Vec<String> = self
            .graph
            .nodes
            .iter()
            .filter(|(_id, node)| {
                let node_type = node
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let node_op_id = node
                    .data
                    .get("operation_id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let node_orig_op = node
                    .data
                    .get("original_operation")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");

                (node_op_id == spec.operation_id || node_orig_op == spec.operation_id)
                    && removable_types.contains(&node_type)
            })
            .map(|(id, _)| id.clone())
            .collect();

        info!(
            "  Removing {} serialization infrastructure nodes:",
            nodes_to_remove.len()
        );

        for node_id in &nodes_to_remove {
            if let Some(node) = self.graph.nodes.get(node_id) {
                let node_type = node
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("unknown");
                info!("    - {} ({})", node_id, node_type);
            }
            self._remove_node(node_id);
        }

        // Also remove any enable/gating nodes
        self._cleanup_enable_gating_nodes(spec);
    }

    /// Helper to remove a node and all its edges.
    fn _remove_node(&mut self, node_id: &str) {
        // ResourceGraph::remove_node handles edge cleanup
        self.graph.remove_node(node_id);
    }

    /// Remove enable/gating nodes associated with the serialization.
    fn _cleanup_enable_gating_nodes(&mut self, spec: &ParallelizationSpec) {
        let counter_id = spec
            .serialization_counter_id
            .as_deref()
            .unwrap_or("");

        let nodes_to_remove: Vec<String> = self
            .graph
            .nodes
            .iter()
            .filter(|(id, _node)| {
                let id_lower = id.to_lowercase();
                (id_lower.contains("enable") || id_lower.contains("gating"))
                    && (id.contains(&spec.operation_id)
                        || (!counter_id.is_empty() && id.contains(counter_id)))
            })
            .map(|(id, _)| id.clone())
            .collect();

        for node_id in &nodes_to_remove {
            info!("    - {} (enable/gating)", node_id);
            self.graph.remove_node(node_id);
        }
    }

    // =====================================================================
    // PHASE 7: TIMING UPDATE
    // =====================================================================

    /// Update timing information after parallelization.
    ///
    /// Parallelization should reduce latency since operations complete in 1
    /// cycle instead of N cycles.
    pub fn update_timing(&mut self, _specs: &[ParallelizationSpec]) {
        info!("Phase 7: TIMING - Updating graph timing");

        let max_time_before = self.graph.get_max_uarch_time();
        info!(
            "  Pipeline depth before timing update: {} cycles",
            max_time_before + 1
        );

        // Re-infer timing for the entire graph
        self.graph.infer_uarch_time(true);

        let max_time_after = self.graph.get_max_uarch_time();
        info!(
            "  Pipeline depth after timing update: {} cycles",
            max_time_after + 1
        );

        if max_time_after < max_time_before {
            info!(
                "  Latency reduced by {} cycle(s)",
                max_time_before - max_time_after
            );
        }

        info!("  Timing update complete");
    }

    // =====================================================================
    // HIGH-LEVEL API
    // =====================================================================

    /// Apply parallelization for a single `ParallelizationSpec`.
    ///
    /// Returns `true` if parallelization was successful.
    pub fn apply_parallelization(&mut self, spec: &ParallelizationSpec) -> bool {
        if !spec.can_parallelize {
            info!("Skipping {}: {}", spec.operation_id, spec.reason);
            return false;
        }

        info!(
            "======================================================================",
        );
        info!("PARALLELIZING: {}", spec.operation_id);
        info!(
            "======================================================================",
        );

        // Phase 3: Structure
        let structure = self.create_wide_operation_structure(spec);

        // Phase 4: Hardware (minimal for wide operations — the wide operation
        // itself is the hardware, no additional components needed since we are
        // just widening the datapath)
        info!("Phase 4: HARDWARE - Wide operation hardware already created in structure phase");

        // Phase 5: Connection
        self.wire_wide_operation(spec, &structure);

        // Phase 6: Cleanup
        self.cleanup_infrastructure(spec);

        info!("Successfully parallelized {}", spec.operation_id);
        true
    }
}

// ---------------------------------------------------------------------------
// Internal helper struct for analysis results
// ---------------------------------------------------------------------------

#[derive(Debug, Default)]
struct AnalysisResult {
    can_parallelize: bool,
    reason: String,
    num_cycles: Option<usize>,
    narrow_width: Option<i64>,
    wide_width: Option<i64>,
    narrow_operation_node_id: Option<String>,
}

// ---------------------------------------------------------------------------
// Standalone convenience function
// ---------------------------------------------------------------------------

/// Detect and parallelize serialized operations in a `ResourceGraph`.
///
/// This detects operations that have been serialized and converts them back
/// into wide parallel operations, trading area for reduced latency.
///
/// # Arguments
///
/// * `graph` - The `ResourceGraph` to optimize.
/// * `operation_id` - Optional specific operation ID to parallelize.
///   If `None`, parallelizes all detected serialized operations.
/// * `target_granularity` - Optional target bit width. If specified and less
///   than the original wide width, the caller is responsible for
///   re-serializing to this granularity after full parallelization (e.g.,
///   going from 8-bit serialized to 16-bit serialized via intermediate full
///   parallelization). This function performs the full parallelization step
///   and reports whether re-serialization is needed.
///
/// # Returns
///
/// `true` if any operations were parallelized, `false` otherwise.
pub fn parallelize_serialized_operations(
    graph: &mut ResourceGraph,
    operation_id: Option<&str>,
    target_granularity: Option<i64>,
) -> bool {
    info!("======================================================================");
    info!("OPERATION PARALLELIZATION OPTIMIZATION");
    info!("======================================================================");

    let mut parallelizer = OperationParallelizationTransform::new(graph);

    // Phase 1: Analysis - Detect serialized operations
    let specs = parallelizer.detect_serialized_operations();

    if specs.is_empty() {
        info!("No serialized operations detected");
        return false;
    }

    // Filter to specific operation if requested
    let specs = if let Some(op_id) = operation_id {
        let filtered: Vec<ParallelizationSpec> = specs
            .into_iter()
            .filter(|s| s.operation_id == op_id)
            .collect();
        if filtered.is_empty() {
            info!(
                "Operation '{}' not found or not serialized",
                op_id
            );
            return false;
        }
        info!("Targeting specific operation: {}", op_id);
        filtered
    } else {
        specs
    };

    // Check if we need partial parallelization
    let mut _original_width: Option<i64> = None;
    if let Some(target) = target_granularity {
        if let Some(first_spec) = specs.first() {
            let orig_w = first_spec.wide_width.unwrap_or(0);
            let current_gran = first_spec.narrow_width.unwrap_or(0);
            _original_width = Some(orig_w);

            if target < current_gran {
                info!(
                    "Error: Target granularity ({}-bit) is smaller than current ({}-bit)",
                    target, current_gran
                );
                info!(
                    "Cannot serialize further via parallelization. Use serialization mode instead."
                );
                return false;
            }

            if target >= orig_w {
                info!(
                    "Target granularity ({}-bit) >= original width ({}-bit)",
                    target, orig_w
                );
                info!("Will fully parallelize to {}-bit", orig_w);
                // target_granularity effectively becomes None (full parallelization)
            } else if target > current_gran {
                info!(
                    "Partial parallelization: {}-bit -> {}-bit -> {}-bit",
                    current_gran, orig_w, target
                );
            }
        }
    }

    // Phase 2: Planning
    let parallel_plan = parallelizer.plan_parallelization(&specs);

    if parallel_plan.is_empty() {
        info!("No operations selected for parallelization");
        return false;
    }

    // Phases 3-6: Apply parallelization to each operation
    let mut parallelized_any = false;
    for spec in &parallel_plan {
        if parallelizer.apply_parallelization(spec) {
            parallelized_any = true;
        }
    }

    // Phase 7: Timing (done once for all parallelized operations)
    if parallelized_any {
        parallelizer.update_timing(&parallel_plan);
    }

    // Note: Phase 8 (re-serialization to target_granularity) is left to the
    // caller since operation_serialization is a separate module.  The Python
    // version imports it inline; in Rust it is cleaner to let the caller
    // compose the two transforms.

    info!("======================================================================");
    if parallelized_any {
        info!("OPERATION PARALLELIZATION COMPLETE");
    } else {
        info!("NO OPERATIONS PARALLELIZED");
    }
    info!("======================================================================");

    parallelized_any
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    /// Helper: create a minimal serialized graph for testing.
    fn create_serialized_test_graph() -> ResourceGraph {
        let mut graph = ResourceGraph::new();

        let op_id = "test_add";

        // Operand source nodes
        let mut src_a = Node::with_defaults(Some("operand_a".to_string()));
        src_a.data.insert("type".to_string(), json!("register"));
        graph.add_node(src_a);

        let mut src_b = Node::with_defaults(Some("operand_b".to_string()));
        src_b.data.insert("type".to_string(), json!("register"));
        graph.add_node(src_b);

        // Bit slice extractors (2 operands x 4 cycles = 8 slices)
        for i in 0..4 {
            let slice_a_id = format!("{}_slice_a_{}", op_id, i);
            let mut slice_a = Node::with_defaults(Some(slice_a_id.clone()));
            slice_a.data.insert("type".to_string(), json!("bit_slice_extractor"));
            slice_a.data.insert("operation_id".to_string(), json!(op_id));
            slice_a.data.insert("source_operand".to_string(), json!("a"));
            graph.add_node(slice_a);

            // Edge from source to slice
            let mut edge_data = HashMap::new();
            edge_data.insert("type".to_string(), json!("bit_slice"));
            let edge = Edge::new(
                "operand_a".to_string(),
                slice_a_id,
                None,
                Some(edge_data),
            );
            graph.add_edge(edge);

            let slice_b_id = format!("{}_slice_b_{}", op_id, i);
            let mut slice_b = Node::with_defaults(Some(slice_b_id.clone()));
            slice_b.data.insert("type".to_string(), json!("bit_slice_extractor"));
            slice_b.data.insert("operation_id".to_string(), json!(op_id));
            slice_b.data.insert("source_operand".to_string(), json!("b"));
            graph.add_node(slice_b);

            let mut edge_data = HashMap::new();
            edge_data.insert("type".to_string(), json!("bit_slice"));
            let edge = Edge::new(
                "operand_b".to_string(),
                slice_b_id,
                None,
                Some(edge_data),
            );
            graph.add_edge(edge);
        }

        // Narrow operation unit
        let mut narrow_op = Node::with_defaults(Some("narrow_add".to_string()));
        narrow_op.data.insert("type".to_string(), json!("narrow_operation_unit"));
        narrow_op.data.insert("original_operation".to_string(), json!(op_id));
        narrow_op.data.insert("operation".to_string(), json!("+"));
        narrow_op.data.insert("bit_width".to_string(), json!(8));
        graph.add_node(narrow_op);

        // Serialization counter (max_count = 3 means 4 cycles)
        let mut counter = Node::with_defaults(Some("test_add_counter".to_string()));
        counter.data.insert("type".to_string(), json!("serialization_counter"));
        counter.data.insert("operation_id".to_string(), json!(op_id));
        counter.data.insert("max_count".to_string(), json!(3));
        graph.add_node(counter);

        // Partial result storage
        let mut partial = Node::with_defaults(Some("test_add_partial".to_string()));
        partial.data.insert("type".to_string(), json!("partial_result_storage"));
        partial.data.insert("operation_id".to_string(), json!(op_id));
        graph.add_node(partial);

        // Result destination
        let mut dest = Node::with_defaults(Some("result_dest".to_string()));
        dest.data.insert("type".to_string(), json!("register"));
        graph.add_node(dest);

        // Edge from partial to destination
        let edge = Edge::new(
            "test_add_partial".to_string(),
            "result_dest".to_string(),
            None,
            None,
        );
        graph.add_edge(edge);

        graph
    }

    #[test]
    fn test_spec_display_can_parallelize() {
        let mut spec = ParallelizationSpec::new("add32");
        spec.can_parallelize = true;
        spec.num_cycles = Some(4);
        spec.narrow_width = Some(8);
        spec.wide_width = Some(32);
        let s = format!("{}", spec);
        assert!(s.contains("Parallelize add32"));
        assert!(s.contains("4x8-bit"));
        assert!(s.contains("32-bit"));
    }

    #[test]
    fn test_spec_display_cannot_parallelize() {
        let mut spec = ParallelizationSpec::new("div64");
        spec.can_parallelize = false;
        spec.reason = "Cross-iteration dependencies".to_string();
        let s = format!("{}", spec);
        assert!(s.contains("Cannot parallelize div64"));
        assert!(s.contains("Cross-iteration dependencies"));
    }

    #[test]
    fn test_detect_serialized_operations() {
        let mut graph = create_serialized_test_graph();
        let transform = OperationParallelizationTransform::new(&mut graph);
        let specs = transform.detect_serialized_operations();

        assert_eq!(specs.len(), 1);
        assert!(specs[0].can_parallelize);
        assert_eq!(specs[0].operation_id, "test_add");
        assert_eq!(specs[0].num_cycles, Some(4));
        assert_eq!(specs[0].narrow_width, Some(8));
        assert_eq!(specs[0].wide_width, Some(32));
    }

    #[test]
    fn test_plan_parallelization_filters_non_parallelizable() {
        let mut graph = ResourceGraph::new();
        let transform = OperationParallelizationTransform::new(&mut graph);

        let mut spec1 = ParallelizationSpec::new("op1");
        spec1.can_parallelize = true;
        spec1.num_cycles = Some(2);
        spec1.narrow_width = Some(16);
        spec1.wide_width = Some(32);

        let mut spec2 = ParallelizationSpec::new("op2");
        spec2.can_parallelize = false;
        spec2.reason = "Cannot parallelize".to_string();

        let plan = transform.plan_parallelization(&[spec1, spec2]);
        assert_eq!(plan.len(), 1);
        assert_eq!(plan[0].operation_id, "op1");
    }

    #[test]
    fn test_apply_parallelization_full() {
        let mut graph = create_serialized_test_graph();

        let result = parallelize_serialized_operations(&mut graph, None, None);
        assert!(result);

        // Wide operation node should exist
        assert!(graph.nodes.contains_key("test_add_wide"));
        let wide_node = graph.nodes.get("test_add_wide").unwrap();
        assert_eq!(
            wide_node.data.get("type").and_then(|v| v.as_str()),
            Some("wide_operation")
        );
        assert_eq!(
            wide_node.data.get("bit_width").and_then(|v| v.as_i64()),
            Some(32)
        );
        assert_eq!(
            wide_node.data.get("operation").and_then(|v| v.as_str()),
            Some("+")
        );

        // Serialization infrastructure should be removed
        assert!(!graph.nodes.contains_key("test_add_counter"));
        assert!(!graph.nodes.contains_key("test_add_partial"));
        assert!(!graph.nodes.contains_key("narrow_add"));
    }

    #[test]
    fn test_apply_parallelization_specific_operation() {
        let mut graph = create_serialized_test_graph();

        // Try a non-existent operation
        let result =
            parallelize_serialized_operations(&mut graph, Some("nonexistent"), None);
        assert!(!result);

        // Try the correct operation
        let result =
            parallelize_serialized_operations(&mut graph, Some("test_add"), None);
        assert!(result);
        assert!(graph.nodes.contains_key("test_add_wide"));
    }

    #[test]
    fn test_cleanup_removes_serialization_nodes() {
        let mut graph = create_serialized_test_graph();
        let mut transform = OperationParallelizationTransform::new(&mut graph);

        let specs = transform.detect_serialized_operations();
        assert!(!specs.is_empty());

        let spec = &specs[0];
        transform.cleanup_infrastructure(spec);

        // Counter, narrow op, partial storage, slices should all be removed
        assert!(!transform.graph.nodes.contains_key("test_add_counter"));
        assert!(!transform.graph.nodes.contains_key("narrow_add"));
        assert!(!transform.graph.nodes.contains_key("test_add_partial"));

        // Bit slice extractors should be removed
        for i in 0..4 {
            assert!(!transform
                .graph
                .nodes
                .contains_key(&format!("test_add_slice_a_{}", i)));
            assert!(!transform
                .graph
                .nodes
                .contains_key(&format!("test_add_slice_b_{}", i)));
        }

        // Source and destination nodes should remain
        assert!(transform.graph.nodes.contains_key("operand_a"));
        assert!(transform.graph.nodes.contains_key("operand_b"));
        assert!(transform.graph.nodes.contains_key("result_dest"));
    }

    #[test]
    fn test_no_serialization_counters() {
        let mut graph = ResourceGraph::new();
        let mut node = Node::with_defaults(Some("plain_node".to_string()));
        node.data.insert("type".to_string(), json!("register"));
        graph.add_node(node);

        let result = parallelize_serialized_operations(&mut graph, None, None);
        assert!(!result);
    }

    #[test]
    fn test_target_granularity_too_small() {
        let mut graph = create_serialized_test_graph();

        // Target granularity smaller than current narrow width (8-bit)
        // should fail
        let result =
            parallelize_serialized_operations(&mut graph, None, Some(4));
        assert!(!result);
    }

    #[test]
    fn test_wide_operation_structure() {
        let mut graph = create_serialized_test_graph();
        let mut transform = OperationParallelizationTransform::new(&mut graph);
        let specs = transform.detect_serialized_operations();
        assert!(!specs.is_empty());

        let spec = &specs[0];
        let structure = transform.create_wide_operation_structure(spec);

        // Wide operation node should exist
        let wide_op_id = structure.get("operation").unwrap();
        assert!(transform.graph.nodes.contains_key(wide_op_id));

        let wide_node = transform.graph.nodes.get(wide_op_id).unwrap();
        // type should be wide_operation
        assert_eq!(
            wide_node.data.get("type").and_then(|v| v.as_str()),
            Some("wide_operation"),
            "Wide operation node should have type 'wide_operation'"
        );
        // bit_width should be narrow_width * num_cycles = 8 * 4 = 32
        assert_eq!(
            wide_node.data.get("bit_width").and_then(|v| v.as_i64()),
            Some(32),
            "Wide operation bit_width should be narrow * cycles"
        );
    }

    #[test]
    fn test_wire_wide_operation() {
        let mut graph = create_serialized_test_graph();
        let mut transform = OperationParallelizationTransform::new(&mut graph);
        let specs = transform.detect_serialized_operations();
        assert!(!specs.is_empty());

        let spec = &specs[0];
        let structure = transform.create_wide_operation_structure(spec);
        transform.wire_wide_operation(spec, &structure);

        let wide_op_id = structure.get("operation").unwrap();
        let wide_node = transform.graph.nodes.get(wide_op_id).unwrap();

        // Should have operand edges from sources to wide op
        let mut has_operand_edge = false;
        for eid in &wide_node.incoming_edges {
            if let Some(edge) = transform.graph.edges.get(eid) {
                if edge.data.get("type").and_then(|v| v.as_str()) == Some("operand") {
                    has_operand_edge = true;
                }
            }
        }
        assert!(has_operand_edge, "Wide operation should have operand edges from sources");

        // Should have assignment edges from wide op to destinations
        let mut has_assignment_edge = false;
        for eid in &wide_node.outgoing_edges {
            if let Some(edge) = transform.graph.edges.get(eid) {
                if edge.data.get("type").and_then(|v| v.as_str()) == Some("assignment") {
                    has_assignment_edge = true;
                }
            }
        }
        assert!(has_assignment_edge, "Wide operation should have assignment edges to destinations");
    }

    #[test]
    fn test_parallelization_spec_fields() {
        let mut graph = create_serialized_test_graph();
        let transform = OperationParallelizationTransform::new(&mut graph);
        let specs = transform.detect_serialized_operations();

        assert_eq!(specs.len(), 1);
        let spec = &specs[0];

        // Verify all spec fields are set correctly after detection
        assert_eq!(spec.num_cycles, Some(4), "num_cycles should be 4 (max_count 3 + 1)");
        assert_eq!(spec.narrow_width, Some(8), "narrow_width should be 8");
        assert_eq!(spec.wide_width, Some(32), "wide_width should be 8 * 4 = 32");
        assert_eq!(
            spec.serialization_counter_id,
            Some("test_add_counter".to_string()),
            "counter_id should match"
        );
        assert!(spec.can_parallelize, "should be parallelizable");
    }

    #[test]
    fn test_update_timing_reinfers() {
        let mut graph = create_serialized_test_graph();

        // Set some explicit uarch_time values
        if let Some(node) = graph.nodes.get_mut("operand_a") {
            node.uarch_time = Some(0);
        }
        if let Some(node) = graph.nodes.get_mut("operand_b") {
            node.uarch_time = Some(0);
        }

        let mut transform = OperationParallelizationTransform::new(&mut graph);
        let specs = transform.detect_serialized_operations();
        assert!(!specs.is_empty());

        // Apply full parallelization including timing update
        let spec = &specs[0];
        let structure = transform.create_wide_operation_structure(spec);
        transform.wire_wide_operation(spec, &structure);
        transform.cleanup_infrastructure(spec);
        transform.update_timing(&specs);

        // After update_timing, graph should have recalculated uarch_time values.
        // The wide operation node should have a uarch_time (inferred or set).
        let wide_op_id = structure.get("operation").unwrap();
        if let Some(wide_node) = transform.graph.nodes.get(wide_op_id) {
            // uarch_time should be set (either 0 from creation or re-inferred)
            assert!(
                wide_node.uarch_time.is_some(),
                "Wide operation should have uarch_time after timing update"
            );
        }
    }
}
