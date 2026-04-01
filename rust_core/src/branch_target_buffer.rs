//! Branch Target Buffer (BTB) Optimization for ResourceGraph.
//!
//! Predicts branch target addresses by caching PC -> target mappings.
//! Supports RAS coordination, configurable size/associativity, and
//! 2-bit saturating counter direction prediction.

use log::info;
use serde_json::json;
use std::collections::HashMap;

use crate::resource_graph::{Edge, Node, ResourceGraph};

/// Helper to create an edge with optional data.
fn make_edge(source: &str, target: &str) -> Edge {
    Edge::new(source.to_string(), target.to_string(), None, None)
}

fn make_edge_with_data(source: &str, target: &str, data: HashMap<String, serde_json::Value>) -> Edge {
    Edge::new(source.to_string(), target.to_string(), None, Some(data))
}

/// Helper to create a typed edge.
fn typed_edge(source: &str, target: &str, edge_type: &str) -> Edge {
    let mut data = HashMap::new();
    data.insert("type".to_string(), json!(edge_type));
    make_edge_with_data(source, target, data)
}

/// Helper to create an operand edge with position.
fn operand_edge(source: &str, target: &str, position: &str) -> Edge {
    let mut data = HashMap::new();
    data.insert("type".to_string(), json!("operand"));
    data.insert("position".to_string(), json!(position));
    make_edge_with_data(source, target, data)
}

// ---------------------------------------------------------------------------
// BTBSpec
// ---------------------------------------------------------------------------

/// Specification for Branch Target Buffer insertion.
#[derive(Debug, Clone)]
pub struct BTBSpec {
    /// Branch enable node IDs (ORed together for BTB update enable)
    pub branch_enable_nodes: Vec<String>,
    /// Signal indicating branch taken/not-taken (Execute stage)
    pub branch_outcome_node: String,
    /// Actual resolved target address (Execute stage)
    pub branch_target_node: String,
    /// Fetch stage PC (used for BTB lookup)
    pub fetch_pc_node: String,
    /// Execute stage PC (for BTB update)
    pub branch_pc_node: String,
    /// Node that will receive the predicted PC
    pub predicted_pc_node_id: String,
    /// Node with default prediction (PC+4)
    pub default_prediction_node_id: String,
    /// Existing control hazard flush signal
    pub control_hazard_flush_node_id: String,
    /// RAS pop signal (optional, for RAS coordination)
    pub ras_pop_node_id: Option<String>,
    /// RAS predicted target (optional)
    pub ras_top_node_id: Option<String>,
    /// Number of BTB entries (power of 2)
    pub num_entries: usize,
    /// Associativity (1=direct-mapped, 2/4/8=set-associative)
    pub associativity: usize,
    /// Address width in bits
    pub pc_width: usize,
    /// Name for the BTB node
    pub btb_name: String,
    /// Store taken/not-taken history
    pub include_direction_bits: bool,
    /// 2-bit saturating counter
    pub confidence_bits: usize,
    /// Replacement policy for set-associative
    pub replacement_policy: String,
}

impl BTBSpec {
    pub fn new(
        branch_enable_nodes: Vec<String>,
        branch_outcome_node: &str,
        branch_target_node: &str,
        fetch_pc_node: &str,
        branch_pc_node: &str,
        predicted_pc_node_id: &str,
        default_prediction_node_id: &str,
        control_hazard_flush_node_id: &str,
    ) -> Result<Self, String> {
        if branch_enable_nodes.is_empty() {
            return Err("At least one branch_enable_node is required".to_string());
        }
        Ok(Self {
            branch_enable_nodes,
            branch_outcome_node: branch_outcome_node.to_string(),
            branch_target_node: branch_target_node.to_string(),
            fetch_pc_node: fetch_pc_node.to_string(),
            branch_pc_node: branch_pc_node.to_string(),
            predicted_pc_node_id: predicted_pc_node_id.to_string(),
            default_prediction_node_id: default_prediction_node_id.to_string(),
            control_hazard_flush_node_id: control_hazard_flush_node_id.to_string(),
            ras_pop_node_id: None,
            ras_top_node_id: None,
            num_entries: 64,
            associativity: 1,
            pc_width: 32,
            btb_name: "btb".to_string(),
            include_direction_bits: true,
            confidence_bits: 2,
            replacement_policy: "lru".to_string(),
        })
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.num_entries & (self.num_entries - 1) != 0 {
            return Err(format!(
                "num_entries must be power of 2, got {}",
                self.num_entries
            ));
        }
        if !matches!(self.associativity, 1 | 2 | 4 | 8) {
            return Err(format!(
                "associativity must be 1, 2, 4, or 8, got {}",
                self.associativity
            ));
        }
        if (self.ras_pop_node_id.is_none()) != (self.ras_top_node_id.is_none()) {
            return Err(
                "ras_pop_node_id and ras_top_node_id must both be set or both be None".to_string(),
            );
        }
        Ok(())
    }

    pub fn has_ras_coordination(&self) -> bool {
        self.ras_pop_node_id.is_some()
    }

    pub fn index_width(&self) -> usize {
        let num_sets = self.num_entries / self.associativity;
        if num_sets <= 1 {
            1
        } else {
            ((num_sets - 1) as f64).log2() as usize + 1
        }
    }

    pub fn tag_width(&self) -> usize {
        let byte_offset_bits = 2; // word-aligned instructions
        self.pc_width - self.index_width() - byte_offset_bits
    }
}

// ---------------------------------------------------------------------------
// BTBOptimization
// ---------------------------------------------------------------------------

pub struct BTBOptimization<'a> {
    graph: &'a mut ResourceGraph,
    spec: BTBSpec,
    btb_node_ids: HashMap<String, String>,
}

impl<'a> BTBOptimization<'a> {
    pub fn new(graph: &'a mut ResourceGraph, spec: BTBSpec) -> Self {
        Self {
            graph,
            spec,
            btb_node_ids: HashMap::new(),
        }
    }

