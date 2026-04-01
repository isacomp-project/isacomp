//! Architectural Retiming Optimization for ResourceGraph.
//!
//! Port of `architectural_retiming.py`. Implements architectural retiming, a technique
//! that optimizes latency-constrained circuits using "negative registers" (anti-registers)
//! that counteract normal register latency.
//!
//! Based on the work of Hassoun and Ebeling (1996), architectural retiming uses two main
//! strategies:
//! 1. Precomputation: Computing critical signals earlier in time by duplicating logic
//! 2. Prediction: Predicting values and correcting on misprediction
//!
//! This technique generalizes optimizations like branch prediction and bypassing, allowing
//! critical path signals to be computed early while preserving functional behavior.

use log::{debug, info};
use serde_json::{json, Value};
use std::collections::HashMap;

use crate::resource_graph::{Edge, Node, ResourceGraph};

// ---------------------------------------------------------------------------
// RetimeableNodeInfo
// ---------------------------------------------------------------------------

/// Information about a node that is a candidate for architectural retiming.
#[derive(Debug, Clone)]
pub struct RetimeableNodeInfo {
    /// Current cycle time of the node.
    pub uarch_time: i64,
    /// Node type (e.g., "operation", "var").
    pub node_type: String,
    /// Whether precomputation is feasible for this node.
    pub can_precompute: bool,
    /// Whether prediction is feasible for this node.
    pub can_predict: bool,
    /// Maximum cycles this node can be moved earlier (down to cycle 0).
    pub max_depth: i64,
}

// ---------------------------------------------------------------------------
// ArchitecturalRetimingPass
// ---------------------------------------------------------------------------

/// Implements architectural retiming using precomputation or prediction.
///
/// The pass takes a target node (critical signal) and applies architectural
/// retiming to compute or predict it earlier in the pipeline, potentially
/// improving timing while maintaining functional correctness.
pub struct ArchitecturalRetimingPass<'a> {
    graph: &'a mut ResourceGraph,
    target_node_id: Option<String>,
    strategy: String,
    depth: usize,
    precomputed_node_id: Option<String>,
    predicted_node_id: Option<String>,
    correction_logic_ids: Vec<String>,
}

impl<'a> ArchitecturalRetimingPass<'a> {
    /// Create a new architectural retiming pass operating on the given graph.
    pub fn new(graph: &'a mut ResourceGraph) -> Self {
        ArchitecturalRetimingPass {
            graph,
            target_node_id: None,
            strategy: "precomputation".to_string(),
            depth: 1,
            precomputed_node_id: None,
            predicted_node_id: None,
            correction_logic_ids: Vec::new(),
        }
    }

    /// Apply architectural retiming to a target node.
    ///
    /// # Arguments
    /// * `target_node_id` - ID of the node to optimize (critical signal)
    /// * `strategy` - Either "precomputation" or "prediction"
    /// * `depth` - How many cycles early to compute/predict (must be <= target node's uarch_time)
    ///
    /// # Returns
    /// `true` if architectural retiming was successfully applied.
    pub fn apply(&mut self, target_node_id: &str, strategy: &str, depth: usize) -> bool {
        info!("");
        info!("======================================================================");
        info!("APPLYING ARCHITECTURAL RETIMING PASS");
        info!("======================================================================");
        info!("Target node: {}", target_node_id);
        info!("Strategy: {}", strategy);
        info!("Depth: {} cycle(s)", depth);

        // Validate inputs
        if !self.graph.nodes.contains_key(target_node_id) {
            info!("Error: Target node {} not found in graph", target_node_id);
            return false;
        }

        if strategy != "precomputation" && strategy != "prediction" {
            info!(
                "Error: Invalid strategy '{}'. Must be 'precomputation' or 'prediction'",
                strategy
            );
            return false;
        }

        if depth < 1 {
            info!("Error: Depth must be at least 1 cycle");
            return false;
        }

        self.target_node_id = Some(target_node_id.to_string());
        self.strategy = strategy.to_string();
        self.depth = depth;

        // Step 1: Analyze the target node and its dependencies
        if !self._analyze_target() {
            info!("Could not analyze target node - architectural retiming not applicable");
            return false;
        }

        // Step 2: Apply the chosen strategy
        if self.strategy == "precomputation" {
            if !self._apply_precomputation() {
                info!("Precomputation strategy failed");
                return false;
            }
        } else if self.strategy == "prediction" {
            if !self._apply_prediction() {
                info!("Prediction strategy failed");
                return false;
            }
        }

        // Step 3: Update timing information
        self.graph.infer_uarch_time(false);

        info!("");
        info!("Architectural retiming pass completed successfully");
        info!("======================================================================");
        true
    }

