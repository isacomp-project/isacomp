//! Return Address Stack (RAS) Optimization for ResourceGraph.
//!
//! Predicts return addresses by maintaining a stack of call return addresses.
//! Pushes PC+4 on call, pops predicted target on return.
//! Integrates with control hazard flush and branch prediction infrastructure.
//! Follows the 7-phase optimization pattern (analysis, planning, structure,
//! hardware, connection, cleanup, timing).

use log::info;
use serde_json::json;
use std::collections::{HashMap, HashSet, VecDeque};

use crate::hardware_builders::{create_index_comparator, create_or_get_literal};
use crate::resource_graph::{Edge, Node, ResourceGraph};

// ---------------------------------------------------------------------------
// Helpers (same pattern as branch_target_buffer.rs)
// ---------------------------------------------------------------------------

fn make_edge(source: &str, target: &str) -> Edge {
    Edge::new(source.to_string(), target.to_string(), None, None)
}

fn make_edge_with_data(
    source: &str,
    target: &str,
    data: HashMap<String, serde_json::Value>,
) -> Edge {
    Edge::new(source.to_string(), target.to_string(), None, Some(data))
}

fn typed_edge(source: &str, target: &str, edge_type: &str) -> Edge {
    let mut data = HashMap::new();
    data.insert("type".to_string(), json!(edge_type));
    make_edge_with_data(source, target, data)
}

fn operand_edge(source: &str, target: &str, position: &str) -> Edge {
    let mut data = HashMap::new();
    data.insert("type".to_string(), json!("operand"));
    data.insert("position".to_string(), json!(position));
    make_edge_with_data(source, target, data)
}

// ---------------------------------------------------------------------------
// CallSpec
// ---------------------------------------------------------------------------

/// Specification for a call instruction pattern.
#[derive(Debug, Clone)]
pub struct CallSpec {
    /// Instruction enable signal (e.g. `jal_enable`)
    pub enable_node_id: String,
    /// Destination register number node (None for unconditional calls like MIPS JAL)
    pub dest_reg_node_id: Option<String>,
    /// Return address value node (PC+4)
    pub return_addr_node_id: String,
}

// ---------------------------------------------------------------------------
// ReturnSpec
// ---------------------------------------------------------------------------

/// Specification for a return instruction pattern.
#[derive(Debug, Clone)]
pub struct ReturnSpec {
    /// Instruction enable signal (e.g. `jalr_enable`)
    pub enable_node_id: String,
    /// Source register number node (None for unconditional returns from LR)
    pub src_reg_node_id: Option<String>,
    /// Destination register node (must be 0 for return). None if never links.
    pub dest_reg_node_id: Option<String>,
}

// ---------------------------------------------------------------------------
// RASSpec
// ---------------------------------------------------------------------------

/// Full specification for Return Address Stack optimization.
#[derive(Debug, Clone)]
pub struct RASSpec {
    pub call_specs: Vec<CallSpec>,
    pub return_specs: Vec<ReturnSpec>,
    /// Which register numbers indicate call/return (e.g. [1, 5] for x1, x5)
    pub link_registers: Vec<i64>,
    /// Number of stack entries (power of 2)
    pub ras_depth: usize,
    /// Address width in bits
    pub ras_width: usize,
    /// Node that holds the predicted next PC
    pub predicted_pc_node_id: String,
    /// Node that holds PC+4 (default prediction)
    pub default_prediction_node_id: String,
    /// Control hazard flush signal node
    pub control_hazard_flush_node_id: String,
    /// Computed JALR target for misprediction detection
    pub jalr_target_node_id: String,
    /// Optional: Execute-stage JALR enable for misprediction timing
    pub jalr_execute_enable_node_id: Option<String>,
    /// Optional: Return branch taken signal for conditional returns (e.g. OpenPOWER bclr)
    pub return_branch_taken_node_id: Option<String>,
    /// Use combinational (not registered) validity gating on RAS operations
    pub use_combinational_validity: bool,
}

impl RASSpec {
    /// Create a new RASSpec with required fields; optional fields get defaults.
    pub fn new(
        call_specs: Vec<CallSpec>,
        return_specs: Vec<ReturnSpec>,
        predicted_pc_node_id: String,
        default_prediction_node_id: String,
        control_hazard_flush_node_id: String,
        jalr_target_node_id: String,
    ) -> Self {
        Self {
            call_specs,
            return_specs,
            link_registers: vec![1, 5],
            ras_depth: 8,
            ras_width: 32,
            predicted_pc_node_id,
            default_prediction_node_id,
            control_hazard_flush_node_id,
            jalr_target_node_id,
            jalr_execute_enable_node_id: None,
            return_branch_taken_node_id: None,
            use_combinational_validity: false,
        }
    }
}

// ---------------------------------------------------------------------------
// RASAnalysis (internal)
// ---------------------------------------------------------------------------

struct RASAnalysis {
    /// Validated call specs with resolved node IDs
    call_nodes: Vec<CallAnalysis>,
    /// Validated return specs with resolved node IDs
    return_nodes: Vec<ReturnAnalysis>,
    /// Required infrastructure node IDs (validated)
    predicted_pc_id: String,
    default_prediction_id: String,
    control_hazard_flush_id: String,
    jalr_target_id: String,
    jalr_execute_enable_id: Option<String>,
    return_branch_taken_id: Option<String>,
    /// Pipeline stage where call/return is detected
    decode_stage: i64,
}

#[derive(Clone)]
struct CallAnalysis {
    enable_id: String,
    dest_reg_id: Option<String>,
    return_addr_id: String,
}

#[derive(Clone)]
struct ReturnAnalysis {
    enable_id: String,
    src_reg_id: Option<String>,
    dest_reg_id: Option<String>,
}

// ---------------------------------------------------------------------------
// RASOptimization
// ---------------------------------------------------------------------------

pub struct RASOptimization<'a> {
    graph: &'a mut ResourceGraph,
    spec: RASSpec,
    ras_node_ids: HashMap<String, String>,
    analysis: Option<RASAnalysis>,
}

impl<'a> RASOptimization<'a> {
    pub fn new(graph: &'a mut ResourceGraph, spec: RASSpec) -> Self {
        Self {
            graph,
            spec,
            ras_node_ids: HashMap::new(),
            analysis: None,
        }
    }

    /// Apply the 7-phase RAS optimization. Returns true on success.
    pub fn apply(&mut self) -> bool {
        info!("Applying Return Address Stack (RAS) optimization");

        // Phase 1: Analysis
        info!("--- Phase 1: ANALYSIS ---");
        let analysis = match self.analyze() {
            Some(a) => a,
            None => {
                info!("Analysis failed - RAS optimization not applicable");
                return false;
            }
        };
        self.analysis = Some(analysis);

        // Phase 2: Planning
        info!("--- Phase 2: PLANNING ---");
        self.plan();

        // Phase 3: Structure
        info!("--- Phase 3: STRUCTURE ---");
        self.create_structure();

        // Phase 4: Hardware
        info!("--- Phase 4: HARDWARE ---");
        self.generate_hardware();

        // Phase 5: Connection
        info!("--- Phase 5: CONNECTION ---");
        self.wire_components();

        // Phase 6: Cleanup
        info!("--- Phase 6: CLEANUP ---");
        info!("  No cleanup needed - RAS optimization is additive");

        // Phase 7: Timing
        info!("--- Phase 7: TIMING ---");
        self.graph.infer_uarch_time(true);

        info!("RAS optimization completed successfully");
        true
    }

    // =====================================================================
    // Phase 1: ANALYSIS
    // =====================================================================

