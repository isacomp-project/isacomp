//! Pipeline optimization: insert pipeline registers and validity signals.
//!
//! Ports the core pipeline transform from Python's pipelining_optimization.py.
//! Key operations:
//! - `add_multiple_pipeline_stages`: Insert pipeline registers at specified edges
//! - `_insert_pipeline_cuts_at_edges`: Core edge-cutting logic
//! - `_add_validity_signals`: Create validity chain for bubble injection

use crate::resource_graph::{Edge, Node, ResourceGraph};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

/// Sanitize an identifier for use in Verilog (remove brackets, operators, etc.).
pub fn sanitize_for_verilog(identifier: &str) -> String {
    let mut s = identifier.to_string();
    s = s.replace('[', "_").replace(']', "_").replace(':', "_");
    s = s.replace('(', "_").replace(')', "_").replace(' ', "_");
    s = s.replace('\'', "_").replace('{', "_").replace('}', "_");
    s = s.replace(',', "_").replace('?', "_");
    s = s.replace('+', "add").replace('-', "sub");
    s = s.replace('*', "mul").replace('/', "div");
    s = s.replace('&', "and").replace('|', "or").replace('^', "xor");
    s = s.replace(">>>", "srlgt").replace("<<", "sll").replace(">>", "srl");
    s = s.replace('<', "lt").replace('>', "gt").replace('=', "eq");
    s = s.replace('!', "not").replace('~', "inv");
    // Remove double underscores
    while s.contains("__") {
        s = s.replace("__", "_");
    }
    s = s.trim_matches('_').to_string();
    s
}

/// Specification for a pipeline cut (a set of edges to cut at a stage boundary).
#[derive(Debug, Clone)]
pub struct CutSpec {
    pub edges: Vec<String>,
    pub after_stage: String,
    pub stage_index: Option<i64>,
}

/// Pipeline transform: inserts pipeline registers and validity signals.
pub struct PipelineTransform<'a> {
    pub graph: &'a mut ResourceGraph,
    pub pipeline_prefix: String,
    pub stage_counter: usize,
    /// Explicit stage order for validity signals
    pub explicit_stage_order: Option<Vec<String>>,
    /// Explicit stage indices (stage_name -> pipe_time)
    pub explicit_stage_indices: Option<HashMap<String, i64>>,
    /// Cached original edge info for multi-stage cuts
    original_edge_info: HashMap<String, OriginalEdgeInfo>,
}

#[derive(Debug, Clone)]
struct OriginalEdgeInfo {
    source_id: String,
    target_id: String,
    edge_type: String,
    input_index: Option<Value>,
    select_index: Option<Value>,
    position: Option<Value>,
}

impl<'a> PipelineTransform<'a> {
    pub fn new(graph: &'a mut ResourceGraph) -> Self {
        Self {
            graph,
            pipeline_prefix: "PIPE".to_string(),
            stage_counter: 0,
            explicit_stage_order: None,
            explicit_stage_indices: None,
            original_edge_info: HashMap::new(),
        }
    }

    /// Set explicit stage order for validity signal creation.
    pub fn set_stage_order(&mut self, stage_order: Vec<String>, stage_indices: Option<HashMap<String, i64>>) {
        self.explicit_stage_order = Some(stage_order);
        self.explicit_stage_indices = stage_indices;
    }

    /// Add multiple pipeline stages at once.
    pub fn add_multiple_pipeline_stages(&mut self, cut_specs: &[CutSpec]) -> bool {
        if cut_specs.is_empty() {
            log::warn!("No cut specifications provided");
            return false;
        }

        log::info!("\nAdding {} pipeline stages at once...", cut_specs.len());

        // Collect edge metadata BEFORE any cuts happen
        log::info!("\nCollecting edge metadata before cutting...");
        self.original_edge_info.clear();
        let edge_ids: Vec<String> = self.graph.edges.keys().cloned().collect();
        for edge_id in &edge_ids {
            if let Some(edge) = self.graph.edges.get(edge_id) {
                self.original_edge_info.insert(edge_id.clone(), OriginalEdgeInfo {
                    source_id: edge.source.clone(),
                    target_id: edge.target.clone(),
                    edge_type: edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                    input_index: edge.data.get("input_index").cloned(),
                    select_index: edge.data.get("select_index").cloned(),
                    position: edge.data.get("position").cloned(),
                });
            }
        }

        // Insert all stages
        log::info!("\nInserting {} pipeline stages...", cut_specs.len());

        for (i, cut_spec) in cut_specs.iter().enumerate() {
            let stage_name = &cut_spec.after_stage;
            log::info!("\n  Stage {}/{}: {}", i + 1, cut_specs.len(), stage_name);

            let success = self.insert_pipeline_cuts_at_edges(
                stage_name,
                cut_spec.stage_index,
                &cut_spec.edges,
            );

            if !success {
                log::info!("    Failed to insert stage {}", i + 1);
                return false;
            }

            self.stage_counter += 1;
            log::info!("    Successfully inserted stage {}", stage_name);
        }

        // Re-infer timing
        log::info!("\nRe-inferring timing for complete pipeline...");
        self.graph.infer_uarch_time(true);
        self.graph.infer_pipe_time(true);

        // Add validity signals
        log::info!("\nAdding validity signals for pipeline stages...");
        self.add_validity_signals();

        // Re-infer pipe_time after validity signals
        log::info!("\nRe-inferring pipe_time after validity signal creation...");
        self.graph.infer_pipe_time(true);

        log::info!("\nSuccessfully added all {} pipeline stages", cut_specs.len());
        true
    }

