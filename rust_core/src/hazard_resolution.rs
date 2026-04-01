//! Hazard resolution for pipelined processors.
//!
//! Ports the core hazard analysis and resolution from Python's hazard_resolution.py.
//! Key operations:
//! - `HazardAnalyzer`: Detects RAW hazards on indexed resources (register files)
//! - `HazardResolver`: Resolves hazards via stalling or bypassing
//! - Control hazard handling (branch/jump flush)
//! - Write enable gating with validity signals

use crate::hardware_builders::{
    self, ArrayAccessInfo,
};
use crate::resource_graph::{Edge, Node, ResourceGraph};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

/// Strategy for resolving a detected hazard.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HazardResolutionStrategy {
    Stall,
    Bypass,
    None,
}

/// A detected pipeline hazard with its characteristics.
#[derive(Debug, Clone)]
pub struct DetectedHazard {
    pub hazard_type: String, // "RAW", "WAR", "WAW"
    pub resource: String,    // e.g., "rf"
    pub write_stage: i64,
    pub write_stage_name: String,
    pub write_access_node_id: String,
    pub write_index_node_id: String,
    pub write_index_name: String,
    pub read_stage: i64,
    pub read_stage_name: String,
    pub read_access_node_id: String,
    pub read_index_node_id: String,
    pub read_index_name: String,
    pub resolution: HazardResolutionStrategy,
}

impl DetectedHazard {
    pub fn get_forwarding_distance(&self) -> i64 {
        self.write_stage - self.read_stage
    }
}

/// Information about a pipeline stage.
#[derive(Debug, Clone)]
pub struct PipelineStageInfo {
    pub stage_index: usize,
    pub stage_name: String,
    pub pipeline_register_id: String,
}

/// Analyzes pipeline for hazards.
pub struct HazardAnalyzer<'a> {
    pub graph: &'a ResourceGraph,
    pub pipeline_stages: Vec<PipelineStageInfo>,
    pub hazards: Vec<DetectedHazard>,
    pub pc_name: String,
}

impl<'a> HazardAnalyzer<'a> {
    pub fn new(graph: &'a ResourceGraph, pc_name: &str) -> Self {
        Self {
            graph,
            pipeline_stages: Vec::new(),
            hazards: Vec::new(),
            pc_name: pc_name.to_string(),
        }
    }

    /// Identify all pipeline stages in the graph.
    pub fn identify_pipeline_stages(&mut self) -> &[PipelineStageInfo] {
        let mut stages_dict: HashMap<String, Vec<String>> = HashMap::new();

        for (node_id, node) in &self.graph.nodes {
            if node.data.get("type").and_then(|v| v.as_str()) != Some("pipeline_register") {
                continue;
            }
            let mut working_id = node_id.as_str();
            // Strip dual-issue prefix
            if working_id.starts_with("p0_") || working_id.starts_with("p1_") {
                working_id = &working_id[3..];
            }
            if working_id.starts_with("PIPE_") && working_id.contains("_PIPE") {
                let parts: Vec<&str> = working_id.split('_').collect();
                if parts.len() >= 3 {
                    let stage_name = parts[1].to_string();
                    stages_dict.entry(stage_name).or_default().push(node_id.clone());
                }
            }
        }

        let mut stages: Vec<PipelineStageInfo> = Vec::new();
        let mut sorted_stages: Vec<(&String, &Vec<String>)> = stages_dict.iter().collect();
        sorted_stages.sort_by_key(|(name, _)| name.to_string());

        for (i, (stage_name, regs)) in sorted_stages.iter().enumerate() {
            stages.push(PipelineStageInfo {
                stage_index: i + 1,
                stage_name: stage_name.to_string(),
                pipeline_register_id: regs[0].clone(),
            });
        }

        log::info!("  Identified {} stages: {:?}",
            stages.len(),
            stages.iter().map(|s| (s.stage_index, &s.stage_name)).collect::<Vec<_>>()
        );

        self.pipeline_stages = stages;
        &self.pipeline_stages
    }

    /// Analyze the graph for all pipeline hazards on indexed resources.
    pub fn analyze_hazards(&mut self) -> &[DetectedHazard] {
        self.hazards.clear();

        if self.pipeline_stages.is_empty() {
            self.identify_pipeline_stages();
        }

        // Find all indexed ISA state resources
        let all_accesses = hardware_builders::get_all_array_accesses(self.graph, None);

        let mut resources: HashMap<String, Vec<ArrayAccessInfo>> = HashMap::new();
        for access in all_accesses {
            if let Some(base_node) = self.graph.nodes.get(&access.base_resource) {
                let is_isa_state = base_node.is_arch_state ||
                    base_node.data.get("type").and_then(|v| v.as_str()) == Some("isa_state");
                let is_var_latency = base_node.variable_latency;
                if is_isa_state && !is_var_latency {
                    resources.entry(access.base_resource.clone()).or_default().push(access);
                }
            }
        }

        if !resources.is_empty() {
            let mut keys: Vec<&String> = resources.keys().collect();
            keys.sort();
            log::info!("Discovered indexed ISA state resources: {:?}", keys);
        } else {
            log::info!("No indexed ISA state resources found");
        }

        let resource_names: Vec<String> = resources.keys().cloned().collect();
        for resource_name in &resource_names {
            self.analyze_resource_hazards(resource_name);
        }

        &self.hazards
    }

    fn analyze_resource_hazards(&mut self, resource_name: &str) {
        let (read_accesses, write_accesses) = hardware_builders::get_reads_and_writes(self.graph, Some(resource_name));

        // Build reads with stage info
        let mut res_reads: Vec<(String, String, Option<String>, i64)> = Vec::new(); // (node_id, index, index_node_id, stage)
        for access in &read_accesses {
            let stage = self.graph.nodes.get(&access.node_id)
                .and_then(|n| n.pipe_time.or(n.uarch_time))
                .unwrap_or(access.uarch_time);
            res_reads.push((
                access.node_id.clone(),
                access.index.clone(),
                access.index_node_id.clone(),
                stage,
            ));
        }

        // Check memory_write_port nodes - these trace the write index through
        // ALL pipeline stages, creating stall comparators at intermediate stages.
        // For 5-stage pipelines, this is essential: a write at Writeback needs
        // stall comparators at Execute, Memory, AND Writeback to stall for 3 cycles.
        let mut write_port_ids: Vec<String> = self.graph.nodes.iter()
            .filter(|(nid, n)| {
                n.data.get("type").and_then(|v| v.as_str()) == Some("memory_write_port") &&
                nid.contains(resource_name)
            })
            .map(|(nid, _)| nid.clone())
            .collect();
        write_port_ids.sort();

        // Build writes with stage info
        let mut res_writes: Vec<(String, String, Option<String>, i64)> = Vec::new();
        let mut has_write_port_writes = false;

        for wp_id in &write_port_ids {
            let node = &self.graph.nodes[wp_id];
            // Find index node from write_address or array_index edges
            let index_node_id = node.incoming_edges.iter()
                .filter_map(|eid| self.graph.edges.get(eid))
                .find(|e| {
                    let et = e.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                    et == "write_address" || et == "array_index"
                })
                .map(|e| e.source.clone());

            if let Some(ref idx_id) = index_node_id {
                // Trace through pipeline to find all stages
                let stages = self.trace_write_index_through_pipeline(idx_id);
                log::info!("  traced stages for {}: {:?}", idx_id, stages);
                if !stages.is_empty() {
                    has_write_port_writes = true;
                    for (stage_node_id, stage) in &stages {
                        res_writes.push((
                            wp_id.clone(),
                            self.extract_core_name(idx_id),
                            Some(stage_node_id.clone()),
                            *stage as i64,
                        ));
                    }
                } else {
                    let write_stage = self.graph.nodes.get(wp_id)
                        .and_then(|n| n.pipe_time.or(n.uarch_time))
                        .unwrap_or(0);
                    res_writes.push((
                        wp_id.clone(),
                        self.extract_core_name(idx_id),
                        Some(idx_id.clone()),
                        write_stage,
                    ));
                }
            }
        }

        // Only use original write_accesses if no memory_write_port entries
        // produced traced writes (they cover all pipeline stages correctly
        // with the right index at each stage depth).
        if !has_write_port_writes {
            for access in &write_accesses {
                let stage = self.determine_node_stage(&access.node_id).unwrap_or(0) as i64;
                res_writes.push((
                    access.node_id.clone(),
                    access.index.clone(),
                    access.index_node_id.clone(),
                    stage,
                ));
            }
        }

        log::info!("Found {} {} reads, {} {} writes", res_reads.len(), resource_name, res_writes.len(), resource_name);

        // Detect RAW hazards: write in later stage, read in earlier stage
        for (w_node, w_idx, w_idx_node, w_stage) in &res_writes {
            for (r_node, r_idx, r_idx_node, r_stage) in &res_reads {
                if w_stage > r_stage {
                    let w_stage_name = self.stage_name_for_time(*w_stage);
                    let r_stage_name = self.stage_name_for_time(*r_stage);

                    let hazard = DetectedHazard {
                        hazard_type: "RAW".into(),
                        resource: resource_name.into(),
                        write_stage: *w_stage,
                        write_stage_name: w_stage_name,
                        write_access_node_id: w_node.clone(),
                        write_index_node_id: w_idx_node.clone().unwrap_or_default(),
                        write_index_name: w_idx.clone(),
                        read_stage: *r_stage,
                        read_stage_name: r_stage_name,
                        read_access_node_id: r_node.clone(),
                        read_index_node_id: r_idx_node.clone().unwrap_or_default(),
                        read_index_name: r_idx.clone(),
                        resolution: HazardResolutionStrategy::Stall,
                    };
                    log::info!("  Detected: RAW hazard {} -> {}", w_node, r_node);
                    self.hazards.push(hazard);
                }
            }
        }
    }

    fn determine_node_stage(&self, node_id: &str) -> Option<usize> {
        if self.pipeline_stages.is_empty() {
            return None;
        }

        // DFS backward to find pipeline registers
        let mut visited: HashSet<String> = HashSet::new();
        let mut stages_encountered: HashSet<usize> = HashSet::new();

        fn dfs_backward(
            graph: &ResourceGraph,
            node_id: &str,
            visited: &mut HashSet<String>,
            stages: &[PipelineStageInfo],
            encountered: &mut HashSet<usize>,
        ) {
            if visited.contains(node_id) {
                return;
            }
            visited.insert(node_id.to_string());

            for (i, stage) in stages.iter().enumerate() {
                if node_id == stage.pipeline_register_id {
                    encountered.insert(i);
                    return;
                }
            }

            if let Some(node) = graph.nodes.get(node_id) {
                for eid in &node.incoming_edges {
                    if let Some(edge) = graph.edges.get(eid) {
                        dfs_backward(graph, &edge.source, visited, stages, encountered);
                    }
                }
            }
        }

        dfs_backward(self.graph, node_id, &mut visited, &self.pipeline_stages, &mut stages_encountered);

        if let Some(&max_stage) = stages_encountered.iter().max() {
            Some(max_stage + 1)
        } else {
            Some(0)
        }
    }

