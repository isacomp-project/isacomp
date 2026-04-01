use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::fmt;
use std::fs;
use std::io;
use uuid::Uuid;

// ---------------------------------------------------------------------------
// Node
// ---------------------------------------------------------------------------

/// A node in the ResourceGraph with bidirectional edge references (stored as IDs).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Node {
    pub id: String,
    pub data: HashMap<String, Value>,
    pub is_arch_state: bool,
    pub is_shared: bool,
    pub is_uarch_state: bool,
    pub used_as_index: bool,
    /// Node ID of the node that indexes this one, if any.
    pub indexed_by: Option<String>,
    pub uarch_time: Option<i64>,
    pub pipe_time: Option<i64>,
    pub pipe_id: Option<i64>,
    pub dual_issue_time: Option<i64>,
    pub from_isa_spec: bool,
    pub already_split: bool,
    pub latency: i64,
    pub variable_latency: bool,
    /// Set of edge IDs for edges coming into this node.
    pub incoming_edges: HashSet<String>,
    /// Set of edge IDs for edges going out of this node.
    pub outgoing_edges: HashSet<String>,
}

impl Node {
    /// Create a new node with the given parameters. If `node_id` is `None`, a
    /// random UUID v4 is generated.
    pub fn new(
        node_id: Option<String>,
        data: Option<HashMap<String, Value>>,
        is_arch_state: bool,
        used_as_index: bool,
        indexed_by: Option<String>,
        is_uarch_state: bool,
        uarch_time: Option<i64>,
        pipe_time: Option<i64>,
        from_isa_spec: bool,
        already_split: bool,
        latency: i64,
        variable_latency: bool,
        is_shared: bool,
        pipe_id: Option<i64>,
        dual_issue_time: Option<i64>,
    ) -> Self {
        Node {
            id: node_id.unwrap_or_else(|| Uuid::new_v4().to_string()),
            data: data.unwrap_or_default(),
            is_arch_state,
            is_shared,
            is_uarch_state,
            used_as_index,
            indexed_by,
            uarch_time,
            pipe_time,
            pipe_id,
            dual_issue_time,
            from_isa_spec,
            already_split,
            latency,
            variable_latency,
            incoming_edges: HashSet::new(),
            outgoing_edges: HashSet::new(),
        }
    }

    /// Convenience constructor with sensible defaults (mirrors Python's
    /// keyword-argument defaults).
    pub fn with_defaults(node_id: Option<String>) -> Self {
        Self::new(
            node_id,
            None,
            false, // is_arch_state
            false, // used_as_index
            None,  // indexed_by
            false, // is_uarch_state
            None,  // uarch_time
            None,  // pipe_time
            false, // from_isa_spec
            false, // already_split
            0,     // latency
            false, // variable_latency
            false, // is_shared
            None,  // pipe_id
            None,  // dual_issue_time
        )
    }

    pub fn add_incoming_edge(&mut self, edge_id: &str) {
        self.incoming_edges.insert(edge_id.to_string());
    }

    pub fn add_outgoing_edge(&mut self, edge_id: &str) {
        self.outgoing_edges.insert(edge_id.to_string());
    }

    pub fn remove_incoming_edge(&mut self, edge_id: &str) {
        self.incoming_edges.remove(edge_id);
    }

    pub fn remove_outgoing_edge(&mut self, edge_id: &str) {
        self.outgoing_edges.remove(edge_id);
    }
}

impl Default for Node {
    fn default() -> Self {
        Self::with_defaults(None)
    }
}

impl fmt::Display for Node {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let indexed_by_str = match &self.indexed_by {
            Some(id) => id.as_str(),
            None => "None",
        };
        let pipe_info = if self.pipe_id.is_some() {
            format!(
                ", pipe_id={}, dual_issue_time={}",
                opt_display(self.pipe_id),
                opt_display(self.dual_issue_time)
            )
        } else {
            String::new()
        };
        write!(
            f,
            "Node({}, data={:?}, arch_state={}, uarch_state={}, uarch_time={}, pipe_time={}{}, index={}, indexed_by={})",
            self.id,
            self.data,
            self.is_arch_state,
            self.is_uarch_state,
            opt_display(self.uarch_time),
            opt_display(self.pipe_time),
            pipe_info,
            self.used_as_index,
            indexed_by_str,
        )
    }
}

// ---------------------------------------------------------------------------
// Edge
// ---------------------------------------------------------------------------

/// An edge in the ResourceGraph connecting two nodes by their IDs.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Edge {
    pub id: String,
    pub source: String,
    pub target: String,
    pub data: HashMap<String, Value>,
}

impl Edge {
    /// Create a new edge. If `edge_id` is `None`, a random UUID v4 is generated.
    pub fn new(
        source: String,
        target: String,
        edge_id: Option<String>,
        data: Option<HashMap<String, Value>>,
    ) -> Self {
        Edge {
            id: edge_id.unwrap_or_else(|| Uuid::new_v4().to_string()),
            source,
            target,
            data: data.unwrap_or_default(),
        }
    }
}

impl fmt::Display for Edge {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "Edge({}, {} -> {}, data={:?})",
            self.id, self.source, self.target, self.data
        )
    }
}

// ---------------------------------------------------------------------------
// ResourceGraph
// ---------------------------------------------------------------------------

/// A graph data structure with nodes and edges, supporting filtering and
/// edge-node insertion.  This is the Rust equivalent of the Python
/// `ResourceGraph` class.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResourceGraph {
    pub nodes: HashMap<String, Node>,
    pub edges: HashMap<String, Edge>,
    /// Aspect declaration data (stored as arbitrary JSON values).
    pub aspect_declarations: Vec<Value>,
    /// Parsed assume constraint ASTs (stored as arbitrary JSON values).
    pub assume_expressions: Vec<Value>,
    /// Set of state names that are gated by aspects (populated by aspect_merger).
    #[serde(default)]
    pub gated_states: HashSet<String>,
}

impl Default for ResourceGraph {
    fn default() -> Self {
        Self::new()
    }
}

impl ResourceGraph {
    // ------------------------------------------------------------------
    // Construction
    // ------------------------------------------------------------------

