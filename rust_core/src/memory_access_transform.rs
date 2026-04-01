//! Memory access transformation for ResourceGraphs.
//!
//! Port of `memory_access_transform.py`. Implements bidirectional algorithms to
//! transform memory accesses. The critical strategy for RV32I is `set_port_width`
//! which converts byte-level accesses to word-level with byte selection muxes.

use serde_json::{json, Value};
use std::collections::HashMap;

use crate::resource_graph::{Edge, Node, ResourceGraph};

// ---------------------------------------------------------------------------
// MemoryAccessTransformSpec
// ---------------------------------------------------------------------------

/// Specification for memory access transformation.
#[derive(Debug, Clone)]
pub struct MemoryAccessTransformSpec {
    /// Memory node name (e.g., "umem", "dmem")
    pub memory: String,
    /// Strategy: "serialize_parallelize", "split_merge", or "set_port_width"
    pub strategy: String,
    /// Current access width in bits
    pub current_width: i64,
    /// Target memory port width in bits
    pub target_width: i64,
    /// Direction: "forward", "reverse", or "update"
    pub direction: String,
    /// For split_merge reverse
    pub merge_from: Vec<String>,
    /// "little" or "big"
    pub endianness: String,
    /// "port_width" (aligned) or "unaligned"
    pub alignment: String,
}

impl MemoryAccessTransformSpec {
    pub fn new(
        memory: &str,
        strategy: &str,
        current_width: i64,
        target_width: i64,
        direction: &str,
    ) -> Result<Self, String> {
        if !["serialize_parallelize", "split_merge", "set_port_width"].contains(&strategy) {
            return Err(format!("Unknown strategy: {strategy}"));
        }
        if !["forward", "reverse", "update"].contains(&direction) {
            return Err(format!("Unknown direction: {direction}"));
        }
        Ok(Self {
            memory: memory.to_string(),
            strategy: strategy.to_string(),
            current_width,
            target_width,
            direction: direction.to_string(),
            merge_from: Vec::new(),
            endianness: "little".to_string(),
            alignment: "port_width".to_string(),
        })
    }
}

impl std::fmt::Display for MemoryAccessTransformSpec {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "{} {}: {} {}->{}  bits",
            self.strategy, self.direction, self.memory, self.current_width, self.target_width
        )
    }
}

// ---------------------------------------------------------------------------
// TransformResult
// ---------------------------------------------------------------------------

/// Result of a memory access transformation.
#[derive(Debug, Clone, Default)]
pub struct TransformResult {
    pub transformed: bool,
    pub reason: Option<String>,
    pub direction: Option<String>,
    pub old_width: Option<i64>,
    pub new_width: Option<i64>,
    pub old_port_width: Option<i64>,
    pub new_port_width: Option<i64>,
    pub nodes_added: Vec<String>,
    pub nodes_removed: Vec<String>,
    pub nodes_updated: Vec<String>,
    pub dry_run: bool,
}

// ---------------------------------------------------------------------------
// MemoryAccessTransform
// ---------------------------------------------------------------------------

/// Transforms memory accesses to match memory width constraints.
pub struct MemoryAccessTransform<'a> {
    graph: &'a mut ResourceGraph,
}

impl<'a> MemoryAccessTransform<'a> {
    pub fn new(graph: &'a mut ResourceGraph) -> Self {
        Self { graph }
    }

    /// Apply bidirectional memory access transformation.
    pub fn apply_transformation(
        &mut self,
        spec: &MemoryAccessTransformSpec,
        dry_run: bool,
    ) -> TransformResult {
        match spec.strategy.as_str() {
            "serialize_parallelize" => self.apply_serialize_parallelize(spec, dry_run),
            "split_merge" => self.apply_split_merge(spec, dry_run),
            "set_port_width" => self.apply_set_port_width(spec, dry_run),
            _ => TransformResult {
                transformed: false,
                reason: Some(format!("Unknown strategy: {}", spec.strategy)),
                ..Default::default()
            },
        }
    }

    // =======================================================================
    // SET_PORT_WIDTH STRATEGY (the critical one for RV32I)
    // =======================================================================

    fn apply_set_port_width(
        &mut self,
        spec: &MemoryAccessTransformSpec,
        dry_run: bool,
    ) -> TransformResult {
        match spec.direction.as_str() {
            "forward" => self.set_port_width_forward(spec, dry_run),
            "reverse" => self.set_port_width_reverse(spec, dry_run),
            _ => TransformResult {
                transformed: false,
                reason: Some(format!(
                    "set_port_width does not support '{}' direction",
                    spec.direction
                )),
                ..Default::default()
            },
        }
    }

    /// Forward: Set port_width and generate word-addressed byte muxing.
    fn set_port_width_forward(
        &mut self,
        spec: &MemoryAccessTransformSpec,
        dry_run: bool,
    ) -> TransformResult {
        // Find memory node
        let mem_id = spec.memory.clone();
        if !self.graph.nodes.contains_key(&mem_id) {
            return TransformResult {
                transformed: false,
                reason: Some(format!("Memory {} not found", mem_id)),
                ..Default::default()
            };
        }

        // Check if already has port_width set
        let existing_port_width = self.graph.nodes[&mem_id]
            .data
            .get("port_width")
            .and_then(|v| v.as_i64());

        if existing_port_width == Some(spec.target_width) {
            // Even if port_width is already set, transform byte_enable_computation nodes
            let mut nodes_added = Vec::new();
            let mut nodes_updated = Vec::new();
            self.transform_byte_enable_computation_nodes(
                &mem_id,
                spec.target_width,
                &mut nodes_added,
                &mut nodes_updated,
                &spec.endianness,
                &spec.alignment,
            );
            return TransformResult {
                transformed: false,
                reason: Some(format!("port_width already {}", spec.target_width)),
                ..Default::default()
            };
        }

        if dry_run {
            return TransformResult {
                transformed: true,
                direction: Some("forward".into()),
                old_port_width: existing_port_width,
                new_port_width: Some(spec.target_width),
                nodes_updated: vec![mem_id.clone()],
                dry_run: true,
                ..Default::default()
            };
        }

        // Set port_width and endianness on memory node
        {
            let mem = self.graph.nodes.get_mut(&mem_id).unwrap();
            mem.data
                .insert("port_width".into(), json!(spec.target_width));
            mem.data
                .insert("endianness".into(), json!(&spec.endianness));
        }

        // Find all memory read nodes
        let read_node_ids = self.find_memory_read_nodes(&mem_id);

        let mut nodes_added = Vec::new();
        let mut nodes_updated = vec![mem_id.clone()];

        for read_id in read_node_ids {
            // Find address sources (array_index edges, excluding memory base)
            let addr_sources = self.find_addr_sources(&read_id);

            if addr_sources.is_empty() {
                continue;
            }

            // Use first address source (single address case)
            let addr_node_id = addr_sources[0].0.clone();

            // Find sub-word and full-word destinations
            let (subword_dests, _fullword_dests) =
                self.find_subword_destinations(&read_id, spec.target_width, &spec.alignment);

            // Insert byte selection mux for each sub-word destination
            for (dest_id, dest_width, orig_edge_id) in subword_dests {
                let result = self.insert_byte_selection_mux(
                    &read_id,
                    &dest_id,
                    &addr_node_id,
                    dest_width,
                    spec.target_width,
                    &orig_edge_id,
                    &spec.endianness,
                );
                nodes_added.extend(result.nodes_added);
                nodes_updated.extend(result.nodes_updated);
            }
        }

        // Transform byte_enable_computation nodes
        self.transform_byte_enable_computation_nodes(
            &mem_id,
            spec.target_width,
            &mut nodes_added,
            &mut nodes_updated,
            &spec.endianness,
            &spec.alignment,
        );

        TransformResult {
            transformed: true,
            direction: Some("forward".into()),
            old_port_width: existing_port_width,
            new_port_width: Some(spec.target_width),
            nodes_added,
            nodes_updated,
            ..Default::default()
        }
    }

    /// Reverse: Remove port_width and byte-muxing logic.
    fn set_port_width_reverse(
        &mut self,
        spec: &MemoryAccessTransformSpec,
        dry_run: bool,
    ) -> TransformResult {
        let mem_id = spec.memory.clone();
        if !self.graph.nodes.contains_key(&mem_id) {
            return TransformResult {
                transformed: false,
                reason: Some(format!("Memory {} not found", mem_id)),
                ..Default::default()
            };
        }

        let existing_port_width = self.graph.nodes[&mem_id]
            .data
            .get("port_width")
            .and_then(|v| v.as_i64());

        if existing_port_width.is_none() {
            return TransformResult {
                transformed: false,
                reason: Some(format!("No port_width set on {}", mem_id)),
                ..Default::default()
            };
        }

        // Find all byte mux nodes and related nodes to remove
        let nodes_to_remove: Vec<String> = self
            .graph
            .nodes
            .values()
            .filter(|n| {
                let ntype = n
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let is_byte_mux = ntype == "multiplexer" && n.id.contains("byte_mux");
                let is_slice = ntype == "bit_slice"
                    && (n.id.contains("word_addr")
                        || n.id.contains("byte_offset")
                        || n.id.contains("_slice_")
                        || n.id.contains("halfword_select"));
                let is_cmp = ntype == "comparison" && n.id.contains("byte_mux_sel_");
                (is_byte_mux || is_slice || is_cmp) && n.id.contains(&mem_id)
            })
            .map(|n| n.id.clone())
            .collect();

        if dry_run {
            return TransformResult {
                transformed: true,
                direction: Some("reverse".into()),
                old_port_width: existing_port_width,
                new_port_width: None,
                nodes_removed: nodes_to_remove,
                nodes_updated: vec![mem_id.clone()],
                dry_run: true,
                ..Default::default()
            };
        }

        // Remove port_width and endianness
        {
            let mem = self.graph.nodes.get_mut(&mem_id).unwrap();
            mem.data.remove("port_width");
            mem.data.remove("endianness");
        }

        // Remove transformation nodes
        let removed_ids: Vec<String> = nodes_to_remove.clone();
        for nid in nodes_to_remove {
            self.graph.remove_node(&nid);
        }

        TransformResult {
            transformed: true,
            direction: Some("reverse".into()),
            old_port_width: existing_port_width,
            new_port_width: None,
            nodes_removed: removed_ids,
            nodes_updated: vec![mem_id],
            ..Default::default()
        }
    }

    // =======================================================================
    // WRITE-READ FORWARDING
    // =======================================================================