    fn trace_write_index_through_pipeline(&self, node_id: &str) -> Vec<(String, usize)> {
        let mut result = Vec::new();
        let mut current_id = node_id.to_string();
        let mut visited: HashSet<String> = HashSet::new();

        let max_stage = self.pipeline_stages.iter().map(|s| s.stage_index).max().unwrap_or(0);

        loop {
            if visited.contains(&current_id) {
                break;
            }
            visited.insert(current_id.clone());

            let node = match self.graph.nodes.get(&current_id) {
                Some(n) => n,
                None => break,
            };

            if node.data.get("type").and_then(|v| v.as_str()) != Some("pipeline_register") {
                break;
            }

            // Prefer pipe_time (set by infer_pipe_time), fall back to depth heuristic
            let stage = if let Some(pt) = node.pipe_time {
                (pt as usize).min(max_stage)
            } else {
                let depth = count_pipe_depth(&current_id);
                (depth + 1).min(max_stage)
            };
            result.push((current_id.clone(), stage));

            // Trace backward through pipeline_input
            let next = node.incoming_edges.iter()
                .filter_map(|eid| self.graph.edges.get(eid))
                .find(|e| e.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_input"))
                .map(|e| e.source.clone());

            match next {
                Some(next_id) => {
                    if let Some(next_node) = self.graph.nodes.get(&next_id) {
                        if next_node.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_register") {
                            current_id = next_id;
                        } else {
                            // Non-pipeline-register node (e.g., multiplexer).
                            // Check if its mux_input sources lead to pipeline registers.
                            // This handles the case where rf_write_addr_mux is a mux
                            // with all inputs from PIPE_Execute_rd_PIPE.
                            let mux_inputs: HashSet<String> = self.graph.edges.values()
                                .filter(|e| e.target == next_id)
                                .filter(|e| e.data.get("type").and_then(|v| v.as_str()) == Some("mux_input"))
                                .map(|e| e.source.clone())
                                .collect();

                            // If all mux inputs are the same pipeline register, continue from there
                            if mux_inputs.len() == 1 {
                                let src = mux_inputs.into_iter().next().unwrap();
                                if let Some(src_node) = self.graph.nodes.get(&src) {
                                    if src_node.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_register") {
                                        current_id = src;
                                        continue;
                                    }
                                }
                            }
                            break;
                        }
                    } else {
                        break;
                    }
                }
                None => break,
            }
        }

        result
    }

    fn stage_name_for_time(&self, pipe_time: i64) -> String {
        if pipe_time > 0 && (pipe_time as usize - 1) < self.pipeline_stages.len() {
            self.pipeline_stages[pipe_time as usize - 1].stage_name.clone()
        } else if pipe_time == 0 {
            "Fetch".into()
        } else if let Some(last) = self.pipeline_stages.last() {
            last.stage_name.clone()
        } else {
            format!("stage_{}", pipe_time)
        }
    }

    fn extract_core_name(&self, node_id: &str) -> String {
        let mut core = node_id.to_string();
        while core.starts_with("PIPE_") {
            if let Some(rest) = core.splitn(3, '_').nth(2) {
                core = rest.to_string();
            } else {
                break;
            }
        }
        while core.ends_with("_PIPE") {
            core = core[..core.len() - 5].to_string();
        }
        core
    }
}

/// Count trailing _PIPE suffixes in a node ID.
fn count_pipe_depth(node_id: &str) -> usize {
    let mut depth = 0;
    let parts: Vec<&str> = node_id.split('_').collect();
    for i in (0..parts.len()).rev() {
        if parts[i] == "PIPE" {
            depth += 1;
        } else {
            break;
        }
    }
    depth
}

/// Implements hazard resolution strategies (stalling and bypassing).
pub struct HazardResolver<'a> {
    pub graph: &'a mut ResourceGraph,
    pub isa_states_to_gate: Vec<String>,
    pub pipeline_config: Option<crate::pipeline_config::PipelineConfig>,
    /// Track bypass muxes: mux_id -> (mux_id, resource, read_index_name)
    pub bypass_muxes: HashMap<String, (String, String, String)>,
}

impl<'a> HazardResolver<'a> {
    pub fn new(
        graph: &'a mut ResourceGraph,
        isa_states_to_gate: Vec<String>,
        pipeline_config: Option<crate::pipeline_config::PipelineConfig>,
    ) -> Self {
        Self {
            graph,
            isa_states_to_gate,
            pipeline_config,
            bypass_muxes: HashMap::new(),
        }
    }

    /// Resolve all hazards according to their chosen strategies.
    pub fn resolve_all_hazards(&mut self, hazards: &[DetectedHazard]) -> bool {
        log::info!("\nResolving {} hazards...", hazards.len());

        // Sort by forwarding distance (smaller first)
        let mut sorted: Vec<&DetectedHazard> = hazards.iter().collect();
        sorted.sort_by_key(|h| h.get_forwarding_distance());

        let mut success_count = 0;
        for hazard in &sorted {
            if self.resolve_hazard(hazard) {
                success_count += 1;
            }
        }

        log::info!("Successfully resolved {}/{} hazards", success_count, hazards.len());

        // After all hazards are resolved, add Writeback forwarding to bypass muxes
        if !self.bypass_muxes.is_empty() {
            self.add_rf_write_forwarding();
        }

        // Add memory latency stalls
        self.add_automatic_memory_latency_stalls();

        // Add cache stalls (bubble insertion for instruction/data caches)
        self.add_automatic_cache_stalls();

        success_count == hazards.len()
    }

    fn resolve_hazard(&mut self, hazard: &DetectedHazard) -> bool {
        match hazard.resolution {
            HazardResolutionStrategy::Stall => self.resolve_with_stalling(hazard),
            HazardResolutionStrategy::Bypass => self.resolve_with_bypassing(hazard),
            HazardResolutionStrategy::None => true,
        }
    }

    /// Resolve a hazard by adding stall logic.
    fn resolve_with_stalling(&mut self, hazard: &DetectedHazard) -> bool {
        log::info!("Resolving with STALL: RAW on {} ({}=={}) s{} vs s{}",
            hazard.resource, hazard.write_index_name, hazard.read_index_name,
            hazard.write_stage, hazard.read_stage);

        // Check if write_read_fwd handles this hazard at the canonical read/write pair.
        // When write_read_fwd is enabled, the memory provides transparent forwarding
        // (write-first semantics), so no stall is needed for same-cycle read/write.
        let has_write_read_fwd = self.graph.nodes.get(&hazard.resource)
            .and_then(|n| n.data.get("write_read_fwd"))
            .and_then(|v| v.as_bool())
            .unwrap_or(false);

        if has_write_read_fwd {
            let read_time = self.graph.nodes.get(&hazard.read_access_node_id)
                .and_then(|n| n.pipe_time.or(n.uarch_time));
            let write_time = self.graph.nodes.get(&hazard.write_access_node_id)
                .and_then(|n| n.pipe_time.or(n.uarch_time));
            if let (Some(rt), Some(wt)) = (read_time, write_time) {
                if hazard.read_stage == rt && hazard.write_stage == wt {
                    log::info!("  Skipping stall - {} has write_read_fwd enabled", hazard.resource);
                    log::info!("  Memory handles same-cycle forwarding at read/write stages");
                    return true;
                }
            }
        }

        // Find actual write index node (pipelined version).
        // If the hazard already has a pipeline register as write_index_node_id
        // (set by trace_write_index_through_pipeline for multi-stage hazards),
        // use it directly — it's already at the correct pipeline depth.
        // Only call find_pipelined_index_at_write for standard array_access writes.
        let mut actual_write_idx = if hazard.write_index_node_id.starts_with("PIPE_")
            && self.graph.nodes.contains_key(&hazard.write_index_node_id)
        {
            hazard.write_index_node_id.clone()
        } else {
            self.find_pipelined_index_at_write(hazard)
                .unwrap_or_else(|| hazard.write_index_node_id.clone())
        };

        let read_idx = &hazard.read_index_node_id;

        // If the write index is not pipelined but write stage > read stage,
        // we need the pipelined version at the write stage
        let needs_pipelined = actual_write_idx.is_empty()
            || !self.graph.nodes.contains_key(&actual_write_idx)
            || (!actual_write_idx.starts_with("PIPE_") && hazard.write_stage > hazard.read_stage);

        if needs_pipelined {
            // Try PIPE_{write_stage_name}_{write_index_name}_PIPE first, then search structurally
            let mut candidates = vec![
                format!("PIPE_{}_{}_PIPE", hazard.write_stage_name, hazard.write_index_name),
            ];
            // Search for any Execute-containing stage pipeline register with this write index
            let suffix = format!("_{}_PIPE", hazard.write_index_name);
            for nid in self.graph.nodes.keys() {
                if nid.starts_with("PIPE_") && nid.ends_with(&suffix) {
                    let stage = &nid["PIPE_".len()..nid.len() - suffix.len()];
                    if stage.contains("Execute") && !candidates.contains(nid) {
                        candidates.push(nid.clone());
                    }
                }
            }
            // Also try with "rd" as index name (common for register writes)
            candidates.push(format!("PIPE_{}_rd_PIPE", hazard.write_stage_name));
            for pipe_name in &candidates {
                if self.graph.nodes.contains_key(pipe_name) {
                    log::info!("  Using pipelined fallback: {}", pipe_name);
                    actual_write_idx = pipe_name.clone();
                    break;
                }
            }
        }

        // Verify nodes exist
        if !self.graph.nodes.contains_key(&actual_write_idx) || !self.graph.nodes.contains_key(read_idx) {
            log::info!("  Warning: Index nodes not found (write_idx={} exists={}, read_idx={} exists={})",
                actual_write_idx, self.graph.nodes.contains_key(&actual_write_idx),
                read_idx, self.graph.nodes.contains_key(read_idx));
            return false;
        }

        // Create comparator: write_idx == read_idx
        let comp_id = format!("stall_{}_{}_{}_s{}_s{}_cmp",
            hazard.resource, hazard.write_index_name, hazard.read_index_name,
            hazard.write_stage, hazard.read_stage);

        // Skip if this comparator already exists (avoid duplicate edges from
        // multiple hazard sources at the same stage)
        if self.graph.nodes.contains_key(&comp_id) {
            log::info!("  Comparator {} already exists, skipping duplicate", comp_id);
            return true;
        }

        hardware_builders::create_index_comparator(
            self.graph,
            &comp_id,
            &actual_write_idx,
            read_idx,
            "==",
            Some(&format!("{}=={}", hazard.write_index_name, hazard.read_index_name)),
            None,
        );

        log::info!("  Connected write index: {}", actual_write_idx);
        log::info!("  Connected read index: {}", read_idx);

        // Find write enable node
        let write_enable_id = self.find_stage_write_enable(hazard, &actual_write_idx);

        // Find valid signal for write stage
        let write_stage_name = if actual_write_idx.starts_with("PIPE_") {
            actual_write_idx.split('_').nth(1).map(|s| s.to_string())
        } else {
            None
        };
        let valid_id = write_stage_name.as_ref().map(|s| format!("PIPE_{}_valid_PIPE", s));

        // Build stall condition: comp && write_enable && stage_valid
        let base_id = format!("stall_{}_{}_{}_s{}_s{}",
            hazard.resource, hazard.write_index_name, hazard.read_index_name,
            hazard.write_stage, hazard.read_stage);

        let mut current_signal = comp_id.clone();

        // AND with write enable
        if let Some(ref we_id) = write_enable_id {
            if self.graph.nodes.contains_key(we_id) {
                let and_id = format!("{}_with_enable", base_id);
                self.create_and_node(&and_id, &current_signal, we_id);
                current_signal = and_id;
            }
        }

        // AND with validity
        if let Some(ref vid) = valid_id {
            if self.graph.nodes.contains_key(vid) {
                let and_id = base_id.clone();
                self.create_and_node(&and_id, &current_signal, vid);
                current_signal = and_id;
            }
        }

        // Find read enable (for partially shared register read ports)
        let read_enable_id = format!("{}_{}_rd_enable", hazard.resource, hazard.read_index_name);
        if self.graph.nodes.contains_key(&read_enable_id) {
            let and_id = format!("{}_with_rd_en", current_signal);
            self.create_and_node(&and_id, &current_signal, &read_enable_id);
            current_signal = and_id;
            log::info!("  Gated with read enable: {}", read_enable_id);
        }

        // Connect to stall controller
        self.connect_to_stall_controller(&current_signal);

        log::info!("  Created stall logic: {}", current_signal);
        true
    }