    /// Insert pipeline cuts at specific edges.
    fn insert_pipeline_cuts_at_edges(
        &mut self,
        stage_name: &str,
        stage_index: Option<i64>,
        edge_ids: &[String],
    ) -> bool {
        if edge_ids.is_empty() {
            log::info!("    Warning: No edges specified for cutting");
            return false;
        }

        log::info!("    Inserting pipeline cuts at {} edges", edge_ids.len());

        // First pass: collect edge info before any modifications
        struct EdgeToCut {
            edge_id: Option<String>,
            original_source_id: String,
            original_target_id: String,
            original_type: String,
            input_index: Option<Value>,
            select_index: Option<Value>,
            position: Option<Value>,
        }

        let mut edges_to_cut: Vec<EdgeToCut> = Vec::new();

        for edge_id in edge_ids {
            if let Some(edge) = self.graph.edges.get(edge_id) {
                edges_to_cut.push(EdgeToCut {
                    edge_id: Some(edge_id.clone()),
                    original_source_id: edge.source.clone(),
                    original_target_id: edge.target.clone(),
                    original_type: edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                    input_index: edge.data.get("input_index").cloned(),
                    select_index: edge.data.get("select_index").cloned(),
                    position: edge.data.get("position").cloned(),
                });
            } else if let Some(info) = self.original_edge_info.get(edge_id) {
                edges_to_cut.push(EdgeToCut {
                    edge_id: None,
                    original_source_id: info.source_id.clone(),
                    original_target_id: info.target_id.clone(),
                    original_type: info.edge_type.clone(),
                    input_index: info.input_index.clone(),
                    select_index: info.select_index.clone(),
                    position: info.position.clone(),
                });
                log::info!("    Using stored metadata for already-cut edge: {} -> {}", info.source_id, info.target_id);
            }
        }

        // Second pass: perform cuts
        let mut edges_modified = 0;

        for edge_info in &edges_to_cut {
            let original_source_id = &edge_info.original_source_id;
            let original_target_id = &edge_info.original_target_id;
            let original_type = &edge_info.original_type;

            // Find the current edge connecting the original endpoints
            let current_edge_id = self.find_current_edge(
                original_source_id,
                original_target_id,
                original_type,
                &edge_info.input_index,
            );

            let current_edge_id = match current_edge_id {
                Some(id) => id,
                None => {
                    log::info!("    Warning: Could not find edge to cut for {} -> {}", original_source_id, original_target_id);
                    continue;
                }
            };

            // Check if this is a pipeline infrastructure edge
            let (is_pipeline_component, is_from_pipeline_reg) = {
                let edge = self.graph.edges.get(&current_edge_id).unwrap();
                let is_pc = edge.data.get("pipeline_component").and_then(|v| v.as_bool()).unwrap_or(false);
                let is_fpr = edge.data.get("from_pipeline_reg").and_then(|v| v.as_bool()).unwrap_or(false);
                (is_pc, is_fpr)
            };

            if is_pipeline_component && !is_from_pipeline_reg {
                log::info!("    Skipping pipeline input edge");
                continue;
            }
            if is_pipeline_component && is_from_pipeline_reg {
                let (s, t) = {
                    let e = self.graph.edges.get(&current_edge_id).unwrap();
                    (e.source.clone(), e.target.clone())
                };
                log::info!("    Extending pipeline chain: {} -> {}", s, t);
            }

            // Get source/target and edge data before removing
            let (source_id, target_id, current_edge_data) = {
                let edge = self.graph.edges.get(&current_edge_id).unwrap();
                (edge.source.clone(), edge.target.clone(), edge.data.clone())
            };

            // Remove current edge
            self.graph.remove_edge(&current_edge_id);

            // Create pipeline register name
            let sanitized_source = sanitize_for_verilog(&source_id);
            let signal_reg_name = format!("PIPE_{}_{}_PIPE", stage_name, sanitized_source);

            // Infer width from source
            let reg_metadata = self.infer_register_metadata(&source_id);

            // Check if pipeline register already exists
            let skip_input_edge = if self.graph.nodes.contains_key(&signal_reg_name) {
                // Check if pipeline_input edge from this source already exists
                let existing = self.graph.nodes[&signal_reg_name].incoming_edges.iter().any(|eid| {
                    if let Some(e) = self.graph.edges.get(eid) {
                        e.source == source_id && e.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_input")
                    } else {
                        false
                    }
                });
                if existing {
                    log::info!("    Skipping duplicate pipeline register input: {} -> {}", source_id, signal_reg_name);
                }
                existing
            } else {
                // Create new pipeline register
                let mut data: HashMap<String, Value> = HashMap::new();
                data.insert("type".into(), json!("pipeline_register"));
                data.insert("name".into(), json!(&signal_reg_name));
                data.insert("display_name".into(), json!(format!("Pipeline register for {}", stage_name)));
                data.insert("pipeline_component".into(), json!(true));
                data.insert("pipeline_prefix".into(), json!(&self.pipeline_prefix));
                data.insert("stage_name".into(), json!(stage_name));
                for (k, v) in &reg_metadata {
                    data.insert(k.clone(), v.clone());
                }

                let reg_node = Node::new(
                    Some(signal_reg_name.clone()),
                    Some(data),
                    false, false, None,
                    true, // is_uarch_state
                    stage_index, // uarch_time
                    stage_index, // pipe_time
                    false, false, 0, false, true, None, None,
                );
                self.graph.add_node(reg_node);
                false
            };

            // Create input edge: source -> pipeline register
            if !skip_input_edge {
                let mut input_data: HashMap<String, Value> = HashMap::new();
                input_data.insert("type".into(), json!("pipeline_input"));
                let orig_type = current_edge_data.get("original_type")
                    .or_else(|| current_edge_data.get("type"))
                    .cloned()
                    .unwrap_or(json!(""));
                input_data.insert("original_type".into(), orig_type);
                input_data.insert("pipeline_component".into(), json!(true));

                let input_edge = Edge::new(source_id.clone(), signal_reg_name.clone(), None, Some(input_data));
                self.graph.add_edge(input_edge);
            }

            // Create output edge: pipeline register -> target
            let mut output_data: HashMap<String, Value> = HashMap::new();
            if let Some(t) = current_edge_data.get("type") {
                output_data.insert("type".into(), t.clone());
            }
            let orig_type = current_edge_data.get("original_type")
                .or_else(|| current_edge_data.get("type"))
                .cloned()
                .unwrap_or(json!(""));
            output_data.insert("original_type".into(), orig_type);
            output_data.insert("pipeline_component".into(), json!(true));
            output_data.insert("from_pipeline_reg".into(), json!(true));

            // Copy mux-related indices
            if let Some(v) = current_edge_data.get("input_index") {
                output_data.insert("input_index".into(), v.clone());
            }
            if let Some(v) = current_edge_data.get("select_index") {
                output_data.insert("select_index".into(), v.clone());
            }
            if let Some(v) = current_edge_data.get("source_instruction") {
                output_data.insert("source_instruction".into(), v.clone());
            }
            if let Some(v) = current_edge_data.get("position") {
                output_data.insert("position".into(), v.clone());
            }

            let output_edge = Edge::new(signal_reg_name.clone(), target_id.clone(), None, Some(output_data));
            self.graph.add_edge(output_edge);

            // Store edge info for subsequent stages
            if let Some(orig_edge_id) = &edge_info.edge_id {
                self.original_edge_info.insert(orig_edge_id.clone(), OriginalEdgeInfo {
                    source_id: original_source_id.clone(),
                    target_id: original_target_id.clone(),
                    edge_type: original_type.clone(),
                    input_index: edge_info.input_index.clone(),
                    select_index: edge_info.select_index.clone(),
                    position: edge_info.position.clone(),
                });
            }

            edges_modified += 1;
        }

        log::info!("    Modified {} edges for pipeline insertion", edges_modified);
        edges_modified > 0
    }