    pub fn new() -> Self {
        ResourceGraph {
            nodes: HashMap::new(),
            edges: HashMap::new(),
            aspect_declarations: Vec::new(),
            assume_expressions: Vec::new(),
            gated_states: HashSet::new(),
        }
    }

    // ------------------------------------------------------------------
    // Node operations
    // ------------------------------------------------------------------

    /// Add a node to the graph.
    ///
    /// If a node with the same ID already exists, all edges from the old node
    /// are transferred to the new one so that graph connectivity is maintained.
    pub fn add_node(&mut self, mut node: Node) {
        if let Some(old_node) = self.nodes.remove(&node.id) {
            // Transfer incoming edges
            for edge_id in &old_node.incoming_edges {
                node.incoming_edges.insert(edge_id.clone());
            }
            // Transfer outgoing edges
            for edge_id in &old_node.outgoing_edges {
                node.outgoing_edges.insert(edge_id.clone());
            }
        }
        self.nodes.insert(node.id.clone(), node);
    }

    /// Remove a node and all its connected edges from the graph.
    pub fn remove_node(&mut self, node_id: &str) {
        if let Some(node) = self.nodes.remove(node_id) {
            let edge_ids: Vec<String> = node
                .incoming_edges
                .iter()
                .chain(node.outgoing_edges.iter())
                .cloned()
                .collect();
            for eid in edge_ids {
                self.remove_edge(&eid);
            }
        }
    }

    /// Get a reference to a node by ID.
    pub fn get_node(&self, node_id: &str) -> Option<&Node> {
        self.nodes.get(node_id)
    }

    /// Get a mutable reference to a node by ID.
    pub fn get_node_mut(&mut self, node_id: &str) -> Option<&mut Node> {
        self.nodes.get_mut(node_id)
    }

    // ------------------------------------------------------------------
    // Edge operations
    // ------------------------------------------------------------------

    /// Add an edge to the graph.
    ///
    /// The source and target nodes are updated to reflect the new edge.
    /// If the source or target node does not exist in the graph, this method
    /// will **not** create them automatically — callers must ensure that
    /// both endpoints exist. (The Python version auto-adds from the edge
    /// objects which hold direct references; in the Rust ID-based design the
    /// caller typically adds nodes first.)
    pub fn add_edge(&mut self, edge: Edge) {
        // Update source node
        if let Some(src) = self.nodes.get_mut(&edge.source) {
            src.add_outgoing_edge(&edge.id);
        }
        // Update target node
        if let Some(tgt) = self.nodes.get_mut(&edge.target) {
            tgt.add_incoming_edge(&edge.id);
        }
        self.edges.insert(edge.id.clone(), edge);
    }

    /// Remove an edge from the graph and update the endpoint nodes.
    pub fn remove_edge(&mut self, edge_id: &str) {
        if let Some(edge) = self.edges.remove(edge_id) {
            if let Some(src) = self.nodes.get_mut(&edge.source) {
                src.remove_outgoing_edge(edge_id);
            }
            if let Some(tgt) = self.nodes.get_mut(&edge.target) {
                tgt.remove_incoming_edge(edge_id);
            }
        }
    }

    /// Get a reference to an edge by ID.
    pub fn get_edge(&self, edge_id: &str) -> Option<&Edge> {
        self.edges.get(edge_id)
    }

    /// Get a mutable reference to an edge by ID.
    pub fn get_edge_mut(&mut self, edge_id: &str) -> Option<&mut Edge> {
        self.edges.get_mut(edge_id)
    }

    // ------------------------------------------------------------------
    // insert_node_on_edge
    // ------------------------------------------------------------------

    /// Insert a node on an existing edge, replacing the edge with two new
    /// edges: `source -> new_node` and `new_node -> target`.
    ///
    /// Returns the IDs of the two new edges `(edge1_id, edge2_id)`.
    pub fn insert_node_on_edge(
        &mut self,
        edge_id: &str,
        new_node: Node,
    ) -> Result<(String, String), String> {
        let old_edge = self
            .edges
            .get(edge_id)
            .ok_or_else(|| format!("Edge {} not found in graph", edge_id))?
            .clone();

        let source_id = old_edge.source.clone();
        let target_id = old_edge.target.clone();
        let edge_data = old_edge.data.clone();

        // Remove the old edge
        self.remove_edge(edge_id);

        let new_node_id = new_node.id.clone();

        // Add the new node
        self.add_node(new_node);

        // Create two new edges
        let edge1 = Edge::new(
            source_id,
            new_node_id.clone(),
            None,
            Some(edge_data.clone()),
        );
        let edge2 = Edge::new(new_node_id, target_id, None, Some(edge_data));

        let e1_id = edge1.id.clone();
        let e2_id = edge2.id.clone();

        self.add_edge(edge1);
        self.add_edge(edge2);

        Ok((e1_id, e2_id))
    }

    // ------------------------------------------------------------------
    // Filtering
    // ------------------------------------------------------------------

    /// Return all nodes that satisfy `predicate`.
    pub fn filter_nodes<F>(&self, predicate: F) -> Vec<&Node>
    where
        F: Fn(&Node) -> bool,
    {
        self.nodes.values().filter(|n| predicate(n)).collect()
    }

    /// Return all edges that satisfy `predicate`.
    pub fn filter_edges<F>(&self, predicate: F) -> Vec<&Edge>
    where
        F: Fn(&Edge) -> bool,
    {
        self.edges.values().filter(|e| predicate(e)).collect()
    }