    pub fn apply(&mut self) -> bool {
        info!("Applying Branch Target Buffer (BTB) optimization");

        if let Err(e) = self.spec.validate() {
            info!("BTB spec validation failed: {}", e);
            return false;
        }

        // Phase 1: Analysis
        if !self.analyze() {
            info!("BTB analysis failed");
            return false;
        }

        // Phase 2: Planning (computed from spec)
        let params = self.plan();

        // Phase 3: Structure
        self.create_structure(&params);

        // Phase 4: Hardware
        self.generate_hardware(&params);

        // Phase 5: Connection
        self.wire_components(&params);

        // Phase 6: Timing
        self.graph.infer_uarch_time(true);

        info!("BTB optimization completed successfully");
        true
    }

    // ----- Phase 1: Analysis -----
    fn analyze(&self) -> bool {
        // Validate all required nodes exist
        for enable_id in &self.spec.branch_enable_nodes {
            if !self.graph.nodes.contains_key(enable_id) {
                info!("Branch enable node '{}' not found", enable_id);
                return false;
            }
        }
        for node_id in &[
            &self.spec.branch_outcome_node,
            &self.spec.branch_target_node,
            &self.spec.fetch_pc_node,
            &self.spec.branch_pc_node,
            &self.spec.predicted_pc_node_id,
            &self.spec.default_prediction_node_id,
            &self.spec.control_hazard_flush_node_id,
        ] {
            if !self.graph.nodes.contains_key(*node_id) {
                info!("Required node '{}' not found", node_id);
                return false;
            }
        }
        if let Some(ref ras_pop) = self.spec.ras_pop_node_id {
            if !self.graph.nodes.contains_key(ras_pop) {
                info!("RAS pop node '{}' not found", ras_pop);
                return false;
            }
        }
        if let Some(ref ras_top) = self.spec.ras_top_node_id {
            if !self.graph.nodes.contains_key(ras_top) {
                info!("RAS top node '{}' not found", ras_top);
                return false;
            }
        }
        true
    }

    // ----- Phase 2: Planning -----
    fn plan(&self) -> HashMap<String, serde_json::Value> {
        let mut params = HashMap::new();
        params.insert("num_entries".to_string(), json!(self.spec.num_entries));
        params.insert("associativity".to_string(), json!(self.spec.associativity));
        params.insert("index_width".to_string(), json!(self.spec.index_width()));
        params.insert("tag_width".to_string(), json!(self.spec.tag_width()));
        params.insert("pc_width".to_string(), json!(self.spec.pc_width));
        params.insert(
            "confidence_bits".to_string(),
            json!(self.spec.confidence_bits),
        );
        params.insert(
            "has_ras".to_string(),
            json!(self.spec.has_ras_coordination()),
        );

        let fetch_time = self
            .graph
            .nodes
            .get(&self.spec.fetch_pc_node)
            .and_then(|n| n.uarch_time)
            .unwrap_or(0);
        let execute_time = self
            .graph
            .nodes
            .get(&self.spec.branch_pc_node)
            .and_then(|n| n.uarch_time)
            .unwrap_or(1);
        params.insert("fetch_stage".to_string(), json!(fetch_time));
        params.insert("execute_stage".to_string(), json!(execute_time));
        params
    }