    fn analyze(&self) -> Option<RASAnalysis> {
        let mut call_nodes = Vec::new();
        let mut return_nodes = Vec::new();

        // Validate call specifications
        info!("  Validating call specifications...");
        for (i, cs) in self.spec.call_specs.iter().enumerate() {
            if !self.graph.nodes.contains_key(&cs.enable_node_id) {
                info!("    Warning: Call enable node '{}' not found", cs.enable_node_id);
                continue;
            }
            if let Some(ref dr) = cs.dest_reg_node_id {
                if !self.graph.nodes.contains_key(dr) {
                    info!("    Warning: Call dest_reg node '{}' not found", dr);
                    continue;
                }
            }
            if !self.graph.nodes.contains_key(&cs.return_addr_node_id) {
                info!("    Warning: Call return_addr node '{}' not found", cs.return_addr_node_id);
                continue;
            }
            info!("    Call pattern {}: {} -> push", i, cs.enable_node_id);
            call_nodes.push(CallAnalysis {
                enable_id: cs.enable_node_id.clone(),
                dest_reg_id: cs.dest_reg_node_id.clone(),
                return_addr_id: cs.return_addr_node_id.clone(),
            });
        }

        // Validate return specifications
        info!("  Validating return specifications...");
        for (i, rs) in self.spec.return_specs.iter().enumerate() {
            if !self.graph.nodes.contains_key(&rs.enable_node_id) {
                info!("    Warning: Return enable node '{}' not found", rs.enable_node_id);
                continue;
            }
            if let Some(ref sr) = rs.src_reg_node_id {
                if !self.graph.nodes.contains_key(sr) {
                    info!("    Warning: Return src_reg node '{}' not found", sr);
                    continue;
                }
            }
            if let Some(ref dr) = rs.dest_reg_node_id {
                if !self.graph.nodes.contains_key(dr) {
                    info!("    Warning: Return dest_reg node '{}' not found", dr);
                    continue;
                }
            }
            info!("    Return pattern {}: {} -> pop", i, rs.enable_node_id);
            return_nodes.push(ReturnAnalysis {
                enable_id: rs.enable_node_id.clone(),
                src_reg_id: rs.src_reg_node_id.clone(),
                dest_reg_id: rs.dest_reg_node_id.clone(),
            });
        }

        if call_nodes.is_empty() && return_nodes.is_empty() {
            info!("  ERROR: No valid call or return patterns found");
            return None;
        }

        // Validate required infrastructure nodes
        info!("  Validating required infrastructure nodes...");

        if self.spec.predicted_pc_node_id.is_empty()
            || !self.graph.nodes.contains_key(&self.spec.predicted_pc_node_id)
        {
            info!("  ERROR: predicted_pc node '{}' not found", self.spec.predicted_pc_node_id);
            return None;
        }
        if self.spec.default_prediction_node_id.is_empty()
            || !self.graph.nodes.contains_key(&self.spec.default_prediction_node_id)
        {
            info!("  ERROR: default_prediction node '{}' not found", self.spec.default_prediction_node_id);
            return None;
        }
        if self.spec.control_hazard_flush_node_id.is_empty()
            || !self.graph.nodes.contains_key(&self.spec.control_hazard_flush_node_id)
        {
            info!("  ERROR: control_hazard_flush node '{}' not found", self.spec.control_hazard_flush_node_id);
            return None;
        }
        if self.spec.jalr_target_node_id.is_empty()
            || !self.graph.nodes.contains_key(&self.spec.jalr_target_node_id)
        {
            info!("  ERROR: jalr_target node '{}' not found", self.spec.jalr_target_node_id);
            return None;
        }

        let jalr_execute_enable_id = self
            .spec
            .jalr_execute_enable_node_id
            .as_ref()
            .filter(|id| self.graph.nodes.contains_key(id.as_str()))
            .cloned();

        let return_branch_taken_id = self
            .spec
            .return_branch_taken_node_id
            .as_ref()
            .filter(|id| self.graph.nodes.contains_key(id.as_str()))
            .cloned();

        // Determine decode stage
        let decode_stage = if !call_nodes.is_empty() {
            self.graph
                .nodes
                .get(&call_nodes[0].enable_id)
                .and_then(|n| n.uarch_time)
                .unwrap_or(0)
        } else {
            0
        };
        info!("  Decode stage: {}", decode_stage);

        Some(RASAnalysis {
            call_nodes,
            return_nodes,
            predicted_pc_id: self.spec.predicted_pc_node_id.clone(),
            default_prediction_id: self.spec.default_prediction_node_id.clone(),
            control_hazard_flush_id: self.spec.control_hazard_flush_node_id.clone(),
            jalr_target_id: self.spec.jalr_target_node_id.clone(),
            jalr_execute_enable_id,
            return_branch_taken_id,
            decode_stage,
        })
    }

    // =====================================================================
    // Phase 2: PLANNING
    // =====================================================================

    fn plan(&self) {
        let ptr_width = ptr_width_for_depth(self.spec.ras_depth);
        let analysis = self.analysis.as_ref().unwrap();
        info!("  RAS depth: {} entries", self.spec.ras_depth);
        info!("  RAS width: {} bits", self.spec.ras_width);
        info!("  Pointer width: {} bits", ptr_width);
        info!("  Link registers: {:?}", self.spec.link_registers);
        info!("  Call patterns: {}", analysis.call_nodes.len());
        info!("  Return patterns: {}", analysis.return_nodes.len());
    }

    // =====================================================================
    // Phase 3: STRUCTURE
    // =====================================================================

    fn create_structure(&mut self) {
        let ptr_width = ptr_width_for_depth(self.spec.ras_depth) as i64;
        let ras_width = self.spec.ras_width as i64;
        let decode_stage = self.analysis.as_ref().unwrap().decode_stage;

        // ras_stack
        let mut n = Node::with_defaults(Some("ras_stack".to_string()));
        n.data.insert("type".into(), json!("ras_stack"));
        n.data.insert("name".into(), json!("ras_stack"));
        n.data.insert("display_name".into(), json!("Return Address Stack"));
        n.data.insert("depth".into(), json!(self.spec.ras_depth as i64));
        n.data.insert("bit_width".into(), json!(ras_width));
        n.is_uarch_state = true;
        n.uarch_time = Some(0);
        self.graph.add_node(n);
        self.ras_node_ids.insert("ras_stack".into(), "ras_stack".into());

        // ras_ptr
        let mut n = Node::with_defaults(Some("ras_ptr".to_string()));
        n.data.insert("type".into(), json!("ras_ptr"));
        n.data.insert("name".into(), json!("ras_ptr"));
        n.data.insert("display_name".into(), json!("RAS Stack Pointer"));
        n.data.insert("bit_width".into(), json!(ptr_width));
        n.data.insert("ras_component".into(), json!(true));
        n.is_uarch_state = true;
        n.uarch_time = Some(0);
        self.graph.add_node(n);
        self.ras_node_ids.insert("ras_ptr".into(), "ras_ptr".into());

        // ras_top
        let mut n = Node::with_defaults(Some("ras_top".to_string()));
        n.data.insert("type".into(), json!("var"));
        n.data.insert("name".into(), json!("ras_top"));
        n.data.insert("display_name".into(), json!("RAS Top of Stack (Predicted Return)"));
        n.data.insert("bit_width".into(), json!(ras_width));
        n.uarch_time = Some(0);
        self.graph.add_node(n);
        self.ras_node_ids.insert("ras_top".into(), "ras_top".into());

        // ras_prediction (pipeline register for Execute-stage comparison)
        let mut n = Node::with_defaults(Some("ras_prediction".to_string()));
        n.data.insert("type".into(), json!("pipeline_register"));
        n.data.insert("name".into(), json!("ras_prediction"));
        n.data.insert("display_name".into(), json!("RAS Prediction (pipelined for Execute)"));
        n.data.insert("bit_width".into(), json!(ras_width));
        n.data.insert("ras_component".into(), json!(true));
        n.is_uarch_state = true;
        n.uarch_time = Some(decode_stage + 1);
        self.graph.add_node(n);
        self.ras_node_ids.insert("ras_prediction".into(), "ras_prediction".into());

        // ras_push
        let mut n = Node::with_defaults(Some("ras_push".to_string()));
        n.data.insert("type".into(), json!("var"));
        n.data.insert("name".into(), json!("ras_push"));
        n.data.insert("display_name".into(), json!("RAS Push Enable"));
        n.data.insert("bit_width".into(), json!(1));
        self.graph.add_node(n);
        self.ras_node_ids.insert("ras_push".into(), "ras_push".into());

        // ras_pop
        let mut n = Node::with_defaults(Some("ras_pop".to_string()));
        n.data.insert("type".into(), json!("var"));
        n.data.insert("name".into(), json!("ras_pop"));
        n.data.insert("display_name".into(), json!("RAS Pop Enable"));
        n.data.insert("bit_width".into(), json!(1));
        self.graph.add_node(n);
        self.ras_node_ids.insert("ras_pop".into(), "ras_pop".into());

        // ras_mispredict
        let mut n = Node::with_defaults(Some("ras_mispredict".to_string()));
        n.data.insert("type".into(), json!("var"));
        n.data.insert("name".into(), json!("ras_mispredict"));
        n.data.insert("display_name".into(), json!("RAS Misprediction"));
        n.data.insert("bit_width".into(), json!(1));
        self.graph.add_node(n);
        self.ras_node_ids.insert("ras_mispredict".into(), "ras_mispredict".into());

        // ras_push_valid (flush-gated)
        let mut n = Node::with_defaults(Some("ras_push_valid".to_string()));
        n.data.insert("type".into(), json!("var"));
        n.data.insert("name".into(), json!("ras_push_valid"));
        n.data.insert("display_name".into(), json!("RAS Push Enable (flush-gated)"));
        n.data.insert("bit_width".into(), json!(1));
        n.data.insert("ras_component".into(), json!(true));
        self.graph.add_node(n);
        self.ras_node_ids.insert("ras_push_valid".into(), "ras_push_valid".into());

        // ras_pop_valid (flush-gated)
        let mut n = Node::with_defaults(Some("ras_pop_valid".to_string()));
        n.data.insert("type".into(), json!("var"));
        n.data.insert("name".into(), json!("ras_pop_valid"));
        n.data.insert("display_name".into(), json!("RAS Pop Enable (flush-gated)"));
        n.data.insert("bit_width".into(), json!(1));
        n.data.insert("ras_component".into(), json!(true));
        self.graph.add_node(n);
        self.ras_node_ids.insert("ras_pop_valid".into(), "ras_pop_valid".into());

        info!("  Created RAS structure nodes");
    }

    // =====================================================================
    // Phase 4: HARDWARE
    // =====================================================================

