// Statement parsing: assignments, if/else, for loops, case statements
// Ported from isa_parser.py statement methods.

use std::collections::{HashMap, HashSet};

use serde_json::{json, Value};

use crate::isa_lexer::TokenType;
use crate::resource_graph::{Edge, ResourceGraph};

use super::ISAParser;

impl ISAParser {
    // -----------------------------------------------------------------------
    // Assignment
    // -----------------------------------------------------------------------

    pub fn parse_assignment(&mut self, graph: &mut ResourceGraph) -> Result<(), String> {
        let left_side = self.parse_expression()?;

        // Check for 'when' clause (guarded assignment)
        let mut enable_expr = None;
        if self.check(&TokenType::When) {
            self.consume(&TokenType::When, "Expected 'when'")?;
            self.consume(&TokenType::Lparen, "Expected '(' after 'when'")?;
            enable_expr = Some(self.parse_expression()?);
            self.consume(&TokenType::Rparen, "Expected ')' after enable condition")?;
        }

        self.consume(&TokenType::Equals, "Expected '='")?;
        let right_side = self.parse_expression()?;
        self.consume(&TokenType::Semicolon, "Expected ';'")?;

        // Create assignment edge
        let left_node_id = self.get_or_create_node_for_expression(
            graph,
            &left_side,
            "write",
            enable_expr.as_ref(),
        )?;
        let right_node_id =
            self.get_or_create_node_for_expression(graph, &right_side, "read", None)?;

        let mut edge_data: HashMap<String, Value> = HashMap::new();
        edge_data.insert("type".to_string(), json!("assignment"));
        edge_data.insert("left".to_string(), left_side.clone());
        edge_data.insert("right".to_string(), right_side.clone());
        if let Some(ref en) = enable_expr {
            edge_data.insert("enable".to_string(), en.clone());
        }

        let edge = Edge::new(right_node_id.clone(), left_node_id.clone(), None, Some(edge_data));
        graph.add_edge(edge);

        // Track intermediate values for sequential assignments
        if left_side.get("type").and_then(|v| v.as_str()) == Some("identifier")
            && enable_expr.is_none()
        {
            let var_name = left_side
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if graph.nodes.contains_key(var_name) {
                let is_isa_state = graph.nodes[var_name]
                    .data
                    .get("type")
                    .and_then(|v| v.as_str())
                    == Some("isa_state");
                if is_isa_state {
                    self.intermediate_values
                        .insert(var_name.to_string(), right_node_id);
                }
            }
        }

        Ok(())
    }

    // -----------------------------------------------------------------------
    // For loop (compile-time unrolling)
    // -----------------------------------------------------------------------

    pub fn parse_for_loop(&mut self, graph: &mut ResourceGraph) -> Result<(), String> {
        self.consume(&TokenType::For, "Expected 'for'")?;
        self.consume(&TokenType::Lparen, "Expected '('")?;

        let loop_var = self.consume(&TokenType::Identifier, "Expected loop variable")?.value;

        self.consume(&TokenType::Semicolon, "Expected ';'")?;
        let start_value = self.parse_loop_value()?;
        self.consume(&TokenType::Semicolon, "Expected ';'")?;

        // Parse condition
        let condition_op = if self.check(&TokenType::LessThan) {
            self.advance();
            "<"
        } else if self.check(&TokenType::GreaterThan) {
            self.advance();
            ">"
        } else {
            return Err("Expected comparison operator in for loop condition".to_string());
        };

        let condition_value = self.parse_loop_value()?;
        self.consume(&TokenType::Semicolon, "Expected ';'")?;

        // Parse increment
        let increment_op = if self.check(&TokenType::Plus) {
            self.advance();
            "+"
        } else if self.check(&TokenType::Minus) {
            self.advance();
            "-"
        } else {
            return Err("Expected '+' or '-' in for loop increment".to_string());
        };

        let increment_value = self.parse_loop_value()?;
        self.consume(&TokenType::Rparen, "Expected ')'")?;

        // Parse loop body
        self.consume(&TokenType::Lbrace, "Expected '{'")?;

        let body_start = self.current;
        let mut brace_count = 1;
        while brace_count > 0 && !self.is_at_end() {
            if self.check(&TokenType::Lbrace) {
                brace_count += 1;
            } else if self.check(&TokenType::Rbrace) {
                brace_count -= 1;
            }
            if brace_count > 0 {
                self.advance();
            }
        }
        let body_end = self.current;
        self.consume(&TokenType::Rbrace, "Expected '}'")?;

        // Unroll the loop
        self.unroll_loop(
            graph,
            &loop_var,
            start_value,
            condition_op,
            condition_value,
            increment_op,
            increment_value,
            body_start,
            body_end,
        )?;

        Ok(())
    }

