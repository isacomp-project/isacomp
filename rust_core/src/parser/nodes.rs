// Node creation and expression-to-ID mapping.
// Ported from isa_parser.py get_or_create_node_for_expression / expression_to_id.

use std::collections::HashMap;

use serde_json::{json, Value};

use crate::resource_graph::{Edge, Node, ResourceGraph};

use super::ISAParser;

impl ISAParser {
    // -----------------------------------------------------------------------
    // Bit-width inference
    // -----------------------------------------------------------------------

    pub fn infer_bit_width(
        operator: &str,
        left_width: Option<i64>,
        right_width: Option<i64>,
        right_expr: Option<&Value>,
    ) -> Option<i64> {
        if left_width.is_none() && right_width.is_none() {
            return None;
        }

        // Comparison operators always produce 1-bit result
        if matches!(
            operator,
            "==" | "!=" | "<" | ">" | "<=" | ">=" | "<s" | ">s" | "<=s" | ">=s"
        ) {
            return Some(1);
        }

        // Shift operators
        if matches!(operator, "<<" | ">>" | ">>>") {
            if operator == "<<" {
                if let Some(re) = right_expr {
                    if re.get("type").and_then(|v| v.as_str()) == Some("literal") {
                        let shift = re.get("value").and_then(|v| v.as_i64()).unwrap_or(0);
                        if let Some(lw) = left_width {
                            return Some(lw + shift);
                        }
                    }
                }
                return left_width;
            } else {
                return left_width;
            }
        }

        // Arithmetic and bitwise
        if matches!(operator, "+" | "-" | "&" | "|" | "^" | "*" | "/" | "/s" | "%" | "%s") {
            if let (Some(lw), Some(rw)) = (left_width, right_width) {
                let max_w = lw.max(rw);
                if matches!(operator, "+" | "-") {
                    return Some(max_w + 1);
                }
                return Some(max_w);
            }
            let w = left_width.or(right_width);
            if matches!(operator, "+" | "-") {
                return w.map(|w| w + 1);
            }
            return w;
        }

        None
    }

    pub fn infer_unary_width(operator: &str, operand_width: Option<i64>) -> Option<i64> {
        operand_width.map(|w| {
            if operator == "!" {
                1 // Logical NOT always 1-bit
            } else {
                w // Bitwise NOT, negation preserve width
            }
        })
    }

    // -----------------------------------------------------------------------
    // expression_to_id
    // -----------------------------------------------------------------------

