//! Register renaming optimization for ResourceGraph.
//!
//! This module implements register renaming, a classic microarchitectural optimization
//! that eliminates false dependencies (WAW and WAR hazards) by mapping architectural
//! registers to a larger pool of physical registers.
//!
//! Key concepts:
//! - Renamer node: Maps architectural indices to microarchitectural indices
//!   - Allocations: Assigns new physical register for writes
//!   - Lookups: Returns current physical register for reads
//! - Denamer node: Maps microarchitectural indices back to architectural indices
//!   before writing to ISA state
//! - Dependency analysis uses microarchitectural indices within renamed domain
//!
//! Usage:
//! ```ignore
//! let spec = RegisterRenamingSpec::new("rf", 64, Some(vec!["rs", "rt", "rd"]), true, false);
//! let mut optimizer = RegisterRenamingOptimization::new(&mut graph);
//! optimizer.apply(&spec);
//! ```

use std::collections::{HashMap, HashSet};

use log::info;
use serde_json::{json, Value};

use crate::resource_graph::{Edge, Node, ResourceGraph};

// ---------------------------------------------------------------------------
// RegisterRenamingSpec
// ---------------------------------------------------------------------------

/// Specification for register renaming on a resource.
#[derive(Debug, Clone)]
pub struct RegisterRenamingSpec {
    /// Resource to rename (e.g., "rf" for register file).
    pub resource_name: String,
    /// Number of physical registers (must be >= 1).
    pub num_physical_regs: u32,
    /// Specific indices to rename (None = all).
    pub target_indices: Option<Vec<String>>,
    /// Add verification logic.
    pub enable_verification: bool,
    /// If true, create separate physical register file (PRF).
    /// If false, just rename indices (default behavior).
    pub separate_regfiles: bool,
}

impl RegisterRenamingSpec {
    /// Create a new RegisterRenamingSpec with validation.
    pub fn new(
        resource_name: &str,
        num_physical_regs: u32,
        target_indices: Option<Vec<String>>,
        enable_verification: bool,
        separate_regfiles: bool,
    ) -> Result<Self, String> {
        if num_physical_regs < 1 {
            return Err(format!(
                "num_physical_regs must be >= 1, got {}",
                num_physical_regs
            ));
        }
        Ok(Self {
            resource_name: resource_name.to_string(),
            num_physical_regs,
            target_indices,
            enable_verification,
            separate_regfiles,
        })
    }
}

// ---------------------------------------------------------------------------
// IndexMapping
// ---------------------------------------------------------------------------

/// Tracks an index that needs renaming.
#[derive(Debug, Clone)]
struct IndexMapping {
    /// Original index name (e.g., "rs", "rd").
    index_name: String,
    /// Node ID that provides the architectural index.
    index_node_id: String,
    /// "READ" or "WRITE".
    access_type: String,
    /// The array access node ID (e.g., rf[rs]).
    array_access_node_id: String,
    /// Timing of this access.
    uarch_time: i64,
}

// ---------------------------------------------------------------------------
// ArrayAccessInfo (local helper)
// ---------------------------------------------------------------------------

/// Information about an array access in the graph.
#[derive(Debug, Clone)]
struct ArrayAccessInfo {
    /// Node ID of the array access.
    node_id: String,
    /// Base resource name (e.g., "rf").
    base_resource: String,
    /// Index name.
    index: String,
    /// Node ID of the index node.
    index_node_id: Option<String>,
    /// "READ" or "WRITE".
    access_type: String,
    /// Timing.
    uarch_time: i64,
}

// ---------------------------------------------------------------------------
// Analysis results
// ---------------------------------------------------------------------------

/// Results from Phase 1 analysis.
#[derive(Debug, Clone)]
struct RenameAnalysisResult {
    read_indices: Vec<IndexMapping>,
    write_indices: Vec<IndexMapping>,
    all_index_node_ids: HashSet<String>,
}

// ---------------------------------------------------------------------------
// Plan results
// ---------------------------------------------------------------------------

/// Results from Phase 2 planning.
#[derive(Debug, Clone)]
struct RenamePlanResult {
    renamer_id: String,
    denamer_id: String,
    rename_table_id: String,
    free_list_id: String,
}

// ---------------------------------------------------------------------------
// Structure results
// ---------------------------------------------------------------------------

/// Results from Phase 3 structure creation.
#[derive(Debug, Clone)]
struct RenameStructureResult {
    renamer_node_id: String,
    denamer_node_id: String,
    rename_table_node_id: String,
    free_list_node_id: String,
    /// Mapping from architectural index node ID to microarchitectural index node ID.
    renamed_index_nodes: HashMap<String, String>,
    /// Physical register file node ID (if separate_regfiles=true).
    physical_regfile_node_id: Option<String>,
}

// ---------------------------------------------------------------------------
// RegisterRenamingOptimization
// ---------------------------------------------------------------------------

/// Main optimization class that orchestrates register renaming.
///
/// Follows the 7-phase pattern:
/// 1. ANALYSIS - Identify renaming opportunities
/// 2. PLANNING - Create renaming specifications
/// 3. STRUCTURE - Build renaming component skeleton
/// 4. HARDWARE - Generate hardware components
/// 5. CONNECTION - Wire everything together
/// 6. CLEANUP - Remove superseded elements
/// 7. TIMING - Update timing information
pub struct RegisterRenamingOptimization<'a> {
    graph: &'a mut ResourceGraph,
}

impl<'a> RegisterRenamingOptimization<'a> {
    /// Create a new RegisterRenamingOptimization.
    pub fn new(graph: &'a mut ResourceGraph) -> Self {
        Self { graph }
    }

    /// Apply register renaming optimization to the graph.
    ///
    /// Returns `true` if optimization was applied successfully.
    pub fn apply(&mut self, spec: &RegisterRenamingSpec) -> bool {
        info!(
            "======================================================================",
        );
        info!(
            "REGISTER RENAMING OPTIMIZATION: {}",
            spec.resource_name
        );
        info!(
            "======================================================================",
        );

        // Phase 1: Analysis
        let analysis = match self.phase1_analysis(spec) {
            Some(a) => a,
            None => {
                info!("Register renaming not applicable - skipping");
                return false;
            }
        };

        // Phase 2: Planning
        let plan = self.phase2_planning(spec);

        // Phase 3: Structure
        let structure = self.phase3_structure(spec, &analysis, &plan);

        // Phase 4: Hardware (currently just metadata)
        self.phase4_hardware();

        // Phase 5: Connection
        self.phase5_connection(spec, &analysis, &structure);

        // Phase 5.5: Expand register file (index renaming mode)
        if !spec.separate_regfiles {
            self.expand_register_file(spec);
        }

        // Phase 6: Cleanup
        self.phase6_cleanup();

        // Phase 7: Timing
        self.phase7_timing();

        info!(
            "======================================================================",
        );
        info!("REGISTER RENAMING COMPLETE");
        info!(
            "======================================================================",
        );

        true
    }