    fn generate_hardware(&mut self) {
        let analysis = self.analysis.as_ref().unwrap().clone_ids();
        let ptr_width = ptr_width_for_depth(self.spec.ras_depth) as i64;
        let ras_width = self.spec.ras_width as i64;

        // Create link register literals
        info!("  Creating link register literals...");
        let mut link_literal_ids: Vec<String> = Vec::new();
        for &lr in &self.spec.link_registers {
            let lit_id = create_or_get_literal(self.graph, lr);
            link_literal_ids.push(lit_id);
        }
        let zero_literal_id = create_or_get_literal(self.graph, 0);

        // =================================================================
        // Call detection: push when enable && (dest_reg is link register)
        // =================================================================
        info!("  Creating call detection logic...");
        let mut call_push_signal_ids: Vec<String> = Vec::new();

        for (i, call) in analysis.call_nodes.iter().enumerate() {
            let prefix = format!("ras_call_{}", i);

            if call.dest_reg_id.is_none() {
                // Unconditional call
                info!("    Call pattern {}: unconditional", i);
                call_push_signal_ids.push(call.enable_id.clone());
                continue;
            }
            let dest_reg_id = call.dest_reg_id.as_ref().unwrap();

            // Create comparators for dest_reg vs each link register
            let mut link_check_ids: Vec<String> = Vec::new();
            for (lr, lit_id) in self.spec.link_registers.iter().zip(link_literal_ids.iter()) {
                let comp_id_str = format!("{}_rd_eq_{}", prefix, lr);
                let mut extra = HashMap::new();
                extra.insert("ras_component".into(), json!(true));
                extra.insert("check_type".into(), json!("link_register"));
                let cid = create_index_comparator(
                    self.graph,
                    &comp_id_str,
                    dest_reg_id,
                    lit_id,
                    "==",
                    Some(&format!("rd == {}", lr)),
                    Some(extra),
                );
                link_check_ids.push(cid);
            }

            // OR link register checks
            let rd_is_link_id = if link_check_ids.len() == 1 {
                link_check_ids[0].clone()
            } else {
                let or_id = format!("{}_rd_is_link", prefix);
                let mut n = Node::with_defaults(Some(or_id.clone()));
                n.data.insert("type".into(), json!("operation"));
                n.data.insert("operator".into(), json!("||"));
                n.data.insert("name".into(), json!(&or_id));
                n.data.insert("display_name".into(), json!("rd is link register"));
                n.data.insert("bit_width".into(), json!(1));
                n.data.insert("ras_component".into(), json!(true));
                self.graph.add_node(n);
                for chk in &link_check_ids {
                    self.graph.add_edge(typed_edge(chk, &or_id, "operand"));
                }
                or_id
            };

            // AND with enable
            let is_call_id = format!("{}_is_call", prefix);
            let mut n = Node::with_defaults(Some(is_call_id.clone()));
            n.data.insert("type".into(), json!("operation"));
            n.data.insert("operator".into(), json!("&&"));
            n.data.insert("name".into(), json!(&is_call_id));
            n.data.insert("display_name".into(), json!(format!("Call detected ({})", call.enable_id)));
            n.data.insert("bit_width".into(), json!(1));
            n.data.insert("ras_component".into(), json!(true));
            self.graph.add_node(n);
            self.graph.add_edge(operand_edge(&call.enable_id, &is_call_id, "left"));
            self.graph.add_edge(operand_edge(&rd_is_link_id, &is_call_id, "right"));
            call_push_signal_ids.push(is_call_id);
        }

        // =================================================================
        // Return detection
        // =================================================================
        info!("  Creating return detection logic...");
        let mut return_pop_signal_ids: Vec<String> = Vec::new();

        for (i, ret) in analysis.return_nodes.iter().enumerate() {
            let prefix = format!("ras_return_{}", i);

            if ret.src_reg_id.is_none() && ret.dest_reg_id.is_none() {
                info!("    Return pattern {}: unconditional", i);
                return_pop_signal_ids.push(ret.enable_id.clone());
                continue;
            }

            let mut conditions: Vec<String> = Vec::new();

            // Check src_reg vs link registers
            if let Some(ref src_reg_id) = ret.src_reg_id {
                let mut link_check_ids: Vec<String> = Vec::new();
                for (lr, lit_id) in self.spec.link_registers.iter().zip(link_literal_ids.iter()) {
                    let comp_id_str = format!("{}_rs1_eq_{}", prefix, lr);
                    let mut extra = HashMap::new();
                    extra.insert("ras_component".into(), json!(true));
                    extra.insert("check_type".into(), json!("link_register"));
                    let cid = create_index_comparator(
                        self.graph,
                        &comp_id_str,
                        src_reg_id,
                        lit_id,
                        "==",
                        Some(&format!("rs1 == {}", lr)),
                        Some(extra),
                    );
                    link_check_ids.push(cid);
                }
                let rs1_is_link_id = if link_check_ids.len() == 1 {
                    link_check_ids[0].clone()
                } else {
                    let or_id = format!("{}_rs1_is_link", prefix);
                    let mut n = Node::with_defaults(Some(or_id.clone()));
                    n.data.insert("type".into(), json!("operation"));
                    n.data.insert("operator".into(), json!("||"));
                    n.data.insert("name".into(), json!(&or_id));
                    n.data.insert("display_name".into(), json!("rs1 is link register"));
                    n.data.insert("bit_width".into(), json!(1));
                    n.data.insert("ras_component".into(), json!(true));
                    self.graph.add_node(n);
                    for chk in &link_check_ids {
                        self.graph.add_edge(typed_edge(chk, &or_id, "operand"));
                    }
                    or_id
                };
                conditions.push(rs1_is_link_id);
            }

            // Check dest_reg == 0
            if let Some(ref dest_reg_id) = ret.dest_reg_id {
                let comp_id_str = format!("{}_rd_eq_0", prefix);
                let mut extra = HashMap::new();
                extra.insert("ras_component".into(), json!(true));
                extra.insert("check_type".into(), json!("return_pattern"));
                let cid = create_index_comparator(
                    self.graph,
                    &comp_id_str,
                    dest_reg_id,
                    &zero_literal_id,
                    "==",
                    Some("rd == 0"),
                    Some(extra),
                );
                conditions.push(cid);
            }

            if conditions.is_empty() {
                return_pop_signal_ids.push(ret.enable_id.clone());
                continue;
            }

            let is_return_pattern_id = if conditions.len() == 1 {
                conditions[0].clone()
            } else {
                // AND: rs1_is_link && rd_is_zero
                let pat_id = format!("{}_pattern", prefix);
                let mut n = Node::with_defaults(Some(pat_id.clone()));
                n.data.insert("type".into(), json!("operation"));
                n.data.insert("operator".into(), json!("&&"));
                n.data.insert("name".into(), json!(&pat_id));
                n.data.insert("display_name".into(), json!("Return pattern (rs1=link, rd=0)"));
                n.data.insert("bit_width".into(), json!(1));
                n.data.insert("ras_component".into(), json!(true));
                self.graph.add_node(n);
                self.graph.add_edge(operand_edge(&conditions[0], &pat_id, "left"));
                self.graph.add_edge(operand_edge(&conditions[1], &pat_id, "right"));
                pat_id
            };

            // AND with enable
            let is_return_id = format!("{}_is_return", prefix);
            let mut n = Node::with_defaults(Some(is_return_id.clone()));
            n.data.insert("type".into(), json!("operation"));
            n.data.insert("operator".into(), json!("&&"));
            n.data.insert("name".into(), json!(&is_return_id));
            n.data.insert("display_name".into(), json!(format!("Return detected ({})", ret.enable_id)));
            n.data.insert("bit_width".into(), json!(1));
            n.data.insert("ras_component".into(), json!(true));
            self.graph.add_node(n);
            self.graph.add_edge(operand_edge(&ret.enable_id, &is_return_id, "left"));
            self.graph.add_edge(operand_edge(&is_return_pattern_id, &is_return_id, "right"));
            return_pop_signal_ids.push(is_return_id);
        }

        // =================================================================
        // Combine call signals -> ras_push
        // =================================================================
        info!("  Combining call signals into ras_push...");
        let ras_push_id = "ras_push";
        if call_push_signal_ids.is_empty() {
            let z = create_or_get_literal(self.graph, 0);
            self.graph.add_edge(typed_edge(&z, ras_push_id, "assignment"));
        } else if call_push_signal_ids.len() == 1 {
            self.graph.add_edge(typed_edge(&call_push_signal_ids[0], ras_push_id, "assignment"));
        } else {
            let final_or = self.build_or_chain("ras_push_or", &call_push_signal_ids);
            self.graph.add_edge(typed_edge(&final_or, ras_push_id, "assignment"));
        }

        // =================================================================
        // Combine return signals -> ras_pop
        // =================================================================
        info!("  Combining return signals into ras_pop...");
        let ras_pop_id = "ras_pop";
        if return_pop_signal_ids.is_empty() {
            let z = create_or_get_literal(self.graph, 0);
            self.graph.add_edge(typed_edge(&z, ras_pop_id, "assignment"));
        } else if return_pop_signal_ids.len() == 1 {
            self.graph.add_edge(typed_edge(&return_pop_signal_ids[0], ras_pop_id, "assignment"));
        } else {
            let final_or = self.build_or_chain("ras_pop_or", &return_pop_signal_ids);
            self.graph.add_edge(typed_edge(&final_or, ras_pop_id, "assignment"));
        }

        // =================================================================
        // Stack pointer update logic
        // =================================================================
        info!("  Creating stack pointer update logic...");
        let one_literal_id = create_or_get_literal(self.graph, 1);

        // ras_ptr_inc = ras_ptr + 1
        {
            let nid = "ras_ptr_inc";
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("operation"));
            n.data.insert("operator".into(), json!("+"));
            n.data.insert("name".into(), json!(nid));
            n.data.insert("display_name".into(), json!("ras_ptr + 1"));
            n.data.insert("bit_width".into(), json!(ptr_width));
            n.data.insert("ras_component".into(), json!(true));
            self.graph.add_node(n);
            self.graph.add_edge(operand_edge("ras_ptr", nid, "left"));
            self.graph.add_edge(operand_edge(&one_literal_id, nid, "right"));
        }

