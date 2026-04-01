//! Cache Optimization for ResourceGraph.
//!
//! Inserts read-only or read-write caches before memory nodes, redirecting
//! accesses through the cache. The cache handles hit/miss logic internally,
//! with a refill interface connecting to the original memory for cache misses.
//!
//! Follows the 7-phase optimization pattern:
//! 1. Analysis  2. Planning  3. Structure  4. Hardware
//! 5. Connection  6. Cleanup  7. Timing

use log::info;
use serde_json::{json, Value};
use std::collections::HashMap;

use crate::resource_graph::{Edge, Node, ResourceGraph};

// ---------------------------------------------------------------------------
// Edge helpers
// ---------------------------------------------------------------------------

fn make_edge(source: &str, target: &str) -> Edge {
    Edge::new(source.to_string(), target.to_string(), None, None)
}

fn make_edge_with_data(source: &str, target: &str, data: HashMap<String, Value>) -> Edge {
    Edge::new(source.to_string(), target.to_string(), None, Some(data))
}

fn typed_edge(source: &str, target: &str, edge_type: &str) -> Edge {
    let mut data = HashMap::new();
    data.insert("type".to_string(), json!(edge_type));
    make_edge_with_data(source, target, data)
}

fn cache_interface_edge(source: &str, target: &str, edge_type: &str) -> Edge {
    let mut data = HashMap::new();
    data.insert("type".to_string(), json!(edge_type));
    data.insert("cache_interface".to_string(), json!(true));
    make_edge_with_data(source, target, data)
}

fn cache_port_edge(source: &str, target: &str, edge_type: &str, port_index: usize) -> Edge {
    let mut data = HashMap::new();
    data.insert("type".to_string(), json!(edge_type));
    data.insert("port_index".to_string(), json!(port_index));
    data.insert("cache_interface".to_string(), json!(true));
    make_edge_with_data(source, target, data)
}

// ---------------------------------------------------------------------------
// Structural helpers — find pipeline nodes by pattern, not hard-coded names
// ---------------------------------------------------------------------------

/// Find the Memory-stage validity signal by structural pattern.
/// Works across pipeline depths: PIPE_Memory_valid_PIPE (5-stage),
/// PIPE_MemoryWriteback_valid_PIPE (4-stage),
/// PIPE_ExecuteMemoryWriteback_valid_PIPE (3/2-stage).
fn find_memory_stage_valid_id(graph: &ResourceGraph) -> Option<String> {
    graph.nodes.keys().find(|nid| {
        nid.starts_with("PIPE_")
            && nid.ends_with("_valid_PIPE")
            && nid["PIPE_".len()..nid.len() - "_valid_PIPE".len()].contains("Memory")
    }).cloned()
}

/// Find the Memory-stage pipeline register for a given content node.
/// Searches for PIPE_{MemoryStage}_{content_id}_PIPE where the stage contains "Memory".
fn find_memory_stage_register(graph: &ResourceGraph, content_id: &str) -> Option<String> {
    let suffix = format!("_{}_PIPE", content_id);
    graph.nodes.keys().find(|nid| {
        nid.starts_with("PIPE_")
            && nid.ends_with(&suffix)
            && {
                let stage = &nid["PIPE_".len()..nid.len() - suffix.len()];
                stage.contains("Memory")
            }
    }).cloned()
}

// ---------------------------------------------------------------------------
// ReadOnlyCacheSpec
// ---------------------------------------------------------------------------

/// Specification for read-only cache insertion.
#[derive(Debug, Clone)]
pub struct ReadOnlyCacheSpec {
    pub memory_name: String,
    pub block_size: usize,
    pub associativity: usize,
    pub num_rows: usize,
    pub address_width: usize,
    pub data_width: Option<usize>,
    pub cache_name: String,
    pub replacement_policy: String,
    pub cached_ports: Option<Vec<String>>,
}

impl ReadOnlyCacheSpec {
    pub fn new(memory_name: &str) -> Self {
        Self {
            memory_name: memory_name.to_string(),
            block_size: 32,
            associativity: 1,
            num_rows: 64,
            address_width: 32,
            data_width: None,
            cache_name: format!("{}_cache", memory_name),
            replacement_policy: "lru".to_string(),
            cached_ports: None,
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.associativity == 0 || (self.associativity & (self.associativity - 1)) != 0 {
            return Err(format!(
                "Associativity must be a power of 2, got {}",
                self.associativity
            ));
        }
        if self.num_rows == 0 || (self.num_rows & (self.num_rows - 1)) != 0 {
            return Err(format!(
                "Number of rows must be a power of 2, got {}",
                self.num_rows
            ));
        }
        if self.block_size == 0 || (self.block_size & (self.block_size - 1)) != 0 {
            return Err(format!(
                "Block size must be a power of 2, got {}",
                self.block_size
            ));
        }
        Ok(())
    }

    pub fn offset_width(&self) -> usize {
        bit_length(self.block_size - 1)
    }

    pub fn index_width(&self) -> usize {
        bit_length(self.num_rows - 1)
    }

    pub fn tag_width(&self) -> usize {
        self.address_width - self.offset_width() - self.index_width()
    }
}

// ---------------------------------------------------------------------------
// ReadWriteCacheSpec
// ---------------------------------------------------------------------------

/// Specification for read-write cache with write-through policy.
#[derive(Debug, Clone)]
pub struct ReadWriteCacheSpec {
    pub memory_name: String,
    pub block_size: usize,
    pub associativity: usize,
    pub num_rows: usize,
    pub address_width: usize,
    pub data_width: Option<usize>,
    pub cache_name: String,
    pub replacement_policy: String,
    pub cached_read_ports: Option<Vec<String>>,
    pub cached_write_ports: Option<Vec<String>>,
    pub write_allocate: bool,
    pub write_read_fwd: bool,
}

impl ReadWriteCacheSpec {
    pub fn new(memory_name: &str) -> Self {
        Self {
            memory_name: memory_name.to_string(),
            block_size: 32,
            associativity: 1,
            num_rows: 64,
            address_width: 32,
            data_width: None,
            cache_name: format!("{}_rwcache", memory_name),
            replacement_policy: "lru".to_string(),
            cached_read_ports: None,
            cached_write_ports: None,
            write_allocate: false,
            write_read_fwd: false,
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.associativity == 0 || (self.associativity & (self.associativity - 1)) != 0 {
            return Err(format!(
                "Associativity must be a power of 2, got {}",
                self.associativity
            ));
        }
        if self.num_rows == 0 || (self.num_rows & (self.num_rows - 1)) != 0 {
            return Err(format!(
                "Number of rows must be a power of 2, got {}",
                self.num_rows
            ));
        }
        if self.block_size == 0 || (self.block_size & (self.block_size - 1)) != 0 {
            return Err(format!(
                "Block size must be a power of 2, got {}",
                self.block_size
            ));
        }
        let valid = ["lru", "random", "fifo"];
        if !valid.contains(&self.replacement_policy.as_str()) {
            return Err(format!(
                "Replacement policy must be one of {:?}, got {}",
                valid, self.replacement_policy
            ));
        }
        Ok(())
    }

    pub fn offset_width(&self) -> usize {
        bit_length(self.block_size - 1)
    }

    pub fn index_width(&self) -> usize {
        bit_length(self.num_rows - 1)
    }

    pub fn tag_width(&self) -> usize {
        self.address_width - self.offset_width() - self.index_width()
    }
}

fn bit_length(v: usize) -> usize {
    if v == 0 {
        0
    } else {
        (usize::BITS - v.leading_zeros()) as usize
    }
}

// ---------------------------------------------------------------------------
// Internal analysis structs
// ---------------------------------------------------------------------------

struct ReadAccessInfo {
    array_access_node_id: String,
    address_node_id: Option<String>,
    memory_edge_id: Option<String>,
    #[allow(dead_code)]
    target_edge_ids: Vec<String>,
}

struct ROAnalysis {
    memory_node_id: String,
    bit_width: usize,
    #[allow(dead_code)]
    addr_width: usize,
    read_accesses: Vec<ReadAccessInfo>,
}

struct RWAnalysis {
    memory_node_id: String,
    bit_width: usize,
    #[allow(dead_code)]
    addr_width: usize,
    read_accesses: Vec<ReadAccessInfo>,
    write_port_id: Option<String>,
}

struct CacheParams {
    data_width: usize,
    #[allow(dead_code)]
    address_width: usize,
    tag_width: usize,
    index_width: usize,
    offset_width: usize,
    num_read_ports: usize,
    has_write_port: bool,
}

// ---------------------------------------------------------------------------
// ReadOnlyCacheOptimization
// ---------------------------------------------------------------------------

/// Inserts a read-only cache before a memory node.
pub struct ReadOnlyCacheOptimization<'a> {
    graph: &'a mut ResourceGraph,
}

impl<'a> ReadOnlyCacheOptimization<'a> {
    pub fn new(graph: &'a mut ResourceGraph) -> Self {
        Self { graph }
    }

    pub fn apply(&mut self, spec: &mut ReadOnlyCacheSpec) -> bool {
        info!("Applying read-only cache optimization for {}", spec.memory_name);

        if let Err(e) = spec.validate() {
            info!("Spec validation failed: {}", e);
            return false;
        }

        // Phase 1: Analysis
        let analysis = match self.analyze(spec) {
            Some(a) => a,
            None => return false,
        };

        // Phase 2: Planning
        let params = self.plan(spec, &analysis);
        info!(
            "  Cache parameters: tag={}b, index={}b, offset={}b",
            params.tag_width, params.index_width, params.offset_width
        );

        // Phase 3: Structure
        let cache_node_id = self.build_structure(spec, &params);
        info!("  Created cache node: {}", cache_node_id);

        // Phase 4: Hardware (backend handles internals)

        // Phase 5: Connection
        self.wire_components(spec, &cache_node_id, &analysis, &params);
        info!("  Wired {} read port(s) to cache", analysis.read_accesses.len());

        // Phase 5b: Flush signals
        self.wire_flush_signals(&cache_node_id, &spec.cache_name);

        // Phase 6: Cleanup
        self.graph.cleanup_disconnected_nodes();

        // Phase 7: Timing
        self.graph.infer_uarch_time(true);
        info!("  Updated timing with variable_latency=True");

        info!(
            "Successfully added cache '{}' before memory '{}'",
            spec.cache_name, spec.memory_name
        );
        true
    }

    // -----------------------------------------------------------------------
    // Phase 1: Analysis
    // -----------------------------------------------------------------------

    fn analyze(&self, spec: &ReadOnlyCacheSpec) -> Option<ROAnalysis> {
        let memory_node_id = find_memory_node_in_graph(self.graph, &spec.memory_name)?;

        let node = self.graph.nodes.get(&memory_node_id)?;
        let bit_width = node
            .data
            .get("bit_width")
            .and_then(|v| v.as_u64())
            .unwrap_or(32) as usize;
        let addr_width = node
            .data
            .get("array_depth")
            .and_then(|v| v.as_u64())
            .unwrap_or(10) as usize;

        info!("  Found memory '{}': {}b data, {}b addr", spec.memory_name, bit_width, addr_width);

        let read_accesses =
            find_read_accesses_in_graph(self.graph, &spec.memory_name, &spec.cached_ports, false);

        if read_accesses.is_empty() {
            info!("Error: No read accesses found for memory '{}'", spec.memory_name);
            return None;
        }

        info!("  Read accesses: {}", read_accesses.len());

        Some(ROAnalysis {
            memory_node_id,
            bit_width,
            addr_width,
            read_accesses,
        })
    }

    // -----------------------------------------------------------------------
    // Phase 2: Planning
    // -----------------------------------------------------------------------

    fn plan(&self, spec: &mut ReadOnlyCacheSpec, analysis: &ROAnalysis) -> CacheParams {
        let data_width = spec.data_width.unwrap_or(analysis.bit_width);
        spec.data_width = Some(data_width);

        CacheParams {
            data_width,
            address_width: spec.address_width,
            tag_width: spec.tag_width(),
            index_width: spec.index_width(),
            offset_width: spec.offset_width(),
            num_read_ports: analysis.read_accesses.len(),
            has_write_port: false,
        }
    }

    // -----------------------------------------------------------------------
    // Phase 3: Structure
    // -----------------------------------------------------------------------

    fn build_structure(&mut self, spec: &ReadOnlyCacheSpec, params: &CacheParams) -> String {
        let cache_name = &spec.cache_name;

        let mut cache_node = Node::with_defaults(Some(cache_name.clone()));
        cache_node.data.insert("type".to_string(), json!("read_only_cache"));
        cache_node.data.insert("name".to_string(), json!(cache_name));
        cache_node.data.insert("display_name".to_string(), json!(cache_name));
        cache_node.data.insert("memory_name".to_string(), json!(&spec.memory_name));
        cache_node.data.insert("block_size".to_string(), json!(spec.block_size));
        cache_node.data.insert("associativity".to_string(), json!(spec.associativity));
        cache_node.data.insert("num_rows".to_string(), json!(spec.num_rows));
        cache_node.data.insert("address_width".to_string(), json!(spec.address_width));
        cache_node.data.insert("data_width".to_string(), json!(params.data_width));
        cache_node.data.insert("tag_width".to_string(), json!(params.tag_width));
        cache_node.data.insert("index_width".to_string(), json!(params.index_width));
        cache_node.data.insert("offset_width".to_string(), json!(params.offset_width));
        cache_node.data.insert("num_read_ports".to_string(), json!(params.num_read_ports));
        cache_node.data.insert("replacement_policy".to_string(), json!(&spec.replacement_policy));
        cache_node.data.insert("has_start_input".to_string(), json!(true));
        cache_node.data.insert("has_idle_output".to_string(), json!(true));
        cache_node.data.insert("has_complete_output".to_string(), json!(true));
        cache_node.data.insert("has_flush_input".to_string(), json!(false));
        cache_node.data.insert("flush_signals".to_string(), json!([]));
        cache_node.variable_latency = true;
        cache_node.latency = 1;
        self.graph.add_node(cache_node);

        // Control signals
        self.create_control_signals(cache_name);

        cache_name.clone()
    }

    fn create_control_signals(&mut self, cache_name: &str) {
        // Start signal (input to cache)
        let start_id = format!("{}_start", cache_name);
        let mut start_node = Node::with_defaults(Some(start_id.clone()));
        start_node.data.insert("type".to_string(), json!("control_signal"));
        start_node.data.insert("signal_type".to_string(), json!("start"));
        start_node.data.insert("cache".to_string(), json!(cache_name));
        start_node.data.insert("direction".to_string(), json!("input"));
        start_node.data.insert("bit_width".to_string(), json!(1));
        self.graph.add_node(start_node);

        let mut d = HashMap::new();
        d.insert("type".to_string(), json!("control"));
        d.insert("signal_type".to_string(), json!("start"));
        self.graph.add_edge(make_edge_with_data(&start_id, cache_name, d));

        // Idle signal (output from cache)
        let idle_id = format!("{}_idle", cache_name);
        let mut idle_node = Node::with_defaults(Some(idle_id.clone()));
        idle_node.data.insert("type".to_string(), json!("control_signal"));
        idle_node.data.insert("signal_type".to_string(), json!("idle"));
        idle_node.data.insert("cache".to_string(), json!(cache_name));
        idle_node.data.insert("direction".to_string(), json!("output"));
        idle_node.data.insert("bit_width".to_string(), json!(1));
        self.graph.add_node(idle_node);

        let mut d = HashMap::new();
        d.insert("type".to_string(), json!("control"));
        d.insert("signal_type".to_string(), json!("idle"));
        self.graph.add_edge(make_edge_with_data(cache_name, &idle_id, d));

        // Complete signal (output from cache)
        let complete_id = format!("{}_complete", cache_name);
        let mut complete_node = Node::with_defaults(Some(complete_id.clone()));
        complete_node.data.insert("type".to_string(), json!("control_signal"));
        complete_node.data.insert("signal_type".to_string(), json!("complete"));
        complete_node.data.insert("cache".to_string(), json!(cache_name));
        complete_node.data.insert("direction".to_string(), json!("output"));
        complete_node.data.insert("bit_width".to_string(), json!(1));
        self.graph.add_node(complete_node);

        let mut d = HashMap::new();
        d.insert("type".to_string(), json!("control"));
        d.insert("signal_type".to_string(), json!("complete"));
        self.graph.add_edge(make_edge_with_data(cache_name, &complete_id, d));

        // Store signal references
        if let Some(cn) = self.graph.nodes.get_mut(cache_name) {
            cn.data.insert("start_signal".to_string(), json!(start_id));
            cn.data.insert("idle_signal".to_string(), json!(idle_id));
            cn.data.insert("complete_signal".to_string(), json!(complete_id));
        }

        info!("  Created control signals: {}_start, {}_idle, {}_complete", cache_name, cache_name, cache_name);
    }