    /// Enable write-to-read forwarding on a memory node.
    pub fn enable_write_read_forwarding(&mut self, memory_name: &str) -> bool {
        let is_memory = self
            .graph
            .nodes
            .get(memory_name)
            .map(|n| {
                n.data
                    .get("is_memory")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false)
            })
            .unwrap_or(false);

        if !is_memory {
            // Check if it looks like a memory (has array accesses)
            let is_array = self.graph.nodes.values().any(|n| {
                n.data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .contains("array_access")
                    && n.id.contains(memory_name)
            });
            if !is_array {
                return false;
            }
        }

        if let Some(node) = self.graph.nodes.get_mut(memory_name) {
            node.data.insert("write_read_fwd".into(), json!(true));
            true
        } else {
            false
        }
    }

    /// Disable write-to-read forwarding on a memory node.
    pub fn disable_write_read_forwarding(&mut self, memory_name: &str) -> bool {
        if let Some(node) = self.graph.nodes.get_mut(memory_name) {
            node.data.remove("write_read_fwd");
            true
        } else {
            false
        }
    }

    /// Check if a memory has write-read forwarding enabled.
    pub fn has_write_read_forwarding(&self, memory_name: &str) -> bool {
        self.graph
            .nodes
            .get(memory_name)
            .and_then(|n| n.data.get("write_read_fwd"))
            .and_then(|v| v.as_bool())
            .unwrap_or(false)
    }

    // =======================================================================
    // HELPERS
    // =======================================================================

    /// Find all memory read nodes for a given memory.
    /// After merging, these are shared nodes like "dmem[addr]_rd".
    fn find_memory_read_nodes(&self, memory: &str) -> Vec<String> {
        let pattern = format!("{memory}[");
        self.graph
            .nodes
            .keys()
            .filter(|id| id.contains(&pattern) && id.contains("_rd"))
            .cloned()
            .collect()
    }

    /// Find all memory access nodes (read and write) for a given memory.
    fn find_memory_access_nodes(&self, memory: &str) -> Vec<String> {
        let mut result = Vec::new();
        let bracket_pattern = format!("{memory}[");

        for (id, node) in &self.graph.nodes {
            // Check for array_access type nodes (pre-split)
            if node.data.get("type").and_then(|v| v.as_str()) == Some("array_access") {
                let target_name = node
                    .data
                    .get("expression")
                    .and_then(|e| e.get("target"))
                    .and_then(|t| t.get("name"))
                    .and_then(|n| n.as_str());
                if target_name == Some(memory) {
                    result.push(id.clone());
                    continue;
                }
            }
            // Check for split memory access nodes (post-merge)
            if id.contains(&bracket_pattern) && (id.contains("_rd") || id.contains("_wr")) {
                result.push(id.clone());
            }
        }
        result
    }

    /// Find address sources for a read node (array_index edges, excluding memory base).
    fn find_addr_sources(&self, read_node_id: &str) -> Vec<(String, String)> {
        let mut sources = Vec::new();
        let node = match self.graph.nodes.get(read_node_id) {
            Some(n) => n,
            None => return sources,
        };

        for eid in &node.incoming_edges {
            let edge = match self.graph.edges.get(eid) {
                Some(e) => e,
                None => continue,
            };
            if edge.data.get("type").and_then(|v| v.as_str()) != Some("array_index") {
                continue;
            }
            // Skip if source is the memory node itself
            if let Some(src) = self.graph.nodes.get(&edge.source) {
                if src
                    .data
                    .get("is_memory")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false)
                {
                    continue;
                }
            }
            sources.push((edge.source.clone(), eid.clone()));
        }
        sources
    }

    /// Find sub-word destinations from a read node.
    /// Returns (subword_dests, fullword_dests) where each is (dest_id, width, edge_id).
    fn find_subword_destinations(
        &self,
        read_node_id: &str,
        port_width: i64,
        alignment: &str,
    ) -> (Vec<(String, i64, String)>, Vec<(String, i64, String)>) {
        let mut subword = Vec::new();
        let mut fullword = Vec::new();

        let node = match self.graph.nodes.get(read_node_id) {
            Some(n) => n,
            None => return (subword, fullword),
        };

        for eid in &node.outgoing_edges {
            let edge = match self.graph.edges.get(eid) {
                Some(e) => e,
                None => continue,
            };
            if edge.data.get("type").and_then(|v| v.as_str()) != Some("assignment") {
                continue;
            }
            let dest = match self.graph.nodes.get(&edge.target) {
                Some(n) => n,
                None => continue,
            };
            let dest_width = match dest.data.get("bit_width").and_then(|v| v.as_i64()) {
                Some(w) => w,
                None => continue,
            };

            if dest_width < port_width {
                if alignment == "unaligned" && dest_width > 8 {
                    // spanning sub-word - treat as fullword for now (stub)
                    fullword.push((edge.target.clone(), dest_width, eid.clone()));
                } else {
                    subword.push((edge.target.clone(), dest_width, eid.clone()));
                }
            } else if dest_width == port_width && alignment == "unaligned" {
                fullword.push((edge.target.clone(), dest_width, eid.clone()));
            }
        }

        (subword, fullword)
    }

    /// Insert a byte selection mux between a memory read and a sub-word destination.
    ///
    /// Transforms:
    ///   read_node --assignment--> dest_node
    /// Into:
    ///   read_node --> slice_0 --> mux --> dest_node
    ///            --> slice_1 -----^
    ///   addr[1:0] --> cmp_0 ------^
    ///            --> cmp_1 ------^
    fn insert_byte_selection_mux(
        &mut self,
        read_node_id: &str,
        dest_node_id: &str,
        addr_node_id: &str,
        dest_width: i64,
        port_width: i64,
        orig_edge_id: &str,
        endianness: &str,
    ) -> TransformResult {
        let mux_name = format!("{dest_node_id}_byte_mux");
        let mut nodes_added = Vec::new();
        let mut nodes_updated = Vec::new();

        let port_bytes = port_width / 8;
        let offset_bits = (port_bytes as f64).log2() as i64;

        // Sanitize read ID for naming
        let sanitized_read_id = read_node_id.replace('[', "_").replace(']', "");
        let byte_offset_name = format!("{sanitized_read_id}_byte_offset");

        // Create byte offset extraction node if not already present
        if !self.graph.nodes.contains_key(&byte_offset_name) {
            let mut bo_node = Node::with_defaults(Some(byte_offset_name.clone()));
            bo_node.data.insert("type".into(), json!("bit_slice"));
            bo_node.data.insert("name".into(), json!(&byte_offset_name));
            bo_node.data.insert(
                "display_name".into(),
                json!(format!("{}[{}:0]", addr_node_id, offset_bits - 1)),
            );
            bo_node.data.insert("bit_width".into(), json!(offset_bits));
            bo_node.data.insert(
                "expression".into(),
                json!({
                    "type": "bit_slice",
                    "range": [offset_bits - 1, 0],
                    "operand": {"type": "identifier", "name": addr_node_id}
                }),
            );
            bo_node
                .data
                .insert("memory_read_node".into(), json!(read_node_id));
            bo_node
                .data
                .insert("address_source".into(), json!(addr_node_id));
            self.graph.add_node(bo_node);
            nodes_added.push(byte_offset_name.clone());

            let mut edata = HashMap::new();
            edata.insert("type".into(), json!("operand"));
            edata.insert("label".into(), json!("bitslice_operand"));
            let edge = Edge::new(
                addr_node_id.to_string(),
                byte_offset_name.clone(),
                None,
                Some(edata),
            );
            self.graph.add_edge(edge);
        }

        // Determine slice ranges and selector based on dest_width and port_width
        let (num_inputs, mut slice_ranges, selector_node_id) =
            self.determine_mux_params(
                dest_width,
                port_width,
                &byte_offset_name,
                &sanitized_read_id,
                addr_node_id,
                read_node_id,
                offset_bits,
                &mut nodes_added,
            );

        // For big-endian, reverse slice_ranges
        if endianness == "big" {
            slice_ranges.reverse();
        }

        // Create bit slice nodes for each position
        let mut slice_node_ids = Vec::new();
        for (high, low) in &slice_ranges {
            let slice_name = format!("{read_node_id}_slice_{high}_{low}");
            if !self.graph.nodes.contains_key(&slice_name) {
                let mut sn = Node::with_defaults(Some(slice_name.clone()));
                sn.data.insert("type".into(), json!("bit_slice"));
                sn.data.insert("name".into(), json!(&slice_name));
                sn.data.insert(
                    "display_name".into(),
                    json!(format!("{read_node_id}[{high}:{low}]")),
                );
                sn.data.insert("bit_width".into(), json!(dest_width));
                sn.data.insert(
                    "expression".into(),
                    json!({
                        "type": "bit_slice",
                        "range": [high, low],
                        "operand": {"type": "identifier", "name": read_node_id}
                    }),
                );
                self.graph.add_node(sn);
                nodes_added.push(slice_name.clone());

                let mut edata = HashMap::new();
                edata.insert("type".into(), json!("operand"));
                edata.insert("label".into(), json!("bitslice_operand"));
                let edge = Edge::new(
                    read_node_id.to_string(),
                    slice_name.clone(),
                    None,
                    Some(edata),
                );
                self.graph.add_edge(edge);
            }
            slice_node_ids.push(slice_name);
        }

        // Create comparison nodes for selector conditions
        let selector_width = if num_inputs > 1 {
            ((num_inputs as f64).log2().ceil() as i64).max(1)
        } else {
            1
        };
        let mut compare_node_ids = Vec::new();
        for i in 0..num_inputs {
            let cmp_name = format!("{mux_name}_sel_{i}");
            if !self.graph.nodes.contains_key(&cmp_name) {
                let mut cn = Node::with_defaults(Some(cmp_name.clone()));
                cn.data.insert("type".into(), json!("comparison"));
                cn.data.insert("name".into(), json!(&cmp_name));
                cn.data.insert(
                    "display_name".into(),
                    json!(format!("{} == {}", selector_node_id, i)),
                );
                cn.data.insert("bit_width".into(), json!(1));
                cn.data.insert("operator".into(), json!("=="));
                cn.data.insert("compare_value".into(), json!(i));
                cn.data.insert(
                    "expression".into(),
                    json!({
                        "type": "comparison",
                        "operator": "==",
                        "left": {"type": "identifier", "name": &selector_node_id},
                        "right": {"type": "literal", "value": i, "width": selector_width}
                    }),
                );
                self.graph.add_node(cn);
                nodes_added.push(cmp_name.clone());

                let mut edata = HashMap::new();
                edata.insert("type".into(), json!("operand"));
                edata.insert("label".into(), json!("left_operand"));
                let edge = Edge::new(
                    selector_node_id.clone(),
                    cmp_name.clone(),
                    None,
                    Some(edata),
                );
                self.graph.add_edge(edge);
            }
            compare_node_ids.push(cmp_name);
        }

        // Create the priority mux node
        let mut mux_node = Node::with_defaults(Some(mux_name.clone()));
        mux_node.data.insert("type".into(), json!("multiplexer"));
        mux_node.data.insert("name".into(), json!(&mux_name));
        mux_node.data.insert(
            "display_name".into(),
            json!(format!("byte_mux({dest_node_id})")),
        );
        mux_node.data.insert("bit_width".into(), json!(dest_width));
        mux_node.data.insert("mux_type".into(), json!("priority"));
        mux_node
            .data
            .insert("num_inputs".into(), json!(num_inputs));
        self.graph.add_node(mux_node);
        nodes_added.push(mux_name.clone());

        // Connect slice and compare nodes to mux
        for (i, (slice_id, cmp_id)) in slice_node_ids
            .iter()
            .zip(compare_node_ids.iter())
            .enumerate()
        {
            // data input edge
            let mut edata = HashMap::new();
            edata.insert("type".into(), json!("mux_input"));
            edata.insert("input_index".into(), json!(i));
            let e1 = Edge::new(slice_id.clone(), mux_name.clone(), None, Some(edata));
            self.graph.add_edge(e1);

            // select edge
            let mut edata2 = HashMap::new();
            edata2.insert("type".into(), json!("mux_select"));
            edata2.insert("input_index".into(), json!(i));
            let e2 = Edge::new(cmp_id.clone(), mux_name.clone(), None, Some(edata2));
            self.graph.add_edge(e2);
        }

        // Remove original edge from read_node to dest_node
        self.graph.remove_edge(orig_edge_id);

        // Connect mux -> dest_node
        let mut edata = HashMap::new();
        edata.insert("type".into(), json!("assignment"));
        edata.insert("from_byte_mux".into(), json!(true));
        edata.insert("original_access".into(), json!(read_node_id));
        let out_edge = Edge::new(mux_name, dest_node_id.to_string(), None, Some(edata));
        self.graph.add_edge(out_edge);

        nodes_updated.push(dest_node_id.to_string());

        TransformResult {
            transformed: true,
            nodes_added,
            nodes_updated,
            ..Default::default()
        }
    }

    /// Determine mux parameters (num_inputs, slice_ranges, selector_node_id)
    /// based on dest_width and port_width.
    #[allow(clippy::too_many_arguments)]
    fn determine_mux_params(
        &mut self,
        dest_width: i64,
        port_width: i64,
        byte_offset_name: &str,
        sanitized_read_id: &str,
        addr_node_id: &str,
        read_node_id: &str,
        _offset_bits: i64,
        nodes_added: &mut Vec<String>,
    ) -> (usize, Vec<(i64, i64)>, String) {
        match dest_width {
            8 => {
                let (num, ranges) = match port_width {
                    32 => (4, vec![(7, 0), (15, 8), (23, 16), (31, 24)]),
                    64 => (
                        8,
                        vec![
                            (7, 0),
                            (15, 8),
                            (23, 16),
                            (31, 24),
                            (39, 32),
                            (47, 40),
                            (55, 48),
                            (63, 56),
                        ],
                    ),
                    _ => (4, vec![(7, 0), (15, 8), (23, 16), (31, 24)]),
                };
                (num, ranges, byte_offset_name.to_string())
            }
            16 => {
                let (num, ranges, sel_bit) = match port_width {
                    32 => (2usize, vec![(15i64, 0i64), (31, 16)], 1i64),
                    64 => (4, vec![(15, 0), (31, 16), (47, 32), (63, 48)], 2),
                    _ => (2, vec![(15, 0), (31, 16)], 1),
                };
                let selector_name = format!("{sanitized_read_id}_halfword_select");
                if !self.graph.nodes.contains_key(&selector_name) {
                    let (range_hi, range_lo) = if port_width == 64 { (2, 1) } else { (1, 1) };
                    let bw = if port_width == 64 { 2 } else { 1 };
                    let display = if port_width == 64 {
                        format!("{addr_node_id}[2:1]")
                    } else {
                        format!("{addr_node_id}[1]")
                    };
                    let mut sn = Node::with_defaults(Some(selector_name.clone()));
                    sn.data.insert("type".into(), json!("bit_slice"));
                    sn.data.insert("name".into(), json!(&selector_name));
                    sn.data.insert("display_name".into(), json!(display));
                    sn.data.insert("bit_width".into(), json!(bw));
                    sn.data.insert(
                        "expression".into(),
                        json!({
                            "type": "bit_slice",
                            "range": [range_hi, range_lo],
                            "operand": {"type": "identifier", "name": addr_node_id}
                        }),
                    );
                    sn.data
                        .insert("memory_read_node".into(), json!(read_node_id));
                    sn.data
                        .insert("address_source".into(), json!(addr_node_id));
                    self.graph.add_node(sn);
                    nodes_added.push(selector_name.clone());

                    let mut edata = HashMap::new();
                    edata.insert("type".into(), json!("operand"));
                    edata.insert("label".into(), json!("bitslice_operand"));
                    let edge = Edge::new(
                        addr_node_id.to_string(),
                        selector_name.clone(),
                        None,
                        Some(edata),
                    );
                    self.graph.add_edge(edge);
                }
                let _ = sel_bit; // used implicitly via range
                (num, ranges, selector_name)
            }
            32 if port_width == 64 => {
                let selector_name = format!("{sanitized_read_id}_word_select");
                if !self.graph.nodes.contains_key(&selector_name) {
                    let mut sn = Node::with_defaults(Some(selector_name.clone()));
                    sn.data.insert("type".into(), json!("bit_slice"));
                    sn.data.insert("name".into(), json!(&selector_name));
                    sn.data.insert(
                        "display_name".into(),
                        json!(format!("{addr_node_id}[2]")),
                    );
                    sn.data.insert("bit_width".into(), json!(1));
                    sn.data.insert(
                        "expression".into(),
                        json!({
                            "type": "bit_slice",
                            "range": [2, 2],
                            "operand": {"type": "identifier", "name": addr_node_id}
                        }),
                    );
                    sn.data
                        .insert("memory_read_node".into(), json!(read_node_id));
                    sn.data
                        .insert("address_source".into(), json!(addr_node_id));
                    self.graph.add_node(sn);
                    nodes_added.push(selector_name.clone());

                    let mut edata = HashMap::new();
                    edata.insert("type".into(), json!("operand"));
                    edata.insert("label".into(), json!("bitslice_operand"));
                    let edge = Edge::new(
                        addr_node_id.to_string(),
                        selector_name.clone(),
                        None,
                        Some(edata),
                    );
                    self.graph.add_edge(edge);
                }
                (2, vec![(31, 0), (63, 32)], selector_name)
            }
            _ => {
                // Fallback: treat as byte access
                (4, vec![(7, 0), (15, 8), (23, 16), (31, 24)], byte_offset_name.to_string())
            }
        }
    }

    /// Transform byte_enable_computation nodes into standard shift operations.
    /// These nodes are created by graph_merger for sub-word stores.
    fn transform_byte_enable_computation_nodes(
        &mut self,
        memory: &str,
        port_width: i64,
        nodes_added: &mut Vec<String>,
        nodes_updated: &mut Vec<String>,
        endianness: &str,
        alignment: &str,
    ) -> usize {
        let mut transformed_count = 0;

        // Find byte_enable_computation nodes
        let be_node_ids: Vec<String> = self
            .graph
            .nodes
            .iter()
            .filter(|(_, n)| {
                n.data.get("type").and_then(|v| v.as_str()) == Some("byte_enable_computation")
            })
            .map(|(id, _)| id.clone())
            .collect();

        // Find write port node
        let write_port_id: Option<String> = self
            .graph
            .nodes
            .iter()
            .find(|(_, n)| {
                n.data.get("type").and_then(|v| v.as_str()) == Some("memory_write_port")
                    && n.data.get("base_memory").and_then(|v| v.as_str()) == Some(memory)
            })
            .map(|(id, _)| id.clone());

        let mut store_byte_enables: HashMap<String, String> = HashMap::new();

        for be_id in be_node_ids {
            let data_width = self.graph.nodes[&be_id]
                .data
                .get("data_width")
                .and_then(|v| v.as_i64())
                .unwrap_or(8);
            let memory_width = self.graph.nodes[&be_id]
                .data
                .get("memory_width")
                .and_then(|v| v.as_i64())
                .unwrap_or(32);

            // Skip byte enable computation for full-word or larger writes
            if data_width >= port_width {
                self.graph.nodes.remove(&be_id);
                continue;
            }

            let num_byte_lanes = memory_width / 8;
            let bytes_per_access = data_width / 8;
            let instruction: Option<String> = self.graph.nodes[&be_id]
                .data
                .get("instruction")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());

            // Find address source from incoming edges
            let addr_node_id: Option<String> = {
                let node = &self.graph.nodes[&be_id];
                let mut found = None;
                for eid in &node.incoming_edges {
                    if let Some(edge) = self.graph.edges.get(eid) {
                        if edge.data.get("type").and_then(|v| v.as_str())
                            == Some("byte_enable_address")
                        {
                            found = Some(edge.source.clone());
                            break;
                        }
                    }
                }
                found
            };

            let addr_node_id = match addr_node_id {
                Some(id) => id,
                None => continue,
            };

            // Create base mask literal
            let base_mask_name = format!("{be_id}_mask");
            let base_mask_value = (1i64 << bytes_per_access) - 1;
            {
                let mut mask_node = Node::with_defaults(Some(base_mask_name.clone()));
                mask_node.data.insert("type".into(), json!("literal"));
                mask_node.data.insert("name".into(), json!(&base_mask_name));
                mask_node
                    .data
                    .insert("bit_width".into(), json!(num_byte_lanes));
                mask_node.data.insert("value".into(), json!(base_mask_value));
                mask_node.data.insert(
                    "expression".into(),
                    json!({"type": "literal", "value": base_mask_value, "width": num_byte_lanes}),
                );
                self.graph.add_node(mask_node);
                nodes_added.push(base_mask_name.clone());
            }

            // Create byte offset extraction
            let offset_bits = (port_width as f64 / 8.0).log2() as i64;
            let byte_offset_name = format!("{be_id}_offset");
            {
                let mut bo_node = Node::with_defaults(Some(byte_offset_name.clone()));
                bo_node.data.insert("type".into(), json!("bit_slice"));
                bo_node.data.insert("name".into(), json!(&byte_offset_name));
                bo_node.data.insert(
                    "display_name".into(),
                    json!(format!("{}[{}:0]", addr_node_id, offset_bits - 1)),
                );
                bo_node.data.insert("bit_width".into(), json!(offset_bits));
                bo_node.data.insert(
                    "expression".into(),
                    json!({
                        "type": "bit_slice",
                        "range": [offset_bits - 1, 0],
                        "operand": {"type": "identifier", "name": &addr_node_id}
                    }),
                );
                self.graph.add_node(bo_node);
                nodes_added.push(byte_offset_name.clone());

                let mut edata = HashMap::new();
                edata.insert("type".into(), json!("operand"));
                let edge = Edge::new(
                    addr_node_id.clone(),
                    byte_offset_name.clone(),
                    None,
                    Some(edata),
                );
                self.graph.add_edge(edge);
            }

            // Determine shift amount node for byte enable
            let be_shift_amount_id = if data_width == 8 {
                // 8-bit: use full byte offset
                if endianness == "big" {
                    // Invert for big-endian
                    let max_val = (port_width / 8) - 1;
                    let max_name = format!("{be_id}_be_max_offset");
                    let mut mn = Node::with_defaults(Some(max_name.clone()));
                    mn.data.insert("type".into(), json!("literal"));
                    mn.data.insert("name".into(), json!(&max_name));
                    mn.data.insert("bit_width".into(), json!(offset_bits));
                    mn.data.insert("value".into(), json!(max_val));
                    mn.data.insert(
                        "expression".into(),
                        json!({"type": "literal", "value": max_val, "width": offset_bits}),
                    );
                    self.graph.add_node(mn);
                    nodes_added.push(max_name.clone());

                    let inv_name = format!("{be_id}_be_inv_offset");
                    let mut inv = Node::with_defaults(Some(inv_name.clone()));
                    inv.data.insert("type".into(), json!("operation"));
                    inv.data.insert("name".into(), json!(&inv_name));
                    inv.data.insert("bit_width".into(), json!(offset_bits));
                    inv.data.insert("operator".into(), json!("^"));
                    inv.data.insert(
                        "expression".into(),
                        json!({
                            "type": "binary_op", "operator": "^",
                            "left": {"type": "identifier", "name": &max_name},
                            "right": {"type": "identifier", "name": &byte_offset_name}
                        }),
                    );
                    self.graph.add_node(inv);
                    nodes_added.push(inv_name.clone());

                    let e1 = Edge::new(
                        max_name,
                        inv_name.clone(),
                        None,
                        Some(HashMap::from([("type".into(), json!("left_operand"))])),
                    );
                    let e2 = Edge::new(
                        byte_offset_name.clone(),
                        inv_name.clone(),
                        None,
                        Some(HashMap::from([("type".into(), json!("right_operand"))])),
                    );
                    self.graph.add_edge(e1);
                    self.graph.add_edge(e2);
                    inv_name
                } else {
                    byte_offset_name.clone()
                }
            } else {
                // Non-byte: use selector with zero padding (aligned) or byte offset (unaligned)
                if alignment == "unaligned" && data_width > 8 {
                    if endianness == "big" {
                        let max_non_spanning = port_width / 8 - bytes_per_access;
                        let max_name = format!("{be_id}_be_max");
                        let mut mn = Node::with_defaults(Some(max_name.clone()));
                        mn.data.insert("type".into(), json!("literal"));
                        mn.data.insert("bit_width".into(), json!(offset_bits));
                        mn.data.insert("value".into(), json!(max_non_spanning));
                        mn.data.insert(
                            "expression".into(),
                            json!({"type": "literal", "value": max_non_spanning, "width": offset_bits}),
                        );
                        self.graph.add_node(mn);
                        nodes_added.push(max_name.clone());

                        let inv_name = format!("{be_id}_be_inv_sel");
                        let mut inv = Node::with_defaults(Some(inv_name.clone()));
                        inv.data.insert("type".into(), json!("operation"));
                        inv.data.insert("bit_width".into(), json!(offset_bits));
                        inv.data.insert("operator".into(), json!("-"));
                        inv.data.insert(
                            "expression".into(),
                            json!({
                                "type": "binary_op", "operator": "-",
                                "left": {"type": "identifier", "name": &max_name},
                                "right": {"type": "identifier", "name": &byte_offset_name}
                            }),
                        );
                        self.graph.add_node(inv);
                        nodes_added.push(inv_name.clone());

                        let e1 = Edge::new(
                            max_name,
                            inv_name.clone(),
                            None,
                            Some(HashMap::from([("type".into(), json!("left_operand"))])),
                        );
                        let e2 = Edge::new(
                            byte_offset_name.clone(),
                            inv_name.clone(),
                            None,
                            Some(HashMap::from([("type".into(), json!("right_operand"))])),
                        );
                        self.graph.add_edge(e1);
                        self.graph.add_edge(e2);
                        inv_name
                    } else {
                        byte_offset_name.clone()
                    }
                } else {
                    // Aligned: selector with zero padding
                    let position_bits = (bytes_per_access as f64).log2() as i64;
                    let num_positions = port_width / data_width;
                    let selector_bits = if num_positions > 1 {
                        ((num_positions as f64).log2() as i64).max(1)
                    } else {
                        1
                    };
                    let selector_high = offset_bits - 1;
                    let selector_low = position_bits;

                    let selector_name = format!("{be_id}_sel");
                    {
                        let mut sn = Node::with_defaults(Some(selector_name.clone()));
                        sn.data.insert("type".into(), json!("bit_slice"));
                        sn.data.insert("name".into(), json!(&selector_name));
                        sn.data.insert("bit_width".into(), json!(selector_bits));
                        sn.data.insert(
                            "expression".into(),
                            json!({
                                "type": "bit_slice",
                                "range": [selector_high, selector_low],
                                "operand": {"type": "identifier", "name": &addr_node_id}
                            }),
                        );
                        self.graph.add_node(sn);
                        nodes_added.push(selector_name.clone());
                        let edge = Edge::new(
                            addr_node_id.clone(),
                            selector_name.clone(),
                            None,
                            Some(HashMap::from([("type".into(), json!("operand"))])),
                        );
                        self.graph.add_edge(edge);
                    }

                    let be_sel_id = if endianness == "big" {
                        let max_val = (1i64 << selector_bits) - 1;
                        let max_name = format!("{be_id}_be_max");
                        let mut mn = Node::with_defaults(Some(max_name.clone()));
                        mn.data.insert("type".into(), json!("literal"));
                        mn.data.insert("bit_width".into(), json!(selector_bits));
                        mn.data.insert("value".into(), json!(max_val));
                        mn.data.insert(
                            "expression".into(),
                            json!({"type": "literal", "value": max_val, "width": selector_bits}),
                        );
                        self.graph.add_node(mn);
                        nodes_added.push(max_name.clone());

                        let inv_name = format!("{be_id}_be_inv_sel");
                        let mut inv = Node::with_defaults(Some(inv_name.clone()));
                        inv.data.insert("type".into(), json!("operation"));
                        inv.data.insert("bit_width".into(), json!(selector_bits));
                        inv.data.insert("operator".into(), json!("^"));
                        inv.data.insert(
                            "expression".into(),
                            json!({
                                "type": "binary_op", "operator": "^",
                                "left": {"type": "identifier", "name": &max_name},
                                "right": {"type": "identifier", "name": &selector_name}
                            }),
                        );
                        self.graph.add_node(inv);
                        nodes_added.push(inv_name.clone());

                        let e1 = Edge::new(
                            max_name,
                            inv_name.clone(),
                            None,
                            Some(HashMap::from([("type".into(), json!("left_operand"))])),
                        );
                        let e2 = Edge::new(
                            selector_name.clone(),
                            inv_name.clone(),
                            None,
                            Some(HashMap::from([("type".into(), json!("right_operand"))])),
                        );
                        self.graph.add_edge(e1);
                        self.graph.add_edge(e2);
                        inv_name
                    } else {
                        selector_name.clone()
                    };

                    // Zero padding
                    let zero_name = format!("{be_id}_zero");
                    {
                        let mut zn = Node::with_defaults(Some(zero_name.clone()));
                        zn.data.insert("type".into(), json!("literal"));
                        zn.data.insert("bit_width".into(), json!(position_bits));
                        zn.data.insert("value".into(), json!(0));
                        zn.data.insert(
                            "expression".into(),
                            json!({"type": "literal", "value": 0, "width": position_bits}),
                        );
                        self.graph.add_node(zn);
                        nodes_added.push(zero_name.clone());
                    }

                    let shift_name = format!("{be_id}_shift");
                    {
                        let mut sn = Node::with_defaults(Some(shift_name.clone()));
                        sn.data.insert("type".into(), json!("concatenation"));
                        sn.data.insert("name".into(), json!(&shift_name));
                        sn.data
                            .insert("bit_width".into(), json!(selector_bits + position_bits));
                        sn.data.insert(
                            "expression".into(),
                            json!({
                                "type": "concatenation",
                                "expressions": [
                                    {"type": "identifier", "name": &be_sel_id},
                                    {"type": "literal", "value": 0, "width": position_bits}
                                ]
                            }),
                        );
                        self.graph.add_node(sn);
                        nodes_added.push(shift_name.clone());

                        let e1 = Edge::new(
                            be_sel_id,
                            shift_name.clone(),
                            None,
                            Some(HashMap::from([
                                ("type".into(), json!("concatenation_input")),
                                ("position".into(), json!(0)),
                            ])),
                        );
                        let e2 = Edge::new(
                            zero_name,
                            shift_name.clone(),
                            None,
                            Some(HashMap::from([
                                ("type".into(), json!("concatenation_input")),
                                ("position".into(), json!(1)),
                            ])),
                        );
                        self.graph.add_edge(e1);
                        self.graph.add_edge(e2);
                    }
                    shift_name
                }
            };

            // Update the be_node to be a shift operation
            {
                let node = self.graph.nodes.get_mut(&be_id).unwrap();
                node.data.insert("type".into(), json!("operation"));
                node.data.insert("operator".into(), json!("<<"));
                node.data.insert(
                    "display_name".into(),
                    json!(format!("{base_mask_name} << {be_shift_amount_id}")),
                );
                node.data.insert(
                    "expression".into(),
                    json!({
                        "type": "binary_op", "operator": "<<",
                        "left": {"type": "identifier", "name": &base_mask_name},
                        "right": {"type": "identifier", "name": &be_shift_amount_id}
                    }),
                );
            }
            nodes_updated.push(be_id.clone());

            // Remove old incoming edges
            let old_edges: Vec<String> = self.graph.nodes[&be_id]
                .incoming_edges
                .iter()
                .cloned()
                .collect();
            for eid in old_edges {
                self.graph.remove_edge(&eid);
            }

            // Add new operand edges
            let e1 = Edge::new(
                base_mask_name.clone(),
                be_id.clone(),
                None,
                Some(HashMap::from([("type".into(), json!("left_operand"))])),
            );
            let e2 = Edge::new(
                be_shift_amount_id,
                be_id.clone(),
                None,
                Some(HashMap::from([("type".into(), json!("right_operand"))])),
            );
            self.graph.add_edge(e1);
            self.graph.add_edge(e2);

            // Store byte enable mapping
            if let Some(ref instr) = instruction {
                store_byte_enables.insert(instr.clone(), be_id.clone());
            }

            transformed_count += 1;
        }

        // Store mappings on write port node
        if let Some(wp_id) = write_port_id {
            if !store_byte_enables.is_empty() {
                let be_json: Value = store_byte_enables
                    .iter()
                    .map(|(k, v)| (k.clone(), json!(v)))
                    .collect::<serde_json::Map<String, Value>>()
                    .into();
                self.graph
                    .nodes
                    .get_mut(&wp_id)
                    .unwrap()
                    .data
                    .insert("store_byte_enables".into(), be_json);
            }
        }

        transformed_count
    }

    // =======================================================================
    // SERIALIZE/PARALLELIZE STRATEGY (Multi-cycle with counter)
    // =======================================================================

    fn apply_serialize_parallelize(
        &mut self,
        spec: &MemoryAccessTransformSpec,
        dry_run: bool,
    ) -> TransformResult {
        match spec.direction.as_str() {
            "forward" => self.serialize_forward(spec, dry_run),
            "reverse" => self.serialize_reverse(spec, dry_run),
            "update" => self.serialize_update(spec, dry_run),
            _ => TransformResult {
                transformed: false,
                reason: Some(format!(
                    "serialize_parallelize does not support '{}' direction",
                    spec.direction
                )),
                ..Default::default()
            },
        }
    }

    /// Forward serialization: add counter to serialize wide accesses into
    /// multiple narrow accesses over multiple cycles.
    fn serialize_forward(
        &mut self,
        spec: &MemoryAccessTransformSpec,
        dry_run: bool,
    ) -> TransformResult {
        let num_cycles = ((spec.current_width + spec.target_width - 1) / spec.target_width) as usize;

        log::info!(
            "Serializing {}->{} bits into {} cycles",
            spec.current_width, spec.target_width, num_cycles
        );

        if !self.graph.nodes.contains_key(&spec.memory) {
            return TransformResult {
                transformed: false,
                reason: Some(format!("Memory {} not found", spec.memory)),
                ..Default::default()
            };
        }

        let access_nodes = self.find_memory_access_nodes(&spec.memory);
        if access_nodes.is_empty() {
            return TransformResult {
                transformed: false,
                reason: Some(format!("No memory accesses found for {}", spec.memory)),
                ..Default::default()
            };
        }

        if dry_run {
            return TransformResult {
                transformed: true,
                direction: Some("forward".into()),
                old_width: Some(spec.current_width),
                new_width: Some(spec.target_width),
                dry_run: true,
                ..Default::default()
            };
        }

        // Create serialization counter
        let counter_id = self.create_access_counter(&spec.memory, num_cycles);
        let mut nodes_added = vec![counter_id.clone()];

        // Transform each memory access
        for access_id in &access_nodes {
            let added = self.transform_access_to_serialized(
                access_id, spec, &counter_id, num_cycles,
            );
            nodes_added.extend(added);
        }

        TransformResult {
            transformed: true,
            direction: Some("forward".into()),
            old_width: Some(spec.current_width),
            new_width: Some(spec.target_width),
            nodes_added,
            ..Default::default()
        }
    }

    /// Reverse serialization: remove counter to parallelize back to wide access.
    fn serialize_reverse(
        &mut self,
        spec: &MemoryAccessTransformSpec,
        dry_run: bool,
    ) -> TransformResult {
        let counter_id = format!("{}_access_counter", spec.memory);
        if !self.graph.nodes.contains_key(&counter_id) {
            return TransformResult {
                transformed: false,
                reason: Some(format!("No serialization counter found for {}", spec.memory)),
                ..Default::default()
            };
        }

        let analysis = self.analyze_serialization_structure(&spec.memory);
        if !analysis.can_parallelize {
            return TransformResult {
                transformed: false,
                reason: Some(analysis.reason.unwrap_or_else(|| "Cannot parallelize".into())),
                ..Default::default()
            };
        }

        if dry_run {
            return TransformResult {
                transformed: true,
                direction: Some("reverse".into()),
                old_width: Some(spec.current_width),
                new_width: Some(spec.target_width),
                dry_run: true,
                ..Default::default()
            };
        }

        let mut nodes_removed = Vec::new();

        // Restore direct access from serialized pattern
        if let Some(info) = &analysis.access_info {
            let removed = self.restore_direct_access(info, spec);
            nodes_removed.extend(removed);
        }

        // Remove counter
        self.graph.remove_node(&counter_id);
        nodes_removed.push(counter_id);

        TransformResult {
            transformed: true,
            direction: Some("reverse".into()),
            old_width: Some(spec.current_width),
            new_width: Some(spec.target_width),
            nodes_removed,
            ..Default::default()
        }
    }

    /// Update existing serialization: change counter width for new granularity.
    fn serialize_update(
        &mut self,
        spec: &MemoryAccessTransformSpec,
        dry_run: bool,
    ) -> TransformResult {
        let counter_id = format!("{}_access_counter", spec.memory);
        if !self.graph.nodes.contains_key(&counter_id) {
            return TransformResult {
                transformed: false,
                reason: Some(format!("No serialization counter found for {}", spec.memory)),
                ..Default::default()
            };
        }

        let analysis = self.analyze_serialization_structure(&spec.memory);
        if !analysis.can_parallelize {
            return TransformResult {
                transformed: false,
                reason: Some(analysis.reason.unwrap_or_else(|| "Cannot analyze serialization".into())),
                ..Default::default()
            };
        }

        // Get original wide width from merge node
        let original_wide_width = analysis.access_info.as_ref()
            .and_then(|info| info.merge_node_id.as_ref())
            .and_then(|mid| self.graph.nodes.get(mid))
            .and_then(|n| n.data.get("output_width"))
            .and_then(|v| v.as_i64())
            .unwrap_or(spec.current_width);

        let new_num_cycles = ((original_wide_width + spec.target_width - 1) / spec.target_width) as usize;

        if dry_run {
            return TransformResult {
                transformed: true,
                direction: Some("update".into()),
                old_width: Some(spec.current_width),
                new_width: Some(spec.target_width),
                nodes_updated: vec![counter_id.clone()],
                dry_run: true,
                ..Default::default()
            };
        }

        // Update counter
        let counter_width = ((new_num_cycles + 1) as f64).log2().ceil() as i64;
        if let Some(counter) = self.graph.nodes.get_mut(&counter_id) {
            counter.data.insert("max_count".into(), json!((new_num_cycles as i64) - 1));
            counter.data.insert("bit_width".into(), json!(counter_width));
            counter.data.insert("granularity".into(), json!(spec.target_width));
        }

        let mut nodes_updated = vec![counter_id.clone()];

        // If cycle count changed, remove old nodes and recreate
        if let Some(info) = &analysis.access_info {
            let old_count = info.narrow_access_ids.len();
            if old_count != new_num_cycles {
                // Remove old serialization nodes
                for nid in &info.narrow_access_ids {
                    self.graph.remove_node(nid);
                }
                for nid in &info.offset_node_ids {
                    self.graph.remove_node(nid);
                }
                if let Some(mid) = &info.merge_node_id {
                    self.graph.remove_node(mid);
                }

                // Recreate with new granularity
                if let Some(orig_id) = &info.original_access_id {
                    if self.graph.nodes.contains_key(orig_id) {
                        let update_spec = MemoryAccessTransformSpec {
                            memory: spec.memory.clone(),
                            strategy: spec.strategy.clone(),
                            current_width: original_wide_width,
                            target_width: spec.target_width,
                            direction: spec.direction.clone(),
                            merge_from: spec.merge_from.clone(),
                            endianness: spec.endianness.clone(),
                            alignment: spec.alignment.clone(),
                        };
                        let added = self.transform_access_to_serialized(
                            orig_id, &update_spec, &counter_id, new_num_cycles,
                        );
                        nodes_updated.extend(added);
                    }
                }
            } else {
                // Same cycle count, just update widths
                for nid in &info.narrow_access_ids {
                    if let Some(n) = self.graph.nodes.get_mut(nid) {
                        n.data.insert("bit_width".into(), json!(spec.target_width));
                    }
                }
                if let Some(mid) = &info.merge_node_id {
                    if let Some(n) = self.graph.nodes.get_mut(mid) {
                        n.data.insert("word_width".into(), json!(spec.target_width));
                        n.data.insert("num_words".into(), json!(new_num_cycles));
                    }
                }
                nodes_updated.extend(info.narrow_access_ids.clone());
            }
        }

        TransformResult {
            transformed: true,
            direction: Some("update".into()),
            old_width: Some(spec.current_width),
            new_width: Some(spec.target_width),
            nodes_updated,
            ..Default::default()
        }
    }

    // -----------------------------------------------------------------------
    // Serialize/Parallelize helpers
    // -----------------------------------------------------------------------

    /// Find serialization counter for a memory.
    fn find_serialization_counter(&self, memory: &str) -> Option<&Node> {
        self.graph.nodes.get(&format!("{}_access_counter", memory))
    }

    /// Create serialization counter node.
    fn create_access_counter(&mut self, memory: &str, num_cycles: usize) -> String {
        let counter_id = format!("{memory}_access_counter");
        let counter_width = ((num_cycles + 1) as f64).log2().ceil() as i64;

        let mut node = Node::with_defaults(Some(counter_id.clone()));
        node.data.insert("type".into(), json!("memory_access_counter"));
        node.data.insert("name".into(), json!(&counter_id));
        node.data.insert("bit_width".into(), json!(counter_width));
        node.data.insert("max_count".into(), json!((num_cycles as i64) - 1));
        node.data.insert("memory".into(), json!(memory));
        node.is_arch_state = true;
        node.uarch_time = Some(0);
        self.graph.add_node(node);

        log::info!("  Created counter: {} (width={}, max={})", counter_id, counter_width, num_cycles - 1);
        counter_id
    }

    /// Transform a single memory access into serialized form.
    fn transform_access_to_serialized(
        &mut self,
        access_id: &str,
        spec: &MemoryAccessTransformSpec,
        counter_id: &str,
        num_cycles: usize,
    ) -> Vec<String> {
        let access_mode = self.graph.nodes.get(access_id)
            .and_then(|n| n.data.get("access_mode"))
            .and_then(|v| v.as_str())
            .unwrap_or("read")
            .to_string();
        let bytes_per_access = (spec.target_width / 8) as usize;
        let mut nodes_added = Vec::new();

        // Step 1: Create narrow memory access nodes (one per cycle)
        let narrow_ids = self.create_narrow_memory_accesses(access_id, spec, num_cycles);
        nodes_added.extend(narrow_ids.clone());

        // Step 2: Create address offset nodes
        let offset_ids = self.create_address_offset_logic(
            access_id, spec, num_cycles, bytes_per_access,
        );
        nodes_added.extend(offset_ids.clone());

        // Step 3: Connect offsets to narrow accesses
        for (i, (offset_id, narrow_id)) in offset_ids.iter().zip(narrow_ids.iter()).enumerate() {
            let mut edata = HashMap::new();
            edata.insert("type".into(), json!("memory_address"));
            edata.insert("cycle".into(), json!(i));
            let edge = Edge::new(offset_id.clone(), narrow_id.clone(), None, Some(edata));
            self.graph.add_edge(edge);
        }

        if access_mode == "read" {
            // Step 4: Create data merge logic
            let merge_id = self.create_data_merge_logic(
                access_id, &narrow_ids, spec, counter_id, num_cycles,
            );
            nodes_added.push(merge_id.clone());

            // Step 5: Redirect destinations
            self.redirect_read_destinations(access_id, &merge_id);
        } else {
            // Write: create data slices
            let write_data_id = self.find_write_data_source(access_id);
            if let Some(wd_id) = write_data_id {
                let slice_ids = self.create_write_data_slices(
                    access_id, &wd_id, spec, num_cycles,
                );
                // Connect slices to narrow writes
                for (i, (narrow_id, slice_id)) in narrow_ids.iter().zip(slice_ids.iter()).enumerate() {
                    let mut edata = HashMap::new();
                    edata.insert("type".into(), json!("assignment"));
                    edata.insert("cycle".into(), json!(i));
                    let edge = Edge::new(slice_id.clone(), narrow_id.clone(), None, Some(edata));
                    self.graph.add_edge(edge);
                }
                nodes_added.extend(slice_ids);
            }
        }

        nodes_added
    }

    /// Create narrow memory access nodes (one per word/cycle).
    fn create_narrow_memory_accesses(
        &mut self,
        access_id: &str,
        spec: &MemoryAccessTransformSpec,
        num_cycles: usize,
    ) -> Vec<String> {
        let access_mode = self.graph.nodes.get(access_id)
            .and_then(|n| n.data.get("access_mode"))
            .and_then(|v| v.as_str())
            .unwrap_or("read")
            .to_string();
        let suffix = if access_mode == "write" { "wr" } else { "rd" };
        let mut ids = Vec::new();

        for i in 0..num_cycles {
            let name = format!("{}_narrow_{suffix}_word{i}", spec.memory);
            let mut node = Node::with_defaults(Some(name.clone()));
            node.data.insert("type".into(), json!("array_access"));
            node.data.insert("name".into(), json!(&name));
            node.data.insert("memory".into(), json!(&spec.memory));
            node.data.insert("word_index".into(), json!(i));
            node.data.insert("access_mode".into(), json!(&access_mode));
            node.data.insert("bit_width".into(), json!(spec.target_width));
            node.data.insert("word_width".into(), json!(spec.target_width));
            node.data.insert("original_access".into(), json!(access_id));
            node.data.insert("original_width".into(), json!(spec.current_width));
            node.data.insert("is_narrow_access".into(), json!(true));
            node.is_arch_state = true;
            node.uarch_time = Some(i as i64);
            self.graph.add_node(node);
            ids.push(name);
        }
        ids
    }

    /// Create address offset logic: addr, addr+bytes, addr+2*bytes, etc.
    fn create_address_offset_logic(
        &mut self,
        access_id: &str,
        spec: &MemoryAccessTransformSpec,
        num_cycles: usize,
        bytes_per_access: usize,
    ) -> Vec<String> {
        // Find base address node from incoming array_index edges
        let base_addr_id = {
            let node = match self.graph.nodes.get(access_id) {
                Some(n) => n,
                None => return Vec::new(),
            };
            let mut found = None;
            for eid in &node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(eid) {
                    let etype = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                    if etype == "array_index" {
                        // Skip if source is the memory node itself
                        let src_is_mem = self.graph.nodes.get(&edge.source)
                            .and_then(|n| n.data.get("is_memory"))
                            .and_then(|v| v.as_bool())
                            .unwrap_or(false);
                        if !src_is_mem {
                            found = Some(edge.source.clone());
                            break;
                        }
                    }
                }
            }
            found
        };

        let mut offset_ids = Vec::new();
        for i in 0..num_cycles {
            let byte_offset = i * bytes_per_access;
            let offset_name = format!("{access_id}_offset_{i}");

            let mut node = Node::with_defaults(Some(offset_name.clone()));
            node.data.insert("type".into(), json!("address_offset"));
            node.data.insert("name".into(), json!(&offset_name));
            node.data.insert("word_index".into(), json!(i));
            node.data.insert("byte_offset".into(), json!(byte_offset));
            node.data.insert("memory".into(), json!(&spec.memory));
            if let Some(ref ba) = base_addr_id {
                node.data.insert("base_address".into(), json!(ba));
                node.data.insert("display_name".into(),
                    json!(if byte_offset > 0 { format!("{ba}+{byte_offset}") } else { ba.clone() }));
            }
            node.is_arch_state = true;
            self.graph.add_node(node);

            // Connect base address to offset
            if let Some(ref ba) = base_addr_id {
                let mut edata = HashMap::new();
                edata.insert("type".into(),
                    json!(if byte_offset > 0 { "address_with_offset" } else { "base_address" }));
                edata.insert("offset".into(), json!(byte_offset));
                let edge = Edge::new(ba.clone(), offset_name.clone(), None, Some(edata));
                self.graph.add_edge(edge);
            }

            offset_ids.push(offset_name);
        }
        offset_ids
    }

    /// Create merge logic to combine narrow reads into wide result.
    fn create_data_merge_logic(
        &mut self,
        access_id: &str,
        narrow_ids: &[String],
        spec: &MemoryAccessTransformSpec,
        counter_id: &str,
        num_cycles: usize,
    ) -> String {
        let merge_id = format!("{}_data_merge", spec.memory);
        let mut node = Node::with_defaults(Some(merge_id.clone()));
        node.data.insert("type".into(), json!("memory_data_merge"));
        node.data.insert("name".into(), json!(&merge_id));
        node.data.insert("memory".into(), json!(&spec.memory));
        node.data.insert("num_words".into(), json!(num_cycles));
        node.data.insert("word_width".into(), json!(spec.target_width));
        node.data.insert("output_width".into(), json!(spec.current_width));
        node.data.insert("original_access".into(), json!(access_id));
        node.is_arch_state = true;
        node.uarch_time = Some((num_cycles - 1) as i64);
        self.graph.add_node(node);

        // Connect narrow reads to merge
        for (i, nid) in narrow_ids.iter().enumerate() {
            let mut edata = HashMap::new();
            edata.insert("type".into(), json!("memory_word"));
            edata.insert("word_index".into(), json!(i));
            let edge = Edge::new(nid.clone(), merge_id.clone(), None, Some(edata));
            self.graph.add_edge(edge);
        }

        // Connect counter to merge
        let mut edata = HashMap::new();
        edata.insert("type".into(), json!("merge_enable"));
        edata.insert("condition".into(), json!(format!("{counter_id} == {}", num_cycles - 1)));
        let edge = Edge::new(counter_id.to_string(), merge_id.clone(), None, Some(edata));
        self.graph.add_edge(edge);

        merge_id
    }

    /// Redirect edges from original access to merge node.
    fn redirect_read_destinations(&mut self, original_id: &str, merge_id: &str) {
        // Collect assignment edges to redirect
        let edges_to_redirect: Vec<(String, String)> = {
            let node = match self.graph.nodes.get(original_id) {
                Some(n) => n,
                None => return,
            };
            node.outgoing_edges.iter()
                .filter_map(|eid| {
                    let edge = self.graph.edges.get(eid)?;
                    let etype = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                    if etype == "assignment" {
                        Some((eid.clone(), edge.target.clone()))
                    } else {
                        None
                    }
                })
                .collect()
        };

        for (old_eid, target_id) in &edges_to_redirect {
            // Create new edge from merge to destination
            let mut edata = HashMap::new();
            edata.insert("type".into(), json!("assignment"));
            edata.insert("from_serialized".into(), json!(true));
            edata.insert("original_access".into(), json!(original_id));
            let edge = Edge::new(merge_id.to_string(), target_id.clone(), None, Some(edata));
            self.graph.add_edge(edge);

            // Remove old edge
            self.graph.remove_edge(old_eid);
        }
    }

    /// Find source of data being written to memory.
    fn find_write_data_source(&self, access_id: &str) -> Option<String> {
        let node = self.graph.nodes.get(access_id)?;
        for eid in &node.incoming_edges {
            if let Some(edge) = self.graph.edges.get(eid) {
                let etype = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                if etype == "assignment" {
                    return Some(edge.source.clone());
                }
            }
        }
        None
    }

    /// Create bit slice nodes for write data, splitting wide data into narrow slices.
    fn create_write_data_slices(
        &mut self,
        access_id: &str,
        write_data_id: &str,
        spec: &MemoryAccessTransformSpec,
        num_cycles: usize,
    ) -> Vec<String> {
        let mut ids = Vec::new();
        for i in 0..num_cycles {
            let low_bit = (i as i64) * spec.target_width;
            let high_bit = std::cmp::min(((i + 1) as i64) * spec.target_width - 1, spec.current_width - 1);
            let slice_id = format!("{access_id}_data_slice_{i}");

            let mut node = Node::with_defaults(Some(slice_id.clone()));
            node.data.insert("type".into(), json!("write_data_slice"));
            node.data.insert("name".into(), json!(&slice_id));
            node.data.insert("source_data".into(), json!(write_data_id));
            node.data.insert("slice_index".into(), json!(i));
            node.data.insert("high_bit".into(), json!(high_bit));
            node.data.insert("low_bit".into(), json!(low_bit));
            node.data.insert("slice_width".into(), json!(high_bit - low_bit + 1));
            node.data.insert("memory".into(), json!(&spec.memory));
            node.is_arch_state = true;
            node.uarch_time = Some(i as i64);
            self.graph.add_node(node);

            // Connect write data to slice
            let mut edata = HashMap::new();
            edata.insert("type".into(), json!("bit_slice"));
            edata.insert("slice_index".into(), json!(i));
            let edge = Edge::new(write_data_id.to_string(), slice_id.clone(), None, Some(edata));
            self.graph.add_edge(edge);

            ids.push(slice_id);
        }
        ids
    }

    /// Analyze existing serialization structure for reverse/update.
    fn analyze_serialization_structure(&self, memory: &str) -> SerializationAnalysis {
        let counter_id = format!("{memory}_access_counter");
        let num_cycles = self.graph.nodes.get(&counter_id)
            .and_then(|n| n.data.get("max_count"))
            .and_then(|v| v.as_i64())
            .map(|m| (m + 1) as usize)
            .unwrap_or(0);

        // Find narrow access nodes
        let narrow_ids: Vec<String> = self.graph.nodes.iter()
            .filter(|(_, n)| {
                n.data.get("type").and_then(|v| v.as_str()) == Some("array_access")
                    && n.data.get("is_narrow_access").and_then(|v| v.as_bool()).unwrap_or(false)
                    && n.data.get("memory").and_then(|v| v.as_str()) == Some(memory)
            })
            .map(|(id, _)| id.clone())
            .collect();

        if narrow_ids.is_empty() {
            return SerializationAnalysis {
                can_parallelize: false,
                reason: Some("No narrow memory accesses found".into()),
                access_info: None,
            };
        }

        // Find merge node
        let merge_id: Option<String> = self.graph.nodes.iter()
            .find(|(_, n)| {
                n.data.get("type").and_then(|v| v.as_str()) == Some("memory_data_merge")
                    && n.data.get("memory").and_then(|v| v.as_str()) == Some(memory)
            })
            .map(|(id, _)| id.clone());

        if merge_id.is_none() {
            return SerializationAnalysis {
                can_parallelize: false,
                reason: Some("No merge node found".into()),
                access_info: None,
            };
        }

        // Find original access
        let original_id = merge_id.as_ref()
            .and_then(|mid| self.graph.nodes.get(mid))
            .and_then(|n| n.data.get("original_access"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        // Find offset nodes
        let offset_ids: Vec<String> = self.graph.nodes.iter()
            .filter(|(_, n)| {
                n.data.get("type").and_then(|v| v.as_str()) == Some("address_offset")
                    && n.data.get("memory").and_then(|v| v.as_str()) == Some(memory)
            })
            .map(|(id, _)| id.clone())
            .collect();

        SerializationAnalysis {
            can_parallelize: true,
            reason: None,
            access_info: Some(SerializationAccessInfo {
                narrow_access_ids: narrow_ids,
                merge_node_id: merge_id,
                original_access_id: original_id,
                offset_node_ids: offset_ids,
                num_cycles,
            }),
        }
    }

    /// Restore direct wide access from serialized pattern.
    fn restore_direct_access(
        &mut self,
        info: &SerializationAccessInfo,
        spec: &MemoryAccessTransformSpec,
    ) -> Vec<String> {
        let mut nodes_removed = Vec::new();

        // If original access exists, reconnect destinations
        if let Some(orig_id) = &info.original_access_id {
            if self.graph.nodes.contains_key(orig_id) {
                // Update width
                if let Some(n) = self.graph.nodes.get_mut(orig_id) {
                    n.data.insert("bit_width".into(), json!(spec.target_width));
                }

                // Find merge destinations and reconnect
                if let Some(merge_id) = &info.merge_node_id {
                    let destinations: Vec<String> = {
                        let merge = match self.graph.nodes.get(merge_id) {
                            Some(n) => n,
                            None => return nodes_removed,
                        };
                        merge.outgoing_edges.iter()
                            .filter_map(|eid| {
                                let edge = self.graph.edges.get(eid)?;
                                let etype = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                                if etype == "assignment" { Some(edge.target.clone()) } else { None }
                            })
                            .collect()
                    };

                    // Remove old edges from merge, add new from original
                    for dest_id in &destinations {
                        let old_eids: Vec<String> = self.graph.nodes.get(merge_id)
                            .map(|n| n.outgoing_edges.iter()
                                .filter(|eid| {
                                    self.graph.edges.get(*eid)
                                        .map(|e| e.target == *dest_id)
                                        .unwrap_or(false)
                                })
                                .cloned()
                                .collect())
                            .unwrap_or_default();
                        for eid in old_eids {
                            self.graph.remove_edge(&eid);
                        }

                        let mut edata = HashMap::new();
                        edata.insert("type".into(), json!("assignment"));
                        edata.insert("from_parallelized".into(), json!(true));
                        let edge = Edge::new(orig_id.clone(), dest_id.clone(), None, Some(edata));
                        self.graph.add_edge(edge);
                    }
                }
            }
        }

        // Remove all serialization nodes
        for nid in &info.narrow_access_ids {
            self.graph.remove_node(nid);
            nodes_removed.push(nid.clone());
        }
        for nid in &info.offset_node_ids {
            self.graph.remove_node(nid);
            nodes_removed.push(nid.clone());
        }
        if let Some(mid) = &info.merge_node_id {
            self.graph.remove_node(mid);
            nodes_removed.push(mid.clone());
        }

        nodes_removed
    }

    // =======================================================================
    // SPLIT/MERGE STRATEGY (Multi-port without counter)
    // =======================================================================

    fn apply_split_merge(
        &mut self,
        spec: &MemoryAccessTransformSpec,
        dry_run: bool,
    ) -> TransformResult {
        match spec.direction.as_str() {
            "forward" => self.split_forward(spec, dry_run),
            "reverse" => self.merge_reverse(spec, dry_run),
            _ => TransformResult {
                transformed: false,
                reason: Some("split_merge does not support 'update' direction".into()),
                ..Default::default()
            },
        }
    }

    /// Forward split: create multiple parallel ports from a wide access.
    /// All ports accessed in the SAME cycle (no counter).
    fn split_forward(
        &mut self,
        spec: &MemoryAccessTransformSpec,
        dry_run: bool,
    ) -> TransformResult {
        let num_ports = ((spec.current_width + spec.target_width - 1) / spec.target_width) as usize;

        log::info!(
            "Splitting {}->{} bits into {} parallel ports",
            spec.current_width, spec.target_width, num_ports
        );

        if !self.graph.nodes.contains_key(&spec.memory) {
            return TransformResult {
                transformed: false,
                reason: Some(format!("Memory {} not found", spec.memory)),
                ..Default::default()
            };
        }

        let access_nodes = self.find_memory_access_nodes(&spec.memory);
        if access_nodes.is_empty() {
            return TransformResult {
                transformed: false,
                reason: Some(format!("No memory accesses found for {}", spec.memory)),
                ..Default::default()
            };
        }

        if dry_run {
            return TransformResult {
                transformed: true,
                direction: Some("forward".into()),
                old_width: Some(spec.current_width),
                new_width: Some(spec.target_width),
                dry_run: true,
                ..Default::default()
            };
        }

        let mut nodes_added = Vec::new();
        for access_id in &access_nodes {
            let added = self.transform_access_to_split_ports(access_id, spec, num_ports);
            nodes_added.extend(added);
        }

        TransformResult {
            transformed: true,
            direction: Some("forward".into()),
            old_width: Some(spec.current_width),
            new_width: Some(spec.target_width),
            nodes_added,
            ..Default::default()
        }
    }

    /// Transform a single memory access into split parallel ports.
    fn transform_access_to_split_ports(
        &mut self,
        access_id: &str,
        spec: &MemoryAccessTransformSpec,
        num_ports: usize,
    ) -> Vec<String> {
        let access_mode = self.graph.nodes.get(access_id)
            .and_then(|n| n.data.get("access_mode"))
            .and_then(|v| v.as_str())
            .unwrap_or("read")
            .to_string();
        let bytes_per_port = (spec.target_width / 8) as usize;
        let mut nodes_added = Vec::new();

        // Step 1: Create memory port nodes
        let port_ids = self.create_memory_port_nodes(spec, num_ports);
        nodes_added.extend(port_ids.clone());

        // Step 2: Create address offset nodes for each port
        let base_addr_id = {
            let node = match self.graph.nodes.get(access_id) {
                Some(n) => n,
                None => return nodes_added,
            };
            let mut found = None;
            for eid in &node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(eid) {
                    let etype = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                    if etype == "array_index" {
                        let src_is_mem = self.graph.nodes.get(&edge.source)
                            .and_then(|n| n.data.get("is_memory"))
                            .and_then(|v| v.as_bool())
                            .unwrap_or(false);
                        if !src_is_mem {
                            found = Some(edge.source.clone());
                            break;
                        }
                    }
                }
            }
            found
        };

        if let Some(ref ba_id) = base_addr_id {
            for i in 0..num_ports {
                let byte_offset = i * bytes_per_port;
                let offset_id = format!("{access_id}_port{i}_offset");

                let mut node = Node::with_defaults(Some(offset_id.clone()));
                node.data.insert("type".into(), json!("port_address_offset"));
                node.data.insert("name".into(), json!(&offset_id));
                node.data.insert("base_address".into(), json!(ba_id));
                node.data.insert("port_index".into(), json!(i));
                node.data.insert("byte_offset".into(), json!(byte_offset));
                node.data.insert("memory".into(), json!(&spec.memory));
                node.data.insert("display_name".into(),
                    json!(if byte_offset > 0 { format!("{ba_id}+{byte_offset}") } else { ba_id.clone() }));
                node.uarch_time = Some(0); // All in same cycle
                self.graph.add_node(node);

                // Connect base address to offset
                let mut edata = HashMap::new();
                edata.insert("type".into(),
                    json!(if byte_offset > 0 { "address_with_offset" } else { "base_address" }));
                edata.insert("offset".into(), json!(byte_offset));
                let edge = Edge::new(ba_id.clone(), offset_id.clone(), None, Some(edata));
                self.graph.add_edge(edge);

                // Connect offset to port
                let mut edata2 = HashMap::new();
                edata2.insert("type".into(), json!("memory_address"));
                edata2.insert("port".into(), json!(i));
                let edge2 = Edge::new(offset_id.clone(), port_ids[i].clone(), None, Some(edata2));
                self.graph.add_edge(edge2);

                nodes_added.push(offset_id);
            }
        }

        if access_mode == "read" {
            // Create port merge logic (parallel reads)
            let merge_id = self.create_port_merge_logic(access_id, &port_ids, spec, num_ports);
            nodes_added.push(merge_id.clone());

            // Redirect original read destinations
            self.redirect_read_destinations(access_id, &merge_id);
        } else {
            // Write: create data slices and connect to ports
            let write_data_id = self.find_write_data_source(access_id);
            if let Some(wd_id) = write_data_id {
                let slice_ids = self.create_write_data_slices(
                    access_id, &wd_id, spec, num_ports,
                );
                for (i, (port_id, slice_id)) in port_ids.iter().zip(slice_ids.iter()).enumerate() {
                    let mut edata = HashMap::new();
                    edata.insert("type".into(), json!("assignment"));
                    edata.insert("port".into(), json!(i));
                    let edge = Edge::new(slice_id.clone(), port_id.clone(), None, Some(edata));
                    self.graph.add_edge(edge);
                }
                nodes_added.extend(slice_ids);
            }
        }

        nodes_added
    }

    /// Create separate memory port nodes for split access.
    fn create_memory_port_nodes(
        &mut self,
        spec: &MemoryAccessTransformSpec,
        num_ports: usize,
    ) -> Vec<String> {
        let mut ids = Vec::new();
        for i in 0..num_ports {
            let port_id = format!("{}_port{i}", spec.memory);
            let mut node = Node::with_defaults(Some(port_id.clone()));
            node.data.insert("type".into(), json!("isa_state mem"));
            node.data.insert("name".into(), json!(&port_id));
            node.data.insert("display_name".into(), json!(format!("{} port {i}", spec.memory)));
            node.data.insert("memory".into(), json!(&spec.memory));
            node.data.insert("port_index".into(), json!(i));
            node.data.insert("bit_width".into(), json!(spec.target_width));
            node.data.insert("original_memory".into(), json!(&spec.memory));
            node.data.insert("is_split_port".into(), json!(true));
            node.data.insert("supports_byte_enable".into(), json!(true));
            node.data.insert("supports_unaligned".into(), json!(true));
            node.data.insert("array_depth".into(), json!(1024));
            self.graph.add_node(node);
            ids.push(port_id);
        }
        ids
    }

    /// Create merge logic for parallel port reads.
    fn create_port_merge_logic(
        &mut self,
        access_id: &str,
        port_ids: &[String],
        spec: &MemoryAccessTransformSpec,
        num_ports: usize,
    ) -> String {
        let merge_id = format!("{}_port_merge", spec.memory);
        let mut node = Node::with_defaults(Some(merge_id.clone()));
        node.data.insert("type".into(), json!("port_data_merge"));
        node.data.insert("name".into(), json!(&merge_id));
        node.data.insert("memory".into(), json!(&spec.memory));
        node.data.insert("num_ports".into(), json!(num_ports));
        node.data.insert("port_width".into(), json!(spec.target_width));
        node.data.insert("output_width".into(), json!(spec.current_width));
        node.data.insert("original_access".into(), json!(access_id));
        node.data.insert("is_parallel".into(), json!(true));
        node.uarch_time = Some(0); // All in same cycle
        self.graph.add_node(node);

        // Connect port reads to merge
        for (i, pid) in port_ids.iter().enumerate() {
            let mut edata = HashMap::new();
            edata.insert("type".into(), json!("port_data"));
            edata.insert("port_index".into(), json!(i));
            let edge = Edge::new(pid.clone(), merge_id.clone(), None, Some(edata));
            self.graph.add_edge(edge);
        }

        merge_id
    }

    /// Reverse merge: merge multiple ports back into one wide port.
    fn merge_reverse(
        &mut self,
        spec: &MemoryAccessTransformSpec,
        dry_run: bool,
    ) -> TransformResult {
        if spec.merge_from.is_empty() {
            return TransformResult {
                transformed: false,
                reason: Some("No ports specified in merge_from".into()),
                ..Default::default()
            };
        }

        // Find all related ports
        let all_port_ids = self.find_related_ports(&spec.merge_from[0], &spec.memory);
        if all_port_ids.is_empty() {
            return TransformResult {
                transformed: false,
                reason: Some(format!("Could not find related ports for {}", spec.merge_from[0])),
                ..Default::default()
            };
        }

        // Find merge node
        let merge_id: Option<String> = self.graph.nodes.iter()
            .find(|(_, n)| {
                n.data.get("type").and_then(|v| v.as_str()) == Some("port_data_merge")
                    && n.data.get("memory").and_then(|v| v.as_str()) == Some(&spec.memory)
            })
            .map(|(id, _)| id.clone());

        let merge_id = match merge_id {
            Some(id) => id,
            None => return TransformResult {
                transformed: false,
                reason: Some(format!("No port merge node found for {}", spec.memory)),
                ..Default::default()
            },
        };

        // Find offset nodes
        let offset_ids: Vec<String> = self.graph.nodes.iter()
            .filter(|(_, n)| {
                n.data.get("type").and_then(|v| v.as_str()) == Some("port_address_offset")
                    && n.data.get("memory").and_then(|v| v.as_str()) == Some(&spec.memory)
            })
            .map(|(id, _)| id.clone())
            .collect();

        if dry_run {
            let mut all_removed: Vec<String> = all_port_ids.clone();
            all_removed.push(merge_id.clone());
            all_removed.extend(offset_ids.clone());
            return TransformResult {
                transformed: true,
                direction: Some("reverse".into()),
                old_width: Some(spec.current_width),
                new_width: Some(spec.target_width),
                nodes_removed: all_removed,
                dry_run: true,
                ..Default::default()
            };
        }

        // Find original access from merge metadata
        let original_id = self.graph.nodes.get(&merge_id)
            .and_then(|n| n.data.get("original_access"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        let mut nodes_removed = Vec::new();

        // Restore original access
        if let Some(ref orig_id) = original_id {
            if self.graph.nodes.contains_key(orig_id) {
                // Update width
                if let Some(n) = self.graph.nodes.get_mut(orig_id) {
                    n.data.insert("bit_width".into(), json!(spec.target_width));
                }

                // Find merge destinations and reconnect
                let destinations: Vec<String> = {
                    let merge = match self.graph.nodes.get(&merge_id) {
                        Some(n) => n,
                        None => return TransformResult { transformed: false, ..Default::default() },
                    };
                    merge.outgoing_edges.iter()
                        .filter_map(|eid| {
                            let edge = self.graph.edges.get(eid)?;
                            let etype = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                            if etype == "assignment" { Some(edge.target.clone()) } else { None }
                        })
                        .collect()
                };

                for dest_id in &destinations {
                    let old_eids: Vec<String> = self.graph.nodes.get(&merge_id)
                        .map(|n| n.outgoing_edges.iter()
                            .filter(|eid| {
                                self.graph.edges.get(*eid)
                                    .map(|e| e.target == *dest_id)
                                    .unwrap_or(false)
                            })
                            .cloned()
                            .collect())
                        .unwrap_or_default();
                    for eid in old_eids {
                        self.graph.remove_edge(&eid);
                    }

                    let mut edata = HashMap::new();
                    edata.insert("type".into(), json!("assignment"));
                    edata.insert("from_merged_ports".into(), json!(true));
                    let edge = Edge::new(orig_id.clone(), dest_id.clone(), None, Some(edata));
                    self.graph.add_edge(edge);
                }
            }
        }

        // Remove all port nodes
        for pid in &all_port_ids {
            self.graph.remove_node(pid);
            nodes_removed.push(pid.clone());
        }

        // Remove offset nodes
        for oid in &offset_ids {
            self.graph.remove_node(oid);
            nodes_removed.push(oid.clone());
        }

        // Remove merge node
        self.graph.remove_node(&merge_id);
        nodes_removed.push(merge_id);

        TransformResult {
            transformed: true,
            direction: Some("reverse".into()),
            old_width: Some(spec.current_width),
            new_width: Some(spec.target_width),
            nodes_removed,
            ..Default::default()
        }
    }

    /// Find all related memory ports by base pattern.
    fn find_related_ports(&self, port_name: &str, memory: &str) -> Vec<String> {
        let base_pattern = format!("{memory}_port");

        let mut ports: Vec<(String, i64)> = self.graph.nodes.iter()
            .filter(|(id, n)| {
                n.data.get("type").and_then(|v| v.as_str()) == Some("isa_state mem")
                    && n.data.get("is_split_port").and_then(|v| v.as_bool()).unwrap_or(false)
                    && n.data.get("memory").and_then(|v| v.as_str()) == Some(memory)
                    && id.starts_with(&base_pattern)
            })
            .map(|(id, n)| {
                let idx = n.data.get("port_index").and_then(|v| v.as_i64()).unwrap_or(0);
                (id.clone(), idx)
            })
            .collect();

        ports.sort_by_key(|(_, idx)| *idx);
        ports.into_iter().map(|(id, _)| id).collect()
    }
}

// ---------------------------------------------------------------------------
// Helper structs for serialization analysis
// ---------------------------------------------------------------------------

struct SerializationAnalysis {
    can_parallelize: bool,
    reason: Option<String>,
    access_info: Option<SerializationAccessInfo>,
}

struct SerializationAccessInfo {
    narrow_access_ids: Vec<String>,
    merge_node_id: Option<String>,
    original_access_id: Option<String>,
    offset_node_ids: Vec<String>,
    num_cycles: usize,
}