    /// Create a subgraph containing only nodes/edges that satisfy the
    /// given predicates. An edge is included only when *both* its
    /// endpoints pass `node_predicate` **and** the edge itself passes
    /// `edge_predicate`.
    pub fn filter_subgraph<NF, EF>(
        &self,
        node_predicate: NF,
        edge_predicate: EF,
    ) -> ResourceGraph
    where
        NF: Fn(&Node) -> bool,
        EF: Fn(&Edge) -> bool,
    {
        let mut subgraph = ResourceGraph::new();

        // Collect matching node IDs
        let mut node_ids: HashSet<String> = HashSet::new();
        for node in self.nodes.values() {
            if node_predicate(node) {
                node_ids.insert(node.id.clone());
                let new_node = Node::new(
                    Some(node.id.clone()),
                    Some(node.data.clone()),
                    node.is_arch_state,
                    node.used_as_index,
                    node.indexed_by.clone(),
                    node.is_uarch_state,
                    node.uarch_time,
                    node.pipe_time,
                    node.from_isa_spec,
                    node.already_split,
                    node.latency,
                    node.variable_latency,
                    node.is_shared,
                    node.pipe_id,
                    node.dual_issue_time,
                );
                subgraph.add_node(new_node);
            }
        }

        // Add matching edges whose endpoints are both included
        for edge in self.edges.values() {
            if node_ids.contains(&edge.source)
                && node_ids.contains(&edge.target)
                && edge_predicate(edge)
            {
                let new_edge = Edge::new(
                    edge.source.clone(),
                    edge.target.clone(),
                    Some(edge.id.clone()),
                    Some(edge.data.clone()),
                );
                subgraph.add_edge(new_edge);
            }
        }

        subgraph
    }

    // ------------------------------------------------------------------
    // Counts
    // ------------------------------------------------------------------

    pub fn get_node_count(&self) -> usize {
        self.nodes.len()
    }

    pub fn get_edge_count(&self) -> usize {
        self.edges.len()
    }

    // ------------------------------------------------------------------
    // Timing inference
    // ------------------------------------------------------------------

    /// Infer `uarch_time` for all nodes in the graph.
    ///
    /// **Algorithm:**
    /// 1. ISA-state READ nodes get `uarch_time = 0`.
    /// 2. Traverse forward through the graph.
    /// 3. Each time we pass through a `uarch_state` node, increment time by 1.
    /// 4. Other nodes inherit the time from their inputs (taking the max).
    /// 5. Edges with type `stall`, `enable`, or `pipeline_control` are skipped.
    /// 6. Variable-latency sources propagate their base time.
    /// 7. Sources with `latency > 0` add their latency.
    pub fn infer_uarch_time(&mut self, force_reinfer: bool) {
        let has_existing_timing = self.nodes.values().any(|n| n.uarch_time.is_some());

        if has_existing_timing && !force_reinfer {
            let all_set = self.nodes.values().all(|n| n.uarch_time.is_some());
            if all_set {
                return;
            }
        } else {
            // Reset – but preserve pipeline_register and validity_bit times
            let ids: Vec<String> = self.nodes.keys().cloned().collect();
            for id in &ids {
                let node = self.nodes.get(id).unwrap();
                let ntype = node
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                if ntype == "pipeline_register" || ntype == "validity_bit" {
                    continue;
                }
                self.nodes.get_mut(id).unwrap().uarch_time = None;
            }
        }

        // Step 1: ISA state READ nodes -> time 0
        let node_ids: Vec<String> = self.nodes.keys().cloned().collect();
        for id in &node_ids {
            let node = &self.nodes[id];
            if !node.is_arch_state {
                continue;
            }
            if node.uarch_time.is_some() {
                continue;
            }
            let ntype = node
                .data
                .get("type")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let is_memory_access = id.contains('[') && id.contains("]_rd");
            let is_multiplexer = ntype == "multiplexer";
            let is_write_port = ntype == "memory_write_port";
            let is_write_node = id.ends_with("_wr");

            if is_memory_access || is_multiplexer || is_write_port || is_write_node {
                continue;
            }
            self.nodes.get_mut(id).unwrap().uarch_time = Some(0);
        }

        // Step 2: Forward propagation
        let max_iterations = self.nodes.len() * 2;
        for _ in 0..max_iterations {
            let mut changed = false;

            let node_ids: Vec<String> = self.nodes.keys().cloned().collect();
            for id in &node_ids {
                if self.nodes[id].uarch_time.is_some() {
                    continue;
                }

                let incoming: Vec<String> =
                    self.nodes[id].incoming_edges.iter().cloned().collect();

                let mut input_times: Vec<i64> = Vec::new();
                let mut has_all_inputs = true;
                let mut var_lat_deps: Vec<String> = Vec::new();

                for eid in &incoming {
                    let edge = match self.edges.get(eid) {
                        Some(e) => e,
                        None => continue,
                    };
                    let edge_type = edge
                        .data
                        .get("type")
                        .and_then(|v| v.as_str())
                        .unwrap_or("");
                    if edge_type == "stall"
                        || edge_type == "enable"
                        || edge_type == "pipeline_control"
                    {
                        continue;
                    }
                    let source_id = edge.source.clone();
                    let source = match self.nodes.get(&source_id) {
                        Some(n) => n,
                        None => continue,
                    };
                    if source.uarch_time.is_none() {
                        has_all_inputs = false;
                        break;
                    }
                    let src_time = source.uarch_time.unwrap();

                    if source.variable_latency {
                        input_times.push(src_time);
                        var_lat_deps.push(source_id);
                    } else if source.is_uarch_state {
                        input_times.push(src_time + 1);
                    } else if source.latency > 0 {
                        input_times.push(src_time + source.latency);
                    } else {
                        input_times.push(src_time);
                    }
                }

                if has_all_inputs && !input_times.is_empty() {
                    let base_time = *input_times.iter().max().unwrap();
                    let node = self.nodes.get_mut(id).unwrap();
                    node.uarch_time = Some(base_time);
                    if !var_lat_deps.is_empty() {
                        let existing = node
                            .data
                            .entry("depends_on_variable_latency".to_string())
                            .or_insert_with(|| Value::Array(Vec::new()));
                        if let Value::Array(arr) = existing {
                            for dep in var_lat_deps {
                                let val = Value::String(dep);
                                if !arr.contains(&val) {
                                    arr.push(val);
                                }
                            }
                        }
                    }
                    changed = true;
                } else if has_all_inputs && input_times.is_empty() {
                    self.nodes.get_mut(id).unwrap().uarch_time = Some(0);
                    changed = true;
                }
            }

            if !changed {
                break;
            }
        }

        // Fallback: remaining nodes without time
        let ids: Vec<String> = self.nodes.keys().cloned().collect();
        for id in ids {
            if self.nodes[&id].uarch_time.is_none() {
                self.nodes.get_mut(&id).unwrap().uarch_time = Some(0);
            }
        }
    }