        // ras_ptr_dec = ras_ptr - 1
        {
            let nid = "ras_ptr_dec";
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("operation"));
            n.data.insert("operator".into(), json!("-"));
            n.data.insert("name".into(), json!(nid));
            n.data.insert("display_name".into(), json!("ras_ptr - 1"));
            n.data.insert("bit_width".into(), json!(ptr_width));
            n.data.insert("ras_component".into(), json!(true));
            self.graph.add_node(n);
            self.graph.add_edge(operand_edge("ras_ptr", nid, "left"));
            self.graph.add_edge(operand_edge(&one_literal_id, nid, "right"));
        }

        // ras_ptr_next mux
        {
            let nid = "ras_ptr_next";
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("ras_ptr_update"));
            n.data.insert("name".into(), json!(nid));
            n.data.insert("display_name".into(), json!("RAS pointer next value"));
            n.data.insert("bit_width".into(), json!(ptr_width));
            n.data.insert("ras_component".into(), json!(true));
            n.data.insert("push_signal".into(), json!("ras_push"));
            n.data.insert("pop_signal".into(), json!("ras_pop"));
            n.data.insert("ptr_inc".into(), json!("ras_ptr_inc"));
            n.data.insert("ptr_dec".into(), json!("ras_ptr_dec"));
            n.data.insert("ptr_current".into(), json!("ras_ptr"));
            self.graph.add_node(n);
            self.ras_node_ids.insert("ras_ptr_next".into(), nid.into());

            // control edges
            let mut d = HashMap::new();
            d.insert("type".into(), json!("control"));
            d.insert("signal".into(), json!("push"));
            self.graph.add_edge(make_edge_with_data("ras_push", nid, d));

            let mut d = HashMap::new();
            d.insert("type".into(), json!("control"));
            d.insert("signal".into(), json!("pop"));
            self.graph.add_edge(make_edge_with_data("ras_pop", nid, d));

            // mux_input edges
            let mut d = HashMap::new();
            d.insert("type".into(), json!("mux_input"));
            d.insert("input_index".into(), json!(0));
            d.insert("condition".into(), json!("push"));
            self.graph.add_edge(make_edge_with_data("ras_ptr_inc", nid, d));

            let mut d = HashMap::new();
            d.insert("type".into(), json!("mux_input"));
            d.insert("input_index".into(), json!(1));
            d.insert("condition".into(), json!("pop"));
            self.graph.add_edge(make_edge_with_data("ras_ptr_dec", nid, d));

            self.graph.add_edge(typed_edge("ras_ptr", nid, "mux_default_input"));

            // Register update
            let mut d = HashMap::new();
            d.insert("type".into(), json!("assignment"));
            d.insert("register_update".into(), json!(true));
            self.graph.add_edge(make_edge_with_data(nid, "ras_ptr", d));
        }

        // =================================================================
        // RAS read logic (top of stack)
        // =================================================================
        info!("  Creating RAS read logic...");
        {
            // ras_read_idx = ras_ptr - 1
            let nid = "ras_read_idx";
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("operation"));
            n.data.insert("operator".into(), json!("-"));
            n.data.insert("name".into(), json!(nid));
            n.data.insert("display_name".into(), json!("ras_ptr - 1 (TOS index)"));
            n.data.insert("bit_width".into(), json!(ptr_width));
            n.data.insert("ras_component".into(), json!(true));
            self.graph.add_node(n);
            self.graph.add_edge(operand_edge("ras_ptr", nid, "left"));
            self.graph.add_edge(operand_edge(&one_literal_id, nid, "right"));
        }
        {
            // ras_stack_read
            let nid = "ras_stack_read";
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("array_read"));
            n.data.insert("name".into(), json!(nid));
            n.data.insert("display_name".into(), json!("ras_stack[ras_ptr-1]"));
            n.data.insert("bit_width".into(), json!(ras_width));
            n.data.insert("array".into(), json!("ras_stack"));
            n.data.insert("ras_component".into(), json!(true));
            self.graph.add_node(n);
            self.graph.add_edge(typed_edge("ras_stack", nid, "array_base"));
            self.graph.add_edge(typed_edge("ras_read_idx", nid, "array_index"));
            self.graph.add_edge(typed_edge(nid, "ras_top", "assignment"));
        }

        // =================================================================
        // RAS write logic
        // =================================================================
        info!("  Creating RAS write logic...");
        if !analysis.call_nodes.is_empty() {
            let return_addr_id = &analysis.call_nodes[0].return_addr_id;
            let decode_stage = analysis.decode_stage;

            // Try to use Decode-stage pipelined PC
            let ras_write_data_id = if self.graph.nodes.contains_key("PIPE_Decode_pc_rd_PIPE") {
                // Determine offset from return_addr name
                let ret_lower = return_addr_id.to_lowercase();
                let offset: i64 = if ret_lower.contains("+ 8") || ret_lower.contains("plus_8") || ret_lower.contains("pc_plus_8") {
                    8
                } else {
                    4
                };
                let offset_lit = create_or_get_literal(self.graph, offset);

                let nid = "ras_return_addr";
                let mut n = Node::with_defaults(Some(nid.to_string()));
                n.data.insert("type".into(), json!("operation"));
                n.data.insert("operator".into(), json!("+"));
                n.data.insert("name".into(), json!(nid));
                n.data.insert("display_name".into(), json!(format!("RAS return address (PIPE_Decode_pc_rd_PIPE + {})", offset)));
                n.data.insert("bit_width".into(), json!(ras_width));
                n.data.insert("ras_component".into(), json!(true));
                n.uarch_time = Some(decode_stage);
                self.graph.add_node(n);
                self.graph.add_edge(operand_edge("PIPE_Decode_pc_rd_PIPE", nid, "left"));
                self.graph.add_edge(operand_edge(&offset_lit, nid, "right"));
                self.ras_node_ids.insert("ras_return_addr".into(), nid.into());
                info!("    Created ras_return_addr = PIPE_Decode_pc_rd_PIPE + {}", offset);
                nid.to_string()
            } else {
                info!("    WARNING: PIPE_Decode_pc_rd_PIPE not found, using original return_addr");
                return_addr_id.clone()
            };

            // ras_stack_write
            let nid = "ras_stack_write";
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("array_write"));
            n.data.insert("name".into(), json!(nid));
            n.data.insert("display_name".into(), json!("ras_stack[ras_ptr] = ret_addr"));
            n.data.insert("bit_width".into(), json!(ras_width));
            n.data.insert("array".into(), json!("ras_stack"));
            n.data.insert("ras_component".into(), json!(true));
            self.graph.add_node(n);
            self.graph.add_edge(typed_edge("ras_stack", nid, "array_base"));
            self.graph.add_edge(typed_edge("ras_ptr", nid, "write_address"));
            self.graph.add_edge(typed_edge(&ras_write_data_id, nid, "write_data"));
            self.graph.add_edge(typed_edge("ras_push", nid, "write_enable"));
        }
    }

    // =====================================================================
    // Phase 5: CONNECTION
    // =====================================================================

    fn wire_components(&mut self) {
        let analysis = self.analysis.as_ref().unwrap().clone_ids();
        let decode_stage = analysis.decode_stage;
        let ras_width = self.spec.ras_width as i64;

        let control_hazard_flush_id = analysis.control_hazard_flush_id.clone();
        let jalr_target_id = analysis.jalr_target_id.clone();

        // Determine if return enable is already validity-gated
        let return_enable_is_validity_gated = if !analysis.return_nodes.is_empty() {
            analysis.return_nodes[0].enable_id.ends_with("_valid")
        } else {
            false
        };

        // The "effective" ras_pop to use for stack operations (may be gated)
        let mut effective_ras_pop_id = "ras_pop".to_string();

        // Gate ras_pop by Decode validity if needed
        if !return_enable_is_validity_gated {
            let decode_valid_id = if self.spec.use_combinational_validity {
                if self.graph.nodes.contains_key("PIPE_Decode_valid_not_flush") {
                    Some("PIPE_Decode_valid_not_flush".to_string())
                } else if self.graph.nodes.contains_key("PIPE_Decode_valid_PIPE") {
                    Some("PIPE_Decode_valid_PIPE".to_string())
                } else {
                    None
                }
            } else if self.graph.nodes.contains_key("PIPE_Decode_valid_PIPE") {
                Some("PIPE_Decode_valid_PIPE".to_string())
            } else if self.graph.nodes.contains_key("PIPE_Decode_valid_not_flush") {
                Some("PIPE_Decode_valid_not_flush".to_string())
            } else {
                None
            };

            if let Some(dv_id) = decode_valid_id {
                info!("  Found Decode validity signal: {}", dv_id);
                let nid = "ras_pop_decode_gated";
                let mut n = Node::with_defaults(Some(nid.to_string()));
                n.data.insert("type".into(), json!("operation"));
                n.data.insert("operator".into(), json!("&&"));
                n.data.insert("name".into(), json!(nid));
                n.data.insert("display_name".into(), json!("ras_pop && decode_valid"));
                n.data.insert("bit_width".into(), json!(1));
                n.data.insert("ras_component".into(), json!(true));
                self.graph.add_node(n);
                self.graph.add_edge(operand_edge("ras_pop", nid, "left"));
                self.graph.add_edge(operand_edge(&dv_id, nid, "right"));
                self.ras_node_ids.insert("ras_pop_decode_gated".into(), nid.into());
                effective_ras_pop_id = nid.to_string();
            }
        }

        // =================================================================
        // Flush/stall gated push/pop
        // =================================================================
        info!("  Creating flush/stall-gated push/pop signals...");

        // !control_hazard_flush
        {
            let nid = "control_hazard_flush_not_ras";
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("operation"));
            n.data.insert("operator".into(), json!("!"));
            n.data.insert("name".into(), json!(nid));
            n.data.insert("display_name".into(), json!("!control_hazard_flush (for RAS)"));
            n.data.insert("bit_width".into(), json!(1));
            n.data.insert("ras_component".into(), json!(true));
            self.graph.add_node(n);
            self.graph.add_edge(typed_edge(&control_hazard_flush_id, nid, "operand"));
        }

        // Find decode stall controller
        let source_node_id = if !analysis.call_nodes.is_empty() {
            Some(analysis.call_nodes[0].enable_id.clone())
        } else {
            None
        };
        let decode_stall_ctrl_id = source_node_id
            .as_ref()
            .and_then(|sid| self.find_stall_controller_for_stage(sid));

        // Create !stall if found
        if let Some(ref ctrl_id) = decode_stall_ctrl_id {
            let nid = "ras_stall_not";
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("operation"));
            n.data.insert("operator".into(), json!("!"));
            n.data.insert("name".into(), json!(nid));
            n.data.insert("display_name".into(), json!("!stall (for RAS)"));
            n.data.insert("bit_width".into(), json!(1));
            n.data.insert("ras_component".into(), json!(true));
            self.graph.add_node(n);
            self.graph.add_edge(typed_edge(ctrl_id, nid, "operand"));
            info!("    Found Decode stall controller: {}", ctrl_id);
        }

        // ras_push_valid = ras_push && !flush [&& !stall]
        {
            let nid = "ras_push_and_not_flush";
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("operation"));
            n.data.insert("operator".into(), json!("&&"));
            n.data.insert("name".into(), json!(nid));
            n.data.insert("display_name".into(), json!("ras_push && !flush"));
            n.data.insert("bit_width".into(), json!(1));
            n.data.insert("ras_component".into(), json!(true));
            self.graph.add_node(n);
            self.graph.add_edge(operand_edge("ras_push", nid, "left"));
            self.graph.add_edge(operand_edge("control_hazard_flush_not_ras", nid, "right"));
        }

        if decode_stall_ctrl_id.is_some() {
            let nid = "ras_push_valid_and";
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("operation"));
            n.data.insert("operator".into(), json!("&&"));
            n.data.insert("name".into(), json!(nid));
            n.data.insert("display_name".into(), json!("ras_push && !flush && !stall"));
            n.data.insert("bit_width".into(), json!(1));
            n.data.insert("ras_component".into(), json!(true));
            self.graph.add_node(n);
            self.graph.add_edge(operand_edge("ras_push_and_not_flush", nid, "left"));
            self.graph.add_edge(operand_edge("ras_stall_not", nid, "right"));
            self.graph.add_edge(typed_edge(nid, "ras_push_valid", "assignment"));
        } else {
            self.graph.add_edge(typed_edge("ras_push_and_not_flush", "ras_push_valid", "assignment"));
        }

        // ras_pop_valid = ras_pop && !flush [&& !stall]
        {
            let nid = "ras_pop_and_not_flush";
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("operation"));
            n.data.insert("operator".into(), json!("&&"));
            n.data.insert("name".into(), json!(nid));
            n.data.insert("display_name".into(), json!("ras_pop && !flush"));
            n.data.insert("bit_width".into(), json!(1));
            n.data.insert("ras_component".into(), json!(true));
            self.graph.add_node(n);
            self.graph.add_edge(operand_edge(&effective_ras_pop_id, nid, "left"));
            self.graph.add_edge(operand_edge("control_hazard_flush_not_ras", nid, "right"));
        }

        if decode_stall_ctrl_id.is_some() {
            let nid = "ras_pop_valid_and";
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("operation"));
            n.data.insert("operator".into(), json!("&&"));
            n.data.insert("name".into(), json!(nid));
            n.data.insert("display_name".into(), json!("ras_pop && !flush && !stall"));
            n.data.insert("bit_width".into(), json!(1));
            n.data.insert("ras_component".into(), json!(true));
            self.graph.add_node(n);
            self.graph.add_edge(operand_edge("ras_pop_and_not_flush", nid, "left"));
            self.graph.add_edge(operand_edge("ras_stall_not", nid, "right"));
            self.graph.add_edge(typed_edge(nid, "ras_pop_valid", "assignment"));
        } else {
            self.graph.add_edge(typed_edge("ras_pop_and_not_flush", "ras_pop_valid", "assignment"));
        }

        // =================================================================
        // Misprediction detection
        // =================================================================
        info!("  Creating misprediction detection...");

        // Pipeline ras_top -> ras_prediction
        {
            let mut d = HashMap::new();
            d.insert("type".into(), json!("pipeline_input"));
            d.insert("stages".into(), json!(1));
            self.graph.add_edge(make_edge_with_data("ras_top", "ras_prediction", d));
        }

        // valid_gate on ras_prediction
        let ras_pop_gate_id = self
            .ras_node_ids
            .get("ras_pop_decode_gated")
            .cloned()
            .unwrap_or_else(|| "ras_pop".to_string());
        self.graph.add_edge(typed_edge(&ras_pop_gate_id, "ras_prediction", "valid_gate"));

        // Stall edge to ras_prediction
        let decode_stall_ctrl_id2 = source_node_id
            .as_ref()
            .and_then(|sid| self.find_stall_controller_for_stage(sid));
        if let Some(ref ctrl_id) = decode_stall_ctrl_id2 {
            self.graph.add_edge(typed_edge(ctrl_id, "ras_prediction", "stall"));
        }

        // Compare ras_prediction != jalr_target
        {
            let mut extra = HashMap::new();
            extra.insert("ras_component".into(), json!(true));
            create_index_comparator(
                self.graph,
                "ras_mispredict_cmp",
                "ras_prediction",
                &jalr_target_id,
                "!=",
                Some("RAS prediction != actual target"),
                Some(extra),
            );
        }

        // Create ras_pop_execute pipeline register
        let ras_pop_execute_id = {
            let nid = "ras_pop_execute";
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("pipeline_register"));
            n.data.insert("name".into(), json!(nid));
            n.data.insert("display_name".into(), json!("RAS pop at Execute stage"));
            n.data.insert("bit_width".into(), json!(1));
            n.data.insert("ras_component".into(), json!(true));
            n.data.insert("pipeline_stage".into(), json!("Execute"));
            n.data.insert("source_signal".into(), json!("ras_pop"));
            n.is_uarch_state = true;
            n.uarch_time = Some(decode_stage + 1);
            self.graph.add_node(n);

            let mut d = HashMap::new();
            d.insert("type".into(), json!("pipeline_input"));
            d.insert("stages".into(), json!(1));
            self.graph.add_edge(make_edge_with_data(&effective_ras_pop_id, nid, d));

            // Stall edge
            if let Some(ref ctrl_id) = decode_stall_ctrl_id2 {
                self.graph.add_edge(typed_edge(ctrl_id, nid, "stall"));
            }

            self.ras_node_ids.insert("ras_pop_execute".into(), nid.into());
            nid.to_string()
        };

        // Determine ras_return_execute (may be validity-gated)
        let ras_return_execute_id = if !return_enable_is_validity_gated {
            if self.graph.nodes.contains_key("PIPE_Execute_valid_PIPE") {
                let nid = "ras_pop_execute_valid";
                let mut n = Node::with_defaults(Some(nid.to_string()));
                n.data.insert("type".into(), json!("operation"));
                n.data.insert("operator".into(), json!("&&"));
                n.data.insert("name".into(), json!(nid));
                n.data.insert("display_name".into(), json!("RAS pop at Execute (validity-gated)"));
                n.data.insert("bit_width".into(), json!(1));
                n.data.insert("ras_component".into(), json!(true));
                self.graph.add_node(n);
                self.graph.add_edge(operand_edge(&ras_pop_execute_id, nid, "left"));
                self.graph.add_edge(operand_edge("PIPE_Execute_valid_PIPE", nid, "right"));
                nid.to_string()
            } else {
                ras_pop_execute_id.clone()
            }
        } else {
            ras_pop_execute_id.clone()
        };

        // Misprediction logic
        let has_conditional_returns = analysis.return_branch_taken_id.is_some();

        if let Some(ref rbt_id) = analysis.return_branch_taken_id {
            // Conditional: mispredict = ras_pop_execute && (!branch_taken || mismatch)
            {
                let nid = "ras_branch_not_taken";
                let mut n = Node::with_defaults(Some(nid.to_string()));
                n.data.insert("type".into(), json!("operation"));
                n.data.insert("operator".into(), json!("!"));
                n.data.insert("name".into(), json!(nid));
                n.data.insert("display_name".into(), json!("Return branch not taken"));
                n.data.insert("bit_width".into(), json!(1));
                n.data.insert("ras_component".into(), json!(true));
                self.graph.add_node(n);
                self.graph.add_edge(operand_edge(rbt_id, nid, "right"));
            }
            {
                let nid = "ras_mispredict_or";
                let mut n = Node::with_defaults(Some(nid.to_string()));
                n.data.insert("type".into(), json!("operation"));
                n.data.insert("operator".into(), json!("||"));
                n.data.insert("name".into(), json!(nid));
                n.data.insert("display_name".into(), json!("Branch not taken OR target mismatch"));
                n.data.insert("bit_width".into(), json!(1));
                n.data.insert("ras_component".into(), json!(true));
                self.graph.add_node(n);
                self.graph.add_edge(operand_edge("ras_branch_not_taken", nid, "left"));
                self.graph.add_edge(operand_edge("ras_mispredict_cmp", nid, "right"));
            }
            {
                let nid = "ras_mispredict_and";
                let mut n = Node::with_defaults(Some(nid.to_string()));
                n.data.insert("type".into(), json!("operation"));
                n.data.insert("operator".into(), json!("&&"));
                n.data.insert("name".into(), json!(nid));
                n.data.insert("display_name".into(), json!("RAS misprediction detected"));
                n.data.insert("bit_width".into(), json!(1));
                n.data.insert("ras_component".into(), json!(true));
                self.graph.add_node(n);
                self.graph.add_edge(operand_edge(&ras_return_execute_id, nid, "left"));
                self.graph.add_edge(operand_edge("ras_mispredict_or", nid, "right"));
                self.graph.add_edge(typed_edge(nid, "ras_mispredict", "assignment"));
            }
        } else {
            // Unconditional: mispredict = ras_pop_execute && mismatch
            let nid = "ras_mispredict_and";
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("operation"));
            n.data.insert("operator".into(), json!("&&"));
            n.data.insert("name".into(), json!(nid));
            n.data.insert("display_name".into(), json!("RAS misprediction detected"));
            n.data.insert("bit_width".into(), json!(1));
            n.data.insert("ras_component".into(), json!(true));
            self.graph.add_node(n);
            self.graph.add_edge(operand_edge(&ras_return_execute_id, nid, "left"));
            self.graph.add_edge(operand_edge("ras_mispredict_cmp", nid, "right"));
            self.graph.add_edge(typed_edge(nid, "ras_mispredict", "assignment"));
        }

        // =================================================================
        // Control hazard flush modification & PC prediction
        // =================================================================
        if has_conditional_returns {
            info!("  SKIPPING flush modification and PC prediction for conditional returns");
            return;
        }

        info!("  Modifying control_hazard_flush for RAS integration...");

        // Find JALR enable node
        let jalr_enable_id = analysis
            .return_nodes
            .iter()
            .map(|r| r.enable_id.clone())
            .find(|id| self.graph.nodes.contains_key(id));

        if let Some(ref jalr_en_id) = jalr_enable_id {
            info!("    Found JALR enable: {}", jalr_en_id);

            // !ras_pop_execute
            {
                let nid = "ras_pop_execute_not";
                let mut n = Node::with_defaults(Some(nid.to_string()));
                n.data.insert("type".into(), json!("operation"));
                n.data.insert("operator".into(), json!("!"));
                n.data.insert("name".into(), json!(nid));
                n.data.insert("display_name".into(), json!("Not a return instruction (Execute)"));
                n.data.insert("bit_width".into(), json!(1));
                n.data.insert("ras_component".into(), json!(true));
                self.graph.add_node(n);
                self.graph.add_edge(typed_edge(&ras_pop_execute_id, nid, "operand"));
            }

            // Find existing pipelined enable for Execute stage
            let pipelined_enable_id = format!("PIPE_Execute_{}_PIPE", jalr_en_id);
            let validity_gated_enable_id = format!("{}_valid_gated", pipelined_enable_id);

            let ret_enable_execute_id = if !return_enable_is_validity_gated {
                if self.graph.nodes.contains_key(&validity_gated_enable_id) {
                    validity_gated_enable_id.clone()
                } else if self.graph.nodes.contains_key(&pipelined_enable_id) {
                    // Gate by Execute validity
                    if self.graph.nodes.contains_key("PIPE_Execute_valid_PIPE") {
                        let nid = "ret_enable_execute_valid";
                        let mut n = Node::with_defaults(Some(nid.to_string()));
                        n.data.insert("type".into(), json!("operation"));
                        n.data.insert("operator".into(), json!("&&"));
                        n.data.insert("name".into(), json!(nid));
                        n.data.insert("display_name".into(), json!(format!("{} at Execute (validity-gated)", jalr_en_id)));
                        n.data.insert("bit_width".into(), json!(1));
                        n.data.insert("ras_component".into(), json!(true));
                        self.graph.add_node(n);
                        self.graph.add_edge(operand_edge(&pipelined_enable_id, nid, "left"));
                        self.graph.add_edge(operand_edge("PIPE_Execute_valid_PIPE", nid, "right"));
                        nid.to_string()
                    } else {
                        pipelined_enable_id.clone()
                    }
                } else {
                    // Fallback: create pipelined enable
                    let nid = "ret_enable_execute";
                    let mut n = Node::with_defaults(Some(nid.to_string()));
                    n.data.insert("type".into(), json!("pipeline_register"));
                    n.data.insert("name".into(), json!(nid));
                    n.data.insert("display_name".into(), json!(format!("{} at Execute stage", jalr_en_id)));
                    n.data.insert("bit_width".into(), json!(1));
                    n.data.insert("ras_component".into(), json!(true));
                    n.data.insert("pipeline_stage".into(), json!("Execute"));
                    n.is_uarch_state = true;
                    n.uarch_time = Some(decode_stage + 1);
                    self.graph.add_node(n);
                    let mut d = HashMap::new();
                    d.insert("type".into(), json!("pipeline_input"));
                    d.insert("stages".into(), json!(1));
                    self.graph.add_edge(make_edge_with_data(jalr_en_id, nid, d));
                    nid.to_string()
                }
            } else if self.graph.nodes.contains_key(&pipelined_enable_id) {
                pipelined_enable_id.clone()
            } else {
                let nid = "ret_enable_execute";
                let mut n = Node::with_defaults(Some(nid.to_string()));
                n.data.insert("type".into(), json!("pipeline_register"));
                n.data.insert("name".into(), json!(nid));
                n.data.insert("bit_width".into(), json!(1));
                n.data.insert("ras_component".into(), json!(true));
                n.is_uarch_state = true;
                n.uarch_time = Some(decode_stage + 1);
                self.graph.add_node(n);
                let mut d = HashMap::new();
                d.insert("type".into(), json!("pipeline_input"));
                d.insert("stages".into(), json!(1));
                self.graph.add_edge(make_edge_with_data(jalr_en_id, nid, d));
                nid.to_string()
            };

            self.ras_node_ids.insert("ret_enable_execute".into(), ret_enable_execute_id.clone());

            // ret_non_return_flush = ret_enable_execute && !ras_pop_execute
            {
                let nid = "ret_non_return_flush";
                let mut n = Node::with_defaults(Some(nid.to_string()));
                n.data.insert("type".into(), json!("operation"));
                n.data.insert("operator".into(), json!("&&"));
                n.data.insert("name".into(), json!(nid));
                n.data.insert("display_name".into(), json!(format!("Non-return {} flush (Execute stage)", jalr_en_id)));
                n.data.insert("bit_width".into(), json!(1));
                n.data.insert("ras_component".into(), json!(true));
                self.graph.add_node(n);
                self.graph.add_edge(operand_edge(&ret_enable_execute_id, nid, "left"));
                self.graph.add_edge(operand_edge("ras_pop_execute_not", nid, "right"));
            }

            // ret_ras_flush = ret_non_return || ras_mispredict
            {
                let nid = "ret_ras_flush";
                let mut n = Node::with_defaults(Some(nid.to_string()));
                n.data.insert("type".into(), json!("operation"));
                n.data.insert("operator".into(), json!("||"));
                n.data.insert("name".into(), json!(nid));
                n.data.insert("display_name".into(), json!(format!("{} flush with RAS", jalr_en_id)));
                n.data.insert("bit_width".into(), json!(1));
                n.data.insert("ras_component".into(), json!(true));
                self.graph.add_node(n);
                self.graph.add_edge(operand_edge("ret_non_return_flush", nid, "left"));
                self.graph.add_edge(operand_edge("ras_mispredict", nid, "right"));
                self.ras_node_ids.insert("ret_ras_flush".into(), nid.into());
            }

            // Replace JALR contribution in flush tree
            self.replace_jalr_flush_contribution(jalr_en_id, "ret_ras_flush", &control_hazard_flush_id);
        }

        // =================================================================
        // Connect RAS prediction to PC prediction path
        // =================================================================
        info!("  Integrating RAS prediction into PC prediction path...");
        let predicted_pc_id = analysis.predicted_pc_id.clone();
        let default_prediction_id = analysis.default_prediction_id.clone();

        // ras_predict_mux
        {
            let nid = "ras_predict_mux";
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("mux"));
            n.data.insert("name".into(), json!(nid));
            n.data.insert("display_name".into(), json!("RAS Prediction Mux (ras_pop ? ras_top : pc+4)"));
            n.data.insert("bit_width".into(), json!(ras_width));
            n.data.insert("ras_component".into(), json!(true));
            n.data.insert("mux_select".into(), json!("ras_pop"));
            n.data.insert("mux_true".into(), json!("ras_top"));
            n.data.insert("mux_false".into(), json!(&default_prediction_id));
            self.graph.add_node(n);

            self.graph.add_edge(typed_edge("ras_pop", nid, "mux_select"));

            let mut d = HashMap::new();
            d.insert("type".into(), json!("mux_input"));
            d.insert("condition".into(), json!("true"));
            self.graph.add_edge(make_edge_with_data("ras_top", nid, d));

            let mut d = HashMap::new();
            d.insert("type".into(), json!("mux_input"));
            d.insert("condition".into(), json!("false"));
            self.graph.add_edge(make_edge_with_data(&default_prediction_id, nid, d));

            self.ras_node_ids.insert("ras_predict_mux".into(), nid.into());
        }

        // Rewire: disconnect default_prediction -> predicted_pc
        let edges_to_remove: Vec<String> = self
            .graph
            .edges
            .iter()
            .filter(|(_, e)| e.source == default_prediction_id && e.target == predicted_pc_id)
            .map(|(eid, _)| eid.clone())
            .collect();
        for eid in edges_to_remove {
            self.graph.remove_edge(&eid);
            info!("    Removed edge: {} -> {}", default_prediction_id, predicted_pc_id);
        }

        // Connect ras_predict_mux -> predicted_pc
        self.graph.add_edge(typed_edge("ras_predict_mux", &predicted_pc_id, "assignment"));
        info!("    Connected ras_predict_mux -> {}", predicted_pc_id);
    }

    // =====================================================================
    // Helpers
    // =====================================================================

    /// Build an OR chain from a list of signal IDs and return the final node ID.
    fn build_or_chain(&mut self, base_name: &str, signals: &[String]) -> String {
        assert!(signals.len() >= 2);
        let mut current = signals[0].clone();
        for (j, sig) in signals[1..].iter().enumerate() {
            let nid = format!("{}_{}", base_name, j + 1);
            let mut n = Node::with_defaults(Some(nid.clone()));
            n.data.insert("type".into(), json!("operation"));
            n.data.insert("operator".into(), json!("||"));
            n.data.insert("name".into(), json!(&nid));
            n.data.insert("bit_width".into(), json!(1));
            n.data.insert("ras_component".into(), json!(true));
            self.graph.add_node(n);
            self.graph.add_edge(operand_edge(&current, &nid, "left"));
            self.graph.add_edge(operand_edge(sig, &nid, "right"));
            current = nid;
        }
        current
    }

    /// Find the stall controller that gates the transition FROM the stage of `source_node_id`.
    fn find_stall_controller_for_stage(&self, source_node_id: &str) -> Option<String> {
        let source_node = self.graph.nodes.get(source_node_id)?;
        let source_time = source_node.uarch_time?;

        // Find pipeline registers capturing data from source stage
        let mut candidate_regs: Vec<String> = Vec::new();
        for (nid, node) in &self.graph.nodes {
            if node.data.get("type").and_then(|v| v.as_str()) != Some("pipeline_register") {
                continue;
            }
            for eid in &node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(eid) {
                    if edge.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_input") {
                        if let Some(src_node) = self.graph.nodes.get(&edge.source) {
                            if src_node.uarch_time == Some(source_time) {
                                candidate_regs.push(nid.clone());
                                break;
                            }
                        }
                    }
                }
            }
        }
        if candidate_regs.is_empty() {
            return None;
        }

        // Find stall controllers for these registers
        let mut controller_info: HashMap<String, (i64, usize)> = HashMap::new();

        for reg_id in &candidate_regs {
            if let Some(reg_node) = self.graph.nodes.get(reg_id) {
                for eid in &reg_node.incoming_edges {
                    if let Some(edge) = self.graph.edges.get(eid) {
                        if edge.data.get("type").and_then(|v| v.as_str()) == Some("stall") {
                            let ctrl_id = &edge.source;
                            let ctrl_time = self
                                .graph
                                .nodes
                                .get(ctrl_id)
                                .and_then(|n| n.uarch_time)
                                .unwrap_or(i64::MAX);
                            let entry = controller_info.entry(ctrl_id.clone()).or_insert((ctrl_time, 0));
                            if ctrl_time < entry.0 {
                                entry.0 = ctrl_time;
                            }
                            entry.1 += 1;
                        }
                    }
                }
            }
        }
        if controller_info.is_empty() {
            return None;
        }

        // Selection priority: hazard_detection > non-memory > fallback
        let mut hazard_ctrls: Vec<(String, usize)> = Vec::new();
        let mut non_mem_ctrls: Vec<(String, usize)> = Vec::new();

        for (ctrl_id, (_time, count)) in &controller_info {
            let base_ctrl_id = ctrl_id.replace("_and_not_flush", "").replace("_not", "");
            let base_data = self
                .graph
                .nodes
                .get(&base_ctrl_id)
                .map(|n| &n.data)
                .or_else(|| self.graph.nodes.get(ctrl_id).map(|n| &n.data));

            let stall_type = base_data
                .and_then(|d| d.get("stall_type"))
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let has_memory = base_data.map(|d| d.contains_key("memory")).unwrap_or(false);

            if stall_type == "hazard_detection" {
                hazard_ctrls.push((ctrl_id.clone(), *count));
            } else if !has_memory {
                non_mem_ctrls.push((ctrl_id.clone(), *count));
            }
        }

        // Try hazard controllers first
        if !hazard_ctrls.is_empty() {
            hazard_ctrls.sort_by(|a, b| b.1.cmp(&a.1));
            for (cid, _) in &hazard_ctrls {
                if cid.contains("_and_not_flush") {
                    return Some(cid.clone());
                }
            }
            return Some(hazard_ctrls[0].0.clone());
        }

        // Try non-memory controllers
        if !non_mem_ctrls.is_empty() {
            non_mem_ctrls.sort_by(|a, b| b.1.cmp(&a.1));
            for (cid, _) in &non_mem_ctrls {
                if cid.contains("_and_not_flush") {
                    return Some(cid.clone());
                }
            }
            return Some(non_mem_ctrls[0].0.clone());
        }

        // Fallback: most used
        let mut all: Vec<(String, usize)> = controller_info
            .iter()
            .map(|(k, (_, c))| (k.clone(), *c))
            .collect();
        all.sort_by(|a, b| b.1.cmp(&a.1));
        for (cid, _) in &all {
            if cid.contains("_and_not_flush") {
                return Some(cid.clone());
            }
        }
        Some(all[0].0.clone())
    }

    /// Replace JALR's contribution in the control_hazard_flush OR tree.
    fn replace_jalr_flush_contribution(
        &mut self,
        jalr_enable_id: &str,
        new_flush_id: &str,
        control_hazard_flush_id: &str,
    ) {
        info!("    Searching for JALR contribution in control hazard flush...");

        let enable_pattern = jalr_enable_id
            .to_lowercase()
            .replace("_enable", "")
            .replace("_valid", "");

        // BFS to find nodes derived from jalr_enable
        let mut jalr_derived: HashSet<String> = HashSet::new();
        jalr_derived.insert(jalr_enable_id.to_string());

        // Also track base enable
        let mut base_enable_id = jalr_enable_id.to_string();
        if jalr_enable_id.ends_with("_valid") {
            for (_, edge) in &self.graph.edges {
                if edge.target == jalr_enable_id
                    && edge.source.ends_with("_enable")
                    && !edge.source.ends_with("_valid")
                {
                    base_enable_id = edge.source.clone();
                    jalr_derived.insert(base_enable_id.clone());
                    break;
                }
            }
        }

        let mut queue: VecDeque<String> = VecDeque::new();
        queue.push_back(base_enable_id.clone());
        if base_enable_id != jalr_enable_id {
            queue.push_back(jalr_enable_id.to_string());
        }
        let mut visited: HashSet<String> = HashSet::new();

        while let Some(nid) = queue.pop_front() {
            if !visited.insert(nid.clone()) {
                continue;
            }
            let outgoing: Vec<String> = self
                .graph
                .edges
                .iter()
                .filter(|(_, e)| e.source == nid)
                .map(|(_, e)| e.target.clone())
                .collect();

            for target_id in outgoing {
                if let Some(target_node) = self.graph.nodes.get(&target_id) {
                    if target_node
                        .data
                        .get("ras_component")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false)
                    {
                        continue;
                    }
                    let tl = target_id.to_lowercase();
                    if tl.contains(&enable_pattern)
                        || tl.contains("valid")
                        || tl.contains("gated")
                        || tl.contains("taken")
                        || tl.contains("pipe")
                    {
                        jalr_derived.insert(target_id.clone());
                        queue.push_back(target_id);
                    }
                }
            }
        }

        // Trace backwards from control_hazard_flush to find JALR-derived input
        let mut nodes_to_check: VecDeque<String> = VecDeque::new();
        nodes_to_check.push_back(control_hazard_flush_id.to_string());
        let mut checked: HashSet<String> = HashSet::new();
        let mut replaced = false;

        while let Some(current_id) = nodes_to_check.pop_front() {
            if !checked.insert(current_id.clone()) {
                continue;
            }
            if replaced {
                break;
            }

            let incoming: Vec<(String, String, HashMap<String, serde_json::Value>)> = self
                .graph
                .edges
                .iter()
                .filter(|(_, e)| e.target == current_id)
                .map(|(eid, e)| (eid.clone(), e.source.clone(), e.data.clone()))
                .collect();

            for (eid, source_id, edge_data) in incoming {
                if jalr_derived.contains(&source_id) {
                    info!("    Found JALR contribution: {} -> {}", source_id, current_id);
                    info!("    Replacing with: {} -> {}", new_flush_id, current_id);
                    self.graph.remove_edge(&eid);
                    self.graph.add_edge(make_edge_with_data(new_flush_id, &current_id, edge_data));
                    replaced = true;
                    break;
                }
                if let Some(src_node) = self.graph.nodes.get(&source_id) {
                    let is_or = src_node
                        .data
                        .get("operator")
                        .and_then(|v| v.as_str())
                        == Some("||")
                        || source_id.to_lowercase().contains("or");
                    if is_or {
                        nodes_to_check.push_back(source_id);
                    }
                }
            }
        }

        if replaced {
            info!("    Successfully replaced JALR contribution in control hazard flush");
        } else {
            info!("    Warning: Could not find JALR contribution to replace in flush tree");
        }
    }
}