    /// Analyze the target node to determine if architectural retiming is applicable.
    fn _analyze_target(&self) -> bool {
        info!("");
        info!("Step 1: Analyzing target node...");

        let target_id = match &self.target_node_id {
            Some(id) => id.clone(),
            None => return false,
        };

        let (current_time, incoming_edge_ids) = match self.graph.get_node(&target_id) {
            Some(node) => {
                let time = node.uarch_time;
                let edges: Vec<String> = node.incoming_edges.iter().cloned().collect();
                (time, edges)
            }
            None => return false,
        };

        info!("  Target node '{}' at uarch_time: {:?}", target_id, current_time);

        // Check if we can move it earlier
        match current_time {
            None => {
                info!("  Warning: Target node has no uarch_time, timing will be inferred");
            }
            Some(t) => {
                if (t as usize) < self.depth {
                    info!(
                        "  Error: Cannot move node {} cycles earlier (currently at cycle {})",
                        self.depth, t
                    );
                    info!(
                        "  Maximum depth for this node is {} (can't go below cycle 0)",
                        t
                    );
                    return false;
                }
            }
        }

        // Analyze dependencies
        let mut input_count = 0;
        for edge_id in &incoming_edge_ids {
            if let Some(edge) = self.graph.get_edge(edge_id) {
                let edge_type = edge
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                if edge_type == "data" || edge_type == "control" || edge_type == "operand" {
                    let source_id = edge.source.clone();
                    if let Some(source_node) = self.graph.get_node(&source_id) {
                        let source_type = source_node
                            .data
                            .get("type")
                            .and_then(|v| v.as_str())
                            .unwrap_or("unknown");
                        let inp_time = match source_node.uarch_time {
                            Some(t) => format!("{}", t),
                            None => "unknown".to_string(),
                        };
                        debug!(
                            "    - {} (type: {}, time: {})",
                            source_id, source_type, inp_time
                        );
                        input_count += 1;
                    }
                }
            }
        }

        info!("  Found {} input dependencies", input_count);

        true
    }

    /// Apply precomputation strategy: duplicate computation to run earlier.
    ///
    /// This creates a "negative register" by computing the target value earlier
    /// in the pipeline and storing it in an architectural state register.
    fn _apply_precomputation(&mut self) -> bool {
        info!("");
        info!("Step 2: Applying precomputation strategy...");

        let target_id = match &self.target_node_id {
            Some(id) => id.clone(),
            None => return false,
        };

        // Calculate target time for precomputed value
        let current_time = self.graph.get_node(&target_id).and_then(|n| n.uarch_time);
        let target_time = match current_time {
            None => 0_usize,
            Some(t) => {
                let new_time = t as usize;
                if new_time >= self.depth {
                    new_time - self.depth
                } else {
                    0
                }
            }
        };

        info!(
            "  Precomputing value at cycle {} (original: {:?})",
            target_time, current_time
        );

        // Step 2a: Duplicate the computation logic
        let duplicated_node_ids =
            self._duplicate_computation_tree(&target_id, target_time);
        if duplicated_node_ids.is_empty() {
            info!("  Error: Could not duplicate computation tree");
            return false;
        }

        info!(
            "  Duplicated {} nodes for early computation",
            duplicated_node_ids.len()
        );

        // Step 2b: Create architectural state register to hold precomputed value
        let precomp_reg_id = format!("{}_precomputed", target_id);
        let mut precomp_reg = Node::with_defaults(Some(precomp_reg_id.clone()));
        precomp_reg.data.insert("type".to_string(), json!("architectural_state"));
        precomp_reg.data.insert("name".to_string(), json!(precomp_reg_id));
        precomp_reg.data.insert(
            "description".to_string(),
            json!(format!("Precomputed value of {}", target_id)),
        );
        precomp_reg.is_arch_state = true;
        precomp_reg.uarch_time = Some(target_time as i64);
        self.graph.add_node(precomp_reg);
        self.precomputed_node_id = Some(precomp_reg_id.clone());

        info!("  Created precomputation register: {}", precomp_reg_id);

        // Step 2c: Connect duplicated computation to precomputation register
        // The root of the duplicated tree should write to the register
        let root_dup_id = duplicated_node_ids[0].clone();
        let mut assign_data = HashMap::new();
        assign_data.insert("type".to_string(), json!("assignment"));
        assign_data.insert(
            "description".to_string(),
            json!("Store precomputed value"),
        );
        let assign_edge = Edge::new(
            root_dup_id.clone(),
            precomp_reg_id.clone(),
            None,
            Some(assign_data),
        );
        self.graph.add_edge(assign_edge);
        info!("  Connected {} -> {}", root_dup_id, precomp_reg_id);

        // Step 2d: Create a read node for the precomputed value
        let precomp_read_id = format!("{}_precomp_read", target_id);
        let mut precomp_read = Node::with_defaults(Some(precomp_read_id.clone()));
        precomp_read.data.insert("type".to_string(), json!("read_state"));
        precomp_read.data.insert("name".to_string(), json!(precomp_read_id));
        precomp_read.uarch_time = current_time;
        self.graph.add_node(precomp_read);

        // Connect read from precomputation register
        let mut read_data = HashMap::new();
        read_data.insert("type".to_string(), json!("state_read"));
        read_data.insert(
            "description".to_string(),
            json!("Read precomputed value"),
        );
        let read_edge = Edge::new(
            precomp_reg_id,
            precomp_read_id.clone(),
            None,
            Some(read_data),
        );
        self.graph.add_edge(read_edge);

        // Step 2e: Replace uses of original target with precomputed read
        self._replace_node_uses(&target_id, &precomp_read_id);

        info!(
            "  Replaced uses of {} with precomputed value",
            target_id
        );

        true
    }