    fn create_and_node(&mut self, and_id: &str, left_id: &str, right_id: &str) {
        let mut data: HashMap<String, Value> = HashMap::new();
        data.insert("type".into(), json!("operation"));
        data.insert("operator".into(), json!("&&"));
        data.insert("name".into(), json!(and_id));
        data.insert("bit_width".into(), json!(1));
        let node = Node::new(Some(and_id.into()), Some(data), false, false, None, false, None, None, false, false, 0, false, true, None, None);
        self.graph.add_node(node);

        let mut e1d: HashMap<String, Value> = HashMap::new();
        e1d.insert("type".into(), json!("left_operand"));
        e1d.insert("position".into(), json!("left"));
        let e1 = Edge::new(left_id.into(), and_id.into(), None, Some(e1d));
        self.graph.add_edge(e1);

        let mut e2d: HashMap<String, Value> = HashMap::new();
        e2d.insert("type".into(), json!("right_operand"));
        e2d.insert("position".into(), json!("right"));
        let e2 = Edge::new(right_id.into(), and_id.into(), None, Some(e2d));
        self.graph.add_edge(e2);
    }

    /// Find pipelined version of write index at the write location.
    fn find_pipelined_index_at_write(&self, hazard: &DetectedHazard) -> Option<String> {
        let write_node = self.graph.nodes.get(&hazard.write_access_node_id)?;
        for eid in &write_node.incoming_edges {
            if let Some(edge) = self.graph.edges.get(eid) {
                let et = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                if (et == "array_index" || et == "write_address") && edge.source != hazard.resource {
                    // Check if reachable from original
                    if self.is_pipelined_version_of(&edge.source, &hazard.write_index_node_id) {
                        return Some(edge.source.clone());
                    }
                }
            }
        }
        None
    }