    // ----- Phase 3: Structure -----
    fn create_structure(&mut self, params: &HashMap<String, serde_json::Value>) {
        let btb = &self.spec.btb_name;
        let pc_width = self.spec.pc_width as i64;
        let execute_stage = params["execute_stage"].as_i64().unwrap_or(1);

        // BTB storage node (microarchitectural state, dual-port)
        let mut storage = Node::with_defaults(Some(format!("{}_storage", btb)));
        storage.data.insert("type".to_string(), json!("btb_storage"));
        storage
            .data
            .insert("name".to_string(), json!(format!("{}_storage", btb)));
        storage.data.insert(
            "num_entries".to_string(),
            json!(self.spec.num_entries as i64),
        );
        storage.data.insert(
            "tag_width".to_string(),
            json!(self.spec.tag_width() as i64),
        );
        storage
            .data
            .insert("target_width".to_string(), json!(pc_width));
        storage.data.insert(
            "confidence_bits".to_string(),
            json!(self.spec.confidence_bits as i64),
        );
        storage.data.insert(
            "associativity".to_string(),
            json!(self.spec.associativity as i64),
        );
        storage
            .data
            .insert("btb_component".to_string(), json!(true));
        storage.data.insert("dual_port".to_string(), json!(true));
        storage.is_uarch_state = true;
        storage.uarch_time = Some(0);
        self.graph.add_node(storage);
        self.btb_node_ids
            .insert("btb_storage".to_string(), format!("{}_storage", btb));

        // Helper to create a simple var node
        let make_var = |name: &str, width: i64, time: Option<i64>| -> Node {
            let mut n = Node::with_defaults(Some(name.to_string()));
            n.data.insert("type".to_string(), json!("var"));
            n.data.insert("name".to_string(), json!(name));
            n.data.insert("bit_width".to_string(), json!(width));
            n.data.insert("btb_component".to_string(), json!(true));
            n.data.insert("btb_output".to_string(), json!(true));
            n.uarch_time = time;
            n
        };

        // BTB output signals
        self.graph.add_node(make_var(
            &format!("{}_hit", btb),
            1,
            Some(0),
        ));
        self.btb_node_ids
            .insert("btb_hit".to_string(), format!("{}_hit", btb));

        self.graph.add_node(make_var(
            &format!("{}_predicted_target", btb),
            pc_width,
            Some(0),
        ));
        self.btb_node_ids.insert(
            "btb_predicted_target".to_string(),
            format!("{}_predicted_target", btb),
        );

        self.graph.add_node(make_var(
            &format!("{}_predicted_taken", btb),
            1,
            Some(0),
        ));
        self.btb_node_ids.insert(
            "btb_predicted_taken".to_string(),
            format!("{}_predicted_taken", btb),
        );

        // BTB use signal (not btb_output)
        let mut use_node = Node::with_defaults(Some(format!("{}_use", btb)));
        use_node.data.insert("type".to_string(), json!("var"));
        use_node
            .data
            .insert("name".to_string(), json!(format!("{}_use", btb)));
        use_node.data.insert("bit_width".to_string(), json!(1));
        use_node
            .data
            .insert("btb_component".to_string(), json!(true));
        use_node.uarch_time = Some(0);
        self.graph.add_node(use_node);
        self.btb_node_ids
            .insert("btb_use".to_string(), format!("{}_use", btb));

        // Update enable (Execute stage)
        let mut update_en = Node::with_defaults(Some(format!("{}_update_enable", btb)));
        update_en.data.insert("type".to_string(), json!("var"));
        update_en.data.insert(
            "name".to_string(),
            json!(format!("{}_update_enable", btb)),
        );
        update_en.data.insert("bit_width".to_string(), json!(1));
        update_en
            .data
            .insert("btb_component".to_string(), json!(true));
        update_en.uarch_time = Some(execute_stage);
        self.graph.add_node(update_en);
        self.btb_node_ids.insert(
            "btb_update_enable".to_string(),
            format!("{}_update_enable", btb),
        );

        // Misprediction signal (Execute stage)
        let mut mispredict = Node::with_defaults(Some(format!("{}_mispredict", btb)));
        mispredict.data.insert("type".to_string(), json!("var"));
        mispredict.data.insert(
            "name".to_string(),
            json!(format!("{}_mispredict", btb)),
        );
        mispredict.data.insert("bit_width".to_string(), json!(1));
        mispredict
            .data
            .insert("btb_component".to_string(), json!(true));
        mispredict.uarch_time = Some(execute_stage);
        self.graph.add_node(mispredict);
        self.btb_node_ids
            .insert("btb_mispredict".to_string(), format!("{}_mispredict", btb));

        // Execute-stage outputs (dual-port lookup)
        let mut exec_hit = Node::with_defaults(Some(format!("{}_execute_hit", btb)));
        exec_hit.data.insert("type".to_string(), json!("var"));
        exec_hit.data.insert(
            "name".to_string(),
            json!(format!("{}_execute_hit", btb)),
        );
        exec_hit.data.insert("bit_width".to_string(), json!(1));
        exec_hit
            .data
            .insert("btb_component".to_string(), json!(true));
        exec_hit
            .data
            .insert("btb_output".to_string(), json!(true));
        exec_hit.uarch_time = Some(execute_stage);
        self.graph.add_node(exec_hit);
        self.btb_node_ids
            .insert("execute_hit".to_string(), format!("{}_execute_hit", btb));

        let mut exec_taken = Node::with_defaults(Some(format!(
            "{}_execute_predicted_taken",
            btb
        )));
        exec_taken.data.insert("type".to_string(), json!("var"));
        exec_taken.data.insert(
            "name".to_string(),
            json!(format!("{}_execute_predicted_taken", btb)),
        );
        exec_taken.data.insert("bit_width".to_string(), json!(1));
        exec_taken
            .data
            .insert("btb_component".to_string(), json!(true));
        exec_taken
            .data
            .insert("btb_output".to_string(), json!(true));
        exec_taken.uarch_time = Some(execute_stage);
        self.graph.add_node(exec_taken);
        self.btb_node_ids.insert(
            "execute_predicted_taken".to_string(),
            format!("{}_execute_predicted_taken", btb),
        );
    }