    /// Find the current edge connecting original endpoints (possibly through pipeline registers).
    fn find_current_edge(
        &self,
        original_source_id: &str,
        original_target_id: &str,
        original_type: &str,
        original_input_index: &Option<Value>,
    ) -> Option<String> {
        let target_node = self.graph.nodes.get(original_target_id)?;

        for incoming_eid in &target_node.incoming_edges {
            let edge = self.graph.edges.get(incoming_eid)?;
            let edge_type = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
            let from_pipeline = edge.data.get("from_pipeline_reg").and_then(|v| v.as_bool()).unwrap_or(false);

            // Match edges with the original type
            let type_matches = edge_type == original_type ||
                (from_pipeline && edge.data.get("original_type").and_then(|v| v.as_str()) == Some(original_type));

            if !type_matches {
                continue;
            }

            // For mux inputs, check input_index
            if let Some(orig_idx) = original_input_index {
                if let Some(incoming_idx) = edge.data.get("input_index") {
                    if incoming_idx != orig_idx {
                        continue;
                    }
                }
            }

            // Check if source traces back to original
            if self.traces_back_to(&edge.source, original_source_id, 10) {
                return Some(incoming_eid.clone());
            }
        }

        None
    }

    /// Check if a node traces back to a target (possibly through pipeline registers).
    fn traces_back_to(&self, node_id: &str, target_id: &str, max_depth: usize) -> bool {
        if node_id == target_id {
            return true;
        }
        if max_depth == 0 {
            return false;
        }

        if let Some(node) = self.graph.nodes.get(node_id) {
            let is_pipe_reg = node.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_register");
            if is_pipe_reg {
                for eid in &node.incoming_edges {
                    if let Some(edge) = self.graph.edges.get(eid) {
                        if edge.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_input") {
                            if self.traces_back_to(&edge.source, target_id, max_depth - 1) {
                                return true;
                            }
                        }
                    }
                }
            }
        }

