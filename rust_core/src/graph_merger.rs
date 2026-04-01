//! Graph merger module: merges multiple per-instruction `ResourceGraph`s into a
//! single unified graph with shared, groupwise-shared, and instruction-specific
//! nodes.
//!
//! This is a Rust port of `graph_merger.py`.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

use serde_json::{json, Value};

use crate::isa_parser::ISAParser;
use crate::resource_graph::{Edge, Node, ResourceGraph};

// ===========================================================================
// Helper functions
// ===========================================================================

/// Convert a condition expression to a valid Verilog identifier fragment.
/// Matches Python graph_merger._sanitize_cond_id().
fn sanitize_cond_id(cond_id: &str) -> String {
    let mut s = cond_id.to_string();
    s = s.replace("!=", "_ne_");
    s = s.replace("==", "_eq_");
    s = s.replace('~', "inv");
    s = s.replace("&&", "_and_");
    s = s.replace("||", "_or_");
    s = s.replace('&', "_and_");
    s = s.replace('|', "_or_");
    s = s.replace('^', "_xor_");
    s = s.replace('!', "not");
    s = s.replace(' ', "_");
    s = s.replace('(', "").replace(')', "");
    while s.contains("__") {
        s = s.replace("__", "_");
    }
    s.trim_matches('_').to_string()
}

/// Convert an enable expression JSON value to a graph node ID.
/// Mirrors the ISAParser.expression_to_id() logic for simple expressions.
fn enable_expr_to_node_id(expr: &Value) -> Option<String> {
    let expr_type = expr.get("type")?.as_str()?;
    match expr_type {
        "identifier" => Some(expr.get("name")?.as_str()?.to_string()),
        "literal" => Some(expr.get("value")?.as_i64()?.to_string()),
        "binary_op" => {
            let left = enable_expr_to_node_id(expr.get("left")?)?;
            let right = enable_expr_to_node_id(expr.get("right")?)?;
            let op = expr.get("operator")?.as_str()?;
            Some(format!("({} {} {})", left, op, right))
        }
        _ => None,
    }
}

// ===========================================================================
// Memory port helper structs
// ===========================================================================

/// Information about a single memory write from an instruction.
#[derive(Debug, Clone)]
struct MemoryWriteInfo {
    instruction: String,
    #[allow(dead_code)]
    array_access_id: String,
    index_id: Option<String>,
    data_source_ids: Vec<String>,
    enable_expr: Option<Value>,
}

/// Information about a single memory read from an instruction.
#[derive(Debug, Clone)]
struct MemoryReadInfo {
    instruction: String,
    #[allow(dead_code)]
    array_access_id: String,
    index_id: String,
}

// ===========================================================================
// SharingType
// ===========================================================================

/// How a node is shared across instructions in the merged graph.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum SharingType {
    ArchitecturalState,
    FullyShared,
    GroupwiseShared,
    InstructionSpecific,
}

impl SharingType {
    /// Numeric rank (lower = earlier in the build order).
    pub fn rank(&self) -> usize {
        match self {
            SharingType::ArchitecturalState => 0,
            SharingType::FullyShared => 1,
            SharingType::GroupwiseShared => 2,
            SharingType::InstructionSpecific => 3,
        }
    }
}

// ===========================================================================
// StructuralGroup
// ===========================================================================

/// A group of instructions that share the same structural signature for a given
/// node.
#[derive(Debug, Clone)]
pub struct StructuralGroup {
    pub group_id: String,
    pub instructions: BTreeSet<String>,
    pub structure_key: String,
}

// ===========================================================================
// NodeClassification
// ===========================================================================

/// Classification result for a single node across all instruction graphs.
#[derive(Debug, Clone)]
pub struct NodeClassification {
    pub node_id: String,
    pub groups: Vec<StructuralGroup>,
    pub merged_ids: HashMap<String, String>,
    pub tier: SharingType,
    pub is_architectural: bool,
}

impl NodeClassification {
    /// Returns `true` when the node has more than one structural group
    /// (i.e. it differs across instruction subsets).
    pub fn is_collision(&self) -> bool {
        self.groups.len() > 1
    }

    /// Find the structural group that contains `instr`.
    pub fn get_group_for_instruction(&self, instr: &str) -> Option<&StructuralGroup> {
        self.groups.iter().find(|g| g.instructions.contains(instr))
    }

    /// Get the merged node-ID for a particular instruction.
    pub fn get_merged_id_for_instruction(&self, instr: &str) -> Option<&String> {
        self.get_group_for_instruction(instr)
            .and_then(|g| self.merged_ids.get(&g.group_id))
    }
}

// ===========================================================================
// GroupTracker
// ===========================================================================

/// Tracks per-node classification results across all instructions.
#[derive(Debug, Clone)]
pub struct GroupTracker {
    pub instruction_names: Vec<String>,
    pub num_instructions: usize,
    pub classifications: HashMap<String, NodeClassification>,
}

impl GroupTracker {
    pub fn new(instruction_names: Vec<String>) -> Self {
        let num = instruction_names.len();
        Self {
            instruction_names,
            num_instructions: num,
            classifications: HashMap::new(),
        }
    }

    pub fn add_classification(&mut self, node_id: String, classification: NodeClassification) {
        self.classifications.insert(node_id, classification);
    }

    pub fn get_classification(&self, node_id: &str) -> Option<&NodeClassification> {
        self.classifications.get(node_id)
    }

    /// Resolve the merged node-ID for a given instruction + original node-ID.
    pub fn get_merged_id(&self, instr: &str, node_id: &str) -> String {
        if let Some(c) = self.classifications.get(node_id) {
            if let Some(mid) = c.get_merged_id_for_instruction(instr) {
                return mid.clone();
            }
        }
        node_id.to_string()
    }

    /// Return all node-IDs that have structural collisions.
    pub fn get_collision_nodes(&self) -> Vec<&str> {
        self.classifications
            .iter()
            .filter(|(_, c)| c.is_collision())
            .map(|(id, _)| id.as_str())
            .collect()
    }
}

// ===========================================================================
// Build-plan types
// ===========================================================================

/// Per-group metadata attached to a [`NodeBuildPlan`].
#[derive(Debug, Clone)]
pub struct GroupInfo {
    pub group_id: String,
    pub original_id: String,
    pub member_instructions: BTreeSet<String>,
    pub assignment_signature: String,
    pub needs_prefix: bool,
    pub prefix_instruction: Option<String>,
}

/// Plan for creating a single node in the merged graph.
#[derive(Debug, Clone)]
pub struct NodeBuildPlan {
    pub node_id: String,
    pub original_id: String,
    pub source_instruction: String,
    pub sharing_type: SharingType,
    pub group_info: Option<GroupInfo>,
    pub dependencies: HashSet<String>,
    pub is_collision_dependent: bool,
    pub metadata: HashMap<String, Value>,
}

/// Plan for creating a single edge in the merged graph.
#[derive(Debug, Clone)]
pub struct EdgeBuildPlan {
    pub source_id: String,
    pub target_id: String,
    pub edge_data: HashMap<String, Value>,
    pub requires_remapping: bool,
}

/// Complete build plan for constructing the merged graph.
#[derive(Debug, Clone)]
pub struct GraphBuildPlan {
    pub architectural_nodes: Vec<NodeBuildPlan>,
    pub fully_shared_nodes: Vec<NodeBuildPlan>,
    pub groupwise_shared_nodes: Vec<NodeBuildPlan>,
    pub instruction_specific_nodes: Vec<NodeBuildPlan>,
    pub edges: Vec<EdgeBuildPlan>,
    pub validated: bool,
}

impl GraphBuildPlan {
    pub fn new() -> Self {
        GraphBuildPlan {
            architectural_nodes: Vec::new(),
            fully_shared_nodes: Vec::new(),
            groupwise_shared_nodes: Vec::new(),
            instruction_specific_nodes: Vec::new(),
            edges: Vec::new(),
            validated: false,
        }
    }

    /// Returns references to all node plans in tier order:
    /// architectural, fully-shared, groupwise-shared, instruction-specific.
    pub fn get_all_nodes_ordered(&self) -> Vec<&NodeBuildPlan> {
        let mut out: Vec<&NodeBuildPlan> = Vec::new();
        for n in &self.architectural_nodes {
            out.push(n);
        }
        for n in &self.fully_shared_nodes {
            out.push(n);
        }
        for n in &self.groupwise_shared_nodes {
            out.push(n);
        }
        for n in &self.instruction_specific_nodes {
            out.push(n);
        }
        out
    }
}

impl Default for GraphBuildPlan {
    fn default() -> Self {
        Self::new()
    }
}

// ===========================================================================
// InstructionDecodeInfo
// ===========================================================================

/// Decode information extracted from a single instruction's `assume` clauses.
#[derive(Debug, Clone)]
pub struct InstructionDecodeInfo {
    pub instruction_name: String,
    /// Each entry is `(field, operator, value)`.
    pub assume_conditions: Vec<(String, String, String)>,
    pub decode_signal_node: Option<String>,
}

// ===========================================================================
// ResourceGraphMerger
// ===========================================================================

/// Merges multiple per-instruction [`ResourceGraph`]s into one.
pub struct ResourceGraphMerger {
    pub graphs: HashMap<String, ResourceGraph>,
    pub decode_info: HashMap<String, InstructionDecodeInfo>,
    pub instruction_order: Vec<String>,
    pub defines: HashMap<String, String>,
    pub pc_name: Option<String>,
    pub partially_shared_nodes: HashMap<String, HashSet<String>>,
}

impl ResourceGraphMerger {
    /// Create a new merger, optionally supplying preprocessor defines.
    pub fn new(defines: Option<HashMap<String, String>>) -> Self {
        ResourceGraphMerger {
            graphs: HashMap::new(),
            decode_info: HashMap::new(),
            instruction_order: Vec::new(),
            defines: defines.unwrap_or_default(),
            pc_name: None,
            partially_shared_nodes: HashMap::new(),
        }
    }

    // -----------------------------------------------------------------------
    // add_instruction
    // -----------------------------------------------------------------------

    /// Parse an ISA file and register the resulting graph under `name`.
    pub fn add_instruction(&mut self, name: &str, file_path: &str) -> Result<bool, String> {
        // NOTE: ISAParser is currently a stub.  When the full parser is
        // implemented its constructor will accept defines and parse_file will
        // accept (path, classify_arch_state, existing_graph).
        let mut parser = ISAParser::new();
        let graph = parser.parse_file(file_path, None)?;

        let decode_info = self.extract_decode_info(name, &graph);
        self.decode_info.insert(name.to_string(), decode_info);
        self.graphs.insert(name.to_string(), graph);
        self.instruction_order.push(name.to_string());
        Ok(true)
    }

    // -----------------------------------------------------------------------
    // extract_decode_info
    // -----------------------------------------------------------------------

    fn extract_decode_info(&self, name: &str, graph: &ResourceGraph) -> InstructionDecodeInfo {
        let mut conditions: Vec<(String, String, String)> = Vec::new();

        for assume_expr in &graph.assume_expressions {
            if let Some(op) = assume_expr.get("operator").and_then(|v| v.as_str()) {
                if op == "==" {
                    let left_id =
                        self.expr_to_string(assume_expr.get("left").unwrap_or(&Value::Null));
                    let right_id =
                        self.expr_to_string(assume_expr.get("right").unwrap_or(&Value::Null));
                    conditions.push((left_id, op.to_string(), right_id));
                }
            }
        }

        InstructionDecodeInfo {
            instruction_name: name.to_string(),
            assume_conditions: conditions,
            decode_signal_node: None,
        }
    }

    // -----------------------------------------------------------------------
    // expr_to_string
    // -----------------------------------------------------------------------

    fn expr_to_string(&self, expr: &Value) -> String {
        match expr {
            Value::String(s) => s.clone(),
            Value::Number(n) => n.to_string(),
            Value::Bool(b) => b.to_string(),
            Value::Null => "null".to_string(),
            Value::Object(map) => {
                // Try common AST shapes: { "id": "..." } or { "value": ... }
                if let Some(id) = map.get("id").and_then(|v| v.as_str()) {
                    return id.to_string();
                }
                if let Some(name) = map.get("name").and_then(|v| v.as_str()) {
                    return name.to_string();
                }
                if let Some(val) = map.get("value") {
                    return self.expr_to_string(val);
                }
                format!("{}", expr)
            }
            Value::Array(_) => format!("{}", expr),
        }
    }

    // =======================================================================
    // merge_graphs  -- main entry point
    // =======================================================================

    /// Merge all registered instruction graphs into one unified graph.
    pub fn merge_graphs(&mut self, pc_name: Option<&str>) -> Result<ResourceGraph, String> {
        if self.graphs.is_empty() {
            return Err("No graphs to merge".into());
        }
        self.pc_name = pc_name.map(|s| s.to_string());

        // Pre-merge: Split arch state nodes into _rd/_wr pairs in each
        // instruction graph BEFORE classification.  This matches the Python
        // parser which splits during from_isa_file().  Without this, ISA
        // state nodes like `pc` have per-instruction assignment sources that
        // produce different structure keys, causing unwanted collision splits.
        for (_name, graph) in self.graphs.iter_mut() {
            split_arch_state_nodes(graph);
        }

        // Merge all instruction graphs using plan-then-execute architecture

        // Phase 1-4: Classification
        let tracker = self.classify_with_groups();

        // Build instruction_specific_nodes map from tracker
        let instruction_specific_nodes =
            self.build_instruction_specific_nodes(&tracker);

        // Phase 5: Generate build plan
        let plan = self.generate_build_plan(&tracker)?;

        // Phase 6: Execute build plan
        let mut merged = self.execute_build_plan(&plan, &tracker)?;

        // Detect arch state _wr nodes that have collision groups
        let arch_state_wr_nodes_needing_mux =
            Self::detect_arch_state_wr_nodes_needing_mux(&merged);

        // Phase 7: Create decode logic
        self.create_decode_logic(&mut merged);

        // Phase 8: Create multiplexers for memory write ports
        self.multiplex_memory_write_ports(&mut merged, &instruction_specific_nodes);

        // Phase 9: Create multiplexers for memory read ports
        self.multiplex_memory_read_ports(&mut merged, &instruction_specific_nodes);

        // Phase 9b: Create read enable signals for partially-shared array reads
        self.create_read_enable_signals(&mut merged);

        // Phase 10: Gate instruction operations and create arch state muxes
        self.gate_instruction_operations(
            &mut merged,
            &instruction_specific_nodes,
            &arch_state_wr_nodes_needing_mux,
        );

        // Phase 11: Split arch state nodes into _rd/_wr pairs (after mux creation)
        split_arch_state_nodes(&mut merged);

        // Phase 12: Promote memory widths based on access patterns
        promote_mem_widths(&mut merged);

        // Phase 13: Cleanup bypassed edges and re-infer timing
        cleanup_bypassed_edges(&mut merged);
        merged.infer_uarch_time(true);

        Ok(merged)
    }

    // =======================================================================
    // Classification pipeline
    // =======================================================================

    fn classify_with_groups(&self) -> GroupTracker {
        let instruction_names: Vec<String> = self.instruction_order.clone();
        let mut tracker = GroupTracker::new(instruction_names.clone());

        // ------------------------------------------------------------------
        // Step 1: Build structural groups
        // ------------------------------------------------------------------
        // node_id -> { structure_key -> [instruction_names] }
        let mut node_id_groups: HashMap<String, HashMap<String, Vec<String>>> = HashMap::new();

        for instr_name in &instruction_names {
            let graph = &self.graphs[instr_name];
            for (node_id, node) in &graph.nodes {
                let struct_key = self.compute_node_structure_key(node, graph);
                node_id_groups
                    .entry(node_id.clone())
                    .or_default()
                    .entry(struct_key)
                    .or_default()
                    .push(instr_name.clone());
            }
        }

        // ------------------------------------------------------------------
        // Step 2: Classify into groups
        // ------------------------------------------------------------------
        for (node_id, struct_groups) in &node_id_groups {
            // Check if node is architectural state FIRST — arch state nodes
            // are never duplicated, regardless of structural collisions
            let is_architectural = instruction_names.iter().any(|instr| {
                self.graphs
                    .get(instr)
                    .and_then(|g| g.get_node(node_id))
                    .map(|n| n.is_arch_state)
                    .unwrap_or(false)
            });

            // For architectural state, force a single shared group
            // (competing writes will be resolved by mux creation later)
            let is_collision = struct_groups.len() > 1 && !is_architectural;
            let mut groups: Vec<StructuralGroup> = Vec::new();
            let mut merged_ids: HashMap<String, String> = HashMap::new();

            if is_architectural {
                // Merge all structural groups into one for arch state
                let all_instrs: BTreeSet<String> = struct_groups
                    .values()
                    .flat_map(|v| v.iter().cloned())
                    .collect();
                let combined_keys: Vec<String> = struct_groups.keys().cloned().collect();
                let combined_key = combined_keys.join("|");
                merged_ids.insert("shared".to_string(), node_id.clone());
                groups.push(StructuralGroup {
                    group_id: "shared".to_string(),
                    instructions: all_instrs,
                    structure_key: combined_key,
                });
            } else {
                for (group_idx, (struct_key, instrs)) in struct_groups.iter().enumerate() {
                    let group_id = if !is_collision {
                        "shared".to_string()
                    } else {
                        format!("group_{}", group_idx)
                    };

                    let instr_set: BTreeSet<String> = instrs.iter().cloned().collect();

                    // Determine merged_id
                    let merged_id = if !is_collision {
                        node_id.clone()
                    } else {
                        // Use first instruction name (in sorted order) as prefix
                        let first_instr = instr_set.iter().next().unwrap();
                        format!("{}_{}", first_instr, node_id)
                    };

                    merged_ids.insert(group_id.clone(), merged_id);
                    groups.push(StructuralGroup {
                        group_id,
                        instructions: instr_set,
                        structure_key: struct_key.clone(),
                    });
                }
            }

            // Determine tier
            let total_instrs: usize = groups.iter().map(|g| g.instructions.len()).sum();
            let all_instrs = total_instrs == instruction_names.len() && !is_collision;

            let tier = if is_architectural {
                SharingType::ArchitecturalState
            } else if all_instrs {
                SharingType::FullyShared
            } else if is_collision {
                SharingType::InstructionSpecific
            } else if total_instrs > 1 {
                SharingType::GroupwiseShared
            } else {
                SharingType::InstructionSpecific
            };

            tracker.add_classification(
                node_id.clone(),
                NodeClassification {
                    node_id: node_id.clone(),
                    groups,
                    merged_ids,
                    tier,
                    is_architectural,
                },
            );
        }

        // ------------------------------------------------------------------
        // Step 3: Propagate collisions to dependents
        // ------------------------------------------------------------------
        self.propagate_collisions(&mut tracker);

        // ------------------------------------------------------------------
        // Step 4: Enforce tier ordering
        // ------------------------------------------------------------------
        self.enforce_tier_ordering(&mut tracker);

        tracker
    }

    // =======================================================================
    // compute_node_structure_key
    // =======================================================================