    /// Get all nodes that execute at a specific `uarch_time`.
    pub fn get_nodes_at_time(&self, time: i64) -> Vec<&Node> {
        self.nodes
            .values()
            .filter(|n| n.uarch_time == Some(time))
            .collect()
    }

    /// Get the maximum `uarch_time` in the graph.
    pub fn get_max_uarch_time(&self) -> i64 {
        self.nodes
            .values()
            .filter_map(|n| n.uarch_time)
            .max()
            .unwrap_or(0)
    }

    /// Infer `pipe_time` for all nodes in the graph.
    ///
    /// `pipe_time` is similar to `uarch_time` but **only** increments when
    /// passing through `pipeline_register` nodes. Pipeline registers already
    /// carry their correct `pipe_time` so downstream nodes simply inherit it.
    pub fn infer_pipe_time(&mut self, force_reinfer: bool) {
        let has_existing_timing = self.nodes.values().any(|n| n.pipe_time.is_some());

        if has_existing_timing && !force_reinfer {
            let all_set = self.nodes.values().all(|n| n.pipe_time.is_some());
            if all_set {
                return;
            }
        } else {
            let ids: Vec<String> = self.nodes.keys().cloned().collect();
            for id in &ids {
                let node = self.nodes.get(id).unwrap();
                let ntype = node
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                if ntype == "pipeline_register" || ntype == "validity_bit" {
                    continue;
                }
                self.nodes.get_mut(id).unwrap().pipe_time = None;
            }
        }

        // Step 1: ISA state READ nodes -> pipe_time 0
        let node_ids: Vec<String> = self.nodes.keys().cloned().collect();
        for id in &node_ids {
            let node = &self.nodes[id];
            if !node.is_arch_state {
                continue;
            }
            if node.pipe_time.is_some() {
                continue;
            }
            let ntype = node
                .data
                .get("type")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let is_memory_access = id.contains('[') && id.contains("]_rd");
            let is_multiplexer = ntype == "multiplexer";
            let is_write_port = ntype == "memory_write_port";
            let is_write_node = id.ends_with("_wr");

            if is_memory_access || is_multiplexer || is_write_port || is_write_node {
                continue;
            }
            self.nodes.get_mut(id).unwrap().pipe_time = Some(0);
        }

        // Step 2: Forward propagation
        let max_iterations = self.nodes.len() * 2;
        for _ in 0..max_iterations {
            let mut changed = false;

            let node_ids: Vec<String> = self.nodes.keys().cloned().collect();
            for id in &node_ids {
                if self.nodes[id].pipe_time.is_some() {
                    continue;
                }

                let incoming: Vec<String> =
                    self.nodes[id].incoming_edges.iter().cloned().collect();

                let mut input_times: Vec<i64> = Vec::new();
                let mut has_all_inputs = true;

                for eid in &incoming {
                    let edge = match self.edges.get(eid) {
                        Some(e) => e,
                        None => continue,
                    };
                    let edge_type = edge
                        .data
                        .get("type")
                        .and_then(|v| v.as_str())
                        .unwrap_or("");
                    if edge_type == "stall"
                        || edge_type == "enable"
                        || edge_type == "pipeline_control"
                        || edge_type == "state_write"
                    {
                        continue;
                    }
                    let source_id = edge.source.clone();
                    let source = match self.nodes.get(&source_id) {
                        Some(n) => n,
                        None => continue,
                    };
                    if source.pipe_time.is_none() {
                        has_all_inputs = false;
                        break;
                    }
                    let src_time = source.pipe_time.unwrap();
                    // pipe_time propagates without incrementing
                    // (pipeline_register nodes already carry correct stage time)
                    input_times.push(src_time);
                }

                if has_all_inputs && !input_times.is_empty() {
                    let base_time = *input_times.iter().max().unwrap();
                    self.nodes.get_mut(id).unwrap().pipe_time = Some(base_time);
                    changed = true;
                } else if has_all_inputs && input_times.is_empty() {
                    self.nodes.get_mut(id).unwrap().pipe_time = Some(0);
                    changed = true;
                }
            }

            if !changed {
                break;
            }
        }

        // Fallback
        let ids: Vec<String> = self.nodes.keys().cloned().collect();
        for id in ids {
            if self.nodes[&id].pipe_time.is_none() {
                self.nodes.get_mut(&id).unwrap().pipe_time = Some(0);
            }
        }
    }

    /// Get all nodes that are at a specific `pipe_time` (pipeline stage).
    pub fn get_nodes_at_pipe_time(&self, time: i64) -> Vec<&Node> {
        self.nodes
            .values()
            .filter(|n| n.pipe_time == Some(time))
            .collect()
    }

    /// Get the maximum `pipe_time` in the graph (number of pipeline stages - 1).
    pub fn get_max_pipe_time(&self) -> i64 {
        self.nodes
            .values()
            .filter_map(|n| n.pipe_time)
            .max()
            .unwrap_or(0)
    }

    /// Infer `dual_issue_time` for all nodes in a dual-issue pipeline.
    ///
    /// `dual_issue_time = pipe_time * 2 + pipe_id`
    ///
    /// Shared nodes (pipe_id = None) get `dual_issue_time = None`.
    pub fn infer_dual_issue_time(&mut self, force_reinfer: bool) {
        let mut nodes_updated: usize = 0;

        let ids: Vec<String> = self.nodes.keys().cloned().collect();
        for id in ids {
            let node = self.nodes.get(&id).unwrap();
            if !force_reinfer && node.dual_issue_time.is_some() {
                continue;
            }
            let pipe_id = node.pipe_id;
            let pipe_time = node.pipe_time;
            let node_mut = self.nodes.get_mut(&id).unwrap();
            if let (Some(pid), Some(pt)) = (pipe_id, pipe_time) {
                node_mut.dual_issue_time = Some(pt * 2 + pid);
                nodes_updated += 1;
            } else {
                node_mut.dual_issue_time = None;
            }
        }

        if nodes_updated > 0 {
            log::info!("  Inferred dual_issue_time for {} nodes", nodes_updated);
        }
    }