    // -----------------------------------------------------------------------
    // Phase 5: Connection
    // -----------------------------------------------------------------------

    fn wire_components(
        &mut self,
        spec: &ReadOnlyCacheSpec,
        cache_node_id: &str,
        analysis: &ROAnalysis,
        params: &CacheParams,
    ) {
        self.create_refill_interface(cache_node_id, &analysis.memory_node_id, spec, params);

        for (port_idx, access) in analysis.read_accesses.iter().enumerate() {
            self.wire_read_port(cache_node_id, access, port_idx, spec, params);
        }
    }

    fn create_refill_interface(
        &mut self,
        cache_node_id: &str,
        memory_node_id: &str,
        spec: &ReadOnlyCacheSpec,
        params: &CacheParams,
    ) {
        let cache_name = &spec.cache_name;
        let memory_name = &spec.memory_name;
        let data_width = params.data_width;

        // Refill address node
        let refill_addr_name = format!("{}_refill_addr", cache_name);
        let mut refill_addr = Node::with_defaults(Some(refill_addr_name.clone()));
        refill_addr.data.insert("type".to_string(), json!("cache_refill_addr"));
        refill_addr.data.insert("name".to_string(), json!(&refill_addr_name));
        refill_addr.data.insert("display_name".to_string(), json!(format!("{} refill addr", cache_name)));
        refill_addr.data.insert("bit_width".to_string(), json!(spec.address_width));
        refill_addr.data.insert("cache_name".to_string(), json!(cache_name));
        self.graph.add_node(refill_addr);

        self.graph.add_edge(cache_interface_edge(cache_node_id, &refill_addr_name, "refill_addr"));

        // Array access node for memory[refill_addr]
        let refill_access_name = format!("{}[{}]_rd", memory_name, refill_addr_name);
        let mut refill_access = Node::with_defaults(Some(refill_access_name.clone()));
        refill_access.data.insert("type".to_string(), json!("array_access"));
        refill_access.data.insert("display_name".to_string(), json!(&refill_access_name));
        refill_access.data.insert("access_mode".to_string(), json!("read"));
        refill_access.data.insert("bit_width".to_string(), json!(data_width));
        refill_access.data.insert("is_refill".to_string(), json!(true));
        refill_access.data.insert("cache_name".to_string(), json!(cache_name));
        self.graph.add_node(refill_access);

        self.graph.add_edge(typed_edge(memory_node_id, &refill_access_name, "array_base"));
        self.graph.add_edge(typed_edge(&refill_addr_name, &refill_access_name, "array_index"));

        // Refill data node
        let refill_data_name = format!("{}_refill_data", cache_name);
        let mut refill_data = Node::with_defaults(Some(refill_data_name.clone()));
        refill_data.data.insert("type".to_string(), json!("var"));
        refill_data.data.insert("name".to_string(), json!(&refill_data_name));
        refill_data.data.insert("display_name".to_string(), json!(format!("{} refill data", cache_name)));
        refill_data.data.insert("bit_width".to_string(), json!(data_width));
        refill_data.data.insert("cache_name".to_string(), json!(cache_name));
        refill_data.data.insert("cache_interface".to_string(), json!("refill_data"));
        self.graph.add_node(refill_data);

        self.graph.add_edge(typed_edge(&refill_access_name, &refill_data_name, "assignment"));
        self.graph.add_edge(cache_interface_edge(&refill_data_name, cache_node_id, "refill_data"));

        // Refill request node
        let refill_req_name = format!("{}_refill_req", cache_name);
        let mut refill_req = Node::with_defaults(Some(refill_req_name.clone()));
        refill_req.data.insert("type".to_string(), json!("cache_refill_req"));
        refill_req.data.insert("name".to_string(), json!(&refill_req_name));
        refill_req.data.insert("bit_width".to_string(), json!(1));
        refill_req.data.insert("cache_name".to_string(), json!(cache_name));
        self.graph.add_node(refill_req);

        self.graph.add_edge(cache_interface_edge(cache_node_id, &refill_req_name, "refill_req"));

        // Refill valid node
        let refill_valid_name = format!("{}_refill_valid", cache_name);
        let mut refill_valid = Node::with_defaults(Some(refill_valid_name.clone()));
        refill_valid.data.insert("type".to_string(), json!("var"));
        refill_valid.data.insert("name".to_string(), json!(&refill_valid_name));
        refill_valid.data.insert("bit_width".to_string(), json!(1));
        refill_valid.data.insert("cache_name".to_string(), json!(cache_name));
        refill_valid.data.insert("cache_interface".to_string(), json!("refill_valid"));
        self.graph.add_node(refill_valid);

        // Check if backing memory has variable latency
        let mem_complete_id = self
            .graph
            .nodes
            .get(memory_node_id)
            .and_then(|n| n.data.get("complete_signal"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        let has_var_latency = mem_complete_id
            .as_ref()
            .map(|id| self.graph.nodes.contains_key(id))
            .unwrap_or(false);

        if has_var_latency {
            let mcid = mem_complete_id.as_ref().unwrap();
            self.graph.add_edge(typed_edge(mcid, &refill_valid_name, "assignment"));
            info!("  Wired {} = {} (variable latency)", refill_valid_name, mcid);
        } else {
            self.graph.add_edge(typed_edge(&refill_req_name, &refill_valid_name, "assignment"));
            info!("  Wired {} = {} (1-cycle memory)", refill_valid_name, refill_req_name);
        }

        self.graph.add_edge(cache_interface_edge(&refill_valid_name, cache_node_id, "refill_valid"));

        info!("  Created refill interface: {} = {}[{}]", refill_data_name, memory_name, refill_addr_name);
    }

    fn wire_read_port(
        &mut self,
        cache_node_id: &str,
        access: &ReadAccessInfo,
        port_idx: usize,
        spec: &ReadOnlyCacheSpec,
        params: &CacheParams,
    ) {
        let cache_name = &spec.cache_name;
        let data_width = params.data_width;

        // Create read address input
        if let Some(ref addr_node_id) = access.address_node_id {
            let read_addr_name = format!("{}_read_addr_{}", cache_name, port_idx);
            let mut read_addr = Node::with_defaults(Some(read_addr_name.clone()));
            read_addr.data.insert("type".to_string(), json!("var"));
            read_addr.data.insert("name".to_string(), json!(&read_addr_name));
            read_addr.data.insert("display_name".to_string(), json!(format!("{} read addr port {}", cache_name, port_idx)));
            read_addr.data.insert("bit_width".to_string(), json!(spec.address_width));
            read_addr.data.insert("cache_name".to_string(), json!(cache_name));
            read_addr.data.insert("port_index".to_string(), json!(port_idx));
            self.graph.add_node(read_addr);

            self.graph.add_edge(typed_edge(addr_node_id, &read_addr_name, "assignment"));
            self.graph.add_edge(cache_port_edge(&read_addr_name, cache_node_id, "cache_read_addr", port_idx));
        }

        // Create cache data output
        let read_data_name = format!("{}_data_{}", cache_name, port_idx);
        let mut read_data = Node::with_defaults(Some(read_data_name.clone()));
        read_data.data.insert("type".to_string(), json!("cache_read_data"));
        read_data.data.insert("name".to_string(), json!(&read_data_name));
        read_data.data.insert("display_name".to_string(), json!(format!("{} data port {}", cache_name, port_idx)));
        read_data.data.insert("bit_width".to_string(), json!(data_width));
        read_data.data.insert("cache_name".to_string(), json!(cache_name));
        read_data.data.insert("port_index".to_string(), json!(port_idx));
        read_data.variable_latency = true;
        self.graph.add_node(read_data);

        self.graph.add_edge(cache_port_edge(cache_node_id, &read_data_name, "cache_read_data", port_idx));

        // Redirect consumers: collect outgoing edges from array_access, create new from cache_data
        let out_edge_ids: Vec<String> = self.graph.nodes.get(&access.array_access_node_id)
            .map(|n| n.outgoing_edges.iter().cloned().collect::<Vec<_>>())
            .unwrap_or_default();
        let outgoing: Vec<(String, HashMap<String, Value>)> = out_edge_ids.iter()
            .filter_map(|eid| self.graph.edges.get(eid))
            .map(|e| (e.target.clone(), e.data.clone()))
            .collect();

        for (target, data) in &outgoing {
            self.graph.add_edge(Edge::new(
                read_data_name.clone(),
                target.clone(),
                None,
                Some(data.clone()),
            ));
        }

        // Remove old outgoing edges from array_access
        for eid in &out_edge_ids {
            self.graph.remove_edge(eid);
        }

        // Remove memory->array_access edge
        if let Some(ref me_id) = access.memory_edge_id {
            self.graph.remove_edge(me_id);
        }

        // Remove address->array_access (array_index) edges
        let in_edge_ids: Vec<String> = self.graph.nodes.get(&access.array_access_node_id)
            .map(|n| n.incoming_edges.iter().cloned().collect::<Vec<_>>())
            .unwrap_or_default();
        let index_edge_ids: Vec<String> = in_edge_ids.iter()
            .filter_map(|eid| self.graph.edges.get(eid))
            .filter(|e| {
                e.data
                    .get("type")
                    .and_then(|v| v.as_str())
                    == Some("array_index")
            })
            .map(|e| e.id.clone())
            .collect();
        for eid in index_edge_ids {
            self.graph.remove_edge(&eid);
        }

        // Create read request node
        let read_req_name = format!("{}_read_req_{}", cache_name, port_idx);
        let mut read_req = Node::with_defaults(Some(read_req_name.clone()));
        read_req.data.insert("type".to_string(), json!("cache_read_req"));
        read_req.data.insert("name".to_string(), json!(&read_req_name));
        read_req.data.insert("display_name".to_string(), json!(format!("{} read req port {}", cache_name, port_idx)));
        read_req.data.insert("bit_width".to_string(), json!(1));
        read_req.data.insert("cache_name".to_string(), json!(cache_name));
        read_req.data.insert("port_index".to_string(), json!(port_idx));
        self.graph.add_node(read_req);

        // Determine if instruction cache
        let is_instruction_cache = spec.memory_name.to_lowercase().contains("imem")
            || spec.memory_name.to_lowercase().contains("instr")
            || spec
                .cached_ports
                .as_ref()
                .map(|cp| cp.iter().any(|p| p.to_lowercase().contains("pc")))
                .unwrap_or(false);

        let mut use_constant = is_instruction_cache;

        if !is_instruction_cache {
            let read_enable_id = self
                .graph
                .nodes
                .get(&access.array_access_node_id)
                .and_then(|n| n.data.get("read_enable"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());

            if let Some(ref re_id) = read_enable_id {
                if self.graph.nodes.contains_key(re_id) {
                    self.graph.add_edge(typed_edge(re_id, &read_req_name, "assignment"));
                } else {
                    use_constant = true;
                }
            } else {
                use_constant = true;
            }
        }

        if use_constant {
            let const_id = format!("{}_read_active_{}", cache_name, port_idx);
            let mut const_node = Node::with_defaults(Some(const_id.clone()));
            const_node.data.insert("type".to_string(), json!("literal"));
            const_node.data.insert("value".to_string(), json!(1));
            const_node.data.insert("bit_width".to_string(), json!(1));
            const_node.data.insert("display_name".to_string(), json!(format!("{} always active", cache_name)));
            self.graph.add_node(const_node);
            self.graph.add_edge(typed_edge(&const_id, &read_req_name, "assignment"));
        }

        self.graph.add_edge(cache_port_edge(&read_req_name, cache_node_id, "cache_read_req", port_idx));

        // Create valid output
        let valid_name = format!("{}_valid_{}", cache_name, port_idx);
        let mut valid_node = Node::with_defaults(Some(valid_name.clone()));
        valid_node.data.insert("type".to_string(), json!("cache_valid"));
        valid_node.data.insert("name".to_string(), json!(&valid_name));
        valid_node.data.insert("display_name".to_string(), json!(format!("{} valid port {}", cache_name, port_idx)));
        valid_node.data.insert("bit_width".to_string(), json!(1));
        valid_node.data.insert("cache_name".to_string(), json!(cache_name));
        valid_node.data.insert("port_index".to_string(), json!(port_idx));
        self.graph.add_node(valid_node);

        self.graph.add_edge(cache_port_edge(cache_node_id, &valid_name, "cache_valid", port_idx));

        // Connect control signals for port 0
        if port_idx == 0 {
            let complete_id = self
                .graph
                .nodes
                .get(cache_node_id)
                .and_then(|n| n.data.get("complete_signal"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());

            if let Some(ref cid) = complete_id {
                if self.graph.nodes.contains_key(cid) {
                    if let Some(cn) = self.graph.nodes.get_mut(cid) {
                        cn.data.insert("type".to_string(), json!("var"));
                        cn.data.insert("name".to_string(), json!(cid));
                    }
                    self.graph.add_edge(typed_edge(&valid_name, cid, "assignment"));
                }
            }

            let idle_id = self
                .graph
                .nodes
                .get(cache_node_id)
                .and_then(|n| n.data.get("idle_signal"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());

            if let Some(ref iid) = idle_id {
                if self.graph.nodes.contains_key(iid) {
                    if let Some(in_node) = self.graph.nodes.get_mut(iid) {
                        in_node.data.insert("type".to_string(), json!("var"));
                        in_node.data.insert("name".to_string(), json!(iid));
                    }

                    let idle_const_id = format!("{}_always_idle", cache_name);
                    let mut idle_const = Node::with_defaults(Some(idle_const_id.clone()));
                    idle_const.data.insert("type".to_string(), json!("literal"));
                    idle_const.data.insert("value".to_string(), json!(1));
                    idle_const.data.insert("bit_width".to_string(), json!(1));
                    idle_const.data.insert("display_name".to_string(), json!(format!("{} always idle", cache_name)));
                    self.graph.add_node(idle_const);
                    self.graph.add_edge(typed_edge(&idle_const_id, iid, "assignment"));
                }
            }
        }
    }

    // -----------------------------------------------------------------------
    // Phase 5b: Flush signal wiring
    // -----------------------------------------------------------------------

    fn wire_flush_signals(&mut self, cache_node_id: &str, cache_name: &str) {
        let mut placeholders_to_remove = Vec::new();
        let mut flush_signals_connected = Vec::new();

        let placeholder_ids: Vec<String> = self
            .graph
            .nodes
            .iter()
            .filter(|(_, n)| {
                n.data.get("type").and_then(|v| v.as_str()) == Some("flush_target_placeholder")
                    && n.data.get("cache_name").and_then(|v| v.as_str()) == Some(cache_name)
            })
            .map(|(id, _)| id.clone())
            .collect();

        for placeholder_id in &placeholder_ids {
            let in_eids: Vec<String> = self.graph.nodes.get(placeholder_id)
                .map(|n| n.incoming_edges.iter().cloned().collect::<Vec<_>>())
                .unwrap_or_default();
            let flush_edges: Vec<(String, String)> = in_eids.iter()
                .filter_map(|eid| self.graph.edges.get(eid))
                .filter(|e| {
                    e.data
                        .get("type")
                        .and_then(|v| v.as_str())
                        == Some("cache_flush")
                })
                .map(|e| (e.id.clone(), e.source.clone()))
                .collect();

            for (edge_id, flush_source) in flush_edges {
                self.graph.remove_edge(&edge_id);

                let mut d = HashMap::new();
                d.insert("type".to_string(), json!("cache_flush"));
                d.insert("signal_type".to_string(), json!("flush"));
                d.insert("cache_interface".to_string(), json!(true));
                self.graph.add_edge(make_edge_with_data(&flush_source, cache_node_id, d));

                flush_signals_connected.push(flush_source.clone());
                info!("  Wired flush signal {} to cache {}", flush_source, cache_name);
            }

            placeholders_to_remove.push(placeholder_id.clone());
        }

        for pid in &placeholders_to_remove {
            self.graph.remove_node(pid);
        }

        if !flush_signals_connected.is_empty() {
            if let Some(cn) = self.graph.nodes.get_mut(cache_node_id) {
                cn.data.insert("has_flush_input".to_string(), json!(true));
                cn.data.insert("flush_signals".to_string(), json!(flush_signals_connected));
            }
        }
    }
}

// ---------------------------------------------------------------------------
// ReadWriteCacheOptimization
// ---------------------------------------------------------------------------

/// Inserts a read-write cache with write-through policy before a memory node.
pub struct ReadWriteCacheOptimization<'a> {
    graph: &'a mut ResourceGraph,
}

impl<'a> ReadWriteCacheOptimization<'a> {
    pub fn new(graph: &'a mut ResourceGraph) -> Self {
        Self { graph }
    }

    pub fn apply(&mut self, spec: &mut ReadWriteCacheSpec) -> bool {
        info!("Applying read-write cache optimization for {}", spec.memory_name);

        if let Err(e) = spec.validate() {
            info!("Spec validation failed: {}", e);
            return false;
        }

        // Phase 1: Analysis
        let analysis = match self.analyze(spec) {
            Some(a) => a,
            None => return false,
        };

        // Phase 2: Planning
        let params = self.plan(spec, &analysis);
        info!(
            "  Cache parameters: tag={}b, index={}b, offset={}b",
            params.tag_width, params.index_width, params.offset_width
        );

        // Phase 3: Structure
        let cache_node_id = self.build_structure(spec, &params);
        info!("  Created cache node: {}", cache_node_id);

        // Phase 4: Hardware (backend handles internals)

        // Phase 5: Connection
        self.wire_components(spec, &cache_node_id, &analysis, &params);

        // Phase 6: Cleanup
        self.graph.cleanup_disconnected_nodes();

        // Phase 7: Timing
        self.graph.infer_uarch_time(true);
        info!("  Updated timing with variable_latency=True");

        info!(
            "Successfully added RW cache '{}' before memory '{}'",
            spec.cache_name, spec.memory_name
        );
        true
    }

    // -----------------------------------------------------------------------
    // Phase 1: Analysis
    // -----------------------------------------------------------------------

    fn analyze(&self, spec: &ReadWriteCacheSpec) -> Option<RWAnalysis> {
        let memory_node_id = find_memory_node_in_graph(self.graph, &spec.memory_name)?;

        let node = self.graph.nodes.get(&memory_node_id)?;
        let bit_width = node
            .data
            .get("bit_width")
            .and_then(|v| v.as_u64())
            .unwrap_or(32) as usize;
        let addr_width = node
            .data
            .get("array_depth")
            .and_then(|v| v.as_u64())
            .unwrap_or(10) as usize;

        info!("  Found memory '{}': {}b data, {}b addr", spec.memory_name, bit_width, addr_width);

        let read_accesses = find_read_accesses_in_graph(
            self.graph,
            &spec.memory_name,
            &spec.cached_read_ports,
            true, // skip refill accesses for RW cache
        );

        let write_port_id = find_write_port_in_graph(self.graph, &spec.memory_name);

        if read_accesses.is_empty() && write_port_id.is_none() {
            info!(
                "Error: No read accesses or write port found for memory '{}'",
                spec.memory_name
            );
            return None;
        }

        info!(
            "  Read accesses: {}, Write port: {}",
            read_accesses.len(),
            write_port_id.as_deref().unwrap_or("None")
        );

        Some(RWAnalysis {
            memory_node_id,
            bit_width,
            addr_width,
            read_accesses,
            write_port_id,
        })
    }

    // -----------------------------------------------------------------------
    // Phase 2: Planning
    // -----------------------------------------------------------------------

    fn plan(&self, spec: &mut ReadWriteCacheSpec, analysis: &RWAnalysis) -> CacheParams {
        let data_width = spec.data_width.unwrap_or(analysis.bit_width);
        spec.data_width = Some(data_width);

        CacheParams {
            data_width,
            address_width: spec.address_width,
            tag_width: spec.tag_width(),
            index_width: spec.index_width(),
            offset_width: spec.offset_width(),
            num_read_ports: analysis.read_accesses.len(),
            has_write_port: analysis.write_port_id.is_some(),
        }
    }

    // -----------------------------------------------------------------------
    // Phase 3: Structure
    // -----------------------------------------------------------------------

    fn build_structure(&mut self, spec: &ReadWriteCacheSpec, params: &CacheParams) -> String {
        let cache_name = &spec.cache_name;

        let mut cache_node = Node::with_defaults(Some(cache_name.clone()));
        cache_node.data.insert("type".to_string(), json!("read_write_cache"));
        cache_node.data.insert("name".to_string(), json!(cache_name));
        cache_node.data.insert("display_name".to_string(), json!(cache_name));
        cache_node.data.insert("memory_name".to_string(), json!(&spec.memory_name));
        cache_node.data.insert("block_size".to_string(), json!(spec.block_size));
        cache_node.data.insert("associativity".to_string(), json!(spec.associativity));
        cache_node.data.insert("num_rows".to_string(), json!(spec.num_rows));
        cache_node.data.insert("address_width".to_string(), json!(spec.address_width));
        cache_node.data.insert("data_width".to_string(), json!(params.data_width));
        cache_node.data.insert("tag_width".to_string(), json!(params.tag_width));
        cache_node.data.insert("index_width".to_string(), json!(params.index_width));
        cache_node.data.insert("offset_width".to_string(), json!(params.offset_width));
        cache_node.data.insert("num_read_ports".to_string(), json!(params.num_read_ports));
        cache_node.data.insert("has_write_port".to_string(), json!(params.has_write_port));
        cache_node.data.insert("replacement_policy".to_string(), json!(&spec.replacement_policy));
        cache_node.data.insert("write_allocate".to_string(), json!(spec.write_allocate));
        cache_node.data.insert("write_read_fwd".to_string(), json!(spec.write_read_fwd));
        cache_node.data.insert("has_start_input".to_string(), json!(true));
        cache_node.data.insert("has_idle_output".to_string(), json!(true));
        cache_node.data.insert("has_complete_output".to_string(), json!(true));
        cache_node.variable_latency = true;
        cache_node.latency = 1;
        self.graph.add_node(cache_node);

        self.create_rw_control_signals(cache_name);

        cache_name.clone()
    }

    fn create_rw_control_signals(&mut self, cache_name: &str) {
        // Start, idle, complete
        for (signal, direction) in &[("start", "input"), ("idle", "output"), ("complete", "output")] {
            let sig_id = format!("{}_{}", cache_name, signal);
            let mut sig_node = Node::with_defaults(Some(sig_id.clone()));
            sig_node.data.insert("type".to_string(), json!("control_signal"));
            sig_node.data.insert("signal_type".to_string(), json!(*signal));
            sig_node.data.insert("cache".to_string(), json!(cache_name));
            sig_node.data.insert("direction".to_string(), json!(*direction));
            sig_node.data.insert("bit_width".to_string(), json!(1));
            self.graph.add_node(sig_node);

            let mut d = HashMap::new();
            d.insert("type".to_string(), json!("control"));
            d.insert("signal_type".to_string(), json!(*signal));

            if *direction == "input" {
                self.graph.add_edge(make_edge_with_data(&sig_id, cache_name, d));
            } else {
                self.graph.add_edge(make_edge_with_data(cache_name, &sig_id, d));
            }
        }

        // Write complete signal
        let wc_id = format!("{}_write_complete", cache_name);
        let mut wc_node = Node::with_defaults(Some(wc_id.clone()));
        wc_node.data.insert("type".to_string(), json!("control_signal"));
        wc_node.data.insert("signal_type".to_string(), json!("write_complete"));
        wc_node.data.insert("cache".to_string(), json!(cache_name));
        wc_node.data.insert("direction".to_string(), json!("output"));
        wc_node.data.insert("bit_width".to_string(), json!(1));
        self.graph.add_node(wc_node);

        let mut d = HashMap::new();
        d.insert("type".to_string(), json!("control"));
        d.insert("signal_type".to_string(), json!("write_complete"));
        self.graph.add_edge(make_edge_with_data(cache_name, &wc_id, d));

        if let Some(cn) = self.graph.nodes.get_mut(cache_name) {
            cn.data.insert("start_signal".to_string(), json!(format!("{}_start", cache_name)));
            cn.data.insert("idle_signal".to_string(), json!(format!("{}_idle", cache_name)));
            cn.data.insert("complete_signal".to_string(), json!(format!("{}_complete", cache_name)));
            cn.data.insert("write_complete_signal".to_string(), json!(wc_id));
        }
    }

    // -----------------------------------------------------------------------
    // Phase 5: Connection
    // -----------------------------------------------------------------------

    fn wire_components(
        &mut self,
        spec: &ReadWriteCacheSpec,
        cache_node_id: &str,
        analysis: &RWAnalysis,
        params: &CacheParams,
    ) {
        self.create_rw_refill_interface(cache_node_id, &analysis.memory_node_id, spec, params);

        for (port_idx, access) in analysis.read_accesses.iter().enumerate() {
            self.wire_rw_read_port(cache_node_id, access, port_idx, spec, params);
        }
        info!("  Wired {} read port(s) to cache", analysis.read_accesses.len());

        if let Some(ref wp_id) = analysis.write_port_id {
            self.wire_write_port(cache_node_id, wp_id, &analysis.memory_node_id, spec, params);
            info!("  Wired write port through cache with write-through");
        }
    }

    fn create_rw_refill_interface(
        &mut self,
        cache_node_id: &str,
        memory_node_id: &str,
        spec: &ReadWriteCacheSpec,
        params: &CacheParams,
    ) {
        let cache_name = &spec.cache_name;
        let memory_name = &spec.memory_name;
        let data_width = params.data_width;

        // Refill address
        let refill_addr_name = format!("{}_refill_addr", cache_name);
        let mut refill_addr = Node::with_defaults(Some(refill_addr_name.clone()));
        refill_addr.data.insert("type".to_string(), json!("cache_refill_addr"));
        refill_addr.data.insert("name".to_string(), json!(&refill_addr_name));
        refill_addr.data.insert("display_name".to_string(), json!(format!("{} refill addr", cache_name)));
        refill_addr.data.insert("bit_width".to_string(), json!(spec.address_width));
        refill_addr.data.insert("cache_name".to_string(), json!(cache_name));
        self.graph.add_node(refill_addr);
        self.graph.add_edge(cache_interface_edge(cache_node_id, &refill_addr_name, "refill_addr"));

        // Array access for memory[refill_addr]
        let refill_access_name = format!("{}[{}]_rd", memory_name, refill_addr_name);
        let mut refill_access = Node::with_defaults(Some(refill_access_name.clone()));
        refill_access.data.insert("type".to_string(), json!("array_access"));
        refill_access.data.insert("display_name".to_string(), json!(&refill_access_name));
        refill_access.data.insert("access_mode".to_string(), json!("read"));
        refill_access.data.insert("bit_width".to_string(), json!(data_width));
        refill_access.data.insert("is_refill".to_string(), json!(true));
        refill_access.data.insert("cache_name".to_string(), json!(cache_name));
        self.graph.add_node(refill_access);

        self.graph.add_edge(typed_edge(memory_node_id, &refill_access_name, "array_base"));
        self.graph.add_edge(typed_edge(&refill_addr_name, &refill_access_name, "array_index"));

        // Refill data
        let refill_data_name = format!("{}_refill_data", cache_name);
        let mut refill_data = Node::with_defaults(Some(refill_data_name.clone()));
        refill_data.data.insert("type".to_string(), json!("var"));
        refill_data.data.insert("name".to_string(), json!(&refill_data_name));
        refill_data.data.insert("display_name".to_string(), json!(format!("{} refill data", cache_name)));
        refill_data.data.insert("bit_width".to_string(), json!(data_width));
        refill_data.data.insert("cache_name".to_string(), json!(cache_name));
        refill_data.data.insert("cache_interface".to_string(), json!("refill_data"));
        self.graph.add_node(refill_data);

        self.graph.add_edge(typed_edge(&refill_access_name, &refill_data_name, "assignment"));
        self.graph.add_edge(cache_interface_edge(&refill_data_name, cache_node_id, "refill_data"));

        // Refill req
        let refill_req_name = format!("{}_refill_req", cache_name);
        let mut refill_req = Node::with_defaults(Some(refill_req_name.clone()));
        refill_req.data.insert("type".to_string(), json!("cache_refill_req"));
        refill_req.data.insert("name".to_string(), json!(&refill_req_name));
        refill_req.data.insert("bit_width".to_string(), json!(1));
        refill_req.data.insert("cache_name".to_string(), json!(cache_name));
        self.graph.add_node(refill_req);
        self.graph.add_edge(cache_interface_edge(cache_node_id, &refill_req_name, "refill_req"));

        // Refill valid
        let refill_valid_name = format!("{}_refill_valid", cache_name);
        let mut refill_valid = Node::with_defaults(Some(refill_valid_name.clone()));
        refill_valid.data.insert("type".to_string(), json!("var"));
        refill_valid.data.insert("name".to_string(), json!(&refill_valid_name));
        refill_valid.data.insert("bit_width".to_string(), json!(1));
        refill_valid.data.insert("cache_name".to_string(), json!(cache_name));
        refill_valid.data.insert("cache_interface".to_string(), json!("refill_valid"));
        self.graph.add_node(refill_valid);

        let mem_complete_id = self
            .graph
            .nodes
            .get(memory_node_id)
            .and_then(|n| n.data.get("complete_signal"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        let has_var_latency = mem_complete_id
            .as_ref()
            .map(|id| self.graph.nodes.contains_key(id))
            .unwrap_or(false);

        if has_var_latency {
            let mcid = mem_complete_id.as_ref().unwrap();
            self.graph.add_edge(typed_edge(mcid, &refill_valid_name, "assignment"));
        } else {
            self.graph.add_edge(typed_edge(&refill_req_name, &refill_valid_name, "assignment"));
        }

        self.graph.add_edge(cache_interface_edge(&refill_valid_name, cache_node_id, "refill_valid"));
    }

    fn wire_rw_read_port(
        &mut self,
        cache_node_id: &str,
        access: &ReadAccessInfo,
        port_idx: usize,
        spec: &ReadWriteCacheSpec,
        params: &CacheParams,
    ) {
        let cache_name = &spec.cache_name;
        let data_width = params.data_width;

        // Create read address input (try Memory stage pipelined version)
        if let Some(ref addr_node_id) = access.address_node_id {
            let read_addr_name = format!("{}_read_addr_{}", cache_name, port_idx);
            let cache_addr_source = if let Some(mem_addr_id) = find_memory_stage_register(&self.graph, addr_node_id) {
                info!("    Using Memory stage address: {}", mem_addr_id);
                mem_addr_id
            } else {
                addr_node_id.clone()
            };

            let mut read_addr = Node::with_defaults(Some(read_addr_name.clone()));
            read_addr.data.insert("type".to_string(), json!("var"));
            read_addr.data.insert("name".to_string(), json!(&read_addr_name));
            read_addr.data.insert("display_name".to_string(), json!(format!("{} read addr port {}", cache_name, port_idx)));
            read_addr.data.insert("bit_width".to_string(), json!(spec.address_width));
            read_addr.data.insert("cache_name".to_string(), json!(cache_name));
            read_addr.data.insert("port_index".to_string(), json!(port_idx));
            self.graph.add_node(read_addr);

            self.graph.add_edge(typed_edge(&cache_addr_source, &read_addr_name, "assignment"));
            self.graph.add_edge(cache_port_edge(&read_addr_name, cache_node_id, "cache_read_addr", port_idx));
        }

        // Cache data output
        let read_data_name = format!("{}_data_{}", cache_name, port_idx);
        let mut read_data = Node::with_defaults(Some(read_data_name.clone()));
        read_data.data.insert("type".to_string(), json!("cache_read_data"));
        read_data.data.insert("name".to_string(), json!(&read_data_name));
        read_data.data.insert("display_name".to_string(), json!(format!("{} data port {}", cache_name, port_idx)));
        read_data.data.insert("bit_width".to_string(), json!(data_width));
        read_data.data.insert("cache_name".to_string(), json!(cache_name));
        read_data.data.insert("port_index".to_string(), json!(port_idx));
        read_data.variable_latency = true;
        self.graph.add_node(read_data);

        self.graph.add_edge(cache_port_edge(cache_node_id, &read_data_name, "cache_read_data", port_idx));

        // Redirect consumers
        let out_eids: Vec<String> = self.graph.nodes.get(&access.array_access_node_id)
            .map(|n| n.outgoing_edges.iter().cloned().collect::<Vec<_>>())
            .unwrap_or_default();
        let outgoing: Vec<(String, HashMap<String, Value>)> = out_eids.iter()
            .filter_map(|eid| self.graph.edges.get(eid))
            .map(|e| (e.target.clone(), e.data.clone()))
            .collect();

        for (target, data) in &outgoing {
            self.graph.add_edge(Edge::new(read_data_name.clone(), target.clone(), None, Some(data.clone())));
        }

        for eid in &out_eids {
            self.graph.remove_edge(eid);
        }

        if let Some(ref me_id) = access.memory_edge_id {
            self.graph.remove_edge(me_id);
        }

        let in_eids: Vec<String> = self.graph.nodes.get(&access.array_access_node_id)
            .map(|n| n.incoming_edges.iter().cloned().collect::<Vec<_>>())
            .unwrap_or_default();
        let index_ids: Vec<String> = in_eids.iter()
            .filter_map(|eid| self.graph.edges.get(eid))
            .filter(|e| {
                e.data
                    .get("type")
                    .and_then(|v| v.as_str())
                    == Some("array_index")
            })
            .map(|e| e.id.clone())
            .collect();
        for eid in index_ids {
            self.graph.remove_edge(&eid);
        }

        // Read request node
        let read_req_name = format!("{}_read_req_{}", cache_name, port_idx);
        let mut read_req = Node::with_defaults(Some(read_req_name.clone()));
        read_req.data.insert("type".to_string(), json!("cache_read_req"));
        read_req.data.insert("name".to_string(), json!(&read_req_name));
        read_req.data.insert("display_name".to_string(), json!(format!("{} read req port {}", cache_name, port_idx)));
        read_req.data.insert("bit_width".to_string(), json!(1));
        read_req.data.insert("cache_name".to_string(), json!(cache_name));
        read_req.data.insert("port_index".to_string(), json!(port_idx));
        self.graph.add_node(read_req);

        // Find read enable source
        let mut read_enable_source: Option<String> = None;

        if let Some(ref addr_node_id) = access.address_node_id {
            let addr_type = self
                .graph
                .nodes
                .get(addr_node_id)
                .and_then(|n| n.data.get("type"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();

            let mux_types = ["one_hot_mux", "collision_mux", "mux", "inline_mux"];
            let mux_node_id = if mux_types.contains(&addr_type.as_str()) {
                Some(addr_node_id.clone())
            } else {
                let addr_in_eids: Vec<String> = self.graph.nodes.get(addr_node_id)
                    .map(|n| n.incoming_edges.iter().cloned().collect::<Vec<_>>())
                    .unwrap_or_default();
                addr_in_eids.iter()
                    .filter_map(|eid| self.graph.edges.get(eid))
                    .find_map(|e| {
                        let src = &e.source;
                        let src_type = self
                            .graph
                            .nodes
                            .get(src)
                            .and_then(|n| n.data.get("type"))
                            .and_then(|v| v.as_str())
                            .unwrap_or("");
                        if mux_types.contains(&src_type) || src.ends_with("_mux") {
                            Some(src.clone())
                        } else {
                            None
                        }
                    })
            };

            if let Some(ref mux_id) = mux_node_id {
                let mux_enable_id = format!("{}_enable_or_0", mux_id);
                if self.graph.nodes.contains_key(&mux_enable_id) {
                    read_enable_source = Some(mux_enable_id);
                }
            }
        }

        if read_enable_source.is_none() {
            let re_id = self
                .graph
                .nodes
                .get(&access.array_access_node_id)
                .and_then(|n| n.data.get("read_enable"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            if let Some(ref id) = re_id {
                if self.graph.nodes.contains_key(id) {
                    read_enable_source = Some(id.clone());
                }
            }
        }

        if let Some(ref re_src) = read_enable_source {
            self.graph.add_edge(typed_edge(re_src, &read_req_name, "assignment"));
        } else {
            // Check for cache refill port
            let is_refill = self
                .graph
                .nodes
                .get(&access.array_access_node_id)
                .and_then(|n| n.data.get("is_refill"))
                .and_then(|v| v.as_bool())
                .unwrap_or(false);

            let source_refill_req_id = if is_refill {
                self.graph
                    .nodes
                    .get(&access.array_access_node_id)
                    .and_then(|n| n.data.get("cache_name"))
                    .and_then(|v| v.as_str())
                    .map(|cn| format!("{}_refill_req", cn))
            } else {
                None
            };

            let has_source = source_refill_req_id
                .as_ref()
                .map(|id| self.graph.nodes.contains_key(id))
                .unwrap_or(false);

            if has_source {
                self.graph.add_edge(typed_edge(&source_refill_req_id.unwrap(), &read_req_name, "assignment"));
            } else {
                let const_id = format!("{}_read_active_{}", cache_name, port_idx);
                let mut const_node = Node::with_defaults(Some(const_id.clone()));
                const_node.data.insert("type".to_string(), json!("literal"));
                const_node.data.insert("value".to_string(), json!(1));
                const_node.data.insert("bit_width".to_string(), json!(1));
                const_node.data.insert("display_name".to_string(), json!(format!("{} always active", cache_name)));
                self.graph.add_node(const_node);
                self.graph.add_edge(typed_edge(&const_id, &read_req_name, "assignment"));
            }
        }

        self.graph.add_edge(cache_port_edge(&read_req_name, cache_node_id, "cache_read_req", port_idx));

        // Valid output
        let valid_name = format!("{}_valid_{}", cache_name, port_idx);
        let mut valid_node = Node::with_defaults(Some(valid_name.clone()));
        valid_node.data.insert("type".to_string(), json!("cache_valid"));
        valid_node.data.insert("name".to_string(), json!(&valid_name));
        valid_node.data.insert("display_name".to_string(), json!(format!("{} valid port {}", cache_name, port_idx)));
        valid_node.data.insert("bit_width".to_string(), json!(1));
        valid_node.data.insert("cache_name".to_string(), json!(cache_name));
        valid_node.data.insert("port_index".to_string(), json!(port_idx));
        self.graph.add_node(valid_node);

        self.graph.add_edge(cache_port_edge(cache_node_id, &valid_name, "cache_valid", port_idx));

        // For RW cache, complete and idle are module outputs (not assigned from valid)
        if port_idx == 0 {
            let complete_id = format!("{}_complete", cache_name);
            if let Some(cn) = self.graph.nodes.get_mut(&complete_id) {
                cn.data.insert("type".to_string(), json!("cache_complete"));
                cn.data.insert("is_module_output".to_string(), json!(true));
                cn.data.insert("cache_name".to_string(), json!(cache_name));
            }

            let idle_id = format!("{}_idle", cache_name);
            if let Some(in_node) = self.graph.nodes.get_mut(&idle_id) {
                in_node.data.insert("type".to_string(), json!("cache_idle"));
                in_node.data.insert("is_module_output".to_string(), json!(true));
                in_node.data.insert("cache_name".to_string(), json!(cache_name));
            }
        }

        // If this port intercepts a refill, rewire source cache's refill_valid
        let is_refill = self
            .graph
            .nodes
            .get(&access.array_access_node_id)
            .and_then(|n| n.data.get("is_refill"))
            .and_then(|v| v.as_bool())
            .unwrap_or(false);

        if is_refill {
            let source_cache = self
                .graph
                .nodes
                .get(&access.array_access_node_id)
                .and_then(|n| n.data.get("cache_name"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());

            if let Some(scn) = source_cache {
                let refill_valid_id = format!("{}_refill_valid", scn);
                if self.graph.nodes.contains_key(&refill_valid_id) {
                    let rv_in_eids: Vec<String> = self.graph.nodes.get(&refill_valid_id)
                        .map(|n| n.incoming_edges.iter().cloned().collect::<Vec<_>>())
                        .unwrap_or_default();
                    let old_edges: Vec<String> = rv_in_eids.iter()
                        .filter_map(|eid| self.graph.edges.get(eid))
                        .filter(|e| {
                            e.data.get("type").and_then(|v| v.as_str())
                                == Some("assignment")
                        })
                        .map(|e| e.id.clone())
                        .collect();
                    for eid in old_edges {
                        self.graph.remove_edge(&eid);
                    }
                    self.graph.add_edge(typed_edge(&valid_name, &refill_valid_id, "assignment"));
                    info!("    Rewired {} = {}", refill_valid_id, valid_name);
                }
            }
        }
    }

    fn wire_write_port(
        &mut self,
        cache_node_id: &str,
        write_port_id: &str,
        memory_node_id: &str,
        spec: &ReadWriteCacheSpec,
        params: &CacheParams,
    ) {
        let cache_name = &spec.cache_name;
        let data_width = params.data_width;

        // Remove old write_port -> memory edge
        let wp_out_eids: Vec<String> = self.graph.nodes.get(write_port_id)
            .map(|n| n.outgoing_edges.iter().cloned().collect::<Vec<_>>())
            .unwrap_or_default();
        let old_mem_edge: Option<String> = wp_out_eids.iter()
            .filter_map(|eid| self.graph.edges.get(eid))
            .find(|e| {
                e.data.get("type").and_then(|v| v.as_str())
                    == Some("memory_write")
            })
            .map(|e| e.id.clone());
        if let Some(eid) = old_mem_edge {
            self.graph.remove_edge(&eid);
        }

        // write_port -> cache
        let mut d = HashMap::new();
        d.insert("type".to_string(), json!("cache_write_input"));
        d.insert("cache_interface".to_string(), json!(true));
        self.graph.add_edge(make_edge_with_data(write_port_id, cache_node_id, d));

        // Write-through address
        let wt_addr_name = format!("{}_write_through_addr", cache_name);
        let mut wt_addr = Node::with_defaults(Some(wt_addr_name.clone()));
        wt_addr.data.insert("type".to_string(), json!("var"));
        wt_addr.data.insert("name".to_string(), json!(&wt_addr_name));
        wt_addr.data.insert("bit_width".to_string(), json!(spec.address_width));
        wt_addr.data.insert("cache_name".to_string(), json!(cache_name));
        wt_addr.data.insert("cache_interface".to_string(), json!("write_through_addr"));
        self.graph.add_node(wt_addr);

        // Write-through data
        let wt_data_name = format!("{}_write_through_data", cache_name);
        let mut wt_data = Node::with_defaults(Some(wt_data_name.clone()));
        wt_data.data.insert("type".to_string(), json!("var"));
        wt_data.data.insert("name".to_string(), json!(&wt_data_name));
        wt_data.data.insert("bit_width".to_string(), json!(data_width));
        wt_data.data.insert("cache_name".to_string(), json!(cache_name));
        wt_data.data.insert("cache_interface".to_string(), json!("write_through_data"));
        self.graph.add_node(wt_data);

        // Write-through byte enable (cache output)
        let byte_enable_width = data_width / 8;
        let wt_byte_en_cache_name = format!("{}_write_through_byte_enable", cache_name);
        let mut wt_byte_en_cache = Node::with_defaults(Some(wt_byte_en_cache_name.clone()));
        wt_byte_en_cache.data.insert("type".to_string(), json!("var"));
        wt_byte_en_cache.data.insert("name".to_string(), json!(&wt_byte_en_cache_name));
        wt_byte_en_cache.data.insert("bit_width".to_string(), json!(byte_enable_width));
        wt_byte_en_cache.data.insert("cache_name".to_string(), json!(cache_name));
        wt_byte_en_cache.data.insert("cache_interface".to_string(), json!("write_through_byte_enable"));
        self.graph.add_node(wt_byte_en_cache);

        // Write-through byte mask
        let wt_byte_en_name = format!("{}_write_through_byte_mask", cache_name);
        let mut wt_byte_en = Node::with_defaults(Some(wt_byte_en_name.clone()));
        wt_byte_en.data.insert("type".to_string(), json!("var"));
        wt_byte_en.data.insert("name".to_string(), json!(&wt_byte_en_name));
        wt_byte_en.data.insert("bit_width".to_string(), json!(byte_enable_width));
        self.graph.add_node(wt_byte_en);

        // Write-through enable
        let wt_enable_name = "cache_wt_enable".to_string();
        let mut wt_enable = Node::with_defaults(Some(wt_enable_name.clone()));
        wt_enable.data.insert("type".to_string(), json!("var"));
        wt_enable.data.insert("name".to_string(), json!(&wt_enable_name));
        wt_enable.data.insert("bit_width".to_string(), json!(1));
        wt_enable.data.insert("cache_name".to_string(), json!(cache_name));
        wt_enable.data.insert("cache_interface".to_string(), json!("write_through_req"));
        self.graph.add_node(wt_enable);

        // Write-through req alias
        let wt_req_name = format!("{}_write_through_req", cache_name);
        let mut wt_req = Node::with_defaults(Some(wt_req_name.clone()));
        wt_req.data.insert("type".to_string(), json!("var"));
        wt_req.data.insert("name".to_string(), json!(&wt_req_name));
        wt_req.data.insert("bit_width".to_string(), json!(1));
        wt_req.data.insert("cache_name".to_string(), json!(cache_name));
        wt_req.data.insert("cache_interface".to_string(), json!("write_through_req"));
        self.graph.add_node(wt_req);

        // Connect cache to write-through outputs
        self.graph.add_edge(cache_interface_edge(cache_node_id, &wt_addr_name, "write_through_addr"));
        self.graph.add_edge(cache_interface_edge(cache_node_id, &wt_data_name, "write_through_data"));
        self.graph.add_edge(cache_interface_edge(cache_node_id, &wt_byte_en_cache_name, "write_through_byte_enable"));
        self.graph.add_edge(typed_edge(&wt_byte_en_cache_name, &wt_byte_en_name, "assignment"));
        self.graph.add_edge(cache_interface_edge(cache_node_id, &wt_req_name, "write_through_req"));
        self.graph.add_edge(typed_edge(&wt_req_name, &wt_enable_name, "assignment"));

        // Data mux node
        let wt_data_mux_name = format!("{}_write_through_data_mux", cache_name);
        let mut wt_data_mux = Node::with_defaults(Some(wt_data_mux_name.clone()));
        wt_data_mux.data.insert("type".to_string(), json!("memory_data_merge"));
        wt_data_mux.data.insert("name".to_string(), json!(&wt_data_mux_name));
        wt_data_mux.data.insert("bit_width".to_string(), json!(data_width));
        self.graph.add_node(wt_data_mux);

        self.graph.add_edge(typed_edge(&wt_data_name, &wt_data_mux_name, "mux_input"));
        self.graph.add_edge(typed_edge(&wt_enable_name, &wt_data_mux_name, "mux_select"));

        // Write-through port node (memory_write_port)
        let wt_port_name = format!("{}_write_through_port", cache_name);
        let mut wt_port = Node::with_defaults(Some(wt_port_name.clone()));
        wt_port.data.insert("type".to_string(), json!("memory_write_port"));
        wt_port.data.insert("name".to_string(), json!(&wt_port_name));
        wt_port.data.insert("cache_name".to_string(), json!(cache_name));
        wt_port.data.insert("base_memory".to_string(), json!(&spec.memory_name));
        wt_port.data.insert("bit_width".to_string(), json!(data_width));
        wt_port.data.insert("writers".to_string(), json!(["cache_wt"]));
        wt_port.data.insert("writer_widths".to_string(), json!({"cache_wt": data_width}));
        wt_port.data.insert("store_byte_enables".to_string(), json!({"cache_wt": &wt_byte_en_name}));
        wt_port.data.insert("store_positioned_data".to_string(), json!({"cache_wt": &wt_data_name}));
        wt_port.data.insert("combined_write_enable".to_string(), json!(&wt_enable_name));
        wt_port.data.insert("cache_write_through".to_string(), json!(true));
        wt_port.data.insert("cache_byte_enable_signal".to_string(), json!(&wt_byte_en_name));
        self.graph.add_node(wt_port);

        self.graph.add_edge(typed_edge(&wt_data_mux_name, &wt_port_name, "write_data"));
        self.graph.add_edge(typed_edge(&wt_addr_name, &wt_port_name, "write_address"));

        let mut be_d = HashMap::new();
        be_d.insert("type".to_string(), json!("byte_enable"));
        be_d.insert("instruction".to_string(), json!("cache_wt"));
        self.graph.add_edge(make_edge_with_data(&wt_byte_en_name, &wt_port_name, be_d));

        self.graph.add_edge(typed_edge(&wt_enable_name, &wt_port_name, "write_enable"));

        // write_through_port -> memory
        let mut wt_mem_d = HashMap::new();
        wt_mem_d.insert("type".to_string(), json!("memory_write"));
        wt_mem_d.insert("description".to_string(), json!("Write-through to backing memory"));
        self.graph.add_edge(make_edge_with_data(&wt_port_name, memory_node_id, wt_mem_d));

        // Copy write port metadata to cache node
        let wp_combined_we = self
            .graph
            .nodes
            .get(write_port_id)
            .and_then(|n| n.data.get("combined_write_enable").cloned());
        let wp_store_be: Option<HashMap<String, String>> = self
            .graph
            .nodes
            .get(write_port_id)
            .and_then(|n| n.data.get("store_byte_enables"))
            .and_then(|v| v.as_object())
            .map(|obj| {
                obj.iter()
                    .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                    .collect()
            });
        let wp_writers = self
            .graph
            .nodes
            .get(write_port_id)
            .and_then(|n| n.data.get("writers").cloned());

        // Create combined byte enable mux for dcache write_byte_enable input.
        // The original write port has per-instruction byte enables; we need to
        // combine them into a single signal based on instruction enables.
        let combined_be_name = format!("{}_write_byte_enable", cache_name);
        if let Some(ref sbe_map) = wp_store_be {
            let byte_enable_width = data_width / 8;

            // Collect (enable_node_id, byte_enable_node_id) pairs
            let mut mux_inputs: Vec<(String, String)> = Vec::new();
            for (instr_name, be_node_id) in sbe_map {
                let enable_patterns = [
                    format!("{}_enable", instr_name),
                    format!("{}_enable_and", instr_name),
                    instr_name.replace('.', "_") + "_enable",
                ];
                let enable_node_id = enable_patterns
                    .iter()
                    .find(|p| self.graph.nodes.contains_key(p.as_str()))
                    .cloned();
                if let Some(en_id) = enable_node_id {
                    if self.graph.nodes.contains_key(be_node_id.as_str()) {
                        mux_inputs.push((en_id, be_node_id.clone()));
                    }
                }
            }

            if !mux_inputs.is_empty() {
                let mux_inputs_json: Vec<Value> = mux_inputs
                    .iter()
                    .map(|(en, be)| json!([en, be]))
                    .collect();
                let default_value = (1i64 << byte_enable_width) - 1;

                let mut be_mux = Node::with_defaults(Some(combined_be_name.clone()));
                be_mux.data.insert("type".into(), json!("byte_enable_mux"));
                be_mux.data.insert("name".into(), json!(&combined_be_name));
                be_mux.data.insert("bit_width".into(), json!(byte_enable_width));
                be_mux.data.insert("mux_inputs".into(), Value::Array(mux_inputs_json));
                be_mux.data.insert("default_value".into(), json!(default_value));
                self.graph.add_node(be_mux);

                // Add edges from enable and byte_enable nodes to the mux
                for (enable_node_id, be_node_id) in &mux_inputs {
                    self.graph.add_edge(typed_edge(enable_node_id, &combined_be_name, "mux_select"));
                    self.graph.add_edge(typed_edge(be_node_id, &combined_be_name, "mux_input"));
                }
            }
        }

        if let Some(cn) = self.graph.nodes.get_mut(cache_node_id) {
            cn.data.insert("write_port".to_string(), json!(write_port_id));
            cn.data.insert("write_through_port".to_string(), json!(&wt_port_name));
            cn.data.insert("write_byte_enable_node".to_string(), json!(&combined_be_name));
            if let Some(v) = wp_combined_we {
                cn.data.insert("combined_write_enable".to_string(), v);
            }
            if let Some(ref v) = wp_store_be {
                let be_json: Value = v.iter()
                    .map(|(k, v)| (k.clone(), json!(v)))
                    .collect::<serde_json::Map<String, Value>>()
                    .into();
                cn.data.insert("store_byte_enables".to_string(), be_json);
            }
            if let Some(v) = wp_writers {
                cn.data.insert("writers".to_string(), v);
            }
        }

        // Remove base_memory from original write port so it doesn't generate
        // a direct write path to memory. Writes now go through the cache's
        // write-through mechanism.
        if let Some(wp) = self.graph.nodes.get_mut(write_port_id) {
            wp.data.remove("base_memory");
        }

        // Write-through complete
        let wt_complete_name = format!("{}_write_through_complete", cache_name);
        let mut wt_complete = Node::with_defaults(Some(wt_complete_name.clone()));
        wt_complete.data.insert("type".to_string(), json!("var"));
        wt_complete.data.insert("name".to_string(), json!(&wt_complete_name));
        wt_complete.data.insert("bit_width".to_string(), json!(1));
        wt_complete.data.insert("cache_name".to_string(), json!(cache_name));
        wt_complete.data.insert("cache_interface".to_string(), json!("write_through_complete"));
        self.graph.add_node(wt_complete);

        let mem_complete_id = self
            .graph
            .nodes
            .get(memory_node_id)
            .and_then(|n| n.data.get("complete_signal"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        let has_var_latency = mem_complete_id
            .as_ref()
            .map(|id| self.graph.nodes.contains_key(id))
            .unwrap_or(false);

        if has_var_latency {
            let mcid = mem_complete_id.unwrap();
            self.graph.add_edge(typed_edge(&mcid, &wt_complete_name, "assignment"));
        } else {
            let const_name = format!("{}_wt_always_complete", cache_name);
            let mut const_node = Node::with_defaults(Some(const_name.clone()));
            const_node.data.insert("type".to_string(), json!("literal"));
            const_node.data.insert("value".to_string(), json!(1));
            const_node.data.insert("bit_width".to_string(), json!(1));
            const_node.data.insert("name".to_string(), json!(&const_name));
            self.graph.add_node(const_node);
            self.graph.add_edge(typed_edge(&const_name, &wt_complete_name, "assignment"));
        }

        self.graph.add_edge(cache_interface_edge(&wt_complete_name, cache_node_id, "write_through_complete"));

        if let Some(cn) = self.graph.nodes.get_mut(cache_node_id) {
            cn.data.insert("write_through_complete".to_string(), json!(&wt_complete_name));
        }
    }
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

fn find_memory_node_in_graph(graph: &ResourceGraph, memory_name: &str) -> Option<String> {
    for (node_id, node) in &graph.nodes {
        let name = node.data.get("name").and_then(|v| v.as_str()).unwrap_or("");
        let ntype = node.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
        let is_mem = node
            .data
            .get("is_memory")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);

        if (name == memory_name || node_id == memory_name)
            && (is_mem || ntype == "isa_state mem")
        {
            return Some(node_id.clone());
        }
    }
    None
}

fn find_read_accesses_in_graph(
    graph: &ResourceGraph,
    memory_name: &str,
    cached_ports: &Option<Vec<String>>,
    skip_refills: bool,
) -> Vec<ReadAccessInfo> {
    let mut accesses = Vec::new();

    let node_ids: Vec<String> = graph.nodes.keys().cloned().collect();
    for node_id in &node_ids {
        let node = match graph.nodes.get(node_id) {
            Some(n) => n,
            None => continue,
        };

        if node.data.get("type").and_then(|v| v.as_str()) != Some("array_access") {
            continue;
        }
        if node.data.get("access_mode").and_then(|v| v.as_str()) != Some("read") {
            continue;
        }

        if skip_refills && node.data.get("is_refill").and_then(|v| v.as_bool()).unwrap_or(false) {
            continue;
        }

        let in_eids: Vec<String> = node.incoming_edges.iter().cloned().collect();
        let mut is_accessing_memory = false;
        let mut address_node_id: Option<String> = None;
        let mut memory_edge_id: Option<String> = None;

        for eid in &in_eids {
            let edge = match graph.edges.get(eid) {
                Some(e) => e,
                None => continue,
            };
            let etype = edge
                .data
                .get("type")
                .and_then(|v| v.as_str())
                .unwrap_or("");

            if etype == "array_base" {
                let src_name = graph
                    .nodes
                    .get(&edge.source)
                    .and_then(|n| n.data.get("name"))
                    .and_then(|v| v.as_str())
                    .unwrap_or(&edge.source);
                if src_name == memory_name || edge.source == memory_name {
                    is_accessing_memory = true;
                    memory_edge_id = Some(edge.id.clone());
                }
            } else if etype == "array_index" {
                address_node_id = Some(edge.source.clone());
            }
        }

        if !is_accessing_memory {
            continue;
        }

        let out_eids: Vec<String> = node.outgoing_edges.iter().cloned().collect();
        let target_edge_ids: Vec<String> = out_eids.iter()
            .filter_map(|eid| graph.edges.get(eid))
            .filter(|e| {
                let et = e
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                matches!(
                    et,
                    "assignment" | "operand" | "ternary_true" | "ternary_false" | "mux_input"
                )
            })
            .map(|e| e.id.clone())
            .collect();

        if target_edge_ids.is_empty() && out_eids.is_empty() {
            continue;
        }

        // Filter by cached_ports
        if let Some(ref ports) = cached_ports {
            let addr_id = address_node_id.as_deref().unwrap_or("");
            let access_id = node_id.as_str();
            let matches = ports.iter().any(|p| addr_id.contains(p) || access_id.contains(p));
            if !matches {
                continue;
            }
        }

        accesses.push(ReadAccessInfo {
            array_access_node_id: node_id.clone(),
            address_node_id,
            memory_edge_id,
            target_edge_ids,
        });
    }

    accesses
}

fn find_write_port_in_graph(graph: &ResourceGraph, memory_name: &str) -> Option<String> {
    for (node_id, node) in &graph.nodes {
        if node.data.get("type").and_then(|v| v.as_str()) != Some("memory_write_port") {
            continue;
        }
        if node.data.get("base_memory").and_then(|v| v.as_str()) != Some(memory_name) {
            continue;
        }
        // Found a write port for this memory - return it.
        // Note: the memory_write outgoing edge may not exist yet if the write port
        // was created by memory_access_transform and cleanup removed the edge.
        return Some(node_id.clone());
    }
    None
}

// ---------------------------------------------------------------------------
// Convenience functions
// ---------------------------------------------------------------------------

/// Apply read-only cache optimization.
pub fn apply_read_only_cache(graph: &mut ResourceGraph, spec: &mut ReadOnlyCacheSpec) -> bool {
    let mut opt = ReadOnlyCacheOptimization::new(graph);
    opt.apply(spec)
}

/// Apply read-write cache optimization.
pub fn apply_read_write_cache(graph: &mut ResourceGraph, spec: &mut ReadWriteCacheSpec) -> bool {
    let mut opt = ReadWriteCacheOptimization::new(graph);
    opt.apply(spec)
}

/// Get all cache node IDs in the graph.
pub fn get_cache_nodes(graph: &ResourceGraph) -> Vec<String> {
    graph
        .nodes
        .iter()
        .filter(|(_, n)| {
            let t = n.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
            t == "read_only_cache" || t == "read_write_cache"
        })
        .map(|(id, _)| id.clone())
        .collect()
}

/// Connect a cache's refill_req signal to the memory's access_enable.
pub fn connect_cache_refill_to_memory(
    graph: &mut ResourceGraph,
    cache_name: &str,
    memory_name: &str,
) -> bool {
    let refill_req_id = format!("{}_refill_req", cache_name);
    if !graph.nodes.contains_key(&refill_req_id) {
        info!("WARNING: {} not found", refill_req_id);
        return false;
    }

    let access_enable_id = format!("{}_access_enable", memory_name);
    if !graph.nodes.contains_key(&access_enable_id) {
        info!("WARNING: {} not found", access_enable_id);
        return false;
    }

    let ae_in_eids: Vec<String> = graph.nodes.get(&access_enable_id)
        .map(|n| n.incoming_edges.iter().cloned().collect::<Vec<_>>())
        .unwrap_or_default();
    let existing_inputs = ae_in_eids.iter()
        .filter_map(|eid| graph.edges.get(eid))
        .filter(|e| {
            e.data
                .get("type")
                .and_then(|v| v.as_str())
                == Some("logic_input")
        })
        .count();

    let mut d = HashMap::new();
    d.insert("type".to_string(), json!("logic_input"));
    d.insert("operand_position".to_string(), json!(existing_inputs));
    graph.add_edge(make_edge_with_data(&refill_req_id, &access_enable_id, d));

    info!("Connected {} to {} (input {})", refill_req_id, access_enable_id, existing_inputs);
    true
}

/// Wire the start signal for a read-only cache.
pub fn wire_cache_start_signal(graph: &mut ResourceGraph, cache_name: &str) -> bool {
    let cache_type = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("type"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    if cache_type.as_deref() != Some("read_only_cache") {
        info!("ERROR: {} is not a read_only_cache", cache_name);
        return false;
    }

    let start_signal_id = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("start_signal"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let idle_signal_id = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("idle_signal"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    let (start_id, idle_id) = match (start_signal_id, idle_signal_id) {
        (Some(s), Some(i)) => (s, i),
        _ => {
            info!("ERROR: Cache {} missing start or idle signal", cache_name);
            return false;
        }
    };

    if !graph.nodes.contains_key(&start_id) || !graph.nodes.contains_key(&idle_id) {
        info!("ERROR: Signal nodes not found");
        return false;
    }

    // Find read request signals
    let cache_in_eids: Vec<String> = graph.nodes.get(cache_name)
        .map(|n| n.incoming_edges.iter().cloned().collect::<Vec<_>>())
        .unwrap_or_default();
    let read_req_ids: Vec<String> = cache_in_eids.iter()
        .filter_map(|eid| graph.edges.get(eid))
        .filter(|e| {
            e.data.get("type").and_then(|v| v.as_str())
                == Some("cache_read_addr")
        })
        .filter_map(|e| {
            let port_idx = e
                .data
                .get("port_index")
                .and_then(|v| v.as_u64())
                .unwrap_or(0);
            let id = format!("{}_read_req_{}", cache_name, port_idx);
            if graph.nodes.contains_key(&id) { Some(id) } else { None }
        })
        .collect();

    let access_enable_id = if read_req_ids.len() <= 1 {
        read_req_ids.first().cloned().unwrap_or_else(|| format!("{}_read_req", cache_name))
    } else {
        let or_id = format!("{}_read_any", cache_name);
        let mut or_node = Node::with_defaults(Some(or_id.clone()));
        or_node.data.insert("type".to_string(), json!("logical_or"));
        or_node.data.insert("pipeline_component".to_string(), json!(true));
        or_node.data.insert("bit_width".to_string(), json!(1));
        graph.add_node(or_node);

        for (i, req_id) in read_req_ids.iter().enumerate() {
            let mut d = HashMap::new();
            d.insert("type".to_string(), json!("logic_input"));
            d.insert("operand_position".to_string(), json!(i));
            graph.add_edge(make_edge_with_data(req_id, &or_id, d));
        }
        or_id
    };

    // AND gate: idle && access_enable
    let and_id = format!("{}_start_condition", cache_name);
    let mut and_node = Node::with_defaults(Some(and_id.clone()));
    and_node.data.insert("type".to_string(), json!("logical_and"));
    and_node.data.insert("pipeline_component".to_string(), json!(true));
    and_node.data.insert("bit_width".to_string(), json!(1));
    graph.add_node(and_node);

    let mut d0 = HashMap::new();
    d0.insert("type".to_string(), json!("logic_input"));
    d0.insert("operand_position".to_string(), json!(0));
    graph.add_edge(make_edge_with_data(&idle_id, &and_id, d0));

    let mut d1 = HashMap::new();
    d1.insert("type".to_string(), json!("logic_input"));
    d1.insert("operand_position".to_string(), json!(1));
    graph.add_edge(make_edge_with_data(&access_enable_id, &and_id, d1));

    let mut op_d = HashMap::new();
    op_d.insert("type".to_string(), json!("operand"));
    graph.add_edge(make_edge_with_data(&and_id, &start_id, op_d));

    info!("  Wired {} = {} && {}", start_id, idle_id, access_enable_id);

    if let Some(cn) = graph.nodes.get_mut(cache_name) {
        cn.data.insert("access_enable_signal".to_string(), json!(&access_enable_id));
    }

    true
}

/// Clean up unreferenced flush placeholders.
pub fn cleanup_unreferenced_flush_placeholders(graph: &mut ResourceGraph) -> usize {
    let placeholder_ids: Vec<String> = graph
        .nodes
        .iter()
        .filter(|(_, n)| {
            n.data.get("type").and_then(|v| v.as_str()) == Some("flush_target_placeholder")
        })
        .map(|(id, _)| id.clone())
        .collect();

    let count = placeholder_ids.len();

    for pid in &placeholder_ids {
        let edge_ids: Vec<String> = graph.nodes.get(pid)
            .map(|n| n.incoming_edges.iter().cloned().collect::<Vec<_>>())
            .unwrap_or_default();
        for eid in edge_ids {
            graph.remove_edge(&eid);
        }
        graph.remove_node(pid);
    }

    if count > 0 {
        info!("Removed {} unreferenced flush placeholder(s)", count);
    }

    count
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

/// Wire the start signal for a read-write cache.
/// The start signal is: idle && (read_request || write_request)
pub fn wire_rwcache_start_signal(graph: &mut ResourceGraph, cache_name: &str) -> bool {
    let cache_type = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("type"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    if cache_type.as_deref() != Some("read_write_cache") {
        info!("ERROR: {} is not a read_write_cache", cache_name);
        return false;
    }

    let start_signal_id = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("start_signal"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let idle_signal_id = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("idle_signal"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    let (start_id, idle_id) = match (start_signal_id, idle_signal_id) {
        (Some(s), Some(i)) => (s, i),
        _ => {
            info!("ERROR: Cache {} missing start or idle signal", cache_name);
            return false;
        }
    };

    if !graph.nodes.contains_key(&start_id) || !graph.nodes.contains_key(&idle_id) {
        info!("ERROR: Signal nodes not found");
        return false;
    }

    // Find read request signals
    let cache_in_eids: Vec<String> = graph.nodes.get(cache_name)
        .map(|n| n.incoming_edges.iter().cloned().collect::<Vec<_>>())
        .unwrap_or_default();
    let mut read_req_ids: Vec<String> = cache_in_eids.iter()
        .filter_map(|eid| graph.edges.get(eid))
        .filter(|e| {
            e.data.get("type").and_then(|v| v.as_str()) == Some("cache_read_req")
        })
        .filter_map(|e| {
            let port_idx = e.data.get("port_index").and_then(|v| v.as_u64()).unwrap_or(0);
            let id = format!("{}_read_req_{}", cache_name, port_idx);
            if graph.nodes.contains_key(&id) { Some(id) } else { None }
        })
        .collect();

    // Check for write request (from write port)
    let write_enable_id = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("combined_write_enable"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    if let Some(ref we_id) = write_enable_id {
        if graph.nodes.contains_key(we_id) {
            read_req_ids.push(we_id.clone());
        }
    }

    if read_req_ids.is_empty() {
        info!("  Warning: No request signals found for {}", cache_name);
        return false;
    }

    let access_enable_id = if read_req_ids.len() == 1 {
        read_req_ids[0].clone()
    } else {
        let or_id = format!("{}_access_any", cache_name);
        let mut or_node = Node::with_defaults(Some(or_id.clone()));
        or_node.data.insert("type".to_string(), json!("logical_or"));
        or_node.data.insert("pipeline_component".to_string(), json!(true));
        or_node.data.insert("bit_width".to_string(), json!(1));
        graph.add_node(or_node);

        for (i, req_id) in read_req_ids.iter().enumerate() {
            let mut d = HashMap::new();
            d.insert("type".to_string(), json!("logic_input"));
            d.insert("operand_position".to_string(), json!(i));
            graph.add_edge(make_edge_with_data(req_id, &or_id, d));
        }
        info!("  Created access_any OR with {} inputs", read_req_ids.len());
        or_id
    };

    // AND gate: idle && access_enable
    let and_id = format!("{}_start_condition", cache_name);
    let mut and_node = Node::with_defaults(Some(and_id.clone()));
    and_node.data.insert("type".to_string(), json!("logical_and"));
    and_node.data.insert("pipeline_component".to_string(), json!(true));
    and_node.data.insert("bit_width".to_string(), json!(1));
    graph.add_node(and_node);

    let mut d0 = HashMap::new();
    d0.insert("type".to_string(), json!("logic_input"));
    d0.insert("operand_position".to_string(), json!(0));
    graph.add_edge(make_edge_with_data(&idle_id, &and_id, d0));

    let mut d1 = HashMap::new();
    d1.insert("type".to_string(), json!("logic_input"));
    d1.insert("operand_position".to_string(), json!(1));
    graph.add_edge(make_edge_with_data(&access_enable_id, &and_id, d1));

    let mut op_d = HashMap::new();
    op_d.insert("type".to_string(), json!("operand"));
    graph.add_edge(make_edge_with_data(&and_id, &start_id, op_d));

    info!("  Wired {} = {} && {}", start_id, idle_id, access_enable_id);

    if let Some(cn) = graph.nodes.get_mut(cache_name) {
        cn.data.insert("access_enable_signal".to_string(), json!(&access_enable_id));
    }

    true
}

/// Add pipeline stall logic for read-only cache miss handling.
pub fn add_cache_latency_stalls(graph: &mut ResourceGraph, cache_name: &str, stage_name: Option<&str>) -> bool {
    let cache_type = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("type"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    if cache_type.as_deref() != Some("read_only_cache") {
        info!("ERROR: {} is not a read_only_cache", cache_name);
        return false;
    }

    info!("Adding cache latency stalls for {}...", cache_name);

    // Wire start signal if not already done
    let has_access_enable = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("access_enable_signal"))
        .is_some();
    if !has_access_enable {
        wire_cache_start_signal(graph, cache_name);
    }

    let complete_signal_id = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("complete_signal"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let access_enable_id = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("access_enable_signal"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    let complete_signal_id = match complete_signal_id {
        Some(id) => id,
        None => {
            info!("  ERROR: Cache {} missing complete signal", cache_name);
            return false;
        }
    };

    if !graph.nodes.contains_key(&complete_signal_id) {
        info!("  ERROR: Complete signal {} not found", complete_signal_id);
        return false;
    }

    // Create !complete
    let not_complete_id = format!("{}_not_complete", cache_name);
    if !graph.nodes.contains_key(&not_complete_id) {
        let mut not_complete = Node::with_defaults(Some(not_complete_id.clone()));
        not_complete.data.insert("type".to_string(), json!("operation"));
        not_complete.data.insert("operator".to_string(), json!("!"));
        not_complete.data.insert("name".to_string(), json!(&not_complete_id));
        not_complete.data.insert("pipeline_component".to_string(), json!(true));
        not_complete.data.insert("bit_width".to_string(), json!(1));
        graph.add_node(not_complete);

        let mut d = HashMap::new();
        d.insert("type".to_string(), json!("operand"));
        d.insert("operand_position".to_string(), json!(0));
        graph.add_edge(make_edge_with_data(&complete_signal_id, &not_complete_id, d));
    }

    // Create stall condition: !complete && access_enable
    let stall_signal_id = if let Some(ref ae_id) = access_enable_id {
        if graph.nodes.contains_key(ae_id) {
            let stall_and_id = format!("{}_stall_condition", cache_name);
            if !graph.nodes.contains_key(&stall_and_id) {
                let mut stall_and = Node::with_defaults(Some(stall_and_id.clone()));
                stall_and.data.insert("type".to_string(), json!("operation"));
                stall_and.data.insert("operator".to_string(), json!("&&"));
                stall_and.data.insert("name".to_string(), json!(&stall_and_id));
                stall_and.data.insert("pipeline_component".to_string(), json!(true));
                stall_and.data.insert("bit_width".to_string(), json!(1));
                graph.add_node(stall_and);

                let mut d0 = HashMap::new();
                d0.insert("type".to_string(), json!("operand"));
                d0.insert("operand_index".to_string(), json!(0));
                graph.add_edge(make_edge_with_data(&not_complete_id, &stall_and_id, d0));

                let mut d1 = HashMap::new();
                d1.insert("type".to_string(), json!("operand"));
                d1.insert("operand_index".to_string(), json!(1));
                graph.add_edge(make_edge_with_data(ae_id, &stall_and_id, d1));
            }
            info!("  Created stall condition: !{} && {}", complete_signal_id, ae_id);
            stall_and_id
        } else {
            info!("  Created stall condition: !{}", complete_signal_id);
            not_complete_id.clone()
        }
    } else {
        info!("  Created stall condition: !{}", complete_signal_id);
        not_complete_id.clone()
    };

    // Determine stage
    let stage = match stage_name {
        Some(s) => s.to_string(),
        None => {
            let memory_name = graph
                .nodes
                .get(cache_name)
                .and_then(|n| n.data.get("memory_name"))
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if memory_name.to_lowercase().contains("imem") {
                "Fetch".to_string()
            } else {
                "Memory".to_string()
            }
        }
    };

    if let Some(cn) = graph.nodes.get_mut(cache_name) {
        cn.data.insert("stall_condition_node".to_string(), json!(&stall_signal_id));
        cn.data.insert("stall_stage".to_string(), json!(&stage));
    }
    info!("  Marked cache with stall_condition={} for hazard resolution", stall_signal_id);

    info!("  Cache latency stalls configured for {}", cache_name);
    true
}

/// Add pipeline stall logic for read-write cache.
/// Creates separate stall conditions for reads and writes.
pub fn add_rwcache_latency_stalls(graph: &mut ResourceGraph, cache_name: &str, stage_name: Option<&str>) -> bool {
    let cache_type = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("type"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    if cache_type.as_deref() != Some("read_write_cache") {
        info!("ERROR: {} is not a read_write_cache", cache_name);
        return false;
    }

    info!("Adding cache latency stalls for {}...", cache_name);

    // Wire start signal if not done
    let has_access_enable = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("access_enable_signal"))
        .is_some();
    if !has_access_enable {
        wire_rwcache_start_signal(graph, cache_name);
    }

    let complete_signal_id = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("complete_signal"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let write_complete_signal_id = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("write_complete_signal"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    let complete_signal_id = match complete_signal_id {
        Some(id) => id,
        None => {
            info!("  ERROR: Cache {} missing complete signal", cache_name);
            return false;
        }
    };

    if !graph.nodes.contains_key(&complete_signal_id) {
        info!("  ERROR: Complete signal {} not found", complete_signal_id);
        return false;
    }

    let has_write_complete = write_complete_signal_id
        .as_ref()
        .map(|id| graph.nodes.contains_key(id))
        .unwrap_or(false);

    // Get read request nodes
    let cache_in_eids: Vec<String> = graph.nodes.get(cache_name)
        .map(|n| n.incoming_edges.iter().cloned().collect::<Vec<_>>())
        .unwrap_or_default();
    let read_req_ids: Vec<String> = cache_in_eids.iter()
        .filter_map(|eid| graph.edges.get(eid))
        .filter(|e| e.data.get("type").and_then(|v| v.as_str()) == Some("cache_read_req"))
        .filter_map(|e| {
            let port_idx = e.data.get("port_index").and_then(|v| v.as_u64()).unwrap_or(0);
            let id = format!("{}_read_req_{}", cache_name, port_idx);
            if graph.nodes.contains_key(&id) { Some(id) } else { None }
        })
        .collect();

    let write_enable_id = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("combined_write_enable"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let has_write_enable = write_enable_id
        .as_ref()
        .map(|id| graph.nodes.contains_key(id))
        .unwrap_or(false);

    // Validity-gated write enable
    let mut write_enable_valid_gated_id: Option<String> = None;
    if let Some(ref we_id) = write_enable_id {
        if has_write_enable {
            let gated_id = format!("{}_valid_gated", we_id);
            if graph.nodes.contains_key(&gated_id) {
                write_enable_valid_gated_id = Some(gated_id);
            } else {
                let mem_valid_id = find_memory_stage_valid_id(graph).unwrap_or_else(|| "PIPE_Memory_valid_PIPE".to_string());
                if graph.nodes.contains_key(&mem_valid_id) {
                    let mut gated_node = Node::with_defaults(Some(gated_id.clone()));
                    gated_node.data.insert("type".to_string(), json!("operation"));
                    gated_node.data.insert("operator".to_string(), json!("&&"));
                    gated_node.data.insert("name".to_string(), json!(&gated_id));
                    gated_node.data.insert("pipeline_component".to_string(), json!(true));
                    gated_node.data.insert("bit_width".to_string(), json!(1));
                    graph.add_node(gated_node);

                    let mut d0 = HashMap::new();
                    d0.insert("type".to_string(), json!("operand"));
                    d0.insert("operand_index".to_string(), json!(0));
                    graph.add_edge(make_edge_with_data(we_id, &gated_id, d0));

                    let mut d1 = HashMap::new();
                    d1.insert("type".to_string(), json!("operand"));
                    d1.insert("operand_index".to_string(), json!(1));
                    graph.add_edge(make_edge_with_data(&mem_valid_id, &gated_id, d1));

                    write_enable_valid_gated_id = Some(gated_id);
                }
            }
        }
    }

    // Create !complete for reads
    let not_complete_id = format!("{}_not_complete", cache_name);
    if !graph.nodes.contains_key(&not_complete_id) {
        let mut not_complete = Node::with_defaults(Some(not_complete_id.clone()));
        not_complete.data.insert("type".to_string(), json!("operation"));
        not_complete.data.insert("operator".to_string(), json!("!"));
        not_complete.data.insert("name".to_string(), json!(&not_complete_id));
        not_complete.data.insert("pipeline_component".to_string(), json!(true));
        not_complete.data.insert("bit_width".to_string(), json!(1));
        graph.add_node(not_complete);

        let mut d = HashMap::new();
        d.insert("type".to_string(), json!("operand"));
        d.insert("operand_position".to_string(), json!(0));
        graph.add_edge(make_edge_with_data(&complete_signal_id, &not_complete_id, d));
    }

    let mut stall_conditions: Vec<String> = Vec::new();

    // Read stall: find Memory stage rd_enable signal
    let backing_mem_name = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("memory_name"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let mem_rd_enable_id = backing_mem_name.as_ref().map(|mn| format!("{}_addr_rd_enable", mn));
    let has_mem_rd_enable = mem_rd_enable_id
        .as_ref()
        .map(|id| graph.nodes.contains_key(id))
        .unwrap_or(false);

    // Validity-gated read enable
    let mut stall_rd_enable_id: Option<String> = None;
    if let Some(ref mre_id) = mem_rd_enable_id {
        if has_mem_rd_enable {
            let gated_rd_id = format!("{}_valid_gated", mre_id);
            if graph.nodes.contains_key(&gated_rd_id) {
                stall_rd_enable_id = Some(gated_rd_id);
            } else {
                let mem_valid_id = find_memory_stage_valid_id(graph).unwrap_or_else(|| "PIPE_Memory_valid_PIPE".to_string());
                if graph.nodes.contains_key(&mem_valid_id) {
                    let mut gated_rd_node = Node::with_defaults(Some(gated_rd_id.clone()));
                    gated_rd_node.data.insert("type".to_string(), json!("operation"));
                    gated_rd_node.data.insert("operator".to_string(), json!("&&"));
                    gated_rd_node.data.insert("name".to_string(), json!(&gated_rd_id));
                    gated_rd_node.data.insert("pipeline_component".to_string(), json!(true));
                    gated_rd_node.data.insert("bit_width".to_string(), json!(1));
                    graph.add_node(gated_rd_node);

                    let mut d0 = HashMap::new();
                    d0.insert("type".to_string(), json!("operand"));
                    d0.insert("operand_index".to_string(), json!(0));
                    graph.add_edge(make_edge_with_data(mre_id, &gated_rd_id, d0));

                    let mut d1 = HashMap::new();
                    d1.insert("type".to_string(), json!("operand"));
                    d1.insert("operand_index".to_string(), json!(1));
                    graph.add_edge(make_edge_with_data(&mem_valid_id, &gated_rd_id, d1));

                    stall_rd_enable_id = Some(gated_rd_id);
                } else {
                    stall_rd_enable_id = Some(mre_id.clone());
                }
            }
        }
    }

    // Create read stall condition
    if let Some(ref sre_id) = stall_rd_enable_id {
        let read_stall_id = format!("{}_read_stall", cache_name);
        if !graph.nodes.contains_key(&read_stall_id) {
            let mut read_stall = Node::with_defaults(Some(read_stall_id.clone()));
            read_stall.data.insert("type".to_string(), json!("operation"));
            read_stall.data.insert("operator".to_string(), json!("&&"));
            read_stall.data.insert("name".to_string(), json!(&read_stall_id));
            read_stall.data.insert("pipeline_component".to_string(), json!(true));
            read_stall.data.insert("bit_width".to_string(), json!(1));
            graph.add_node(read_stall);

            let mut d0 = HashMap::new();
            d0.insert("type".to_string(), json!("operand"));
            d0.insert("operand_index".to_string(), json!(0));
            graph.add_edge(make_edge_with_data(sre_id, &read_stall_id, d0));

            let mut d1 = HashMap::new();
            d1.insert("type".to_string(), json!("operand"));
            d1.insert("operand_index".to_string(), json!(1));
            graph.add_edge(make_edge_with_data(&not_complete_id, &read_stall_id, d1));
        }
        stall_conditions.push(read_stall_id);
    } else if !read_req_ids.is_empty() {
        // Fallback: use read_req nodes
        let read_req_or_id = if read_req_ids.len() == 1 {
            read_req_ids[0].clone()
        } else {
            let or_id = format!("{}_read_req_any", cache_name);
            if !graph.nodes.contains_key(&or_id) {
                let mut or_node = Node::with_defaults(Some(or_id.clone()));
                or_node.data.insert("type".to_string(), json!("logical_or"));
                or_node.data.insert("pipeline_component".to_string(), json!(true));
                or_node.data.insert("bit_width".to_string(), json!(1));
                graph.add_node(or_node);

                for (i, req_id) in read_req_ids.iter().enumerate() {
                    let mut d = HashMap::new();
                    d.insert("type".to_string(), json!("logic_input"));
                    d.insert("operand_position".to_string(), json!(i));
                    graph.add_edge(make_edge_with_data(req_id, &or_id, d));
                }
            }
            or_id
        };

        let read_stall_id = format!("{}_read_stall", cache_name);
        if !graph.nodes.contains_key(&read_stall_id) {
            let mut read_stall = Node::with_defaults(Some(read_stall_id.clone()));
            read_stall.data.insert("type".to_string(), json!("operation"));
            read_stall.data.insert("operator".to_string(), json!("&&"));
            read_stall.data.insert("name".to_string(), json!(&read_stall_id));
            read_stall.data.insert("pipeline_component".to_string(), json!(true));
            read_stall.data.insert("bit_width".to_string(), json!(1));
            graph.add_node(read_stall);

            let mut d0 = HashMap::new();
            d0.insert("type".to_string(), json!("operand"));
            d0.insert("operand_index".to_string(), json!(0));
            graph.add_edge(make_edge_with_data(&read_req_or_id, &read_stall_id, d0));

            let mut d1 = HashMap::new();
            d1.insert("type".to_string(), json!("operand"));
            d1.insert("operand_index".to_string(), json!(1));
            graph.add_edge(make_edge_with_data(&not_complete_id, &read_stall_id, d1));
        }
        stall_conditions.push(read_stall_id);
    }

    // Write stall condition: write_enable && !write_complete
    if has_write_enable && has_write_complete {
        let wc_id = write_complete_signal_id.as_ref().unwrap();
        let not_write_complete_id = format!("{}_not_write_complete", cache_name);
        if !graph.nodes.contains_key(&not_write_complete_id) {
            let mut not_wc = Node::with_defaults(Some(not_write_complete_id.clone()));
            not_wc.data.insert("type".to_string(), json!("operation"));
            not_wc.data.insert("operator".to_string(), json!("!"));
            not_wc.data.insert("name".to_string(), json!(&not_write_complete_id));
            not_wc.data.insert("pipeline_component".to_string(), json!(true));
            not_wc.data.insert("bit_width".to_string(), json!(1));
            graph.add_node(not_wc);

            let mut d = HashMap::new();
            d.insert("type".to_string(), json!("operand"));
            d.insert("operand_position".to_string(), json!(0));
            graph.add_edge(make_edge_with_data(wc_id, &not_write_complete_id, d));
        }

        let write_stall_id = format!("{}_write_stall", cache_name);
        if !graph.nodes.contains_key(&write_stall_id) {
            let stall_enable_id = write_enable_valid_gated_id
                .as_deref()
                .or(write_enable_id.as_deref())
                .unwrap();

            let mut write_stall = Node::with_defaults(Some(write_stall_id.clone()));
            write_stall.data.insert("type".to_string(), json!("operation"));
            write_stall.data.insert("operator".to_string(), json!("&&"));
            write_stall.data.insert("name".to_string(), json!(&write_stall_id));
            write_stall.data.insert("pipeline_component".to_string(), json!(true));
            write_stall.data.insert("bit_width".to_string(), json!(1));
            graph.add_node(write_stall);

            let mut d0 = HashMap::new();
            d0.insert("type".to_string(), json!("operand"));
            d0.insert("operand_index".to_string(), json!(0));
            graph.add_edge(make_edge_with_data(stall_enable_id, &write_stall_id, d0));

            let mut d1 = HashMap::new();
            d1.insert("type".to_string(), json!("operand"));
            d1.insert("operand_index".to_string(), json!(1));
            graph.add_edge(make_edge_with_data(&not_write_complete_id, &write_stall_id, d1));
        }
        stall_conditions.push(write_stall_id);
    }

    // Combine stall conditions with OR
    let stall_signal_id = if stall_conditions.is_empty() {
        info!("  WARNING: No stall conditions created for {}", cache_name);
        not_complete_id.clone()
    } else if stall_conditions.len() == 1 {
        stall_conditions[0].clone()
    } else {
        let stall_or_id = format!("{}_stall_condition", cache_name);
        if !graph.nodes.contains_key(&stall_or_id) {
            let mut stall_or = Node::with_defaults(Some(stall_or_id.clone()));
            stall_or.data.insert("type".to_string(), json!("logical_or"));
            stall_or.data.insert("pipeline_component".to_string(), json!(true));
            stall_or.data.insert("bit_width".to_string(), json!(1));
            graph.add_node(stall_or);

            for (i, cond_id) in stall_conditions.iter().enumerate() {
                let mut d = HashMap::new();
                d.insert("type".to_string(), json!("logic_input"));
                d.insert("operand_position".to_string(), json!(i));
                graph.add_edge(make_edge_with_data(cond_id, &stall_or_id, d));
            }
        }
        stall_or_id
    };

    // Determine stage
    let stage = match stage_name {
        Some(s) => s.to_string(),
        None => "Memory".to_string(),
    };

    if let Some(cn) = graph.nodes.get_mut(cache_name) {
        cn.data.insert("stall_condition_node".to_string(), json!(&stall_signal_id));
        cn.data.insert("stall_stage".to_string(), json!(&stage));
    }
    info!("  Marked cache with stall_condition={} for hazard resolution", stall_signal_id);

    info!("  Cache latency stalls configured for {}", cache_name);
    true
}

/// Connect the cache's write-through interface properly.
pub fn connect_rwcache_write_through(graph: &mut ResourceGraph, cache_name: &str, memory_name: &str) -> bool {
    if !graph.nodes.contains_key(cache_name) {
        info!("  WARNING: {} not found", cache_name);
        return false;
    }

    let wt_port_id = graph
        .nodes
        .get(cache_name)
        .and_then(|n| n.data.get("write_through_port"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    let wt_port_id = match wt_port_id {
        Some(id) => id,
        None => {
            info!("  No write-through port for {} (read-only)", cache_name);
            return true; // Not an error, just no writes
        }
    };

    if !graph.nodes.contains_key(&wt_port_id) {
        info!("  WARNING: Write-through port {} not found", wt_port_id);
        return false;
    }

    // Verify connection to memory exists
    let wt_out_eids: Vec<String> = graph.nodes.get(&wt_port_id)
        .map(|n| n.outgoing_edges.iter().cloned().collect::<Vec<_>>())
        .unwrap_or_default();
    let has_memory_edge = wt_out_eids.iter()
        .filter_map(|eid| graph.edges.get(eid))
        .any(|e| e.data.get("type").and_then(|v| v.as_str()) == Some("memory_write"));

    if !has_memory_edge {
        info!("  WARNING: Write-through port not connected to memory");
        return false;
    }

    info!("  Write-through path verified: {} -> {}", cache_name, memory_name);

    // Connect write_through_req to memory's access_enable
    let wt_req_id = format!("{}_write_through_req", cache_name);
    if !graph.nodes.contains_key(&wt_req_id) {
        info!("  WARNING: {} not found - creating it", wt_req_id);
        let mut wt_req_node = Node::with_defaults(Some(wt_req_id.clone()));
        wt_req_node.data.insert("type".to_string(), json!("var"));
        wt_req_node.data.insert("name".to_string(), json!(&wt_req_id));
        wt_req_node.data.insert("bit_width".to_string(), json!(1));
        wt_req_node.data.insert("cache_name".to_string(), json!(cache_name));
        wt_req_node.data.insert("cache_interface".to_string(), json!("write_through_req"));
        graph.add_node(wt_req_node);
    }

    let access_enable_id = format!("{}_access_enable", memory_name);
    if !graph.nodes.contains_key(&access_enable_id) {
        info!("  WARNING: {} not found", access_enable_id);
        return false;
    }

    let ae_in_eids: Vec<String> = graph.nodes.get(&access_enable_id)
        .map(|n| n.incoming_edges.iter().cloned().collect::<Vec<_>>())
        .unwrap_or_default();
    let existing_inputs = ae_in_eids.iter()
        .filter_map(|eid| graph.edges.get(eid))
        .filter(|e| e.data.get("type").and_then(|v| v.as_str()) == Some("logic_input"))
        .count();

    let mut d = HashMap::new();
    d.insert("type".to_string(), json!("logic_input"));
    d.insert("operand_position".to_string(), json!(existing_inputs));
    graph.add_edge(make_edge_with_data(&wt_req_id, &access_enable_id, d));

    info!("  Connected {} to {} (input {})", wt_req_id, access_enable_id, existing_inputs);
    true
}

/// Add arbitration logic for memory access when multiple caches share a memory.
pub fn add_memory_access_arbiter(graph: &mut ResourceGraph, memories: &[String]) -> bool {
    if memories.is_empty() {
        return true;
    }

    // The python_bindings passes a list of memory names.
    // We process the first one (matching the Python API pattern).
    let memory_name = &memories[0];
    info!("=== Adding memory access arbiter for {} ===", memory_name);

    if !graph.nodes.contains_key(memory_name.as_str()) {
        info!("  ERROR: Memory {} not found", memory_name);
        return false;
    }

    let complete_signal_id = graph
        .nodes
        .get(memory_name.as_str())
        .and_then(|n| n.data.get("complete_signal"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let start_signal_id = graph
        .nodes
        .get(memory_name.as_str())
        .and_then(|n| n.data.get("start_signal"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    let complete_signal_id = match complete_signal_id {
        Some(id) => id,
        None => {
            info!("  ERROR: Memory {} missing complete signal", memory_name);
            return false;
        }
    };

    if !graph.nodes.contains_key(&complete_signal_id) {
        info!("  ERROR: Complete signal {} not found", complete_signal_id);
        return false;
    }

    // Find access_enable node
    let access_enable_id = format!("{}_access_enable", memory_name);
    if !graph.nodes.contains_key(&access_enable_id) {
        info!("  WARNING: {} not found - no arbitration needed", access_enable_id);
        return true;
    }

    // Discover request sources from the access_enable OR gate inputs
    let ae_in_eids: Vec<String> = graph.nodes.get(&access_enable_id)
        .map(|n| n.incoming_edges.iter().cloned().collect::<Vec<_>>())
        .unwrap_or_default();
    let mut request_source_ids: Vec<String> = ae_in_eids.iter()
        .filter_map(|eid| graph.edges.get(eid))
        .filter(|e| e.data.get("type").and_then(|v| v.as_str()) == Some("logic_input"))
        .map(|e| e.source.clone())
        .filter(|src| src.contains("_refill_req") || src.contains("_write_through_req"))
        .collect();

    if request_source_ids.len() <= 1 {
        info!("  Only {} cache request source(s) - no arbitration needed", request_source_ids.len());
        return true;
    }

    info!("  Found {} request sources requiring arbitration", request_source_ids.len());

    // Sort by priority (ascending): icache refill < dcache refill < write_through
    request_source_ids.sort_by_key(|src| {
        if src.contains("write_through") { 3 }
        else if src.contains("dcache") && src.contains("refill") { 2 }
        else if src.contains("icache") || src.contains("refill") { 1 }
        else { 0 }
    });

    // Create grant signals for each source
    let mut grant_ids: Vec<String> = Vec::new();

    for i in 0..request_source_ids.len() {
        let source_id = &request_source_ids[i];
        let source_name = source_id.replace("_req", "");
        let grant_id = format!("{}_grant", source_name);

        let higher_priority: Vec<String> = request_source_ids[i + 1..].to_vec();

        if higher_priority.is_empty() {
            // Highest priority - grant when requesting
            let mut grant_node = Node::with_defaults(Some(grant_id.clone()));
            grant_node.data.insert("type".to_string(), json!("var"));
            grant_node.data.insert("name".to_string(), json!(&grant_id));
            grant_node.data.insert("bit_width".to_string(), json!(1));
            grant_node.data.insert("is_grant_signal".to_string(), json!(true));
            grant_node.data.insert("source_req".to_string(), json!(source_id));
            graph.add_node(grant_node);
            graph.add_edge(typed_edge(source_id, &grant_id, "assignment"));
        } else {
            // Create negated higher priority signals
            let mut not_hp_ids: Vec<String> = Vec::new();
            for hp_src in &higher_priority {
                let not_hp_id = format!("not_{}", hp_src);
                if !graph.nodes.contains_key(&not_hp_id) {
                    let mut not_hp = Node::with_defaults(Some(not_hp_id.clone()));
                    not_hp.data.insert("type".to_string(), json!("operation"));
                    not_hp.data.insert("operator".to_string(), json!("!"));
                    not_hp.data.insert("name".to_string(), json!(&not_hp_id));
                    not_hp.data.insert("bit_width".to_string(), json!(1));
                    graph.add_node(not_hp);

                    let mut d = HashMap::new();
                    d.insert("type".to_string(), json!("operand"));
                    d.insert("operand_position".to_string(), json!(0));
                    graph.add_edge(make_edge_with_data(hp_src, &not_hp_id, d));
                }
                not_hp_ids.push(not_hp_id);
            }

            // AND gate: req && !higher1 && !higher2 ...
            let mut grant_node = Node::with_defaults(Some(grant_id.clone()));
            grant_node.data.insert("type".to_string(), json!("logical_and"));
            grant_node.data.insert("name".to_string(), json!(&grant_id));
            grant_node.data.insert("bit_width".to_string(), json!(1));
            grant_node.data.insert("is_grant_signal".to_string(), json!(true));
            grant_node.data.insert("source_req".to_string(), json!(source_id));
            graph.add_node(grant_node);

            // Connect all inputs
            let mut all_inputs = vec![source_id.clone()];
            all_inputs.extend(not_hp_ids);

            for (j, inp_id) in all_inputs.iter().enumerate() {
                let mut d = HashMap::new();
                d.insert("type".to_string(), json!("logic_input"));
                d.insert("operand_position".to_string(), json!(j));
                graph.add_edge(make_edge_with_data(inp_id, &grant_id, d));
            }
        }

        grant_ids.push(grant_id.clone());
        info!("  Created {}", grant_id);
    }

    // Create registered grant signals
    let mut reg_grant_ids: Vec<String> = Vec::new();

    for grant_id in &grant_ids {
        let reg_grant_id = format!("{}_reg", grant_id);
        let mut reg_grant = Node::with_defaults(Some(reg_grant_id.clone()));
        reg_grant.data.insert("type".to_string(), json!("register"));
        reg_grant.data.insert("name".to_string(), json!(&reg_grant_id));
        reg_grant.data.insert("bit_width".to_string(), json!(1));
        reg_grant.data.insert("is_registered_grant".to_string(), json!(true));
        reg_grant.data.insert("grant_signal".to_string(), json!(grant_id));
        if let Some(ref sid) = start_signal_id {
            reg_grant.data.insert("latch_condition".to_string(), json!(sid));
        }
        reg_grant.data.insert("clear_condition".to_string(), json!(&complete_signal_id));
        graph.add_node(reg_grant);

        let mut d = HashMap::new();
        d.insert("type".to_string(), json!("register_input"));
        if let Some(ref sid) = start_signal_id {
            d.insert("latch_on".to_string(), json!(sid));
        }
        d.insert("clear_on".to_string(), json!(&complete_signal_id));
        graph.add_edge(make_edge_with_data(grant_id, &reg_grant_id, d));

        if let Some(ref sid) = start_signal_id {
            if graph.nodes.contains_key(sid.as_str()) {
                let mut ld = HashMap::new();
                ld.insert("type".to_string(), json!("latch_enable"));
                graph.add_edge(make_edge_with_data(sid, &reg_grant_id, ld));
            }
        }

        reg_grant_ids.push(reg_grant_id.clone());
        info!("  Created registered grant: {}", reg_grant_id);
    }

    // Rewire completion signals gated with registered grants
    for (idx, grant_id) in grant_ids.iter().enumerate() {
        let reg_grant_id = &reg_grant_ids[idx];

        let source_req_id = graph
            .nodes
            .get(grant_id.as_str())
            .and_then(|n| n.data.get("source_req"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        let source_req_id = match source_req_id {
            Some(id) => id,
            None => continue,
        };

        // Determine completion signal
        let completion_id = if source_req_id.contains("write_through") {
            source_req_id.replace("_req", "_complete")
        } else {
            source_req_id.replace("_req", "_valid")
        };

        if !graph.nodes.contains_key(&completion_id) {
            info!("  WARNING: Completion signal {} not found", completion_id);
            continue;
        }

        // Find and remove old edge from memory_complete to completion
        let comp_in_eids: Vec<String> = graph.nodes.get(&completion_id)
            .map(|n| n.incoming_edges.iter().cloned().collect::<Vec<_>>())
            .unwrap_or_default();
        let old_edge_id: Option<String> = comp_in_eids.iter()
            .filter_map(|eid| graph.edges.get(eid))
            .find(|e| e.source == complete_signal_id && e.data.get("type").and_then(|v| v.as_str()) == Some("assignment"))
            .map(|e| e.id.clone());

        if let Some(eid) = old_edge_id {
            graph.remove_edge(&eid);
            info!("  Removed direct {} -> {}", complete_signal_id, completion_id);
        }

        // Use direct resp_ready signals
        let completion_source_id = if source_req_id.contains("write_through") {
            let resp_ready_id = format!("{}_write_resp_ready", memory_name);
            if !graph.nodes.contains_key(&resp_ready_id) {
                let mut resp_ready = Node::with_defaults(Some(resp_ready_id.clone()));
                resp_ready.data.insert("type".to_string(), json!("external_input"));
                resp_ready.data.insert("name".to_string(), json!(&resp_ready_id));
                resp_ready.data.insert("bit_width".to_string(), json!(1));
                resp_ready.data.insert("is_external_port".to_string(), json!(true));
                graph.add_node(resp_ready);
                info!("  Created external input node: {}", resp_ready_id);
            }
            resp_ready_id
        } else if source_req_id.contains("refill") {
            let cache_prefix = source_req_id.replace("_refill_req", "");
            let resp_ready_id = format!("{}_{}_refill_addr_read_resp_ready", memory_name, cache_prefix);
            if !graph.nodes.contains_key(&resp_ready_id) {
                let mut resp_ready = Node::with_defaults(Some(resp_ready_id.clone()));
                resp_ready.data.insert("type".to_string(), json!("external_input"));
                resp_ready.data.insert("name".to_string(), json!(&resp_ready_id));
                resp_ready.data.insert("bit_width".to_string(), json!(1));
                resp_ready.data.insert("is_external_port".to_string(), json!(true));
                graph.add_node(resp_ready);
                info!("  Created external input node: {}", resp_ready_id);
            }
            resp_ready_id
        } else {
            complete_signal_id.clone()
        };

        let gated_complete_id = format!("{}_gated", completion_id);
        let mut gated_complete = Node::with_defaults(Some(gated_complete_id.clone()));
        gated_complete.data.insert("type".to_string(), json!("logical_and"));
        gated_complete.data.insert("name".to_string(), json!(&gated_complete_id));
        gated_complete.data.insert("bit_width".to_string(), json!(1));
        graph.add_node(gated_complete);

        let mut d0 = HashMap::new();
        d0.insert("type".to_string(), json!("logic_input"));
        d0.insert("operand_position".to_string(), json!(0));
        graph.add_edge(make_edge_with_data(&completion_source_id, &gated_complete_id, d0));

        let mut d1 = HashMap::new();
        d1.insert("type".to_string(), json!("logic_input"));
        d1.insert("operand_position".to_string(), json!(1));
        graph.add_edge(make_edge_with_data(reg_grant_id, &gated_complete_id, d1));

        graph.add_edge(typed_edge(&gated_complete_id, &completion_id, "assignment"));
        info!("  Rewired {} = {} && {}", completion_id, completion_source_id, reg_grant_id);
    }

    // Store grant register IDs in memory node
    if let Some(mn) = graph.nodes.get_mut(memory_name.as_str()) {
        mn.data.insert("arbiter_grant_regs".to_string(), json!(reg_grant_ids));
        info!("    Generated arbiter registers: {:?}", reg_grant_ids);
    }

    info!("  Memory arbiter configured successfully");
    true
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_test_graph_with_memory(mem_name: &str) -> ResourceGraph {
        let mut graph = ResourceGraph::new();

        // Memory node
        let mut mem = Node::with_defaults(Some(mem_name.to_string()));
        mem.data.insert("type".to_string(), json!("isa_state mem"));
        mem.data.insert("name".to_string(), json!(mem_name));
        mem.data.insert("is_memory".to_string(), json!(true));
        mem.data.insert("bit_width".to_string(), json!(32));
        mem.data.insert("array_depth".to_string(), json!(10));
        graph.add_node(mem);

        // Array access node (read)
        let aa_id = format!("{}[pc_rd]_rd", mem_name);
        let mut aa = Node::with_defaults(Some(aa_id.clone()));
        aa.data.insert("type".to_string(), json!("array_access"));
        aa.data.insert("access_mode".to_string(), json!("read"));
        aa.data.insert("bit_width".to_string(), json!(32));
        graph.add_node(aa);

        // Address node
        let addr_id = "pc_rd".to_string();
        let mut addr = Node::with_defaults(Some(addr_id.clone()));
        addr.data.insert("type".to_string(), json!("var"));
        addr.data.insert("name".to_string(), json!("pc_rd"));
        addr.data.insert("bit_width".to_string(), json!(32));
        graph.add_node(addr);

        // Target node
        let target_id = "instr".to_string();
        let mut target = Node::with_defaults(Some(target_id.clone()));
        target.data.insert("type".to_string(), json!("var"));
        target.data.insert("name".to_string(), json!("instr"));
        target.data.insert("bit_width".to_string(), json!(32));
        graph.add_node(target);

        // Edges
        graph.add_edge(typed_edge(mem_name, &aa_id, "array_base"));
        graph.add_edge(typed_edge(&addr_id, &aa_id, "array_index"));
        graph.add_edge(typed_edge(&aa_id, &target_id, "assignment"));

        graph
    }

    #[test]
    fn test_ro_cache_spec_validation() {
        let spec = ReadOnlyCacheSpec::new("imem");
        assert!(spec.validate().is_ok());

        let mut spec = ReadOnlyCacheSpec::new("imem");
        spec.associativity = 3;
        assert!(spec.validate().is_err());

        spec.associativity = 4;
        spec.num_rows = 100;
        assert!(spec.validate().is_err());

        spec.num_rows = 128;
        spec.block_size = 17;
        assert!(spec.validate().is_err());
    }

    #[test]
    fn test_rw_cache_spec_validation() {
        let spec = ReadWriteCacheSpec::new("dmem");
        assert!(spec.validate().is_ok());

        let mut spec = ReadWriteCacheSpec::new("dmem");
        spec.replacement_policy = "invalid".to_string();
        assert!(spec.validate().is_err());

        spec.replacement_policy = "fifo".to_string();
        assert!(spec.validate().is_ok());
    }

    #[test]
    fn test_cache_widths() {
        let spec = ReadOnlyCacheSpec::new("imem");
        assert_eq!(spec.offset_width(), 5);  // block_size=32 -> 5 bits
        assert_eq!(spec.index_width(), 6);   // num_rows=64 -> 6 bits
        assert_eq!(spec.tag_width(), 21);    // 32-5-6=21
    }

    #[test]
    fn test_ro_cache_apply() {
        let mut graph = make_test_graph_with_memory("imem");
        let mut spec = ReadOnlyCacheSpec::new("imem");

        let result = apply_read_only_cache(&mut graph, &mut spec);
        assert!(result);

        // Cache node exists
        assert!(graph.nodes.contains_key("imem_cache"));
        let cache = &graph.nodes["imem_cache"];
        assert_eq!(cache.data.get("type").and_then(|v| v.as_str()), Some("read_only_cache"));

        // Control signals
        assert!(graph.nodes.contains_key("imem_cache_start"));
        assert!(graph.nodes.contains_key("imem_cache_idle"));
        assert!(graph.nodes.contains_key("imem_cache_complete"));

        // Refill interface
        assert!(graph.nodes.contains_key("imem_cache_refill_addr"));
        assert!(graph.nodes.contains_key("imem_cache_refill_data"));
        assert!(graph.nodes.contains_key("imem_cache_refill_req"));
        assert!(graph.nodes.contains_key("imem_cache_refill_valid"));

        // Read port
        assert!(graph.nodes.contains_key("imem_cache_read_addr_0"));
        assert!(graph.nodes.contains_key("imem_cache_data_0"));
        assert!(graph.nodes.contains_key("imem_cache_read_req_0"));
        assert!(graph.nodes.contains_key("imem_cache_valid_0"));

        // Consumer redirected
        let instr_in_eids: Vec<String> = graph.nodes.get("instr")
            .map(|n| n.incoming_edges.iter().cloned().collect::<Vec<_>>())
            .unwrap_or_default();
        assert!(
            instr_in_eids.iter()
                .filter_map(|eid| graph.edges.get(eid))
                .any(|e| e.source == "imem_cache_data_0"),
            "instr should be connected to cache data output"
        );
    }

    #[test]
    fn test_rw_cache_apply() {
        let mut graph = make_test_graph_with_memory("dmem");

        // Add write port
        let wp_id = "dmem_write_port";
        let mut wp = Node::with_defaults(Some(wp_id.to_string()));
        wp.data.insert("type".to_string(), json!("memory_write_port"));
        wp.data.insert("base_memory".to_string(), json!("dmem"));
        wp.data.insert("combined_write_enable".to_string(), json!("store_enable"));
        wp.data.insert("writers".to_string(), json!(["sw", "sb"]));
        graph.add_node(wp);
        graph.add_edge(typed_edge(wp_id, "dmem", "memory_write"));

        let mut spec = ReadWriteCacheSpec::new("dmem");
        let result = apply_read_write_cache(&mut graph, &mut spec);
        assert!(result);

        // Cache node
        assert!(graph.nodes.contains_key("dmem_rwcache"));
        let cache = &graph.nodes["dmem_rwcache"];
        assert_eq!(cache.data.get("type").and_then(|v| v.as_str()), Some("read_write_cache"));

        // Write-through interface
        assert!(graph.nodes.contains_key("dmem_rwcache_write_through_addr"));
        assert!(graph.nodes.contains_key("dmem_rwcache_write_through_data"));
        assert!(graph.nodes.contains_key("dmem_rwcache_write_through_port"));
        assert!(graph.nodes.contains_key("dmem_rwcache_write_through_complete"));
        assert!(graph.nodes.contains_key("dmem_rwcache_write_complete"));
    }

    #[test]
    fn test_get_cache_nodes() {
        let mut graph = make_test_graph_with_memory("imem");
        let mut spec = ReadOnlyCacheSpec::new("imem");
        apply_read_only_cache(&mut graph, &mut spec);

        let caches = get_cache_nodes(&graph);
        assert_eq!(caches.len(), 1);
        assert!(caches.contains(&"imem_cache".to_string()));
    }

    #[test]
    fn test_cleanup_flush_placeholders() {
        let mut graph = ResourceGraph::new();

        let mut ph = Node::with_defaults(Some("flush_placeholder_icache".to_string()));
        ph.data.insert("type".to_string(), json!("flush_target_placeholder"));
        ph.data.insert("cache_name".to_string(), json!("icache"));
        graph.add_node(ph);

        assert_eq!(cleanup_unreferenced_flush_placeholders(&mut graph), 1);
        assert!(!graph.nodes.contains_key("flush_placeholder_icache"));
    }

    #[test]
    fn test_no_memory_returns_false() {
        let mut graph = ResourceGraph::new();
        let mut spec = ReadOnlyCacheSpec::new("nonexistent");
        assert!(!apply_read_only_cache(&mut graph, &mut spec));
    }
}