    pub fn expression_to_id(&self, graph: &ResourceGraph, expr: &Value, access_mode: &str) -> String {
        let expr_type = expr.get("type").and_then(|v| v.as_str()).unwrap_or("");

        match expr_type {
            "identifier" => {
                let identifier_name = expr
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();

                // Check for _rd version (indicates isa_state with split)
                let rd_name = format!("{}_rd", identifier_name);
                if graph.nodes.contains_key(&rd_name) {
                    // Check for intermediate value on read
                    if access_mode == "read" {
                        if let Some(intermediate_id) =
                            self.intermediate_values.get(&identifier_name)
                        {
                            return intermediate_id.clone();
                        }
                    }
                    let suffix = if access_mode == "write" { "_wr" } else { "_rd" };
                    return format!("{}{}", identifier_name, suffix);
                }

                // Fallback: check direct node
                if graph.nodes.contains_key(&identifier_name) {
                    let node = &graph.nodes[&identifier_name];
                    let is_isa_state = node
                        .data
                        .get("type")
                        .and_then(|v| v.as_str())
                        == Some("isa_state");

                    if is_isa_state && access_mode == "read" {
                        if let Some(intermediate_id) =
                            self.intermediate_values.get(&identifier_name)
                        {
                            return intermediate_id.clone();
                        }
                    }
                }

                identifier_name
            }
            "array_access" => {
                let target = expr.get("target").unwrap_or(&Value::Null);
                let index = expr.get("index").unwrap_or(&Value::Null);
                let array_id = self.expression_to_id(graph, target, access_mode);
                let index_id = self.expression_to_id(graph, index, "read");
                let suffix = if access_mode == "write" { "_wr" } else { "_rd" };
                format!("{}[{}]{}", array_id, index_id, suffix)
            }
            "bit_slice" => {
                let target = expr.get("target").unwrap_or(&Value::Null);
                let range = expr.get("range").unwrap_or(&Value::Null);
                let target_id = self.expression_to_id(graph, target, access_mode);
                let high = range.get(0).unwrap_or(&Value::Null);
                let low = range.get(1).unwrap_or(&Value::Null);

                // Add suffix for arch state
                let mut suffix = String::new();
                if target.get("type").and_then(|v| v.as_str()) == Some("identifier") {
                    let target_name = target
                        .get("name")
                        .and_then(|v| v.as_str())
                        .unwrap_or("");
                    if graph.nodes.contains_key(target_name) {
                        let node = &graph.nodes[target_name];
                        let is_arch = node.is_arch_state
                            || node
                                .data
                                .get("type")
                                .and_then(|v| v.as_str())
                                == Some("isa_state");
                        if is_arch {
                            suffix = if access_mode == "write" {
                                "_wr".to_string()
                            } else {
                                "_rd".to_string()
                            };
                        }
                    }
                }
                format!("{}[{}:{}]{}", target_id, high, low, suffix)
            }
            "binary_op" => {
                let left = expr.get("left").unwrap_or(&Value::Null);
                let right = expr.get("right").unwrap_or(&Value::Null);
                let left_id = self.expression_to_id(graph, left, "read");
                let right_id = self.expression_to_id(graph, right, "read");
                let op = expr
                    .get("operator")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                format!("({} {} {})", left_id, op, right_id)
            }
            "literal" => {
                let val = expr.get("value").and_then(|v| v.as_i64()).unwrap_or(0);
                val.to_string()
            }
            "sized_literal" => {
                let fmt = expr
                    .get("format")
                    .and_then(|v| v.as_str())
                    .unwrap_or("bin");
                let fmt_char = match fmt {
                    "bin" => "b",
                    "hex" => "h",
                    "dec" => "d",
                    _ => "b",
                };
                let width = expr.get("width").and_then(|v| v.as_i64()).unwrap_or(0);
                let digits = expr
                    .get("original_digits")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                format!("{}'{}{}", width, fmt_char, digits)
            }
            "binary_wildcard" => expr
                .get("original")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
            "concatenation" => {
                let parts = expr
                    .get("parts")
                    .and_then(|v| v.as_array())
                    .cloned()
                    .unwrap_or_default();
                let sub_ids: Vec<String> =
                    parts.iter().map(|p| self.expression_to_id(graph, p, "read")).collect();
                format!("{{{}}}", sub_ids.join(", "))
            }
            "repetition" => {
                let sub_expr = expr.get("expression").unwrap_or(&Value::Null);
                let sub_id = self.expression_to_id(graph, sub_expr, "read");
                let count = expr.get("count").and_then(|v| v.as_i64()).unwrap_or(0);
                format!("{{{}{{{}}}}}", count, sub_id)
            }
            "ternary_op" => {
                let cond = expr.get("condition").unwrap_or(&Value::Null);
                let t = expr.get("if_true").unwrap_or(&Value::Null);
                let f = expr.get("if_false").unwrap_or(&Value::Null);
                let cond_id = self.expression_to_id(graph, cond, "read");
                let true_id = self.expression_to_id(graph, t, "read");
                let false_id = self.expression_to_id(graph, f, "read");
                format!("{} ? {} : {}", cond_id, true_id, false_id)
            }
            "unary_op" => {
                let operand = expr.get("operand").unwrap_or(&Value::Null);
                let operand_id = self.expression_to_id(graph, operand, "read");
                let op = expr
                    .get("operator")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                format!("{}{}", op, operand_id)
            }
            "reduction_op" => {
                let operand = expr.get("operand").unwrap_or(&Value::Null);
                let operand_id = self.expression_to_id(graph, operand, "read");
                let op = expr
                    .get("operator")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                format!("{}{}", op, operand_id)
            }
            "fp_intrinsic_call" => {
                let operands = expr
                    .get("operands")
                    .and_then(|v| v.as_array())
                    .cloned()
                    .unwrap_or_default();
                let op_ids: Vec<String> =
                    operands.iter().map(|o| self.expression_to_id(graph, o, "read")).collect();
                let name = expr
                    .get("intrinsic")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                format!("{}({})", name, op_ids.join(", "))
            }
            "cam_lookup" => {
                let cam = expr.get("target").unwrap_or(&Value::Null);
                let key = expr.get("key").unwrap_or(&Value::Null);
                let cam_id = self.expression_to_id(graph, cam, "read");
                let key_id = self.expression_to_id(graph, key, "read");
                if let Some(set_index) = expr.get("set_index") {
                    if !set_index.is_null() {
                        let set_id = self.expression_to_id(graph, set_index, "read");
                        return format!("{}@[{}][{}]", cam_id, key_id, set_id);
                    }
                }
                format!("{}@[{}]", cam_id, key_id)
            }
            "builtin_call" => {
                let builtin = expr
                    .get("builtin")
                    .and_then(|v| v.as_str())
                    .unwrap_or("ctz");
                let operand = expr.get("operand").unwrap_or(&Value::Null);
                let operand_id = self.expression_to_id(graph, operand, "read");
                format!("{}({})", builtin, operand_id)
            }
            _ => {
                log::warn!(
                    "Unhandled expression type '{}' in expression_to_id",
                    expr_type
                );
                format!("unknown_{}", expr)
            }
        }
    }