    /// Get all nodes at a specific `dual_issue_time`.
    pub fn get_nodes_at_dual_issue_time(&self, time: i64) -> Vec<&Node> {
        self.nodes
            .values()
            .filter(|n| n.dual_issue_time == Some(time))
            .collect()
    }

    /// Get the maximum `dual_issue_time` in the graph.
    pub fn get_max_dual_issue_time(&self) -> i64 {
        self.nodes
            .values()
            .filter_map(|n| n.dual_issue_time)
            .max()
            .unwrap_or(0)
    }

    // ------------------------------------------------------------------
    // classify_architectural_state
    // ------------------------------------------------------------------

    /// Heuristic-based classification of architectural state nodes.
    ///
    /// Nodes that are already explicitly marked `is_arch_state = true` are
    /// left as-is. Otherwise the method examines usage patterns (multi-
    /// dimensional arrays, self-referential writes, write counts, etc.) to
    /// decide whether a node should be architectural state.
    pub fn classify_architectural_state(&mut self) {
        let node_ids: Vec<String> = self.nodes.keys().cloned().collect();

        for id in &node_ids {
            let node = &self.nodes[id];
            let ntype = node
                .data
                .get("type")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if !ntype.starts_with("isa_state") {
                continue;
            }
            if node.is_arch_state {
                continue;
            }

            // Multi-dimensional arrays (memory)
            let is_memory = node
                .data
                .get("is_memory")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            if is_memory {
                self.nodes.get_mut(id).unwrap().is_arch_state = true;
                continue;
            }

            // Analyse usage patterns via edges
            let mut is_written_to = false;
            let mut is_read_from = false;
            let mut write_count: usize = 0;
            let mut has_self_referential_write = false;

            let incoming: Vec<String> = node.incoming_edges.iter().cloned().collect();
            for eid in &incoming {
                let edge = match self.edges.get(eid) {
                    Some(e) => e,
                    None => continue,
                };
                let etype = edge
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                if etype == "assignment" {
                    is_written_to = true;
                    write_count += 1;
                    let source_id = edge.source.clone();
                    if self.node_depends_on(&source_id, id, &mut HashSet::new()) {
                        has_self_referential_write = true;
                    }
                }
            }

            let outgoing: Vec<String> = node.outgoing_edges.iter().cloned().collect();
            for eid in &outgoing {
                let edge = match self.edges.get(eid) {
                    Some(e) => e,
                    None => continue,
                };
                let etype = edge
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                if etype == "operand" || etype == "bit_access" || etype == "array_index" {
                    is_read_from = true;
                }
            }

            // Heuristics
            let classify = if write_count > 1 {
                true
            } else if has_self_referential_write {
                true
            } else if is_written_to && is_read_from {
                false
            } else if is_written_to && !is_read_from {
                true
            } else if !is_written_to && is_read_from {
                true
            } else {
                // Default: leave as-is
                continue;
            };

            self.nodes.get_mut(id).unwrap().is_arch_state = classify;
        }
    }

    /// Check if `expr_node_id`'s computation depends on `target_node_id`.
    fn node_depends_on(
        &self,
        expr_node_id: &str,
        target_node_id: &str,
        visited: &mut HashSet<String>,
    ) -> bool {
        if visited.contains(expr_node_id) {
            return false;
        }
        visited.insert(expr_node_id.to_string());

        if expr_node_id == target_node_id {
            return true;
        }

        let incoming: Vec<String> = match self.nodes.get(expr_node_id) {
            Some(n) => n.incoming_edges.iter().cloned().collect(),
            None => return false,
        };

        for eid in &incoming {
            if let Some(edge) = self.edges.get(eid) {
                if self.node_depends_on(&edge.source, target_node_id, visited) {
                    return true;
                }
            }
        }

        false
    }

    // ------------------------------------------------------------------
    // cleanup_disconnected_nodes
    // ------------------------------------------------------------------

    /// Remove nodes that have become disconnected (no incoming or outgoing
    /// edges). Preserves architectural state, uarch state, and various
    /// structural node types.
    pub fn cleanup_disconnected_nodes(&mut self) {
        let mut to_remove: Vec<String> = Vec::new();

        for node in self.nodes.values() {
            if node.is_arch_state || node.is_uarch_state {
                continue;
            }
            let ntype = node
                .data
                .get("type")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if matches!(
                ntype,
                "uarch_counter"
                    | "hazard_detection_unit"
                    | "stall_controller"
                    | "pipeline_register"
                    | "completion_signal"
            ) {
                continue;
            }
            if node.incoming_edges.is_empty() && node.outgoing_edges.is_empty() {
                if ntype == "literal" || ntype == "isa_state" {
                    continue;
                }
                if matches!(
                    ntype,
                    "temp_var" | "operation" | "bit_slice" | "array_access"
                ) {
                    to_remove.push(node.id.clone());
                }
            }
        }

        for id in &to_remove {
            log::info!("Removing disconnected node: {}", id);
            self.nodes.remove(id);
        }
    }

    // ------------------------------------------------------------------
    // copy (deep clone)
    // ------------------------------------------------------------------

    /// Create a deep copy of this `ResourceGraph`.
    pub fn copy(&self) -> ResourceGraph {
        let mut new_graph = ResourceGraph::new();
        new_graph.aspect_declarations = self.aspect_declarations.clone();
        new_graph.assume_expressions = self.assume_expressions.clone();
        new_graph.gated_states = self.gated_states.clone();

        // Copy all nodes (without edge sets – edges will be re-added)
        for node in self.nodes.values() {
            let new_node = Node::new(
                Some(node.id.clone()),
                Some(node.data.clone()),
                node.is_arch_state,
                node.used_as_index,
                node.indexed_by.clone(),
                node.is_uarch_state,
                node.uarch_time,
                node.pipe_time,
                node.from_isa_spec,
                node.already_split,
                node.latency,
                node.variable_latency,
                node.is_shared,
                node.pipe_id,
                node.dual_issue_time,
            );
            new_graph.nodes.insert(new_node.id.clone(), new_node);
        }

        // Copy all edges (this also populates node edge sets)
        for edge in self.edges.values() {
            let new_edge = Edge::new(
                edge.source.clone(),
                edge.target.clone(),
                Some(edge.id.clone()),
                Some(edge.data.clone()),
            );
            new_graph.add_edge(new_edge);
        }

        new_graph
    }