    /// Apply prediction strategy: predict value early and correct on misprediction.
    ///
    /// This creates a "negative register" by predicting the target value earlier
    /// and adding correction logic when the prediction is wrong.
    fn _apply_prediction(&mut self) -> bool {
        info!("");
        info!("Step 2: Applying prediction strategy...");

        let target_id = match &self.target_node_id {
            Some(id) => id.clone(),
            None => return false,
        };

        // Calculate target time for predicted value
        let current_time = self.graph.get_node(&target_id).and_then(|n| n.uarch_time);
        let target_time = match current_time {
            None => 0_i64,
            Some(t) => {
                let new_time = t - self.depth as i64;
                if new_time > 0 { new_time } else { 0 }
            }
        };

        info!(
            "  Predicting value at cycle {} (actual: {:?})",
            target_time, current_time
        );

        // Step 2a: Create predictor node (simple last-value predictor)
        let predictor_id = format!("{}_predictor", target_id);
        let mut predictor = Node::with_defaults(Some(predictor_id.clone()));
        predictor.data.insert("type".to_string(), json!("operation"));
        predictor.data.insert("op".to_string(), json!("predict"));
        predictor.data.insert(
            "description".to_string(),
            json!(format!("Predicts value of {}", target_id)),
        );
        predictor.uarch_time = Some(target_time);
        self.graph.add_node(predictor);

        info!("  Created predictor node: {}", predictor_id);

        // Step 2b: Create architectural state to hold last actual value
        let last_value_id = format!("{}_last_value", target_id);
        let mut last_value_reg = Node::with_defaults(Some(last_value_id.clone()));
        last_value_reg.data.insert("type".to_string(), json!("architectural_state"));
        last_value_reg.data.insert("name".to_string(), json!(last_value_id));
        last_value_reg.data.insert(
            "description".to_string(),
            json!(format!("Last actual value of {}", target_id)),
        );
        last_value_reg.is_arch_state = true;
        last_value_reg.uarch_time = None; // Written at end of instruction
        self.graph.add_node(last_value_reg);

        // Connect predictor to read last value
        let mut read_last_data = HashMap::new();
        read_last_data.insert("type".to_string(), json!("state_read"));
        read_last_data.insert(
            "description".to_string(),
            json!("Read last value for prediction"),
        );
        let read_last_edge = Edge::new(
            last_value_id.clone(),
            predictor_id.clone(),
            None,
            Some(read_last_data),
        );
        self.graph.add_edge(read_last_edge);

        // Step 2c: Create predicted value register
        let predicted_reg_id = format!("{}_predicted", target_id);
        let mut predicted_reg = Node::with_defaults(Some(predicted_reg_id.clone()));
        predicted_reg.data.insert("type".to_string(), json!("architectural_state"));
        predicted_reg.data.insert("name".to_string(), json!(predicted_reg_id));
        predicted_reg.data.insert(
            "description".to_string(),
            json!(format!("Predicted value of {}", target_id)),
        );
        predicted_reg.is_arch_state = true;
        predicted_reg.uarch_time = Some(target_time);
        self.graph.add_node(predicted_reg);
        self.predicted_node_id = Some(predicted_reg_id.clone());

        // Connect predictor to predicted register
        let mut pred_assign_data = HashMap::new();
        pred_assign_data.insert("type".to_string(), json!("assignment"));
        pred_assign_data.insert(
            "description".to_string(),
            json!("Store predicted value"),
        );
        let pred_assign_edge = Edge::new(
            predictor_id,
            predicted_reg_id.clone(),
            None,
            Some(pred_assign_data),
        );
        self.graph.add_edge(pred_assign_edge);

        info!("  Created prediction register: {}", predicted_reg_id);

        // Step 2d: Create misprediction detector
        let mispredict_detect_id = format!("{}_mispredict_detect", target_id);
        let mut mispredict_detect = Node::with_defaults(Some(mispredict_detect_id.clone()));
        mispredict_detect.data.insert("type".to_string(), json!("operation"));
        mispredict_detect.data.insert("op".to_string(), json!("!="));
        mispredict_detect.data.insert(
            "description".to_string(),
            json!(format!("Detect misprediction of {}", target_id)),
        );
        mispredict_detect.uarch_time = current_time;
        self.graph.add_node(mispredict_detect);

        // Connect actual value and predicted value to detector
        let mut actual_data = HashMap::new();
        actual_data.insert("type".to_string(), json!("operand"));
        actual_data.insert("operand_idx".to_string(), json!(0));
        let actual_edge = Edge::new(
            target_id.clone(),
            mispredict_detect_id.clone(),
            None,
            Some(actual_data),
        );
        self.graph.add_edge(actual_edge);

        let mut pred_read_data = HashMap::new();
        pred_read_data.insert("type".to_string(), json!("operand"));
        pred_read_data.insert("operand_idx".to_string(), json!(1));
        let pred_read_edge = Edge::new(
            predicted_reg_id.clone(),
            mispredict_detect_id.clone(),
            None,
            Some(pred_read_data),
        );
        self.graph.add_edge(pred_read_edge);

        info!("  Created misprediction detector: {}", mispredict_detect_id);

        // Step 2e: Create correction mux (select predicted or actual based on misprediction)
        let correction_mux_id = format!("{}_correction_mux", target_id);
        let mut correction_mux = Node::with_defaults(Some(correction_mux_id.clone()));
        correction_mux.data.insert("type".to_string(), json!("ternary_op"));
        correction_mux.data.insert(
            "description".to_string(),
            json!("Correct mispredicted value"),
        );
        correction_mux.uarch_time = current_time;
        self.graph.add_node(correction_mux);

        // Ternary: condition ? true_val : false_val
        // If mispredicted, use actual value; else use predicted value
        let mut cond_data = HashMap::new();
        cond_data.insert("type".to_string(), json!("ternary_condition"));
        let cond_edge = Edge::new(
            mispredict_detect_id.clone(),
            correction_mux_id.clone(),
            None,
            Some(cond_data),
        );
        self.graph.add_edge(cond_edge);

        let mut true_data = HashMap::new();
        true_data.insert("type".to_string(), json!("ternary_true"));
        let true_edge = Edge::new(
            target_id.clone(),
            correction_mux_id.clone(),
            None,
            Some(true_data),
        );
        self.graph.add_edge(true_edge);

        let mut false_data = HashMap::new();
        false_data.insert("type".to_string(), json!("ternary_false"));
        let false_edge = Edge::new(
            predicted_reg_id.clone(),
            correction_mux_id.clone(),
            None,
            Some(false_data),
        );
        self.graph.add_edge(false_edge);

        info!("  Created correction mux: {}", correction_mux_id);

        // Track correction logic node IDs before replace_node_uses
        self.correction_logic_ids = vec![
            mispredict_detect_id,
            correction_mux_id.clone(),
        ];

        // Step 2f: Replace uses of original target with correction mux
        self._replace_node_uses(&target_id, &correction_mux_id);

        // Step 2g: Update last_value register with actual value
        let mut update_last_data = HashMap::new();
        update_last_data.insert("type".to_string(), json!("assignment"));
        update_last_data.insert(
            "description".to_string(),
            json!("Update last value"),
        );
        let update_last_edge = Edge::new(
            target_id.clone(),
            last_value_id,
            None,
            Some(update_last_data),
        );
        self.graph.add_edge(update_last_edge);

        info!(
            "  Replaced uses of {} with corrected prediction",
            target_id
        );

        true
    }