    fn is_pipelined_version_of(&self, candidate: &str, original: &str) -> bool {
        if candidate == original {
            return true;
        }
        if let Some(node) = self.graph.nodes.get(candidate) {
            if node.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_register") {
                for eid in &node.incoming_edges {
                    if let Some(edge) = self.graph.edges.get(eid) {
                        if edge.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_input") {
                            if self.is_pipelined_version_of(&edge.source, original) {
                                return true;
                            }
                        }
                    }
                }
            }
        }
        false
    }

    /// Find write enable signal at the appropriate pipeline stage.
    fn find_stage_write_enable(&self, hazard: &DetectedHazard, actual_write_idx: &str) -> Option<String> {
        // Look for combined_write_enable on write access node
        let write_node = self.graph.nodes.get(&hazard.write_access_node_id)?;
        let default_we = format!("{}_write_enable", hazard.resource);
        let combined_we = write_node.data.get("combined_write_enable")
            .and_then(|v| v.as_str())
            .unwrap_or(&default_we);

        let target_depth = count_pipe_depth(actual_write_idx);

        // Find the write enable node and its predecessors
        if let Some(we_node) = self.graph.nodes.get(combined_we) {
            // Get predecessors
            let mut predecessors: Vec<String> = Vec::new();
            for eid in &we_node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(eid) {
                    let src_id = &edge.source;
                    if !src_id.to_lowercase().contains("valid") {
                        predecessors.push(self.extract_core_name(src_id));
                    }
                }
            }

            // Find pipelined versions at target depth
            let mut stage_enables: Vec<String> = Vec::new();
            for pred_base in &predecessors {
                let mut sorted_ids: Vec<&String> = self.graph.nodes.keys().collect();
                sorted_ids.sort();
                for node_id in sorted_ids {
                    let node = &self.graph.nodes[node_id];
                    if node.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_register") {
                        if node_id.contains(pred_base) && count_pipe_depth(node_id) == target_depth {
                            stage_enables.push(node_id.clone());
                            break;
                        }
                    }
                }
            }

            if !stage_enables.is_empty() {
                if stage_enables.len() == 1 {
                    return Some(stage_enables[0].clone());
                }
                // TODO: OR multiple enables together
                return Some(stage_enables[0].clone());
            }

            // Fallback: look for valid-gated version
            let gated = format!("{}_valid_gated", combined_we);
            if self.graph.nodes.contains_key(&gated) {
                return Some(gated);
            }
            if self.graph.nodes.contains_key(combined_we) {
                return Some(combined_we.to_string());
            }
        }

        // Fallback: look for rd_noteq_0 pipeline register at the same stage.
        // Extract stage name from the actual write index (e.g. PIPE_Memory_... -> Memory)
        if actual_write_idx.starts_with("PIPE_") {
            let stage_name = actual_write_idx.strip_prefix("PIPE_")
                .and_then(|s| s.split('_').next())
                .unwrap_or("");
            // Search for a pipeline register containing "rd_noteq_0" at this stage
            for (node_id, node) in &self.graph.nodes {
                if node.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_register")
                    && node_id.starts_with(&format!("PIPE_{}_", stage_name))
                    && node_id.contains("rd_noteq_0")
                {
                    log::info!("  Found write enable at stage {}: {}", stage_name, node_id);
                    return Some(node_id.clone());
                }
            }
        }

        None
    }

    fn extract_core_name(&self, node_id: &str) -> String {
        let mut core = node_id.to_string();
        while core.starts_with("PIPE_") {
            if let Some(rest) = core.splitn(3, '_').nth(2) {
                core = rest.to_string();
            } else {
                break;
            }
        }
        while core.ends_with("_PIPE") {
            core = core[..core.len() - 5].to_string();
        }
        core
    }

    /// Connect stall signal to the stall controller (or create one).
    fn connect_to_stall_controller(&mut self, stall_signal_id: &str) {
        // Find or create stall controller
        let ctrl_id: String = self.graph.nodes.iter()
            .find(|(nid, n)| {
                nid.contains("stall_ctrl") &&
                n.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_stall_controller")
            })
            .map(|(nid, _)| nid.clone())
            .unwrap_or_else(|| {
                // Create stall controller — find register-read stage name structurally
                let decode_stage = self.graph.nodes.keys()
                    .find(|nid| nid.starts_with("PIPE_") && nid.ends_with("_valid_PIPE")
                        && nid["PIPE_".len()..nid.len() - "_valid_PIPE".len()].contains("Decode"))
                    .map(|nid| nid["PIPE_".len()..nid.len() - "_valid_PIPE".len()].to_string())
                    .unwrap_or_else(|| "Decode".to_string());
                let id = format!("PIPE_{}_stall_ctrl", decode_stage);
                hardware_builders::create_or_get_stall_controller(
                    self.graph, &id, &decode_stage, "PIPE",
                );
                id
            });

        // Connect stall signal to controller
        let mut edge_data: HashMap<String, Value> = HashMap::new();
        edge_data.insert("type".into(), json!("stall_condition"));
        edge_data.insert("pipeline_component".into(), json!(true));
        let edge = Edge::new(stall_signal_id.into(), ctrl_id, None, Some(edge_data));
        self.graph.add_edge(edge);
    }

    // =====================================================================
    // Bypass / Forwarding Resolution
    // =====================================================================

    /// Resolve a hazard by adding bypass/forwarding logic.
    fn resolve_with_bypassing(&mut self, hazard: &DetectedHazard) -> bool {
        log::info!("Resolving with BYPASS: RAW on {} ({}=={}) s{} vs s{}",
            hazard.resource, hazard.write_index_name, hazard.read_index_name,
            hazard.write_stage, hazard.read_stage);

        // Check if this hazard is at the canonical read/write stage pair.
        // Without write_read_fwd, the RF write and read happen at the same posedge
        // and the read gets the stale value - must fall back to stalling.
        let read_time = self.graph.nodes.get(&hazard.read_access_node_id)
            .and_then(|n| n.pipe_time.or(n.uarch_time));
        let write_time = self.graph.nodes.get(&hazard.write_access_node_id)
            .and_then(|n| n.pipe_time.or(n.uarch_time));
        if let (Some(rt), Some(wt)) = (read_time, write_time) {
            if hazard.read_stage == rt && hazard.write_stage == wt {
                let has_write_read_fwd = self.graph.nodes.get(&hazard.resource)
                    .and_then(|n| n.data.get("write_read_fwd"))
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false);
                if !has_write_read_fwd {
                    log::info!("  Hazard at canonical read/write pair without write_read_fwd - using stalling");
                    return self.resolve_with_stalling(hazard);
                }
                // With write_read_fwd, hardware handles transparent forwarding
                log::info!("  Skipping - {} has write_read_fwd (hardware handles same-cycle forwarding)", hazard.resource);
                return true;
            }
        }

        // Distance 1 hazards can't be forwarded - result not ready yet
        if hazard.get_forwarding_distance() <= 1 {
            log::info!("  Distance {} hazard, using stalling (result not ready)",
                hazard.get_forwarding_distance());
            return self.resolve_with_stalling(hazard);
        }

        let distance = hazard.get_forwarding_distance();
        log::info!("  Implementing forwarding for distance {} hazard", distance);

        let read_index_name = hazard.read_index_name.clone();
        let mux_id = format!("bypass_mux_{}", read_index_name);

        // Find or create bypass mux for this read index
        if !self.bypass_muxes.contains_key(&mux_id) {
            if !self.create_bypass_mux(hazard, &mux_id) {
                log::info!("  Could not create bypass mux, falling back to stalling");
                return self.resolve_with_stalling(hazard);
            }
        }

        // Determine forwarding source stage
        let stage_name = match self.determine_forwarding_stage(hazard) {
            Some(s) => s,
            None => {
                log::info!("  Could not determine forwarding stage, falling back to stalling");
                return self.resolve_with_stalling(hazard);
            }
        };
        log::info!("  Forwarding from stage: {} (distance={})", stage_name, distance);

        // Find forwarding value at this stage
        let forward_value_id = if self.is_final_stage(&stage_name) {
            // Final stage: use rf_write_data_mux directly
            if self.graph.nodes.contains_key("rf_write_data_mux") {
                "rf_write_data_mux".to_string()
            } else {
                log::info!("  Could not find rf_write_data_mux, falling back to stalling");
                return self.resolve_with_stalling(hazard);
            }
        } else {
            // Intermediate stage: create one-hot forward data mux
            match self.find_or_create_forward_data_mux(&stage_name) {
                Some(id) => id,
                None => {
                    log::info!("  Could not create forward data mux, falling back to stalling");
                    return self.resolve_with_stalling(hazard);
                }
            }
        };

        // Create forwarding condition
        let forward_cond_id = match self.create_forwarding_condition(hazard, &stage_name) {
            Some(id) => id,
            None => {
                log::info!("  Could not create forwarding condition, falling back to stalling");
                return self.resolve_with_stalling(hazard);
            }
        };

        // Add forwarding input to bypass mux
        self.add_forwarding_to_bypass_mux(&mux_id, &forward_value_id, &forward_cond_id, &stage_name);

        log::info!("  Added forwarding from {} (distance {})", stage_name, distance);
        true
    }

    /// Determine which stage to forward from based on the hazard.
    fn determine_forwarding_stage(&self, hazard: &DetectedHazard) -> Option<String> {
        if !hazard.write_stage_name.is_empty() {
            return Some(hazard.write_stage_name.clone());
        }
        if let Some(ref config) = self.pipeline_config {
            let stage_idx = hazard.write_stage as usize;
            if stage_idx < config.stage_names.len() {
                return Some(config.stage_names[stage_idx].clone());
            }
        }
        None
    }

    /// Check if a stage is the final pipeline stage.
    fn is_final_stage(&self, stage_name: &str) -> bool {
        if let Some(ref config) = self.pipeline_config {
            if let Some(last) = config.stage_names.last() {
                return last == stage_name;
            }
        }
        stage_name == "Writeback" || stage_name == "MemoryWriteback"
            || stage_name == "ExecuteMemoryWriteback"
    }

    /// Get numeric stage index for a stage name.
    fn get_stage_index(&self, stage_name: &str) -> Option<usize> {
        if let Some(ref config) = self.pipeline_config {
            return config.get_stage_index(stage_name);
        }
        let standard = ["Fetch", "Decode", "Execute", "Memory", "Writeback"];
        standard.iter().position(|&s| s == stage_name)
    }

    /// Get the pipeline stage name for a node based on its pipe_time.
    fn get_node_stage(&self, node_id: &str) -> Option<String> {
        let node = self.graph.nodes.get(node_id)?;
        let ptime = node.pipe_time.or(node.uarch_time)?;
        let config = self.pipeline_config.as_ref()?;
        let idx = ptime as usize;
        config.get_stage_name(idx).map(|s| s.to_string())
    }

    /// Create a bypass (priority) mux for a read index, inserting it between
    /// the pipelined RF read and its consumers.
    fn create_bypass_mux(&mut self, hazard: &DetectedHazard, mux_id: &str) -> bool {
        let read_index_name = &hazard.read_index_name;

        // Find pipelined RF read: rf[rs1]_rd -> pipeline_input -> PIPE_Execute_rf_rs1_rd_PIPE
        let pipelined_rf_read_id = {
            let mut found: Option<String> = None;

            // Try following pipeline_input edge from read access node
            if let Some(read_node) = self.graph.nodes.get(&hazard.read_access_node_id) {
                for eid in &read_node.outgoing_edges {
                    if let Some(edge) = self.graph.edges.get(eid) {
                        if edge.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_input") {
                            found = Some(edge.target.clone());
                            break;
                        }
                    }
                }
            }

            // Fallback: search by pattern
            if found.is_none() {
                let pattern = format!("rf_{}_rd", read_index_name);
                let mut sorted_ids: Vec<&String> = self.graph.nodes.keys().collect();
                sorted_ids.sort();
                for nid in sorted_ids {
                    if nid.contains(&pattern) && nid.contains("PIPE") && nid.contains("Execute") {
                        found = Some(nid.clone());
                        break;
                    }
                }
            }

            match found {
                Some(id) => id,
                None => {
                    log::info!("  Could not find pipelined RF read for {}", read_index_name);
                    return false;
                }
            }
        };

        // Find all consumers of the pipelined RF read
        let consumers: Vec<(String, String, HashMap<String, Value>)> = {
            let node = match self.graph.nodes.get(&pipelined_rf_read_id) {
                Some(n) => n,
                None => return false,
            };

            let mut result = Vec::new();
            for eid in &node.outgoing_edges {
                if let Some(edge) = self.graph.edges.get(eid) {
                    let et = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                    if et == "assignment" || et == "mux_input" || et == "bit_access" {
                        result.push((eid.clone(), edge.target.clone(), edge.data.clone()));
                    }
                }
            }
            result
        };

        if consumers.is_empty() {
            log::info!("  No consumers found for {}", pipelined_rf_read_id);
            return false;
        }

        log::info!("  Found {} consumers of {}: {:?}",
            consumers.len(), pipelined_rf_read_id,
            consumers.iter().map(|(_, t, _)| t.as_str()).collect::<Vec<_>>());

        // Get data width and timing from pipelined RF read
        let data_width = self.graph.nodes.get(&pipelined_rf_read_id)
            .and_then(|n| n.data.get("bit_width"))
            .and_then(|v| v.as_i64())
            .unwrap_or(32);
        let pipe_time = self.graph.nodes.get(&pipelined_rf_read_id)
            .and_then(|n| n.pipe_time);
        let uarch_time = self.graph.nodes.get(&pipelined_rf_read_id)
            .and_then(|n| n.uarch_time);

        // Create bypass mux node (priority_select: first matching condition wins)
        let mut mux_data: HashMap<String, Value> = HashMap::new();
        mux_data.insert("type".into(), json!("multiplexer"));
        mux_data.insert("name".into(), json!(mux_id));
        mux_data.insert("display_name".into(),
            json!(format!("Bypass Mux for {}", read_index_name)));
        mux_data.insert("num_inputs".into(), json!(0));
        mux_data.insert("operation".into(), json!("priority_select"));
        mux_data.insert("bit_width".into(), json!(data_width));
        mux_data.insert("data_width".into(), json!(data_width));
        mux_data.insert("output_width".into(), json!(data_width));
        mux_data.insert("has_default".into(), json!(true));

        let mux_node = Node::new(
            Some(mux_id.to_string()), Some(mux_data),
            false, false, None, false, uarch_time, pipe_time,
            false, false, 0, false, true, None, None,
        );
        self.graph.add_node(mux_node);

        // Remove edges from pipelined_rf_read to consumers
        for (eid, _, _) in &consumers {
            self.graph.remove_edge(eid);
        }

        // Connect pipelined_rf_read -> bypass_mux as default input
        let mut default_data: HashMap<String, Value> = HashMap::new();
        default_data.insert("type".into(), json!("mux_default_input"));
        default_data.insert("label".into(), json!("normal"));
        let default_edge = Edge::new(
            pipelined_rf_read_id.clone(), mux_id.to_string(), None, Some(default_data),
        );
        self.graph.add_edge(default_edge);

        // Connect bypass_mux -> all consumers (preserving original edge types)
        for (_, target_id, orig_data) in &consumers {
            let output_edge = Edge::new(
                mux_id.to_string(), target_id.clone(), None, Some(orig_data.clone()),
            );
            self.graph.add_edge(output_edge);
            log::info!("    Connected bypass mux to consumer: {}", target_id);
        }

        self.bypass_muxes.insert(
            mux_id.to_string(),
            (mux_id.to_string(), hazard.resource.clone(), hazard.read_index_name.clone()),
        );
        log::info!("  Created bypass mux: {}", mux_id);
        true
    }

    /// Find or create a one-hot forwarding data mux at a pipeline stage.
    /// This mux selects from all ALU results available at that stage.
    fn find_or_create_forward_data_mux(&mut self, stage_name: &str) -> Option<String> {
        let mux_id = format!("forward_data_{}", stage_name);

        // Already created?
        if self.graph.nodes.contains_key(&mux_id) {
            return Some(mux_id);
        }

        // Get one-hot inputs from rf_write_data_mux
        if !self.graph.nodes.contains_key("rf_write_data_mux") {
            log::info!("    Could not find rf_write_data_mux");
            return None;
        }
        let mux_inputs = self.get_one_hot_mux_inputs("rf_write_data_mux");
        if mux_inputs.is_empty() {
            log::info!("    No inputs found in rf_write_data_mux");
            return None;
        }

        let target_stage_idx = self.get_stage_index(stage_name)?;

        // Find values computed BEFORE the target stage (available for forwarding)
        let mut result_nodes: Vec<(String, String, usize)> = Vec::new(); // (data_at_stage, enable_at_stage, orig_idx)

        for (data_node_id, enable_node_id, mux_idx) in &mux_inputs {
            let (_, compute_stage) = self.trace_back_to_compute_source(data_node_id);
            let compute_stage_idx = compute_stage
                .as_ref()
                .and_then(|s| self.get_stage_index(s));

            if let Some(cs_idx) = compute_stage_idx {
                if cs_idx < target_stage_idx {
                    let data_at_stage = self.find_pipelined_at_stage(data_node_id, stage_name);
                    let enable_at_stage = self.find_pipelined_at_stage(enable_node_id, stage_name);

                    if let (Some(das), Some(eas)) = (data_at_stage, enable_at_stage) {
                        result_nodes.push((das, eas, *mux_idx));
                    }
                }
            }
        }

        if result_nodes.is_empty() {
            log::info!("    No forwardable values at stage {}", stage_name);
            return None;
        }

        // Infer data width from first result node
        let data_width = result_nodes.first()
            .and_then(|(nid, _, _)| self.graph.nodes.get(nid))
            .and_then(|n| n.data.get("bit_width"))
            .and_then(|v| v.as_i64())
            .unwrap_or(32);

        // Get timing from valid signal at target stage
        let valid_id = format!("PIPE_{}_valid_PIPE", stage_name);
        let mux_pipe_time = self.graph.nodes.get(&valid_id).and_then(|n| n.pipe_time);
        let mux_uarch_time = self.graph.nodes.get(&valid_id).and_then(|n| n.uarch_time);

        // Create the one-hot forward data mux
        let num = result_nodes.len();
        let mut mux_data: HashMap<String, Value> = HashMap::new();
        mux_data.insert("type".into(), json!("multiplexer"));
        mux_data.insert("name".into(), json!(&mux_id));
        mux_data.insert("display_name".into(),
            json!(format!("Forward Data Mux ({})", stage_name)));
        mux_data.insert("num_inputs".into(), json!(num));
        mux_data.insert("operation".into(), json!("one_hot_select"));
        mux_data.insert("bit_width".into(), json!(data_width));
        mux_data.insert("data_width".into(), json!(data_width));
        mux_data.insert("output_width".into(), json!(data_width));
        mux_data.insert("default_value".into(), json!(format!("{}'b0", data_width)));

        let mux_node = Node::new(
            Some(mux_id.clone()), Some(mux_data),
            false, false, None, false, mux_uarch_time, mux_pipe_time,
            false, false, 0, false, true, None, None,
        );
        self.graph.add_node(mux_node);

        // Connect inputs
        for (i, (data_id, enable_id, _)) in result_nodes.iter().enumerate() {
            let mut d_edge: HashMap<String, Value> = HashMap::new();
            d_edge.insert("type".into(), json!("mux_input"));
            d_edge.insert("input_index".into(), json!(i));
            self.graph.add_edge(Edge::new(
                data_id.clone(), mux_id.clone(), None, Some(d_edge),
            ));

            let mut s_edge: HashMap<String, Value> = HashMap::new();
            s_edge.insert("type".into(), json!("mux_select"));
            s_edge.insert("select_index".into(), json!(i));
            self.graph.add_edge(Edge::new(
                enable_id.clone(), mux_id.clone(), None, Some(s_edge),
            ));
        }

        log::info!("    Created forwarding mux {} with {} inputs", mux_id, num);
        Some(mux_id)
    }

    /// Create a forwarding condition for a hazard at a given stage.
    /// Returns the final condition signal ID.
    /// Chain: comparator -> AND write_enable -> AND read_enable -> AND valid
    fn create_forwarding_condition(
        &mut self, hazard: &DetectedHazard, stage_name: &str,
    ) -> Option<String> {
        // Find pipelined write address (rd) at target stage
        let rd_at_stage = self.find_rd_at_stage(hazard, stage_name)?;

        // Find pipelined read index (rs1/rs2) at Execute
        let pipelined_rs = self.find_pipelined_read_index(hazard)?;

        // Create comparator: rd_at_stage == pipelined_rs
        let cmp_id = format!("fwd_cmp_{}_{}", stage_name, hazard.read_index_name);

        hardware_builders::create_index_comparator(
            self.graph, &cmp_id, &rd_at_stage, &pipelined_rs, "==",
            Some(&format!("Forward Compare ({})", stage_name)),
            None,
        );

        log::info!("    Comparator: {} == {}", rd_at_stage, pipelined_rs);

        let mut current_signal = cmp_id.clone();

        // AND with write enable at stage
        let write_enable = self.find_stage_write_enable(hazard, &rd_at_stage);
        if let Some(ref we_id) = write_enable {
            if self.graph.nodes.contains_key(we_id) {
                let and_id = format!("{}_we", cmp_id);
                self.create_and_node(&and_id, &current_signal, we_id);
                current_signal = and_id;
            }
        }

        // AND with read enable at Execute stage (structurally: any pipeline register
        // containing the read enable at a stage with "Execute" in its name)
        let read_enable_id = format!("{}_{}_rd_enable", hazard.resource, hazard.read_index_name);
        let pipelined_re_suffix = format!("_{}_PIPE", read_enable_id);
        let pipelined_re_id: Option<String> = self.graph.nodes.keys()
            .find(|nid| nid.starts_with("PIPE_") && nid.ends_with(&pipelined_re_suffix) && {
                let stage = &nid["PIPE_".len()..nid.len() - pipelined_re_suffix.len()];
                stage.contains("Execute")
            })
            .cloned();
        if let Some(ref pipelined_re_id) = pipelined_re_id {
            let and_id = format!("{}_rd_en", cmp_id);
            self.create_and_node(&and_id, &current_signal, pipelined_re_id);
            current_signal = and_id;
            log::info!("    Added read enable gating: {}", pipelined_re_id);
        } else {
            // Try searching by pattern
            let mut found_re: Option<String> = None;
            let mut sorted: Vec<&String> = self.graph.nodes.keys().collect();
            sorted.sort();
            for nid in sorted {
                if nid.contains("Execute") && nid.contains(&read_enable_id) && nid.ends_with("PIPE") {
                    found_re = Some(nid.clone());
                    break;
                }
            }
            if let Some(ref re_id) = found_re {
                let and_id = format!("{}_rd_en", cmp_id);
                self.create_and_node(&and_id, &current_signal, re_id);
                current_signal = and_id;
                log::info!("    Added read enable gating (pattern): {}", re_id);
            }
        }

        // AND with stage valid
        let valid_id = format!("PIPE_{}_valid_PIPE", stage_name);
        if self.graph.nodes.contains_key(&valid_id) {
            let and_id = format!("{}_valid", cmp_id);
            self.create_and_node(&and_id, &current_signal, &valid_id);
            current_signal = and_id;
        }

        Some(current_signal)
    }

    /// Find pipelined write address (rd) at a specific forwarding stage.
    fn find_rd_at_stage(&self, hazard: &DetectedHazard, stage_name: &str) -> Option<String> {
        let core_write_index = self.extract_core_name(&hazard.write_index_node_id);

        let mut sorted_ids: Vec<&String> = self.graph.nodes.keys().collect();
        sorted_ids.sort();

        // Primary: match by pipe_time stage and core name
        for node_id in &sorted_ids {
            let node = &self.graph.nodes[*node_id];
            if node.data.get("type").and_then(|v| v.as_str()) != Some("pipeline_register") {
                continue;
            }
            if self.get_node_stage(node_id) != Some(stage_name.to_string()) {
                continue;
            }
            let node_core = self.extract_core_name(node_id);
            if node_core == core_write_index {
                log::info!("    Found pipelined write addr at {}: {}", stage_name, node_id);
                return Some((*node_id).clone());
            }
        }

        // Fallback: match by stage prefix and rd/rf_write_addr_mux pattern
        let prefix = format!("PIPE_{}_", stage_name);
        for node_id in &sorted_ids {
            if !node_id.starts_with(&prefix) || !node_id.ends_with("PIPE") {
                continue;
            }
            let node = &self.graph.nodes[*node_id];
            if node.data.get("type").and_then(|v| v.as_str()) != Some("pipeline_register") {
                continue;
            }
            let core = self.extract_core_name(node_id);
            if (core == "rd" || core == "rf_write_addr_mux")
                && !node_id.contains("noteq")
                && !node_id.contains("ne_0")
                && !node_id.contains("enable")
            {
                log::info!("    Found pipelined write addr (fallback): {}", node_id);
                return Some((*node_id).clone());
            }
        }

        log::info!("    Could not find pipelined write addr at stage {}", stage_name);
        None
    }

    /// Find pipelined read index (rs1/rs2) at Execute stage.
    fn find_pipelined_read_index(&mut self, hazard: &DetectedHazard) -> Option<String> {
        let rs_index_name = &hazard.read_index_name;

        // Forward trace from original read index node
        if let Some(node) = self.graph.nodes.get(&hazard.read_index_node_id) {
            let outgoing: Vec<String> = node.outgoing_edges.iter().cloned().collect();
            for eid in &outgoing {
                if let Some(edge) = self.graph.edges.get(eid) {
                    if edge.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_input") {
                        let target = edge.target.clone();
                        if let Some(tn) = self.graph.nodes.get(&target) {
                            if tn.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_register")
                                && target.contains("Execute")
                            {
                                log::info!("    Found pipelined rs index: {}", target);
                                return Some(target);
                            }
                        }
                    }
                }
            }
        }

        // Pattern search
        let mut sorted_ids: Vec<String> = self.graph.nodes.keys().cloned().collect();
        sorted_ids.sort();
        for node_id in &sorted_ids {
            if node_id.contains("Execute") && node_id.ends_with("PIPE") {
                let node_core = self.extract_core_name(node_id);
                if node_core == *rs_index_name {
                    log::info!("    Found pipelined rs index via pattern: {}", node_id);
                    return Some(node_id.clone());
                }
            }
        }

        // Create pipelined version if not found — derive Execute stage name structurally
        let execute_stage = self.graph.nodes.keys()
            .find(|nid| nid.starts_with("PIPE_") && nid.ends_with("_valid_PIPE")
                && nid["PIPE_".len()..nid.len() - "_valid_PIPE".len()].contains("Execute"))
            .map(|nid| nid["PIPE_".len()..nid.len() - "_valid_PIPE".len()].to_string())
            .unwrap_or_else(|| "Execute".to_string());
        let pipelined_id = format!("PIPE_{}_{}_PIPE", execute_stage, rs_index_name);
        if !self.graph.nodes.contains_key(&pipelined_id) {
            let bit_width = self.graph.nodes.get(&hazard.read_index_node_id)
                .and_then(|n| n.data.get("bit_width"))
                .and_then(|v| v.as_i64())
                .unwrap_or(5);

            let mut data: HashMap<String, Value> = HashMap::new();
            data.insert("type".into(), json!("pipeline_register"));
            data.insert("name".into(), json!(&pipelined_id));
            data.insert("bit_width".into(), json!(bit_width));
            data.insert("pipeline_component".into(), json!(true));

            let node = Node::new(
                Some(pipelined_id.clone()), Some(data),
                false, false, None, false, Some(2), Some(2),
                false, false, 0, false, true, None, None,
            );
            self.graph.add_node(node);

            let mut ed: HashMap<String, Value> = HashMap::new();
            ed.insert("type".into(), json!("pipeline_input"));
            ed.insert("pipeline_component".into(), json!(true));
            let edge = Edge::new(
                hazard.read_index_node_id.clone(), pipelined_id.clone(), None, Some(ed),
            );
            self.graph.add_edge(edge);
            log::info!("    Created pipelined read index: {}", pipelined_id);
        }

        Some(pipelined_id)
    }

    /// Add a forwarding input to an existing bypass mux.
    fn add_forwarding_to_bypass_mux(
        &mut self, mux_id: &str, forward_value_id: &str,
        forward_cond_id: &str, stage_name: &str,
    ) {
        let num_inputs = self.graph.nodes.get(mux_id)
            .and_then(|n| n.data.get("num_inputs"))
            .and_then(|v| v.as_i64())
            .unwrap_or(0) as usize;

        // Update num_inputs
        if let Some(node) = self.graph.nodes.get_mut(mux_id) {
            node.data.insert("num_inputs".into(), json!(num_inputs + 1));
        }

        // Connect forwarding value
        let mut fwd_data: HashMap<String, Value> = HashMap::new();
        fwd_data.insert("type".into(), json!("mux_input"));
        fwd_data.insert("input_index".into(), json!(num_inputs));
        fwd_data.insert("label".into(), json!(format!("forward_{}", stage_name)));
        self.graph.add_edge(Edge::new(
            forward_value_id.to_string(), mux_id.to_string(), None, Some(fwd_data),
        ));

        // Connect forwarding condition as select
        let mut sel_data: HashMap<String, Value> = HashMap::new();
        sel_data.insert("type".into(), json!("mux_select"));
        sel_data.insert("select_index".into(), json!(num_inputs));
        self.graph.add_edge(Edge::new(
            forward_cond_id.to_string(), mux_id.to_string(), None, Some(sel_data),
        ));

        log::info!("  Added forwarding input {} from {} to {}", num_inputs, stage_name, mux_id);
    }

    // =====================================================================
    // Bypass Helper Methods
    // =====================================================================

    /// Extract one-hot mux inputs: (data_node_id, enable_node_id, index).
    fn get_one_hot_mux_inputs(&self, mux_id: &str) -> Vec<(String, String, usize)> {
        let node = match self.graph.nodes.get(mux_id) {
            Some(n) => n,
            None => return Vec::new(),
        };

        let mut data_by_index: HashMap<usize, String> = HashMap::new();
        let mut select_by_index: HashMap<usize, String> = HashMap::new();

        for eid in &node.incoming_edges {
            if let Some(edge) = self.graph.edges.get(eid) {
                let et = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                if et == "mux_input" {
                    let idx = edge.data.get("input_index")
                        .and_then(|v| v.as_u64()).unwrap_or(0) as usize;
                    data_by_index.insert(idx, edge.source.clone());
                } else if et == "mux_select" {
                    let idx = edge.data.get("select_index")
                        .and_then(|v| v.as_u64()).unwrap_or(0) as usize;
                    select_by_index.insert(idx, edge.source.clone());
                }
            }
        }

        let mut result = Vec::new();
        let mut indices: Vec<usize> = data_by_index.keys().cloned().collect();
        indices.sort();
        for idx in indices {
            if let (Some(d), Some(s)) = (data_by_index.get(&idx), select_by_index.get(&idx)) {
                result.push((d.clone(), s.clone(), idx));
            }
        }
        result
    }

    /// Trace backward from a node to find the compute source and its stage.
    fn trace_back_to_compute_source(&self, node_id: &str) -> (String, Option<String>) {
        let mut visited: HashSet<String> = HashSet::new();
        self.trace_back_recursive(node_id, &mut visited)
    }

    fn trace_back_recursive(
        &self, node_id: &str, visited: &mut HashSet<String>,
    ) -> (String, Option<String>) {
        if visited.contains(node_id) {
            return (node_id.to_string(), self.get_node_stage(node_id));
        }
        visited.insert(node_id.to_string());

        let node = match self.graph.nodes.get(node_id) {
            Some(n) => n,
            None => return (node_id.to_string(), None),
        };

        let node_type = node.data.get("type").and_then(|v| v.as_str()).unwrap_or("");

        // Pipeline register: trace through pipeline_input
        if node_type == "pipeline_register" {
            for eid in &node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(eid) {
                    if edge.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_input") {
                        return self.trace_back_recursive(&edge.source, visited);
                    }
                }
            }
            return (node_id.to_string(), self.get_node_stage(node_id));
        }

        // Wire/signal: trace through if single assignment source is a pipeline register
        if node_type == "wire" || node_type == "signal" || node_type.is_empty() {
            let mut assignment_sources = Vec::new();
            for eid in &node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(eid) {
                    let et = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                    if et == "assignment" || et == "operand" {
                        assignment_sources.push(edge.source.clone());
                    }
                }
            }
            if assignment_sources.len() == 1 {
                if let Some(src) = self.graph.nodes.get(&assignment_sources[0]) {
                    if src.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_register") {
                        return self.trace_back_recursive(&assignment_sources[0], visited);
                    }
                }
            }
        }

        // Compute source (operation, memory, etc.) or can't trace further
        (node_id.to_string(), self.get_node_stage(node_id))
    }

    /// Find pipelined version of a node at a target stage by tracing backward.
    fn find_pipelined_at_stage(&self, node_id: &str, target_stage: &str) -> Option<String> {
        // Check if node itself is at target stage
        if let Some(stage) = self.get_node_stage(node_id) {
            if stage == target_stage {
                return Some(node_id.to_string());
            }
        }

        let mut current = node_id.to_string();
        let mut visited: HashSet<String> = HashSet::new();

        loop {
            if visited.contains(&current) {
                break;
            }
            visited.insert(current.clone());

            if let Some(stage) = self.get_node_stage(&current) {
                if stage == target_stage {
                    return Some(current);
                }
            }

            let node = match self.graph.nodes.get(&current) {
                Some(n) => n,
                None => break,
            };

            let node_type = node.data.get("type").and_then(|v| v.as_str()).unwrap_or("");

            if node_type == "pipeline_register" {
                let mut found = false;
                for eid in &node.incoming_edges {
                    if let Some(edge) = self.graph.edges.get(eid) {
                        if edge.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_input") {
                            current = edge.source.clone();
                            found = true;
                            break;
                        }
                    }
                }
                if !found { break; }
            } else {
                // Non-pipeline: look for incoming assignment from pipeline register
                let mut found = false;
                for eid in &node.incoming_edges {
                    if let Some(edge) = self.graph.edges.get(eid) {
                        let et = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                        if et == "assignment" || et == "operand" {
                            if let Some(src) = self.graph.nodes.get(&edge.source) {
                                if src.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_register") {
                                    current = edge.source.clone();
                                    found = true;
                                    break;
                                }
                            }
                        }
                    }
                }
                if !found { break; }
            }
        }

        None
    }

    /// Add Writeback forwarding to all bypass muxes.
    /// This is called AFTER all hazards are resolved. It adds a lower-priority
    /// forwarding path from the Writeback stage (rf_write_data_mux) to each
    /// bypass mux, so that instructions at Execute can get the correct value
    /// when their producer has moved from Memory to Writeback.
    fn add_rf_write_forwarding(&mut self) {
        log::info!("  Adding memory write forwarding...");

        // Find the final pipeline stage name
        let final_stage = if let Some(ref config) = self.pipeline_config {
            config.stage_names.last().cloned().unwrap_or_else(|| "Writeback".to_string())
        } else {
            "Writeback".to_string()
        };

        // Collect bypass mux info (avoid borrow issues)
        let mux_infos: Vec<(String, String, String)> = self.bypass_muxes.values().cloned().collect();

        for (mux_id, resource, read_index_name) in &mux_infos {
            // Only handle register file resources
            if resource != "rf" {
                continue;
            }

            // 1. Find rf_write_data_mux (the value being written to RF at Writeback)
            if !self.graph.nodes.contains_key("rf_write_data_mux") {
                log::info!("    Could not find rf_write_data_mux, skipping Writeback forwarding");
                continue;
            }

            // 2. Find pipelined write address (rd) at Writeback
            let rd_at_writeback = {
                let mut found: Option<String> = None;
                let prefix = format!("PIPE_{}_", final_stage);
                let mut sorted_ids: Vec<String> = self.graph.nodes.keys().cloned().collect();
                sorted_ids.sort();
                for node_id in &sorted_ids {
                    if !node_id.starts_with(&prefix) || !node_id.ends_with("PIPE") {
                        continue;
                    }
                    let node = &self.graph.nodes[node_id];
                    if node.data.get("type").and_then(|v| v.as_str()) != Some("pipeline_register") {
                        continue;
                    }
                    let core = self.extract_core_name(node_id);
                    if (core == "rd" || core == "rf_write_addr_mux")
                        && !node_id.contains("noteq")
                        && !node_id.contains("ne_0")
                        && !node_id.contains("enable")
                    {
                        found = Some(node_id.clone());
                        break;
                    }
                }
                match found {
                    Some(id) => id,
                    None => {
                        log::info!("    Could not find rd at {} stage", final_stage);
                        continue;
                    }
                }
            };

            // 3. Find pipelined read index (rs1/rs2) at Execute
            let pipelined_rs = {
                let mut found: Option<String> = None;
                let mut sorted_ids: Vec<String> = self.graph.nodes.keys().cloned().collect();
                sorted_ids.sort();
                for node_id in &sorted_ids {
                    if node_id.contains("Execute") && node_id.ends_with("PIPE") {
                        let core = self.extract_core_name(node_id);
                        if core == *read_index_name {
                            let node = &self.graph.nodes[node_id];
                            if node.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_register") {
                                found = Some(node_id.clone());
                                break;
                            }
                        }
                    }
                }
                match found {
                    Some(id) => id,
                    None => {
                        log::info!("    Could not find pipelined {} at Execute", read_index_name);
                        continue;
                    }
                }
            };

            // 4. Create forwarding condition: compare rd at Writeback with rs at Execute
            let cmp_id = format!("fwd_write_{}_{}_cmp", resource, read_index_name);
            hardware_builders::create_index_comparator(
                self.graph, &cmp_id, &rd_at_writeback, &pipelined_rs, "==",
                Some(&format!("Writeback Forward Compare ({})", read_index_name)),
                None,
            );

            let mut current_signal = cmp_id.clone();

            // 5. AND with write enable at Writeback (rd_noteq_0 && valid)
            // Find rd_noteq_0 at Writeback
            let wb_write_enable = {
                let mut found: Option<String> = None;
                let prefix = format!("PIPE_{}_", final_stage);
                let mut sorted_ids: Vec<String> = self.graph.nodes.keys().cloned().collect();
                sorted_ids.sort();
                for node_id in &sorted_ids {
                    if node_id.starts_with(&prefix) && node_id.ends_with("PIPE") {
                        let core = self.extract_core_name(node_id);
                        if core == "rd_noteq_0" || core == "rd_ne_0"
                            || core == "rf_rd_ne_0_guarded_enable"
                        {
                            found = Some(node_id.clone());
                            break;
                        }
                    }
                }
                found
            };

            if let Some(ref we_id) = wb_write_enable {
                let and_id = format!("fwd_write_{}_{}_valid", resource, read_index_name);
                self.create_and_node(&and_id, &current_signal, we_id);
                current_signal = and_id;
            }

            // AND with Writeback valid
            let valid_id = format!("PIPE_{}_valid_PIPE", final_stage);
            if self.graph.nodes.contains_key(&valid_id) {
                if wb_write_enable.is_some() {
                    // Already have write enable, just AND with valid
                    let and_id = format!("fwd_write_{}_{}_valid_gated", resource, read_index_name);
                    self.create_and_node(&and_id, &current_signal, &valid_id);
                    current_signal = and_id;
                } else {
                    let and_id = format!("fwd_write_{}_{}_valid", resource, read_index_name);
                    self.create_and_node(&and_id, &current_signal, &valid_id);
                    current_signal = and_id;
                }
            }

            // 6. AND with read enable at Execute stage (structural search)
            let read_enable_id = format!("{}_{}_rd_enable", resource, read_index_name);
            let pipelined_re_suffix = format!("_{}_PIPE", read_enable_id);
            let pipelined_re_id: Option<String> = self.graph.nodes.keys()
                .find(|nid| nid.starts_with("PIPE_") && nid.ends_with(&pipelined_re_suffix) && {
                    let stage = &nid["PIPE_".len()..nid.len() - pipelined_re_suffix.len()];
                    stage.contains("Execute")
                })
                .cloned();
            if let Some(ref pipelined_re_id) = pipelined_re_id {
                let and_id = format!("fwd_write_{}_{}_rd_en", resource, read_index_name);
                self.create_and_node(&and_id, &current_signal, pipelined_re_id);
                current_signal = and_id;
                log::info!("    Added read enable gating to Writeback forwarding");
            } else {
                // Try searching by pattern
                let mut found_re: Option<String> = None;
                let sorted: Vec<String> = self.graph.nodes.keys().cloned().collect();
                for nid in &sorted {
                    if nid.contains("Execute") && nid.contains(&read_enable_id) && nid.ends_with("PIPE") {
                        found_re = Some(nid.clone());
                        break;
                    }
                }
                if let Some(ref re_id) = found_re {
                    let and_id = format!("fwd_write_{}_{}_rd_en", resource, read_index_name);
                    self.create_and_node(&and_id, &current_signal, re_id);
                    current_signal = and_id;
                    log::info!("    Added read enable gating to Writeback forwarding");
                }
            }

            // 7. Add to bypass mux as a lower-priority forwarding input
            self.add_forwarding_to_bypass_mux(
                mux_id,
                "rf_write_data_mux",
                &current_signal,
                &final_stage,
            );
            log::info!("    Added rf write forwarding to {}", mux_id);
        }
    }

    /// Add control hazard handling (branch/jump flush).
    pub fn add_control_hazard_handling(
        &mut self,
        branch_conditions: &HashMap<String, String>,
        jump_types: &[String],
        _pc_mux_id: Option<&str>,
    ) {
        log::info!("\n{}", "=".repeat(70));
        log::info!("ADDING CONTROL HAZARD HANDLING (PIPELINE FLUSH)");
        log::info!("{}", "=".repeat(70));

        // Find validity signals and their stage order
        let mut valid_signals: HashMap<String, String> = HashMap::new(); // stage -> node_id
        for (node_id, _) in &self.graph.nodes {
            if node_id.starts_with("PIPE_") && node_id.ends_with("_valid_PIPE") {
                let stage = node_id.replace("PIPE_", "").replace("_valid_PIPE", "");
                valid_signals.insert(stage, node_id.clone());
            }
        }

        // Infer stage order from pipe_time
        let mut stage_order: Vec<(String, i64)> = Vec::new();
        for (stage, vid) in &valid_signals {
            let ptime = self.graph.nodes.get(vid)
                .and_then(|n| n.pipe_time.or(n.uarch_time))
                .unwrap_or(0);
            stage_order.push((stage.clone(), ptime));
        }
        stage_order.sort_by_key(|(_, t)| *t);
        let stage_names: Vec<String> = stage_order.iter().map(|(s, _)| s.clone()).collect();

        log::info!("  Pipeline stage order: {:?}", stage_names);

        // Determine resolution stage (where branches resolve)
        let branch_types: Vec<&String> = branch_conditions.keys().collect();
        let mut resolution_stage: Option<String> = None;

        for stage_name in &stage_names {
            for bt in &branch_types {
                let pipelined_enable = format!("PIPE_{}_{}_enable_PIPE", stage_name, bt);
                if self.graph.nodes.contains_key(&pipelined_enable) {
                    resolution_stage = Some(stage_name.clone());
                    break;
                }
            }
            if resolution_stage.is_some() {
                break;
            }
        }

        if resolution_stage.is_none() && stage_names.len() > 1 {
            resolution_stage = Some(stage_names[1].clone());
        }

        let resolution_stage = match resolution_stage {
            Some(s) => s,
            None => {
                log::info!("  ERROR: Cannot determine resolution stage");
                return;
            }
        };

        log::info!("  Resolution stage: {}", resolution_stage);

        // Find branch and jump enables at resolution stage
        let prefix = format!("PIPE_{}_", resolution_stage);
        let suffix = "_enable_PIPE";

        let mut flush_components: Vec<String> = Vec::new();

        // Jump enables (always flush)
        for jt in jump_types {
            let enable_id = format!("{}{}{}", prefix, jt, suffix);
            if self.graph.nodes.contains_key(&enable_id) {
                flush_components.push(enable_id.clone());
                log::info!("    Flush on: {} (jump always taken)", enable_id);
            } else {
                // Pipeline register doesn't exist yet -- create it so the
                // jump instruction's enable gets flushed at the resolution
                // stage.  This happens when a jump instruction (like JR in
                // MIPS) doesn't have any other consumers in the execute
                // stage, so the pipeline transform never created a register
                // for it.
                let unpipelined_enable = format!("{}_enable", jt);
                if self.graph.nodes.contains_key(&unpipelined_enable) {
                    // Create pipeline register node
                    let mut data: HashMap<String, Value> = HashMap::new();
                    data.insert("type".into(), json!("pipeline_register"));
                    data.insert("name".into(), json!(&enable_id));
                    data.insert("bit_width".into(), json!(1));
                    data.insert("display_name".into(), json!(format!("Pipelined {} enable", jt)));
                    let node = Node::new(
                        Some(enable_id.clone()), Some(data),
                        false, false, None, false, None, None,
                        false, false, 0, false, true, None, None,
                    );
                    self.graph.add_node(node);

                    // Connect unpipelined enable -> pipeline register
                    let mut ed: HashMap<String, Value> = HashMap::new();
                    ed.insert("type".into(), json!("pipeline_input"));
                    let e = Edge::new(unpipelined_enable, enable_id.clone(), None, Some(ed));
                    self.graph.add_edge(e);

                    flush_components.push(enable_id.clone());
                    log::info!("    Flush on: {} (created pipeline register for jump)", enable_id);
                }
            }
        }

        // Branch enables AND condition
        for (bt, cond_name) in branch_conditions {
            let enable_id = format!("{}{}{}", prefix, bt, suffix);
            let cond_id = cond_name.to_string();

            if !self.graph.nodes.contains_key(&enable_id) {
                continue;
            }

            // Create: branch_taken = enable AND condition
            let taken_id = format!("{}_branch_taken_{}", bt, resolution_stage.to_lowercase());
            self.create_and_node(&taken_id, &enable_id, &cond_id);
            flush_components.push(taken_id.clone());
            log::info!("    Flush on: {} (branch taken)", taken_id);
        }

        if flush_components.is_empty() {
            log::info!("  No flush components found");
            return;
        }

        // Gate all flush components with Execute valid to prevent bubbles from triggering flushes
        let valid_id = format!("PIPE_{}_valid_PIPE", resolution_stage);
        if self.graph.nodes.contains_key(&valid_id) {
            let mut gated_components: Vec<String> = Vec::new();
            for comp in &flush_components {
                let gated_id = format!("{}_valid_gated", comp);
                self.create_and_node(&gated_id, comp, &valid_id);
                log::info!("    Valid-gated: {} -> {}", comp, gated_id);
                gated_components.push(gated_id);
            }
            flush_components = gated_components;
        }

        // OR all flush components together
        let flush_id = "control_hazard_flush".to_string();
        if flush_components.len() == 1 {
            // Create alias
            let mut data: HashMap<String, Value> = HashMap::new();
            data.insert("type".into(), json!("var"));
            data.insert("name".into(), json!(&flush_id));
            data.insert("bit_width".into(), json!(1));
            let node = Node::new(Some(flush_id.clone()), Some(data), false, false, None, false, None, None, false, false, 0, false, true, None, None);
            self.graph.add_node(node);
            let mut ed: HashMap<String, Value> = HashMap::new();
            ed.insert("type".into(), json!("assignment"));
            let edge = Edge::new(flush_components[0].clone(), flush_id.clone(), None, Some(ed));
            self.graph.add_edge(edge);
        } else {
            // Build OR chain
            let mut current = flush_components[0].clone();
            for (i, comp) in flush_components[1..].iter().enumerate() {
                let or_id = if i == flush_components.len() - 2 {
                    flush_id.clone()
                } else {
                    format!("control_hazard_flush_or_{}", i)
                };
                let mut data: HashMap<String, Value> = HashMap::new();
                data.insert("type".into(), json!("operation"));
                data.insert("operator".into(), json!("||"));
                data.insert("name".into(), json!(&or_id));
                data.insert("bit_width".into(), json!(1));
                let node = Node::new(Some(or_id.clone()), Some(data), false, false, None, false, None, None, false, false, 0, false, true, None, None);
                self.graph.add_node(node);

                let mut e1d: HashMap<String, Value> = HashMap::new();
                e1d.insert("type".into(), json!("operand"));
                e1d.insert("position".into(), json!("left"));
                let e1 = Edge::new(current.clone(), or_id.clone(), None, Some(e1d));
                self.graph.add_edge(e1);

                let mut e2d: HashMap<String, Value> = HashMap::new();
                e2d.insert("type".into(), json!("operand"));
                e2d.insert("position".into(), json!("right"));
                let e2 = Edge::new(comp.clone(), or_id.clone(), None, Some(e2d));
                self.graph.add_edge(e2);

                current = or_id;
            }
        }

        // Connect flush to validity signals (flush earlier stages when taken)
        let res_idx = stage_names.iter().position(|s| *s == resolution_stage).unwrap_or(0);
        for i in 0..res_idx {
            let stage = &stage_names[i];
            if let Some(valid_id) = valid_signals.get(stage) {
                // Create AND: existing_valid AND NOT flush
                let not_flush_id = "control_hazard_not_flush".to_string();
                if !self.graph.nodes.contains_key(&not_flush_id) {
                    let mut data: HashMap<String, Value> = HashMap::new();
                    data.insert("type".into(), json!("operation"));
                    data.insert("operator".into(), json!("!"));
                    data.insert("name".into(), json!(&not_flush_id));
                    let node = Node::new(Some(not_flush_id.clone()), Some(data), false, false, None, false, None, None, false, false, 0, false, true, None, None);
                    self.graph.add_node(node);
                    let mut ed: HashMap<String, Value> = HashMap::new();
                    ed.insert("type".into(), json!("operand"));
                    let edge = Edge::new(flush_id.clone(), not_flush_id.clone(), None, Some(ed));
                    self.graph.add_edge(edge);
                }

                // Modify validity: valid = old_valid AND NOT flush
                // Find and rewire pipeline_input edge to validity signal
                let incoming: Vec<String> = self.graph.nodes.get(valid_id)
                    .map(|n| n.incoming_edges.iter().cloned().collect())
                    .unwrap_or_default();

                let pipe_input_edge = incoming.iter()
                    .find(|eid| {
                        self.graph.edges.get(*eid)
                            .map(|e| e.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_input"))
                            .unwrap_or(false)
                    })
                    .cloned();

                if let Some(ref old_eid) = pipe_input_edge {
                    let old_source = self.graph.edges.get(old_eid)
                        .map(|e| e.source.clone())
                        .unwrap_or_default();

                    self.graph.remove_edge(old_eid);

                    // Create AND gate
                    let and_id = format!("{}_flush_gated", valid_id);
                    let mut and_data: HashMap<String, Value> = HashMap::new();
                    and_data.insert("type".into(), json!("operation"));
                    and_data.insert("operator".into(), json!("&&"));
                    and_data.insert("name".into(), json!(&and_id));
                    let and_node = Node::new(Some(and_id.clone()), Some(and_data), false, false, None, false, None, None, false, false, 0, false, true, None, None);
                    self.graph.add_node(and_node);

                    // old_source -> AND
                    let mut e1d: HashMap<String, Value> = HashMap::new();
                    e1d.insert("type".into(), json!("left_operand"));
                    e1d.insert("position".into(), json!("left"));
                    let e1 = Edge::new(old_source, and_id.clone(), None, Some(e1d));
                    self.graph.add_edge(e1);

                    // NOT flush -> AND
                    let mut e2d: HashMap<String, Value> = HashMap::new();
                    e2d.insert("type".into(), json!("right_operand"));
                    e2d.insert("position".into(), json!("right"));
                    let e2 = Edge::new(not_flush_id.clone(), and_id.clone(), None, Some(e2d));
                    self.graph.add_edge(e2);

                    // AND -> validity
                    let mut e3d: HashMap<String, Value> = HashMap::new();
                    e3d.insert("type".into(), json!("pipeline_input"));
                    e3d.insert("pipeline_component".into(), json!(true));
                    let e3 = Edge::new(and_id.clone(), valid_id.clone(), None, Some(e3d));
                    self.graph.add_edge(e3);

                    log::info!("  Flush gating: {} = old_valid AND NOT flush", valid_id);
                }
            }
        }

        log::info!("  Control hazard handling added successfully");
    }

    /// Gate write enables with validity signals.
    pub fn gate_write_enables_with_validity(&mut self) {
        log::info!("\n{}", "=".repeat(70));
        log::info!("GATING WRITE ENABLES WITH VALIDITY");
        log::info!("{}", "=".repeat(70));

        // Find ISA state elements to gate
        for state_id in &self.isa_states_to_gate.clone() {
            // Find validity signal at the write stage
            // PC is typically gated at Fetch stage (or the stall controller handles it)
            log::info!("  ISA state to gate: {} (handled by stall controller)", state_id);
        }

        log::info!("  Write enable gating complete");
    }

    /// Automatically detect and add memory latency stalls.
    /// Automatically detect caches and integrate their stall conditions into the pipeline
    /// stall controller. This is the Rust equivalent of Python's _add_automatic_cache_stalls().
    ///
    /// The Rust Verilog generator's stall controller logic collects all edges with
    /// type="stall_condition" targeting the controller and ORs them together. So we simply
    /// add a stall_condition edge from the cache stall signal to the stall controller.
    ///
    /// For data caches (read_write_cache), also integrate into Memory stage stall controller.
    fn add_automatic_cache_stalls(&mut self) {
        log::info!("\n  Checking for caches requiring stall integration...");

        // Find all cache nodes with stall conditions
        let caches: Vec<(String, String, String)> = self.graph.nodes.iter()
            .filter_map(|(nid, n)| {
                let nt = n.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                if nt == "read_only_cache" || nt == "read_write_cache" {
                    if let Some(stall_cond_id) = n.data.get("stall_condition_node").and_then(|v| v.as_str()) {
                        return Some((nid.clone(), stall_cond_id.to_string(), nt.to_string()));
                    }
                }
                None
            })
            .collect();

        if caches.is_empty() {
            log::info!("  No caches with stall conditions found");
            return;
        }

        for (cache_name, stall_cond_id, cache_type) in &caches {
            log::info!("  Processing cache: {} (type: {})", cache_name, cache_type);

            if !self.graph.nodes.contains_key(stall_cond_id) {
                log::info!("    Warning: Stall condition {} not found, skipping", stall_cond_id);
                continue;
            }

            // Find the existing Decode stall controller
            let ctrl_id: Option<String> = self.graph.nodes.iter()
                .find(|(nid, n)| {
                    nid.contains("stall_ctrl") &&
                    n.data.get("type").and_then(|v| v.as_str()) == Some("pipeline_stall_controller")
                })
                .map(|(nid, _)| nid.clone());

            if let Some(ref ctrl_id) = ctrl_id {
                // Check if already connected via stall_condition edge
                let already_connected = self.graph.edges.values().any(|e| {
                    e.target == *ctrl_id && e.source == *stall_cond_id
                        && e.data.get("type").and_then(|v| v.as_str()) == Some("stall_condition")
                });

                if !already_connected {
                    // Add stall_condition edge — the Verilog generator ORs all such edges
                    let mut ed: HashMap<String, Value> = HashMap::new();
                    ed.insert("type".into(), json!("stall_condition"));
                    ed.insert("pipeline_component".into(), json!(true));
                    let edge = Edge::new(stall_cond_id.clone(), ctrl_id.clone(), None, Some(ed));
                    self.graph.add_edge(edge);
                    log::info!("    Connected cache stall {} to {}", stall_cond_id, ctrl_id);
                } else {
                    log::info!("    Cache stall already connected to {}", ctrl_id);
                }

                // For data caches (read_write_cache), also integrate into Memory stage stall controller
                let is_data_cache = cache_type == "read_write_cache";
                // Find or create the Memory-stage umem stall controller structurally
                let mem_stall_ctrl_id = self.graph.nodes.keys()
                    .find(|nid| nid.starts_with("PIPE_") && nid.contains("Memory") && nid.ends_with("_umem_stall_ctrl"))
                    .cloned()
                    .unwrap_or_else(|| {
                        // Derive from memory stage valid signal pattern
                        let mem_stage = self.graph.nodes.keys()
                            .find(|nid| nid.starts_with("PIPE_") && nid.ends_with("_valid_PIPE") && nid["PIPE_".len()..nid.len() - "_valid_PIPE".len()].contains("Memory"))
                            .map(|nid| nid["PIPE_".len()..nid.len() - "_valid_PIPE".len()].to_string())
                            .unwrap_or_else(|| "Memory".to_string());
                        format!("PIPE_{}_umem_stall_ctrl", mem_stage)
                    });
                if is_data_cache {
                    // Create Memory stall controller if it doesn't exist
                    let mem_stage_name = if mem_stall_ctrl_id.starts_with("PIPE_") && mem_stall_ctrl_id.ends_with("_umem_stall_ctrl") {
                        mem_stall_ctrl_id["PIPE_".len()..mem_stall_ctrl_id.len() - "_umem_stall_ctrl".len()].to_string()
                    } else {
                        "Memory".to_string()
                    };
                    if !self.graph.nodes.contains_key(&mem_stall_ctrl_id) {
                        hardware_builders::create_or_get_stall_controller(
                            self.graph, &mem_stall_ctrl_id, &mem_stage_name, "PIPE",
                        );
                        log::info!("    Created Memory stall controller: {}", mem_stall_ctrl_id);
                    }
                    // Add cache stall as another stall_condition to Memory stage controller
                    let mem_already = self.graph.edges.values().any(|e| {
                        e.target == mem_stall_ctrl_id && e.source == *stall_cond_id
                            && e.data.get("type").and_then(|v| v.as_str()) == Some("stall_condition")
                    });
                    if !mem_already {
                        let mut ed: HashMap<String, Value> = HashMap::new();
                        ed.insert("type".into(), json!("stall_condition"));
                        ed.insert("pipeline_component".into(), json!(true));
                        let edge = Edge::new(stall_cond_id.clone(), mem_stall_ctrl_id.clone(), None, Some(ed));
                        self.graph.add_edge(edge);
                        log::info!("    Extended cache stall to Memory stage via {}", mem_stall_ctrl_id);
                    }

                    // Add skip_flush_transform stall edges for Memory/Writeback registers
                    let node_ids: Vec<String> = self.graph.nodes.keys().cloned().collect();
                    let mut registers_gated = 0;
                    for node_id in &node_ids {
                        // Structurally identify pipeline registers at Memory or later stages:
                        // - PIPE_{stage}_valid_PIPE where stage contains Memory or Writeback
                        // - PIPE_{stage}_PIPE_{prev}_ where stage contains Memory or Writeback
                        let should_gate = if node_id.starts_with("PIPE_") {
                            if node_id.ends_with("_valid_PIPE") {
                                let stage = &node_id["PIPE_".len()..node_id.len() - "_valid_PIPE".len()];
                                stage.contains("Memory") || stage.contains("Writeback")
                            } else if let Some(rest) = node_id.strip_prefix("PIPE_") {
                                // Pattern: PIPE_{stage}_PIPE_{prev}_... where stage has Memory/Writeback
                                if let Some(idx) = rest.find("_PIPE_") {
                                    let stage = &rest[..idx];
                                    stage.contains("Memory") || stage.contains("Writeback")
                                } else {
                                    false
                                }
                            } else {
                                false
                            }
                        } else {
                            false
                        };

                        if should_gate {
                            // Check if skip_flush_transform stall edge already exists
                            let has_skip = self.graph.nodes.get(node_id)
                                .map(|n| n.incoming_edges.iter().any(|eid| {
                                    self.graph.edges.get(eid).map(|e| {
                                        e.source == mem_stall_ctrl_id
                                            && e.data.get("type").and_then(|v| v.as_str()) == Some("stall")
                                            && e.data.get("skip_flush_transform").and_then(|v| v.as_bool()).unwrap_or(false)
                                    }).unwrap_or(false)
                                }))
                                .unwrap_or(false);

                            if !has_skip {
                                // Remove existing non-skip stall edges from this controller
                                let edges_to_remove: Vec<String> = self.graph.nodes.get(node_id)
                                    .map(|n| n.incoming_edges.iter().filter(|eid| {
                                        self.graph.edges.get(*eid).map(|e| {
                                            e.source == mem_stall_ctrl_id
                                                && e.data.get("type").and_then(|v| v.as_str()) == Some("stall")
                                                && !e.data.get("skip_flush_transform").and_then(|v| v.as_bool()).unwrap_or(false)
                                        }).unwrap_or(false)
                                    }).cloned().collect())
                                    .unwrap_or_default();

                                for eid in &edges_to_remove {
                                    if let Some(e) = self.graph.edges.get(eid) {
                                        let src = e.source.clone();
                                        let tgt = e.target.clone();
                                        if let Some(n) = self.graph.nodes.get_mut(&src) {
                                            n.outgoing_edges.retain(|x| x != eid);
                                        }
                                        if let Some(n) = self.graph.nodes.get_mut(&tgt) {
                                            n.incoming_edges.retain(|x| x != eid);
                                        }
                                    }
                                    self.graph.edges.remove(eid);
                                }

                                // Add stall edge with skip_flush_transform
                                let mut ed: HashMap<String, Value> = HashMap::new();
                                ed.insert("type".into(), json!("stall"));
                                ed.insert("skip_flush_transform".into(), json!(true));
                                let edge = Edge::new(mem_stall_ctrl_id.clone(), node_id.clone(), None, Some(ed));
                                self.graph.add_edge(edge);
                                registers_gated += 1;
                            }
                        }
                    }
                    if registers_gated > 0 {
                        log::info!("    Added skip_flush_transform stall edges to {} registers from {}", registers_gated, mem_stall_ctrl_id);
                    }
                }
            } else {
                // No stall controller found - add stall edge directly to pc_rd
                if self.graph.nodes.contains_key("pc_rd") {
                    let mut ed: HashMap<String, Value> = HashMap::new();
                    ed.insert("type".into(), json!("stall"));
                    ed.insert("description".into(), json!(format!("Gate PC on {} miss", cache_name)));
                    let edge = Edge::new(stall_cond_id.clone(), "pc_rd".into(), None, Some(ed));
                    self.graph.add_edge(edge);
                    log::info!("    Added cache stall edge to pc_rd (no stall controller found)");
                }
            }
        }
    }

    fn add_automatic_memory_latency_stalls(&mut self) {
        // Find variable-latency memory nodes
        let var_lat_memories: Vec<(String, Option<String>)> = self.graph.nodes.iter()
            .filter(|(_, n)| n.variable_latency)
            .map(|(nid, n)| {
                let complete = n.data.get("complete_signal").and_then(|v| v.as_str()).map(|s| s.to_string());
                (nid.clone(), complete)
            })
            .collect();

        for (mem_id, complete_signal) in &var_lat_memories {
            if let Some(ref cs_id) = complete_signal {
                if self.graph.nodes.contains_key(cs_id) {
                    log::info!("  Memory {} has complete signal: {}", mem_id, cs_id);

                    // Create: stall = access_enable AND NOT complete
                    let access_enable_id = format!("{}_access_enable", mem_id);
                    if self.graph.nodes.contains_key(&access_enable_id) {
                        let not_complete_id = format!("{}_not_complete", mem_id);
                        if !self.graph.nodes.contains_key(&not_complete_id) {
                            let mut data: HashMap<String, Value> = HashMap::new();
                            data.insert("type".into(), json!("operation"));
                            data.insert("operator".into(), json!("!"));
                            data.insert("name".into(), json!(&not_complete_id));
                            let node = Node::new(Some(not_complete_id.clone()), Some(data), false, false, None, false, None, None, false, false, 0, false, true, None, None);
                            self.graph.add_node(node);
                            let mut ed: HashMap<String, Value> = HashMap::new();
                            ed.insert("type".into(), json!("operand"));
                            let edge = Edge::new(cs_id.clone(), not_complete_id.clone(), None, Some(ed));
                            self.graph.add_edge(edge);
                        }

                        let stall_id = format!("{}_latency_stall", mem_id);
                        self.create_and_node(&stall_id, &access_enable_id, &not_complete_id);

                        // Connect to stall controller
                        self.connect_to_stall_controller(&stall_id);
                        log::info!("  Added memory latency stall: {}", stall_id);
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_count_pipe_depth() {
        assert_eq!(count_pipe_depth("PIPE_Execute_rd_PIPE"), 1);
        assert_eq!(count_pipe_depth("PIPE_Memory_PIPE_Execute_rd_PIPE_PIPE"), 2);
        assert_eq!(count_pipe_depth("rd"), 0);
    }

    #[test]
    fn test_hazard_resolution_strategy() {
        let h = DetectedHazard {
            hazard_type: "RAW".into(),
            resource: "rf".into(),
            write_stage: 3,
            write_stage_name: "Writeback".into(),
            write_access_node_id: "rf_shared_wr".into(),
            write_index_node_id: "rd".into(),
            write_index_name: "rd".into(),
            read_stage: 1,
            read_stage_name: "Decode".into(),
            read_access_node_id: "rf[rs1]_rd".into(),
            read_index_node_id: "rs1".into(),
            read_index_name: "rs1".into(),
            resolution: HazardResolutionStrategy::Stall,
        };
        assert_eq!(h.get_forwarding_distance(), 2);
    }
}