    fn unroll_loop(
        &mut self,
        graph: &mut ResourceGraph,
        loop_var: &str,
        start: i64,
        condition_op: &str,
        condition_value: i64,
        increment_op: &str,
        increment_value: i64,
        body_start: usize,
        body_end: usize,
    ) -> Result<(), String> {
        let saved_pos = self.current;

        // Calculate iterations
        let mut current_val = start;
        let mut iterations = Vec::new();
        const MAX_UNROLL_ITERATIONS: usize = 100_000;

        match condition_op {
            "<" => {
                while current_val < condition_value {
                    if iterations.len() >= MAX_UNROLL_ITERATIONS {
                        return Err(format!(
                            "For loop exceeded {} iterations ({}={}, cond {} {})",
                            MAX_UNROLL_ITERATIONS, loop_var, current_val,
                            condition_op, condition_value
                        ));
                    }
                    iterations.push(current_val);
                    if increment_op == "+" {
                        current_val += increment_value;
                    } else {
                        current_val -= increment_value;
                    }
                }
            }
            ">" => {
                while current_val > condition_value {
                    if iterations.len() >= MAX_UNROLL_ITERATIONS {
                        return Err(format!(
                            "For loop exceeded {} iterations ({}={}, cond {} {})",
                            MAX_UNROLL_ITERATIONS, loop_var, current_val,
                            condition_op, condition_value
                        ));
                    }
                    iterations.push(current_val);
                    if increment_op == "+" {
                        current_val += increment_value;
                    } else {
                        current_val -= increment_value;
                    }
                }
            }
            _ => {}
        }

        // Execute body for each iteration
        for iteration_value in iterations {
            self.loop_vars.insert(loop_var.to_string(), iteration_value);
            self.current = body_start;
            self.parse_body_statements(graph, body_end, None)?;
        }

        self.loop_vars.remove(loop_var);
        self.current = saved_pos;

        Ok(())
    }

    // -----------------------------------------------------------------------
    // Body statement parsing (shared by if/for/case)
    // -----------------------------------------------------------------------

    pub fn parse_body_statements(
        &mut self,
        graph: &mut ResourceGraph,
        body_end: usize,
        mut collect_assignments: Option<&mut Vec<Value>>,
    ) -> Result<(), String> {
        while self.current < body_end {
            if self.check(&TokenType::Identifier) {
                if let Some(ref mut assignments) = collect_assignments {
                    // Collect for later ternary creation
                    let left_expr = self.parse_expression()?;
                    self.consume(&TokenType::Equals, "Expected '='")?;
                    let right_expr = self.parse_expression()?;
                    self.consume(&TokenType::Semicolon, "Expected ';'")?;
                    assignments.push(json!({"left": left_expr, "right": right_expr}));
                } else {
                    self.parse_assignment(graph)?;
                }
            } else if self.check(&TokenType::If) {
                self.parse_if_statement(graph)?;
            } else if self.check(&TokenType::For) {
                self.parse_for_loop(graph)?;
            } else if self.check(&TokenType::Case) {
                self.parse_case_statement(graph)?;
            } else if self.check(&TokenType::Var) {
                self.parse_var_declaration(graph)?;
            } else {
                self.advance();
            }
        }
        Ok(())
    }

    // -----------------------------------------------------------------------
    // If statement
    // -----------------------------------------------------------------------