// ---------------------------------------------------------------------------
// RASAnalysis helper
// ---------------------------------------------------------------------------

impl RASAnalysis {
    fn clone_ids(&self) -> RASAnalysisIds {
        RASAnalysisIds {
            call_nodes: self.call_nodes.clone(),
            return_nodes: self.return_nodes.clone(),
            predicted_pc_id: self.predicted_pc_id.clone(),
            default_prediction_id: self.default_prediction_id.clone(),
            control_hazard_flush_id: self.control_hazard_flush_id.clone(),
            jalr_target_id: self.jalr_target_id.clone(),
            jalr_execute_enable_id: self.jalr_execute_enable_id.clone(),
            return_branch_taken_id: self.return_branch_taken_id.clone(),
            decode_stage: self.decode_stage,
        }
    }
}

#[derive(Clone)]
struct RASAnalysisIds {
    call_nodes: Vec<CallAnalysis>,
    return_nodes: Vec<ReturnAnalysis>,
    predicted_pc_id: String,
    default_prediction_id: String,
    control_hazard_flush_id: String,
    jalr_target_id: String,
    jalr_execute_enable_id: Option<String>,
    return_branch_taken_id: Option<String>,
    decode_stage: i64,
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

fn ptr_width_for_depth(depth: usize) -> usize {
    if depth <= 1 {
        1
    } else {
        ((depth as f64).log2().ceil()) as usize
    }
}

// ---------------------------------------------------------------------------
// Standalone function
// ---------------------------------------------------------------------------

/// Convenience function to apply RAS optimization to a ResourceGraph.
pub fn apply_return_address_stack(graph: &mut ResourceGraph, spec: RASSpec) -> bool {
    let mut ras = RASOptimization::new(graph, spec);
    ras.apply()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    /// Build a minimal graph with the nodes needed for RAS analysis.
    fn build_test_graph() -> ResourceGraph {
        let mut g = ResourceGraph::new();

        // Instruction enables
        for nid in &["jal_enable", "jalr_enable"] {
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("var"));
            n.data.insert("bit_width".into(), json!(1));
            n.uarch_time = Some(1); // Decode stage
            g.add_node(n);
        }

        // Register nodes
        for nid in &["rd", "rs1"] {
            let mut n = Node::with_defaults(Some(nid.to_string()));
            n.data.insert("type".into(), json!("var"));
            n.data.insert("bit_width".into(), json!(5));
            n.uarch_time = Some(1);
            g.add_node(n);
        }

        // Return address (PC+4)
        let mut n = Node::with_defaults(Some("ret_addr".to_string()));
        n.data.insert("type".into(), json!("var"));
        n.data.insert("bit_width".into(), json!(32));
        n.uarch_time = Some(1);
        g.add_node(n);

        // Predicted PC
        let mut n = Node::with_defaults(Some("predicted_pc".to_string()));
        n.data.insert("type".into(), json!("var"));
        n.data.insert("bit_width".into(), json!(32));
        g.add_node(n);

        // Default prediction (PC+4)
        let mut n = Node::with_defaults(Some("pc_plus_4".to_string()));
        n.data.insert("type".into(), json!("var"));
        n.data.insert("bit_width".into(), json!(32));
        g.add_node(n);

        // Wire default prediction -> predicted_pc
        g.add_edge(typed_edge("pc_plus_4", "predicted_pc", "assignment"));

        // Control hazard flush
        let mut n = Node::with_defaults(Some("control_hazard_flush".to_string()));
        n.data.insert("type".into(), json!("var"));
        n.data.insert("bit_width".into(), json!(1));
        g.add_node(n);

        // JALR target
        let mut n = Node::with_defaults(Some("jalr_target".to_string()));
        n.data.insert("type".into(), json!("var"));
        n.data.insert("bit_width".into(), json!(32));
        n.uarch_time = Some(2); // Execute
        g.add_node(n);

        g
    }