    // -----------------------------------------------------------------------
    // get_or_create_node_for_expression
    // -----------------------------------------------------------------------

    pub fn get_or_create_node_for_expression(
        &mut self,
        graph: &mut ResourceGraph,
        expr: &Value,
        access_mode: &str,
        enable_expr: Option<&Value>,
    ) -> Result<String, String> {
        let expr_id = self.expression_to_id(graph, expr, access_mode);

        if graph.nodes.contains_key(&expr_id) {
            return Ok(expr_id);
        }

        let expr_type = expr.get("type").and_then(|v| v.as_str()).unwrap_or("");

        match expr_type {
            "identifier" => {
                let name = expr
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();

                if !graph.nodes.contains_key(&name) && !graph.nodes.contains_key(&expr_id) {
                    // Create temporary node
                    let mut node_data: HashMap<String, Value> = HashMap::new();
                    node_data.insert("type".to_string(), json!("temp_var"));
                    node_data.insert("name".to_string(), json!(name));
                    node_data.insert("display_name".to_string(), json!(name));

                    let node = Node::new(
                        Some(name.clone()),
                        Some(node_data),
                        false, false, None, false, None, None, false, false, 0, false, false,
                        None, None,
                    );
                    graph.add_node(node);
                }

                // Return whichever ID exists
                if graph.nodes.contains_key(&expr_id) {
                    Ok(expr_id)
                } else {
                    Ok(name)
                }
            }

            "array_access" => {
                let target = expr.get("target").unwrap_or(&Value::Null);
                let index = expr.get("index").unwrap_or(&Value::Null);

                // Check if this is a bit-select on a scalar variable
                let mut is_bit_select = false;
                if target.get("type").and_then(|v| v.as_str()) == Some("identifier")
                    && index.get("type").and_then(|v| v.as_str()) == Some("literal")
                {
                    let array_id = target
                        .get("name")
                        .and_then(|v| v.as_str())
                        .unwrap_or("");
                    if graph.nodes.contains_key(array_id) {
                        let node_type = graph.nodes[array_id]
                            .data
                            .get("type")
                            .and_then(|v| v.as_str())
                            .unwrap_or("");
                        let is_var = node_type == "var";
                        let is_scalar_isa = node_type == "isa_state"
                            && !graph.nodes[array_id]
                                .data
                                .get("is_memory")
                                .and_then(|v| v.as_bool())
                                .unwrap_or(false);
                        is_bit_select = is_var || is_scalar_isa;
                    }
                }

                if is_bit_select {
                    let index_val = index.get("value").and_then(|v| v.as_i64()).unwrap_or(0);
                    let bs_expr = json!({
                        "type": "bit_slice",
                        "target": target,
                        "range": [index_val, index_val]
                    });
                    return self.get_or_create_node_for_expression(
                        graph,
                        &bs_expr,
                        access_mode,
                        enable_expr,
                    );
                }

                // Genuine array access
                let array_name = self.expression_to_id(graph, target, "read");
                let index_name = self.expression_to_id(graph, index, "read");
                let suffix = if access_mode == "write" { "wr" } else { "rd" };

                let array_node_id =
                    self.get_or_create_node_for_expression(graph, target, "read", None)?;

                // Get element width from base array
                let element_width = graph
                    .nodes
                    .get(&array_node_id)
                    .and_then(|n| n.data.get("bit_width"))
                    .and_then(|v| v.as_i64());

                let mut node_data: HashMap<String, Value> = HashMap::new();
                node_data.insert("type".to_string(), json!("array_access"));
                node_data.insert(
                    "display_name".to_string(),
                    json!(format!("{}[{}]_{}", array_name, index_name, suffix)),
                );
                node_data.insert("expression".to_string(), expr.clone());
                node_data.insert("access_mode".to_string(), json!(access_mode));
                if let Some(ew) = element_width {
                    node_data.insert("bit_width".to_string(), json!(ew));
                }
                if let Some(en) = enable_expr {
                    if access_mode == "write" {
                        node_data.insert("enable".to_string(), en.clone());
                    }
                }

                let node = Node::new(
                    Some(expr_id.clone()),
                    Some(node_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None,
                    None,
                );
                graph.add_node(node);

                // Edge to array base
                let mut base_data: HashMap<String, Value> = HashMap::new();
                base_data.insert("type".to_string(), json!("array_base"));
                let base_edge =
                    Edge::new(array_node_id, expr_id.clone(), None, Some(base_data));
                graph.add_edge(base_edge);

                // Index node
                let index_node_id =
                    self.get_or_create_node_for_expression(graph, index, "read", None)?;

                // Mark index node
                if let Some(idx_node) = graph.nodes.get_mut(&index_node_id) {
                    idx_node.used_as_index = true;
                    idx_node.indexed_by = Some(array_name);
                }

                let mut idx_data: HashMap<String, Value> = HashMap::new();
                idx_data.insert("type".to_string(), json!("array_index"));
                let idx_edge =
                    Edge::new(index_node_id, expr_id.clone(), None, Some(idx_data));
                graph.add_edge(idx_edge);

                // Enable expression edge for writes
                if let Some(en) = enable_expr {
                    if access_mode == "write" {
                        let enable_id = self.get_or_create_node_for_expression(
                            graph, en, "read", None,
                        )?;
                        let mut en_data: HashMap<String, Value> = HashMap::new();
                        en_data.insert("type".to_string(), json!("write_enable"));
                        let en_edge =
                            Edge::new(enable_id, expr_id.clone(), None, Some(en_data));
                        graph.add_edge(en_edge);
                    }
                }

                Ok(expr_id)
            }

            "bit_slice" => {
                let target = expr.get("target").unwrap_or(&Value::Null);
                let range = expr.get("range").unwrap_or(&Value::Null);
                let high = range.get(0).and_then(|v| v.as_i64()).unwrap_or(0);
                let low = range.get(1).and_then(|v| v.as_i64()).unwrap_or(0);
                let slice_width = high - low + 1;

                let target_name = self.expression_to_id(graph, target, access_mode);

                let mut node_data: HashMap<String, Value> = HashMap::new();
                node_data.insert("type".to_string(), json!("bit_slice"));
                node_data.insert(
                    "display_name".to_string(),
                    json!(format!("{}[{}:{}]", target_name, high, low)),
                );
                node_data.insert("expression".to_string(), expr.clone());
                node_data.insert("access_mode".to_string(), json!(access_mode));
                node_data.insert("bit_width".to_string(), json!(slice_width));

                let node = Node::new(
                    Some(expr_id.clone()),
                    Some(node_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None,
                    None,
                );
                graph.add_node(node);

                if access_mode == "read" {
                    let target_node_id = self.get_or_create_node_for_expression(
                        graph, target, "read", None,
                    )?;
                    let mut ba_data: HashMap<String, Value> = HashMap::new();
                    ba_data.insert("type".to_string(), json!("bit_access"));
                    let edge = Edge::new(target_node_id, expr_id.clone(), None, Some(ba_data));
                    graph.add_edge(edge);
                } else {
                    // For writes, create index nodes if array access target
                    if target.get("type").and_then(|v| v.as_str()) == Some("array_access") {
                        if let Some(idx_expr) = target.get("index") {
                            let _ = self.get_or_create_node_for_expression(
                                graph, idx_expr, "read", None,
                            );
                        }
                    }
                }

                Ok(expr_id)
            }

            "binary_op" => {
                let left = expr.get("left").unwrap_or(&Value::Null);
                let right = expr.get("right").unwrap_or(&Value::Null);
                let operator = expr
                    .get("operator")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");

                let left_name = self.expression_to_id(graph, left, "read");
                let right_name = self.expression_to_id(graph, right, "read");

                let left_node_id =
                    self.get_or_create_node_for_expression(graph, left, "read", None)?;
                let right_node_id =
                    self.get_or_create_node_for_expression(graph, right, "read", None)?;

                let left_width = graph
                    .nodes
                    .get(&left_node_id)
                    .and_then(|n| n.data.get("bit_width"))
                    .and_then(|v| v.as_i64());
                let right_width = graph
                    .nodes
                    .get(&right_node_id)
                    .and_then(|n| n.data.get("bit_width"))
                    .and_then(|v| v.as_i64());

                let result_width =
                    Self::infer_bit_width(operator, left_width, right_width, Some(right));

                let mut node_data: HashMap<String, Value> = HashMap::new();
                node_data.insert("type".to_string(), json!("operation"));
                node_data.insert("operator".to_string(), json!(operator));
                node_data.insert(
                    "display_name".to_string(),
                    json!(format!("({} {} {})", left_name, operator, right_name)),
                );
                node_data.insert("expression".to_string(), expr.clone());
                if let Some(rw) = result_width {
                    node_data.insert("bit_width".to_string(), json!(rw));
                }

                let node = Node::new(
                    Some(expr_id.clone()),
                    Some(node_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None,
                    None,
                );
                graph.add_node(node);

                // Edges to operands
                let mut l_data: HashMap<String, Value> = HashMap::new();
                l_data.insert("type".to_string(), json!("operand"));
                l_data.insert("position".to_string(), json!("left"));
                let l_edge = Edge::new(left_node_id, expr_id.clone(), None, Some(l_data));
                graph.add_edge(l_edge);

                let mut r_data: HashMap<String, Value> = HashMap::new();
                r_data.insert("type".to_string(), json!("operand"));
                r_data.insert("position".to_string(), json!("right"));
                let r_edge = Edge::new(right_node_id, expr_id.clone(), None, Some(r_data));
                graph.add_edge(r_edge);

                Ok(expr_id)
            }

            "literal" => {
                let value = expr.get("value").and_then(|v| v.as_i64()).unwrap_or(0);
                let mut node_data: HashMap<String, Value> = HashMap::new();
                node_data.insert("type".to_string(), json!("literal"));
                node_data.insert("value".to_string(), json!(value));
                node_data.insert("display_name".to_string(), json!(value.to_string()));

                let node = Node::new(
                    Some(expr_id.clone()),
                    Some(node_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None,
                    None,
                );
                graph.add_node(node);
                Ok(expr_id)
            }

            "sized_literal" => {
                let fmt = expr
                    .get("format")
                    .and_then(|v| v.as_str())
                    .unwrap_or("bin");
                let width = expr.get("width").and_then(|v| v.as_i64()).unwrap_or(0);
                let value = expr.get("value").and_then(|v| v.as_i64()).unwrap_or(0);
                let original_digits = expr
                    .get("original_digits")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let fmt_char = match fmt {
                    "bin" => "b",
                    "hex" => "h",
                    "dec" => "d",
                    _ => "b",
                };

                let mut node_data: HashMap<String, Value> = HashMap::new();
                node_data.insert("type".to_string(), json!("sized_literal"));
                node_data.insert("value".to_string(), json!(value));
                node_data.insert("width".to_string(), json!(width));
                node_data.insert("format".to_string(), json!(fmt));
                node_data.insert("original_digits".to_string(), json!(original_digits));
                node_data.insert("bit_width".to_string(), json!(width));
                node_data.insert(
                    "display_name".to_string(),
                    json!(format!("{}'{}{}", width, fmt_char, original_digits)),
                );

                let node = Node::new(
                    Some(expr_id.clone()),
                    Some(node_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None,
                    None,
                );
                graph.add_node(node);
                Ok(expr_id)
            }

            "binary_wildcard" => {
                let pattern = expr
                    .get("pattern")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let width = expr.get("width").and_then(|v| v.as_i64()).unwrap_or(0);
                let original = expr
                    .get("original")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");

                let mut node_data: HashMap<String, Value> = HashMap::new();
                node_data.insert("type".to_string(), json!("binary_wildcard"));
                node_data.insert("pattern".to_string(), json!(pattern));
                node_data.insert("width".to_string(), json!(width));
                node_data.insert("bit_width".to_string(), json!(width));
                node_data.insert("display_name".to_string(), json!(original));

                let node = Node::new(
                    Some(expr_id.clone()),
                    Some(node_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None,
                    None,
                );
                graph.add_node(node);
                Ok(expr_id)
            }

            "concatenation" => {
                let parts = expr
                    .get("parts")
                    .and_then(|v| v.as_array())
                    .cloned()
                    .unwrap_or_default();

                let sub_names: Vec<String> = parts
                    .iter()
                    .map(|p| self.expression_to_id(graph, p, "read"))
                    .collect();

                // Create sub-nodes and calculate total width
                let mut sub_node_ids = Vec::new();
                let mut total_width: i64 = 0;
                let mut all_widths_known = true;

                for part in &parts {
                    let sub_id =
                        self.get_or_create_node_for_expression(graph, part, "read", None)?;
                    if let Some(node) = graph.nodes.get(&sub_id) {
                        if let Some(w) = node.data.get("bit_width").and_then(|v| v.as_i64()) {
                            total_width += w;
                        } else {
                            all_widths_known = false;
                        }
                    } else {
                        all_widths_known = false;
                    }
                    sub_node_ids.push(sub_id);
                }

                let mut node_data: HashMap<String, Value> = HashMap::new();
                node_data.insert("type".to_string(), json!("concatenation"));
                node_data.insert(
                    "display_name".to_string(),
                    json!(format!("{{{}}}", sub_names.join(", "))),
                );
                node_data.insert("expression".to_string(), expr.clone());
                if all_widths_known && total_width > 0 {
                    node_data.insert("bit_width".to_string(), json!(total_width));
                }

                let node = Node::new(
                    Some(expr_id.clone()),
                    Some(node_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None,
                    None,
                );
                graph.add_node(node);

                for (i, sub_id) in sub_node_ids.iter().enumerate() {
                    let mut ed: HashMap<String, Value> = HashMap::new();
                    ed.insert("type".to_string(), json!("concatenation_input"));
                    ed.insert("position".to_string(), json!(i));
                    let edge = Edge::new(sub_id.clone(), expr_id.clone(), None, Some(ed));
                    graph.add_edge(edge);
                }

                Ok(expr_id)
            }

            "repetition" => {
                let sub_expr = expr.get("expression").unwrap_or(&Value::Null);
                let count = expr.get("count").and_then(|v| v.as_i64()).unwrap_or(0);
                let sub_name = self.expression_to_id(graph, sub_expr, "read");

                let sub_id =
                    self.get_or_create_node_for_expression(graph, sub_expr, "read", None)?;
                let sub_width = graph
                    .nodes
                    .get(&sub_id)
                    .and_then(|n| n.data.get("bit_width"))
                    .and_then(|v| v.as_i64());

                let mut node_data: HashMap<String, Value> = HashMap::new();
                node_data.insert("type".to_string(), json!("repetition"));
                node_data.insert("count".to_string(), json!(count));
                node_data.insert(
                    "display_name".to_string(),
                    json!(format!("{{{}{{{}}}}}", count, sub_name)),
                );
                node_data.insert("expression".to_string(), expr.clone());
                if let Some(sw) = sub_width {
                    node_data.insert("bit_width".to_string(), json!(count * sw));
                }

                let node = Node::new(
                    Some(expr_id.clone()),
                    Some(node_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None,
                    None,
                );
                graph.add_node(node);

                let mut ed: HashMap<String, Value> = HashMap::new();
                ed.insert("type".to_string(), json!("repetition_input"));
                let edge = Edge::new(sub_id, expr_id.clone(), None, Some(ed));
                graph.add_edge(edge);

                Ok(expr_id)
            }

            "ternary_op" => {
                let condition = expr.get("condition").unwrap_or(&Value::Null);
                let if_true = expr.get("if_true").unwrap_or(&Value::Null);
                let if_false = expr.get("if_false").unwrap_or(&Value::Null);

                let cond_name = self.expression_to_id(graph, condition, "read");
                let true_name = self.expression_to_id(graph, if_true, "read");
                let false_name = self.expression_to_id(graph, if_false, "read");

                let cond_id =
                    self.get_or_create_node_for_expression(graph, condition, "read", None)?;
                let true_id =
                    self.get_or_create_node_for_expression(graph, if_true, "read", None)?;
                let false_id =
                    self.get_or_create_node_for_expression(graph, if_false, "read", None)?;

                let true_width = graph
                    .nodes
                    .get(&true_id)
                    .and_then(|n| n.data.get("bit_width"))
                    .and_then(|v| v.as_i64());
                let false_width = graph
                    .nodes
                    .get(&false_id)
                    .and_then(|n| n.data.get("bit_width"))
                    .and_then(|v| v.as_i64());

                let result_width = match (true_width, false_width) {
                    (Some(tw), Some(fw)) => Some(tw.max(fw)),
                    (Some(tw), None) => Some(tw),
                    (None, Some(fw)) => Some(fw),
                    (None, None) => None,
                };

                let mut node_data: HashMap<String, Value> = HashMap::new();
                node_data.insert("type".to_string(), json!("ternary_op"));
                node_data.insert(
                    "display_name".to_string(),
                    json!(format!("{} ? {} : {}", cond_name, true_name, false_name)),
                );
                node_data.insert("expression".to_string(), expr.clone());
                if let Some(rw) = result_width {
                    node_data.insert("bit_width".to_string(), json!(rw));
                }

                let node = Node::new(
                    Some(expr_id.clone()),
                    Some(node_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None,
                    None,
                );
                graph.add_node(node);

                // Edges
                let mut cd: HashMap<String, Value> = HashMap::new();
                cd.insert("type".to_string(), json!("ternary_condition"));
                let ce = Edge::new(cond_id, expr_id.clone(), None, Some(cd));
                graph.add_edge(ce);

                let mut td: HashMap<String, Value> = HashMap::new();
                td.insert("type".to_string(), json!("ternary_true"));
                let te = Edge::new(true_id, expr_id.clone(), None, Some(td));
                graph.add_edge(te);

                let mut fd: HashMap<String, Value> = HashMap::new();
                fd.insert("type".to_string(), json!("ternary_false"));
                let fe = Edge::new(false_id, expr_id.clone(), None, Some(fd));
                graph.add_edge(fe);

                Ok(expr_id)
            }

            "unary_op" => {
                let operand = expr.get("operand").unwrap_or(&Value::Null);
                let operator = expr
                    .get("operator")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let operand_name = self.expression_to_id(graph, operand, "read");

                let operand_id =
                    self.get_or_create_node_for_expression(graph, operand, "read", None)?;
                let operand_width = graph
                    .nodes
                    .get(&operand_id)
                    .and_then(|n| n.data.get("bit_width"))
                    .and_then(|v| v.as_i64());
                let result_width = Self::infer_unary_width(operator, operand_width);

                let mut node_data: HashMap<String, Value> = HashMap::new();
                node_data.insert("type".to_string(), json!("operation"));
                node_data.insert("operator".to_string(), json!(operator));
                node_data.insert(
                    "display_name".to_string(),
                    json!(format!("({}{})", operator, operand_name)),
                );
                node_data.insert("expression".to_string(), expr.clone());
                if let Some(rw) = result_width {
                    node_data.insert("bit_width".to_string(), json!(rw));
                }

                let node = Node::new(
                    Some(expr_id.clone()),
                    Some(node_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None,
                    None,
                );
                graph.add_node(node);

                let mut od: HashMap<String, Value> = HashMap::new();
                od.insert("type".to_string(), json!("operand"));
                od.insert("position".to_string(), json!("unary"));
                let oe = Edge::new(operand_id, expr_id.clone(), None, Some(od));
                graph.add_edge(oe);

                Ok(expr_id)
            }

            "reduction_op" => {
                let operand = expr.get("operand").unwrap_or(&Value::Null);
                let operator = expr
                    .get("operator")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let operand_name = self.expression_to_id(graph, operand, "read");

                let operand_id =
                    self.get_or_create_node_for_expression(graph, operand, "read", None)?;

                let mut node_data: HashMap<String, Value> = HashMap::new();
                node_data.insert("type".to_string(), json!("operation"));
                node_data.insert(
                    "operator".to_string(),
                    json!(format!("reduce_{}", operator)),
                );
                node_data.insert(
                    "display_name".to_string(),
                    json!(format!("({}{})", operator, operand_name)),
                );
                node_data.insert("expression".to_string(), expr.clone());
                node_data.insert("bit_width".to_string(), json!(1));

                let node = Node::new(
                    Some(expr_id.clone()),
                    Some(node_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None,
                    None,
                );
                graph.add_node(node);

                let mut od: HashMap<String, Value> = HashMap::new();
                od.insert("type".to_string(), json!("operand"));
                od.insert("position".to_string(), json!("unary"));
                let oe = Edge::new(operand_id, expr_id.clone(), None, Some(od));
                graph.add_edge(oe);

                Ok(expr_id)
            }

            "cam_lookup" => {
                let cam_expr = expr.get("target").unwrap_or(&Value::Null);
                let key_expr = expr.get("key").unwrap_or(&Value::Null);
                let cam_info = expr.get("cam_info").cloned().unwrap_or(Value::Null);

                let cam_node_id =
                    self.get_or_create_node_for_expression(graph, cam_expr, "read", None)?;
                let key_node_id =
                    self.get_or_create_node_for_expression(graph, key_expr, "read", None)?;

                let set_node_id = if let Some(set_index) = expr.get("set_index") {
                    if !set_index.is_null() {
                        Some(self.get_or_create_node_for_expression(
                            graph, set_index, "read", None,
                        )?)
                    } else {
                        None
                    }
                } else {
                    None
                };

                let num_ways = cam_info
                    .get("num_ways")
                    .and_then(|v| v.as_i64())
                    .unwrap_or(1);

                let mut node_data: HashMap<String, Value> = HashMap::new();
                node_data.insert("type".to_string(), json!("cam_lookup"));
                node_data.insert(
                    "cam_name".to_string(),
                    expr.get("cam_name").cloned().unwrap_or(Value::Null),
                );
                node_data.insert("cam_info".to_string(), cam_info);
                node_data.insert("bit_width".to_string(), json!(num_ways));
                node_data.insert(
                    "display_name".to_string(),
                    json!(format!("{}@[{}]", cam_node_id, key_node_id)),
                );
                node_data.insert("expression".to_string(), expr.clone());

                let node = Node::new(
                    Some(expr_id.clone()),
                    Some(node_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None,
                    None,
                );
                graph.add_node(node);

                // Edges
                let mut cd: HashMap<String, Value> = HashMap::new();
                cd.insert("type".to_string(), json!("cam_array"));
                cd.insert("position".to_string(), json!("cam"));
                let ce = Edge::new(cam_node_id, expr_id.clone(), None, Some(cd));
                graph.add_edge(ce);

                let mut kd: HashMap<String, Value> = HashMap::new();
                kd.insert("type".to_string(), json!("cam_key"));
                kd.insert("position".to_string(), json!("key"));
                let ke = Edge::new(key_node_id, expr_id.clone(), None, Some(kd));
                graph.add_edge(ke);

                if let Some(sid) = set_node_id {
                    let mut sd: HashMap<String, Value> = HashMap::new();
                    sd.insert("type".to_string(), json!("cam_set_index"));
                    sd.insert("position".to_string(), json!("set"));
                    let se = Edge::new(sid, expr_id.clone(), None, Some(sd));
                    graph.add_edge(se);
                }

                Ok(expr_id)
            }

            "builtin_call" => {
                let builtin = expr
                    .get("builtin")
                    .and_then(|v| v.as_str())
                    .unwrap_or("ctz");
                let operand_expr = expr.get("operand").unwrap_or(&Value::Null);

                let operand_id =
                    self.get_or_create_node_for_expression(graph, operand_expr, "read", None)?;

                let operand_width = graph
                    .nodes
                    .get(&operand_id)
                    .and_then(|n| n.data.get("bit_width"))
                    .and_then(|v| v.as_i64())
                    .unwrap_or(32);

                let result_width = if operand_width > 0 {
                    ((operand_width + 2) as f64).log2().ceil() as i64
                } else {
                    1
                };

                let mut node_data: HashMap<String, Value> = HashMap::new();
                node_data.insert("type".to_string(), json!("builtin_call"));
                node_data.insert("builtin".to_string(), json!(builtin));
                node_data.insert("bit_width".to_string(), json!(result_width));
                node_data.insert("operand_width".to_string(), json!(operand_width));
                node_data.insert(
                    "display_name".to_string(),
                    json!(format!("{}({})", builtin, operand_id)),
                );
                node_data.insert("expression".to_string(), expr.clone());

                let node = Node::new(
                    Some(expr_id.clone()),
                    Some(node_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None,
                    None,
                );
                graph.add_node(node);

                let mut od: HashMap<String, Value> = HashMap::new();
                od.insert("type".to_string(), json!("builtin_operand"));
                od.insert("position".to_string(), json!("operand"));
                let oe = Edge::new(operand_id, expr_id.clone(), None, Some(od));
                graph.add_edge(oe);

                Ok(expr_id)
            }

            "fp_intrinsic_call" => {
                // Placeholder for FP intrinsics
                let intrinsic_name = expr
                    .get("intrinsic")
                    .and_then(|v| v.as_str())
                    .unwrap_or("fp_unknown");

                let mut node_data: HashMap<String, Value> = HashMap::new();
                node_data.insert("type".to_string(), json!("fp_operation"));
                node_data.insert("fp_intrinsic".to_string(), json!(intrinsic_name));
                node_data.insert("display_name".to_string(), json!(intrinsic_name));
                node_data.insert("expression".to_string(), expr.clone());
                node_data.insert("bit_width".to_string(), json!(32)); // placeholder

                let node = Node::new(
                    Some(expr_id.clone()),
                    Some(node_data),
                    false, false, None, false, None, None, false, false, 0, false, false, None,
                    None,
                );
                graph.add_node(node);

                // Create edges to operands
                if let Some(operands) = expr.get("operands").and_then(|v| v.as_array()) {
                    let positions = ["first", "second", "third"];
                    for (i, op_expr) in operands.iter().enumerate() {
                        let op_id = self.get_or_create_node_for_expression(
                            graph, op_expr, "read", None,
                        )?;
                        let pos = positions.get(i).unwrap_or(&"operand");
                        let mut od: HashMap<String, Value> = HashMap::new();
                        od.insert("type".to_string(), json!("fp_operand"));
                        od.insert("position".to_string(), json!(pos));
                        let oe = Edge::new(op_id, expr_id.clone(), None, Some(od));
                        graph.add_edge(oe);
                    }
                }

                if let Some(rm) = expr.get("rounding_mode") {
                    if !rm.is_null() {
                        let rm_id = self.get_or_create_node_for_expression(
                            graph, rm, "read", None,
                        )?;
                        let mut rd: HashMap<String, Value> = HashMap::new();
                        rd.insert("type".to_string(), json!("rounding_mode"));
                        rd.insert("position".to_string(), json!("rounding_mode"));
                        let re = Edge::new(rm_id, expr_id.clone(), None, Some(rd));
                        graph.add_edge(re);
                    }
                }

                Ok(expr_id)
            }

            _ => Err(format!("Unknown expression type: {}", expr_type)),
        }
    }
}