    pub fn parse_if_statement(&mut self, graph: &mut ResourceGraph) -> Result<(), String> {
        self.consume(&TokenType::If, "Expected 'if'")?;
        self.consume(&TokenType::Lparen, "Expected '('")?;

        let condition_expr = self.parse_expression()?;

        self.consume(&TokenType::Rparen, "Expected ')'")?;
        self.consume(&TokenType::Lbrace, "Expected '{'")?;

        // Collect if-body tokens
        let body_start = self.current;
        let mut brace_count = 1;
        while brace_count > 0 && !self.is_at_end() {
            if self.check(&TokenType::Lbrace) {
                brace_count += 1;
            } else if self.check(&TokenType::Rbrace) {
                brace_count -= 1;
            }
            if brace_count > 0 {
                self.advance();
            }
        }
        let body_end = self.current;
        self.consume(&TokenType::Rbrace, "Expected '}'")?;

        // Check for else clause
        let mut else_body_start = None;
        let mut else_body_end = None;
        if self.check(&TokenType::Else) {
            self.advance();
            self.consume(&TokenType::Lbrace, "Expected '{'")?;
            else_body_start = Some(self.current);
            brace_count = 1;
            while brace_count > 0 && !self.is_at_end() {
                if self.check(&TokenType::Lbrace) {
                    brace_count += 1;
                } else if self.check(&TokenType::Rbrace) {
                    brace_count -= 1;
                }
                if brace_count > 0 {
                    self.advance();
                }
            }
            else_body_end = Some(self.current);
            self.consume(&TokenType::Rbrace, "Expected '}'")?;
        }

        // Check if condition can be evaluated at parse time
        if self.can_evaluate(&condition_expr) {
            let condition_value = self.evaluate_expression(&condition_expr)?;

            if condition_value != 0 {
                let saved_pos = self.current;
                self.current = body_start;
                self.parse_body_statements(graph, body_end, None)?;
                self.current = saved_pos;
            } else if let Some(ebs) = else_body_start {
                let saved_pos = self.current;
                self.current = ebs;
                self.parse_body_statements(graph, else_body_end.unwrap(), None)?;
                self.current = saved_pos;
            }
        } else {
            // Runtime conditional - create ternary muxes
            let saved_pos = self.current;

            // Collect if assignments
            let mut if_assignments = Vec::new();
            self.current = body_start;
            self.parse_body_statements(graph, body_end, Some(&mut if_assignments))?;

            // Collect else assignments
            let mut else_assignments = Vec::new();
            if let Some(ebs) = else_body_start {
                self.current = ebs;
                self.parse_body_statements(
                    graph,
                    else_body_end.unwrap(),
                    Some(&mut else_assignments),
                )?;
            }

            // Match if/else by target
            let mut else_by_target: HashMap<String, Value> = HashMap::new();
            for ea in &else_assignments {
                let left = ea.get("left").unwrap_or(&Value::Null);
                let left_str = self.expr_to_string(left);
                else_by_target.insert(left_str, ea.get("right").cloned().unwrap_or(Value::Null));
            }

            for ia in &if_assignments {
                let left = ia.get("left").unwrap_or(&Value::Null);
                let left_str = self.expr_to_string(left);

                if let Some(else_right) = else_by_target.get(&left_str) {
                    // Both branches assign to same target - create ternary
                    let ternary_expr = json!({
                        "type": "ternary_op",
                        "condition": condition_expr,
                        "if_true": ia.get("right").unwrap_or(&Value::Null),
                        "if_false": else_right
                    });

                    let left_node_id = self.get_or_create_node_for_expression(
                        graph,
                        left,
                        "write",
                        None,
                    )?;
                    let right_node_id = self.get_or_create_node_for_expression(
                        graph,
                        &ternary_expr,
                        "read",
                        None,
                    )?;

                    let mut edge_data: HashMap<String, Value> = HashMap::new();
                    edge_data.insert("type".to_string(), json!("assignment"));
                    edge_data.insert("left".to_string(), left.clone());
                    edge_data.insert("right".to_string(), ternary_expr);
                    let edge = Edge::new(right_node_id, left_node_id, None, Some(edge_data));
                    graph.add_edge(edge);
                } else {
                    // Only if branch assigns - use condition as write enable
                    let left_node_id = self.get_or_create_node_for_expression(
                        graph,
                        left,
                        "write",
                        Some(&condition_expr),
                    )?;
                    let right_node_id = self.get_or_create_node_for_expression(
                        graph,
                        ia.get("right").unwrap_or(&Value::Null),
                        "read",
                        None,
                    )?;

                    let mut edge_data: HashMap<String, Value> = HashMap::new();
                    edge_data.insert("type".to_string(), json!("assignment"));
                    edge_data.insert("left".to_string(), left.clone());
                    edge_data.insert(
                        "right".to_string(),
                        ia.get("right").cloned().unwrap_or(Value::Null),
                    );
                    edge_data.insert("enable".to_string(), condition_expr.clone());
                    let edge = Edge::new(right_node_id, left_node_id, None, Some(edge_data));
                    graph.add_edge(edge);
                }
            }

            // Handle else-only assignments
            let if_targets: HashSet<String> = if_assignments
                .iter()
                .map(|ia| self.expr_to_string(ia.get("left").unwrap_or(&Value::Null)))
                .collect();

            for ea in &else_assignments {
                let left = ea.get("left").unwrap_or(&Value::Null);
                let left_str = self.expr_to_string(left);
                if !if_targets.contains(&left_str) {
                    let neg_condition = json!({
                        "type": "unary_op",
                        "operator": "!",
                        "operand": condition_expr
                    });
                    let left_node_id = self.get_or_create_node_for_expression(
                        graph,
                        left,
                        "write",
                        Some(&neg_condition),
                    )?;
                    let right_node_id = self.get_or_create_node_for_expression(
                        graph,
                        ea.get("right").unwrap_or(&Value::Null),
                        "read",
                        None,
                    )?;

                    let mut edge_data: HashMap<String, Value> = HashMap::new();
                    edge_data.insert("type".to_string(), json!("assignment"));
                    edge_data.insert("left".to_string(), left.clone());
                    edge_data.insert(
                        "right".to_string(),
                        ea.get("right").cloned().unwrap_or(Value::Null),
                    );
                    edge_data.insert("enable".to_string(), neg_condition);
                    let edge = Edge::new(right_node_id, left_node_id, None, Some(edge_data));
                    graph.add_edge(edge);
                }
            }

            self.current = saved_pos;
        }

        Ok(())
    }