    /// Duplicate the computation tree rooted at `root_id` to run at `target_time`.
    ///
    /// Returns a list of duplicated node IDs, with root equivalent first.
    fn _duplicate_computation_tree(
        &mut self,
        root_id: &str,
        target_time: usize,
    ) -> Vec<String> {
        debug!("");
        debug!("  Duplicating computation tree for {}...", root_id);

        // Collect data from root node before mutating the graph
        let (root_data, incoming_edge_info) = match self.graph.get_node(root_id) {
            Some(root_node) => {
                let data = root_node.data.clone();
                let edge_ids: Vec<String> = root_node.incoming_edges.iter().cloned().collect();
                // Collect edge info: (source_id, edge_data) for relevant edges
                let mut edge_info = Vec::new();
                for eid in &edge_ids {
                    if let Some(edge) = self.graph.get_edge(eid) {
                        let edge_type = edge
                            .data
                            .get("type")
                            .and_then(|v| v.as_str())
                            .unwrap_or("");
                        if edge_type == "operand" || edge_type == "data" || edge_type == "control" {
                            edge_info.push((edge.source.clone(), edge.data.clone()));
                        }
                    }
                }
                (data, edge_info)
            }
            None => return Vec::new(),
        };

        // Create a duplicate of the root node
        let dup_id = format!("{}_precomp_dup", root_id);
        let mut dup_node = Node::with_defaults(Some(dup_id.clone()));
        dup_node.data = root_data;
        dup_node.is_arch_state = false;
        dup_node.is_uarch_state = false;
        dup_node.uarch_time = Some(target_time as i64);
        self.graph.add_node(dup_node);

        // Copy incoming operand edges from original node
        for (source_id, edge_data) in incoming_edge_info {
            let dup_edge = Edge::new(
                source_id.clone(),
                dup_id.clone(),
                None,
                Some(edge_data),
            );
            self.graph.add_edge(dup_edge);
            debug!("    Copied edge: {} -> {}", source_id, dup_id);
        }

        vec![dup_id]
    }