    fn make_test_spec() -> RASSpec {
        RASSpec {
            call_specs: vec![
                CallSpec {
                    enable_node_id: "jal_enable".into(),
                    dest_reg_node_id: Some("rd".into()),
                    return_addr_node_id: "ret_addr".into(),
                },
                CallSpec {
                    enable_node_id: "jalr_enable".into(),
                    dest_reg_node_id: Some("rd".into()),
                    return_addr_node_id: "ret_addr".into(),
                },
            ],
            return_specs: vec![ReturnSpec {
                enable_node_id: "jalr_enable".into(),
                src_reg_node_id: Some("rs1".into()),
                dest_reg_node_id: Some("rd".into()),
            }],
            link_registers: vec![1, 5],
            ras_depth: 8,
            ras_width: 32,
            predicted_pc_node_id: "predicted_pc".into(),
            default_prediction_node_id: "pc_plus_4".into(),
            control_hazard_flush_node_id: "control_hazard_flush".into(),
            jalr_target_node_id: "jalr_target".into(),
            jalr_execute_enable_node_id: None,
            return_branch_taken_node_id: None,
            use_combinational_validity: false,
        }
    }

    #[test]
    fn test_ras_analysis_succeeds() {
        let mut g = build_test_graph();
        let spec = make_test_spec();
        let ras = RASOptimization::new(&mut g, spec);
        let analysis = ras.analyze();
        assert!(analysis.is_some());
        let a = analysis.unwrap();
        assert_eq!(a.call_nodes.len(), 2);
        assert_eq!(a.return_nodes.len(), 1);
        assert_eq!(a.decode_stage, 1);
    }