    // ------------------------------------------------------------------
    // set_memory_width
    // ------------------------------------------------------------------

    /// Set the width of a memory and propagate to its access nodes.
    pub fn set_memory_width(&mut self, mem_name: &str, width: i64) -> Result<(), String> {
        // Find the memory node
        let mem_node_id = {
            let mut found: Option<String> = None;
            for node in self.nodes.values() {
                let ntype = node
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let name = node
                    .data
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                if ntype == "isa_state mem" && name == mem_name {
                    found = Some(node.id.clone());
                    break;
                }
            }
            found.ok_or_else(|| format!("Memory '{}' not found in graph", mem_name))?
        };

        let old_width = self.nodes[&mem_node_id]
            .data
            .get("bit_width")
            .cloned();

        // Store original access widths (first time only)
        let has_access_widths = self.nodes[&mem_node_id]
            .data
            .contains_key("access_widths");

        if !has_access_widths {
            let mut access_widths: Vec<Value> = Vec::new();
            let pattern = format!("{}[", mem_name);
            for node in self.nodes.values() {
                if node.id.contains(&pattern) && (node.id.contains("_rd") || node.id.contains("_wr"))
                {
                    let is_narrow = node
                        .data
                        .get("is_narrow_access")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false);
                    let is_split = node
                        .data
                        .get("is_split_port")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false);
                    if !is_narrow && !is_split {
                        let orig_width = node
                            .data
                            .get("bit_width")
                            .cloned()
                            .unwrap_or_else(|| old_width.clone().unwrap_or(Value::Null));
                        access_widths.push(orig_width);
                    }
                }
            }
            if !access_widths.is_empty() {
                self.nodes
                    .get_mut(&mem_node_id)
                    .unwrap()
                    .data
                    .insert("access_widths".to_string(), Value::Array(access_widths));
            }
        }

        // Update the memory width
        self.nodes
            .get_mut(&mem_node_id)
            .unwrap()
            .data
            .insert("bit_width".to_string(), Value::Number(width.into()));

        // Propagate width to all access nodes
        let pattern = format!("{}[", mem_name);
        let access_ids: Vec<String> = self
            .nodes
            .keys()
            .filter(|id| {
                id.contains(&pattern) && (id.contains("_rd") || id.contains("_wr"))
            })
            .cloned()
            .collect();

        for id in &access_ids {
            let is_narrow = self.nodes[id]
                .data
                .get("is_narrow_access")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            if !is_narrow {
                self.nodes
                    .get_mut(id)
                    .unwrap()
                    .data
                    .insert("bit_width".to_string(), Value::Number(width.into()));
            }
        }

        Ok(())
    }

    // ------------------------------------------------------------------
    // create_uarch_state_node helper
    // ------------------------------------------------------------------

    /// Create a new `uarch_state` node and add it to the graph.
    pub fn create_uarch_state_node(
        &mut self,
        node_id: &str,
        data: Option<HashMap<String, Value>>,
        bit_width: i64,
    ) -> String {
        let node_data = data.unwrap_or_else(|| {
            let mut d = HashMap::new();
            d.insert("type".to_string(), Value::String("uarch_state".to_string()));
            d.insert("name".to_string(), Value::String(node_id.to_string()));
            d.insert(
                "display_name".to_string(),
                Value::String(node_id.to_string()),
            );
            d.insert("bit_width".to_string(), Value::Number(bit_width.into()));
            d
        });

        let node = Node::new(
            Some(node_id.to_string()),
            Some(node_data),
            false, // is_arch_state
            false, // used_as_index
            None,  // indexed_by
            true,  // is_uarch_state
            None,  // uarch_time
            None,  // pipe_time
            false, // from_isa_spec
            false, // already_split
            0,     // latency
            false, // variable_latency
            false, // is_shared
            None,  // pipe_id
            None,  // dual_issue_time
        );
        let id = node.id.clone();
        self.add_node(node);
        id
    }

    // ------------------------------------------------------------------
    // get_neighbors
    // ------------------------------------------------------------------

    /// Get all neighboring node IDs of a given node (connected via incoming or
    /// outgoing edges).
    pub fn get_neighbors(&self, node_id: &str) -> HashSet<String> {
        let mut neighbors = HashSet::new();
        if let Some(node) = self.nodes.get(node_id) {
            for eid in &node.incoming_edges {
                if let Some(e) = self.edges.get(eid) {
                    neighbors.insert(e.source.clone());
                }
            }
            for eid in &node.outgoing_edges {
                if let Some(e) = self.edges.get(eid) {
                    neighbors.insert(e.target.clone());
                }
            }
        }
        neighbors
    }

    // ------------------------------------------------------------------
    // JSON serialization / deserialization
    // ------------------------------------------------------------------

    /// Serialize the graph to a JSON-compatible `serde_json::Value`.
    pub fn to_json(&self) -> Value {
        let mut nodes_data: Vec<Value> = Vec::new();
        for node in self.nodes.values() {
            let node_val = serde_json::json!({
                "id": node.id,
                "data": node.data,
                "is_arch_state": node.is_arch_state,
                "is_shared": node.is_shared,
                "is_uarch_state": node.is_uarch_state,
                "used_as_index": node.used_as_index,
                "indexed_by": node.indexed_by,
                "uarch_time": node.uarch_time,
                "pipe_time": node.pipe_time,
                "latency": node.latency,
                "variable_latency": node.variable_latency,
            });
            nodes_data.push(node_val);
        }

        let mut edges_data: Vec<Value> = Vec::new();
        for edge in self.edges.values() {
            let edge_val = serde_json::json!({
                "id": edge.id,
                "source": edge.source,
                "target": edge.target,
                "data": edge.data,
            });
            edges_data.push(edge_val);
        }

        serde_json::json!({
            "nodes": nodes_data,
            "edges": edges_data,
        })
    }

    /// Deserialize a graph from a JSON-compatible `serde_json::Value`
    /// (matching the Python JSON format).
    pub fn from_json(data: &Value) -> Result<ResourceGraph, String> {
        let mut graph = ResourceGraph::new();

        let nodes_arr = data
            .get("nodes")
            .and_then(|v| v.as_array())
            .ok_or("Missing or invalid 'nodes' array")?;

        // First pass: create all nodes
        for nd in nodes_arr {
            let id = nd
                .get("id")
                .and_then(|v| v.as_str())
                .ok_or("Node missing 'id'")?
                .to_string();

            let node_data: HashMap<String, Value> = nd
                .get("data")
                .and_then(|v| serde_json::from_value(v.clone()).ok())
                .unwrap_or_default();

            let is_arch_state = nd
                .get("is_arch_state")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            let is_shared = nd
                .get("is_shared")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            let is_uarch_state = nd
                .get("is_uarch_state")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            let used_as_index = nd
                .get("used_as_index")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            let uarch_time = nd.get("uarch_time").and_then(|v| v.as_i64());
            let pipe_time = nd.get("pipe_time").and_then(|v| v.as_i64());
            let latency = nd
                .get("latency")
                .and_then(|v| v.as_i64())
                .unwrap_or(1); // Default 1 for backward compat
            let variable_latency = nd
                .get("variable_latency")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);

            let node = Node::new(
                Some(id),
                Some(node_data),
                is_arch_state,
                used_as_index,
                None, // indexed_by set in second pass
                is_uarch_state,
                uarch_time,
                pipe_time,
                false, // from_isa_spec
                false, // already_split
                latency,
                variable_latency,
                is_shared,
                None, // pipe_id
                None, // dual_issue_time
            );
            graph.nodes.insert(node.id.clone(), node);
        }

        // Second pass: set indexed_by references
        for nd in nodes_arr {
            let id = nd.get("id").and_then(|v| v.as_str()).unwrap();
            let indexed_by = nd
                .get("indexed_by")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            if let Some(ref ib) = indexed_by {
                if graph.nodes.contains_key(ib) {
                    graph.nodes.get_mut(id).unwrap().indexed_by = Some(ib.clone());
                }
            }
        }

        // Third pass: create all edges
        let edges_arr = data
            .get("edges")
            .and_then(|v| v.as_array())
            .ok_or("Missing or invalid 'edges' array")?;

        for ed in edges_arr {
            let eid = ed
                .get("id")
                .and_then(|v| v.as_str())
                .ok_or("Edge missing 'id'")?
                .to_string();
            let source = ed
                .get("source")
                .and_then(|v| v.as_str())
                .ok_or("Edge missing 'source'")?
                .to_string();
            let target = ed
                .get("target")
                .and_then(|v| v.as_str())
                .ok_or("Edge missing 'target'")?
                .to_string();
            let edge_data: HashMap<String, Value> = ed
                .get("data")
                .and_then(|v| serde_json::from_value(v.clone()).ok())
                .unwrap_or_default();

            let edge = Edge::new(source, target, Some(eid), Some(edge_data));
            graph.add_edge(edge);
        }

        Ok(graph)
    }

    /// Save the graph to a JSON file.
    pub fn save_to_file(&self, filename: &str) -> io::Result<()> {
        let json = self.to_json();
        let text = serde_json::to_string_pretty(&json)
            .map_err(|e| io::Error::new(io::ErrorKind::Other, e))?;
        fs::write(filename, text)
    }

    /// Load a graph from a JSON file.
    pub fn load_from_file(filename: &str) -> Result<ResourceGraph, String> {
        let text = fs::read_to_string(filename)
            .map_err(|e| format!("Failed to read file '{}': {}", filename, e))?;
        let data: Value = serde_json::from_str(&text)
            .map_err(|e| format!("Failed to parse JSON from '{}': {}", filename, e))?;
        ResourceGraph::from_json(&data)
    }
}