        false
    }

    /// Infer metadata (width) for a pipeline register from its source node.
    fn infer_register_metadata(&self, source_id: &str) -> HashMap<String, Value> {
        let mut metadata = HashMap::new();

        let node = match self.graph.nodes.get(source_id) {
            Some(n) => n,
            None => return metadata,
        };

        // Check explicit widths
        if let Some(bw) = node.data.get("bit_width").and_then(|v| v.as_i64()) {
            metadata.insert("bit_width".into(), json!(bw));
            return metadata;
        }
        if let Some(w) = node.data.get("width").and_then(|v| v.as_i64()) {
            metadata.insert("width".into(), json!(w));
            return metadata;
        }

        let node_type = node.data.get("type").and_then(|v| v.as_str()).unwrap_or("");

        // Infer width=1 for boolean signals
        if source_id.ends_with("_enable") ||
           matches!(node_type, "comparison" | "logical_and" | "logical_or" | "logical_not") {
            metadata.insert("width".into(), json!(1));
            return metadata;
        }

        // Infer width for bit_slice nodes
        if node_type == "bit_slice" {
            if let (Some(high), Some(low)) = (
                node.data.get("high_bit").and_then(|v| v.as_i64()),
                node.data.get("low_bit").and_then(|v| v.as_i64()),
            ) {
                metadata.insert("bit_width".into(), json!(high - low + 1));
                return metadata;
            }
            if let (Some(high), Some(low)) = (
                node.data.get("slice_high").and_then(|v| v.as_i64()),
                node.data.get("slice_low").and_then(|v| v.as_i64()),
            ) {
                metadata.insert("bit_width".into(), json!(high - low + 1));
                return metadata;
            }
            if let Some(expr) = node.data.get("expression") {
                if expr.get("type").and_then(|v| v.as_str()) == Some("bit_slice") {
                    if let Some(range) = expr.get("range").and_then(|v| v.as_array()) {
                        if range.len() == 2 {
                            if let (Some(h), Some(l)) = (range[0].as_i64(), range[1].as_i64()) {
                                metadata.insert("bit_width".into(), json!(h - l + 1));
                                return metadata;
                            }
                        }
                    }
                }
            }
        }

        // Try to infer from incoming edges
        if let Some(width) = self.infer_width_from_incoming(source_id, 0) {
            metadata.insert("bit_width".into(), json!(width));
        }

        metadata
    }

    /// Infer bit width by tracing incoming assignment/bit_access edges.
    fn infer_width_from_incoming(&self, node_id: &str, depth: usize) -> Option<i64> {
        if depth > 5 {
            return None;
        }

        let node = self.graph.nodes.get(node_id)?;
        let node_type = node.data.get("type").and_then(|v| v.as_str()).unwrap_or("");

        // For concatenation nodes, sum component widths
        if node_type == "concatenation" {
            if let Some(expr) = node.data.get("expression") {
                if expr.get("type").and_then(|v| v.as_str()) == Some("concatenation") {
                    let parts = expr.get("parts")
                        .or_else(|| expr.get("expressions"))
                        .or_else(|| expr.get("components"))
                        .and_then(|v| v.as_array());
                    if let Some(parts) = parts {
                        let mut total: i64 = 0;
                        for comp in parts {
                            let ct = comp.get("type").and_then(|v| v.as_str()).unwrap_or("");
                            match ct {
                                "repetition" => {
                                    let count = comp.get("count").and_then(|v| v.as_i64()).unwrap_or(1);
                                    let inner = comp.get("expression").unwrap_or(comp);
                                    let inner_w = inner.get("width")
                                        .or_else(|| inner.get("bit_width"))
                                        .and_then(|v| v.as_i64())
                                        .unwrap_or(1);
                                    total += count * inner_w;
                                }
                                "bit_slice" => {
                                    if let Some(range) = comp.get("range").and_then(|v| v.as_array()) {
                                        if range.len() == 2 {
                                            let h = range[0].as_i64().unwrap_or(0);
                                            let l = range[1].as_i64().unwrap_or(0);
                                            total += h - l + 1;
                                        }
                                    } else {
                                        total += 1;
                                    }
                                }
                                "literal" => {
                                    total += comp.get("width")
                                        .or_else(|| comp.get("bit_width"))
                                        .and_then(|v| v.as_i64())
                                        .unwrap_or(32);
                                }
                                "identifier" => {
                                    let ref_id = comp.get("name").and_then(|v| v.as_str());
                                    if let Some(rid) = ref_id {
                                        if let Some(rn) = self.graph.nodes.get(rid) {
                                            let rw = rn.data.get("bit_width")
                                                .or_else(|| rn.data.get("width"))
                                                .and_then(|v| v.as_i64())
                                                .unwrap_or(32);
                                            total += rw;
                                        } else {
                                            total += 32;
                                        }
                                    } else {
                                        total += 32;
                                    }
                                }
                                _ => {
                                    total += comp.get("width")
                                        .or_else(|| comp.get("bit_width"))
                                        .and_then(|v| v.as_i64())
                                        .unwrap_or(32);
                                }
                            }
                        }
                        if total > 0 {
                            return Some(total);
                        }
                    }
                }
            }
        }

        // For multiplexer nodes, infer from inputs
        if node_type == "multiplexer" {
            let mut best_width: Option<i64> = None;
            for eid in &node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(eid) {
                    let has_pos = edge.data.get("position").is_some();
                    let is_mux_input = edge.data.get("type").and_then(|v| v.as_str()) == Some("mux_input");
                    if has_pos || is_mux_input {
                        if let Some(src) = self.graph.nodes.get(&edge.source) {
                            let w = src.data.get("bit_width")
                                .or_else(|| src.data.get("width"))
                                .and_then(|v| v.as_i64());
                            if let Some(w) = w {
                                if w != 32 && (best_width.is_none() || w > best_width.unwrap()) {
                                    best_width = Some(w);
                                }
                            }
                        }
                    }
                }
            }
            if let Some(w) = best_width {
                return Some(w);
            }
        }

        // Check incoming assignment/bit_access edges
        for eid in &node.incoming_edges {
            if let Some(edge) = self.graph.edges.get(eid) {
                let et = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                if et == "assignment" || et == "bit_access" {
                    if let Some(src) = self.graph.nodes.get(&edge.source) {
                        if let Some(bw) = src.data.get("bit_width").and_then(|v| v.as_i64()) {
                            return Some(bw);
                        }
                        let st = src.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                        if st == "bit_slice" {
                            if let (Some(h), Some(l)) = (
                                src.data.get("high_bit").and_then(|v| v.as_i64()),
                                src.data.get("low_bit").and_then(|v| v.as_i64()),
                            ) {
                                return Some(h - l + 1);
                            }
                            if let (Some(h), Some(l)) = (
                                src.data.get("slice_high").and_then(|v| v.as_i64()),
                                src.data.get("slice_low").and_then(|v| v.as_i64()),
                            ) {
                                return Some(h - l + 1);
                            }
                        }
                        let result = self.infer_width_from_incoming(&edge.source, depth + 1);
                        if let Some(w) = result {
                            if w != 32 {
                                return Some(w);
                            }
                        }
                    }
                }
            }
        }

        None
    }

    /// Add validity signals for each pipeline stage.
    fn add_validity_signals(&mut self) {
        log::info!("\n{}", "=".repeat(70));
        log::info!("ADDING PIPELINE VALIDITY SIGNALS");
        log::info!("{}", "=".repeat(70));

        // Find all pipeline stages by looking at pipeline register names
        let mut stage_names: HashSet<String> = HashSet::new();
        for (node_id, node) in &self.graph.nodes {
            let is_pipe_reg = node.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_register");
            if is_pipe_reg && node_id.starts_with("PIPE_") && node_id.ends_with("_PIPE") {
                let parts: Vec<&str> = node_id.split('_').collect();
                if parts.len() >= 3 {
                    stage_names.insert(parts[1].to_string());
                }
            }
        }

        if stage_names.is_empty() {
            log::info!("  No pipeline stages found");
            return;
        }

        // Determine stage order
        let stage_order: Vec<(String, i64)> = if let Some(ref explicit_order) = self.explicit_stage_order {
            if let Some(ref indices) = self.explicit_stage_indices {
                explicit_order.iter()
                    .filter(|s| stage_names.contains(*s) && indices.contains_key(*s))
                    .map(|s| (s.clone(), indices[s]))
                    .collect()
            } else {
                explicit_order.iter()
                    .filter(|s| stage_names.contains(*s))
                    .enumerate()
                    .map(|(i, s)| (s.clone(), i as i64))
                    .collect()
            }
        } else {
            // Infer from pipe_time of pipeline registers
            let mut stage_min_times: HashMap<String, i64> = HashMap::new();
            for (node_id, node) in &self.graph.nodes {
                let is_pipe_reg = node.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_register");
                if is_pipe_reg && node_id.starts_with("PIPE_") && node_id.ends_with("_PIPE") {
                    let parts: Vec<&str> = node_id.split('_').collect();
                    if parts.len() >= 3 {
                        let stage = parts[1].to_string();
                        let time_val = node.pipe_time.or(node.uarch_time).unwrap_or(0);
                        let entry = stage_min_times.entry(stage).or_insert(i64::MAX);
                        if time_val < *entry {
                            *entry = time_val;
                        }
                    }
                }
            }
            let mut order: Vec<(String, i64)> = stage_min_times.into_iter().collect();
            order.sort_by_key(|(_, t)| *t);
            order
        };

        log::info!("  Found {} pipeline stages: {:?}", stage_order.len(), stage_order.iter().map(|(s, _)| s.as_str()).collect::<Vec<_>>());

        // Create validity signal for each stage
        let mut valid_signal_ids: Vec<(String, String)> = Vec::new(); // (stage_name, valid_node_id)
        let mut prev_valid_id: Option<String> = None;

        for (stage_name, depth) in &stage_order {
            let valid_id = format!("PIPE_{}_valid_PIPE", stage_name);

            let mut data: HashMap<String, Value> = HashMap::new();
            data.insert("type".into(), json!("pipeline_register"));
            data.insert("name".into(), json!(&valid_id));
            data.insert("display_name".into(), json!(format!("{} valid", stage_name)));
            data.insert("bit_width".into(), json!(1));
            data.insert("pipeline_component".into(), json!(true));

            let valid_node = Node::new(
                Some(valid_id.clone()),
                Some(data),
                false, false, None,
                false,
                Some(*depth), // uarch_time
                Some(*depth), // pipe_time
                false, false, 0, false, true, None, None,
            );
            self.graph.add_node(valid_node);
            log::info!("  Created validity signal: {}", valid_id);

            // Connect to previous stage's validity (or constant 1 for first stage)
            if let Some(ref prev_id) = prev_valid_id {
                let mut edge_data: HashMap<String, Value> = HashMap::new();
                edge_data.insert("type".into(), json!("pipeline_input"));
                edge_data.insert("pipeline_component".into(), json!(true));
                let edge = Edge::new(prev_id.clone(), valid_id.clone(), None, Some(edge_data));
                self.graph.add_edge(edge);
            } else {
                // First stage: create const_valid_1
                if !self.graph.nodes.contains_key("const_valid_1") {
                    let mut const_data: HashMap<String, Value> = HashMap::new();
                    const_data.insert("type".into(), json!("literal"));
                    const_data.insert("value".into(), json!(1));
                    const_data.insert("bit_width".into(), json!(1));
                    const_data.insert("name".into(), json!("const_valid_1"));
                    let const_node = Node::new(
                        Some("const_valid_1".into()),
                        Some(const_data),
                        false, false, None, false, None, None,
                        false, false, 0, false, true, None, None,
                    );
                    self.graph.add_node(const_node);
                }
                let mut edge_data: HashMap<String, Value> = HashMap::new();
                edge_data.insert("type".into(), json!("pipeline_input"));
                edge_data.insert("pipeline_component".into(), json!(true));
                let edge = Edge::new("const_valid_1".into(), valid_id.clone(), None, Some(edge_data));
                self.graph.add_edge(edge);
            }

            valid_signal_ids.push((stage_name.clone(), valid_id.clone()));
            prev_valid_id = Some(valid_id);
        }

        // Find stall controller
        let stall_ctrl_id: Option<String> = self.graph.nodes.iter()
            .find(|(nid, n)| {
                nid.contains("stall_ctrl") &&
                n.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_stall_controller")
            })
            .map(|(nid, _)| nid.clone());

        // Connect stall controller to pipeline registers
        if let Some(ref stall_id) = stall_ctrl_id {
            // Connect to Execute-stage pipeline registers
            if stage_order.len() >= 2 {
                let second_stage = &stage_order[1].0;
                let prefix = format!("PIPE_{}_", second_stage);
                let suffix = "_PIPE";
                let double_suffix = "_PIPE_PIPE";
                let valid_suffix = "_valid_PIPE";

                let reg_ids: Vec<String> = self.graph.nodes.keys()
                    .filter(|nid| {
                        nid.starts_with(&prefix) && nid.ends_with(suffix) &&
                        !nid.ends_with(double_suffix) && !nid.ends_with(valid_suffix)
                    })
                    .cloned()
                    .collect();

                let mut stall_count = 0;
                for reg_id in &reg_ids {
                    let has_stall = self.graph.nodes[reg_id].incoming_edges.iter().any(|eid| {
                        self.graph.edges.get(eid)
                            .map(|e| e.data.get("type").and_then(|v| v.as_str()) == Some("stall"))
                            .unwrap_or(false)
                    });
                    if !has_stall {
                        let mut edge_data: HashMap<String, Value> = HashMap::new();
                        edge_data.insert("type".into(), json!("stall"));
                        edge_data.insert("description".into(), json!(format!("Gate {} pipeline register when stalling", second_stage)));
                        let edge = Edge::new(stall_id.clone(), reg_id.clone(), None, Some(edge_data));
                        self.graph.add_edge(edge);
                        stall_count += 1;
                    }
                }
                if stall_count > 0 {
                    log::info!("  Connected stall controller to {} additional {} pipeline registers", stall_count, second_stage);
                }
            }

            // Connect to Decode-stage pipeline registers (hold behavior)
            if !stage_order.is_empty() {
                let first_stage = &stage_order[0].0;
                let prefix = format!("PIPE_{}_", first_stage);
                let suffix = "_PIPE";
                let double_suffix = "_PIPE_PIPE";
                let valid_suffix = "_valid_PIPE";

                let reg_ids: Vec<String> = self.graph.nodes.keys()
                    .filter(|nid| {
                        nid.starts_with(&prefix) && nid.ends_with(suffix) &&
                        !nid.ends_with(double_suffix) && !nid.ends_with(valid_suffix)
                    })
                    .cloned()
                    .collect();

                let mut hold_count = 0;
                for reg_id in &reg_ids {
                    let has_stall = self.graph.nodes[reg_id].incoming_edges.iter().any(|eid| {
                        self.graph.edges.get(eid)
                            .map(|e| e.data.get("type").and_then(|v| v.as_str()) == Some("stall"))
                            .unwrap_or(false)
                    });
                    if !has_stall {
                        let mut edge_data: HashMap<String, Value> = HashMap::new();
                        edge_data.insert("type".into(), json!("stall"));
                        edge_data.insert("hold".into(), json!(true));
                        edge_data.insert("description".into(), json!(format!("Hold {} pipeline register when stalling", first_stage)));
                        let edge = Edge::new(stall_id.clone(), reg_id.clone(), None, Some(edge_data));
                        self.graph.add_edge(edge);
                        hold_count += 1;
                    }
                }
                if hold_count > 0 {
                    log::info!("  Connected stall controller to {} {} pipeline registers (hold behavior)", hold_count, first_stage);
                }
            }

            // Gate PC updates with stall
            if self.graph.nodes.contains_key("pc_wr") {
                let mut edge_data: HashMap<String, Value> = HashMap::new();
                edge_data.insert("type".into(), json!("stall"));
                edge_data.insert("description".into(), json!("Gate PC update when stalling"));
                let edge = Edge::new(stall_id.clone(), "pc_wr".into(), None, Some(edge_data));
                self.graph.add_edge(edge);
                log::info!("  PC gating: pc_rd held when stalling");
            }

            // Bubble injection: second_stage_valid = first_stage_valid AND NOT stall
            if stage_order.len() >= 2 {
                let first_stage = &stage_order[0].0;
                let second_stage = &stage_order[1].0;

                let first_valid = format!("PIPE_{}_valid_PIPE", first_stage);
                let second_valid = format!("PIPE_{}_valid_PIPE", second_stage);

                // Create NOT stall
                let not_stall_id = format!("{}_not", stall_id);
                if !self.graph.nodes.contains_key(&not_stall_id) {
                    let mut data: HashMap<String, Value> = HashMap::new();
                    data.insert("type".into(), json!("operation"));
                    data.insert("operator".into(), json!("!"));
                    data.insert("name".into(), json!(&not_stall_id));
                    let not_node = Node::new(Some(not_stall_id.clone()), Some(data), false, false, None, false, None, None, false, false, 0, false, true, None, None);
                    self.graph.add_node(not_node);
                    let mut ed: HashMap<String, Value> = HashMap::new();
                    ed.insert("type".into(), json!("operand"));
                    let edge = Edge::new(stall_id.clone(), not_stall_id.clone(), None, Some(ed));
                    self.graph.add_edge(edge);
                }

                // Create AND gate: prev_valid AND NOT stall
                let and_id = format!("PIPE_{}_valid_and_not_stall", second_stage);
                let mut and_data: HashMap<String, Value> = HashMap::new();
                and_data.insert("type".into(), json!("operation"));
                and_data.insert("operator".into(), json!("&&"));
                and_data.insert("name".into(), json!(&and_id));
                let and_node = Node::new(Some(and_id.clone()), Some(and_data), false, false, None, false, None, None, false, false, 0, false, true, None, None);
                self.graph.add_node(and_node);

                // Remove existing pipeline_input edge to second_valid
                let edges_to_remove: Vec<String> = self.graph.nodes.get(&second_valid)
                    .map(|n| n.incoming_edges.iter()
                        .filter(|eid| {
                            self.graph.edges.get(*eid)
                                .map(|e| e.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_input"))
                                .unwrap_or(false)
                        })
                        .cloned()
                        .collect())
                    .unwrap_or_default();
                for eid in &edges_to_remove {
                    self.graph.remove_edge(eid);
                }

                // Connect: first_valid -> AND left
                let source_for_and = if self.graph.nodes.contains_key(&first_valid) {
                    first_valid.clone()
                } else {
                    "const_valid_1".into()
                };
                let mut e1d: HashMap<String, Value> = HashMap::new();
                e1d.insert("type".into(), json!("left_operand"));
                e1d.insert("position".into(), json!("left"));
                let e1 = Edge::new(source_for_and, and_id.clone(), None, Some(e1d));
                self.graph.add_edge(e1);

                // Connect: NOT stall -> AND right
                let mut e2d: HashMap<String, Value> = HashMap::new();
                e2d.insert("type".into(), json!("right_operand"));
                e2d.insert("position".into(), json!("right"));
                let e2 = Edge::new(not_stall_id.clone(), and_id.clone(), None, Some(e2d));
                self.graph.add_edge(e2);

                // Connect: AND -> second_valid
                let mut e3d: HashMap<String, Value> = HashMap::new();
                e3d.insert("type".into(), json!("pipeline_input"));
                e3d.insert("pipeline_component".into(), json!(true));
                let e3 = Edge::new(and_id.clone(), second_valid.clone(), None, Some(e3d));
                self.graph.add_edge(e3);

                log::info!("  Bubble injection: {}_valid = {}_valid AND NOT stall", second_stage, first_stage);
            }
        }

        // Gate memory write enables with validity
        self.gate_memory_writes_with_validity(&valid_signal_ids, &stage_order);

        log::info!("  Validity signals added successfully");
    }

    /// Gate memory write port enables with the validity signal of the appropriate stage.
    fn gate_memory_writes_with_validity(
        &mut self,
        valid_signal_ids: &[(String, String)],
        stage_order: &[(String, i64)],
    ) {
        if stage_order.is_empty() || valid_signal_ids.is_empty() {
            return;
        }

        // Find memory_write_port nodes
        let write_ports: Vec<(String, String, Option<String>)> = self.graph.nodes.iter()
            .filter(|(_, n)| n.data.get("type").and_then(|v| v.as_str()) == Some("memory_write_port"))
            .filter_map(|(nid, n)| {
                let we_name = n.data.get("combined_write_enable").and_then(|v| v.as_str())?.to_string();
                let cache = n.data.get("cache_name").and_then(|v| v.as_str()).map(|s| s.to_string());
                Some((nid.clone(), we_name, cache))
            })
            .collect();

        for (port_id, write_enable_name, cache_name) in &write_ports {
            // Skip cache write-through ports
            if cache_name.is_some() {
                log::info!("  Skipping validity gating for cache write-through port {}", port_id);
                continue;
            }

            // Find the write enable node
            if !self.graph.nodes.contains_key(write_enable_name) {
                continue;
            }

            // Find the deepest pipelined version
            let best_enable = self.find_deepest_pipelined(write_enable_name);

            // Determine which stage this write happens in
            let write_time = self.graph.nodes.get(&best_enable)
                .and_then(|n| n.pipe_time.or(n.uarch_time));

            let write_stage = write_time.and_then(|wt| {
                valid_signal_ids.iter().find(|(_, vid)| {
                    self.graph.nodes.get(vid)
                        .and_then(|n| n.pipe_time.or(n.uarch_time))
                        .map(|vt| vt == wt)
                        .unwrap_or(false)
                }).map(|(s, _)| s.clone())
            }).or_else(|| {
                // Use last stage as fallback
                stage_order.last().map(|(s, _)| s.clone())
            });

            let write_stage = match write_stage {
                Some(s) => s,
                None => continue,
            };

            let valid_id = format!("PIPE_{}_valid_PIPE", write_stage);
            if !self.graph.nodes.contains_key(&valid_id) {
                continue;
            }

            // Create: write_enable_gated = write_enable AND stage_valid
            let and_id = format!("{}_valid_gated", write_enable_name);
            let mut and_data: HashMap<String, Value> = HashMap::new();
            and_data.insert("type".into(), json!("operation"));
            and_data.insert("operator".into(), json!("&&"));
            and_data.insert("name".into(), json!(&and_id));
            and_data.insert("display_name".into(), json!(format!("{} (valid gated)", write_enable_name)));
            let and_node = Node::new(Some(and_id.clone()), Some(and_data), false, false, None, false, None, None, false, false, 0, false, true, None, None);
            self.graph.add_node(and_node);

            // Move write_enable's outgoing edges to AND node
            let outgoing: Vec<String> = self.graph.nodes.get(&best_enable)
                .map(|n| n.outgoing_edges.iter().cloned().collect())
                .unwrap_or_default();
            for eid in &outgoing {
                if let Some(edge) = self.graph.edges.get(eid) {
                    let target = edge.target.clone();
                    let data = edge.data.clone();
                    let new_edge = Edge::new(and_id.clone(), target, None, Some(data));
                    self.graph.add_edge(new_edge);
                }
                self.graph.remove_edge(eid);
            }

            // Connect: write_enable -> AND left
            let mut e1d: HashMap<String, Value> = HashMap::new();
            e1d.insert("type".into(), json!("left_operand"));
            e1d.insert("position".into(), json!("left"));
            let e1 = Edge::new(best_enable.clone(), and_id.clone(), None, Some(e1d));
            self.graph.add_edge(e1);

            // Connect: validity -> AND right
            let mut e2d: HashMap<String, Value> = HashMap::new();
            e2d.insert("type".into(), json!("right_operand"));
            e2d.insert("position".into(), json!("right"));
            let e2 = Edge::new(valid_id.clone(), and_id.clone(), None, Some(e2d));
            self.graph.add_edge(e2);

            log::info!("  Gated {} with {} validity", write_enable_name, write_stage);

            // Update write_port to use gated version
            if let Some(wp) = self.graph.nodes.get_mut(port_id) {
                wp.data.insert("combined_write_enable".into(), json!(&and_id));
            }
        }
    }

    /// Find the deepest pipelined version of a node (following outgoing pipeline registers).
    fn find_deepest_pipelined(&self, node_id: &str) -> String {
        let mut best = node_id.to_string();
        let mut visited: HashSet<String> = HashSet::new();

        fn recurse(graph: &ResourceGraph, current: &str, best: &mut String, visited: &mut HashSet<String>) {
            if visited.contains(current) {
                return;
            }
            visited.insert(current.to_string());

            if let Some(node) = graph.nodes.get(current) {
                if node.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_register") {
                    *best = current.to_string();
                }
                for eid in &node.outgoing_edges {
                    if let Some(edge) = graph.edges.get(eid) {
                        if let Some(target) = graph.nodes.get(&edge.target) {
                            if target.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_register") {
                                recurse(graph, &edge.target, best, visited);
                            }
                        }
                    }
                }
            }
        }

        recurse(self.graph, node_id, &mut best, &mut visited);
        best
    }

    /// Get summary of pipeline components added.
    pub fn get_pipeline_summary(&self) -> PipelineSummary {
        let mut components: HashMap<String, Vec<String>> = HashMap::new();

        for (nid, node) in &self.graph.nodes {
            let is_pc = node.data.get("pipeline_component").and_then(|v| v.as_bool()).unwrap_or(false);
            let pp = node.data.get("pipeline_prefix").and_then(|v| v.as_str()).unwrap_or("");
            if is_pc && pp == self.pipeline_prefix {
                let ct = node.data.get("type").and_then(|v| v.as_str()).unwrap_or("unknown").to_string();
                components.entry(ct).or_default().push(nid.clone());
            }
        }

        PipelineSummary {
            total_stages: self.stage_counter,
            pipeline_prefix: self.pipeline_prefix.clone(),
            components,
            max_uarch_time: self.graph.get_max_uarch_time(),
        }
    }
}