    /// Replace all uses of `old_node_id` with `new_node_id` (except specific exclusions).
    fn _replace_node_uses(&mut self, old_node_id: &str, new_node_id: &str) {
        // Collect outgoing edge IDs from old_node
        let outgoing_edge_ids: Vec<String> = match self.graph.get_node(old_node_id) {
            Some(node) => node.outgoing_edges.iter().cloned().collect(),
            None => return,
        };

        // Determine which edges to redirect: collect (edge_id, target_id, edge_data)
        let mut edges_to_modify: Vec<(String, String, HashMap<String, Value>)> = Vec::new();

        for edge_id in &outgoing_edge_ids {
            let (target_id, edge_data) = match self.graph.get_edge(edge_id) {
                Some(edge) => (edge.target.clone(), edge.data.clone()),
                None => continue,
            };

            // Don't replace edges we just created for precomputation register
            if let Some(ref precomp_id) = self.precomputed_node_id {
                if target_id == *precomp_id {
                    continue;
                }
            }

            // Don't replace edges we just created for predicted register
            if let Some(ref pred_id) = self.predicted_node_id {
                if target_id == *pred_id {
                    continue;
                }
            }

            // Don't replace edges going to correction logic nodes
            if self.correction_logic_ids.contains(&target_id) {
                continue;
            }

            // Don't replace edges going to last_value register
            if target_id.ends_with("_last_value") {
                continue;
            }

            // Don't replace edges going to mispredict_detect for this node
            if target_id == format!("{}_mispredict_detect", old_node_id) {
                continue;
            }

            edges_to_modify.push((edge_id.clone(), target_id, edge_data));
        }

        // Redirect edges: remove old, create new from new_node_id to same target
        for (edge_id, target_id, edge_data) in edges_to_modify {
            self.graph.remove_edge(&edge_id);

            let new_edge = Edge::new(
                new_node_id.to_string(),
                target_id,
                None,
                Some(edge_data),
            );
            self.graph.add_edge(new_edge);
        }
    }
}

// ---------------------------------------------------------------------------
// Standalone functions
// ---------------------------------------------------------------------------

/// Apply architectural retiming optimization to a target node.
///
/// # Arguments
/// * `graph` - The ResourceGraph to optimize
/// * `target_node_id` - ID of the critical signal to optimize
/// * `strategy` - Either "precomputation" or "prediction"
/// * `depth` - How many cycles early to compute/predict (must be <= target node's uarch_time)
///
/// # Returns
/// `true` if optimization was successfully applied.
///
/// # Examples
/// ```ignore
/// // Apply precomputation to compute ALU result 1 cycle early
/// apply_architectural_retiming(&mut graph, "alu_result", "precomputation", 1);
///
/// // Apply prediction to predict memory address 2 cycles early
/// // (assumes mem_addr is at uarch_time >= 2)
/// apply_architectural_retiming(&mut graph, "mem_addr", "prediction", 2);
/// ```
pub fn apply_architectural_retiming(
    graph: &mut ResourceGraph,
    target_node_id: &str,
    strategy: &str,
    depth: usize,
) -> bool {
    let mut pass = ArchitecturalRetimingPass::new(graph);
    pass.apply(target_node_id, strategy, depth)
}