    // -----------------------------------------------------------------------
    // Case statement
    // -----------------------------------------------------------------------

    pub fn parse_case_statement(&mut self, graph: &mut ResourceGraph) -> Result<(), String> {
        self.consume(&TokenType::Case, "Expected 'case'")?;
        self.consume(&TokenType::Lparen, "Expected '('")?;

        let selector_expr = self.parse_expression()?;

        self.consume(&TokenType::Rparen, "Expected ')'")?;
        self.consume(&TokenType::Lbrace, "Expected '{'")?;

        // Parse case arms
        let mut case_arms: Vec<Value> = Vec::new();
        while !self.check(&TokenType::Rbrace) && !self.is_at_end() {
            let case_value = self.parse_expression()?;
            self.consume(&TokenType::Colon, "Expected ':' after case value")?;

            let mut arm_statements = Vec::new();
            if self.check(&TokenType::Identifier) {
                let left_side = self.parse_expression()?;
                self.consume(&TokenType::Equals, "Expected '='")?;
                let right_side = self.parse_expression()?;
                self.consume(&TokenType::Semicolon, "Expected ';'")?;
                arm_statements.push(json!({"left": left_side, "right": right_side}));
            }

            case_arms.push(json!({
                "value": case_value,
                "statements": arm_statements
            }));
        }

        self.consume(&TokenType::Rbrace, "Expected '}'")?;

        // Evaluate at parse time if possible
        if self.can_evaluate(&selector_expr) {
            let selector_value = self.evaluate_expression(&selector_expr)?;

            for arm in &case_arms {
                let arm_value_expr = arm.get("value").unwrap_or(&Value::Null);
                if self.can_evaluate(arm_value_expr) {
                    let arm_value = self.evaluate_expression(arm_value_expr)?;
                    if arm_value == selector_value {
                        if let Some(stmts) = arm.get("statements").and_then(|v| v.as_array()) {
                            for stmt in stmts {
                                let left = stmt.get("left").unwrap_or(&Value::Null);
                                let right = stmt.get("right").unwrap_or(&Value::Null);
                                let left_id = self.get_or_create_node_for_expression(
                                    graph, left, "write", None,
                                )?;
                                let right_id = self.get_or_create_node_for_expression(
                                    graph, right, "read", None,
                                )?;
                                let mut ed: HashMap<String, Value> = HashMap::new();
                                ed.insert("type".to_string(), json!("assignment"));
                                ed.insert("left".to_string(), left.clone());
                                ed.insert("right".to_string(), right.clone());
                                let edge = Edge::new(right_id, left_id, None, Some(ed));
                                graph.add_edge(edge);
                            }
                        }
                        break;
                    }
                }
            }
        } else {
            // Runtime case - check if all arms target same variable for nested ternary
            let all_single_target = case_arms.len() >= 2 && {
                let mut target_vars = HashSet::new();
                let mut ok = true;
                for arm in &case_arms {
                    let stmts = arm.get("statements").and_then(|v| v.as_array());
                    if let Some(stmts) = stmts {
                        if stmts.len() != 1 {
                            ok = false;
                            break;
                        }
                        let left = stmts[0].get("left").unwrap_or(&Value::Null);
                        if left.get("type").and_then(|v| v.as_str()) == Some("identifier") {
                            target_vars.insert(
                                left.get("name")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("")
                                    .to_string(),
                            );
                        } else {
                            ok = false;
                            break;
                        }
                    } else {
                        ok = false;
                        break;
                    }
                }
                ok && target_vars.len() == 1
            };

            if all_single_target {
                // Build nested ternary
                let ternary_expr =
                    self.build_nested_ternary(&case_arms, &selector_expr, 0);
                let target_expr = case_arms[0]
                    .get("statements")
                    .and_then(|v| v.get(0))
                    .and_then(|v| v.get("left"))
                    .cloned()
                    .unwrap_or(Value::Null);

                let left_id =
                    self.get_or_create_node_for_expression(graph, &target_expr, "write", None)?;
                let right_id =
                    self.get_or_create_node_for_expression(graph, &ternary_expr, "read", None)?;

                let mut ed: HashMap<String, Value> = HashMap::new();
                ed.insert("type".to_string(), json!("assignment"));
                ed.insert("left".to_string(), target_expr);
                ed.insert("right".to_string(), ternary_expr);
                let edge = Edge::new(right_id, left_id, None, Some(ed));
                graph.add_edge(edge);
            } else {
                // Fallback: conditional assignments per arm
                for arm in &case_arms {
                    let arm_condition = json!({
                        "type": "binary_op",
                        "operator": "==",
                        "left": selector_expr,
                        "right": arm.get("value").unwrap_or(&Value::Null)
                    });
                    let _condition_id = self.get_or_create_node_for_expression(
                        graph,
                        &arm_condition,
                        "read",
                        None,
                    )?;

                    if let Some(stmts) = arm.get("statements").and_then(|v| v.as_array()) {
                        for stmt in stmts {
                            let left = stmt.get("left").unwrap_or(&Value::Null);
                            let right = stmt.get("right").unwrap_or(&Value::Null);
                            let left_id = self.get_or_create_node_for_expression(
                                graph,
                                left,
                                "write",
                                Some(&arm_condition),
                            )?;
                            let right_id = self.get_or_create_node_for_expression(
                                graph,
                                right,
                                "read",
                                None,
                            )?;
                            let mut ed: HashMap<String, Value> = HashMap::new();
                            ed.insert("type".to_string(), json!("assignment"));
                            ed.insert("left".to_string(), left.clone());
                            ed.insert("right".to_string(), right.clone());
                            ed.insert("enable".to_string(), arm_condition.clone());
                            let edge = Edge::new(right_id, left_id, None, Some(ed));
                            graph.add_edge(edge);
                        }
                    }
                }
            }
        }

        Ok(())
    }

    fn build_nested_ternary(
        &self,
        arms: &[Value],
        selector: &Value,
        idx: usize,
    ) -> Value {
        if idx == arms.len() - 1 {
            // Last arm: default case
            arms[idx]
                .get("statements")
                .and_then(|v| v.get(0))
                .and_then(|v| v.get("right"))
                .cloned()
                .unwrap_or(Value::Null)
        } else {
            let condition = json!({
                "type": "binary_op",
                "operator": "==",
                "left": selector,
                "right": arms[idx].get("value").unwrap_or(&Value::Null)
            });
            json!({
                "type": "ternary_op",
                "condition": condition,
                "if_true": arms[idx].get("statements")
                    .and_then(|v| v.get(0))
                    .and_then(|v| v.get("right"))
                    .unwrap_or(&Value::Null),
                "if_false": self.build_nested_ternary(arms, selector, idx + 1)
            })
        }
    }
}