/// Summary of pipeline components.
#[derive(Debug)]
pub struct PipelineSummary {
    pub total_stages: usize,
    pub pipeline_prefix: String,
    pub components: HashMap<String, Vec<String>>,
    pub max_uarch_time: i64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sanitize_for_verilog() {
        assert_eq!(sanitize_for_verilog("rf[rs]_rd"), "rf_rs_rd");
        assert_eq!(sanitize_for_verilog("(pc + 4)"), "pc_add_4");
        assert_eq!(sanitize_for_verilog("a == b"), "a_eqeq_b");
    }

    #[test]
    fn test_pipeline_transform_basic() {
        let mut graph = ResourceGraph::new();

        // Create simple graph: src -> dst
        let src = Node::new(Some("src".into()), None, false, false, None, false, Some(0), None, false, false, 0, false, true, None, None);
        let dst = Node::new(Some("dst".into()), None, false, false, None, false, Some(1), None, false, false, 0, false, true, None, None);
        graph.add_node(src);
        graph.add_node(dst);

        let mut edge_data: HashMap<String, Value> = HashMap::new();
        edge_data.insert("type".into(), json!("assignment"));
        let edge = Edge::new("src".into(), "dst".into(), Some("e1".into()), Some(edge_data));
        graph.add_edge(edge);

        let cut_specs = vec![CutSpec {
            edges: vec!["e1".into()],
            after_stage: "Decode".into(),
            stage_index: Some(1),
        }];

        let mut transform = PipelineTransform::new(&mut graph);
        transform.set_stage_order(vec!["Decode".into()], Some([("Decode".into(), 1)].into()));
        let result = transform.add_multiple_pipeline_stages(&cut_specs);
        assert!(result);

        // Should have created pipeline register
        assert!(graph.nodes.contains_key("PIPE_Decode_src_PIPE"));
        // Should have validity signal
        assert!(graph.nodes.contains_key("PIPE_Decode_valid_PIPE"));
    }
}