    // ----- Phase 4: Hardware -----
    fn generate_hardware(&mut self, _params: &HashMap<String, serde_json::Value>) {
        let btb = self.spec.btb_name.clone();
        let storage_id = self.btb_node_ids["btb_storage"].clone();
        let hit_id = self.btb_node_ids["btb_hit"].clone();
        let target_id = self.btb_node_ids["btb_predicted_target"].clone();
        let taken_id = self.btb_node_ids["btb_predicted_taken"].clone();
        let use_id = self.btb_node_ids["btb_use"].clone();
        let update_en_id = self.btb_node_ids["btb_update_enable"].clone();

        // Connect fetch_pc -> BTB storage (lookup)
        let mut lookup_edge = make_edge(&self.spec.fetch_pc_node, &storage_id);
        lookup_edge
            .data
            .insert("type".to_string(), json!("btb_lookup"));
        self.graph.add_edge(lookup_edge);

        // BTB storage -> outputs
        for (target, edge_type) in &[
            (&hit_id, "btb_hit_output"),
            (&target_id, "btb_target_output"),
            (&taken_id, "btb_taken_output"),
        ] {
            let mut e = make_edge(&storage_id, target);
            e.data.insert("type".to_string(), json!(edge_type));
            self.graph.add_edge(e);
        }

        // btb_use = hit && predicted_taken [&& !ras_pop]
        let hit_and_taken_id = format!("{}_hit_and_taken", btb);
        let mut hit_and_taken = Node::with_defaults(Some(hit_and_taken_id.clone()));
        hit_and_taken
            .data
            .insert("type".to_string(), json!("operation"));
        hit_and_taken
            .data
            .insert("operator".to_string(), json!("&&"));
        hit_and_taken
            .data
            .insert("name".to_string(), json!(&hit_and_taken_id));
        hit_and_taken.data.insert("bit_width".to_string(), json!(1));
        hit_and_taken
            .data
            .insert("btb_component".to_string(), json!(true));
        self.graph.add_node(hit_and_taken);
        let mut e1 = make_edge(&hit_id, &hit_and_taken_id);
        e1.data.insert("type".to_string(), json!("operand"));
        e1.data.insert("position".to_string(), json!("left"));
        self.graph.add_edge(e1);
        let mut e2 = make_edge(&taken_id, &hit_and_taken_id);
        e2.data.insert("type".to_string(), json!("operand"));
        e2.data.insert("position".to_string(), json!("right"));
        self.graph.add_edge(e2);

        let use_driver = if self.spec.has_ras_coordination() {
            let ras_pop_id = self.spec.ras_pop_node_id.as_ref().unwrap().clone();
            // Create !ras_pop
            let not_ras_id = format!("{}_ras_pop_not", btb);
            let mut not_ras = Node::with_defaults(Some(not_ras_id.clone()));
            not_ras
                .data
                .insert("type".to_string(), json!("operation"));
            not_ras.data.insert("operator".to_string(), json!("!"));
            not_ras
                .data
                .insert("name".to_string(), json!(&not_ras_id));
            not_ras.data.insert("bit_width".to_string(), json!(1));
            not_ras
                .data
                .insert("btb_component".to_string(), json!(true));
            self.graph.add_node(not_ras);
            let mut e = make_edge(&ras_pop_id, &not_ras_id);
            e.data.insert("type".to_string(), json!("operand"));
            self.graph.add_edge(e);

            // hit_and_taken && !ras_pop
            let use_logic_id = format!("{}_use_logic", btb);
            let mut use_logic = Node::with_defaults(Some(use_logic_id.clone()));
            use_logic
                .data
                .insert("type".to_string(), json!("operation"));
            use_logic
                .data
                .insert("operator".to_string(), json!("&&"));
            use_logic
                .data
                .insert("name".to_string(), json!(&use_logic_id));
            use_logic.data.insert("bit_width".to_string(), json!(1));
            use_logic
                .data
                .insert("btb_component".to_string(), json!(true));
            self.graph.add_node(use_logic);
            let mut e1 = make_edge(&hit_and_taken_id, &use_logic_id);
            e1.data.insert("type".to_string(), json!("operand"));
            e1.data.insert("position".to_string(), json!("left"));
            self.graph.add_edge(e1);
            let mut e2 = make_edge(&not_ras_id, &use_logic_id);
            e2.data.insert("type".to_string(), json!("operand"));
            e2.data.insert("position".to_string(), json!("right"));
            self.graph.add_edge(e2);
            use_logic_id
        } else {
            hit_and_taken_id.clone()
        };

        let mut e = make_edge(&use_driver, &use_id);
        e.data.insert("type".to_string(), json!("assignment"));
        self.graph.add_edge(e);

        // Update enable = OR of all branch enables
        let enable_nodes = self.spec.branch_enable_nodes.clone();
        if enable_nodes.len() == 1 {
            let mut e = make_edge(&enable_nodes[0], &update_en_id);
            e.data.insert("type".to_string(), json!("assignment"));
            self.graph.add_edge(e);
        } else {
            let mut or_result = enable_nodes[0].clone();
            for (i, enable) in enable_nodes[1..].iter().enumerate() {
                let or_id = format!("{}_update_or_{}", btb, i + 1);
                let mut or_node = Node::with_defaults(Some(or_id.clone()));
                or_node
                    .data
                    .insert("type".to_string(), json!("operation"));
                or_node
                    .data
                    .insert("operator".to_string(), json!("||"));
                or_node.data.insert("name".to_string(), json!(&or_id));
                or_node.data.insert("bit_width".to_string(), json!(1));
                or_node
                    .data
                    .insert("btb_component".to_string(), json!(true));
                self.graph.add_node(or_node);
                let mut e1 = make_edge(&or_result, &or_id);
                e1.data.insert("type".to_string(), json!("operand"));
                e1.data.insert("position".to_string(), json!("left"));
                self.graph.add_edge(e1);
                let mut e2 = make_edge(enable, &or_id);
                e2.data.insert("type".to_string(), json!("operand"));
                e2.data.insert("position".to_string(), json!("right"));
                self.graph.add_edge(e2);
                or_result = or_id;
            }
            let mut e = make_edge(&or_result, &update_en_id);
            e.data.insert("type".to_string(), json!("assignment"));
            self.graph.add_edge(e);
        }

        // Connect update interface to BTB storage
        for (src, edge_type) in &[
            (&self.spec.branch_pc_node, "btb_update_pc"),
            (&self.spec.branch_target_node, "btb_update_target"),
            (&self.spec.branch_outcome_node, "btb_update_taken"),
        ] {
            let mut e = make_edge(src, &storage_id);
            e.data.insert("type".to_string(), json!(edge_type));
            self.graph.add_edge(e);
        }
        let update_en_id_clone = update_en_id.clone();
        let mut e = make_edge(&update_en_id_clone, &storage_id);
        e.data
            .insert("type".to_string(), json!("btb_update_enable"));
        self.graph.add_edge(e);

        // Connect Execute-stage PC to BTB for dual-port lookup
        let execute_pc_id = "PIPE_Execute_PIPE_Decode_pc_rd_PIPE_PIPE".to_string();
        if self.graph.nodes.contains_key(&execute_pc_id) {
            let mut e = make_edge(&execute_pc_id, &storage_id);
            e.data
                .insert("type".to_string(), json!("btb_execute_lookup"));
            self.graph.add_edge(e);
        }

        // Connect BTB storage to execute outputs
        let exec_hit_id = self.btb_node_ids["execute_hit"].clone();
        let exec_taken_id = self.btb_node_ids["execute_predicted_taken"].clone();
        let mut e1 = make_edge(&storage_id, &exec_hit_id);
        e1.data
            .insert("type".to_string(), json!("btb_execute_hit_output"));
        self.graph.add_edge(e1);
        let mut e2 = make_edge(&storage_id, &exec_taken_id);
        e2.data
            .insert("type".to_string(), json!("btb_execute_taken_output"));
        self.graph.add_edge(e2);

        // Create execute_btb_use = execute_hit && execute_predicted_taken
        let exec_use_id = format!("{}_execute_btb_use", btb);
        let mut exec_use = Node::with_defaults(Some(exec_use_id.clone()));
        exec_use
            .data
            .insert("type".to_string(), json!("operation"));
        exec_use.data.insert("operator".to_string(), json!("&&"));
        exec_use
            .data
            .insert("name".to_string(), json!(&exec_use_id));
        exec_use.data.insert("bit_width".to_string(), json!(1));
        exec_use
            .data
            .insert("btb_component".to_string(), json!(true));
        self.graph.add_node(exec_use);
        let mut e1 = make_edge(&exec_hit_id, &exec_use_id);
        e1.data.insert("type".to_string(), json!("operand"));
        e1.data.insert("position".to_string(), json!("left"));
        self.graph.add_edge(e1);
        let mut e2 = make_edge(&exec_taken_id, &exec_use_id);
        e2.data.insert("type".to_string(), json!("operand"));
        e2.data.insert("position".to_string(), json!("right"));
        self.graph.add_edge(e2);

        // Create !branch_outcome
        let branch_not_taken_id = format!("{}_branch_not_taken", btb);
        let mut bnt = Node::with_defaults(Some(branch_not_taken_id.clone()));
        bnt.data.insert("type".to_string(), json!("operation"));
        bnt.data.insert("operator".to_string(), json!("!"));
        bnt.data
            .insert("name".to_string(), json!(&branch_not_taken_id));
        bnt.data.insert("bit_width".to_string(), json!(1));
        bnt.data.insert("btb_component".to_string(), json!(true));
        self.graph.add_node(bnt);
        let outcome_node = self.spec.branch_outcome_node.clone();
        let mut e = make_edge(&outcome_node, &branch_not_taken_id);
        e.data.insert("type".to_string(), json!("operand"));
        self.graph.add_edge(e);

        // Misprediction = execute_btb_use && !branch_taken
        let mispredict_and_id = format!("{}_mispredict_and", btb);
        let mut mp = Node::with_defaults(Some(mispredict_and_id.clone()));
        mp.data.insert("type".to_string(), json!("operation"));
        mp.data.insert("operator".to_string(), json!("&&"));
        mp.data
            .insert("name".to_string(), json!(&mispredict_and_id));
        mp.data.insert("bit_width".to_string(), json!(1));
        mp.data.insert("btb_component".to_string(), json!(true));
        self.graph.add_node(mp);
        let mut e1 = make_edge(&exec_use_id, &mispredict_and_id);
        e1.data.insert("type".to_string(), json!("operand"));
        e1.data.insert("position".to_string(), json!("left"));
        self.graph.add_edge(e1);
        let mut e2 = make_edge(&branch_not_taken_id, &mispredict_and_id);
        e2.data.insert("type".to_string(), json!("operand"));
        e2.data.insert("position".to_string(), json!("right"));
        self.graph.add_edge(e2);

        // Gate by Execute validity if available
        let mispredict_id = self.btb_node_ids["btb_mispredict"].clone();
        let execute_valid = "PIPE_Execute_valid_PIPE".to_string();
        if self.graph.nodes.contains_key(&execute_valid) {
            let gated_id = format!("{}_mispredict_valid_gated", btb);
            let mut gated = Node::with_defaults(Some(gated_id.clone()));
            gated
                .data
                .insert("type".to_string(), json!("operation"));
            gated.data.insert("operator".to_string(), json!("&&"));
            gated.data.insert("name".to_string(), json!(&gated_id));
            gated.data.insert("bit_width".to_string(), json!(1));
            gated
                .data
                .insert("btb_component".to_string(), json!(true));
            self.graph.add_node(gated);
            let mut e1 = make_edge(&mispredict_and_id, &gated_id);
            e1.data.insert("type".to_string(), json!("operand"));
            e1.data.insert("position".to_string(), json!("left"));
            self.graph.add_edge(e1);
            let mut e2 = make_edge(&execute_valid, &gated_id);
            e2.data.insert("type".to_string(), json!("operand"));
            e2.data.insert("position".to_string(), json!("right"));
            self.graph.add_edge(e2);

            let mut e = make_edge(&gated_id, &mispredict_id);
            e.data.insert("type".to_string(), json!("assignment"));
            self.graph.add_edge(e);
        } else {
            let mut e = make_edge(&mispredict_and_id, &mispredict_id);
            e.data.insert("type".to_string(), json!("assignment"));
            self.graph.add_edge(e);
        }
    }