    #[test]
    fn test_ras_analysis_fails_missing_node() {
        let mut g = ResourceGraph::new();
        let spec = make_test_spec();
        let ras = RASOptimization::new(&mut g, spec);
        let analysis = ras.analyze();
        // Should fail because predicted_pc does not exist
        assert!(analysis.is_none());
    }

    #[test]
    fn test_ras_apply_creates_structure_nodes() {
        let mut g = build_test_graph();
        let spec = make_test_spec();
        let result = apply_return_address_stack(&mut g, spec);
        assert!(result);

        // Verify key structure nodes exist
        assert!(g.nodes.contains_key("ras_stack"));
        assert!(g.nodes.contains_key("ras_ptr"));
        assert!(g.nodes.contains_key("ras_top"));
        assert!(g.nodes.contains_key("ras_push"));
        assert!(g.nodes.contains_key("ras_pop"));
        assert!(g.nodes.contains_key("ras_mispredict"));
        assert!(g.nodes.contains_key("ras_prediction"));
        assert!(g.nodes.contains_key("ras_push_valid"));
        assert!(g.nodes.contains_key("ras_pop_valid"));
    }

    #[test]
    fn test_ras_apply_creates_hardware_nodes() {
        let mut g = build_test_graph();
        let spec = make_test_spec();
        let result = apply_return_address_stack(&mut g, spec);
        assert!(result);

        // Stack pointer update
        assert!(g.nodes.contains_key("ras_ptr_inc"));
        assert!(g.nodes.contains_key("ras_ptr_dec"));
        assert!(g.nodes.contains_key("ras_ptr_next"));

        // Stack read
        assert!(g.nodes.contains_key("ras_read_idx"));
        assert!(g.nodes.contains_key("ras_stack_read"));

        // Stack write
        assert!(g.nodes.contains_key("ras_stack_write"));

        // Misprediction
        assert!(g.nodes.contains_key("ras_mispredict_cmp"));
        assert!(g.nodes.contains_key("ras_mispredict_and"));
        assert!(g.nodes.contains_key("ras_pop_execute"));

        // Prediction mux
        assert!(g.nodes.contains_key("ras_predict_mux"));
    }