    // -----------------------------------------------------------------------
    // Phase 1: Analysis
    // -----------------------------------------------------------------------

    fn phase1_analysis(&self, spec: &RegisterRenamingSpec) -> Option<RenameAnalysisResult> {
        info!(
            "[PHASE 1: ANALYSIS] Analyzing register renaming opportunities for '{}'",
            spec.resource_name
        );

        // Get reads and writes for the target resource
        let reads = self.get_read_accesses(&spec.resource_name);
        let write_port_writes = self.find_write_port_accesses(&spec.resource_name);
        let direct_writes = self.get_write_accesses(&spec.resource_name);

        let mut all_writes = direct_writes;
        all_writes.extend(write_port_writes.iter().cloned());

        if reads.is_empty() && all_writes.is_empty() {
            info!("  No accesses found to resource '{}'", spec.resource_name);
            return None;
        }

        info!(
            "  Found {} read(s) and {} write(s) ({} via write ports)",
            reads.len(),
            all_writes.len(),
            write_port_writes.len()
        );

        let mut read_indices = Vec::new();
        let mut write_indices = Vec::new();
        let mut all_index_node_ids = HashSet::new();

        // Process reads (lookups)
        for read_access in &reads {
            if self.should_rename_index(spec, read_access) {
                if let Some(ref idx_id) = read_access.index_node_id {
                    all_index_node_ids.insert(idx_id.clone());
                    read_indices.push(IndexMapping {
                        index_name: read_access.index.clone(),
                        index_node_id: idx_id.clone(),
                        access_type: "READ".to_string(),
                        array_access_node_id: read_access.node_id.clone(),
                        uarch_time: read_access.uarch_time,
                    });
                }
            }
        }

        // Process writes (allocations)
        for write_access in &all_writes {
            if self.should_rename_index(spec, write_access) {
                if let Some(ref idx_id) = write_access.index_node_id {
                    all_index_node_ids.insert(idx_id.clone());
                    write_indices.push(IndexMapping {
                        index_name: write_access.index.clone(),
                        index_node_id: idx_id.clone(),
                        access_type: "WRITE".to_string(),
                        array_access_node_id: write_access.node_id.clone(),
                        uarch_time: write_access.uarch_time,
                    });
                }
            }
        }

        info!(
            "  Selected {} read index/indices for renaming",
            read_indices.len()
        );
        info!(
            "  Selected {} write index/indices for renaming",
            write_indices.len()
        );

        if read_indices.is_empty() && write_indices.is_empty() {
            info!("  No indices selected for renaming (check target_indices filter)");
            return None;
        }

        Some(RenameAnalysisResult {
            read_indices,
            write_indices,
            all_index_node_ids,
        })
    }

    /// Get read accesses for the target resource (array_access nodes).
    fn get_read_accesses(&self, resource_name: &str) -> Vec<ArrayAccessInfo> {
        let mut result = Vec::new();

        for node in self.graph.nodes.values() {
            if node.data.get("type").and_then(|v| v.as_str()) != Some("array_access") {
                continue;
            }

            let base = node
                .data
                .get("base_resource")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if base != resource_name {
                continue;
            }

            // A read access has outgoing assignment edges (data flows out)
            let has_outgoing_assignment = node.outgoing_edges.iter().any(|eid| {
                self.graph
                    .edges
                    .get(eid)
                    .map(|e| e.data.get("type").and_then(|v| v.as_str()) == Some("assignment"))
                    .unwrap_or(false)
            });

            if !has_outgoing_assignment {
                continue;
            }

            // Find the index node (connected via array_index edge)
            let mut index_node_id = None;
            let mut index_name = String::new();
            for eid in &node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(eid) {
                    if edge.data.get("type").and_then(|v| v.as_str()) == Some("array_index") {
                        index_node_id = Some(edge.source.clone());
                        if let Some(src_node) = self.graph.nodes.get(&edge.source) {
                            index_name = src_node
                                .data
                                .get("name")
                                .and_then(|v| v.as_str())
                                .unwrap_or(&src_node.id)
                                .to_string();
                        }
                        break;
                    }
                }
            }

            let uarch_time = node.uarch_time.unwrap_or(0);

            result.push(ArrayAccessInfo {
                node_id: node.id.clone(),
                base_resource: resource_name.to_string(),
                index: index_name,
                index_node_id,
                access_type: "READ".to_string(),
                uarch_time,
            });
        }