    // ----- Phase 5: Connection -----
    fn wire_components(&mut self, params: &HashMap<String, serde_json::Value>) {
        let btb = self.spec.btb_name.clone();
        let pc_width = self.spec.pc_width as i64;
        let use_id = self.btb_node_ids["btb_use"].clone();
        let target_id = self.btb_node_ids["btb_predicted_target"].clone();
        let mispredict_id = self.btb_node_ids["btb_mispredict"].clone();
        let exec_use_id = format!("{}_execute_btb_use", btb);
        let execute_stage = params["execute_stage"].as_i64().unwrap_or(1);

        // Integrate misprediction with control_hazard_flush
        let flush_id = self.spec.control_hazard_flush_node_id.clone();
        let incoming: Vec<_> = self
            .graph
            .edges
            .values()
            .filter(|e| {
                e.target == flush_id
                    && e.data
                        .get("type")
                        .and_then(|v| v.as_str())
                        .map_or(false, |t| t.contains("operand"))
            })
            .map(|e| (e.id.clone(), e.source.clone()))
            .collect();

        let source_ids: Vec<_> = incoming.iter().map(|(_, s)| s.clone()).collect();
        for (edge_id, _) in &incoming {
            self.graph.remove_edge(edge_id);
        }

        if !source_ids.is_empty() {
            // Combine existing sources
            let existing_combined = if source_ids.len() == 1 {
                source_ids[0].clone()
            } else {
                let mut result = source_ids[0].clone();
                for (i, source) in source_ids[1..].iter().enumerate() {
                    let or_id = format!("{}_existing_or_{}", btb, i + 1);
                    let mut or_node = Node::with_defaults(Some(or_id.clone()));
                    or_node
                        .data
                        .insert("type".to_string(), json!("operation"));
                    or_node
                        .data
                        .insert("operator".to_string(), json!("||"));
                    or_node
                        .data
                        .insert("name".to_string(), json!(&or_id));
                    or_node.data.insert("bit_width".to_string(), json!(1));
                    or_node
                        .data
                        .insert("btb_component".to_string(), json!(true));
                    or_node.uarch_time = Some(execute_stage);
                    self.graph.add_node(or_node);
                    let mut e1 = make_edge(&result, &or_id);
                    e1.data.insert("type".to_string(), json!("operand"));
                    e1.data.insert("position".to_string(), json!("left"));
                    self.graph.add_edge(e1);
                    let mut e2 = make_edge(source, &or_id);
                    e2.data.insert("type".to_string(), json!("operand"));
                    e2.data.insert("position".to_string(), json!("right"));
                    self.graph.add_edge(e2);
                    result = or_id;
                }
                result
            };

            // Create !execute_btb_use
            let not_exec_use_id = format!("{}_execute_btb_use_not", btb);
            let mut not_node = Node::with_defaults(Some(not_exec_use_id.clone()));
            not_node
                .data
                .insert("type".to_string(), json!("operation"));
            not_node.data.insert("operator".to_string(), json!("!"));
            not_node
                .data
                .insert("name".to_string(), json!(&not_exec_use_id));
            not_node.data.insert("bit_width".to_string(), json!(1));
            not_node
                .data
                .insert("btb_component".to_string(), json!(true));
            not_node.uarch_time = Some(execute_stage);
            self.graph.add_node(not_node);
            let mut e = make_edge(&exec_use_id, &not_exec_use_id);
            e.data.insert("type".to_string(), json!("operand"));
            self.graph.add_edge(e);

            // Gate existing with !execute_btb_use
            let gated_id = format!("{}_existing_flush_gated", btb);
            let mut gated = Node::with_defaults(Some(gated_id.clone()));
            gated
                .data
                .insert("type".to_string(), json!("operation"));
            gated.data.insert("operator".to_string(), json!("&&"));
            gated.data.insert("name".to_string(), json!(&gated_id));
            gated.data.insert("bit_width".to_string(), json!(1));
            gated
                .data
                .insert("btb_component".to_string(), json!(true));
            gated.uarch_time = Some(execute_stage);
            self.graph.add_node(gated);
            let mut e1 = make_edge(&existing_combined, &gated_id);
            e1.data.insert("type".to_string(), json!("operand"));
            e1.data.insert("position".to_string(), json!("left"));
            self.graph.add_edge(e1);
            let mut e2 = make_edge(&not_exec_use_id, &gated_id);
            e2.data.insert("type".to_string(), json!("operand"));
            e2.data.insert("position".to_string(), json!("right"));
            self.graph.add_edge(e2);

            // Connect to flush
            let mut e1 = make_edge(&gated_id, &flush_id);
            e1.data.insert("type".to_string(), json!("operand"));
            e1.data.insert("position".to_string(), json!("left"));
            self.graph.add_edge(e1);
            let mut e2 = make_edge(&mispredict_id, &flush_id);
            e2.data.insert("type".to_string(), json!("operand"));
            e2.data.insert("position".to_string(), json!("right"));
            self.graph.add_edge(e2);
        } else {
            let mut e = make_edge(&mispredict_id, &flush_id);
            e.data.insert("type".to_string(), json!("operand"));
            self.graph.add_edge(e);
        }

        // BTB recovery path
        let pc_recovery_mux = "pc_recovery_mux".to_string();
        let execute_pc_add_4 = "PIPE_Execute_PIPE_Decode_pc_add_4_PIPE_PIPE".to_string();
        if self.graph.nodes.contains_key(&pc_recovery_mux)
            && self.graph.nodes.contains_key(&execute_pc_add_4)
        {
            // Find old target of pc_recovery_mux
            let old_target: Option<String> = self
                .graph
                .edges
                .values()
                .find(|e| e.source == pc_recovery_mux)
                .map(|e| e.target.clone());

            if let Some(old_target_id) = old_target {
                // Remove old edges from pc_recovery_mux
                let to_remove: Vec<_> = self
                    .graph
                    .edges
                    .values()
                    .filter(|e| e.source == pc_recovery_mux)
                    .map(|e| e.id.clone())
                    .collect();
                for eid in to_remove {
                    self.graph.remove_edge(&eid);
                }

                // Create btb_recovery_mux = btb_mispredict ? execute_pc_add_4 : pc_recovery_mux
                let recovery_id = format!("{}_recovery_mux", btb);
                let mut recovery = Node::with_defaults(Some(recovery_id.clone()));
                recovery
                    .data
                    .insert("type".to_string(), json!("ternary_op"));
                recovery
                    .data
                    .insert("name".to_string(), json!(&recovery_id));
                recovery
                    .data
                    .insert("bit_width".to_string(), json!(pc_width));
                recovery
                    .data
                    .insert("btb_component".to_string(), json!(true));
                recovery.uarch_time = Some(0);
                self.graph.add_node(recovery);

                let mut e = make_edge(&mispredict_id, &recovery_id);
                e.data
                    .insert("type".to_string(), json!("ternary_condition"));
                self.graph.add_edge(e);
                let mut e = make_edge(&execute_pc_add_4, &recovery_id);
                e.data.insert("type".to_string(), json!("ternary_true"));
                self.graph.add_edge(e);
                let mut e = make_edge(&pc_recovery_mux, &recovery_id);
                e.data
                    .insert("type".to_string(), json!("ternary_false"));
                self.graph.add_edge(e);
                let mut e = make_edge(&recovery_id, &old_target_id);
                e.data.insert("type".to_string(), json!("assignment"));
                self.graph.add_edge(e);
            }
        }

        // Prediction mux: btb_use ? btb_target : default_prediction
        let btb_or_default_id = format!("{}_or_default", btb);
        let mut btb_or_default = Node::with_defaults(Some(btb_or_default_id.clone()));
        btb_or_default
            .data
            .insert("type".to_string(), json!("ternary_op"));
        btb_or_default
            .data
            .insert("name".to_string(), json!(&btb_or_default_id));
        btb_or_default
            .data
            .insert("bit_width".to_string(), json!(pc_width));
        btb_or_default
            .data
            .insert("btb_component".to_string(), json!(true));
        self.graph.add_node(btb_or_default);

        let mut e = make_edge(&use_id, &btb_or_default_id);
        e.data
            .insert("type".to_string(), json!("ternary_condition"));
        self.graph.add_edge(e);
        let mut e = make_edge(&target_id, &btb_or_default_id);
        e.data.insert("type".to_string(), json!("ternary_true"));
        self.graph.add_edge(e);
        let default_pred = self.spec.default_prediction_node_id.clone();
        let mut e = make_edge(&default_pred, &btb_or_default_id);
        e.data
            .insert("type".to_string(), json!("ternary_false"));
        self.graph.add_edge(e);

        // Replace predicted_pc driver
        let predicted_pc = self.spec.predicted_pc_node_id.clone();
        let new_driver = if self.spec.has_ras_coordination() {
            let ras_pop = self.spec.ras_pop_node_id.as_ref().unwrap().clone();
            let ras_top = self.spec.ras_top_node_id.as_ref().unwrap().clone();

            let priority_id = format!("{}_ras_priority_mux", btb);
            let mut priority = Node::with_defaults(Some(priority_id.clone()));
            priority
                .data
                .insert("type".to_string(), json!("ternary_op"));
            priority
                .data
                .insert("name".to_string(), json!(&priority_id));
            priority
                .data
                .insert("bit_width".to_string(), json!(pc_width));
            priority
                .data
                .insert("btb_component".to_string(), json!(true));
            self.graph.add_node(priority);

            let mut e = make_edge(&ras_pop, &priority_id);
            e.data
                .insert("type".to_string(), json!("ternary_condition"));
            self.graph.add_edge(e);
            let mut e = make_edge(&ras_top, &priority_id);
            e.data.insert("type".to_string(), json!("ternary_true"));
            self.graph.add_edge(e);
            let mut e = make_edge(&btb_or_default_id, &priority_id);
            e.data
                .insert("type".to_string(), json!("ternary_false"));
            self.graph.add_edge(e);
            priority_id
        } else {
            btb_or_default_id
        };

        // Remove old predicted_pc driver
        let to_remove: Vec<_> = self
            .graph
            .edges
            .values()
            .filter(|e| {
                e.target == predicted_pc
                    && e.data
                        .get("type")
                        .and_then(|v| v.as_str())
                        .map_or(false, |t| {
                            t == "assignment" || t == "ternary_result"
                        })
            })
            .map(|e| e.id.clone())
            .collect();
        for eid in to_remove {
            self.graph.remove_edge(&eid);
        }
        let mut e = make_edge(&new_driver, &predicted_pc);
        e.data.insert("type".to_string(), json!("assignment"));
        self.graph.add_edge(e);
    }
}