    #[test]
    fn test_ras_ptr_width_calculation() {
        assert_eq!(ptr_width_for_depth(1), 1);
        assert_eq!(ptr_width_for_depth(2), 1);
        assert_eq!(ptr_width_for_depth(4), 2);
        assert_eq!(ptr_width_for_depth(8), 3);
        assert_eq!(ptr_width_for_depth(16), 4);
        assert_eq!(ptr_width_for_depth(32), 5);
    }

    #[test]
    fn test_ras_unconditional_call() {
        let mut g = build_test_graph();
        let spec = RASSpec {
            call_specs: vec![CallSpec {
                enable_node_id: "jal_enable".into(),
                dest_reg_node_id: None, // unconditional
                return_addr_node_id: "ret_addr".into(),
            }],
            return_specs: vec![ReturnSpec {
                enable_node_id: "jalr_enable".into(),
                src_reg_node_id: None,
                dest_reg_node_id: None,
            }],
            link_registers: vec![1],
            ras_depth: 4,
            ras_width: 32,
            predicted_pc_node_id: "predicted_pc".into(),
            default_prediction_node_id: "pc_plus_4".into(),
            control_hazard_flush_node_id: "control_hazard_flush".into(),
            jalr_target_node_id: "jalr_target".into(),
            jalr_execute_enable_node_id: None,
            return_branch_taken_node_id: None,
            use_combinational_validity: false,
        };
        let result = apply_return_address_stack(&mut g, spec);
        assert!(result);
        // No call detection comparators needed for unconditional call
        assert!(!g.nodes.contains_key("ras_call_0_rd_eq_1"));
        assert!(!g.nodes.contains_key("ras_call_0_is_call"));
    }

    #[test]
    fn test_ras_prediction_mux_rewiring() {
        let mut g = build_test_graph();
        let spec = make_test_spec();

        // Before: pc_plus_4 -> predicted_pc
        let edges_before: Vec<String> = g
            .edges
            .iter()
            .filter(|(_, e)| e.source == "pc_plus_4" && e.target == "predicted_pc")
            .map(|(eid, _)| eid.clone())
            .collect();
        assert_eq!(edges_before.len(), 1);

        let result = apply_return_address_stack(&mut g, spec);
        assert!(result);

        // After: pc_plus_4 -> predicted_pc should be removed
        let edges_after: Vec<String> = g
            .edges
            .iter()
            .filter(|(_, e)| e.source == "pc_plus_4" && e.target == "predicted_pc")
            .map(|(eid, _)| eid.clone())
            .collect();
        assert_eq!(edges_after.len(), 0);

        // ras_predict_mux -> predicted_pc should exist
        let mux_edges: Vec<String> = g
            .edges
            .iter()
            .filter(|(_, e)| e.source == "ras_predict_mux" && e.target == "predicted_pc")
            .map(|(eid, _)| eid.clone())
            .collect();
        assert_eq!(mux_edges.len(), 1);
    }
}
