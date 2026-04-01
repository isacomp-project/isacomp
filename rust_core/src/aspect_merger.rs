//! Aspect-Oriented Programming support for ISA specifications.
//!
//! This module handles loading, validating, and merging aspect files with base ISA graphs.

use std::collections::{HashMap, HashSet};
use std::path::Path;

use serde_json::Value;

use crate::isa_parser::ISAParser;
use crate::resource_graph::{Edge, Node, ResourceGraph};

// ---------------------------------------------------------------------------
// Helper: convert a serde_json::Value (used as a mini-map) into a
// HashMap<String, Value> suitable for Node/Edge data fields.
// ---------------------------------------------------------------------------

/// Convert a `serde_json::Value::Object` into `HashMap<String, Value>`.
/// If the value is not an object, returns an empty map.
fn value_to_data(v: Value) -> HashMap<String, Value> {
    match v {
        Value::Object(map) => map.into_iter().collect(),
        _ => HashMap::new(),
    }
}

/// Read a string field from a `HashMap<String, Value>` data map.
fn data_str<'a>(data: &'a HashMap<String, Value>, key: &str) -> &'a str {
    data.get(key)
        .and_then(|v| v.as_str())
        .unwrap_or("")
}

/// Read an i64 field from a data map with a default.
fn data_i64(data: &HashMap<String, Value>, key: &str, default: i64) -> i64 {
    data.get(key).and_then(|v| v.as_i64()).unwrap_or(default)
}

// ---------------------------------------------------------------------------
// AspectInfo
// ---------------------------------------------------------------------------

/// Metadata about a single loaded aspect.
#[derive(Debug, Clone)]
pub struct AspectInfo {
    /// States that this aspect has exclusive gated access to.
    pub gated_states: HashSet<String>,
    /// States with explicit priority annotations: state_name -> priority.
    pub prioritized_states: HashMap<String, i64>,
    /// Merge order (from the aspect declaration).
    pub order: usize,
    /// Resolved file path of the aspect.
    pub file: String,
    /// Node IDs that were added by this aspect.
    pub aspect_nodes: HashSet<String>,
}

// ---------------------------------------------------------------------------
// AspectMerger
// ---------------------------------------------------------------------------

/// Handles merging aspect files with base ISA specifications.
pub struct AspectMerger {
    /// The base ISA resource graph.
    pub base_graph: ResourceGraph,
    /// Path to the base `.isa` file (used to resolve relative aspect paths).
    pub base_file_path: Option<String>,
    /// Loaded aspect metadata, in declaration order.
    pub aspect_graphs: Vec<AspectInfo>,
}

impl AspectMerger {
    /// Create a new `AspectMerger`.
    pub fn new(base_graph: ResourceGraph, base_file_path: Option<String>) -> Self {
        AspectMerger {
            base_graph,
            base_file_path,
            aspect_graphs: Vec::new(),
        }
    }

    // =======================================================================
    // Main entry point
    // =======================================================================

    /// Load all declared aspects and merge them with the base graph.
    ///
    /// This is the main entry point for aspect processing.
    pub fn load_and_merge_aspects(&mut self) -> Result<(), String> {
        if self.base_graph.aspect_declarations.is_empty() {
            return Ok(());
        }

        // Clone declarations so we can iterate while mutating self.
        let declarations: Vec<Value> = self.base_graph.aspect_declarations.clone();

        // 1. Load all aspect files.
        for aspect_decl in &declarations {
            self.load_aspect(aspect_decl)?;
        }

        // 2. Validate priority consistency.
        self.validate_priority_consistency()?;

        // 3. Merge each aspect (mark edges with precedence, validate gating).
        let aspect_infos: Vec<AspectInfo> = self.aspect_graphs.clone();
        for aspect_info in &aspect_infos {
            self.merge_aspect(aspect_info)?;
        }

        // 4. Store gated_states metadata on graph.
        let mut all_gated_states: HashSet<String> = HashSet::new();
        for ai in &self.aspect_graphs {
            all_gated_states.extend(ai.gated_states.iter().cloned());
            all_gated_states.extend(ai.prioritized_states.keys().cloned());
        }
        if !all_gated_states.is_empty() {
            self.base_graph.gated_states = all_gated_states;
        }

        // 5. Create gated write multiplexers.
        self.create_gated_write_multiplexers();

        // 6. Merge prioritized writes.
        self.merge_prioritized_writes()?;

        Ok(())
    }

    // =======================================================================
    // load_aspect
    // =======================================================================

    /// Load and parse a single aspect file into the base graph.
    fn load_aspect(&mut self, aspect_decl: &Value) -> Result<(), String> {
        let aspect_file_raw = aspect_decl
            .get("file")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "Aspect declaration missing 'file' field".to_string())?
            .to_string();

        // Resolve relative path.
        let aspect_file = if let Some(ref base_path) = self.base_file_path {
            let p = Path::new(&aspect_file_raw);
            if p.is_absolute() {
                aspect_file_raw.clone()
            } else {
                let base_dir = Path::new(base_path)
                    .parent()
                    .unwrap_or_else(|| Path::new("."));
                base_dir
                    .join(&aspect_file_raw)
                    .to_string_lossy()
                    .to_string()
            }
        } else {
            aspect_file_raw.clone()
        };

        // Verify file exists.
        if !Path::new(&aspect_file).exists() {
            return Err(format!("Aspect file not found: {}", aspect_file));
        }

        // Snapshot node IDs before parsing.
        let nodes_before: HashSet<String> = self.base_graph.nodes.keys().cloned().collect();

        // Parse aspect file into the base graph (sharing namespace).
        let mut parser = ISAParser::new();
        parser.parse_file(&aspect_file, Some(&mut self.base_graph))?;

        // Determine which nodes were added by the aspect.
        let nodes_after: HashSet<String> = self.base_graph.nodes.keys().cloned().collect();
        let aspect_nodes: HashSet<String> =
            nodes_after.difference(&nodes_before).cloned().collect();

        // Mark new nodes with from_aspect metadata.
        for node_id in &aspect_nodes {
            if let Some(node) = self.base_graph.nodes.get_mut(node_id) {
                node.data.insert(
                    "from_aspect".to_string(),
                    Value::String(aspect_file.clone()),
                );
            }
        }

        // Parse gated_states from declaration.
        let gated_states: HashSet<String> = aspect_decl
            .get("gated_states")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();

        // Parse prioritized_states from declaration.
        let prioritized_states: HashMap<String, i64> = aspect_decl
            .get("prioritized_states")
            .and_then(|v| v.as_object())
            .map(|obj| {
                obj.iter()
                    .filter_map(|(k, v)| v.as_i64().map(|p| (k.clone(), p)))
                    .collect()
            })
            .unwrap_or_default();

        let order = aspect_decl
            .get("order")
            .and_then(|v| v.as_u64())
            .unwrap_or(0) as usize;