// ---------------------------------------------------------------------------
// Standalone function
// ---------------------------------------------------------------------------

/// Apply BTB optimization to a ResourceGraph.
pub fn apply_branch_target_buffer(graph: &mut ResourceGraph, spec: BTBSpec) -> bool {
    let mut btb = BTBOptimization::new(graph, spec);
    btb.apply()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_btb_test_graph() -> ResourceGraph {
        let mut graph = ResourceGraph::new();

        // Fetch-stage nodes
        let mut pc = Node::with_defaults(Some("pc_rd".to_string()));
        pc.data.insert("type".to_string(), json!("var"));
        pc.data.insert("bit_width".to_string(), json!(32));
        pc.uarch_time = Some(0);
        graph.add_node(pc);

        let mut pc_add_4 = Node::with_defaults(Some("pc_add_4".to_string()));
        pc_add_4.data.insert("type".to_string(), json!("var"));
        pc_add_4.data.insert("bit_width".to_string(), json!(32));
        pc_add_4.uarch_time = Some(0);
        graph.add_node(pc_add_4);

        let mut predicted_pc = Node::with_defaults(Some("predicted_pc".to_string()));
        predicted_pc.data.insert("type".to_string(), json!("var"));
        predicted_pc
            .data
            .insert("bit_width".to_string(), json!(32));
        predicted_pc.uarch_time = Some(0);
        graph.add_node(predicted_pc);

        // Execute-stage nodes
        let mut branch_taken = Node::with_defaults(Some("branch_taken".to_string()));
        branch_taken
            .data
            .insert("type".to_string(), json!("var"));
        branch_taken.data.insert("bit_width".to_string(), json!(1));
        branch_taken.uarch_time = Some(2);
        graph.add_node(branch_taken);

        let mut branch_target = Node::with_defaults(Some("branch_target".to_string()));
        branch_target
            .data
            .insert("type".to_string(), json!("var"));
        branch_target
            .data
            .insert("bit_width".to_string(), json!(32));
        branch_target.uarch_time = Some(2);
        graph.add_node(branch_target);

        let mut branch_pc = Node::with_defaults(Some("branch_pc_execute".to_string()));
        branch_pc.data.insert("type".to_string(), json!("var"));
        branch_pc.data.insert("bit_width".to_string(), json!(32));
        branch_pc.uarch_time = Some(2);
        graph.add_node(branch_pc);

        // Branch enables
        for name in &["beq_enable", "bne_enable", "jal_enable"] {
            let mut n = Node::with_defaults(Some(name.to_string()));
            n.data.insert("type".to_string(), json!("var"));
            n.data.insert("bit_width".to_string(), json!(1));
            n.uarch_time = Some(2);
            graph.add_node(n);
        }

        // Control hazard flush
        let mut flush = Node::with_defaults(Some("control_hazard_flush".to_string()));
        flush.data.insert("type".to_string(), json!("operation"));
        flush.data.insert("operator".to_string(), json!("||"));
        flush.data.insert("bit_width".to_string(), json!(1));
        flush.uarch_time = Some(2);
        graph.add_node(flush);

        // Connect pc_add_4 to predicted_pc
        let mut e = make_edge("pc_add_4", "predicted_pc");
        e.data.insert("type".to_string(), json!("assignment"));
        graph.add_edge(e);

        graph
    }

    #[test]
    fn test_btb_spec_validation() {
        let spec = BTBSpec::new(
            vec!["beq_enable".to_string()],
            "branch_taken",
            "branch_target",
            "pc_rd",
            "branch_pc_execute",
            "predicted_pc",
            "pc_add_4",
            "control_hazard_flush",
        )
        .unwrap();
        assert!(spec.validate().is_ok());
    }

    #[test]
    fn test_btb_spec_validation_bad_entries() {
        let mut spec = BTBSpec::new(
            vec!["beq_enable".to_string()],
            "branch_taken",
            "branch_target",
            "pc_rd",
            "branch_pc_execute",
            "predicted_pc",
            "pc_add_4",
            "control_hazard_flush",
        )
        .unwrap();
        spec.num_entries = 13;
        assert!(spec.validate().is_err());
    }

    #[test]
    fn test_btb_spec_empty_enables() {
        let result = BTBSpec::new(
            vec![],
            "branch_taken",
            "branch_target",
            "pc_rd",
            "branch_pc_execute",
            "predicted_pc",
            "pc_add_4",
            "control_hazard_flush",
        );
        assert!(result.is_err());
    }

    #[test]
    fn test_btb_index_tag_width() {
        let spec = BTBSpec::new(
            vec!["beq_enable".to_string()],
            "b", "b", "b", "b", "b", "b", "b",
        )
        .unwrap();
        // 64 entries, 1-way = 64 sets, index = 6 bits, tag = 32 - 6 - 2 = 24
        assert_eq!(spec.index_width(), 6);
        assert_eq!(spec.tag_width(), 24);
    }

    #[test]
    fn test_apply_btb_full() {
        let mut graph = make_btb_test_graph();
        let spec = BTBSpec::new(
            vec![
                "beq_enable".to_string(),
                "bne_enable".to_string(),
                "jal_enable".to_string(),
            ],
            "branch_taken",
            "branch_target",
            "pc_rd",
            "branch_pc_execute",
            "predicted_pc",
            "pc_add_4",
            "control_hazard_flush",
        )
        .unwrap();

        let result = apply_branch_target_buffer(&mut graph, spec);
        assert!(result);

        // Verify BTB nodes were created
        assert!(graph.nodes.contains_key("btb_storage"));
        assert!(graph.nodes.contains_key("btb_hit"));
        assert!(graph.nodes.contains_key("btb_predicted_target"));
        assert!(graph.nodes.contains_key("btb_predicted_taken"));
        assert!(graph.nodes.contains_key("btb_use"));
        assert!(graph.nodes.contains_key("btb_update_enable"));
        assert!(graph.nodes.contains_key("btb_mispredict"));
        assert!(graph.nodes.contains_key("btb_execute_hit"));
        assert!(graph.nodes.contains_key("btb_execute_predicted_taken"));

        // Verify BTB storage is uarch state
        let storage = &graph.nodes["btb_storage"];
        assert!(storage.is_uarch_state);
        assert_eq!(
            storage
                .data
                .get("type")
                .and_then(|v| v.as_str()),
            Some("btb_storage")
        );

        // Verify prediction mux was created
        assert!(graph.nodes.contains_key("btb_or_default"));
    }

    #[test]
    fn test_btb_analyze_missing_node() {
        let mut graph = ResourceGraph::new();
        let spec = BTBSpec::new(
            vec!["missing_enable".to_string()],
            "branch_taken",
            "branch_target",
            "pc_rd",
            "branch_pc",
            "predicted_pc",
            "pc_add_4",
            "control_hazard_flush",
        )
        .unwrap();

        let result = apply_branch_target_buffer(&mut graph, spec);
        assert!(!result);
    }

    #[test]
    fn test_btb_with_ras_coordination() {
        let mut graph = make_btb_test_graph();

        // Add RAS nodes
        let mut ras_pop = Node::with_defaults(Some("ras_pop".to_string()));
        ras_pop.data.insert("type".to_string(), json!("var"));
        ras_pop.data.insert("bit_width".to_string(), json!(1));
        graph.add_node(ras_pop);

        let mut ras_top = Node::with_defaults(Some("ras_top".to_string()));
        ras_top.data.insert("type".to_string(), json!("var"));
        ras_top.data.insert("bit_width".to_string(), json!(32));
        graph.add_node(ras_top);

        let mut spec = BTBSpec::new(
            vec!["beq_enable".to_string()],
            "branch_taken",
            "branch_target",
            "pc_rd",
            "branch_pc_execute",
            "predicted_pc",
            "pc_add_4",
            "control_hazard_flush",
        )
        .unwrap();
        spec.ras_pop_node_id = Some("ras_pop".to_string());
        spec.ras_top_node_id = Some("ras_top".to_string());

        let result = apply_branch_target_buffer(&mut graph, spec);
        assert!(result);

        // Verify RAS priority mux
        assert!(graph.nodes.contains_key("btb_ras_priority_mux"));
        assert!(graph.nodes.contains_key("btb_ras_pop_not"));
    }
}