    /// Get a signature string for an operand source node.
    /// For var nodes, recurse one level to include assignment sources so that
    /// variables with the same name but different definitions get different sigs.
    fn get_operand_source_sig(source_node: &Node, graph: &ResourceGraph) -> String {
        let source_type = source_node
            .data
            .get("type")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if source_type == "var" {
            let mut var_sources: Vec<String> = Vec::new();
            for eid in &source_node.incoming_edges {
                if let Some(edge) = graph.get_edge(eid) {
                    if edge.data.get("type").and_then(|v| v.as_str()) == Some("assignment") {
                        if let Some(src) = graph.get_node(&edge.source) {
                            var_sources.push(
                                src.data
                                    .get("display_name")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or(&edge.source)
                                    .to_string(),
                            );
                        }
                    }
                }
            }
            if !var_sources.is_empty() {
                var_sources.sort();
                let node_id = source_node
                    .data
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                format!("var:{}={}", node_id, var_sources.join(","))
            } else {
                source_node
                    .data
                    .get("display_name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string()
            }
        } else {
            source_node
                .data
                .get("display_name")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string()
        }
    }

    /// Convert edge position to a numeric sort order matching Python's _pos_order.
    fn position_sort_key(edge: &Edge) -> i64 {
        let pos_val = edge.data.get("position");
        match pos_val {
            Some(v) => {
                // Try as string first
                if let Some(s) = v.as_str() {
                    match s {
                        "left" | "unary" | "operand" => 0,
                        "right" => 1,
                        _ => 99,
                    }
                } else if let Some(n) = v.as_i64() {
                    // Numeric position (e.g., concatenation inputs)
                    n
                } else {
                    99
                }
            }
            None => 99,
        }
    }

    fn compute_node_structure_key(&self, node: &Node, graph: &ResourceGraph) -> String {
        let node_type = node
            .data
            .get("type")
            .and_then(|v| v.as_str())
            .unwrap_or("");

        match node_type {
            "var" => {
                // Key by assignment sources and enable conditions
                let mut sources: BTreeSet<String> = BTreeSet::new();
                let mut incoming_enables: BTreeSet<String> = BTreeSet::new();
                for eid in &node.incoming_edges {
                    if let Some(edge) = graph.get_edge(eid) {
                        let etype = edge
                            .data
                            .get("type")
                            .and_then(|v| v.as_str())
                            .unwrap_or("");
                        if etype == "assignment" {
                            if let Some(src) = graph.get_node(&edge.source) {
                                sources.insert(
                                    src.data
                                        .get("display_name")
                                        .and_then(|v| v.as_str())
                                        .unwrap_or(&edge.source)
                                        .to_string(),
                                );
                            }
                            if let Some(enable) = edge.data.get("enable") {
                                incoming_enables.insert(format!("{}", enable));
                            }
                        }
                    }
                }
                // Outgoing enables from assignment and mux_input/mux_default_input edges
                let mut outgoing_enables: BTreeSet<String> = BTreeSet::new();
                for eid in &node.outgoing_edges {
                    if let Some(edge) = graph.get_edge(eid) {
                        let etype = edge
                            .data
                            .get("type")
                            .and_then(|v| v.as_str())
                            .unwrap_or("");
                        match etype {
                            "assignment" => {
                                let enable_str = edge
                                    .data
                                    .get("enable")
                                    .map(|v| format!("{}", v))
                                    .unwrap_or_else(|| "null".to_string());
                                outgoing_enables.insert(enable_str);
                            }
                            "mux_input" | "mux_default_input" => {
                                let enable_str = edge
                                    .data
                                    .get("original_enable")
                                    .map(|v| format!("{}", v))
                                    .unwrap_or_else(|| "null".to_string());
                                outgoing_enables.insert(enable_str);
                            }
                            _ => {}
                        }
                    }
                }
                format!(
                    "var:sources={:?}:out_enables={:?}:in_enables={:?}",
                    sources, outgoing_enables, incoming_enables
                )
            }

            "multiplexer" => {
                let mut target_ids: Vec<String> = Vec::new();
                let mut input_pairs: BTreeSet<(String, String)> = BTreeSet::new();
                let mut default_source = String::new();

                for eid in &node.outgoing_edges {
                    if let Some(edge) = graph.get_edge(eid) {
                        if edge
                            .data
                            .get("type")
                            .and_then(|v| v.as_str())
                            == Some("assignment")
                        {
                            target_ids.push(edge.target.clone());
                        }
                    }
                }
                target_ids.sort();

                // Collect inputs and selects by index
                let mut inputs_by_idx: HashMap<i64, String> = HashMap::new();
                let mut selects_by_idx: HashMap<i64, String> = HashMap::new();

                for eid in &node.incoming_edges {
                    if let Some(edge) = graph.get_edge(eid) {
                        let etype = edge
                            .data
                            .get("type")
                            .and_then(|v| v.as_str())
                            .unwrap_or("");
                        match etype {
                            "mux_input" => {
                                let idx = edge
                                    .data
                                    .get("input_index")
                                    .and_then(|v| v.as_i64())
                                    .unwrap_or(-1);
                                let src_name = graph
                                    .get_node(&edge.source)
                                    .and_then(|n| {
                                        n.data.get("display_name").and_then(|v| v.as_str())
                                    })
                                    .unwrap_or(&edge.source)
                                    .to_string();
                                inputs_by_idx.insert(idx, src_name);
                            }
                            "mux_default_input" => {
                                // Get detailed default source signature
                                if let Some(src_node) = graph.get_node(&edge.source) {
                                    let src_type = src_node
                                        .data
                                        .get("type")
                                        .and_then(|v| v.as_str())
                                        .unwrap_or("");
                                    if src_type == "var" {
                                        let sig = Self::get_operand_source_sig(src_node, graph);
                                        default_source = sig;
                                    } else if src_type == "ternary_op" {
                                        // Include ternary operand sources for full discrimination
                                        let mut cond = String::new();
                                        let mut true_val = String::new();
                                        let mut false_val = String::new();
                                        for teid in &src_node.incoming_edges {
                                            if let Some(te) = graph.get_edge(teid) {
                                                let tetype = te
                                                    .data
                                                    .get("type")
                                                    .and_then(|v| v.as_str())
                                                    .unwrap_or("");
                                                if let Some(tsrc) = graph.get_node(&te.source) {
                                                    let sig = Self::get_operand_source_sig(tsrc, graph);
                                                    match tetype {
                                                        "ternary_condition" => cond = sig,
                                                        "ternary_true" => true_val = sig,
                                                        "ternary_false" => false_val = sig,
                                                        _ => {}
                                                    }
                                                }
                                            }
                                        }
                                        default_source = format!(
                                            "ternary:{}[cond={},true={},false={}]",
                                            edge.source, cond, true_val, false_val
                                        );
                                    } else {
                                        default_source = src_node
                                            .data
                                            .get("display_name")
                                            .and_then(|v| v.as_str())
                                            .unwrap_or(&edge.source)
                                            .to_string();
                                    }
                                }
                            }
                            "mux_select" => {
                                let idx = edge
                                    .data
                                    .get("select_index")
                                    .and_then(|v| v.as_i64())
                                    .unwrap_or(-1);
                                selects_by_idx.insert(idx, edge.source.clone());
                            }
                            _ => {}
                        }
                    }
                }

                // Create order-independent (value, condition) pairs
                let mut all_indices: BTreeSet<i64> = BTreeSet::new();
                all_indices.extend(inputs_by_idx.keys());
                all_indices.extend(selects_by_idx.keys());
                for idx in &all_indices {
                    let val = inputs_by_idx.get(idx).cloned().unwrap_or_default();
                    let cond = selects_by_idx.get(idx).cloned().unwrap_or_default();
                    input_pairs.insert((val, cond));
                }

                let is_gated = node
                    .data
                    .get("gated_write_mux")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false);

                format!(
                    "mux:targets={:?}:pairs={:?}:gated={}:default={}",
                    target_ids, input_pairs, is_gated, default_source
                )
            }

            "ternary_op" => {
                // Ternary operations: key by condition, true, and false operand sources
                // separately. This is critical for branch instructions where all have
                // the same structure (res ? branch_dest : pc+4) but different conditions.
                let display_name = node
                    .data
                    .get("display_name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");

                let mut cond_source = String::new();
                let mut true_source = String::new();
                let mut false_source = String::new();
                for eid in &node.incoming_edges {
                    if let Some(edge) = graph.get_edge(eid) {
                        let etype = edge
                            .data
                            .get("type")
                            .and_then(|v| v.as_str())
                            .unwrap_or("");
                        if let Some(src) = graph.get_node(&edge.source) {
                            let sig = Self::get_operand_source_sig(src, graph);
                            match etype {
                                "ternary_condition" | "mux_select" => cond_source = sig,
                                "ternary_true" => true_source = sig,
                                "ternary_false" => false_source = sig,
                                _ => {
                                    // Fallback: check input_index for condition
                                    if edge.data.get("input_index").and_then(|v| v.as_i64())
                                        == Some(0)
                                    {
                                        cond_source = sig;
                                    }
                                }
                            }
                        }
                    }
                }

                format!(
                    "ternary_op:display={}:cond={}:true={}:false={}",
                    display_name, cond_source, true_source, false_source
                )
            }

            "operation" | "concatenation" | "repetition" | "sign_extend" | "zero_extend" => {
                let display_name = node
                    .data
                    .get("display_name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                // Sort edges by position (numeric sort order matching Python's _pos_order)
                let mut edges_with_pos: Vec<(i64, &Edge)> = Vec::new();
                for eid in &node.incoming_edges {
                    if let Some(edge) = graph.get_edge(eid) {
                        edges_with_pos.push((Self::position_sort_key(edge), edge));
                    }
                }
                edges_with_pos.sort_by_key(|(pos, _)| *pos);

                let mut operand_sigs: Vec<String> = Vec::new();
                for (_, edge) in &edges_with_pos {
                    if let Some(src) = graph.get_node(&edge.source) {
                        operand_sigs
                            .push(Self::get_operand_source_sig(src, graph));
                    }
                }
                format!(
                    "{}:display={}:operands={:?}",
                    node_type, display_name, operand_sigs
                )
            }

            "literal" | "sized_literal" => {
                let value = node.data.get("value").cloned().unwrap_or(Value::Null);
                format!("{}:value={}", node_type, value)
            }

            "bit_slice" => {
                let display_name = node
                    .data
                    .get("display_name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let bitslice = node
                    .data
                    .get("expression")
                    .and_then(|e| e.get("range"))
                    .cloned()
                    .unwrap_or(Value::Null);
                format!("bit_slice:range={}:display={}", bitslice, display_name)
            }

            "isa_state" => {
                let name = node
                    .data
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let mut sources: BTreeSet<String> = BTreeSet::new();
                let mut incoming_enables: BTreeSet<String> = BTreeSet::new();
                for eid in &node.incoming_edges {
                    if let Some(edge) = graph.get_edge(eid) {
                        if edge.data.get("type").and_then(|v| v.as_str()) == Some("assignment") {
                            if let Some(src) = graph.get_node(&edge.source) {
                                sources.insert(
                                    src.data
                                        .get("display_name")
                                        .and_then(|v| v.as_str())
                                        .unwrap_or(&edge.source)
                                        .to_string(),
                                );
                            }
                            if let Some(enable) = edge.data.get("enable") {
                                incoming_enables.insert(format!("{}", enable));
                            }
                        }
                    }
                }
                format!(
                    "isa_state:name={}:sources={:?}:enables={:?}",
                    name, sources, incoming_enables
                )
            }

            _ => {
                let name = node
                    .data
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                format!("{}:{}", node_type, name)
            }
        }
    }

    // =======================================================================
    // propagate_collisions
    // =======================================================================

    fn propagate_collisions(&self, tracker: &mut GroupTracker) {
        // Match Python's _propagate_groups_to_dependents approach:
        // For each node, check if its INCOMING dependencies include collision nodes.
        // Split by those collision groups, keeping uncovered instructions together.

        // Data dependency edge types that represent actual data flow.
        // Control/metadata edges (array_base, array_index, write_enable,
        // decode_enable, cache_flush) are excluded.
        const DATA_DEPENDENCY_EDGE_TYPES: &[&str] = &[
            "assignment",
            "operand",
            "left_operand",
            "right_operand",
            "concatenation_input",
            "concat_element",
            "ternary_condition",
            "ternary_true",
            "ternary_false",
            "mux_input",
            "mux_default_input",
            "mux_select",
            "repetition_value",
            "repetition_input",
            "bit_slice_source",
            "bit_access",
        ];

        // Build per-instruction dependency map: for each instruction's graph,
        // map node_id -> set of source node_ids via data dependency edges.
        let mut instr_node_deps: HashMap<String, HashMap<String, BTreeSet<String>>> =
            HashMap::new();
        for instr_name in &self.instruction_order {
            let graph = &self.graphs[instr_name];
            let mut node_deps: HashMap<String, BTreeSet<String>> = HashMap::new();
            for (node_id, node) in &graph.nodes {
                let deps = node_deps.entry(node_id.clone()).or_default();
                for eid in &node.incoming_edges {
                    if let Some(edge) = graph.get_edge(eid) {
                        let edge_type = edge
                            .data
                            .get("type")
                            .and_then(|v| v.as_str())
                            .unwrap_or("");
                        if DATA_DEPENDENCY_EDGE_TYPES.contains(&edge_type) {
                            deps.insert(edge.source.clone());
                        }
                    }
                }
            }
            instr_node_deps.insert(instr_name.clone(), node_deps);
        }

        // Track collision nodes — this list grows as new splits create new collisions
        let mut collision_nodes: Vec<String> = tracker
            .get_collision_nodes()
            .iter()
            .map(|s| s.to_string())
            .collect();

        let mut changed = true;
        while changed {
            changed = false;

            let node_ids: Vec<String> = tracker.classifications.keys().cloned().collect();
            for node_id in &node_ids {
                // Get all instructions that have this node
                let all_instrs_with_node: BTreeSet<String> = {
                    let classification = &tracker.classifications[node_id];
                    classification
                        .groups
                        .iter()
                        .flat_map(|g| g.instructions.iter().cloned())
                        .collect()
                };

                // Find which collision nodes this node depends on, PER INSTRUCTION
                let mut instrs_with_collision_deps: HashMap<String, BTreeSet<String>> =
                    HashMap::new();
                for instr in &all_instrs_with_node {
                    if let Some(node_deps) = instr_node_deps.get(instr) {
                        if let Some(deps) = node_deps.get(node_id) {
                            for dep_id in deps {
                                if collision_nodes.contains(dep_id) {
                                    instrs_with_collision_deps
                                        .entry(dep_id.clone())
                                        .or_default()
                                        .insert(instr.clone());
                                }
                            }
                        }
                    }
                }

                if instrs_with_collision_deps.is_empty() {
                    continue;
                }

                // Process one collision dependency at a time (break after first split)
                for (collision_dep_id, instrs_with_dep) in &instrs_with_collision_deps {
                    let collision_groups: Vec<BTreeSet<String>> = tracker.classifications
                        .get(collision_dep_id)
                        .map(|c| c.groups.iter().map(|g| g.instructions.clone()).collect())
                        .unwrap_or_default();

                    if collision_groups.is_empty() {
                        continue;
                    }

                    let classification = &tracker.classifications[node_id];
                    let existing_groups = classification.groups.clone();
                    let existing_merged_ids = classification.merged_ids.clone();
                    let is_already_collision = classification.is_collision();

                    let mut new_groups: Vec<StructuralGroup> = Vec::new();
                    let mut new_merged_ids: HashMap<String, String> = HashMap::new();
                    let mut needs_split = false;

                    for our_group in &existing_groups {
                        let our_instrs = &our_group.instructions;

                        // Split into instructions that DO vs DON'T depend on the
                        // collision node in this group
                        let instrs_with_dep_in_group: BTreeSet<String> = our_instrs
                            .intersection(instrs_with_dep)
                            .cloned()
                            .collect();
                        let instrs_without_dep_in_group: BTreeSet<String> = our_instrs
                            .difference(instrs_with_dep)
                            .cloned()
                            .collect();

                        // Sub-groups from collision structure
                        let mut sub_groups: Vec<(String, BTreeSet<String>)> = Vec::new();
                        for coll_instrs in &collision_groups {
                            let overlap: BTreeSet<String> = coll_instrs
                                .intersection(&instrs_with_dep_in_group)
                                .cloned()
                                .collect();
                            if !overlap.is_empty() {
                                let first = overlap.iter().next().unwrap().clone();
                                sub_groups.push((first, overlap));
                            }
                        }

                        // Instructions without the dependency stay together
                        if !instrs_without_dep_in_group.is_empty() {
                            let first = instrs_without_dep_in_group
                                .iter()
                                .next()
                                .unwrap()
                                .clone();
                            sub_groups.push((first, instrs_without_dep_in_group));
                        }

                        if sub_groups.len() > 1 {
                            needs_split = true;
                            for (sub_group_id, sub_instrs) in sub_groups {
                                let first_instr =
                                    sub_instrs.iter().next().unwrap().clone();
                                let merged_id =
                                    format!("{}_{}", first_instr, node_id);
                                new_groups.push(StructuralGroup {
                                    group_id: sub_group_id.clone(),
                                    instructions: sub_instrs,
                                    structure_key: our_group.structure_key.clone(),
                                });
                                new_merged_ids.insert(sub_group_id, merged_id);
                            }
                        } else {
                            // Keep this group as-is
                            let group_id = our_group.group_id.clone();
                            let merged_id = if is_already_collision {
                                existing_merged_ids
                                    .get(&group_id)
                                    .cloned()
                                    .unwrap_or_else(|| {
                                        let fi =
                                            our_instrs.iter().next().unwrap();
                                        format!("{}_{}", fi, node_id)
                                    })
                            } else {
                                node_id.clone()
                            };
                            new_groups.push(our_group.clone());
                            new_merged_ids.insert(group_id, merged_id);
                        }
                    }

                    if needs_split {
                        let classification =
                            tracker.classifications.get_mut(node_id).unwrap();
                        classification.groups = new_groups;
                        classification.merged_ids = new_merged_ids;
                        classification.tier = SharingType::InstructionSpecific;
                        changed = true;
                        if !collision_nodes.contains(node_id) {
                            collision_nodes.push(node_id.clone());
                        }
                        break; // Process one collision dep at a time
                    }
                }
            }
        }
    }

    // =======================================================================
    // enforce_tier_ordering
    // =======================================================================

    fn enforce_tier_ordering(&self, tracker: &mut GroupTracker) {
        // Ensure dependencies are in earlier/same tiers.
        let mut changed = true;
        while changed {
            changed = false;
            let node_ids: Vec<String> = tracker.classifications.keys().cloned().collect();
            for node_id in &node_ids {
                let current_rank = tracker.classifications[node_id].tier.rank();

                // Check dependencies
                for instr_name in &self.instruction_order {
                    let graph = &self.graphs[instr_name];
                    if let Some(node) = graph.get_node(node_id) {
                        for eid in &node.incoming_edges {
                            if let Some(edge) = graph.get_edge(eid) {
                                if let Some(dep_class) =
                                    tracker.classifications.get(&edge.source)
                                {
                                    if dep_class.tier.rank() > current_rank {
                                        tracker
                                            .classifications
                                            .get_mut(node_id)
                                            .unwrap()
                                            .tier = dep_class.tier;
                                        changed = true;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // =======================================================================
    // generate_build_plan
    // =======================================================================

    fn generate_build_plan(&self, tracker: &GroupTracker) -> Result<GraphBuildPlan, String> {
        let mut plan = GraphBuildPlan::new();
        let mut planned_ids: HashSet<String> = HashSet::new();

        // ------------------------------------------------------------------
        // Generate node plans
        // ------------------------------------------------------------------
        for (node_id, classification) in &tracker.classifications {
            for group in &classification.groups {
                let merged_id = classification
                    .merged_ids
                    .get(&group.group_id)
                    .cloned()
                    .unwrap_or_else(|| node_id.clone());

                if planned_ids.contains(&merged_id) {
                    continue;
                }
                planned_ids.insert(merged_id.clone());

                let source_instr = group.instructions.iter().next().unwrap().clone();

                // Build dependencies
                let mut deps: HashSet<String> = HashSet::new();
                if let Some(graph) = self.graphs.get(&source_instr) {
                    if let Some(node) = graph.get_node(node_id) {
                        for eid in &node.incoming_edges {
                            if let Some(edge) = graph.get_edge(eid) {
                                let dep_merged =
                                    tracker.get_merged_id(&source_instr, &edge.source);
                                deps.insert(dep_merged);
                            }
                        }
                    }
                }

                let group_info =
                    if group.instructions.len() > 1 && group.group_id != "shared" {
                        Some(GroupInfo {
                            group_id: group.group_id.clone(),
                            original_id: node_id.clone(),
                            member_instructions: group.instructions.clone(),
                            assignment_signature: group.structure_key.clone(),
                            needs_prefix: merged_id != *node_id,
                            prefix_instruction: if merged_id != *node_id {
                                Some(source_instr.clone())
                            } else {
                                None
                            },
                        })
                    } else {
                        None
                    };

                let node_plan = NodeBuildPlan {
                    node_id: merged_id,
                    original_id: node_id.clone(),
                    source_instruction: source_instr,
                    sharing_type: classification.tier,
                    group_info,
                    dependencies: deps,
                    is_collision_dependent: classification.is_collision(),
                    metadata: HashMap::new(),
                };

                match classification.tier {
                    SharingType::ArchitecturalState => {
                        plan.architectural_nodes.push(node_plan);
                    }
                    SharingType::FullyShared => {
                        plan.fully_shared_nodes.push(node_plan);
                    }
                    SharingType::GroupwiseShared => {
                        plan.groupwise_shared_nodes.push(node_plan);
                    }
                    SharingType::InstructionSpecific => {
                        plan.instruction_specific_nodes.push(node_plan);
                    }
                }
            }
        }

        // ------------------------------------------------------------------
        // Generate edge plans
        // ------------------------------------------------------------------
        let mut seen_edges: HashSet<(String, String, String)> = HashSet::new();
        for instr_name in &self.instruction_order {
            let graph = &self.graphs[instr_name];
            for edge in graph.edges.values() {
                let merged_source = tracker.get_merged_id(instr_name, &edge.source);
                let merged_target = tracker.get_merged_id(instr_name, &edge.target);

                if !planned_ids.contains(&merged_source)
                    || !planned_ids.contains(&merged_target)
                {
                    continue;
                }

                let edge_type = edge
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                let edge_key = (
                    merged_source.clone(),
                    merged_target.clone(),
                    edge_type,
                );
                if seen_edges.contains(&edge_key) {
                    continue;
                }
                seen_edges.insert(edge_key);

                let requires_remapping =
                    merged_source != edge.source || merged_target != edge.target;

                plan.edges.push(EdgeBuildPlan {
                    source_id: merged_source,
                    target_id: merged_target,
                    edge_data: edge.data.iter().map(|(k, v)| (k.clone(), v.clone())).collect(),
                    requires_remapping,
                });
            }
        }

        plan.validated = true;
        Ok(plan)
    }

    // =======================================================================
    // execute_build_plan
    // =======================================================================

    #[allow(unused_variables)]
    fn execute_build_plan(
        &self,
        plan: &GraphBuildPlan,
        tracker: &GroupTracker,
    ) -> Result<ResourceGraph, String> {
        let mut merged = ResourceGraph::new();

        // Add nodes in tier order
        for node_plan in plan.get_all_nodes_ordered() {
            let source_graph = &self.graphs[&node_plan.source_instruction];

            if let Some(source_node) = source_graph.get_node(&node_plan.original_id) {
                let mut new_data = source_node.data.clone();

                // Track which instruction this node came from (matches Python merger behavior)
                new_data.insert("instruction".into(), json!(node_plan.source_instruction));

                // If renamed, store original_id
                if node_plan.node_id != node_plan.original_id {
                    new_data.insert("original_id".into(), json!(node_plan.original_id));
                }

                let new_node = Node::new(
                    Some(node_plan.node_id.clone()),
                    Some(new_data),
                    source_node.is_arch_state,
                    source_node.used_as_index,
                    source_node.indexed_by.clone(),
                    source_node.is_uarch_state,
                    source_node.uarch_time,
                    source_node.pipe_time,
                    source_node.from_isa_spec,
                    source_node.already_split,
                    source_node.latency,
                    source_node.variable_latency,
                    node_plan.sharing_type != SharingType::InstructionSpecific,
                    source_node.pipe_id,
                    source_node.dual_issue_time,
                );
                merged.add_node(new_node);
            }
        }

        // Add edges
        for edge_plan in &plan.edges {
            if merged.nodes.contains_key(&edge_plan.source_id)
                && merged.nodes.contains_key(&edge_plan.target_id)
            {
                let edge = Edge::new(
                    edge_plan.source_id.clone(),
                    edge_plan.target_id.clone(),
                    None,
                    Some(edge_plan.edge_data.clone()),
                );
                merged.add_edge(edge);
            }
        }

        Ok(merged)
    }

    // =======================================================================
    // build_instruction_specific_nodes
    // =======================================================================

    /// Build a map from instruction name to the set of node IDs that are
    /// instruction-specific (or part of collision groups) for that instruction.
    fn build_instruction_specific_nodes(
        &self,
        tracker: &GroupTracker,
    ) -> HashMap<String, HashSet<String>> {
        let mut result: HashMap<String, HashSet<String>> = HashMap::new();
        for instr in &self.instruction_order {
            result.insert(instr.clone(), HashSet::new());
        }

        for (node_id, classification) in &tracker.classifications {
            if classification.tier == SharingType::InstructionSpecific {
                for group in &classification.groups {
                    if group.instructions.len() == 1 {
                        let instr = group.instructions.iter().next().unwrap();
                        if let Some(set) = result.get_mut(instr) {
                            set.insert(node_id.clone());
                        }
                    }
                }
            }
            if classification.is_collision() {
                for group in &classification.groups {
                    for instr in &group.instructions {
                        if let Some(set) = result.get_mut(instr) {
                            set.insert(node_id.clone());
                        }
                    }
                }
            }
        }

        result
    }

    // =======================================================================
    // detect_arch_state_wr_nodes_needing_mux
    // =======================================================================

    /// Detect arch state _wr nodes that have collision groups (i.e. nodes in
    /// the merged graph whose `original_id` ends with `_wr`). These need muxes
    /// to merge all instruction-specific values.
    fn detect_arch_state_wr_nodes_needing_mux(merged: &ResourceGraph) -> HashSet<String> {
        let mut result = HashSet::new();
        for (_node_id, node) in &merged.nodes {
            if let Some(original_id) = node.data.get("original_id").and_then(|v| v.as_str()) {
                if original_id.ends_with("_wr") {
                    result.insert(original_id.to_string());
                }
            }
        }
        result
    }

    // =======================================================================
    // gate_instruction_operations
    // =======================================================================

    /// Create multiplexers for nodes that receive assignments from multiple
    /// instruction-specific operations. Also creates arch state muxes for
    /// `_wr` nodes with collision groups.
    fn gate_instruction_operations(
        &self,
        merged: &mut ResourceGraph,
        instruction_specific_nodes: &HashMap<String, HashSet<String>>,
        arch_state_wr_nodes_needing_mux: &HashSet<String>,
    ) {
        // Step 1: Find all assignment edges where the source is instruction-specific
        // and the target is shared (or arch state). Group by target.
        // assignment_targets: target_id -> Vec<(source_id, instr_name, enable_expr)>
        let mut assignment_targets: HashMap<String, Vec<(String, String, Option<Value>)>> =
            HashMap::new();

        // Collect node info first to avoid borrow issues
        let node_infos: Vec<(String, Option<String>, Option<String>)> = merged
            .nodes
            .iter()
            .map(|(id, n)| {
                let ntype = n
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());
                let instr = n
                    .data
                    .get("instruction")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());
                (id.clone(), ntype, instr)
            })
            .collect();

        for (node_id, node_type, node_instr) in &node_infos {
            let should_check = match node_type.as_deref() {
                Some("operation") | Some("ternary_op") => true,
                Some("var") => {
                    node_instr.is_some()
                        || instruction_specific_nodes
                            .values()
                            .any(|set| set.contains(node_id.as_str()))
                        || self.partially_shared_nodes.contains_key(node_id.as_str())
                        // Also catch collision nodes with instruction prefix (e.g., jal_jump_dest)
                        || self.instruction_order.iter().any(|instr|
                            node_id.starts_with(&format!("{}_", instr)))
                }
                _ => false,
            };

            if !should_check {
                continue;
            }

            // Find outgoing assignment edges
            let outgoing_eids: Vec<String> = merged
                .nodes
                .get(node_id)
                .map(|n| n.outgoing_edges.iter().cloned().collect())
                .unwrap_or_default();

            for eid in &outgoing_eids {
                let (target_id, edge_type, enable_expr) = match merged.get_edge(eid) {
                    Some(edge) => {
                        let etype = edge
                            .data
                            .get("type")
                            .and_then(|v| v.as_str())
                            .unwrap_or("");
                        let enable = edge.data.get("enable").cloned();
                        (edge.target.clone(), etype.to_string(), enable)
                    }
                    None => continue,
                };

                if edge_type != "assignment" {
                    continue;
                }

                // Determine which instruction this assignment belongs to
                let instr_name = if let Some(instr) = node_instr {
                    instr.clone()
                } else {
                    // Check if node_id is in any instruction_specific set
                    let mut found_instr = "shared".to_string();
                    for (instr, set) in instruction_specific_nodes {
                        if set.contains(node_id.as_str()) {
                            found_instr = instr.clone();
                            break;
                        }
                    }
                    // Also check by prefix
                    if found_instr == "shared" {
                        for instr in self.instruction_order.iter() {
                            if node_id.starts_with(&format!("{}_", instr)) {
                                found_instr = instr.clone();
                                break;
                            }
                        }
                    }
                    found_instr
                };

                assignment_targets
                    .entry(target_id.clone())
                    .or_default()
                    .push((node_id.clone(), instr_name, enable_expr));
            }
        }

        // Step 1b: Also detect assignment edges from shared/non-instruction-specific
        // nodes to arch state targets (e.g., rf[rs]_rd -> pc from jr).
        // These are missed by step 1 because shared nodes fail should_check.
        // We attribute them to the correct instruction by checking individual graphs.
        // Note: at this phase, arch state nodes may not be split yet (e.g., "pc"
        // not "pc_wr"), so we check all arch state nodes.
        {
            // Scan all targets that already have entries in assignment_targets,
            // plus arch state nodes, for uncaptured assignment edges.
            let mut targets_to_check: Vec<String> = assignment_targets.keys().cloned().collect();
            // Also add arch state nodes
            for (id, n) in &merged.nodes {
                if n.is_arch_state && !targets_to_check.contains(id) {
                    targets_to_check.push(id.clone());
                }
            }

            for target_id in &targets_to_check {
                // For collision nodes (e.g., add_pc_wr), get the original_id
                // (e.g., pc_wr) so we can match against individual instruction graphs.
                let original_target_id: Option<String> = merged
                    .get_node(target_id)
                    .and_then(|n| n.data.get("original_id"))
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());

                if let Some(target_node) = merged.get_node(target_id) {
                    let incoming_eids: Vec<String> =
                        target_node.incoming_edges.iter().cloned().collect();
                    for eid in &incoming_eids {
                        if let Some(edge) = merged.get_edge(&eid) {
                            if edge.data.get("type").and_then(|v| v.as_str()) != Some("assignment") {
                                continue;
                            }
                            let source_id = edge.source.clone();
                            // Skip if this source is already captured in assignment_targets
                            let already_captured = assignment_targets
                                .get(target_id)
                                .map(|srcs| srcs.iter().any(|(s, _, _)| *s == source_id))
                                .unwrap_or(false);
                            if already_captured {
                                continue;
                            }
                            // Check individual instruction graphs to find which instruction(s)
                            // originally had this assignment.
                            for instr in self.instruction_order.iter() {
                                if let Some(instr_graph) = self.graphs.get(instr) {
                                    if instr_graph.get_node(&source_id).is_some() {
                                        // Check for assignment to the target in
                                        // the original graph.  The target may be
                                        // the merged name (e.g. "add_pc_wr") or
                                        // the original name (e.g. "pc_wr").
                                        let has_assignment = instr_graph.edges.values().any(|e| {
                                            e.source == source_id
                                                && (e.target == *target_id
                                                    || original_target_id.as_deref() == Some(&e.target))
                                                && e.data
                                                    .get("type")
                                                    .and_then(|v| v.as_str())
                                                    == Some("assignment")
                                        });
                                        if has_assignment {
                                            assignment_targets
                                                .entry(target_id.clone())
                                                .or_default()
                                                .push((
                                                    source_id.clone(),
                                                    instr.clone(),
                                                    None,
                                                ));
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // Step 2: For targets with multiple sources, create multiplexers
        // Skip arch state targets - they're handled separately below
        let mut edges_to_remove: Vec<String> = Vec::new();
        let mut muxes_to_create: Vec<(
            String,
            Vec<(String, Vec<String>, Option<Value>)>,
            Option<String>,
        )> = Vec::new();

        for (target_id, sources) in &assignment_targets {
            if sources.len() <= 1 {
                continue;
            }
            // Skip if this will be handled by arch state mux
            if arch_state_wr_nodes_needing_mux.contains(target_id) {
                continue;
            }

            // Deduplicate: group by source node, collect all instruction names
            let mut source_by_node: HashMap<String, (Vec<String>, Option<Value>)> =
                HashMap::new();
            for (src_id, instr_name, enable_expr) in sources {
                source_by_node
                    .entry(src_id.clone())
                    .and_modify(|(instrs, _)| {
                        if !instrs.contains(instr_name) {
                            instrs.push(instr_name.clone());
                        }
                    })
                    .or_insert_with(|| (vec![instr_name.clone()], enable_expr.clone()));
            }

            if source_by_node.len() <= 1 {
                continue; // All sources are the same node
            }

            // Separate into instruction-specific and shared (default) sources
            let mut instruction_sources: Vec<(String, Vec<String>, Option<Value>)> = Vec::new();
            let mut default_source: Option<String> = None;

            for (src_id, (instrs, enable_expr)) in &source_by_node {
                let specific: Vec<String> =
                    instrs.iter().filter(|i| *i != "shared").cloned().collect();
                if specific.is_empty() {
                    default_source = Some(src_id.clone());
                } else {
                    instruction_sources.push((
                        src_id.clone(),
                        specific,
                        enable_expr.clone(),
                    ));
                }
            }

            // Optimization: single source covering all instructions, skip mux
            if instruction_sources.len() == 1 && default_source.is_none() {
                let (_, ref instrs, _) = instruction_sources[0];
                if instrs.len() == self.graphs.len() {
                    continue;
                }
            }

            // Collect edges to remove (direct assignments to target)
            for (src_id, _, _) in sources {
                if let Some(src_node) = merged.get_node(src_id) {
                    for eid in &src_node.outgoing_edges {
                        if let Some(edge) = merged.get_edge(eid) {
                            if edge.target == *target_id
                                && edge
                                    .data
                                    .get("type")
                                    .and_then(|v| v.as_str())
                                    == Some("assignment")
                            {
                                edges_to_remove.push(eid.clone());
                            }
                        }
                    }
                }
            }

            muxes_to_create.push((
                target_id.clone(),
                instruction_sources,
                default_source,
            ));
        }

        // Remove conflicting direct assignment edges
        for eid in &edges_to_remove {
            merged.remove_edge(eid);
        }

        // Create multiplexers
        for (target_id, instruction_sources, default_source) in &muxes_to_create {
            Self::create_instruction_multiplexer(
                merged,
                target_id,
                instruction_sources,
                default_source.as_deref(),
            );
        }

        // Step 3: Handle arch state _wr nodes with collision groups
        for wr_node_id in arch_state_wr_nodes_needing_mux {
            self.create_arch_state_mux(merged, wr_node_id, instruction_specific_nodes);
        }
    }

    // =======================================================================
    // create_instruction_multiplexer
    // =======================================================================

    /// Create a priority mux to select between instruction-specific values
    /// that assign to the same target.
    fn create_instruction_multiplexer(
        merged: &mut ResourceGraph,
        target_id: &str,
        instruction_sources: &[(String, Vec<String>, Option<Value>)],
        default_source: Option<&str>,
    ) {
        let mux_id = format!("{}_mux", target_id);

        // Get target bit_width
        let target_bit_width = merged
            .get_node(target_id)
            .and_then(|n| n.data.get("bit_width"))
            .and_then(|v| v.as_i64())
            .unwrap_or(32);

        // Create mux node
        let mut mux_data: HashMap<String, Value> = HashMap::new();
        mux_data.insert("type".into(), json!("multiplexer"));
        mux_data.insert("name".into(), json!(&mux_id));
        mux_data.insert("display_name".into(), json!(format!("{} MUX", target_id)));
        mux_data.insert(
            "num_inputs".into(),
            json!(instruction_sources.len()),
        );
        mux_data.insert("operation".into(), json!("priority_select"));
        mux_data.insert("bit_width".into(), json!(target_bit_width));

        let mux_node = Node::new(
            Some(mux_id.clone()),
            Some(mux_data),
            false, false, None, false, None, None, false, false, 0, false, true, None, None,
        );
        merged.add_node(mux_node);

        // Add inputs
        for (i, (src_id, instr_names, _enable_expr)) in instruction_sources.iter().enumerate() {
            if !merged.nodes.contains_key(src_id) {
                continue;
            }

            // Create mux_input edge: source -> mux
            let mut input_data: HashMap<String, Value> = HashMap::new();
            input_data.insert("type".into(), json!("mux_input"));
            input_data.insert("input_index".into(), json!(i));
            input_data.insert(
                "source_instruction".into(),
                json!(instr_names.first().unwrap_or(&"unknown".to_string())),
            );
            let input_edge = Edge::new(src_id.clone(), mux_id.clone(), None, Some(input_data));
            merged.add_edge(input_edge);

            // Create select signal: OR of instruction enables if multiple
            let enable_id = if instr_names.len() == 1 {
                format!("{}_enable", instr_names[0])
            } else {
                // Create OR node for multiple enables
                let or_id = format!("{}_enable_or_{}", mux_id, i);
                let mut or_data: HashMap<String, Value> = HashMap::new();
                or_data.insert("type".into(), json!("logical_or"));
                or_data.insert("operator".into(), json!("||"));
                or_data.insert(
                    "display_name".into(),
                    json!(
                        instr_names
                            .iter()
                            .map(|n| format!("{}_enable", n))
                            .collect::<Vec<_>>()
                            .join(" || ")
                    ),
                );
                or_data.insert("bit_width".into(), json!(1));

                let or_node = Node::new(
                    Some(or_id.clone()),
                    Some(or_data),
                    false, false, None, false, None, None, false, false, 0, false, true, None,
                    None,
                );
                merged.add_node(or_node);

                for (j, instr_name) in instr_names.iter().enumerate() {
                    let en_id = format!("{}_enable", instr_name);
                    if merged.nodes.contains_key(&en_id) {
                        let mut d: HashMap<String, Value> = HashMap::new();
                        d.insert("type".into(), json!("operand"));
                        d.insert("operand_index".into(), json!(j));
                        d.insert("position".into(), json!(j));
                        let e = Edge::new(en_id, or_id.clone(), None, Some(d));
                        merged.add_edge(e);
                    }
                }

                or_id
            };

            // Create mux_select edge: enable -> mux
            if merged.nodes.contains_key(&enable_id) {
                let mut select_data: HashMap<String, Value> = HashMap::new();
                select_data.insert("type".into(), json!("mux_select"));
                select_data.insert("select_index".into(), json!(i));
                let select_edge =
                    Edge::new(enable_id, mux_id.clone(), None, Some(select_data));
                merged.add_edge(select_edge);
            }
        }

        // Add default input if present
        if let Some(default_src) = default_source {
            if merged.nodes.contains_key(default_src) {
                let mut default_data: HashMap<String, Value> = HashMap::new();
                default_data.insert("type".into(), json!("mux_default_input"));
                let default_edge =
                    Edge::new(default_src.to_string(), mux_id.clone(), None, Some(default_data));
                merged.add_edge(default_edge);

                // Mark mux as having default
                if let Some(mux_node) = merged.get_node_mut(&mux_id) {
                    mux_node.data.insert("has_default".into(), json!(true));
                    mux_node
                        .data
                        .insert("default_source".into(), json!(default_src));
                }
            }
        }

        // Connect mux output to target
        let mut output_data: HashMap<String, Value> = HashMap::new();
        output_data.insert("type".into(), json!("assignment"));
        output_data.insert(
            "description".into(),
            json!(format!(
                "Priority multiplexed assignment to {}",
                target_id
            )),
        );
        let output_edge = Edge::new(mux_id.clone(), target_id.to_string(), None, Some(output_data));
        merged.add_edge(output_edge);

    }

    // =======================================================================
    // create_arch_state_mux
    // =======================================================================

    /// Create a mux to merge group-specific arch state writes into the shared
    /// write node. For example, when `pc_wr` has been split into `beq_pc_wr`,
    /// `jal_pc_wr`, etc., this creates a mux that selects the appropriate value
    /// based on instruction enable signals.
    fn create_arch_state_mux(
        &self,
        merged: &mut ResourceGraph,
        wr_node_id: &str,
        instruction_specific_nodes: &HashMap<String, HashSet<String>>,
    ) {
        // Find all group-specific versions: nodes named {prefix}_{wr_node_id}
        // Collect (source_id_that_assigns_to_it, prefix_instruction, collision_node_id)
        let mut group_specific_sources: Vec<(String, String, String)> = Vec::new();
        let mut seen_sources: HashSet<String> = HashSet::new();

        // Scan for collision nodes
        let sorted_nodes: BTreeSet<String> = merged.nodes.keys().cloned().collect();
        for node_id in &sorted_nodes {
            let suffix = format!("_{}", wr_node_id);
            if node_id.ends_with(&suffix) && node_id != wr_node_id {
                let prefix = &node_id[..node_id.len() - suffix.len()];

                // Find ALL sources that assign to this collision node.
                // A collision node may have multiple assignment sources when
                // the collision group merged multiple instructions with
                // different PC write sources (e.g., add_pc_wr may contain
                // add's (pc+4), jr's rf[rs]_rd, and jalr's jump_dest).
                let incoming_eids: Vec<String> = merged
                    .get_node(node_id)
                    .map(|n| n.incoming_edges.iter().cloned().collect())
                    .unwrap_or_default();

                let mut collision_sources: Vec<String> = Vec::new();
                for eid in &incoming_eids {
                    if let Some(edge) = merged.get_edge(eid) {
                        if edge.data.get("type").and_then(|v| v.as_str()) == Some("assignment") {
                            collision_sources.push(edge.source.clone());
                        }
                    }
                }

                if collision_sources.len() <= 1 {
                    // Single source: use the prefix as the instruction
                    for source_id in &collision_sources {
                        if !seen_sources.contains(source_id) {
                            seen_sources.insert(source_id.clone());
                            group_specific_sources.push((
                                source_id.clone(),
                                prefix.to_string(),
                                node_id.clone(),
                            ));
                        }
                    }
                } else {
                    // Multiple sources: attribute each to the correct instruction
                    // by checking individual instruction graphs.
                    // The collision node's group has `member_instructions` -
                    // get these from the group info or the collision node's data.
                    let base_target = if wr_node_id.ends_with("_wr") {
                        &wr_node_id[..wr_node_id.len() - 3]
                    } else {
                        wr_node_id
                    };

                    for source_id in &collision_sources {
                        if seen_sources.contains(source_id) {
                            continue;
                        }
                        // Find which instruction has this specific assignment
                        let mut attributed_instr = prefix.to_string();
                        for instr in self.instruction_order.iter() {
                            if let Some(instr_graph) = self.graphs.get(instr) {
                                if instr_graph.get_node(source_id).is_some() {
                                    let has_assignment = instr_graph.edges.values().any(|e| {
                                        e.source == *source_id
                                            && (e.target == wr_node_id
                                                || e.target == base_target)
                                            && e.data.get("type").and_then(|v| v.as_str())
                                                == Some("assignment")
                                    });
                                    if has_assignment {
                                        attributed_instr = instr.clone();
                                        break;
                                    }
                                }
                            }
                        }
                        seen_sources.insert(source_id.clone());
                        group_specific_sources.push((
                            source_id.clone(),
                            attributed_instr,
                            node_id.clone(),
                        ));
                    }
                }
            }
        }

        // Also check direct assignments to the target node itself
        if let Some(target_node) = merged.get_node(wr_node_id) {
            let incoming_eids: Vec<String> =
                target_node.incoming_edges.iter().cloned().collect();

            for eid in &incoming_eids {
                if let Some(edge) = merged.get_edge(&eid) {
                    if edge.data.get("type").and_then(|v| v.as_str()) == Some("assignment") {
                        let source_id = edge.source.clone();
                        if seen_sources.contains(&source_id) {
                            continue;
                        }
                        // Check if source has instruction prefix
                        let mut found = false;
                        for instr in self.instruction_order.iter() {
                            if source_id.starts_with(&format!("{}_", instr)) {
                                seen_sources.insert(source_id.clone());
                                group_specific_sources.push((
                                    source_id.clone(),
                                    instr.clone(),
                                    source_id.clone(),
                                ));
                                found = true;
                                break;
                            }
                        }
                        // If source has no instruction prefix (shared node writing to
                        // arch state), check individual instruction graphs to find which
                        // instruction(s) originally had this assignment.
                        // Example: jr writes rf[rs] to pc directly, so rf[rs]_rd -> pc_wr
                        // exists but rf[rs]_rd is shared across many instructions.
                        if !found {
                            // Individual graphs use unsplit names (e.g., "pc" not "pc_wr")
                            let base_target = if wr_node_id.ends_with("_wr") {
                                &wr_node_id[..wr_node_id.len() - 3]
                            } else {
                                wr_node_id
                            };
                            for instr in self.instruction_order.iter() {
                                if let Some(instr_graph) = self.graphs.get(instr) {
                                    // Check if this instruction's graph has the source node
                                    // and an assignment edge from it to the write target
                                    if instr_graph.get_node(&source_id).is_some() {
                                        let has_assignment = instr_graph.edges.values().any(|e| {
                                            e.source == source_id
                                                && (e.target == wr_node_id
                                                    || e.target == base_target)
                                                && e.data.get("type").and_then(|v| v.as_str())
                                                    == Some("assignment")
                                        });
                                        if has_assignment {
                                            seen_sources.insert(source_id.clone());
                                            group_specific_sources.push((
                                                source_id.clone(),
                                                instr.clone(),
                                                source_id.clone(),
                                            ));
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        if group_specific_sources.is_empty() {
            return;
        }

        // Ensure target node exists
        if !merged.nodes.contains_key(wr_node_id) {
            // Create it from a collision node's metadata
            let mut created = false;
            for (_node_id, node) in merged.nodes.iter() {
                if node.data.get("original_id").and_then(|v| v.as_str()) == Some(wr_node_id) {
                    let orig_type = node.data.get("type").and_then(|v| v.as_str()).unwrap_or("var");
                    let mut target_data: HashMap<String, Value> = node.data.clone();
                    target_data.insert("type".into(), json!(orig_type));
                    target_data.insert("name".into(), json!(wr_node_id));
                    target_data.insert("is_arch_state_target".into(), json!(true));
                    target_data.remove("original_id");
                    let target_node = Node::new(
                        Some(wr_node_id.to_string()),
                        Some(target_data),
                        true,
                        false,
                        None,
                        node.is_uarch_state,
                        node.uarch_time,
                        node.pipe_time,
                        true,
                        true,
                        0,
                        false,
                        true,
                        None,
                        None,
                    );
                    merged.add_node(target_node);
                    created = true;
                    break;
                }
            }
            if !created {
                return;
            }
        }

        // Find default source: the _rd version to preserve current value
        let default_source_id = if wr_node_id.ends_with("_wr") {
            let rd_id = format!("{}_rd", &wr_node_id[..wr_node_id.len() - 3]);
            if merged.nodes.contains_key(&rd_id) {
                Some(rd_id)
            } else {
                let base = &wr_node_id[..wr_node_id.len() - 3];
                if merged.nodes.contains_key(base) {
                    Some(base.to_string())
                } else {
                    None
                }
            }
        } else {
            None
        };

        // Create the mux
        let mux_id = format!("{}_mux", wr_node_id);

        let mut mux_data: HashMap<String, Value> = HashMap::new();
        mux_data.insert("type".into(), json!("multiplexer"));
        mux_data.insert("name".into(), json!(&mux_id));
        mux_data.insert("display_name".into(), json!(format!("{} MUX", wr_node_id)));
        mux_data.insert(
            "num_inputs".into(),
            json!(group_specific_sources.len()),
        );
        mux_data.insert("operation".into(), json!("priority_select"));
        mux_data.insert("gated_write_mux".into(), json!(true));

        let mux_node = Node::new(
            Some(mux_id.clone()),
            Some(mux_data),
            false, false, None, false, None, None, false, false, 0, false, true, None, None,
        );
        merged.add_node(mux_node);

        // Determine which collision group source should be the default of
        // the outer mux.  When a collision group's source is a sub-mux with a
        // default input, it represents a "catch-all" group containing many
        // instructions (e.g., add_pc_wr_mux covers add, jr, jalr and all other
        // non-branch/non-jump instructions).  Promoting it to the outer mux's
        // default avoids needing an impossibly large OR of all member enables.
        let mut default_collision_idx: Option<usize> = None;
        for (i, (source_id, _prefix, _group_node_id)) in
            group_specific_sources.iter().enumerate()
        {
            if let Some(src_node) = merged.get_node(source_id) {
                let src_type = src_node.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                if src_type == "multiplexer" {
                    let has_default = src_node.data.get("has_default").and_then(|v| v.as_bool()).unwrap_or(false)
                        || src_node.incoming_edges.iter().any(|eid| {
                            merged.get_edge(eid)
                                .map(|e| e.data.get("type").and_then(|v| v.as_str()) == Some("mux_default_input"))
                                .unwrap_or(false)
                        });
                    if has_default {
                        default_collision_idx = Some(i);
                    }
                }
            }
        }

        // Add inputs with enable signals
        let mut source_ids_for_bypass: Vec<String> = Vec::new();
        let mut input_idx = 0usize;
        for (i, (source_id, prefix, _group_node_id)) in
            group_specific_sources.iter().enumerate()
        {
            if !merged.nodes.contains_key(source_id) {
                continue;
            }
            source_ids_for_bypass.push(source_id.clone());

            // If this collision group is the default (sub-mux with default input),
            // add it as the mux default instead of a numbered input with a select.
            if default_collision_idx == Some(i) {
                let mut default_data: HashMap<String, Value> = HashMap::new();
                default_data.insert("type".into(), json!("mux_default_input"));
                default_data.insert("source_instruction".into(), json!(prefix));
                let default_edge =
                    Edge::new(source_id.clone(), mux_id.clone(), None, Some(default_data));
                merged.add_edge(default_edge);

                if let Some(mux_node) = merged.get_node_mut(&mux_id) {
                    mux_node.data.insert("has_default".into(), json!(true));
                    mux_node.data.insert("default_source".into(), json!(source_id));
                }
                continue;
            }

            // mux_input edge
            let mut input_data: HashMap<String, Value> = HashMap::new();
            input_data.insert("type".into(), json!("mux_input"));
            input_data.insert("input_index".into(), json!(input_idx));
            input_data.insert("source_instruction".into(), json!(prefix));
            let input_edge =
                Edge::new(source_id.clone(), mux_id.clone(), None, Some(input_data));
            merged.add_edge(input_edge);

            // Find enable signal for this prefix
            let enable_signal = format!("{}_enable", prefix);
            if merged.nodes.contains_key(&enable_signal) {
                let mut select_data: HashMap<String, Value> = HashMap::new();
                select_data.insert("type".into(), json!("mux_select"));
                select_data.insert("select_index".into(), json!(input_idx));
                let select_edge =
                    Edge::new(enable_signal, mux_id.clone(), None, Some(select_data));
                merged.add_edge(select_edge);
            } else {
                // Try to find enable for any instruction matching this prefix
                let mut found = false;
                for instr_name in &self.instruction_order {
                    let en_id = format!("{}_enable", instr_name);
                    if merged.nodes.contains_key(&en_id) && instr_name == prefix {
                        let mut select_data: HashMap<String, Value> = HashMap::new();
                        select_data.insert("type".into(), json!("mux_select"));
                        select_data.insert("select_index".into(), json!(input_idx));
                        let select_edge =
                            Edge::new(en_id, mux_id.clone(), None, Some(select_data));
                        merged.add_edge(select_edge);
                        found = true;
                        break;
                    }
                }
                if !found {
                    // No enable signal found for this prefix
                }
            }

            input_idx += 1;
        }

        // Add default input from _rd node ONLY if no collision group was
        // promoted to default.  When a sub-mux collision group serves as
        // default, the _rd node is not needed (the sub-mux already has a
        // default path, e.g., (pc + 4)).
        if default_collision_idx.is_none() {
            if let Some(ref default_id) = default_source_id {
            if merged.nodes.contains_key(default_id) {
                let mut default_data: HashMap<String, Value> = HashMap::new();
                default_data.insert("type".into(), json!("mux_default_input"));
                let default_edge =
                    Edge::new(default_id.clone(), mux_id.clone(), None, Some(default_data));
                merged.add_edge(default_edge);

                if let Some(mux_node) = merged.get_node_mut(&mux_id) {
                    mux_node.data.insert("has_default".into(), json!(true));
                    mux_node
                        .data
                        .insert("default_source".into(), json!(default_id));
                }

                source_ids_for_bypass.push(default_id.clone());
            }
        }
        } // end if default_collision_idx.is_none()

        // Connect mux output to target
        let mut output_data: HashMap<String, Value> = HashMap::new();
        output_data.insert("type".into(), json!("assignment"));
        output_data.insert(
            "description".into(),
            json!(format!(
                "Priority multiplexed assignment to {}",
                wr_node_id
            )),
        );
        let output_edge =
            Edge::new(mux_id.clone(), wr_node_id.to_string(), None, Some(output_data));
        merged.add_edge(output_edge);

        // Remove bypassing edges (direct assignments from sources to target)
        let mut bypass_edges: Vec<String> = Vec::new();
        for src_id in &source_ids_for_bypass {
            if let Some(src_node) = merged.get_node(src_id) {
                for eid in &src_node.outgoing_edges {
                    if let Some(edge) = merged.get_edge(eid) {
                        if edge.target == wr_node_id
                            && edge.data.get("type").and_then(|v| v.as_str())
                                == Some("assignment")
                        {
                            bypass_edges.push(eid.clone());
                        }
                    }
                }
            }
        }
        for eid in &bypass_edges {
            merged.remove_edge(eid);
        }

        // Remove collision nodes - they're absorbed by the mux
        // Note: write_enable edges from collision nodes are NOT transferred here.
        // For memory array writes (e.g., rf[rd]_wr), write enables are handled by
        // create_memory_write_mux() which creates properly guarded enable signals
        // (e.g., rf_rd_ne_0_guarded_enable). Transferring write_enable edges here
        // would create a redundant condition that gets under-pipelined.
        let mut collision_nodes_to_remove: Vec<String> = Vec::new();
        for (node_id, node) in merged.nodes.iter() {
            if node.data.get("original_id").and_then(|v| v.as_str()) == Some(wr_node_id) {
                collision_nodes_to_remove.push(node_id.clone());
            }
        }

        for node_id in &collision_nodes_to_remove {
            merged.remove_node(node_id);
        }

    }

    // =======================================================================
    // multiplex_memory_write_ports
    // =======================================================================

    /// Create multiplexers for memory write ports when multiple instructions
    /// write to the same base memory with different addresses/data.
    fn multiplex_memory_write_ports(
        &self,
        merged: &mut ResourceGraph,
        instruction_specific_nodes: &HashMap<String, HashSet<String>>,
    ) {
        // Analyze original instruction graphs to find memory writes
        // memory_writes: base_memory -> Vec<{instruction, index_id, data_source_ids}>
        let mut memory_writes: HashMap<String, Vec<MemoryWriteInfo>> = HashMap::new();

        let mut sorted_write_instrs: Vec<&str> = self.graphs.keys().map(|s| s.as_str()).collect();
        sorted_write_instrs.sort();
        for instr_name in &sorted_write_instrs {
            let instr_graph = &self.graphs[*instr_name];
            for (node_id, node) in &instr_graph.nodes {
                let node_type = node
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");

                if node_type != "array_access" {
                    continue;
                }

                // Check if this is a write (has incoming assignment edges)
                let incoming_eids: Vec<String> =
                    node.incoming_edges.iter().cloned().collect();
                let mut write_source_ids: Vec<String> = Vec::new();
                let mut enable_expr: Option<Value> = None;

                for eid in &incoming_eids {
                    if let Some(edge) = instr_graph.get_edge(eid) {
                        if edge.data.get("type").and_then(|v| v.as_str()) == Some("assignment") {
                            write_source_ids.push(edge.source.clone());
                            if let Some(en) = edge.data.get("enable") {
                                enable_expr = Some(en.clone());
                            }
                        }
                    }
                }

                if write_source_ids.is_empty() {
                    continue;
                }

                // Find base memory and index
                let mut base_memory: Option<String> = None;
                let mut index_id: Option<String> = None;

                for eid in &incoming_eids {
                    if let Some(edge) = instr_graph.get_edge(eid) {
                        match edge.data.get("type").and_then(|v| v.as_str()) {
                            Some("array_base") => {
                                if let Some(src_node) = instr_graph.get_node(&edge.source) {
                                    base_memory = src_node
                                        .data
                                        .get("name")
                                        .and_then(|v| v.as_str())
                                        .map(|s| s.to_string())
                                        .or_else(|| Some(edge.source.clone()));
                                }
                            }
                            Some("array_index") => {
                                index_id = Some(edge.source.clone());
                            }
                            _ => {}
                        }
                    }
                }

                if let Some(base_mem) = base_memory {
                    memory_writes
                        .entry(base_mem.clone())
                        .or_default()
                        .push(MemoryWriteInfo {
                            instruction: instr_name.to_string(),
                            array_access_id: node_id.clone(),
                            index_id,
                            data_source_ids: write_source_ids,
                            enable_expr,
                        });
                }
            }
        }

        // For each memory with writes from multiple instructions, create mux
        let mut sorted_mem_keys: Vec<&String> = memory_writes.keys().collect();
        sorted_mem_keys.sort();
        for base_memory in sorted_mem_keys {
            let writes = memory_writes.get(base_memory).unwrap();
            let unique_instrs: HashSet<&str> =
                writes.iter().map(|w| w.instruction.as_str()).collect();
            if unique_instrs.len() <= 1 {
                continue;
            }

            // Sort writes by instruction name for deterministic mux indices
            let mut sorted_writes = writes.clone();
            sorted_writes.sort_by(|a, b| a.instruction.cmp(&b.instruction));
            self.create_memory_write_mux(merged, base_memory, &sorted_writes);
        }
    }

    /// Create multiplexers for memory write address and data.
    fn create_memory_write_mux(
        &self,
        merged: &mut ResourceGraph,
        base_memory: &str,
        writes: &[MemoryWriteInfo],
    ) {
        let write_port_id = format!("{}_shared_wr", base_memory);

        // Collect writer widths for byte-lane selection generation
        let mut writer_widths: HashMap<String, i64> = HashMap::new();
        for w in writes {
            let instr = &w.instruction;
            for data_src in &w.data_source_ids {
                let prefixed_src = format!("{}_{}", instr, data_src);
                let actual_src = if merged.nodes.contains_key(&prefixed_src) {
                    &prefixed_src
                } else if merged.nodes.contains_key(data_src) {
                    data_src
                } else {
                    continue;
                };
                if let Some(node) = merged.nodes.get(actual_src) {
                    if let Some(w) = node.data.get("bit_width").and_then(|v| v.as_i64()) {
                        writer_widths.insert(instr.clone(), w);
                        break;
                    }
                }
            }
        }

        // Create write port node
        let instr_list: Vec<&str> = writes.iter().map(|w| w.instruction.as_str()).collect();
        let mut port_data: HashMap<String, Value> = HashMap::new();
        port_data.insert("type".into(), json!("memory_write_port"));
        port_data.insert("name".into(), json!(&write_port_id));
        port_data.insert(
            "display_name".into(),
            json!(format!("{} Shared Write Port", base_memory)),
        );
        port_data.insert("base_memory".into(), json!(base_memory));
        port_data.insert("writers".into(), json!(instr_list));
        port_data.insert("writer_widths".into(), json!(writer_widths));

        let port_node = Node::new(
            Some(write_port_id.clone()),
            Some(port_data),
            false, false, None, false, None, None, false, false, 0, false, true, None, None,
        );
        merged.add_node(port_node);

        // --- Resolve actual node IDs for each write's address and data ---
        let resolve_node_id = |instr: &str, orig_id: &str| -> Option<String> {
            let prefixed = format!("{}_{}", instr, orig_id);
            if merged.nodes.contains_key(&prefixed) {
                Some(prefixed)
            } else if merged.nodes.contains_key(orig_id) {
                Some(orig_id.to_string())
            } else {
                // Fallback: find node from any co-writer instruction
                writes.iter().find_map(|w| {
                    let other_prefixed = format!("{}_{}", w.instruction, orig_id);
                    merged
                        .nodes
                        .contains_key(&other_prefixed)
                        .then(|| other_prefixed)
                })
            }
        };

        // Collect resolved address and data sources per write
        let mut addr_sources: Vec<(usize, String)> = Vec::new(); // (index, node_id)
        let mut data_sources: Vec<(usize, String)> = Vec::new(); // (index, node_id)

        for (i, write) in writes.iter().enumerate() {
            if let Some(ref idx_id) = write.index_id {
                if let Some(actual) = resolve_node_id(&write.instruction, idx_id) {
                    addr_sources.push((i, actual));
                }
            }
            for data_src in &write.data_source_ids {
                if let Some(actual) = resolve_node_id(&write.instruction, data_src) {
                    data_sources.push((i, actual));
                }
            }
        }

        // Check if muxes are needed (Python merger optimization: bypass when all
        // sources are the same node, e.g., all RF writes use 'rd' as address)
        let unique_addrs: HashSet<&str> = addr_sources.iter().map(|(_, id)| id.as_str()).collect();
        let unique_datas: HashSet<&str> = data_sources.iter().map(|(_, id)| id.as_str()).collect();
        let addr_needs_mux = unique_addrs.len() > 1;
        let data_needs_mux = unique_datas.len() > 1;

        let addr_mux_id = format!("{}_write_addr_mux", base_memory);
        let data_mux_id = format!("{}_write_data_mux", base_memory);

        // Create address mux only if multiple unique address sources
        if addr_needs_mux {
            let mut addr_mux_data: HashMap<String, Value> = HashMap::new();
            addr_mux_data.insert("type".into(), json!("multiplexer"));
            addr_mux_data.insert("name".into(), json!(&addr_mux_id));
            addr_mux_data.insert(
                "display_name".into(),
                json!(format!("{} Write Addr MUX", base_memory)),
            );
            addr_mux_data.insert("operation".into(), json!("priority_select"));
            addr_mux_data.insert("num_inputs".into(), json!(writes.len()));

            let addr_mux_node = Node::new(
                Some(addr_mux_id.clone()),
                Some(addr_mux_data),
                false, false, None, false, None, None, false, false, 0, false, true, None, None,
            );
            merged.add_node(addr_mux_node);

            for (i, actual_idx) in &addr_sources {
                let mut d: HashMap<String, Value> = HashMap::new();
                d.insert("type".into(), json!("mux_input"));
                d.insert("input_index".into(), json!(i));
                let e = Edge::new(actual_idx.clone(), addr_mux_id.clone(), None, Some(d));
                merged.add_edge(e);
            }
        }

        // Create data mux only if multiple unique data sources
        if data_needs_mux {
            let mut data_mux_data: HashMap<String, Value> = HashMap::new();
            data_mux_data.insert("type".into(), json!("multiplexer"));
            data_mux_data.insert("name".into(), json!(&data_mux_id));
            data_mux_data.insert(
                "display_name".into(),
                json!(format!("{} Write Data MUX", base_memory)),
            );
            data_mux_data.insert("operation".into(), json!("priority_select"));
            data_mux_data.insert("num_inputs".into(), json!(writes.len()));

            let data_mux_node = Node::new(
                Some(data_mux_id.clone()),
                Some(data_mux_data),
                false, false, None, false, None, None, false, false, 0, false, true, None, None,
            );
            merged.add_node(data_mux_node);

            for (i, actual_src) in &data_sources {
                let mut d: HashMap<String, Value> = HashMap::new();
                d.insert("type".into(), json!("mux_input"));
                d.insert("input_index".into(), json!(i));
                let e = Edge::new(actual_src.clone(), data_mux_id.clone(), None, Some(d));
                merged.add_edge(e);
            }
        }

        // Add enable/select signals for whichever muxes exist
        for (i, write) in writes.iter().enumerate() {
            let enable_id = format!("{}_enable", write.instruction);
            if merged.nodes.contains_key(&enable_id) {
                if addr_needs_mux {
                    let mut sd: HashMap<String, Value> = HashMap::new();
                    sd.insert("type".into(), json!("mux_select"));
                    sd.insert("select_index".into(), json!(i));
                    let se = Edge::new(enable_id.clone(), addr_mux_id.clone(), None, Some(sd));
                    merged.add_edge(se);
                }
                if data_needs_mux {
                    let mut sd2: HashMap<String, Value> = HashMap::new();
                    sd2.insert("type".into(), json!("mux_select"));
                    sd2.insert("select_index".into(), json!(i));
                    let se2 = Edge::new(enable_id, data_mux_id.clone(), None, Some(sd2));
                    merged.add_edge(se2);
                }
            }
        }

        // Connect address source (mux or direct) to write port
        if addr_needs_mux {
            let mut addr_out: HashMap<String, Value> = HashMap::new();
            addr_out.insert("type".into(), json!("write_address"));
            let addr_edge = Edge::new(
                addr_mux_id,
                write_port_id.clone(),
                None,
                Some(addr_out),
            );
            merged.add_edge(addr_edge);
        } else if !addr_sources.is_empty() {
            // All sources are the same - wire shared node directly to write port
            let shared_addr = &addr_sources[0].1;
            let mut addr_out: HashMap<String, Value> = HashMap::new();
            addr_out.insert("type".into(), json!("write_address"));
            let addr_edge = Edge::new(
                shared_addr.clone(),
                write_port_id.clone(),
                None,
                Some(addr_out),
            );
            merged.add_edge(addr_edge);
        }

        // Connect data source (mux or direct) to write port
        if data_needs_mux {
            let mut data_out: HashMap<String, Value> = HashMap::new();
            data_out.insert("type".into(), json!("write_data"));
            let data_edge =
                Edge::new(data_mux_id, write_port_id.clone(), None, Some(data_out));
            merged.add_edge(data_edge);
        } else if !data_sources.is_empty() {
            // All sources are the same - wire shared node directly to write port
            let shared_data = &data_sources[0].1;
            let mut data_out: HashMap<String, Value> = HashMap::new();
            data_out.insert("type".into(), json!("write_data"));
            let data_edge = Edge::new(
                shared_data.clone(),
                write_port_id.clone(),
                None,
                Some(data_out),
            );
            merged.add_edge(data_edge);
        }

        // --- Guarded Write Enable ---
        // Group writes by their enable condition (e.g., all RF-writing instructions
        // share the guard `rd != 0`). Create combined enable nodes matching the
        // Python merger's structure: OR(instruction_enables) && condition.
        // Deduplicate by instruction name: when a memory has multiple write ports
        // (e.g., umem[ea]_wr and umem[ea_pa]_wr), the same instruction may appear
        // multiple times in `writes`. Without dedup, duplicate edges are created
        // from each enable to the write_enable OR node, which breaks pipelining.
        let mut cond_to_instrs: BTreeMap<String, Vec<String>> = BTreeMap::new();
        let mut instrs_without_cond: Vec<String> = Vec::new();
        let mut seen_instrs: HashSet<String> = HashSet::new();

        for write in writes {
            if !seen_instrs.insert(write.instruction.clone()) {
                continue; // Skip duplicate instruction entries
            }
            let mut found_cond = false;
            if let Some(ref enable_expr) = write.enable_expr {
                if let Some(cond_node_id) = enable_expr_to_node_id(enable_expr) {
                    if merged.nodes.contains_key(&cond_node_id) {
                        cond_to_instrs
                            .entry(cond_node_id)
                            .or_default()
                            .push(write.instruction.clone());
                        found_cond = true;
                    }
                }
            }
            if !found_cond {
                instrs_without_cond.push(write.instruction.clone());
            }
        }

        let mut guarded_enable_ids: Vec<String> = Vec::new();

        for (cond_id, instrs) in &cond_to_instrs {
            let sanitized_cond = sanitize_cond_id(cond_id);

            let instr_enables: Vec<String> = instrs
                .iter()
                .map(|i| format!("{}_enable", i))
                .filter(|en| merged.nodes.contains_key(en))
                .collect();

            if instr_enables.is_empty() {
                continue;
            }

            let enable_source = if instr_enables.len() > 1 {
                // Create OR node combining all instruction enables
                let or_node_id = format!("{}_{}_enables", base_memory, sanitized_cond);
                let mut or_data: HashMap<String, Value> = HashMap::new();
                or_data.insert("type".into(), json!("logical_or"));
                or_data.insert("operation".into(), json!("||"));
                or_data.insert("bit_width".into(), json!(1));
                let or_node = Node::new(
                    Some(or_node_id.clone()),
                    Some(or_data),
                    false, false, None, false, None, None, false, false, 0, false, true, None,
                    None,
                );
                merged.add_node(or_node);

                for en_id in &instr_enables {
                    let mut d: HashMap<String, Value> = HashMap::new();
                    d.insert("type".into(), json!("logic_input"));
                    let e = Edge::new(en_id.clone(), or_node_id.clone(), None, Some(d));
                    merged.add_edge(e);
                }

                or_node_id
            } else {
                instr_enables[0].clone()
            };

            // Create AND node: enable_source && condition
            let and_node_id =
                format!("{}_{}_guarded_enable", base_memory, sanitized_cond);
            let mut and_data: HashMap<String, Value> = HashMap::new();
            and_data.insert("type".into(), json!("logical_and"));
            and_data.insert("operation".into(), json!("&&"));
            and_data.insert("bit_width".into(), json!(1));
            let and_node = Node::new(
                Some(and_node_id.clone()),
                Some(and_data),
                false, false, None, false, None, None, false, false, 0, false, true, None, None,
            );
            merged.add_node(and_node);

            // Connect enable source -> AND
            let mut d: HashMap<String, Value> = HashMap::new();
            d.insert("type".into(), json!("logic_input"));
            let e = Edge::new(enable_source, and_node_id.clone(), None, Some(d));
            merged.add_edge(e);

            // Connect condition -> AND
            let mut d2: HashMap<String, Value> = HashMap::new();
            d2.insert("type".into(), json!("logic_input"));
            let e2 = Edge::new(cond_id.clone(), and_node_id.clone(), None, Some(d2));
            merged.add_edge(e2);

            guarded_enable_ids.push(and_node_id);
        }

        // Add instructions without conditions as direct enables
        for instr in &instrs_without_cond {
            let en_id = format!("{}_enable", instr);
            if merged.nodes.contains_key(&en_id) {
                guarded_enable_ids.push(en_id);
            }
        }

        // Combine all guarded enables into one signal
        let combined_we_id = if guarded_enable_ids.len() > 1 {
            // Multiple groups/conditions - OR them together
            let final_or_id = format!("{}_write_enable", base_memory);
            let mut or_data: HashMap<String, Value> = HashMap::new();
            or_data.insert("type".into(), json!("logical_or"));
            or_data.insert("operation".into(), json!("||"));
            or_data.insert("bit_width".into(), json!(1));
            let or_node = Node::new(
                Some(final_or_id.clone()),
                Some(or_data),
                false, false, None, false, None, None, false, false, 0, false, true, None, None,
            );
            merged.add_node(or_node);

            for ge_id in &guarded_enable_ids {
                let mut d: HashMap<String, Value> = HashMap::new();
                d.insert("type".into(), json!("logic_input"));
                let e = Edge::new(ge_id.clone(), final_or_id.clone(), None, Some(d));
                merged.add_edge(e);
            }
            Some(final_or_id)
        } else if guarded_enable_ids.len() == 1 {
            Some(guarded_enable_ids[0].clone())
        } else {
            None
        };

        // Set combined_write_enable on write port and create write_enable edge
        if let Some(ref we_id) = combined_we_id {
            if let Some(port_node) = merged.get_node_mut(&write_port_id) {
                port_node
                    .data
                    .insert("combined_write_enable".into(), json!(we_id));
            }

            let mut we_data: HashMap<String, Value> = HashMap::new();
            we_data.insert("type".into(), json!("write_enable"));
            let we_edge =
                Edge::new(we_id.clone(), write_port_id.clone(), None, Some(we_data));
            merged.add_edge(we_edge);

            // Remove original write_enable edges on array_access _wr nodes for this
            // memory. These are now superseded by the guarded enable on the shared port.
            // Without this, the Verilog generator would find the old write_enable edge
            // and add a redundant, under-pipelined condition.
            let wr_node_pattern = format!("{}[", base_memory);
            let mut we_edges_to_remove: Vec<String> = Vec::new();
            // Search all edges for write_enable edges targeting array_access _wr nodes
            for (eid, edge) in merged.edges.iter() {
                if edge.data.get("type").and_then(|v| v.as_str()) == Some("write_enable") {
                    let tgt = &edge.target;
                    if tgt.starts_with(&wr_node_pattern) && tgt.ends_with("_wr") {
                        we_edges_to_remove.push(eid.clone());
                    }
                }
            }
            for eid in &we_edges_to_remove {
                merged.remove_edge(eid);
            }
        }
    }

    // =======================================================================
    // multiplex_memory_read_ports
    // =======================================================================

    /// Create multiplexers for memory read addresses when multiple instructions
    /// read from the same memory with different addresses.
    fn multiplex_memory_read_ports(
        &self,
        merged: &mut ResourceGraph,
        _instruction_specific_nodes: &HashMap<String, HashSet<String>>,
    ) {
        // Analyze original instruction graphs to find memory reads
        let mut memory_reads: HashMap<String, Vec<MemoryReadInfo>> = HashMap::new();

        let mut sorted_read_instrs: Vec<&str> = self.graphs.keys().map(|s| s.as_str()).collect();
        sorted_read_instrs.sort();
        for instr_name in &sorted_read_instrs {
            let instr_graph = &self.graphs[*instr_name];
            for (node_id, node) in &instr_graph.nodes {
                let node_type = node
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");

                if node_type != "array_access" {
                    continue;
                }

                // Skip writes
                let incoming_eids: Vec<String> =
                    node.incoming_edges.iter().cloned().collect();
                let has_assignment_in = incoming_eids.iter().any(|eid| {
                    instr_graph
                        .get_edge(eid)
                        .map(|e| {
                            e.data.get("type").and_then(|v| v.as_str()) == Some("assignment")
                        })
                        .unwrap_or(false)
                });
                if has_assignment_in {
                    continue;
                }

                // Find base memory and index
                let mut base_memory: Option<String> = None;
                let mut index_id: Option<String> = None;

                for eid in &incoming_eids {
                    if let Some(edge) = instr_graph.get_edge(eid) {
                        match edge.data.get("type").and_then(|v| v.as_str()) {
                            Some("array_base") => {
                                if let Some(src_node) = instr_graph.get_node(&edge.source) {
                                    base_memory = src_node
                                        .data
                                        .get("name")
                                        .and_then(|v| v.as_str())
                                        .map(|s| s.to_string())
                                        .or_else(|| Some(edge.source.clone()));
                                }
                            }
                            Some("array_index") => {
                                index_id = Some(edge.source.clone());
                            }
                            _ => {}
                        }
                    }
                }

                // Only consider 'mem' type memories
                if let Some(ref base_mem) = base_memory {
                    if let Some(mem_node) = instr_graph.get_node(base_mem) {
                        let mem_type = mem_node
                            .data
                            .get("type")
                            .and_then(|v| v.as_str())
                            .unwrap_or("");
                        if mem_type != "isa_state mem" {
                            continue;
                        }
                    } else {
                        continue;
                    }
                } else {
                    continue;
                }

                // Skip instruction fetch reads (pc-indexed)
                if let Some(ref idx) = index_id {
                    if idx.to_lowercase().contains("pc") {
                        continue;
                    }
                }

                if let (Some(base_mem), Some(idx)) = (base_memory, index_id) {
                    memory_reads
                        .entry(base_mem)
                        .or_default()
                        .push(MemoryReadInfo {
                            instruction: instr_name.to_string(),
                            array_access_id: node_id.clone(),
                            index_id: idx,
                        });
                }
            }
        }

        // For each memory with multiple unique read addresses, create address mux
        let mut sorted_read_keys: Vec<&String> = memory_reads.keys().collect();
        sorted_read_keys.sort();
        for base_memory in sorted_read_keys {
            let reads = memory_reads.get(base_memory).unwrap();
            if reads.len() <= 1 {
                continue;
            }

            // Group by address pattern
            let mut unique_addrs: HashMap<String, Vec<String>> = HashMap::new();
            for r in reads {
                let prefixed_idx = format!("{}_{}", r.instruction, r.index_id);
                let actual_idx = if merged.nodes.contains_key(&prefixed_idx) {
                    prefixed_idx
                } else if merged.nodes.contains_key(&r.index_id) {
                    r.index_id.clone()
                } else {
                    continue;
                };

                unique_addrs
                    .entry(actual_idx)
                    .or_default()
                    .push(r.instruction.clone());
            }

            if unique_addrs.len() <= 1 {
                continue;
            }

            // Create address mux
            let mux_id = format!("{}_read_addr_mux", base_memory);

            let mut mux_data: HashMap<String, Value> = HashMap::new();
            mux_data.insert("type".into(), json!("multiplexer"));
            mux_data.insert("name".into(), json!(&mux_id));
            mux_data.insert(
                "display_name".into(),
                json!(format!("{} Read Address MUX", base_memory)),
            );
            mux_data.insert("operation".into(), json!("priority_select"));
            mux_data.insert("is_address_mux".into(), json!(true));

            let mux_node = Node::new(
                Some(mux_id.clone()),
                Some(mux_data),
                false, false, None, false, None, None, false, false, 0, false, true, None, None,
            );
            merged.add_node(mux_node);

            let mut sorted_addrs: Vec<(&String, &Vec<String>)> = unique_addrs.iter().collect();
            sorted_addrs.sort_by_key(|(k, _)| k.as_str());
            for (i, (addr_id, instrs)) in sorted_addrs.iter().enumerate() {
                // Address input
                let mut d: HashMap<String, Value> = HashMap::new();
                d.insert("type".into(), json!("mux_input"));
                d.insert("input_index".into(), json!(i));
                let e = Edge::new(addr_id.to_string(), mux_id.clone(), None, Some(d));
                merged.add_edge(e);

                // Enable select (OR of instruction enables)
                if instrs.len() == 1 {
                    let en_id = format!("{}_enable", instrs[0]);
                    if merged.nodes.contains_key(&en_id) {
                        let mut sd: HashMap<String, Value> = HashMap::new();
                        sd.insert("type".into(), json!("mux_select"));
                        sd.insert("select_index".into(), json!(i));
                        let se = Edge::new(en_id, mux_id.clone(), None, Some(sd));
                        merged.add_edge(se);
                    }
                }
            }
        }
    }

    // =======================================================================
    // create_read_enable_signals
    // =======================================================================

    /// Create read enable signals for array read ports that are only used by a
    /// subset of instructions.
    ///
    /// For each array read node `{array}[{index}]_rd` (e.g. `rf[rs]_rd`,
    /// `rf[rt]_rd`) that appears in *some* but not *all* per-instruction
    /// graphs, create:
    ///
    /// `{array}_{index}_rd_enable = instr1_enable || instr2_enable || ...`
    ///
    /// These signals are used by hazard resolution to gate stall conditions,
    /// preventing false stalls when instructions don't actually read a
    /// particular register port (e.g. MIPS I-type instructions don't read
    /// `rf[rt]` -- they write to it).
    fn create_read_enable_signals(&self, merged: &mut ResourceGraph) {
        log::info!("\n============================================================");
        log::info!("CREATING READ ENABLE SIGNALS");
        log::info!("============================================================");

        // Collect which instructions use each array-read node.
        // Pattern we match: {array}[{index}]_rd   (no suffix after _rd)
        let mut read_node_users: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();

        for (instr_name, instr_graph) in &self.graphs {
            for node_id in instr_graph.nodes.keys() {
                // Match pattern: must contain '[', end with ']_rd', and the
                // part after the last ']_rd' must be empty.
                if let Some(bracket_start) = node_id.find('[') {
                    if node_id.ends_with("]_rd") {
                        // Verify the bracket is balanced
                        let bracket_end = node_id.rfind(']').unwrap();
                        if bracket_end > bracket_start {
                            read_node_users
                                .entry(node_id.clone())
                                .or_default()
                                .insert(instr_name.clone());
                        }
                    }
                }
            }
        }

        let all_instrs: BTreeSet<String> =
            self.instruction_order.iter().cloned().collect();
        let mut created = 0usize;

        for (node_id, using_instrs) in &read_node_users {
            // Skip if *all* instructions use this read (no gating needed)
            if *using_instrs == all_instrs {
                continue;
            }
            // Only process reads that exist in the merged graph
            if !merged.nodes.contains_key(node_id) {
                continue;
            }

            // Parse array and index from the node id
            let bracket_start = node_id.find('[').unwrap();
            let bracket_end = node_id.rfind(']').unwrap();
            let array_name = &node_id[..bracket_start];
            let index_name = &node_id[bracket_start + 1..bracket_end];

            // Skip PC-indexed reads (instruction fetch is always enabled)
            if index_name == "pc" || index_name == "ip" {
                continue;
            }

            let enable_node_id = format!("{}_{}_rd_enable", array_name, index_name);

            // Skip if already exists
            if merged.nodes.contains_key(&enable_node_id) {
                log::info!(
                    "  {} already exists, skipping",
                    enable_node_id
                );
                continue;
            }

            // Collect instruction enable node ids
            let instr_enables: Vec<String> = using_instrs
                .iter()
                .map(|name| format!("{}_enable", name))
                .filter(|en_id| merged.nodes.contains_key(en_id))
                .collect();

            if instr_enables.is_empty() {
                continue;
            }

            if instr_enables.len() == 1 {
                // Single instruction: create an alias node
                let mut data: HashMap<String, Value> = HashMap::new();
                data.insert("type".into(), json!("alias"));
                data.insert(
                    "display_name".into(),
                    json!(format!("{}[{}] read enable", array_name, index_name)),
                );
                data.insert("bit_width".into(), json!(1));
                let node = Node::new(
                    Some(enable_node_id.clone()),
                    Some(data),
                    false, false, None, false, None, None,
                    false, false, 0, false, true, None, None,
                );
                merged.add_node(node);

                let mut ed: HashMap<String, Value> = HashMap::new();
                ed.insert("type".into(), json!("assignment"));
                let e = Edge::new(
                    instr_enables[0].clone(),
                    enable_node_id.clone(),
                    None,
                    Some(ed),
                );
                merged.add_edge(e);

                log::info!(
                    "  Created {} = {}",
                    enable_node_id, instr_enables[0]
                );
            } else {
                // Multiple instructions: create a logical_or node
                let mut data: HashMap<String, Value> = HashMap::new();
                data.insert("type".into(), json!("logical_or"));
                data.insert("operation".into(), json!("||"));
                data.insert(
                    "display_name".into(),
                    json!(format!("{}[{}] read enable", array_name, index_name)),
                );
                data.insert("bit_width".into(), json!(1));
                let node = Node::new(
                    Some(enable_node_id.clone()),
                    Some(data),
                    false, false, None, false, None, None,
                    false, false, 0, false, true, None, None,
                );
                merged.add_node(node);

                for en_id in &instr_enables {
                    let mut ed: HashMap<String, Value> = HashMap::new();
                    ed.insert("type".into(), json!("logic_input"));
                    let e = Edge::new(
                        en_id.clone(),
                        enable_node_id.clone(),
                        None,
                        Some(ed),
                    );
                    merged.add_edge(e);
                }

                log::info!(
                    "  Created {} = {}",
                    enable_node_id,
                    instr_enables.join(" || ")
                );
            }

            // Also store read_enable on the read node data for cross-reference
            if let Some(read_node) = merged.nodes.get_mut(node_id) {
                read_node
                    .data
                    .insert("read_enable".into(), json!(enable_node_id));
            }

            created += 1;
        }

        log::info!("Created {} read enable signal(s)", created);
    }

    // =======================================================================
    // create_decode_logic
    // =======================================================================

    fn create_decode_logic(&self, merged: &mut ResourceGraph) {
        let mut sorted_decode_keys: Vec<&String> = self.decode_info.keys().collect();
        sorted_decode_keys.sort();
        for instr_name in &sorted_decode_keys {
            let decode_info = &self.decode_info[*instr_name];
            // Create instruction_enable node
            let enable_id = format!("{}_enable", instr_name);
            let mut enable_data: HashMap<String, Value> = HashMap::new();
            enable_data.insert("type".into(), json!("instruction_enable"));
            enable_data.insert("name".into(), json!(enable_id));
            enable_data.insert("display_name".into(), json!(enable_id));
            enable_data.insert("bit_width".into(), json!(1));
            enable_data.insert("instruction".into(), json!(instr_name));

            let enable_node = Node::new(
                Some(enable_id.clone()),
                Some(enable_data),
                false,  // is_arch_state
                false,  // used_as_index
                None,   // indexed_by
                false,  // is_uarch_state
                None,   // uarch_time
                None,   // pipe_time
                false,  // from_isa_spec
                false,  // already_split
                0,      // latency
                false,  // variable_latency
                true,   // is_shared
                None,   // pipe_id
                None,   // dual_issue_time
            );
            merged.add_node(enable_node);

            // Create decode comparison nodes from assume conditions
            if !decode_info.assume_conditions.is_empty() {
                let mut prev_node: Option<String> = None;

                for (i, (field, op, value)) in decode_info.assume_conditions.iter().enumerate() {
                    let cmp_id = format!("{}_decode_cmp_{}", instr_name, i);
                    let mut cmp_data: HashMap<String, Value> = HashMap::new();
                    cmp_data
                        .insert("type".into(), json!("decode_comparison"));
                    cmp_data.insert(
                        "display_name".into(),
                        json!(format!("{} {} {}", field, op, value)),
                    );
                    cmp_data.insert("bit_width".into(), json!(1));
                    cmp_data.insert("field".into(), json!(field));
                    cmp_data.insert("operator".into(), json!(op));
                    cmp_data.insert("value".into(), json!(value));

                    let cmp_node = Node::new(
                        Some(cmp_id.clone()),
                        Some(cmp_data),
                        false, false, None, false, None, None, false, false, 0, false, true, None,
                        None,
                    );
                    merged.add_node(cmp_node);

                    if let Some(prev) = prev_node {
                        // AND with previous condition
                        let and_id = format!("{}_decode_and_{}", instr_name, i);
                        let mut and_data: HashMap<String, Value> = HashMap::new();
                        and_data.insert("type".into(), json!("operation"));
                        and_data.insert("operator".into(), json!("&"));
                        and_data
                            .insert("display_name".into(), json!(and_id));
                        and_data.insert("bit_width".into(), json!(1));

                        let and_node = Node::new(
                            Some(and_id.clone()),
                            Some(and_data),
                            false, false, None, false, None, None, false, false, 0, false, true,
                            None, None,
                        );
                        merged.add_node(and_node);

                        // edge: prev -> and (left operand)
                        let mut d1: HashMap<String, Value> = HashMap::new();
                        d1.insert("type".into(), json!("operand"));
                        d1.insert("position".into(), json!("left"));
                        let edge1 = Edge::new(prev, and_id.clone(), None, Some(d1));
                        merged.add_edge(edge1);

                        // edge: cmp -> and (right operand)
                        let mut d2: HashMap<String, Value> = HashMap::new();
                        d2.insert("type".into(), json!("operand"));
                        d2.insert("position".into(), json!("right"));
                        let edge2 = Edge::new(cmp_id.clone(), and_id.clone(), None, Some(d2));
                        merged.add_edge(edge2);

                        prev_node = Some(and_id);
                    } else {
                        prev_node = Some(cmp_id);
                    }
                }

                // Connect final condition to enable node
                if let Some(final_cond) = prev_node {
                    let mut d: HashMap<String, Value> = HashMap::new();
                    d.insert("type".into(), json!("decode_enable"));
                    let edge = Edge::new(final_cond, enable_id, None, Some(d));
                    merged.add_edge(edge);
                }
            }
        }
    }
}

// ===========================================================================
// split_arch_state_nodes  (public free function)
// ===========================================================================

/// Split each architectural-state node into a `_rd` (read) and `_wr` (write)
/// pair, redirecting edges accordingly.
///
/// Matches Python `split_arch_state_nodes()` in graph_merger.py:
/// - Skips nodes with `array_depth` or `is_memory` (memory arrays)
/// - Skips nodes already ending in `_rd` or `_wr`
/// - Redirects incoming `assignment`/`mux_output` edges to `_wr`
/// - Redirects outgoing edges to come from `_rd`
/// - Tracks max source timing for the `_wr` node
/// - Re-infers timing after splitting
pub fn split_arch_state_nodes(graph: &mut ResourceGraph) {
    // Collect candidates: arch state nodes that aren't already split or memory/array
    let arch_nodes: Vec<String> = graph
        .nodes
        .values()
        .filter(|n| {
            if !n.is_arch_state || n.already_split {
                return false;
            }
            if n.id.ends_with("_rd") || n.id.ends_with("_wr") {
                return false;
            }
            // Skip memory arrays — accessed via indexing, not split into copies
            let has_array_depth = n
                .data
                .get("array_depth")
                .map(|v| !v.is_null() && v.as_i64().unwrap_or(0) > 0)
                .unwrap_or(false);
            let is_memory = n
                .data
                .get("is_memory")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            if has_array_depth || is_memory {
                return false;
            }
            true
        })
        .map(|n| n.id.clone())
        .collect();

    let mut splits_made = 0;

    for node_id in &arch_nodes {
        let node = match graph.nodes.get(node_id) {
            Some(n) => n.clone(),
            None => continue,
        };

        let rd_id = format!("{}_rd", node_id);
        let wr_id = format!("{}_wr", node_id);

        // Create read node
        let mut rd_data = node.data.clone();
        rd_data.insert("display_name".into(), json!(rd_id));
        if !rd_data.contains_key("name") {
            rd_data.insert("name".into(), json!(node_id));
        }
        let rd_node = Node::new(
            Some(rd_id.clone()),
            Some(rd_data),
            true,                               // is_arch_state
            node.used_as_index,                  // used_as_index
            node.indexed_by.clone(),             // indexed_by
            node.is_uarch_state,                 // is_uarch_state
            Some(node.uarch_time.unwrap_or(0)),  // uarch_time
            Some(0),                             // pipe_time
            node.from_isa_spec,                  // from_isa_spec
            true,                                // already_split
            0,                                   // latency
            false,                               // variable_latency
            node.is_shared,                      // is_shared
            None,                                // pipe_id
            None,                                // dual_issue_time
        );

        // Create write node
        let mut wr_data = node.data.clone();
        wr_data.insert("display_name".into(), json!(wr_id));
        if !wr_data.contains_key("name") {
            wr_data.insert("name".into(), json!(node_id));
        }
        let wr_node = Node::new(
            Some(wr_id.clone()),
            Some(wr_data),
            true,                // is_arch_state
            false,               // used_as_index
            None,                // indexed_by
            node.is_uarch_state, // is_uarch_state
            None,                // uarch_time (computed from sources below)
            None,                // pipe_time
            node.from_isa_spec,  // from_isa_spec
            true,                // already_split
            0,                   // latency
            false,               // variable_latency
            node.is_shared,      // is_shared
            None,                // pipe_id
            None,                // dual_issue_time
        );

        // Collect edges to redirect
        let incoming: Vec<String> = node.incoming_edges.iter().cloned().collect();
        let outgoing: Vec<String> = node.outgoing_edges.iter().cloned().collect();

        // Add new nodes
        graph.nodes.insert(rd_id.clone(), rd_node);
        graph.nodes.insert(wr_id.clone(), wr_node);

        // Redirect incoming assignment edges to _wr, track max source time
        let mut max_source_time: i64 = 0;
        for eid in &incoming {
            if let Some(edge) = graph.edges.get(eid).cloned() {
                let etype = edge
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                if etype == "assignment" || etype == "mux_output" {
                    // Track timing from source
                    if let Some(src_node) = graph.nodes.get(&edge.source) {
                        if let Some(t) = src_node.uarch_time {
                            max_source_time = max_source_time.max(t);
                        }
                    }
                    let new_edge =
                        Edge::new(edge.source, wr_id.clone(), None, Some(edge.data));
                    graph.add_edge(new_edge);
                } else {
                    let new_edge =
                        Edge::new(edge.source, rd_id.clone(), None, Some(edge.data));
                    graph.add_edge(new_edge);
                }
            }
        }

        // Set write node's uarch_time based on its sources
        if let Some(wr) = graph.nodes.get_mut(&wr_id) {
            wr.uarch_time = Some(max_source_time);
        }

        // Redirect outgoing edges — all come from _rd
        for eid in &outgoing {
            if let Some(edge) = graph.edges.get(eid).cloned() {
                let new_edge =
                    Edge::new(rd_id.clone(), edge.target, None, Some(edge.data));
                graph.add_edge(new_edge);
            }
        }

        // Remove old node and its edges
        for eid in incoming.iter().chain(outgoing.iter()) {
            graph.remove_edge(eid);
        }
        graph.nodes.remove(node_id);
        splits_made += 1;

    }

    // Re-infer timing after splitting
    if splits_made > 0 {
        graph.infer_uarch_time(true);
    }
}

// ===========================================================================
// promote_mem_widths  (public free function)
// ===========================================================================

/// Promote memory node widths based on actual access patterns in the merged graph.
///
/// For each memory node with `width_inferred=true`:
/// 1. Find all memory access nodes (split `_rd`/`_wr` nodes or `array_access` nodes)
/// 2. Determine the maximum access width
/// 3. Set `bit_width` to the maximum and store `access_widths` metadata
pub fn promote_mem_widths(graph: &mut ResourceGraph) {
    // Find all mem nodes with width_inferred=true
    let mem_node_ids: Vec<String> = graph
        .nodes
        .values()
        .filter(|n| {
            let ntype = n
                .data
                .get("type")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let width_inferred = n
                .data
                .get("width_inferred")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            ntype == "isa_state mem" && width_inferred
        })
        .map(|n| n.id.clone())
        .collect();

    for mem_node_id in &mem_node_ids {
        let mem_name = graph.nodes[mem_node_id]
            .data
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or(mem_node_id)
            .to_string();

        let mut access_widths: Vec<i64> = Vec::new();

        let all_node_ids: Vec<String> = graph.nodes.keys().cloned().collect();

        for nid in &all_node_ids {
            let node = &graph.nodes[nid];

            let ntype = node
                .data
                .get("type")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if ntype == "concatenation" {
                continue;
            }

            // Check for split memory access nodes: memname[...]_rd or memname[...]_wr
            let pattern = format!("{}[", mem_name);
            if nid.contains(&pattern) && (nid.contains("_rd") || nid.contains("_wr")) {
                let width = node.data.get("bit_width").and_then(|v| v.as_i64());

                if width.is_none() {
                    if nid.contains("_rd") {
                        // Collect ALL individual connected widths to capture sub-word accesses.
                        // A shared read node (e.g., umem[addr]_rd) may connect to destinations
                        // of different widths (byte_data=8, halfword_data=16, data=32).
                        // We need all of them, not just the max.
                        for eid in &node.outgoing_edges {
                            if let Some(edge) = graph.edges.get(eid) {
                                let et = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                                if et == "concat_input" || et == "concatenation_input" {
                                    continue;
                                }
                                if let Some(tgt) = graph.nodes.get(&edge.target) {
                                    let tt = tgt.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                                    if tt == "concatenation" { continue; }
                                    if let Some(tw) = tgt.data.get("bit_width").and_then(|v| v.as_i64()) {
                                        if tw > 0 { access_widths.push(tw); }
                                    }
                                }
                            }
                        }
                        continue;
                    } else if nid.contains("_wr") {
                        // Collect ALL individual source widths for write nodes
                        for eid in &node.incoming_edges {
                            if let Some(edge) = graph.edges.get(eid) {
                                let et = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                                if et == "assignment" {
                                    if let Some(src) = graph.nodes.get(&edge.source) {
                                        if let Some(sw) = src.data.get("bit_width").and_then(|v| v.as_i64()) {
                                            if sw > 0 { access_widths.push(sw); }
                                        }
                                    }
                                }
                            }
                        }
                        continue;
                    }
                }

                if let Some(w) = width {
                    if w > 0 { access_widths.push(w); }
                }
                continue;
            }

            // Also check for regular array_access nodes (before splitting)
            if ntype == "array_access" {
                let is_our_mem = node.incoming_edges.iter().any(|eid| {
                    graph.edges.get(eid).map_or(false, |e| {
                        e.data.get("type").and_then(|v| v.as_str()) == Some("array_base")
                            && e.source == *mem_node_id
                    })
                });
                if is_our_mem {
                    if let Some(w) = node.data.get("bit_width").and_then(|v| v.as_i64()) {
                        if w > 0 { access_widths.push(w); }
                    }
                }
            }
        }

        if !access_widths.is_empty() {
            let max_width = *access_widths.iter().max().unwrap();

            if let Some(mem_node) = graph.nodes.get_mut(mem_node_id) {
                mem_node.data.insert("bit_width".into(), json!(max_width));

                // Normalize to standard power-of-2 values
                let normalized: Vec<i64> = access_widths
                    .iter()
                    .map(|&w| if w <= 8 { 8 } else if w <= 16 { 16 } else if w <= 32 { 32 } else { 64 })
                    .collect::<std::collections::BTreeSet<_>>()
                    .into_iter()
                    .collect();

                let existing: Vec<i64> = mem_node
                    .data.get("access_widths")
                    .and_then(|v| v.as_array())
                    .map(|arr| arr.iter().filter_map(|v| v.as_i64()).collect())
                    .unwrap_or_default();

                let mut all: Vec<i64> = existing.into_iter().chain(normalized)
                    .collect::<std::collections::BTreeSet<_>>()
                    .into_iter().collect();
                all.sort();

                mem_node.data.insert("access_widths".into(), json!(all));
            }
        } else if let Some(mem_node) = graph.nodes.get_mut(mem_node_id) {
            mem_node.data.insert("bit_width".into(), json!(32));
        }
    }
}

// ===========================================================================
// cleanup_bypassed_edges  (public free function)
// ===========================================================================

/// Remove direct assignment edges that bypass multiplexers.
pub fn cleanup_bypassed_edges(graph: &mut ResourceGraph) {
    let mux_node_ids: Vec<String> = graph
        .nodes
        .values()
        .filter(|n| n.data.get("type").and_then(|v| v.as_str()) == Some("multiplexer"))
        .map(|n| n.id.clone())
        .collect();

    if mux_node_ids.is_empty() { return; }

    let mut edges_to_remove: Vec<String> = Vec::new();

    for mux_id in &mux_node_ids {
        let mux_node = match graph.nodes.get(mux_id) { Some(n) => n, None => continue };

        let mux_targets: Vec<String> = mux_node.outgoing_edges.iter().filter_map(|eid| {
            graph.edges.get(eid).and_then(|e| {
                if e.data.get("type").and_then(|v| v.as_str()) == Some("assignment") {
                    Some(e.target.clone())
                } else { None }
            })
        }).collect();

        let mux_sources: Vec<String> = mux_node.incoming_edges.iter().filter_map(|eid| {
            graph.edges.get(eid).and_then(|e| {
                if e.data.get("type").and_then(|v| v.as_str()) == Some("mux_input") {
                    Some(e.source.clone())
                } else { None }
            })
        }).collect();

        // Remove ANY direct assignment edge to a mux target that doesn't come
        // from the mux itself. This catches both mux sources that also directly
        // assign, and non-mux-source nodes that bypass the mux entirely.
        for target_id in &mux_targets {
            if let Some(target_node) = graph.nodes.get(target_id) {
                for eid in &target_node.incoming_edges {
                    if let Some(edge) = graph.edges.get(eid) {
                        let et = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                        if et == "assignment" && edge.source != *mux_id {
                            edges_to_remove.push(eid.clone());
                        }
                    }
                }
            }
        }
    }

    for eid in &edges_to_remove { graph.remove_edge(eid); }
}

// ===========================================================================
// deep_copy_graph  (public free function)
// ===========================================================================

/// Create a deep copy of a [`ResourceGraph`].
pub fn deep_copy_graph(graph: &ResourceGraph) -> ResourceGraph {
    graph.copy()
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sharing_type_rank() {
        assert_eq!(SharingType::ArchitecturalState.rank(), 0);
        assert_eq!(SharingType::FullyShared.rank(), 1);
        assert_eq!(SharingType::GroupwiseShared.rank(), 2);
        assert_eq!(SharingType::InstructionSpecific.rank(), 3);
    }

    #[test]
    fn test_node_classification_collision() {
        let nc = NodeClassification {
            node_id: "n".into(),
            groups: vec![
                StructuralGroup {
                    group_id: "g0".into(),
                    instructions: BTreeSet::from(["add".into()]),
                    structure_key: "k0".into(),
                },
                StructuralGroup {
                    group_id: "g1".into(),
                    instructions: BTreeSet::from(["sub".into()]),
                    structure_key: "k1".into(),
                },
            ],
            merged_ids: HashMap::from([
                ("g0".into(), "add_n".into()),
                ("g1".into(), "sub_n".into()),
            ]),
            tier: SharingType::InstructionSpecific,
            is_architectural: false,
        };
        assert!(nc.is_collision());
        assert_eq!(
            nc.get_merged_id_for_instruction("add"),
            Some(&"add_n".to_string())
        );
        assert_eq!(
            nc.get_merged_id_for_instruction("sub"),
            Some(&"sub_n".to_string())
        );
        assert_eq!(nc.get_merged_id_for_instruction("mul"), None);
    }

    #[test]
    fn test_group_tracker_basic() {
        let mut tracker = GroupTracker::new(vec!["add".into(), "sub".into()]);
        assert_eq!(tracker.num_instructions, 2);

        let nc = NodeClassification {
            node_id: "n".into(),
            groups: vec![StructuralGroup {
                group_id: "shared".into(),
                instructions: BTreeSet::from(["add".into(), "sub".into()]),
                structure_key: "k".into(),
            }],
            merged_ids: HashMap::from([("shared".into(), "n".into())]),
            tier: SharingType::FullyShared,
            is_architectural: false,
        };

        tracker.add_classification("n".into(), nc);
        assert_eq!(tracker.get_merged_id("add", "n"), "n");
        assert_eq!(tracker.get_merged_id("sub", "n"), "n");
        assert!(tracker.get_collision_nodes().is_empty());
    }

    #[test]
    fn test_graph_build_plan_ordered() {
        let mut plan = GraphBuildPlan::new();

        plan.architectural_nodes.push(NodeBuildPlan {
            node_id: "arch1".into(),
            original_id: "arch1".into(),
            source_instruction: "add".into(),
            sharing_type: SharingType::ArchitecturalState,
            group_info: None,
            dependencies: HashSet::new(),
            is_collision_dependent: false,
            metadata: HashMap::new(),
        });

        plan.instruction_specific_nodes.push(NodeBuildPlan {
            node_id: "spec1".into(),
            original_id: "spec1".into(),
            source_instruction: "add".into(),
            sharing_type: SharingType::InstructionSpecific,
            group_info: None,
            dependencies: HashSet::new(),
            is_collision_dependent: false,
            metadata: HashMap::new(),
        });

        let ordered = plan.get_all_nodes_ordered();
        assert_eq!(ordered.len(), 2);
        assert_eq!(ordered[0].node_id, "arch1");
        assert_eq!(ordered[1].node_id, "spec1");
    }

    #[test]
    fn test_merger_new() {
        let merger = ResourceGraphMerger::new(None);
        assert!(merger.graphs.is_empty());
        assert!(merger.instruction_order.is_empty());
        assert!(merger.defines.is_empty());

        let mut defs = HashMap::new();
        defs.insert("XLEN".into(), "32".into());
        let merger2 = ResourceGraphMerger::new(Some(defs));
        assert_eq!(merger2.defines.get("XLEN").unwrap(), "32");
    }

    #[test]
    fn test_merger_empty_merge_fails() {
        let mut merger = ResourceGraphMerger::new(None);
        let result = merger.merge_graphs(None);
        assert!(result.is_err());
        assert_eq!(result.unwrap_err(), "No graphs to merge");
    }

    #[test]
    fn test_expr_to_string() {
        let merger = ResourceGraphMerger::new(None);

        assert_eq!(merger.expr_to_string(&json!("hello")), "hello");
        assert_eq!(merger.expr_to_string(&json!(42)), "42");
        assert_eq!(merger.expr_to_string(&json!(true)), "true");
        assert_eq!(merger.expr_to_string(&Value::Null), "null");
        assert_eq!(
            merger.expr_to_string(&json!({"id": "opcode"})),
            "opcode"
        );
        assert_eq!(
            merger.expr_to_string(&json!({"name": "funct3"})),
            "funct3"
        );
        assert_eq!(
            merger.expr_to_string(&json!({"value": 7})),
            "7"
        );
    }

    #[test]
    fn test_split_arch_state_nodes_basic() {
        let mut graph = ResourceGraph::new();

        // Create an architectural state node
        let mut data = HashMap::new();
        data.insert("type".into(), json!("isa_state"));
        data.insert("name".into(), json!("x1"));
        data.insert("display_name".into(), json!("x1"));
        let arch_node = Node::new(
            Some("x1".into()),
            Some(data),
            true,  // is_arch_state
            false, // used_as_index
            None,  // indexed_by
            false, // is_uarch_state
            None,  // uarch_time
            None,  // pipe_time
            true,  // from_isa_spec
            false, // already_split
            0,     // latency
            false, // variable_latency
            true,  // is_shared
            None,  // pipe_id
            None,  // dual_issue_time
        );
        graph.add_node(arch_node);

        // Create a source node
        graph.add_node(Node::with_defaults(Some("src".into())));

        // Create a target node
        graph.add_node(Node::with_defaults(Some("tgt".into())));

        // Add assignment edge (incoming -> _wr)
        let mut assign_data = HashMap::new();
        assign_data.insert("type".into(), json!("assignment"));
        graph.add_edge(Edge::new(
            "src".into(),
            "x1".into(),
            None,
            Some(assign_data),
        ));

        // Add operand edge (outgoing -> _rd)
        let mut op_data = HashMap::new();
        op_data.insert("type".into(), json!("operand"));
        graph.add_edge(Edge::new(
            "x1".into(),
            "tgt".into(),
            None,
            Some(op_data),
        ));

        split_arch_state_nodes(&mut graph);

        // Original node should be gone
        assert!(graph.get_node("x1").is_none());

        // Read and write nodes should exist
        assert!(graph.get_node("x1_rd").is_some());
        assert!(graph.get_node("x1_wr").is_some());

        let rd = graph.get_node("x1_rd").unwrap();
        assert!(rd.is_arch_state);
        assert!(rd.already_split);

        let wr = graph.get_node("x1_wr").unwrap();
        assert!(wr.is_arch_state);
        assert!(wr.already_split);
    }

    #[test]
    fn test_split_arch_state_nodes_skips_already_split() {
        let mut graph = ResourceGraph::new();

        let mut data = HashMap::new();
        data.insert("type".into(), json!("isa_state"));
        let node = Node::new(
            Some("x1_rd".into()),
            Some(data),
            true, false, None, false, None, None, true, false, 0, false, true, None, None,
        );
        graph.add_node(node);

        split_arch_state_nodes(&mut graph);

        // Should still be there, not re-split
        assert!(graph.get_node("x1_rd").is_some());
        assert!(graph.get_node("x1_rd_rd").is_none());
    }

    #[test]
    fn test_deep_copy_graph() {
        let mut g = ResourceGraph::new();
        g.add_node(Node::with_defaults(Some("a".into())));
        g.add_node(Node::with_defaults(Some("b".into())));
        g.add_edge(Edge::new("a".into(), "b".into(), None, None));

        let g2 = deep_copy_graph(&g);
        assert_eq!(g2.get_node_count(), 2);
        assert_eq!(g2.get_edge_count(), 1);
    }

    #[test]
    fn test_extract_decode_info_empty() {
        let merger = ResourceGraphMerger::new(None);
        let graph = ResourceGraph::new();
        let info = merger.extract_decode_info("add", &graph);
        assert_eq!(info.instruction_name, "add");
        assert!(info.assume_conditions.is_empty());
        assert!(info.decode_signal_node.is_none());
    }

    #[test]
    fn test_extract_decode_info_with_conditions() {
        let merger = ResourceGraphMerger::new(None);
        let mut graph = ResourceGraph::new();
        graph.assume_expressions.push(json!({
            "operator": "==",
            "left": {"id": "opcode"},
            "right": {"value": 51}
        }));
        graph.assume_expressions.push(json!({
            "operator": "==",
            "left": "funct3",
            "right": "0"
        }));
        // Non-== operators should be skipped
        graph.assume_expressions.push(json!({
            "operator": "!=",
            "left": "other",
            "right": "1"
        }));

        let info = merger.extract_decode_info("add", &graph);
        assert_eq!(info.assume_conditions.len(), 2);
        assert_eq!(info.assume_conditions[0].0, "opcode");
        assert_eq!(info.assume_conditions[0].1, "==");
        assert_eq!(info.assume_conditions[0].2, "51");
        assert_eq!(info.assume_conditions[1].0, "funct3");
        assert_eq!(info.assume_conditions[1].2, "0");
    }

    #[test]
    fn test_compute_node_structure_key_literal() {
        let merger = ResourceGraphMerger::new(None);
        let graph = ResourceGraph::new();

        let mut data = HashMap::new();
        data.insert("type".into(), json!("literal"));
        data.insert("value".into(), json!(42));
        let node = Node::new(
            Some("lit".into()),
            Some(data),
            false, false, None, false, None, None, false, false, 0, false, false, None, None,
        );

        let key = merger.compute_node_structure_key(&node, &graph);
        assert!(key.starts_with("literal:value="));
        assert!(key.contains("42"));
    }

    #[test]
    fn test_compute_node_structure_key_unknown() {
        let merger = ResourceGraphMerger::new(None);
        let graph = ResourceGraph::new();

        let mut data = HashMap::new();
        data.insert("type".into(), json!("custom_widget"));
        data.insert("name".into(), json!("foo"));
        let node = Node::new(
            Some("w".into()),
            Some(data),
            false, false, None, false, None, None, false, false, 0, false, false, None, None,
        );

        let key = merger.compute_node_structure_key(&node, &graph);
        assert_eq!(key, "custom_widget:foo");
    }

    #[test]
    fn test_classify_with_groups_single_instruction() {
        let mut merger = ResourceGraphMerger::new(None);

        // Build a tiny graph for one instruction
        let mut g = ResourceGraph::new();
        let mut d1 = HashMap::new();
        d1.insert("type".into(), json!("literal"));
        d1.insert("value".into(), json!(1));
        let n1 = Node::new(
            Some("lit1".into()),
            Some(d1),
            false, false, None, false, None, None, false, false, 0, false, false, None, None,
        );
        g.add_node(n1);

        merger.graphs.insert("add".into(), g);
        merger.instruction_order.push("add".into());

        let tracker = merger.classify_with_groups();
        assert!(tracker.classifications.contains_key("lit1"));
        let c = tracker.classifications.get("lit1").unwrap();
        // Single instruction, node present in all (1/1) -> FullyShared
        assert_eq!(c.tier, SharingType::FullyShared);
    }

    #[test]
    fn test_classify_with_groups_fully_shared() {
        let mut merger = ResourceGraphMerger::new(None);

        // Two instructions, same node with same structure
        let mut g1 = ResourceGraph::new();
        let mut d1 = HashMap::new();
        d1.insert("type".into(), json!("literal"));
        d1.insert("value".into(), json!(1));
        g1.add_node(Node::new(
            Some("lit1".into()),
            Some(d1),
            false, false, None, false, None, None, false, false, 0, false, false, None, None,
        ));

        let mut g2 = ResourceGraph::new();
        let mut d2 = HashMap::new();
        d2.insert("type".into(), json!("literal"));
        d2.insert("value".into(), json!(1));
        g2.add_node(Node::new(
            Some("lit1".into()),
            Some(d2),
            false, false, None, false, None, None, false, false, 0, false, false, None, None,
        ));

        merger.graphs.insert("add".into(), g1);
        merger.graphs.insert("sub".into(), g2);
        merger.instruction_order.push("add".into());
        merger.instruction_order.push("sub".into());

        let tracker = merger.classify_with_groups();
        let c = tracker.classifications.get("lit1").unwrap();
        assert_eq!(c.tier, SharingType::FullyShared);
        assert!(!c.is_collision());
    }

    #[test]
    fn test_create_decode_logic() {
        let mut merged = ResourceGraph::new();

        let mut decode_info = HashMap::new();
        decode_info.insert(
            "add".into(),
            InstructionDecodeInfo {
                instruction_name: "add".into(),
                assume_conditions: vec![
                    ("opcode".into(), "==".into(), "51".into()),
                    ("funct3".into(), "==".into(), "0".into()),
                ],
                decode_signal_node: None,
            },
        );

        // Use a temporary merger with decode_info set
        let m = ResourceGraphMerger {
            graphs: HashMap::new(),
            decode_info,
            instruction_order: vec!["add".into()],
            defines: HashMap::new(),
            pc_name: None,
            partially_shared_nodes: HashMap::new(),
        };
        m.create_decode_logic(&mut merged);

        // Should have: add_enable, add_decode_cmp_0, add_decode_cmp_1, add_decode_and_1
        assert!(merged.get_node("add_enable").is_some());
        assert!(merged.get_node("add_decode_cmp_0").is_some());
        assert!(merged.get_node("add_decode_cmp_1").is_some());
        assert!(merged.get_node("add_decode_and_1").is_some());

        // Verify enable node data
        let en = merged.get_node("add_enable").unwrap();
        assert_eq!(
            en.data.get("type").and_then(|v| v.as_str()),
            Some("instruction_enable")
        );
        assert_eq!(
            en.data.get("instruction").and_then(|v| v.as_str()),
            Some("add")
        );
    }

    #[test]
    fn test_gate_instruction_operations_creates_mux() {
        // Simulate two instructions (add, sub) that both assign to a shared target
        let mut merged = ResourceGraph::new();

        // Shared target node
        let mut target_data = HashMap::new();
        target_data.insert("type".into(), json!("var"));
        target_data.insert("name".into(), json!("rf[rd]_wr"));
        let target = Node::new(
            Some("rf[rd]_wr".into()),
            Some(target_data),
            true, false, None, false, None, None, true, true, 0, false, true, None, None,
        );
        merged.add_node(target);

        // Instruction-specific source nodes
        let mut add_data = HashMap::new();
        add_data.insert("type".into(), json!("operation"));
        add_data.insert("instruction".into(), json!("add"));
        let add_res = Node::new(
            Some("add_res".into()),
            Some(add_data),
            false, false, None, false, None, None, false, false, 0, false, false, None, None,
        );
        merged.add_node(add_res);

        let mut sub_data = HashMap::new();
        sub_data.insert("type".into(), json!("operation"));
        sub_data.insert("instruction".into(), json!("sub"));
        let sub_res = Node::new(
            Some("sub_res".into()),
            Some(sub_data),
            false, false, None, false, None, None, false, false, 0, false, false, None, None,
        );
        merged.add_node(sub_res);

        // Enable nodes
        let mut add_en_data = HashMap::new();
        add_en_data.insert("type".into(), json!("instruction_enable"));
        let add_en = Node::new(
            Some("add_enable".into()),
            Some(add_en_data),
            false, false, None, false, None, None, false, false, 0, false, true, None, None,
        );
        merged.add_node(add_en);

        let mut sub_en_data = HashMap::new();
        sub_en_data.insert("type".into(), json!("instruction_enable"));
        let sub_en = Node::new(
            Some("sub_enable".into()),
            Some(sub_en_data),
            false, false, None, false, None, None, false, false, 0, false, true, None, None,
        );
        merged.add_node(sub_en);

        // Assignment edges
        let mut assign1 = HashMap::new();
        assign1.insert("type".into(), json!("assignment"));
        merged.add_edge(Edge::new(
            "add_res".into(),
            "rf[rd]_wr".into(),
            None,
            Some(assign1),
        ));

        let mut assign2 = HashMap::new();
        assign2.insert("type".into(), json!("assignment"));
        merged.add_edge(Edge::new(
            "sub_res".into(),
            "rf[rd]_wr".into(),
            None,
            Some(assign2),
        ));

        // Set up instruction_specific_nodes
        let mut instruction_specific_nodes: HashMap<String, HashSet<String>> = HashMap::new();
        instruction_specific_nodes.insert(
            "add".into(),
            HashSet::from(["add_res".into()]),
        );
        instruction_specific_nodes.insert(
            "sub".into(),
            HashSet::from(["sub_res".into()]),
        );

        // Create a merger with dummy graphs
        let mut g1 = ResourceGraph::new();
        g1.add_node(Node::with_defaults(Some("add_res".into())));
        let mut g2 = ResourceGraph::new();
        g2.add_node(Node::with_defaults(Some("sub_res".into())));

        let m = ResourceGraphMerger {
            graphs: HashMap::from([
                ("add".into(), g1),
                ("sub".into(), g2),
            ]),
            decode_info: HashMap::new(),
            instruction_order: vec!["add".into(), "sub".into()],
            defines: HashMap::new(),
            pc_name: None,
            partially_shared_nodes: HashMap::new(),
        };

        let arch_state_wr_needing_mux = HashSet::new();

        m.gate_instruction_operations(
            &mut merged,
            &instruction_specific_nodes,
            &arch_state_wr_needing_mux,
        );

        // Verify mux was created
        assert!(
            merged.get_node("rf[rd]_wr_mux").is_some(),
            "Expected rf[rd]_wr_mux node to be created"
        );

        let mux = merged.get_node("rf[rd]_wr_mux").unwrap();
        assert_eq!(
            mux.data.get("type").and_then(|v| v.as_str()),
            Some("multiplexer")
        );
        assert_eq!(
            mux.data.get("operation").and_then(|v| v.as_str()),
            Some("priority_select")
        );

        // Verify mux has inputs from both sources
        let mux_input_edges: Vec<&Edge> = merged
            .edges
            .values()
            .filter(|e| {
                e.target == "rf[rd]_wr_mux"
                    && e.data.get("type").and_then(|v| v.as_str()) == Some("mux_input")
            })
            .collect();
        assert_eq!(
            mux_input_edges.len(),
            2,
            "Expected 2 mux inputs, got {}",
            mux_input_edges.len()
        );

        // Verify mux has select signals
        let mux_select_edges: Vec<&Edge> = merged
            .edges
            .values()
            .filter(|e| {
                e.target == "rf[rd]_wr_mux"
                    && e.data.get("type").and_then(|v| v.as_str()) == Some("mux_select")
            })
            .collect();
        assert_eq!(
            mux_select_edges.len(),
            2,
            "Expected 2 mux selects, got {}",
            mux_select_edges.len()
        );

        // Verify mux output goes to target
        let mux_output_edges: Vec<&Edge> = merged
            .edges
            .values()
            .filter(|e| {
                e.source == "rf[rd]_wr_mux"
                    && e.target == "rf[rd]_wr"
                    && e.data.get("type").and_then(|v| v.as_str()) == Some("assignment")
            })
            .collect();
        assert_eq!(
            mux_output_edges.len(),
            1,
            "Expected 1 mux output edge to target"
        );

        // Verify direct assignment edges were removed
        let direct_assign_edges: Vec<&Edge> = merged
            .edges
            .values()
            .filter(|e| {
                (e.source == "add_res" || e.source == "sub_res")
                    && e.target == "rf[rd]_wr"
                    && e.data.get("type").and_then(|v| v.as_str()) == Some("assignment")
            })
            .collect();
        assert_eq!(
            direct_assign_edges.len(),
            0,
            "Direct assignment edges should have been removed"
        );
    }

    #[test]
    fn test_arch_state_mux_for_collision_nodes() {
        // Simulate collision nodes: add_pc_wr and sub_pc_wr both writing to pc_wr
        let mut merged = ResourceGraph::new();

        // Target: pc_wr
        let mut pc_wr_data = HashMap::new();
        pc_wr_data.insert("type".into(), json!("var"));
        pc_wr_data.insert("name".into(), json!("pc_wr"));
        let pc_wr = Node::new(
            Some("pc_wr".into()),
            Some(pc_wr_data),
            true, false, None, false, None, None, true, true, 0, false, true, None, None,
        );
        merged.add_node(pc_wr);

        // pc_rd (default source)
        let mut pc_rd_data = HashMap::new();
        pc_rd_data.insert("type".into(), json!("var"));
        let pc_rd = Node::new(
            Some("pc_rd".into()),
            Some(pc_rd_data),
            true, false, None, false, None, None, true, true, 0, false, true, None, None,
        );
        merged.add_node(pc_rd);

        // Collision nodes
        let mut add_pc_wr_data = HashMap::new();
        add_pc_wr_data.insert("type".into(), json!("var"));
        add_pc_wr_data.insert("original_id".into(), json!("pc_wr"));
        let add_pc_wr = Node::new(
            Some("add_pc_wr".into()),
            Some(add_pc_wr_data),
            true, false, None, false, None, None, true, true, 0, false, false, None, None,
        );
        merged.add_node(add_pc_wr);

        let mut sub_pc_wr_data = HashMap::new();
        sub_pc_wr_data.insert("type".into(), json!("var"));
        sub_pc_wr_data.insert("original_id".into(), json!("pc_wr"));
        let sub_pc_wr = Node::new(
            Some("sub_pc_wr".into()),
            Some(sub_pc_wr_data),
            true, false, None, false, None, None, true, true, 0, false, false, None, None,
        );
        merged.add_node(sub_pc_wr);

        // Source nodes that assign to collision nodes
        let mut add_src_data = HashMap::new();
        add_src_data.insert("type".into(), json!("operation"));
        let add_src = Node::new(
            Some("add_next_pc".into()),
            Some(add_src_data),
            false, false, None, false, None, None, false, false, 0, false, false, None, None,
        );
        merged.add_node(add_src);

        let mut sub_src_data = HashMap::new();
        sub_src_data.insert("type".into(), json!("operation"));
        let sub_src = Node::new(
            Some("sub_next_pc".into()),
            Some(sub_src_data),
            false, false, None, false, None, None, false, false, 0, false, false, None, None,
        );
        merged.add_node(sub_src);

        // Enables
        let mut add_en = HashMap::new();
        add_en.insert("type".into(), json!("instruction_enable"));
        merged.add_node(Node::new(
            Some("add_enable".into()),
            Some(add_en),
            false, false, None, false, None, None, false, false, 0, false, true, None, None,
        ));
        let mut sub_en = HashMap::new();
        sub_en.insert("type".into(), json!("instruction_enable"));
        merged.add_node(Node::new(
            Some("sub_enable".into()),
            Some(sub_en),
            false, false, None, false, None, None, false, false, 0, false, true, None, None,
        ));

        // Assignment edges: source -> collision node
        let mut a1 = HashMap::new();
        a1.insert("type".into(), json!("assignment"));
        merged.add_edge(Edge::new("add_next_pc".into(), "add_pc_wr".into(), None, Some(a1)));

        let mut a2 = HashMap::new();
        a2.insert("type".into(), json!("assignment"));
        merged.add_edge(Edge::new("sub_next_pc".into(), "sub_pc_wr".into(), None, Some(a2)));

        // Set up merger
        let m = ResourceGraphMerger {
            graphs: HashMap::from([
                ("add".into(), ResourceGraph::new()),
                ("sub".into(), ResourceGraph::new()),
            ]),
            decode_info: HashMap::new(),
            instruction_order: vec!["add".into(), "sub".into()],
            defines: HashMap::new(),
            pc_name: Some("pc".into()),
            partially_shared_nodes: HashMap::new(),
        };

        let instruction_specific_nodes: HashMap<String, HashSet<String>> = HashMap::from([
            ("add".into(), HashSet::from(["add_next_pc".into()])),
            ("sub".into(), HashSet::from(["sub_next_pc".into()])),
        ]);

        m.create_arch_state_mux(&mut merged, "pc_wr", &instruction_specific_nodes);

        // Verify mux was created
        assert!(
            merged.get_node("pc_wr_mux").is_some(),
            "Expected pc_wr_mux node to be created"
        );

        let mux = merged.get_node("pc_wr_mux").unwrap();
        assert_eq!(
            mux.data.get("type").and_then(|v| v.as_str()),
            Some("multiplexer")
        );
        assert_eq!(
            mux.data.get("gated_write_mux").and_then(|v| v.as_bool()),
            Some(true)
        );

        // Verify mux has inputs
        let mux_inputs: Vec<&Edge> = merged
            .edges
            .values()
            .filter(|e| {
                e.target == "pc_wr_mux"
                    && e.data.get("type").and_then(|v| v.as_str()) == Some("mux_input")
            })
            .collect();
        assert_eq!(mux_inputs.len(), 2);

        // Verify default input (pc_rd)
        let default_inputs: Vec<&Edge> = merged
            .edges
            .values()
            .filter(|e| {
                e.target == "pc_wr_mux"
                    && e.data.get("type").and_then(|v| v.as_str()) == Some("mux_default_input")
            })
            .collect();
        assert_eq!(default_inputs.len(), 1);
        assert_eq!(default_inputs[0].source, "pc_rd");

        // Verify mux output goes to pc_wr
        let mux_outputs: Vec<&Edge> = merged
            .edges
            .values()
            .filter(|e| {
                e.source == "pc_wr_mux" && e.target == "pc_wr"
            })
            .collect();
        assert_eq!(mux_outputs.len(), 1);

        // Verify collision nodes were removed
        assert!(merged.get_node("add_pc_wr").is_none(), "add_pc_wr should be removed");
        assert!(merged.get_node("sub_pc_wr").is_none(), "sub_pc_wr should be removed");
    }

    #[test]
    fn test_build_instruction_specific_nodes() {
        let mut merger = ResourceGraphMerger::new(None);

        // Two instructions with collision on res but shared on lit1
        let mut g1 = ResourceGraph::new();
        let mut d1a = HashMap::new();
        d1a.insert("type".into(), json!("literal"));
        d1a.insert("value".into(), json!(1));
        g1.add_node(Node::new(
            Some("lit1".into()), Some(d1a),
            false, false, None, false, None, None, false, false, 0, false, false, None, None,
        ));
        let mut d1b = HashMap::new();
        d1b.insert("type".into(), json!("operation"));
        d1b.insert("display_name".into(), json!("rs1+rs2"));
        g1.add_node(Node::new(
            Some("res".into()), Some(d1b),
            false, false, None, false, None, None, false, false, 0, false, false, None, None,
        ));

        let mut g2 = ResourceGraph::new();
        let mut d2a = HashMap::new();
        d2a.insert("type".into(), json!("literal"));
        d2a.insert("value".into(), json!(1));
        g2.add_node(Node::new(
            Some("lit1".into()), Some(d2a),
            false, false, None, false, None, None, false, false, 0, false, false, None, None,
        ));
        let mut d2b = HashMap::new();
        d2b.insert("type".into(), json!("operation"));
        d2b.insert("display_name".into(), json!("rs1-rs2"));
        g2.add_node(Node::new(
            Some("res".into()), Some(d2b),
            false, false, None, false, None, None, false, false, 0, false, false, None, None,
        ));

        merger.graphs.insert("add".into(), g1);
        merger.graphs.insert("sub".into(), g2);
        merger.instruction_order = vec!["add".into(), "sub".into()];

        let tracker = merger.classify_with_groups();
        let isn = merger.build_instruction_specific_nodes(&tracker);

        // "res" should be collision -> both instructions get it
        assert!(isn["add"].contains("res"), "add should have res as instruction-specific");
        assert!(isn["sub"].contains("res"), "sub should have res as instruction-specific");

        // "lit1" should be shared -> not in instruction-specific
        assert!(!isn["add"].contains("lit1"), "lit1 should not be instruction-specific");
        assert!(!isn["sub"].contains("lit1"), "lit1 should not be instruction-specific");
    }
}

#[cfg(test)]
mod test_write_enable {
    use super::*;

    #[test]
    fn test_write_enable_edge_preserved_in_merge() {
        let mut merger = ResourceGraphMerger::new(None);

        merger.add_instruction("add", "../riscv32/add.isa").expect("add.isa");
        merger.add_instruction("jal", "../riscv32/jal.isa").expect("jal.isa");

        for (instr, graph) in &merger.graphs {
            for edge in graph.edges.values() {
                let etype: &str = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                if etype == "write_enable" {
                    log::debug!("[{}] write_enable: {} -> {}", instr, edge.source, edge.target);
                }
            }
        }

        let merged = merger.merge_graphs(Some("pc")).expect("merge");

        let mut found_we = false;
        for edge in merged.edges.values() {
            let etype: &str = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
            if etype == "write_enable" {
                log::debug!("[merged] write_enable: {} -> {}", edge.source, edge.target);
                found_we = true;
            }
        }
        assert!(found_we, "write_enable edge should exist in merged graph");

        if let Some(node) = merged.get_node("rf[rd]_wr") {
            let ntype: &str = node.data.get("type").and_then(|v| v.as_str()).unwrap_or("?");
            log::debug!("[merged] rf[rd]_wr node type: {}", ntype);
        } else {
            log::debug!("[merged] rf[rd]_wr node NOT FOUND");
        }
    }

    #[test]
    fn test_sign_ext_imm_collision_between_addi_and_sb() {
        let mut merger = ResourceGraphMerger::new(None);
        // Add all 37 instructions
        let instrs = vec![
            "add", "addi", "sub", "lui", "auipc", "and", "andi", "or", "ori",
            "xor", "xori", "sll", "slli", "srl", "srli", "sra", "srai",
            "slt", "slti", "sltu", "sltiu",
            "beq", "bne", "blt", "bltu", "bge", "bgeu",
            "jal", "jalr", "lw", "lh", "lhu", "lb", "lbu", "sw", "sh", "sb",
        ];
        for instr in &instrs {
            merger.add_instruction(instr, &format!("../riscv32/{}.isa", instr)).expect(instr);
        }

        // Check the classifier
        let tracker = merger.classify_with_groups();

        // Check imm classification
        if let Some(c) = tracker.get_classification("imm") {
            log::debug!("imm: collision={} groups={}", c.is_collision(), c.groups.len());
            for g in &c.groups {
                let mid = c.merged_ids.get(&g.group_id).cloned().unwrap_or_default();
                log::debug!("  group {}: instrs={:?} merged_id={}", g.group_id, g.instructions, mid);
            }
        }

        // Check sign_ext_imm classification
        if let Some(c) = tracker.get_classification("sign_ext_imm") {
            log::debug!("sign_ext_imm: collision={} groups={}", c.is_collision(), c.groups.len());
            for g in &c.groups {
                let mid = c.merged_ids.get(&g.group_id).cloned().unwrap_or_default();
                log::debug!("  group {}: instrs={:?} merged_id={}", g.group_id, g.instructions, mid);
            }
        }

        // Check concatenation node
        // Node ID for {{20{imm[11:11]}}, imm} — check what it looks like
        for (nid, c) in &tracker.classifications {
            if nid.contains("imm") && (c.is_collision() || c.groups.len() > 1) {
                log::debug!("collision node: {} groups={}", nid, c.groups.len());
                for g in &c.groups {
                    let mid = c.merged_ids.get(&g.group_id).cloned().unwrap_or_default();
                    log::debug!("  group {}: instrs={:?} merged_id={}", g.group_id, g.instructions, mid);
                }
            }
        }

        let merged = merger.merge_graphs(Some("pc")).expect("merge");

        // Check the concatenation node in merged graph
        for (nid, node) in &merged.nodes {
            let ntype: &str = node.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
            if ntype == "concatenation" && nid.contains("imm") {
                log::debug!("merged concat node: {}", nid);
                for eid in &node.incoming_edges {
                    if let Some(edge) = merged.get_edge(eid) {
                        let pos = edge.data.get("position").and_then(|v| v.as_i64()).unwrap_or(-1);
                        log::debug!("  incoming: {} (pos={}, type={})", edge.source, pos,
                            edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("?"));
                    }
                }
            }
        }
    }

    #[test]
    fn test_guarded_enable_created_for_rf_writes() {
        // Verify that merging instructions with guarded RF writes produces
        // rf_rd_ne_0_enables, rf_rd_ne_0_guarded_enable, and combined_write_enable
        let mut merger = ResourceGraphMerger::new(None);
        merger
            .add_instruction("add", "../riscv32/add.isa")
            .expect("add.isa");
        merger
            .add_instruction("sub", "../riscv32/sub.isa")
            .expect("sub.isa");

        let merged = merger.merge_graphs(Some("pc")).expect("merge");

        // Check rf_rd_ne_0_guarded_enable exists
        assert!(
            merged.nodes.contains_key("rf_rd_ne_0_guarded_enable"),
            "Expected rf_rd_ne_0_guarded_enable node"
        );

        // Check it's a logical_and
        let ge = merged.get_node("rf_rd_ne_0_guarded_enable").unwrap();
        assert_eq!(
            ge.data.get("type").and_then(|v| v.as_str()),
            Some("logical_and")
        );

        // Check rf_rd_ne_0_enables exists (OR of instruction enables)
        assert!(
            merged.nodes.contains_key("rf_rd_ne_0_enables"),
            "Expected rf_rd_ne_0_enables node"
        );

        // Check rf_shared_wr has combined_write_enable
        if let Some(port) = merged.get_node("rf_shared_wr") {
            assert_eq!(
                port.data.get("combined_write_enable").and_then(|v| v.as_str()),
                Some("rf_rd_ne_0_guarded_enable"),
                "Expected combined_write_enable on rf_shared_wr"
            );
        } else {
            panic!("Expected rf_shared_wr node");
        }

        // Check write_enable edge from guarded_enable to rf_shared_wr
        let mut found_we_edge = false;
        for edge in merged.edges.values() {
            if edge.source == "rf_rd_ne_0_guarded_enable"
                && edge.target == "rf_shared_wr"
                && edge.data.get("type").and_then(|v| v.as_str()) == Some("write_enable")
            {
                found_we_edge = true;
            }
        }
        assert!(found_we_edge, "Expected write_enable edge from rf_rd_ne_0_guarded_enable to rf_shared_wr");
    }
}