impl fmt::Display for ResourceGraph {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "ResourceGraph(nodes={}, edges={})",
            self.nodes.len(),
            self.edges.len()
        )
    }
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

fn opt_display<T: fmt::Display>(opt: Option<T>) -> String {
    match opt {
        Some(v) => v.to_string(),
        None => "None".to_string(),
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_node(id: &str) -> Node {
        Node::with_defaults(Some(id.to_string()))
    }

    fn make_edge(src: &str, tgt: &str) -> Edge {
        Edge::new(src.to_string(), tgt.to_string(), None, None)
    }

    #[test]
    fn test_add_and_get_node() {
        let mut g = ResourceGraph::new();
        g.add_node(make_node("a"));
        assert_eq!(g.get_node_count(), 1);
        assert!(g.get_node("a").is_some());
    }

    #[test]
    fn test_add_node_replaces_and_transfers_edges() {
        let mut g = ResourceGraph::new();
        g.add_node(make_node("a"));
        g.add_node(make_node("b"));
        g.add_edge(make_edge("a", "b"));

        // Replace "b" with a new node that has different data
        let mut new_b = make_node("b");
        new_b.is_arch_state = true;
        g.add_node(new_b);

        assert_eq!(g.get_node_count(), 2);
        let b = g.get_node("b").unwrap();
        assert!(b.is_arch_state);
        assert!(!b.incoming_edges.is_empty());
    }

    #[test]
    fn test_add_and_remove_edge() {
        let mut g = ResourceGraph::new();
        g.add_node(make_node("a"));
        g.add_node(make_node("b"));
        let e = Edge::new(
            "a".to_string(),
            "b".to_string(),
            Some("e1".to_string()),
            None,
        );
        g.add_edge(e);
        assert_eq!(g.get_edge_count(), 1);

        g.remove_edge("e1");
        assert_eq!(g.get_edge_count(), 0);
        assert!(g.get_node("a").unwrap().outgoing_edges.is_empty());
        assert!(g.get_node("b").unwrap().incoming_edges.is_empty());
    }

    #[test]
    fn test_remove_node_removes_edges() {
        let mut g = ResourceGraph::new();
        g.add_node(make_node("a"));
        g.add_node(make_node("b"));
        g.add_node(make_node("c"));
        g.add_edge(make_edge("a", "b"));
        g.add_edge(make_edge("b", "c"));
        assert_eq!(g.get_edge_count(), 2);

        g.remove_node("b");
        assert_eq!(g.get_node_count(), 2);
        assert_eq!(g.get_edge_count(), 0);
    }

    #[test]
    fn test_insert_node_on_edge() {
        let mut g = ResourceGraph::new();
        g.add_node(make_node("a"));
        g.add_node(make_node("c"));
        let e = Edge::new(
            "a".to_string(),
            "c".to_string(),
            Some("e_ac".to_string()),
            None,
        );
        g.add_edge(e);

        let (e1, e2) = g.insert_node_on_edge("e_ac", make_node("b")).unwrap();
        assert_eq!(g.get_node_count(), 3);
        assert_eq!(g.get_edge_count(), 2);
        assert!(g.get_edge("e_ac").is_none());

        let edge1 = g.get_edge(&e1).unwrap();
        assert_eq!(edge1.source, "a");
        assert_eq!(edge1.target, "b");

        let edge2 = g.get_edge(&e2).unwrap();
        assert_eq!(edge2.source, "b");
        assert_eq!(edge2.target, "c");
    }

    #[test]
    fn test_filter_nodes() {
        let mut g = ResourceGraph::new();
        let mut n1 = make_node("a");
        n1.is_arch_state = true;
        g.add_node(n1);
        g.add_node(make_node("b"));

        let arch = g.filter_nodes(|n| n.is_arch_state);
        assert_eq!(arch.len(), 1);
        assert_eq!(arch[0].id, "a");
    }

    #[test]
    fn test_filter_subgraph() {
        let mut g = ResourceGraph::new();
        let mut n1 = make_node("a");
        n1.is_arch_state = true;
        let mut n2 = make_node("b");
        n2.is_arch_state = true;
        g.add_node(n1);
        g.add_node(n2);
        g.add_node(make_node("c"));
        g.add_edge(make_edge("a", "b"));
        g.add_edge(make_edge("b", "c"));

        let sub = g.filter_subgraph(|n| n.is_arch_state, |_| true);
        assert_eq!(sub.get_node_count(), 2);
        assert_eq!(sub.get_edge_count(), 1);
    }

    #[test]
    fn test_to_json_and_from_json() {
        let mut g = ResourceGraph::new();
        let mut n1 = make_node("a");
        n1.is_arch_state = true;
        n1.data
            .insert("type".to_string(), Value::String("isa_state".to_string()));
        g.add_node(n1);
        g.add_node(make_node("b"));
        g.add_edge(Edge::new(
            "a".to_string(),
            "b".to_string(),
            Some("e1".to_string()),
            None,
        ));

        let json = g.to_json();
        let g2 = ResourceGraph::from_json(&json).unwrap();
        assert_eq!(g2.get_node_count(), 2);
        assert_eq!(g2.get_edge_count(), 1);
        assert!(g2.get_node("a").unwrap().is_arch_state);
    }

    #[test]
    fn test_copy() {
        let mut g = ResourceGraph::new();
        g.add_node(make_node("a"));
        g.add_node(make_node("b"));
        g.add_edge(make_edge("a", "b"));

        let g2 = g.copy();
        assert_eq!(g2.get_node_count(), 2);
        assert_eq!(g2.get_edge_count(), 1);
    }

    #[test]
    fn test_display() {
        let g = ResourceGraph::new();
        let s = format!("{}", g);
        assert!(s.contains("ResourceGraph"));
    }

    #[test]
    fn test_infer_uarch_time_simple() {
        let mut g = ResourceGraph::new();
        let mut n_a = make_node("reg_rd");
        n_a.is_arch_state = true;
        n_a.data
            .insert("type".to_string(), Value::String("isa_state".to_string()));
        g.add_node(n_a);

        let mut n_b = make_node("pipe_reg");
        n_b.is_uarch_state = true;
        g.add_node(n_b);

        g.add_node(make_node("compute"));

        g.add_edge(make_edge("reg_rd", "pipe_reg"));
        g.add_edge(make_edge("pipe_reg", "compute"));

        g.infer_uarch_time(true);

        assert_eq!(g.get_node("reg_rd").unwrap().uarch_time, Some(0));
        assert_eq!(g.get_node("pipe_reg").unwrap().uarch_time, Some(0));
        assert_eq!(g.get_node("compute").unwrap().uarch_time, Some(1));
    }

    #[test]
    fn test_infer_pipe_time_simple() {
        let mut g = ResourceGraph::new();
        let mut n_a = make_node("reg_rd");
        n_a.is_arch_state = true;
        n_a.data
            .insert("type".to_string(), Value::String("isa_state".to_string()));
        g.add_node(n_a);

        let mut n_b = make_node("pipe_reg");
        n_b.is_uarch_state = true;
        n_b.data.insert(
            "type".to_string(),
            Value::String("pipeline_register".to_string()),
        );
        n_b.pipe_time = Some(1);
        g.add_node(n_b);

        g.add_node(make_node("compute"));

        g.add_edge(make_edge("reg_rd", "pipe_reg"));
        g.add_edge(make_edge("pipe_reg", "compute"));

        g.infer_pipe_time(true);

        assert_eq!(g.get_node("reg_rd").unwrap().pipe_time, Some(0));
        assert_eq!(g.get_node("pipe_reg").unwrap().pipe_time, Some(1));
        assert_eq!(g.get_node("compute").unwrap().pipe_time, Some(1));
    }

    #[test]
    fn test_infer_dual_issue_time() {
        let mut g = ResourceGraph::new();
        let mut n = make_node("n1");
        n.pipe_time = Some(2);
        n.pipe_id = Some(1);
        g.add_node(n);

        g.infer_dual_issue_time(true);
        assert_eq!(g.get_node("n1").unwrap().dual_issue_time, Some(5)); // 2*2+1
    }

    #[test]
    fn test_neighbors() {
        let mut g = ResourceGraph::new();
        g.add_node(make_node("a"));
        g.add_node(make_node("b"));
        g.add_node(make_node("c"));
        g.add_edge(make_edge("a", "b"));
        g.add_edge(make_edge("c", "b"));

        let neighbors = g.get_neighbors("b");
        assert!(neighbors.contains("a"));
        assert!(neighbors.contains("c"));
        assert_eq!(neighbors.len(), 2);
    }
}