        self.aspect_graphs.push(AspectInfo {
            gated_states,
            prioritized_states,
            order,
            file: aspect_file,
            aspect_nodes,
        });

        Ok(())
    }

    // =======================================================================
    // merge_aspect
    // =======================================================================

    /// Process aspect metadata: mark assignment edges with precedence and
    /// validate that the aspect only writes to gated/prioritized states.
    fn merge_aspect(&mut self, aspect_info: &AspectInfo) -> Result<(), String> {
        let all_valid_states: HashSet<String> = aspect_info
            .gated_states
            .iter()
            .chain(aspect_info.prioritized_states.keys())
            .cloned()
            .collect();
        let aspect_file = &aspect_info.file;
        let precedence = (aspect_info.order as i64) + 1;

        // Collect edge IDs to update (to avoid borrow conflicts).
        struct EdgeUpdate {
            edge_id: String,
            aspect_file: String,
            is_assignment: bool,
            has_enable: bool,
            target_state: Option<String>,
        }

        let mut edge_updates: Vec<EdgeUpdate> = Vec::new();

        for node_id in &aspect_info.aspect_nodes {
            if let Some(node) = self.base_graph.nodes.get(node_id) {
                let outgoing: Vec<String> = node.outgoing_edges.iter().cloned().collect();
                for edge_id in &outgoing {
                    if let Some(edge) = self.base_graph.edges.get(edge_id) {
                        let etype = data_str(&edge.data, "type");
                        let is_assignment = etype == "assignment";
                        let has_enable = edge.data.contains_key("enable");

                        let target_state = if is_assignment {
                            self.get_state_name_from_node_id(&edge.target)
                        } else {
                            None
                        };

                        edge_updates.push(EdgeUpdate {
                            edge_id: edge_id.clone(),
                            aspect_file: aspect_file.clone(),
                            is_assignment,
                            has_enable,
                            target_state,
                        });
                    }
                }
            }
        }

        // Validate and apply updates.
        for eu in &edge_updates {
            if eu.is_assignment {
                if let Some(ref state_name) = eu.target_state {
                    if !all_valid_states.contains(state_name) && eu.has_enable {
                        return Err(format!(
                            "Aspect {} uses conditional assignment to '{}' \
                             but this state is not in the gates list. \
                             Conditional assignments must target gated states: {:?}",
                            eu.aspect_file, state_name, aspect_info.gated_states
                        ));
                    }
                }
            }
        }

        for eu in edge_updates {
            if let Some(edge) = self.base_graph.edges.get_mut(&eu.edge_id) {
                edge.data.insert(
                    "from_aspect".to_string(),
                    Value::String(eu.aspect_file),
                );
                if eu.is_assignment {
                    edge.data.insert(
                        "precedence".to_string(),
                        Value::Number(serde_json::Number::from(precedence)),
                    );
                }
            }
        }

        Ok(())
    }

    // =======================================================================
    // create_gated_write_multiplexers
    // =======================================================================

    /// Create multiplexer nodes for gated writes.
    ///
    /// When multiple assignments target the same state (base + aspects with
    /// conditions), create a priority multiplexer that combines them properly.
    fn create_gated_write_multiplexers(&mut self) {
        // Collect all gated states across all aspects.
        let mut all_gated_states: HashSet<String> = HashSet::new();
        for ai in &self.aspect_graphs {
            all_gated_states.extend(ai.gated_states.iter().cloned());
            all_gated_states.extend(ai.prioritized_states.keys().cloned());
        }
        if all_gated_states.is_empty() {
            return;
        }

        // Build explicit priority map: (state_name, aspect_file) -> priority_number.
        let mut explicit_priority_map: HashMap<(String, String), i64> = HashMap::new();
        for ai in &self.aspect_graphs {
            for (state_name, &priority) in &ai.prioritized_states {
                explicit_priority_map
                    .insert((state_name.clone(), ai.file.clone()), priority);
            }
        }

        log::debug!(
            "\nCreating multiplexers for {} gated states: {:?}",
            all_gated_states.len(),
            all_gated_states
        );

        // Sort for deterministic iteration.
        let mut sorted_states: Vec<String> = all_gated_states.into_iter().collect();
        sorted_states.sort();

        for state_name in &sorted_states {
            // Find target node for this state.
            let target_node_id = {
                let mut found: Option<String> = None;
                let mut sorted_nodes: Vec<(&String, &Node)> =
                    self.base_graph.nodes.iter().collect();
                sorted_nodes.sort_by_key(|(id, _)| (*id).clone());
                for (nid, node) in &sorted_nodes {
                    let ntype = data_str(&node.data, "type");
                    let nname = data_str(&node.data, "name");
                    if ntype.starts_with("isa_state") && nname == state_name.as_str() {
                        found = Some((*nid).clone());
                        break;
                    }
                }
                found
            };

            let target_node_id = match target_node_id {
                Some(id) => id,
                None => {
                    log::debug!(
                        "  Warning: Gated state '{}' not found in graph",
                        state_name
                    );
                    continue;
                }
            };

            // Collect assignment edges to target.
            // (source_id, edge_id, precedence, condition, from_aspect)
            let mut assignments: Vec<(String, String, i64, Option<Value>, Option<String>)> = {
                let target_node = match self.base_graph.nodes.get(&target_node_id) {
                    Some(n) => n,
                    None => continue,
                };
                let mut incoming: Vec<String> =
                    target_node.incoming_edges.iter().cloned().collect();
                incoming.sort();

                let mut result = Vec::new();
                for edge_id in &incoming {
                    if let Some(edge) = self.base_graph.edges.get(edge_id) {
                        let etype = data_str(&edge.data, "type");
                        if etype == "assignment" {
                            let prec = data_i64(&edge.data, "precedence", 0);
                            let condition = edge.data.get("enable").cloned();
                            let from_aspect = edge
                                .data
                                .get("from_aspect")
                                .and_then(|v| v.as_str())
                                .map(|s| s.to_string());
                            result.push((
                                edge.source.clone(),
                                edge_id.clone(),
                                prec,
                                condition,
                                from_aspect,
                            ));
                        }
                    }
                }
                result
            };

            if assignments.len() <= 1 {
                continue;
            }

            log::debug!(
                "\n  State '{}' has {} assignments:",
                state_name,
                assignments.len()
            );
            for (src_id, _eid, prec, cond, aspect) in &assignments {
                let cond_str = match cond {
                    Some(c) => format!("when ({})", c),
                    None => "unconditional".to_string(),
                };
                let aspect_str = match aspect {
                    Some(a) => format!("from {}", a),
                    None => "from base".to_string(),
                };
                log::debug!(
                    "    - {} [{}, precedence={}, {}]",
                    src_id, cond_str, prec, aspect_str
                );
            }

            // Check if this state has explicit priorities.
            let has_explicit_priorities = self.aspect_graphs.iter().any(|ai| {
                explicit_priority_map.contains_key(&(state_name.clone(), ai.file.clone()))
            });

            if has_explicit_priorities {
                // Sort by explicit priority: lower number = higher priority = first.
                assignments.sort_by(|a, b| {
                    let pri_a = explicit_priority_map
                        .get(&(state_name.clone(), a.4.clone().unwrap_or_default()))
                        .copied()
                        .unwrap_or(9999);
                    let pri_b = explicit_priority_map
                        .get(&(state_name.clone(), b.4.clone().unwrap_or_default()))
                        .copied()
                        .unwrap_or(9999);
                    pri_a.cmp(&pri_b).then_with(|| a.0.cmp(&b.0))
                });
            } else {
                // Sort by precedence descending, then source id.
                assignments.sort_by(|a, b| b.2.cmp(&a.2).then_with(|| a.0.cmp(&b.0)));
            }

            // Create multiplexer node.
            let mux_id = format!("{}_gated_mux", state_name);
            let mux_data = value_to_data(serde_json::json!({
                "type": "multiplexer",
                "name": mux_id,
                "display_name": mux_id,
                "select_type": "priority",
                "num_inputs": assignments.len(),
                "gated_write_mux": true,
            }));
            let mut mux_node = Node::with_defaults(Some(mux_id.clone()));
            mux_node.data = mux_data;
            self.base_graph.add_node(mux_node);
            log::debug!("    Created mux node: {}", mux_id);

            // Remove original assignment edges.
            let edge_ids_to_remove: Vec<String> =
                assignments.iter().map(|(_, eid, _, _, _)| eid.clone()).collect();
            for eid in &edge_ids_to_remove {
                self.base_graph.remove_edge(eid);
            }

            // Add mux inputs.
            for (i, (src_id, _eid, prec, cond, aspect)) in assignments.iter().enumerate() {
                let edge_type = if cond.is_some() {
                    "mux_input"
                } else {
                    "mux_default_input"
                };

                let mut input_data: HashMap<String, Value> = HashMap::new();
                input_data.insert("type".into(), Value::String(edge_type.into()));
                input_data.insert(
                    "input_index".into(),
                    Value::Number(serde_json::Number::from(i as i64)),
                );
                input_data.insert(
                    "original_precedence".into(),
                    Value::Number(serde_json::Number::from(*prec)),
                );
                if let Some(a) = aspect {
                    input_data.insert("from_aspect".into(), Value::String(a.clone()));
                } else {
                    input_data.insert("from_aspect".into(), Value::Null);
                }
                if let Some(c) = cond {
                    input_data.insert("original_enable".into(), c.clone());
                } else {
                    input_data.insert("original_enable".into(), Value::Null);
                }

                let input_edge = Edge::new(
                    src_id.clone(),
                    mux_id.clone(),
                    None,
                    Some(input_data),
                );
                self.base_graph.add_edge(input_edge);

                // Create select edge if there is a condition.
                if let Some(cond_val) = cond {
                    let cond_node_id =
                        self.get_or_create_condition_node(cond_val, i, src_id);
                    if let Some(ref cid) = cond_node_id {
                        let mut select_data: HashMap<String, Value> = HashMap::new();
                        select_data
                            .insert("type".into(), Value::String("mux_select".into()));
                        select_data.insert(
                            "select_index".into(),
                            Value::Number(serde_json::Number::from(i as i64)),
                        );
                        let select_edge = Edge::new(
                            cid.clone(),
                            mux_id.clone(),
                            None,
                            Some(select_data),
                        );
                        self.base_graph.add_edge(select_edge);
                        log::debug!("      Input {}: {} when ({})", i, src_id, cid);
                    } else {
                        log::debug!(
                            "      Warning: Could not create condition node for input {}: {}",
                            i, src_id
                        );
                    }
                } else {
                    log::debug!("      Input {}: {} (default)", i, src_id);
                }
            }

            // Add mux output -> target assignment edge.
            let mut output_data: HashMap<String, Value> = HashMap::new();
            output_data.insert("type".into(), Value::String("assignment".into()));
            let output_edge = Edge::new(
                mux_id.clone(),
                target_node_id.clone(),
                None,
                Some(output_data),
            );
            self.base_graph.add_edge(output_edge);
            log::debug!("    Mux output -> {}", state_name);
        }
    }

    // =======================================================================
    // get_or_create_condition_node
    // =======================================================================

    /// Get or create a node for a condition expression.
    ///
    /// For simple identifier conditions, finds the existing node.
    /// For compound expressions (binary_op, etc.), creates new operation nodes.
    ///
    /// Returns the node ID if found or created.
    fn get_or_create_condition_node(
        &mut self,
        cond: &Value,
        input_index: usize,
        src_id: &str,
    ) -> Option<String> {
        match cond {
            Value::String(cond_name) => {
                // Simple string condition -- find existing node.
                self.find_node_by_name_or_id(cond_name)
            }
            Value::Object(obj) => {
                let cond_type = obj
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");

                match cond_type {
                    "identifier" => {
                        let name = obj
                            .get("name")
                            .and_then(|v| v.as_str())
                            .unwrap_or("unknown");
                        self.find_node_by_name_or_id(name)
                    }

                    "binary_op" => {
                        let left = obj.get("left").cloned().unwrap_or(Value::Null);
                        let right = obj.get("right").cloned().unwrap_or(Value::Null);
                        let operator = obj
                            .get("operator")
                            .and_then(|v| v.as_str())
                            .unwrap_or("&")
                            .to_string();

                        let left_id_str = expression_to_id(&left);
                        let right_id_str = expression_to_id(&right);
                        let cond_id = format!(
                            "({} {} {})",
                            left_id_str, operator, right_id_str
                        );

                        // Already exists?
                        if self.base_graph.nodes.contains_key(&cond_id) {
                            return Some(cond_id);
                        }

                        // Create operand nodes recursively.
                        let left_node_id = self.get_or_create_condition_node(
                            &left,
                            input_index,
                            src_id,
                        );
                        let right_node_id = self.get_or_create_condition_node(
                            &right,
                            input_index,
                            src_id,
                        );

                        // Result width: comparisons produce 1-bit.
                        let result_width: i64 = if [
                            "==", "!=", "<", ">", "<=", ">=", "&", "|", "&&", "||",
                        ]
                        .contains(&operator.as_str())
                        {
                            1
                        } else {
                            32
                        };

                        let node_data = value_to_data(serde_json::json!({
                            "type": "operation",
                            "operator": operator,
                            "expression": cond,
                            "display_name": cond_id,
                            "bit_width": result_width,
                        }));
                        let mut cond_node = Node::with_defaults(Some(cond_id.clone()));
                        cond_node.data = node_data;
                        self.base_graph.add_node(cond_node);

                        // Add operand edges.
                        if let Some(ref lid) = left_node_id {
                            let mut ed: HashMap<String, Value> = HashMap::new();
                            ed.insert("type".into(), Value::String("operand".into()));
                            ed.insert("position".into(), Value::String("left".into()));
                            self.base_graph.add_edge(Edge::new(
                                lid.clone(),
                                cond_id.clone(),
                                None,
                                Some(ed),
                            ));
                        }
                        if let Some(ref rid) = right_node_id {
                            let mut ed: HashMap<String, Value> = HashMap::new();
                            ed.insert("type".into(), Value::String("operand".into()));
                            ed.insert("position".into(), Value::String("right".into()));
                            self.base_graph.add_edge(Edge::new(
                                rid.clone(),
                                cond_id.clone(),
                                None,
                                Some(ed),
                            ));
                        }

                        Some(cond_id)
                    }

                    "unary_op" => {
                        let operator = obj
                            .get("operator")
                            .and_then(|v| v.as_str())
                            .unwrap_or("~")
                            .to_string();
                        let operand = obj.get("operand").cloned().unwrap_or(Value::Null);
                        let operand_id_str = expression_to_id(&operand);
                        let cond_id = format!("{}{}", operator, operand_id_str);

                        if self.base_graph.nodes.contains_key(&cond_id) {
                            return Some(cond_id);
                        }

                        let operand_node_id = self.get_or_create_condition_node(
                            &operand,
                            input_index,
                            src_id,
                        );

                        let node_data = value_to_data(serde_json::json!({
                            "type": "operation",
                            "operator": operator,
                            "expression": cond,
                            "display_name": cond_id,
                            "bit_width": 1,
                        }));
                        let mut cond_node = Node::with_defaults(Some(cond_id.clone()));
                        cond_node.data = node_data;
                        self.base_graph.add_node(cond_node);

                        if let Some(ref oid) = operand_node_id {
                            let mut ed: HashMap<String, Value> = HashMap::new();
                            ed.insert("type".into(), Value::String("operand".into()));
                            ed.insert("position".into(), Value::String("unary".into()));
                            self.base_graph.add_edge(Edge::new(
                                oid.clone(),
                                cond_id.clone(),
                                None,
                                Some(ed),
                            ));
                        }

                        Some(cond_id)
                    }

                    "literal" => {
                        let value = obj
                            .get("value")
                            .and_then(|v| v.as_i64())
                            .unwrap_or(0);
                        let literal_id = value.to_string();

                        if self.base_graph.nodes.contains_key(&literal_id) {
                            return Some(literal_id);
                        }

                        let node_data = value_to_data(serde_json::json!({
                            "type": "literal",
                            "value": value,
                            "display_name": literal_id,
                        }));
                        let mut literal_node =
                            Node::with_defaults(Some(literal_id.clone()));
                        literal_node.data = node_data;
                        self.base_graph.add_node(literal_node);
                        Some(literal_id)
                    }

                    other => {
                        log::debug!(
                            "      Warning: Unhandled condition type '{}' in condition: {}",
                            other, cond
                        );
                        None
                    }
                }
            }
            _ => None,
        }
    }

    // =======================================================================
    // validate_priority_consistency
    // =======================================================================

    /// Validate that if multiple aspects assign to the same prioritized state,
    /// all of them must specify a priority.
    fn validate_priority_consistency(&self) -> Result<(), String> {
        // state_name -> Vec<(aspect_file, Option<priority>)>
        let mut prioritized_by_aspect: HashMap<String, Vec<(String, Option<i64>)>> =
            HashMap::new();

        for ai in &self.aspect_graphs {
            for (state, priority) in &ai.prioritized_states {
                prioritized_by_aspect
                    .entry(state.clone())
                    .or_default()
                    .push((ai.file.clone(), Some(*priority)));
            }
        }

        let mut errors = Vec::new();
        for (state, aspects) in &prioritized_by_aspect {
            if aspects.len() <= 1 {
                continue;
            }
            let no_priority: Vec<&(String, Option<i64>)> =
                aspects.iter().filter(|(_, p)| p.is_none()).collect();
            if !no_priority.is_empty() {
                let files: Vec<&str> =
                    no_priority.iter().map(|(f, _)| f.as_str()).collect();
                errors.push(format!(
                    "State '{}' has inconsistent priorities:\n\
                     Without priority: {}\n\
                     All aspects writing to the same state must specify a priority.",
                    state,
                    files.join(", ")
                ));
            }
        }

        if !errors.is_empty() {
            return Err(format!(
                "Aspect priority conflicts:\n\n{}",
                errors.join("\n\n")
            ));
        }

        Ok(())
    }

    // =======================================================================
    // merge_prioritized_writes
    // =======================================================================

    /// Merge writes from multiple aspects to prioritized variables.
    ///
    /// - 1-bit variables: OR all sources together.
    /// - Multi-bit variables: Create priority-ordered conditional chain.
    fn merge_prioritized_writes(&mut self) -> Result<(), String> {
        // Step 1: Collect all prioritized writes across aspects.
        // var_name -> Vec<PrioritizedWrite>
        let mut prioritized_vars: HashMap<String, Vec<PrioritizedWrite>> = HashMap::new();

        for ai in &self.aspect_graphs {
            let aspect_file = &ai.file;

            for (var_name, &priority) in &ai.prioritized_states {
                for node_id in &ai.aspect_nodes {
                    if let Some(node) = self.base_graph.nodes.get(node_id) {
                        let outgoing: Vec<String> =
                            node.outgoing_edges.iter().cloned().collect();
                        for edge_id in &outgoing {
                            if let Some(edge) = self.base_graph.edges.get(edge_id) {
                                let etype = data_str(&edge.data, "type");
                                if etype == "assignment" {
                                    let target_name = self
                                        .base_graph
                                        .nodes
                                        .get(&edge.target)
                                        .map(|n| data_str(&n.data, "name"))
                                        .unwrap_or("");
                                    if target_name == var_name {
                                        prioritized_vars
                                            .entry(var_name.clone())
                                            .or_default()
                                            .push(PrioritizedWrite {
                                                priority,
                                                aspect: aspect_file.clone(),
                                                source_id: node_id.clone(),
                                                edge_id: edge_id.clone(),
                                            });
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // Step 2: Pre-compute conditions for multi-bit variables BEFORE any
        // merging. For 1-bit variables, the source IS the condition.
        let mut conditions_map: HashMap<(String, i64), String> = HashMap::new();
        for (var_name, writes) in &prioritized_vars {
            if writes.len() < 2 {
                continue;
            }
            let var_width = self.find_var_width(var_name);
            if var_width == 1 {
                for w in writes {
                    conditions_map
                        .insert((w.aspect.clone(), w.priority), w.source_id.clone());
                }
            }
        }

        // Step 3: Process each variable with multiple prioritized writes.
        let var_names: Vec<String> = prioritized_vars.keys().cloned().collect();
        for var_name in var_names {
            let writes = match prioritized_vars.get_mut(&var_name) {
                Some(w) if w.len() >= 2 => w,
                _ => continue,
            };

            // Sort by priority (lower number = higher priority = checked first).
            writes.sort_by_key(|w| w.priority);

            // Find the target node.
            let target_node_id = match self.find_target_node_for_var(&var_name) {
                Some(id) => id,
                None => {
                    log::debug!(
                        "  Warning: Prioritized variable '{}' not found",
                        var_name
                    );
                    continue;
                }
            };

            let var_width = self.find_var_width(&var_name);

            // Validate: for multi-bit variables, no duplicate priorities.
            if var_width > 1 {
                let mut seen: HashMap<i64, Vec<String>> = HashMap::new();
                for w in writes.iter() {
                    seen.entry(w.priority).or_default().push(w.aspect.clone());
                }
                let duplicates: Vec<i64> = seen
                    .iter()
                    .filter(|(_, v)| v.len() > 1)
                    .map(|(&k, _)| k)
                    .collect();
                if !duplicates.is_empty() {
                    let mut details = Vec::new();
                    for p in &duplicates {
                        let aspects = &seen[p];
                        details.push(format!(
                            "  Priority {}: {}",
                            p,
                            aspects.join(", ")
                        ));
                    }
                    return Err(format!(
                        "Multiple aspects assign to multi-bit variable '{}' \
                         with the same priority:\n{}\n\
                         Each aspect must use a unique priority for multi-bit variables.",
                        var_name,
                        details.join("\n")
                    ));
                }
            }

            log::debug!(
                "\nMerging {} writes to '{}' (width={}):",
                writes.len(),
                var_name,
                var_width
            );
            for w in writes.iter() {
                let basename = Path::new(&w.aspect)
                    .file_name()
                    .map(|f| f.to_string_lossy().to_string())
                    .unwrap_or_else(|| w.aspect.clone());
                log::debug!(
                    "  Priority {}: {} from {}",
                    w.priority, w.source_id, basename
                );
            }

            // Clone needed data to avoid borrow issues.
            let writes_clone: Vec<PrioritizedWrite> = writes.clone();
            let conditions_map_clone = conditions_map.clone();

            if var_width == 1 {
                self.create_or_merge(&target_node_id, &writes_clone, &var_name);
            } else {
                self.create_priority_chain_merge(
                    &target_node_id,
                    &writes_clone,
                    &var_name,
                    var_width,
                    &conditions_map_clone,
                );
            }
        }

        Ok(())
    }

    // =======================================================================
    // create_or_merge  (1-bit variables: OR chain)
    // =======================================================================

    /// Merge multiple 1-bit writes using OR: target = source1 | source2 | ...
    fn create_or_merge(
        &mut self,
        target_node_id: &str,
        writes: &[PrioritizedWrite],
        var_name: &str,
    ) {
        // Remove original assignment edges.
        for w in writes {
            if self.base_graph.edges.contains_key(&w.edge_id) {
                self.base_graph.remove_edge(&w.edge_id);
            }
        }

        let sources: Vec<String> = writes.iter().map(|w| w.source_id.clone()).collect();

        // Build OR chain: ((s1 | s2) | s3) | ...
        let or_result_id = if sources.len() == 2 {
            let id = format!("{}_merged", var_name);
            self.create_or_node(&sources[0], &sources[1], &id);
            id
        } else {
            let first_id = format!("{}_or_0_1", var_name);
            self.create_or_node(&sources[0], &sources[1], &first_id);
            let mut prev_id = first_id;
            for (i, source) in sources.iter().enumerate().skip(2) {
                let id = format!("{}_or_{}", var_name, i);
                self.create_or_node(&prev_id, source, &id);
                prev_id = id;
            }
            prev_id
        };

        // Create assignment from OR result to target.
        let mut assign_data: HashMap<String, Value> = HashMap::new();
        assign_data.insert("type".into(), Value::String("assignment".into()));
        self.base_graph.add_edge(Edge::new(
            or_result_id,
            target_node_id.to_string(),
            None,
            Some(assign_data),
        ));

        let source_ids: Vec<&str> = sources.iter().map(|s| s.as_str()).collect();
        log::debug!(
            "  Created OR merge: {} = {}",
            var_name,
            source_ids.join(" | ")
        );
    }

    /// Create an OR operation node with edges from left and right operands.
    fn create_or_node(&mut self, left_id: &str, right_id: &str, node_id: &str) {
        let display = format!("({} | {})", left_id, right_id);
        let node_data = value_to_data(serde_json::json!({
            "type": "operation",
            "operator": "|",
            "display_name": display,
            "bit_width": 1,
        }));
        let mut or_node = Node::with_defaults(Some(node_id.to_string()));
        or_node.data = node_data;
        self.base_graph.add_node(or_node);

        // Left operand edge.
        let mut left_data: HashMap<String, Value> = HashMap::new();
        left_data.insert("type".into(), Value::String("operand".into()));
        left_data.insert("position".into(), Value::String("left".into()));
        self.base_graph.add_edge(Edge::new(
            left_id.to_string(),
            node_id.to_string(),
            None,
            Some(left_data),
        ));

        // Right operand edge.
        let mut right_data: HashMap<String, Value> = HashMap::new();
        right_data.insert("type".into(), Value::String("operand".into()));
        right_data.insert("position".into(), Value::String("right".into()));
        self.base_graph.add_edge(Edge::new(
            right_id.to_string(),
            node_id.to_string(),
            None,
            Some(right_data),
        ));
    }

    // =======================================================================
    // create_priority_chain_merge  (multi-bit variables: ternary chain)
    // =======================================================================

    /// Merge multiple multi-bit writes using priority-ordered conditional chain.
    ///
    /// Creates: target = cond1 ? val1 : (cond2 ? val2 : (... : default))
    fn create_priority_chain_merge(
        &mut self,
        target_node_id: &str,
        writes: &[PrioritizedWrite],
        var_name: &str,
        var_width: i64,
        conditions_map: &HashMap<(String, i64), String>,
    ) {
        // Remove original assignment edges.
        for w in writes {
            if self.base_graph.edges.contains_key(&w.edge_id) {
                self.base_graph.remove_edge(&w.edge_id);
            }
        }

        // Find conditions for each write from the pre-computed map.
        let mut writes_with_conditions: Vec<WriteWithCondition> = Vec::new();
        for w in writes {
            let key = (w.aspect.clone(), w.priority);
            if let Some(cond_id) = conditions_map.get(&key) {
                writes_with_conditions.push(WriteWithCondition {
                    priority: w.priority,
                    value_id: w.source_id.clone(),
                    condition_id: cond_id.clone(),
                    _aspect: w.aspect.clone(),
                });
            } else {
                let basename = Path::new(&w.aspect)
                    .file_name()
                    .map(|f| f.to_string_lossy().to_string())
                    .unwrap_or_else(|| w.aspect.clone());
                log::debug!(
                    "  Warning: No condition found for priority {} from {}",
                    w.priority, basename
                );
            }
        }

        if writes_with_conditions.is_empty() {
            log::debug!(
                "  Error: No conditions found for any writes to {}",
                var_name
            );
            return;
        }

        // Build ternary chain from lowest to highest priority (inside-out).
        // Start with default value (0).
        let default_id = format!("{}_default", var_name);
        self.get_or_create_literal_node(0, var_width, &default_id);

        let mut result_node_id = default_id;

        // Process in reverse order (lowest priority first -> innermost).
        for w in writes_with_conditions.iter().rev() {
            let ternary_id = format!("{}_priority_{}", var_name, w.priority);
            let display =
                format!("{} ? {} : ...", w.condition_id, w.value_id);

            let ternary_data = value_to_data(serde_json::json!({
                "type": "ternary_op",
                "display_name": display,
                "bit_width": var_width,
            }));
            let mut ternary_node =
                Node::with_defaults(Some(ternary_id.clone()));
            ternary_node.data = ternary_data;
            self.base_graph.add_node(ternary_node);

            // condition -> ternary
            let mut cond_ed: HashMap<String, Value> = HashMap::new();
            cond_ed.insert(
                "type".into(),
                Value::String("ternary_condition".into()),
            );
            self.base_graph.add_edge(Edge::new(
                w.condition_id.clone(),
                ternary_id.clone(),
                None,
                Some(cond_ed),
            ));

            // true value -> ternary
            let mut true_ed: HashMap<String, Value> = HashMap::new();
            true_ed.insert("type".into(), Value::String("ternary_true".into()));
            self.base_graph.add_edge(Edge::new(
                w.value_id.clone(),
                ternary_id.clone(),
                None,
                Some(true_ed),
            ));

            // false value (previous result) -> ternary
            let mut false_ed: HashMap<String, Value> = HashMap::new();
            false_ed
                .insert("type".into(), Value::String("ternary_false".into()));
            self.base_graph.add_edge(Edge::new(
                result_node_id.clone(),
                ternary_id.clone(),
                None,
                Some(false_ed),
            ));

            result_node_id = ternary_id;
        }

        // Final assignment: result -> target.
        let mut assign_data: HashMap<String, Value> = HashMap::new();
        assign_data.insert("type".into(), Value::String("assignment".into()));
        self.base_graph.add_edge(Edge::new(
            result_node_id,
            target_node_id.to_string(),
            None,
            Some(assign_data),
        ));

        log::debug!("  Created priority chain for {}:", var_name);
        for w in &writes_with_conditions {
            log::debug!(
                "    Priority {}: {} ? {}",
                w.priority, w.condition_id, w.value_id
            );
        }
    }

    // =======================================================================
    // Internal helpers
    // =======================================================================

    /// Get or create a literal node with the given value and width.
    fn get_or_create_literal_node(&mut self, value: i64, width: i64, node_id: &str) {
        if self.base_graph.nodes.contains_key(node_id) {
            return;
        }
        let nd = value_to_data(serde_json::json!({
            "type": "literal",
            "value": value,
            "bit_width": width,
            "display_name": value.to_string(),
        }));
        let mut literal_node = Node::with_defaults(Some(node_id.to_string()));
        literal_node.data = nd;
        self.base_graph.add_node(literal_node);
    }

    /// Find a node by name or direct ID match. Returns the node ID if found.
    fn find_node_by_name_or_id(&self, name: &str) -> Option<String> {
        // Sort for deterministic order.
        let mut sorted: Vec<(&String, &Node)> = self.base_graph.nodes.iter().collect();
        sorted.sort_by_key(|(id, _)| (*id).clone());
        for (nid, node) in &sorted {
            if nid.as_str() == name {
                return Some((*nid).clone());
            }
            let nname = data_str(&node.data, "name");
            if nname == name {
                return Some((*nid).clone());
            }
        }
        None
    }

    /// Extract the base state name from a node (handling array access, etc.).
    fn get_state_name_from_node_id(&self, node_id: &str) -> Option<String> {
        let node = self.base_graph.nodes.get(node_id)?;
        let ntype = data_str(&node.data, "type");

        if ntype.starts_with("isa_state") {
            return node
                .data
                .get("name")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
        }

        if ntype == "array_access" {
            // Follow edges backward to find the array node.
            for edge_id in &node.incoming_edges {
                if let Some(edge) = self.base_graph.edges.get(edge_id) {
                    let etype = data_str(&edge.data, "type");
                    if etype == "array_index" {
                        if let Some(result) =
                            self.get_state_name_from_node_id(&edge.source)
                        {
                            return Some(result);
                        }
                    }
                }
            }
        }

        None
    }

    /// Find the target node ID for a variable by name.
    fn find_target_node_for_var(&self, var_name: &str) -> Option<String> {
        for (nid, node) in &self.base_graph.nodes {
            let nname = data_str(&node.data, "name");
            if nname == var_name {
                return Some(nid.clone());
            }
        }
        None
    }

    /// Find the bit width of a variable by name. Defaults to 1.
    fn find_var_width(&self, var_name: &str) -> i64 {
        for (_nid, node) in &self.base_graph.nodes {
            let nname = data_str(&node.data, "name");
            if nname == var_name {
                return node
                    .data
                    .get("bit_width")
                    .and_then(|v| v.as_i64())
                    .or_else(|| {
                        node.data.get("width").and_then(|v| v.as_i64())
                    })
                    .unwrap_or(1);
            }
        }
        1
    }
}

// ---------------------------------------------------------------------------
// Internal helper structs
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
struct PrioritizedWrite {
    priority: i64,
    aspect: String,
    source_id: String,
    edge_id: String,
}

#[derive(Debug, Clone)]
struct WriteWithCondition {
    priority: i64,
    value_id: String,
    condition_id: String,
    _aspect: String,
}

// ---------------------------------------------------------------------------
// Public helper function
// ---------------------------------------------------------------------------

/// Convert an expression AST (`serde_json::Value`) to a unique ID string
/// for node lookup (matching ISA parser format).
pub fn expression_to_id(expr: &Value) -> String {
    match expr {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        Value::Object(obj) => {
            let expr_type = obj
                .get("type")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            match expr_type {
                "identifier" => obj
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("unknown")
                    .to_string(),
                "literal" => obj
                    .get("value")
                    .map(|v| match v {
                        Value::Number(n) => n.to_string(),
                        other => other.to_string(),
                    })
                    .unwrap_or_else(|| "0".to_string()),
                "binary_op" => {
                    let left = obj.get("left").cloned().unwrap_or(Value::Null);
                    let right = obj.get("right").cloned().unwrap_or(Value::Null);
                    let op = obj
                        .get("operator")
                        .and_then(|v| v.as_str())
                        .unwrap_or("&");
                    format!(
                        "({} {} {})",
                        expression_to_id(&left),
                        op,
                        expression_to_id(&right)
                    )
                }
                "unary_op" => {
                    let op = obj
                        .get("operator")
                        .and_then(|v| v.as_str())
                        .unwrap_or("~");
                    let operand = obj.get("operand").cloned().unwrap_or(Value::Null);
                    format!("{}{}", op, expression_to_id(&operand))
                }
                _ => {
                    // Fallback: simple hash-like ID.
                    let s = expr.to_string();
                    let hash: u64 = s
                        .bytes()
                        .fold(0u64, |acc, b| acc.wrapping_mul(31).wrapping_add(b as u64));
                    format!("expr_{}", hash % 10000)
                }
            }
        }
        _ => expr.to_string(),
    }
}

// ---------------------------------------------------------------------------
// Public convenience function
// ---------------------------------------------------------------------------

/// Convenience function to merge all aspects in a graph.
///
/// Creates an `AspectMerger` and calls `load_and_merge_aspects`.
pub fn merge_aspects(
    graph: &mut ResourceGraph,
    base_file_path: Option<&str>,
) -> Result<(), String> {
    // Take ownership of the graph temporarily, then put it back.
    let taken_graph = std::mem::replace(graph, ResourceGraph::new());
    let mut merger = AspectMerger::new(
        taken_graph,
        base_file_path.map(|s| s.to_string()),
    );
    let result = merger.load_and_merge_aspects();
    // Put the (possibly modified) graph back.
    *graph = merger.base_graph;
    result
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_expression_to_id_identifier() {
        let expr = serde_json::json!({"type": "identifier", "name": "foo"});
        assert_eq!(expression_to_id(&expr), "foo");
    }

    #[test]
    fn test_expression_to_id_literal() {
        let expr = serde_json::json!({"type": "literal", "value": 42});
        assert_eq!(expression_to_id(&expr), "42");
    }

    #[test]
    fn test_expression_to_id_binary_op() {
        let expr = serde_json::json!({
            "type": "binary_op",
            "operator": "&",
            "left": {"type": "identifier", "name": "a"},
            "right": {"type": "identifier", "name": "b"}
        });
        assert_eq!(expression_to_id(&expr), "(a & b)");
    }

    #[test]
    fn test_expression_to_id_unary_op() {
        let expr = serde_json::json!({
            "type": "unary_op",
            "operator": "~",
            "operand": {"type": "identifier", "name": "x"}
        });
        assert_eq!(expression_to_id(&expr), "~x");
    }

    #[test]
    fn test_expression_to_id_string() {
        let expr = Value::String("hello".to_string());
        assert_eq!(expression_to_id(&expr), "hello");
    }

    #[test]
    fn test_expression_to_id_nested() {
        let expr = serde_json::json!({
            "type": "binary_op",
            "operator": "|",
            "left": {
                "type": "binary_op",
                "operator": "&",
                "left": {"type": "identifier", "name": "a"},
                "right": {"type": "identifier", "name": "b"}
            },
            "right": {
                "type": "unary_op",
                "operator": "~",
                "operand": {"type": "identifier", "name": "c"}
            }
        });
        assert_eq!(expression_to_id(&expr), "((a & b) | ~c)");
    }

    #[test]
    fn test_aspect_merger_no_declarations() {
        let mut graph = ResourceGraph::new();
        let result = merge_aspects(&mut graph, None);
        assert!(result.is_ok());
    }

    #[test]
    fn test_aspect_info_struct() {
        let info = AspectInfo {
            gated_states: HashSet::from(["pc".to_string(), "dmem".to_string()]),
            prioritized_states: HashMap::from([
                ("exc_taken".to_string(), 1),
                ("exc_vector".to_string(), 1),
            ]),
            order: 0,
            file: "interrupts.isa".to_string(),
            aspect_nodes: HashSet::new(),
        };
        assert_eq!(info.gated_states.len(), 2);
        assert!(info.gated_states.contains("pc"));
        assert_eq!(info.prioritized_states["exc_taken"], 1);
    }

    #[test]
    fn test_validate_priority_consistency_ok() {
        let graph = ResourceGraph::new();
        let merger = AspectMerger {
            base_graph: graph,
            base_file_path: None,
            aspect_graphs: vec![
                AspectInfo {
                    gated_states: HashSet::new(),
                    prioritized_states: HashMap::from([("exc_taken".to_string(), 1)]),
                    order: 0,
                    file: "int.isa".to_string(),
                    aspect_nodes: HashSet::new(),
                },
                AspectInfo {
                    gated_states: HashSet::new(),
                    prioritized_states: HashMap::from([("exc_taken".to_string(), 2)]),
                    order: 1,
                    file: "trap.isa".to_string(),
                    aspect_nodes: HashSet::new(),
                },
            ],
        };
        assert!(merger.validate_priority_consistency().is_ok());
    }

    #[test]
    fn test_find_node_by_name_or_id() {
        let mut graph = ResourceGraph::new();
        let mut n = Node::with_defaults(Some("my_node".to_string()));
        n.data
            .insert("name".to_string(), Value::String("foo".to_string()));
        graph.add_node(n);

        let merger = AspectMerger::new(graph, None);

        // Find by id.
        assert_eq!(
            merger.find_node_by_name_or_id("my_node"),
            Some("my_node".to_string())
        );
        // Find by name.
        assert_eq!(
            merger.find_node_by_name_or_id("foo"),
            Some("my_node".to_string())
        );
        // Not found.
        assert_eq!(merger.find_node_by_name_or_id("bar"), None);
    }

    #[test]
    fn test_get_state_name_from_node_id() {
        let mut graph = ResourceGraph::new();
        let mut n = Node::with_defaults(Some("pc".to_string()));
        n.data.insert(
            "type".to_string(),
            Value::String("isa_state".to_string()),
        );
        n.data
            .insert("name".to_string(), Value::String("pc".to_string()));
        graph.add_node(n);

        let merger = AspectMerger::new(graph, None);
        assert_eq!(
            merger.get_state_name_from_node_id("pc"),
            Some("pc".to_string())
        );
        assert_eq!(merger.get_state_name_from_node_id("nonexistent"), None);
    }

    #[test]
    fn test_find_var_width() {
        let mut graph = ResourceGraph::new();
        let mut n1 = Node::with_defaults(Some("exc_taken".to_string()));
        n1.data.insert(
            "name".to_string(),
            Value::String("exc_taken".to_string()),
        );
        n1.data.insert(
            "bit_width".to_string(),
            Value::Number(serde_json::Number::from(1)),
        );
        graph.add_node(n1);

        let mut n2 = Node::with_defaults(Some("exc_vector".to_string()));
        n2.data.insert(
            "name".to_string(),
            Value::String("exc_vector".to_string()),
        );
        n2.data.insert(
            "bit_width".to_string(),
            Value::Number(serde_json::Number::from(32)),
        );
        graph.add_node(n2);

        let merger = AspectMerger::new(graph, None);
        assert_eq!(merger.find_var_width("exc_taken"), 1);
        assert_eq!(merger.find_var_width("exc_vector"), 32);
        assert_eq!(merger.find_var_width("missing"), 1); // default
    }

    #[test]
    fn test_or_node_creation() {
        let mut graph = ResourceGraph::new();
        // Add source nodes.
        let mut s1 = Node::with_defaults(Some("src1".to_string()));
        s1.data
            .insert("name".to_string(), Value::String("src1".to_string()));
        graph.add_node(s1);

        let mut s2 = Node::with_defaults(Some("src2".to_string()));
        s2.data
            .insert("name".to_string(), Value::String("src2".to_string()));
        graph.add_node(s2);

        let mut merger = AspectMerger::new(graph, None);
        merger.create_or_node("src1", "src2", "or_result");

        assert!(merger.base_graph.nodes.contains_key("or_result"));
        let or_node = &merger.base_graph.nodes["or_result"];
        assert_eq!(data_str(&or_node.data, "type"), "operation");
        assert_eq!(data_str(&or_node.data, "operator"), "|");
        // Should have 2 incoming edges (from src1 and src2).
        assert_eq!(or_node.incoming_edges.len(), 2);
    }

    #[test]
    fn test_literal_node_creation() {
        let graph = ResourceGraph::new();
        let mut merger = AspectMerger::new(graph, None);
        merger.get_or_create_literal_node(0, 32, "my_literal");

        assert!(merger.base_graph.nodes.contains_key("my_literal"));
        let lit = &merger.base_graph.nodes["my_literal"];
        assert_eq!(data_str(&lit.data, "type"), "literal");
        assert_eq!(data_i64(&lit.data, "value", -1), 0);
        assert_eq!(data_i64(&lit.data, "bit_width", -1), 32);

        // Calling again should not duplicate.
        merger.get_or_create_literal_node(0, 32, "my_literal");
        assert_eq!(merger.base_graph.nodes.len(), 1);
    }

    #[test]
    fn test_condition_node_identifier() {
        let mut graph = ResourceGraph::new();
        let mut n = Node::with_defaults(Some("int_should_take".to_string()));
        n.data.insert(
            "name".to_string(),
            Value::String("int_should_take".to_string()),
        );
        graph.add_node(n);

        let mut merger = AspectMerger::new(graph, None);
        let cond = serde_json::json!({"type": "identifier", "name": "int_should_take"});
        let result = merger.get_or_create_condition_node(&cond, 0, "src");
        assert_eq!(result, Some("int_should_take".to_string()));
    }

    #[test]
    fn test_condition_node_binary_op() {
        let mut graph = ResourceGraph::new();
        let mut a = Node::with_defaults(Some("a".to_string()));
        a.data
            .insert("name".to_string(), Value::String("a".to_string()));
        graph.add_node(a);
        let mut b = Node::with_defaults(Some("b".to_string()));
        b.data
            .insert("name".to_string(), Value::String("b".to_string()));
        graph.add_node(b);

        let mut merger = AspectMerger::new(graph, None);
        let cond = serde_json::json!({
            "type": "binary_op",
            "operator": "&",
            "left": {"type": "identifier", "name": "a"},
            "right": {"type": "identifier", "name": "b"}
        });
        let result = merger.get_or_create_condition_node(&cond, 0, "src");
        assert_eq!(result, Some("(a & b)".to_string()));
        assert!(merger.base_graph.nodes.contains_key("(a & b)"));
    }

    #[test]
    fn test_value_to_data() {
        let v = serde_json::json!({"type": "literal", "value": 42});
        let d = value_to_data(v);
        assert_eq!(d.get("type").unwrap(), &Value::String("literal".into()));
        assert_eq!(d.get("value").unwrap(), &Value::Number(42.into()));

        // Non-object returns empty map.
        let d2 = value_to_data(Value::Null);
        assert!(d2.is_empty());
    }

    #[test]
    fn test_gated_mux_creation() {
        let mut graph = ResourceGraph::new();

        // Create a gated state node.
        let mut pc = Node::with_defaults(Some("pc".to_string()));
        pc.data.insert(
            "type".to_string(),
            Value::String("isa_state".to_string()),
        );
        pc.data
            .insert("name".to_string(), Value::String("pc".to_string()));
        graph.add_node(pc);

        // Create two source nodes.
        let mut src_base = Node::with_defaults(Some("pc_plus_4".to_string()));
        src_base.data.insert(
            "name".to_string(),
            Value::String("pc_plus_4".to_string()),
        );
        graph.add_node(src_base);

        let mut src_aspect = Node::with_defaults(Some("exc_handler".to_string()));
        src_aspect.data.insert(
            "name".to_string(),
            Value::String("exc_handler".to_string()),
        );
        src_aspect.data.insert(
            "from_aspect".to_string(),
            Value::String("int.isa".to_string()),
        );
        graph.add_node(src_aspect);

        // Create an enable-condition node.
        let mut cond_node =
            Node::with_defaults(Some("exc_taken_flag".to_string()));
        cond_node.data.insert(
            "name".to_string(),
            Value::String("exc_taken_flag".to_string()),
        );
        graph.add_node(cond_node);

        // Add base assignment edge (no precedence).
        let mut base_data: HashMap<String, Value> = HashMap::new();
        base_data.insert("type".into(), Value::String("assignment".into()));
        graph.add_edge(Edge::new(
            "pc_plus_4".into(),
            "pc".into(),
            None,
            Some(base_data),
        ));

        // Add aspect assignment edge with precedence and enable.
        let mut asp_data: HashMap<String, Value> = HashMap::new();
        asp_data.insert("type".into(), Value::String("assignment".into()));
        asp_data.insert("precedence".into(), Value::Number(1.into()));
        asp_data.insert(
            "from_aspect".into(),
            Value::String("int.isa".into()),
        );
        asp_data.insert(
            "enable".into(),
            serde_json::json!({"type": "identifier", "name": "exc_taken_flag"}),
        );
        graph.add_edge(Edge::new(
            "exc_handler".into(),
            "pc".into(),
            None,
            Some(asp_data),
        ));

        let mut merger = AspectMerger::new(graph, None);
        merger.aspect_graphs.push(AspectInfo {
            gated_states: HashSet::from(["pc".to_string()]),
            prioritized_states: HashMap::new(),
            order: 0,
            file: "int.isa".to_string(),
            aspect_nodes: HashSet::from(["exc_handler".to_string()]),
        });

        merger.create_gated_write_multiplexers();

        // Verify mux was created.
        assert!(
            merger.base_graph.nodes.contains_key("pc_gated_mux"),
            "Mux node should exist"
        );
        let mux = &merger.base_graph.nodes["pc_gated_mux"];
        assert_eq!(data_str(&mux.data, "type"), "multiplexer");
        assert_eq!(data_str(&mux.data, "select_type"), "priority");

        // Verify original direct assignments to pc are gone.
        let pc_node = &merger.base_graph.nodes["pc"];
        for eid in &pc_node.incoming_edges {
            let edge = &merger.base_graph.edges[eid];
            // The only incoming assignment should be from the mux.
            if data_str(&edge.data, "type") == "assignment" {
                assert_eq!(edge.source, "pc_gated_mux");
            }
        }
    }
}