        result
    }

    /// Get write accesses for the target resource (array_access nodes that receive data).
    fn get_write_accesses(&self, resource_name: &str) -> Vec<ArrayAccessInfo> {
        let mut result = Vec::new();

        for node in self.graph.nodes.values() {
            if node.data.get("type").and_then(|v| v.as_str()) != Some("array_access") {
                continue;
            }

            let base = node
                .data
                .get("base_resource")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if base != resource_name {
                continue;
            }

            // A write access has incoming assignment edges (data flows in)
            let has_incoming_assignment = node.incoming_edges.iter().any(|eid| {
                self.graph
                    .edges
                    .get(eid)
                    .map(|e| e.data.get("type").and_then(|v| v.as_str()) == Some("assignment"))
                    .unwrap_or(false)
            });

            if !has_incoming_assignment {
                continue;
            }

            // Find the index node
            let mut index_node_id = None;
            let mut index_name = String::new();
            for eid in &node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(eid) {
                    if edge.data.get("type").and_then(|v| v.as_str()) == Some("array_index") {
                        index_node_id = Some(edge.source.clone());
                        if let Some(src_node) = self.graph.nodes.get(&edge.source) {
                            index_name = src_node
                                .data
                                .get("name")
                                .and_then(|v| v.as_str())
                                .unwrap_or(&src_node.id)
                                .to_string();
                        }
                        break;
                    }
                }
            }

            let uarch_time = node.uarch_time.unwrap_or(0);

            result.push(ArrayAccessInfo {
                node_id: node.id.clone(),
                base_resource: resource_name.to_string(),
                index: index_name,
                index_node_id,
                access_type: "WRITE".to_string(),
                uarch_time,
            });
        }

        result
    }

    /// Find write accesses through memory_write_port nodes (created by graph merger).
    fn find_write_port_accesses(&self, resource_name: &str) -> Vec<ArrayAccessInfo> {
        let mut result = Vec::new();

        for node in self.graph.nodes.values() {
            if node.data.get("type").and_then(|v| v.as_str()) != Some("memory_write_port") {
                continue;
            }

            let base_memory = node
                .data
                .get("base_memory")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if base_memory != resource_name {
                continue;
            }

            // Find the write address index node
            let mut index_node_id = None;
            let mut index_name = String::new();
            for eid in &node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(eid) {
                    if edge.data.get("type").and_then(|v| v.as_str()) == Some("write_address") {
                        index_node_id = Some(edge.source.clone());
                        if let Some(src_node) = self.graph.nodes.get(&edge.source) {
                            index_name = src_node
                                .data
                                .get("name")
                                .and_then(|v| v.as_str())
                                .unwrap_or(&src_node.id)
                                .to_string();
                        }
                        break;
                    }
                }
            }

            if index_node_id.is_none() {
                info!(
                    "  Warning: write port {} has no write_address edge",
                    node.id
                );
                continue;
            }

            let uarch_time = node.uarch_time.unwrap_or(0);

            result.push(ArrayAccessInfo {
                node_id: node.id.clone(),
                base_resource: resource_name.to_string(),
                index: index_name,
                index_node_id,
                access_type: "WRITE".to_string(),
                uarch_time,
            });
        }

        result
    }

    /// Check if an access should be renamed based on spec filters.
    fn should_rename_index(&self, spec: &RegisterRenamingSpec, access: &ArrayAccessInfo) -> bool {
        if access.index_node_id.is_none() {
            return false;
        }

        if let Some(ref targets) = spec.target_indices {
            for target in targets {
                if access.index == *target || access.index.ends_with(&format!("_{}", target)) {
                    return true;
                }
            }
            false
        } else {
            // Rename all indices
            true
        }
    }

    // -----------------------------------------------------------------------
    // Phase 2: Planning
    // -----------------------------------------------------------------------

    fn phase2_planning(&self, spec: &RegisterRenamingSpec) -> RenamePlanResult {
        info!("[PHASE 2: PLANNING] Creating renaming plan");

        let renamer_id = format!("renamer_{}", spec.resource_name);
        let denamer_id = format!("denamer_{}", spec.resource_name);
        let rename_table_id = format!("rename_table_{}", spec.resource_name);
        let free_list_id = format!("free_list_{}", spec.resource_name);

        info!("  Renamer node: {}", renamer_id);
        info!("  Denamer node: {}", denamer_id);
        info!("  Rename table: {}", rename_table_id);
        info!("  Free list: {}", free_list_id);

        RenamePlanResult {
            renamer_id,
            denamer_id,
            rename_table_id,
            free_list_id,
        }
    }

    // -----------------------------------------------------------------------
    // Phase 3: Structure
    // -----------------------------------------------------------------------

    fn phase3_structure(
        &mut self,
        spec: &RegisterRenamingSpec,
        analysis: &RenameAnalysisResult,
        plan: &RenamePlanResult,
    ) -> RenameStructureResult {
        info!("[PHASE 3: STRUCTURE] Creating renaming component structure");

        // Create rename table
        let mut rename_table_data = HashMap::new();
        rename_table_data.insert("type".to_string(), json!("rename_table"));
        rename_table_data.insert("name".to_string(), json!(plan.rename_table_id));
        rename_table_data.insert(
            "display_name".to_string(),
            json!(format!("Rename Table ({})", spec.resource_name)),
        );
        rename_table_data.insert("resource_name".to_string(), json!(spec.resource_name));
        rename_table_data.insert(
            "num_physical_regs".to_string(),
            json!(spec.num_physical_regs),
        );
        rename_table_data.insert("is_uarch_state".to_string(), json!(true));

        let mut rename_table_node =
            Node::new(Some(plan.rename_table_id.clone()), Some(rename_table_data),
                false, false, None, true, None, None, false, false, 0, false, false, None, None);
        rename_table_node.is_uarch_state = true;
        self.graph.add_node(rename_table_node);
        info!("  Created rename table: {}", plan.rename_table_id);

        // Create free list
        let mut free_list_data = HashMap::new();
        free_list_data.insert("type".to_string(), json!("free_list"));
        free_list_data.insert("name".to_string(), json!(plan.free_list_id));
        free_list_data.insert(
            "display_name".to_string(),
            json!(format!("Free List ({})", spec.resource_name)),
        );
        free_list_data.insert("resource_name".to_string(), json!(spec.resource_name));
        free_list_data.insert(
            "num_physical_regs".to_string(),
            json!(spec.num_physical_regs),
        );
        free_list_data.insert("is_uarch_state".to_string(), json!(true));

        let mut free_list_node =
            Node::new(Some(plan.free_list_id.clone()), Some(free_list_data),
                false, false, None, true, None, None, false, false, 0, false, false, None, None);
        free_list_node.is_uarch_state = true;
        self.graph.add_node(free_list_node);
        info!("  Created free list: {}", plan.free_list_id);

        // Create renamer node
        let mut renamer_data = HashMap::new();
        renamer_data.insert("type".to_string(), json!("renamer"));
        renamer_data.insert("name".to_string(), json!(plan.renamer_id));
        renamer_data.insert(
            "display_name".to_string(),
            json!(format!("Renamer ({})", spec.resource_name)),
        );
        renamer_data.insert("resource_name".to_string(), json!(spec.resource_name));
        renamer_data.insert(
            "num_physical_regs".to_string(),
            json!(spec.num_physical_regs),
        );
        renamer_data.insert("num_reads".to_string(), json!(analysis.read_indices.len()));
        renamer_data.insert("num_writes".to_string(), json!(analysis.write_indices.len()));

        let renamer_node =
            Node::new(Some(plan.renamer_id.clone()), Some(renamer_data),
                false, false, None, false, None, None, false, false, 0, false, false, None, None);
        self.graph.add_node(renamer_node);
        info!("  Created renamer: {}", plan.renamer_id);

        // Create denamer node
        let mut denamer_data = HashMap::new();
        denamer_data.insert("type".to_string(), json!("denamer"));
        denamer_data.insert("name".to_string(), json!(plan.denamer_id));
        denamer_data.insert(
            "display_name".to_string(),
            json!(format!("Denamer ({})", spec.resource_name)),
        );
        denamer_data.insert("resource_name".to_string(), json!(spec.resource_name));

        let denamer_node =
            Node::new(Some(plan.denamer_id.clone()), Some(denamer_data),
                false, false, None, false, None, None, false, false, 0, false, false, None, None);
        self.graph.add_node(denamer_node);
        info!("  Created denamer: {}", plan.denamer_id);

        // Create microarchitectural index nodes
        let mut renamed_index_nodes = HashMap::new();
        for index_node_id in &analysis.all_index_node_ids {
            let uarch_index_id = format!("uarch_{}", index_node_id);

            let mut uarch_index_data = HashMap::new();
            uarch_index_data.insert("type".to_string(), json!("uarch_index"));
            uarch_index_data.insert("name".to_string(), json!(uarch_index_id));
            uarch_index_data.insert(
                "display_name".to_string(),
                json!(format!("Physical {}", index_node_id)),
            );
            uarch_index_data.insert("architectural_index".to_string(), json!(index_node_id));
            uarch_index_data.insert("resource_name".to_string(), json!(spec.resource_name));

            let uarch_index_node =
                Node::new(Some(uarch_index_id.clone()), Some(uarch_index_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None, None);
            self.graph.add_node(uarch_index_node);
            renamed_index_nodes.insert(index_node_id.clone(), uarch_index_id);
        }

        // Create physical register file if separate_regfiles mode
        let physical_regfile_node_id = if spec.separate_regfiles {
            self.create_physical_regfile(spec)
        } else {
            None
        };

        info!(
            "  Created {} microarchitectural index node(s)",
            renamed_index_nodes.len()
        );

        RenameStructureResult {
            renamer_node_id: plan.renamer_id.clone(),
            denamer_node_id: plan.denamer_id.clone(),
            rename_table_node_id: plan.rename_table_id.clone(),
            free_list_node_id: plan.free_list_id.clone(),
            renamed_index_nodes,
            physical_regfile_node_id,
        }
    }

    /// Create a separate physical register file node.
    fn create_physical_regfile(&mut self, spec: &RegisterRenamingSpec) -> Option<String> {
        // Find the original architectural register file
        let mut arch_rf_id = None;
        let mut bit_width = None;
        for node in self.graph.nodes.values() {
            if node.is_arch_state
                && node.data.get("name").and_then(|v| v.as_str()) == Some(&spec.resource_name)
            {
                arch_rf_id = Some(node.id.clone());
                bit_width = node.data.get("bit_width").cloned();
                break;
            }
        }

        let arch_rf_id = match arch_rf_id {
            Some(id) => id,
            None => {
                info!(
                    "Warning: Could not find architectural register file '{}'",
                    spec.resource_name
                );
                return None;
            }
        };

        let prf_id = format!("prf_{}", spec.resource_name);
        let mut prf_data = HashMap::new();
        prf_data.insert("type".to_string(), json!("physical_regfile"));
        prf_data.insert("name".to_string(), json!(prf_id));
        prf_data.insert(
            "display_name".to_string(),
            json!(format!("Physical RF ({})", spec.resource_name)),
        );
        prf_data.insert("resource_name".to_string(), json!(spec.resource_name));
        prf_data.insert(
            "num_physical_regs".to_string(),
            json!(spec.num_physical_regs),
        );
        prf_data.insert("is_uarch_state".to_string(), json!(true));
        prf_data.insert("architectural_counterpart".to_string(), json!(arch_rf_id));

        if let Some(bw) = bit_width {
            prf_data.insert("bit_width".to_string(), bw);
        }
        prf_data.insert("array_depth".to_string(), json!(spec.num_physical_regs));

        let mut prf_node =
            Node::new(Some(prf_id.clone()), Some(prf_data),
                false, false, None, true, None, None, false, false, 0, false, false, None, None);
        prf_node.is_uarch_state = true;
        self.graph.add_node(prf_node);
        info!(
            "  Created physical register file: {} ({} registers)",
            prf_id, spec.num_physical_regs
        );

        Some(prf_id)
    }

    // -----------------------------------------------------------------------
    // Phase 4: Hardware
    // -----------------------------------------------------------------------

    fn phase4_hardware(&self) {
        info!("[PHASE 4: HARDWARE] Generating renaming hardware");
        info!("  Renaming hardware components created");
        info!("  Note: Renamer and denamer nodes represent the renaming logic");
    }

    // -----------------------------------------------------------------------
    // Phase 5: Connection
    // -----------------------------------------------------------------------

    fn phase5_connection(
        &mut self,
        spec: &RegisterRenamingSpec,
        analysis: &RenameAnalysisResult,
        structure: &RenameStructureResult,
    ) {
        info!("[PHASE 5: CONNECTION] Wiring renaming components");

        // Connect architectural indices to renamer
        self.connect_arch_indices_to_renamer(analysis, structure);

        // Connect renamer to microarchitectural indices
        self.connect_renamer_to_uarch_indices(structure);

        if spec.separate_regfiles {
            // Separate register files mode
            self.redirect_to_physical_regfile(spec, analysis, structure);
        } else {
            // Index renaming mode
            self.redirect_read_accesses(analysis, structure);
            self.redirect_write_accesses(analysis, structure);
        }

        // Connect renamer to state tables
        self.connect_state_tables(structure);

        info!("  Wiring complete");
    }

    /// Connect architectural index nodes to renamer inputs.
    fn connect_arch_indices_to_renamer(
        &mut self,
        analysis: &RenameAnalysisResult,
        structure: &RenameStructureResult,
    ) {
        info!(
            "  Connecting {} architectural index/indices to renamer",
            analysis.all_index_node_ids.len()
        );

        for (idx, index_node_id) in analysis.all_index_node_ids.iter().enumerate() {
            let mut data = HashMap::new();
            data.insert("type".to_string(), json!("rename_input"));
            data.insert("input_position".to_string(), json!(idx));
            data.insert("architectural_index".to_string(), json!(index_node_id));

            let edge = Edge::new(
                index_node_id.clone(),
                structure.renamer_node_id.clone(),
                None,
                Some(data),
            );
            self.graph.add_edge(edge);
        }
    }

    /// Connect renamer outputs to microarchitectural index nodes.
    fn connect_renamer_to_uarch_indices(&mut self, structure: &RenameStructureResult) {
        info!(
            "  Connecting renamer to {} microarchitectural index/indices",
            structure.renamed_index_nodes.len()
        );

        for (arch_index_id, uarch_index_id) in &structure.renamed_index_nodes {
            let mut data = HashMap::new();
            data.insert("type".to_string(), json!("rename_output"));
            data.insert("architectural_index".to_string(), json!(arch_index_id));

            let edge = Edge::new(
                structure.renamer_node_id.clone(),
                uarch_index_id.clone(),
                None,
                Some(data),
            );
            self.graph.add_edge(edge);
        }
    }

    /// Redirect read accesses to use microarchitectural indices.
    fn redirect_read_accesses(
        &mut self,
        analysis: &RenameAnalysisResult,
        structure: &RenameStructureResult,
    ) {
        info!(
            "  Redirecting {} read access(es)",
            analysis.read_indices.len()
        );

        for read_mapping in &analysis.read_indices {
            let uarch_index_id =
                match structure.renamed_index_nodes.get(&read_mapping.index_node_id) {
                    Some(id) => id.clone(),
                    None => continue,
                };

            // Find and remove edge from architectural index to array access
            let edges_to_remove: Vec<String> = {
                let array_node = match self.graph.nodes.get(&read_mapping.array_access_node_id) {
                    Some(n) => n,
                    None => continue,
                };
                array_node
                    .incoming_edges
                    .iter()
                    .filter(|eid| {
                        self.graph.edges.get(*eid).map_or(false, |e| {
                            e.source == read_mapping.index_node_id
                                && e.data.get("type").and_then(|v| v.as_str())
                                    == Some("array_index")
                        })
                    })
                    .cloned()
                    .collect()
            };

            for eid in &edges_to_remove {
                self.graph.remove_edge(eid);
            }

            // Add edge from microarchitectural index to array access
            let mut data = HashMap::new();
            data.insert("type".to_string(), json!("array_index"));
            data.insert("renamed".to_string(), json!(true));
            data.insert(
                "original_index".to_string(),
                json!(read_mapping.index_node_id),
            );

            let edge = Edge::new(
                uarch_index_id,
                read_mapping.array_access_node_id.clone(),
                None,
                Some(data),
            );
            self.graph.add_edge(edge);
        }
    }

    /// Mark write accesses for physical index override by the renamer.
    fn redirect_write_accesses(
        &mut self,
        analysis: &RenameAnalysisResult,
        structure: &RenameStructureResult,
    ) {
        info!(
            "  Marking {} write access(es) for physical index override",
            analysis.write_indices.len()
        );

        for write_mapping in &analysis.write_indices {
            let uarch_index_id =
                match structure.renamed_index_nodes.get(&write_mapping.index_node_id) {
                    Some(id) => id.clone(),
                    None => continue,
                };

            // Store the physical index node reference as metadata on the write node
            if let Some(write_node) = self.graph.nodes.get_mut(&write_mapping.array_access_node_id)
            {
                write_node
                    .data
                    .insert("renamed_write_index".to_string(), json!(uarch_index_id));
                write_node.data.insert(
                    "original_write_index".to_string(),
                    json!(write_mapping.index_node_id),
                );
            }

            // Tag the uarch_index node as a write index
            if let Some(uarch_node) = self.graph.nodes.get_mut(&uarch_index_id) {
                uarch_node
                    .data
                    .insert("rename_role".to_string(), json!("write"));
            }

            info!(
                "    Marked {}: physical index = {} (arch = {})",
                write_mapping.array_access_node_id, uarch_index_id, write_mapping.index_node_id
            );
        }
    }

    /// Redirect accesses to use physical register file (separate_regfiles mode).
    fn redirect_to_physical_regfile(
        &mut self,
        spec: &RegisterRenamingSpec,
        analysis: &RenameAnalysisResult,
        structure: &RenameStructureResult,
    ) {
        info!("  Redirecting accesses to separate physical register file");

        let prf_node_id = match &structure.physical_regfile_node_id {
            Some(id) => id.clone(),
            None => {
                info!("  Error: Physical register file not created");
                return;
            }
        };

        // Process read accesses - redirect to PRF
        info!(
            "    Redirecting {} read(s) to PRF",
            analysis.read_indices.len()
        );
        for read_mapping in &analysis.read_indices {
            let uarch_index_id =
                match structure.renamed_index_nodes.get(&read_mapping.index_node_id) {
                    Some(id) => id.clone(),
                    None => continue,
                };

            // Create new array access node for PRF
            let prf_access_id = format!("prf_{}", read_mapping.array_access_node_id);
            let mut prf_access_data = HashMap::new();
            prf_access_data.insert("type".to_string(), json!("array_access"));
            prf_access_data.insert(
                "name".to_string(),
                json!(format!(
                    "prf_{}[{}]",
                    spec.resource_name, read_mapping.index_name
                )),
            );
            prf_access_data.insert(
                "base_resource".to_string(),
                json!(format!("prf_{}", spec.resource_name)),
            );
            prf_access_data.insert(
                "display_name".to_string(),
                json!(format!("PRF[{}]", read_mapping.index_name)),
            );

            let prf_access_node =
                Node::new(Some(prf_access_id.clone()), Some(prf_access_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None, None);
            self.graph.add_node(prf_access_node);

            // Connect: PRF -> prf_access
            let mut base_data = HashMap::new();
            base_data.insert("type".to_string(), json!("base_resource"));
            let edge_prf = Edge::new(
                prf_node_id.clone(),
                prf_access_id.clone(),
                None,
                Some(base_data),
            );
            self.graph.add_edge(edge_prf);

            // Connect: uarch_index -> prf_access
            let mut idx_data = HashMap::new();
            idx_data.insert("type".to_string(), json!("array_index"));
            idx_data.insert("renamed".to_string(), json!(true));
            idx_data.insert("physical_index".to_string(), json!(true));
            let edge_idx = Edge::new(
                uarch_index_id.clone(),
                prf_access_id.clone(),
                None,
                Some(idx_data),
            );
            self.graph.add_edge(edge_idx);

            // Redirect output edges from original array_access to prf_access
            let edges_to_redirect: Vec<(String, String)> = {
                let array_node =
                    match self.graph.nodes.get(&read_mapping.array_access_node_id) {
                        Some(n) => n,
                        None => continue,
                    };
                array_node
                    .outgoing_edges
                    .iter()
                    .filter_map(|eid| {
                        self.graph.edges.get(eid).and_then(|e| {
                            if e.data.get("type").and_then(|v| v.as_str()) == Some("assignment") {
                                Some((eid.clone(), e.target.clone()))
                            } else {
                                None
                            }
                        })
                    })
                    .collect()
            };

            for (old_eid, target_id) in &edges_to_redirect {
                self.graph.remove_edge(old_eid);
                let mut new_data = HashMap::new();
                new_data.insert("type".to_string(), json!("assignment"));
                new_data.insert("from_prf".to_string(), json!(true));
                let new_edge = Edge::new(
                    prf_access_id.clone(),
                    target_id.clone(),
                    None,
                    Some(new_data),
                );
                self.graph.add_edge(new_edge);
            }
        }

        // Process write accesses - write to BOTH PRF and ARF
        info!(
            "    Redirecting {} write(s) to PRF + ARF",
            analysis.write_indices.len()
        );
        for write_mapping in &analysis.write_indices {
            let uarch_index_id =
                match structure.renamed_index_nodes.get(&write_mapping.index_node_id) {
                    Some(id) => id.clone(),
                    None => continue,
                };

            // Create new array access node for PRF write
            let prf_access_id = format!("prf_{}", write_mapping.array_access_node_id);
            let mut prf_access_data = HashMap::new();
            prf_access_data.insert("type".to_string(), json!("array_access"));
            prf_access_data.insert(
                "name".to_string(),
                json!(format!(
                    "prf_{}[{}]",
                    spec.resource_name, write_mapping.index_name
                )),
            );
            prf_access_data.insert(
                "base_resource".to_string(),
                json!(format!("prf_{}", spec.resource_name)),
            );
            prf_access_data.insert(
                "display_name".to_string(),
                json!(format!("PRF[{}]", write_mapping.index_name)),
            );

            let prf_access_node =
                Node::new(Some(prf_access_id.clone()), Some(prf_access_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None, None);
            self.graph.add_node(prf_access_node);

            // Connect: PRF -> prf_access
            let mut base_data = HashMap::new();
            base_data.insert("type".to_string(), json!("base_resource"));
            let edge_prf = Edge::new(
                prf_node_id.clone(),
                prf_access_id.clone(),
                None,
                Some(base_data),
            );
            self.graph.add_edge(edge_prf);

            // Connect: uarch_index -> prf_access
            let mut idx_data = HashMap::new();
            idx_data.insert("type".to_string(), json!("array_index"));
            idx_data.insert("renamed".to_string(), json!(true));
            idx_data.insert("physical_index".to_string(), json!(true));
            let edge_idx = Edge::new(
                uarch_index_id.clone(),
                prf_access_id.clone(),
                None,
                Some(idx_data),
            );
            self.graph.add_edge(edge_idx);

            // Copy assignment input edges to PRF access
            let assignment_sources: Vec<String> = {
                let array_node =
                    match self.graph.nodes.get(&write_mapping.array_access_node_id) {
                        Some(n) => n,
                        None => continue,
                    };
                array_node
                    .incoming_edges
                    .iter()
                    .filter_map(|eid| {
                        self.graph.edges.get(eid).and_then(|e| {
                            if e.data.get("type").and_then(|v| v.as_str()) == Some("assignment") {
                                Some(e.source.clone())
                            } else {
                                None
                            }
                        })
                    })
                    .collect()
            };

            for source_id in &assignment_sources {
                let mut new_data = HashMap::new();
                new_data.insert("type".to_string(), json!("assignment"));
                new_data.insert("to_prf".to_string(), json!(true));
                let new_edge = Edge::new(
                    source_id.clone(),
                    prf_access_id.clone(),
                    None,
                    Some(new_data),
                );
                self.graph.add_edge(new_edge);
            }

            // For ARF: Use denamer to convert physical index back to architectural
            let denamer_instance_id = format!(
                "{}_{}_arf",
                structure.denamer_node_id, write_mapping.index_name
            );
            let mut denamer_data = HashMap::new();
            denamer_data.insert("type".to_string(), json!("denamer_instance"));
            denamer_data.insert("name".to_string(), json!(denamer_instance_id));
            denamer_data.insert(
                "display_name".to_string(),
                json!(format!("Denamer ARF ({})", write_mapping.index_name)),
            );
            denamer_data.insert("resource_name".to_string(), json!(spec.resource_name));
            denamer_data.insert(
                "architectural_index".to_string(),
                json!(write_mapping.index_node_id),
            );

            let denamer_instance =
                Node::new(Some(denamer_instance_id.clone()), Some(denamer_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None, None);
            self.graph.add_node(denamer_instance);

            // Connect: uarch_index -> denamer_instance
            let mut den_in_data = HashMap::new();
            den_in_data.insert("type".to_string(), json!("denamer_input"));
            den_in_data.insert("uarch_index".to_string(), json!(uarch_index_id));
            let edge_den = Edge::new(
                uarch_index_id.clone(),
                denamer_instance_id.clone(),
                None,
                Some(den_in_data),
            );
            self.graph.add_edge(edge_den);

            // Remove old architectural index edge from ARF access
            let edges_to_remove: Vec<String> = {
                let array_node =
                    match self.graph.nodes.get(&write_mapping.array_access_node_id) {
                        Some(n) => n,
                        None => continue,
                    };
                array_node
                    .incoming_edges
                    .iter()
                    .filter(|eid| {
                        self.graph.edges.get(*eid).map_or(false, |e| {
                            e.source == write_mapping.index_node_id
                                && e.data.get("type").and_then(|v| v.as_str())
                                    == Some("array_index")
                        })
                    })
                    .cloned()
                    .collect()
            };

            for eid in &edges_to_remove {
                self.graph.remove_edge(eid);
            }

            // Connect: denamer_instance -> arf_access
            let mut den_out_data = HashMap::new();
            den_out_data.insert("type".to_string(), json!("array_index"));
            den_out_data.insert("denamed".to_string(), json!(true));
            den_out_data.insert("architectural_index".to_string(), json!(true));
            let edge_den_out = Edge::new(
                denamer_instance_id,
                write_mapping.array_access_node_id.clone(),
                None,
                Some(den_out_data),
            );
            self.graph.add_edge(edge_den_out);
        }
    }

    /// Connect renamer to state tables (rename table and free list).
    fn connect_state_tables(&mut self, structure: &RenameStructureResult) {
        info!("  Connecting state tables");

        // Rename table -> renamer
        let mut data1 = HashMap::new();
        data1.insert("type".to_string(), json!("state_read"));
        data1.insert("state_type".to_string(), json!("rename_table"));
        let e1 = Edge::new(
            structure.rename_table_node_id.clone(),
            structure.renamer_node_id.clone(),
            None,
            Some(data1),
        );
        self.graph.add_edge(e1);

        // Renamer -> rename table
        let mut data2 = HashMap::new();
        data2.insert("type".to_string(), json!("state_write"));
        data2.insert("state_type".to_string(), json!("rename_table"));
        let e2 = Edge::new(
            structure.renamer_node_id.clone(),
            structure.rename_table_node_id.clone(),
            None,
            Some(data2),
        );
        self.graph.add_edge(e2);

        // Free list -> renamer
        let mut data3 = HashMap::new();
        data3.insert("type".to_string(), json!("state_read"));
        data3.insert("state_type".to_string(), json!("free_list"));
        let e3 = Edge::new(
            structure.free_list_node_id.clone(),
            structure.renamer_node_id.clone(),
            None,
            Some(data3),
        );
        self.graph.add_edge(e3);

        // Renamer -> free list
        let mut data4 = HashMap::new();
        data4.insert("type".to_string(), json!("state_write"));
        data4.insert("state_type".to_string(), json!("free_list"));
        let e4 = Edge::new(
            structure.renamer_node_id.clone(),
            structure.free_list_node_id.clone(),
            None,
            Some(data4),
        );
        self.graph.add_edge(e4);

        // Rename table -> denamer (reverse lookup)
        let mut data5 = HashMap::new();
        data5.insert("type".to_string(), json!("state_read"));
        data5.insert("state_type".to_string(), json!("rename_table"));
        let e5 = Edge::new(
            structure.rename_table_node_id.clone(),
            structure.denamer_node_id.clone(),
            None,
            Some(data5),
        );
        self.graph.add_edge(e5);
    }

    // -----------------------------------------------------------------------
    // Phase 5.5: Expand register file
    // -----------------------------------------------------------------------

    fn expand_register_file(&mut self, spec: &RegisterRenamingSpec) {
        let new_addr_width = if spec.num_physical_regs > 1 {
            (spec.num_physical_regs as f64).log2().ceil() as u32
        } else {
            1
        };
        info!(
            "[PHASE 5.5] Expanding register file '{}' to {} entries ({}-bit address)",
            spec.resource_name, spec.num_physical_regs, new_addr_width
        );

        // Find the register file node
        let rf_node_id = {
            let mut found = None;
            for node in self.graph.nodes.values() {
                if node.is_arch_state
                    && node.data.get("name").and_then(|v| v.as_str())
                        == Some(&spec.resource_name)
                {
                    found = Some(node.id.clone());
                    break;
                }
            }
            found
        };

        let rf_node_id = match rf_node_id {
            Some(id) => id,
            None => {
                info!(
                    "  Warning: Could not find register file '{}'",
                    spec.resource_name
                );
                return;
            }
        };

        if let Some(rf_node) = self.graph.nodes.get_mut(&rf_node_id) {
            let old_depth = rf_node
                .data
                .get("array_depth")
                .and_then(|v| v.as_u64())
                .unwrap_or(5) as u32;

            rf_node
                .data
                .insert("array_depth".to_string(), json!(new_addr_width));

            // Also update dimensions if present
            if let Some(dims) = rf_node.data.get("dimensions").cloned() {
                if let Some(arr) = dims.as_array() {
                    if arr.len() >= 2 {
                        let new_dims = json!([arr[0], [new_addr_width - 1, 0]]);
                        rf_node.data.insert("dimensions".to_string(), new_dims);
                    }
                }
            }

            info!(
                "  Expanded {} array_depth: {} -> {} bits ({} -> {} entries)",
                spec.resource_name,
                old_depth,
                new_addr_width,
                1u64 << old_depth,
                1u64 << new_addr_width,
            );
        }
    }

    // -----------------------------------------------------------------------
    // Phase 6: Cleanup
    // -----------------------------------------------------------------------

    fn phase6_cleanup(&mut self) {
        info!("[PHASE 6: CLEANUP] Cleaning up graph");

        // Find orphaned nodes (no edges, not arch state, not input/field)
        let orphaned: Vec<String> = self
            .graph
            .nodes
            .values()
            .filter(|node| {
                node.incoming_edges.is_empty()
                    && node.outgoing_edges.is_empty()
                    && !node.is_arch_state
                    && node.data.get("type").and_then(|v| v.as_str()) != Some("input")
                    && node.data.get("type").and_then(|v| v.as_str()) != Some("field")
            })
            .map(|n| n.id.clone())
            .collect();

        for nid in &orphaned {
            self.graph.remove_node(nid);
        }

        if !orphaned.is_empty() {
            info!("  Removed {} orphaned node(s)", orphaned.len());
        } else {
            info!("  No cleanup needed");
        }
    }

    // -----------------------------------------------------------------------
    // Phase 7: Timing
    // -----------------------------------------------------------------------

    fn phase7_timing(&mut self) {
        info!("[PHASE 7: TIMING] Updating timing information");

        self.graph.infer_uarch_time(true);

        let max_time = self.graph.get_max_uarch_time();
        info!("  Timing re-inference complete");
        info!("  Maximum uarch_time: {}", max_time);
    }
}

// ---------------------------------------------------------------------------
// Standalone API
// ---------------------------------------------------------------------------

/// Convenience function to apply register renaming to a graph.
///
/// Returns `true` if renaming was applied successfully.
pub fn apply_register_renaming(graph: &mut ResourceGraph, spec: &RegisterRenamingSpec) -> bool {
    let mut optimizer = RegisterRenamingOptimization::new(graph);
    optimizer.apply(spec)
}

/// Get all microarchitectural index nodes in the graph.
///
/// Useful for dependency analysis after renaming, so that
/// hazard detection uses physical register indices instead of architectural ones.
///
/// Returns a mapping from architectural index names to uarch index node IDs.
pub fn get_microarchitectural_index_nodes(graph: &ResourceGraph) -> HashMap<String, String> {
    let mut uarch_indices = HashMap::new();

    for node in graph.nodes.values() {
        if node.data.get("type").and_then(|v| v.as_str()) == Some("uarch_index") {
            if let Some(arch_index) = node
                .data
                .get("architectural_index")
                .and_then(|v| v.as_str())
            {
                uarch_indices.insert(arch_index.to_string(), node.id.clone());
            }
        }
    }

    uarch_indices
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_spec_validation_valid() {
        let spec = RegisterRenamingSpec::new("rf", 64, None, true, false);
        assert!(spec.is_ok());
        let s = spec.unwrap();
        assert_eq!(s.resource_name, "rf");
        assert_eq!(s.num_physical_regs, 64);
        assert!(s.target_indices.is_none());
        assert!(s.enable_verification);
        assert!(!s.separate_regfiles);
    }

    #[test]
    fn test_spec_validation_invalid() {
        let spec = RegisterRenamingSpec::new("rf", 0, None, true, false);
        assert!(spec.is_err());
        assert!(spec.unwrap_err().contains("num_physical_regs must be >= 1"));
    }

    #[test]
    fn test_spec_with_target_indices() {
        let spec = RegisterRenamingSpec::new(
            "rf",
            64,
            Some(vec!["rs".to_string(), "rt".to_string(), "rd".to_string()]),
            true,
            false,
        );
        assert!(spec.is_ok());
        let s = spec.unwrap();
        assert_eq!(
            s.target_indices,
            Some(vec!["rs".to_string(), "rt".to_string(), "rd".to_string()])
        );
    }

    #[test]
    fn test_spec_separate_regfiles() {
        let spec = RegisterRenamingSpec::new("rf", 64, None, true, true);
        assert!(spec.is_ok());
        assert!(spec.unwrap().separate_regfiles);
    }

    #[test]
    fn test_basic_renaming_workflow() {
        // Build a simple graph with a register file and one read access
        let mut graph = ResourceGraph::new();

        // Add a register file node (architectural state)
        let mut rf_data = HashMap::new();
        rf_data.insert("type".to_string(), json!("memory"));
        rf_data.insert("name".to_string(), json!("rf"));
        rf_data.insert("bit_width".to_string(), json!(32));
        rf_data.insert("array_depth".to_string(), json!(5));
        let rf_node = Node::new(
            Some("rf".to_string()),
            Some(rf_data),
            true,  // is_arch_state
            false,
            None,
            false,
            None,
            None,
            true,
            false,
            0,
            false,
            false,
            None,
            None,
        );
        graph.add_node(rf_node);

        // Add an index node (rs)
        let mut rs_data = HashMap::new();
        rs_data.insert("type".to_string(), json!("field"));
        rs_data.insert("name".to_string(), json!("rs"));
        let rs_node = Node::new(
            Some("rs".to_string()),
            Some(rs_data),
            false,
            true, // used_as_index
            None,
            false,
            None,
            None,
            true,
            false,
            0,
            false,
            false,
            None,
            None,
        );
        graph.add_node(rs_node);

        // Add an array_access node (rf[rs] read)
        let mut access_data = HashMap::new();
        access_data.insert("type".to_string(), json!("array_access"));
        access_data.insert("base_resource".to_string(), json!("rf"));
        access_data.insert("name".to_string(), json!("rf[rs]"));
        let access_node = Node::new(
            Some("rf_rs_read".to_string()),
            Some(access_data),
            false,
            false,
            Some("rs".to_string()),
            false,
            None,
            None,
            false,
            false,
            0,
            false,
            false,
            None,
            None,
        );
        graph.add_node(access_node);

        // Add edge: rs -> rf[rs] (array_index)
        let mut idx_edge_data = HashMap::new();
        idx_edge_data.insert("type".to_string(), json!("array_index"));
        let idx_edge = Edge::new(
            "rs".to_string(),
            "rf_rs_read".to_string(),
            None,
            Some(idx_edge_data),
        );
        graph.add_edge(idx_edge);

        // Add a target node that receives the read value
        let mut target_data = HashMap::new();
        target_data.insert("type".to_string(), json!("var"));
        target_data.insert("name".to_string(), json!("r1_val"));
        let target_node = Node::new(
            Some("r1_val".to_string()),
            Some(target_data),
            false,
            false,
            None,
            false,
            None,
            None,
            false,
            false,
            0,
            false,
            false,
            None,
            None,
        );
        graph.add_node(target_node);

        // Add edge: rf[rs] -> r1_val (assignment)
        let mut assign_data = HashMap::new();
        assign_data.insert("type".to_string(), json!("assignment"));
        let assign_edge = Edge::new(
            "rf_rs_read".to_string(),
            "r1_val".to_string(),
            None,
            Some(assign_data),
        );
        graph.add_edge(assign_edge);

        // Now apply renaming
        let spec = RegisterRenamingSpec::new("rf", 64, None, true, false).unwrap();
        let result = apply_register_renaming(&mut graph, &spec);
        assert!(result, "Renaming should succeed");

        // Verify that renaming components were created
        assert!(
            graph.nodes.contains_key("renamer_rf"),
            "Renamer node should exist"
        );
        assert!(
            graph.nodes.contains_key("denamer_rf"),
            "Denamer node should exist"
        );
        assert!(
            graph.nodes.contains_key("rename_table_rf"),
            "Rename table should exist"
        );
        assert!(
            graph.nodes.contains_key("free_list_rf"),
            "Free list should exist"
        );
        assert!(
            graph.nodes.contains_key("uarch_rs"),
            "Microarchitectural index should exist"
        );

        // Verify that the renamed index node has the correct type
        let uarch_rs = graph.nodes.get("uarch_rs").unwrap();
        assert_eq!(
            uarch_rs.data.get("type").and_then(|v| v.as_str()),
            Some("uarch_index")
        );
        assert_eq!(
            uarch_rs
                .data
                .get("architectural_index")
                .and_then(|v| v.as_str()),
            Some("rs")
        );
    }

    #[test]
    fn test_no_accesses_returns_false() {
        let mut graph = ResourceGraph::new();

        // Add an empty register file with no accesses
        let mut rf_data = HashMap::new();
        rf_data.insert("type".to_string(), json!("memory"));
        rf_data.insert("name".to_string(), json!("rf"));
        let rf_node = Node::new(
            Some("rf".to_string()),
            Some(rf_data),
            true,
            false,
            None,
            false,
            None,
            None,
            true,
            false,
            0,
            false,
            false,
            None,
            None,
        );
        graph.add_node(rf_node);

        let spec = RegisterRenamingSpec::new("rf", 64, None, true, false).unwrap();
        let result = apply_register_renaming(&mut graph, &spec);
        assert!(!result, "Renaming should fail when no accesses found");
    }

    #[test]
    fn test_get_microarchitectural_index_nodes() {
        let mut graph = ResourceGraph::new();

        // Add a uarch_index node
        let mut data = HashMap::new();
        data.insert("type".to_string(), json!("uarch_index"));
        data.insert("architectural_index".to_string(), json!("rs"));
        let node = Node::new(
            Some("uarch_rs".to_string()),
            Some(data),
            false,
            false,
            None,
            false,
            None,
            None,
            false,
            false,
            0,
            false,
            false,
            None,
            None,
        );
        graph.add_node(node);

        let result = get_microarchitectural_index_nodes(&graph);
        assert_eq!(result.len(), 1);
        assert_eq!(result.get("rs"), Some(&"uarch_rs".to_string()));
    }
}