/// Identify nodes in the graph that are good candidates for architectural retiming.
///
/// Returns a map from node IDs to their retiming properties. Good candidates are
/// typically:
/// - Operation nodes (not state)
/// - Nodes with sufficient `uarch_time` to move earlier
/// - Nodes on critical paths
pub fn get_retimeable_nodes(graph: &ResourceGraph) -> HashMap<String, RetimeableNodeInfo> {
    let mut candidates = HashMap::new();

    for (node_id, node) in &graph.nodes {
        // Skip state nodes
        if node.is_arch_state || node.is_uarch_state {
            continue;
        }

        // Skip nodes without timing info
        let uarch_time = match node.uarch_time {
            Some(t) => t,
            None => continue,
        };

        // Skip early nodes (must be at least cycle 1 to move earlier)
        if uarch_time < 1 {
            continue;
        }

        let node_type = node
            .data
            .get("type")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string();

        candidates.insert(
            node_id.clone(),
            RetimeableNodeInfo {
                uarch_time,
                node_type,
                can_precompute: true, // Most operations can be precomputed
                can_predict: true,    // Most values can be predicted
                max_depth: uarch_time, // Can move up to cycle 0
            },
        );
    }

    candidates
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    /// Helper: create a simple graph with a chain of nodes at different uarch_times.
    fn make_test_graph() -> ResourceGraph {
        let mut graph = ResourceGraph::new();

        // Source node at time 0 (e.g., register file read)
        let mut src = Node::with_defaults(Some("rf_read".to_string()));
        src.data.insert("type".to_string(), json!("read_state"));
        src.uarch_time = Some(0);
        graph.add_node(src);

        // Operation node at time 1 (e.g., ALU computation)
        let mut alu = Node::with_defaults(Some("alu_result".to_string()));
        alu.data.insert("type".to_string(), json!("operation"));
        alu.data.insert("op".to_string(), json!("+"));
        alu.uarch_time = Some(1);
        graph.add_node(alu);

        // Consumer node at time 2
        let mut consumer = Node::with_defaults(Some("consumer".to_string()));
        consumer.data.insert("type".to_string(), json!("operation"));
        consumer.uarch_time = Some(2);
        graph.add_node(consumer);

        // Edges: rf_read -> alu_result -> consumer
        let mut data1 = HashMap::new();
        data1.insert("type".to_string(), json!("operand"));
        graph.add_edge(Edge::new(
            "rf_read".to_string(),
            "alu_result".to_string(),
            None,
            Some(data1),
        ));

        let mut data2 = HashMap::new();
        data2.insert("type".to_string(), json!("data"));
        graph.add_edge(Edge::new(
            "alu_result".to_string(),
            "consumer".to_string(),
            None,
            Some(data2),
        ));

        graph
    }

    #[test]
    fn test_precomputation_basic() {
        let mut graph = make_test_graph();

        let result = apply_architectural_retiming(
            &mut graph,
            "alu_result",
            "precomputation",
            1,
        );
        assert!(result, "Precomputation should succeed");

        // Precomputed register should exist
        assert!(
            graph.nodes.contains_key("alu_result_precomputed"),
            "Precomputed register should be created"
        );

        // Duplicated node should exist
        assert!(
            graph.nodes.contains_key("alu_result_precomp_dup"),
            "Duplicated node should be created"
        );

        // Read node should exist
        assert!(
            graph.nodes.contains_key("alu_result_precomp_read"),
            "Read node should be created"
        );

        // Consumer should now get its input from the precomputed read
        let consumer = graph.get_node("consumer").unwrap();
        let mut fed_by_precomp = false;
        for eid in &consumer.incoming_edges {
            if let Some(edge) = graph.get_edge(eid) {
                if edge.source == "alu_result_precomp_read" {
                    fed_by_precomp = true;
                }
            }
        }
        assert!(
            fed_by_precomp,
            "Consumer should be fed by precomputed read node"
        );
    }

    #[test]
    fn test_prediction_basic() {
        let mut graph = make_test_graph();

        let result = apply_architectural_retiming(
            &mut graph,
            "alu_result",
            "prediction",
            1,
        );
        assert!(result, "Prediction should succeed");

        // Predictor, predicted register, detector, correction mux, last_value should exist
        assert!(graph.nodes.contains_key("alu_result_predictor"));
        assert!(graph.nodes.contains_key("alu_result_predicted"));
        assert!(graph.nodes.contains_key("alu_result_mispredict_detect"));
        assert!(graph.nodes.contains_key("alu_result_correction_mux"));
        assert!(graph.nodes.contains_key("alu_result_last_value"));

        // Consumer should now get its input from the correction mux
        let consumer = graph.get_node("consumer").unwrap();
        let mut fed_by_correction = false;
        for eid in &consumer.incoming_edges {
            if let Some(edge) = graph.get_edge(eid) {
                if edge.source == "alu_result_correction_mux" {
                    fed_by_correction = true;
                }
            }
        }
        assert!(
            fed_by_correction,
            "Consumer should be fed by correction mux"
        );
    }

    #[test]
    fn test_invalid_target() {
        let mut graph = make_test_graph();
        let result = apply_architectural_retiming(
            &mut graph,
            "nonexistent_node",
            "precomputation",
            1,
        );
        assert!(!result, "Should fail for nonexistent target");
    }

    #[test]
    fn test_invalid_strategy() {
        let mut graph = make_test_graph();
        let result = apply_architectural_retiming(
            &mut graph,
            "alu_result",
            "invalid_strategy",
            1,
        );
        assert!(!result, "Should fail for invalid strategy");
    }

    #[test]
    fn test_depth_too_large() {
        let mut graph = make_test_graph();
        // alu_result is at time 1, depth 5 should fail
        let result = apply_architectural_retiming(
            &mut graph,
            "alu_result",
            "precomputation",
            5,
        );
        assert!(!result, "Should fail when depth exceeds uarch_time");
    }

    #[test]
    fn test_get_retimeable_nodes() {
        let graph = make_test_graph();
        let candidates = get_retimeable_nodes(&graph);

        // alu_result at time 1 and consumer at time 2 should be candidates
        assert!(candidates.contains_key("alu_result"));
        assert!(candidates.contains_key("consumer"));

        // rf_read at time 0 should not be a candidate
        assert!(!candidates.contains_key("rf_read"));

        // Check properties of alu_result
        let alu_info = &candidates["alu_result"];
        assert_eq!(alu_info.uarch_time, 1);
        assert_eq!(alu_info.max_depth, 1);
        assert!(alu_info.can_precompute);
        assert!(alu_info.can_predict);
    }

    #[test]
    fn test_state_nodes_not_retimeable() {
        let mut graph = ResourceGraph::new();

        // Arch state node at time 2
        let mut state = Node::with_defaults(Some("rf".to_string()));
        state.is_arch_state = true;
        state.uarch_time = Some(2);
        graph.add_node(state);

        let candidates = get_retimeable_nodes(&graph);
        assert!(
            candidates.is_empty(),
            "Arch state nodes should not be retimeable"
        );
    }

    #[test]
    fn test_precomputation_timing() {
        let mut graph = make_test_graph();

        let result = apply_architectural_retiming(
            &mut graph,
            "alu_result",
            "precomputation",
            1,
        );
        assert!(result, "Precomputation should succeed");

        // The precomp_dup node should have uarch_time = 0 (moved 1 cycle earlier from time 1)
        let precomp_dup = graph.get_node("alu_result_precomp_dup").unwrap();
        assert_eq!(
            precomp_dup.uarch_time,
            Some(0),
            "Precomp_dup node should be at uarch_time 0"
        );

        // The precomputed register should also have uarch_time = 0
        let precomp_reg = graph.get_node("alu_result_precomputed").unwrap();
        assert_eq!(
            precomp_reg.uarch_time,
            Some(0),
            "Precomputed register should be at uarch_time 0"
        );
    }

    #[test]
    fn test_prediction_node_connections() {
        let mut graph = make_test_graph();

        let result = apply_architectural_retiming(
            &mut graph,
            "alu_result",
            "prediction",
            1,
        );
        assert!(result, "Prediction should succeed");

        // Verify: last_value_reg <- state_read edge -> predictor
        let predictor = graph.get_node("alu_result_predictor").unwrap();
        let mut has_state_read_from_last_value = false;
        for eid in &predictor.incoming_edges {
            if let Some(edge) = graph.get_edge(eid) {
                if edge.source == "alu_result_last_value"
                    && edge.data.get("type").and_then(|v| v.as_str()) == Some("state_read")
                {
                    has_state_read_from_last_value = true;
                }
            }
        }
        assert!(has_state_read_from_last_value, "Predictor should have state_read edge from last_value");

        // Verify: predictor -> assignment edge -> predicted_reg
        let predicted_reg = graph.get_node("alu_result_predicted").unwrap();
        let mut has_assignment_from_predictor = false;
        for eid in &predicted_reg.incoming_edges {
            if let Some(edge) = graph.get_edge(eid) {
                if edge.source == "alu_result_predictor"
                    && edge.data.get("type").and_then(|v| v.as_str()) == Some("assignment")
                {
                    has_assignment_from_predictor = true;
                }
            }
        }
        assert!(has_assignment_from_predictor, "Predicted register should have assignment from predictor");

        // Verify: target -> operand[0] edge -> mispredict_detect
        let mispredict = graph.get_node("alu_result_mispredict_detect").unwrap();
        let mut has_operand0_from_target = false;
        let mut has_operand1_from_predicted = false;
        for eid in &mispredict.incoming_edges {
            if let Some(edge) = graph.get_edge(eid) {
                let edge_type = edge.data.get("type").and_then(|v| v.as_str());
                let operand_idx = edge.data.get("operand_idx").and_then(|v| v.as_i64());
                if edge.source == "alu_result" && edge_type == Some("operand") && operand_idx == Some(0) {
                    has_operand0_from_target = true;
                }
                if edge.source == "alu_result_predicted" && edge_type == Some("operand") && operand_idx == Some(1) {
                    has_operand1_from_predicted = true;
                }
            }
        }
        assert!(has_operand0_from_target, "Mispredict detect should have operand[0] from target");
        assert!(has_operand1_from_predicted, "Mispredict detect should have operand[1] from predicted_reg");

        // Verify: mispredict_detect -> ternary_condition -> correction_mux
        // Verify: target -> ternary_true -> correction_mux
        // Verify: predicted_reg -> ternary_false -> correction_mux
        let correction_mux = graph.get_node("alu_result_correction_mux").unwrap();
        let mut has_ternary_condition = false;
        let mut has_ternary_true = false;
        let mut has_ternary_false = false;
        for eid in &correction_mux.incoming_edges {
            if let Some(edge) = graph.get_edge(eid) {
                let edge_type = edge.data.get("type").and_then(|v| v.as_str());
                match edge_type {
                    Some("ternary_condition") if edge.source == "alu_result_mispredict_detect" => {
                        has_ternary_condition = true;
                    }
                    Some("ternary_true") if edge.source == "alu_result" => {
                        has_ternary_true = true;
                    }
                    Some("ternary_false") if edge.source == "alu_result_predicted" => {
                        has_ternary_false = true;
                    }
                    _ => {}
                }
            }
        }
        assert!(has_ternary_condition, "Correction mux should have ternary_condition from mispredict_detect");
        assert!(has_ternary_true, "Correction mux should have ternary_true from target");
        assert!(has_ternary_false, "Correction mux should have ternary_false from predicted_reg");

        // Verify: target -> assignment -> last_value
        let last_value = graph.get_node("alu_result_last_value").unwrap();
        let mut has_assignment_from_target = false;
        for eid in &last_value.incoming_edges {
            if let Some(edge) = graph.get_edge(eid) {
                if edge.source == "alu_result"
                    && edge.data.get("type").and_then(|v| v.as_str()) == Some("assignment")
                {
                    has_assignment_from_target = true;
                }
            }
        }
        assert!(has_assignment_from_target, "Last value should have assignment from target");
    }

    #[test]
    fn test_precomputation_preserves_original() {
        let mut graph = make_test_graph();

        let result = apply_architectural_retiming(
            &mut graph,
            "alu_result",
            "precomputation",
            1,
        );
        assert!(result, "Precomputation should succeed");

        // Original alu_result node should still exist (not removed, just its consumer edges redirected)
        assert!(
            graph.nodes.contains_key("alu_result"),
            "Original alu_result node should still exist after precomputation"
        );
    }

    #[test]
    fn test_depth_2_precomputation() {
        let mut graph = ResourceGraph::new();

        // Source node at time 0
        let mut src = Node::with_defaults(Some("src".to_string()));
        src.data.insert("type".to_string(), json!("read_state"));
        src.uarch_time = Some(0);
        graph.add_node(src);

        // Intermediate node at time 1
        let mut mid = Node::with_defaults(Some("mid".to_string()));
        mid.data.insert("type".to_string(), json!("operation"));
        mid.data.insert("op".to_string(), json!("+"));
        mid.uarch_time = Some(1);
        graph.add_node(mid);

        // Target node at time 3
        let mut target = Node::with_defaults(Some("target_node".to_string()));
        target.data.insert("type".to_string(), json!("operation"));
        target.data.insert("op".to_string(), json!("+"));
        target.uarch_time = Some(3);
        graph.add_node(target);

        // Consumer at time 4
        let mut consumer = Node::with_defaults(Some("consumer2".to_string()));
        consumer.data.insert("type".to_string(), json!("operation"));
        consumer.uarch_time = Some(4);
        graph.add_node(consumer);

        // Edges
        let mut d1 = HashMap::new();
        d1.insert("type".to_string(), json!("operand"));
        graph.add_edge(Edge::new("src".to_string(), "mid".to_string(), None, Some(d1)));

        let mut d2 = HashMap::new();
        d2.insert("type".to_string(), json!("operand"));
        graph.add_edge(Edge::new("mid".to_string(), "target_node".to_string(), None, Some(d2)));

        let mut d3 = HashMap::new();
        d3.insert("type".to_string(), json!("data"));
        graph.add_edge(Edge::new("target_node".to_string(), "consumer2".to_string(), None, Some(d3)));

        let result = apply_architectural_retiming(
            &mut graph,
            "target_node",
            "precomputation",
            2,
        );
        assert!(result, "Depth-2 precomputation should succeed");

        // precomp_dup should be at time 3 - 2 = 1
        let precomp_dup = graph.get_node("target_node_precomp_dup").unwrap();
        assert_eq!(
            precomp_dup.uarch_time,
            Some(1),
            "Precomp_dup node should be at uarch_time 1 (3 - 2)"
        );
    }

    #[test]
    fn test_multiple_consumers_redirected() {
        let mut graph = ResourceGraph::new();

        // Source node at time 0
        let mut src = Node::with_defaults(Some("src".to_string()));
        src.data.insert("type".to_string(), json!("read_state"));
        src.uarch_time = Some(0);
        graph.add_node(src);

        // Operation node at time 1
        let mut op = Node::with_defaults(Some("op_node".to_string()));
        op.data.insert("type".to_string(), json!("operation"));
        op.data.insert("op".to_string(), json!("+"));
        op.uarch_time = Some(1);
        graph.add_node(op);

        // Three consumer nodes at time 2
        for i in 0..3 {
            let id = format!("consumer_{}", i);
            let mut c = Node::with_defaults(Some(id.clone()));
            c.data.insert("type".to_string(), json!("operation"));
            c.uarch_time = Some(2);
            graph.add_node(c);

            let mut d = HashMap::new();
            d.insert("type".to_string(), json!("data"));
            graph.add_edge(Edge::new("op_node".to_string(), id, None, Some(d)));
        }

        // Edge from src to op_node
        let mut d = HashMap::new();
        d.insert("type".to_string(), json!("operand"));
        graph.add_edge(Edge::new("src".to_string(), "op_node".to_string(), None, Some(d)));

        let result = apply_architectural_retiming(
            &mut graph,
            "op_node",
            "precomputation",
            1,
        );
        assert!(result, "Precomputation should succeed");

        // All 3 consumers should now be fed by the precomp_read node
        for i in 0..3 {
            let consumer_id = format!("consumer_{}", i);
            let consumer = graph.get_node(&consumer_id).unwrap();
            let mut fed_by_precomp = false;
            for eid in &consumer.incoming_edges {
                if let Some(edge) = graph.get_edge(eid) {
                    if edge.source == "op_node_precomp_read" {
                        fed_by_precomp = true;
                    }
                }
            }
            assert!(
                fed_by_precomp,
                "Consumer {} should be fed by precomp_read node",
                consumer_id
            );
        }
    }
}
