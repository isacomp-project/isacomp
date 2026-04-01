// Expression parsing - precedence climbing parser
// Ported from isa_parser.py parse_expression and related methods.

use serde_json::{json, Value};

use crate::isa_lexer::TokenType;

use super::ISAParser;

impl ISAParser {
    // -----------------------------------------------------------------------
    // Expression parsing entry point
    // -----------------------------------------------------------------------

    pub fn parse_expression(&mut self) -> Result<Value, String> {
        self.parse_ternary()
    }

    fn parse_ternary(&mut self) -> Result<Value, String> {
        let mut expr = self.parse_logical_or()?;

        if self.match_token(&[TokenType::Question]) {
            let true_expr = self.parse_logical_or()?;
            self.consume(&TokenType::Colon, "Expected ':' in ternary operator")?;
            let false_expr = self.parse_ternary()?;
            expr = json!({
                "type": "ternary_op",
                "condition": expr,
                "if_true": true_expr,
                "if_false": false_expr
            });
        }

        Ok(expr)
    }

    fn parse_logical_or(&mut self) -> Result<Value, String> {
        let mut expr = self.parse_logical_and()?;

        while self.match_token(&[TokenType::LogicalOr]) {
            let right = self.parse_logical_and()?;
            expr = json!({
                "type": "binary_op",
                "operator": "||",
                "left": expr,
                "right": right
            });
        }

        Ok(expr)
    }

    fn parse_logical_and(&mut self) -> Result<Value, String> {
        let mut expr = self.parse_bitwise_or()?;

        while self.match_token(&[TokenType::LogicalAnd]) {
            let right = self.parse_bitwise_or()?;
            expr = json!({
                "type": "binary_op",
                "operator": "&&",
                "left": expr,
                "right": right
            });
        }

        Ok(expr)
    }

    fn parse_bitwise_or(&mut self) -> Result<Value, String> {
        let mut expr = self.parse_bitwise_xor()?;

        while self.match_token(&[TokenType::Pipe]) {
            let op = self.previous().value.clone();
            let right = self.parse_bitwise_xor()?;
            expr = json!({
                "type": "binary_op",
                "operator": op,
                "left": expr,
                "right": right
            });
        }

        Ok(expr)
    }

    fn parse_bitwise_xor(&mut self) -> Result<Value, String> {
        let mut expr = self.parse_bitwise_and()?;

        while self.match_token(&[TokenType::Caret]) {
            let op = self.previous().value.clone();
            let right = self.parse_bitwise_and()?;
            expr = json!({
                "type": "binary_op",
                "operator": op,
                "left": expr,
                "right": right
            });
        }

        Ok(expr)
    }

    fn parse_bitwise_and(&mut self) -> Result<Value, String> {
        let mut expr = self.parse_equality()?;

        while self.match_token(&[TokenType::Ampersand]) {
            let op = self.previous().value.clone();
            let right = self.parse_equality()?;
            expr = json!({
                "type": "binary_op",
                "operator": op,
                "left": expr,
                "right": right
            });
        }

        Ok(expr)
    }

    fn parse_equality(&mut self) -> Result<Value, String> {
        let mut expr = self.parse_comparison()?;

        while self.match_token(&[TokenType::DoubleEquals, TokenType::NotEquals]) {
            let op = self.previous().value.clone();
            let right = self.parse_comparison()?;
            expr = json!({
                "type": "binary_op",
                "operator": op,
                "left": expr,
                "right": right
            });
        }

        Ok(expr)
    }

    fn parse_comparison(&mut self) -> Result<Value, String> {
        let mut expr = self.parse_shift()?;

        while self.match_token(&[
            TokenType::LessThan,
            TokenType::GreaterThan,
            TokenType::LessEqual,
            TokenType::GreaterEqual,
            TokenType::LessThanSigned,
            TokenType::GreaterThanSigned,
            TokenType::LessEqualSigned,
            TokenType::GreaterEqualSigned,
        ]) {
            let op = self.previous().value.clone();
            let right = self.parse_shift()?;
            expr = json!({
                "type": "binary_op",
                "operator": op,
                "left": expr,
                "right": right
            });
        }

        Ok(expr)
    }

    fn parse_shift(&mut self) -> Result<Value, String> {
        let mut expr = self.parse_additive()?;

        while self.match_token(&[
            TokenType::LeftShift,
            TokenType::RightShift,
            TokenType::ArithRightShift,
        ]) {
            let op = self.previous().value.clone();
            let right = self.parse_additive()?;
            expr = json!({
                "type": "binary_op",
                "operator": op,
                "left": expr,
                "right": right
            });
        }

        Ok(expr)
    }

    fn parse_additive(&mut self) -> Result<Value, String> {
        let mut expr = self.parse_multiplicative()?;

        while self.match_token(&[TokenType::Plus, TokenType::Minus]) {
            let op = self.previous().value.clone();
            let right = self.parse_multiplicative()?;
            expr = json!({
                "type": "binary_op",
                "operator": op,
                "left": expr,
                "right": right
            });
        }

        Ok(expr)
    }

    fn parse_multiplicative(&mut self) -> Result<Value, String> {
        let mut expr = self.parse_unary()?;

        while self.match_token(&[
            TokenType::Multiply,
            TokenType::Divide,
            TokenType::DivideSigned,
            TokenType::Modulo,
            TokenType::ModuloSigned,
        ]) {
            let token = self.previous();
            let op = match token.type_ {
                TokenType::Multiply => "*",
                TokenType::Divide => "/",
                TokenType::DivideSigned => "/s",
                TokenType::Modulo => "%",
                TokenType::ModuloSigned => "%s",
                _ => &token.value,
            };
            let right = self.parse_unary()?;
            expr = json!({
                "type": "binary_op",
                "operator": op,
                "left": expr,
                "right": right
            });
        }

        Ok(expr)
    }

    fn parse_unary(&mut self) -> Result<Value, String> {
        // Unary operators: ~ (NOT), - (negation), ! (logical NOT)
        if self.match_token(&[TokenType::Tilde, TokenType::Minus, TokenType::LogicalNot]) {
            let op = self.previous().value.clone();
            let operand = self.parse_unary()?;
            return Ok(json!({
                "type": "unary_op",
                "operator": op,
                "operand": operand
            }));
        }
        // Reduction operators: |expr, &expr, ^expr
        if self.match_token(&[TokenType::Pipe, TokenType::Ampersand, TokenType::Caret]) {
            let op = self.previous().value.clone();
            let operand = self.parse_unary()?;
            return Ok(json!({
                "type": "reduction_op",
                "operator": op,
                "operand": operand
            }));
        }
        self.parse_primary()
    }

    pub fn parse_primary(&mut self) -> Result<Value, String> {
        // Number literal
        if self.match_token(&[TokenType::Number]) {
            let val: i64 = self.previous().value.parse().unwrap_or(0);
            return Ok(json!({
                "type": "literal",
                "value": val
            }));
        }

        // Hex number
        if self.match_token(&[TokenType::HexNumber]) {
            let hex_str = self.previous().value;
            let val = i64::from_str_radix(hex_str.trim_start_matches("0x").trim_start_matches("0X"), 16)
                .unwrap_or(0);
            return Ok(json!({
                "type": "literal",
                "value": val
            }));
        }

        // Verilog hex literal (e.g., 32'hFFFF)
        if self.match_token(&[TokenType::VerilogHexLiteral]) {
            let hex_str = self.previous().value;
            if let Some(pos) = hex_str.find("'h") {
                let width: i64 = hex_str[..pos].parse().unwrap_or(0);
                let hex_digits = &hex_str[pos + 2..];
                let value = i64::from_str_radix(hex_digits, 16).unwrap_or(0);
                return Ok(json!({
                    "type": "sized_literal",
                    "width": width,
                    "format": "hex",
                    "original_digits": hex_digits,
                    "value": value
                }));
            }
        }

        // Binary literal (e.g., 2'b01)
        if self.match_token(&[TokenType::BinaryLiteral]) {
            let binary_str = self.previous().value;
            if let Some(pos) = binary_str.find("'b") {
                let width: i64 = binary_str[..pos].parse().unwrap_or(0);
                let bits = &binary_str[pos + 2..];
                let value = i64::from_str_radix(bits, 2).unwrap_or(0);
                return Ok(json!({
                    "type": "sized_literal",
                    "width": width,
                    "format": "bin",
                    "original_digits": bits,
                    "value": value
                }));
            }
        }

        // Decimal literal (e.g., 6'd32)
        if self.match_token(&[TokenType::DecimalLiteral]) {
            let dec_str = self.previous().value;
            if let Some(pos) = dec_str.find("'d") {
                let width: i64 = dec_str[..pos].parse().unwrap_or(0);
                let dec_digits = &dec_str[pos + 2..];
                let value: i64 = dec_digits.parse().unwrap_or(0);
                return Ok(json!({
                    "type": "sized_literal",
                    "width": width,
                    "format": "dec",
                    "original_digits": dec_digits,
                    "value": value
                }));
            }
        }

        // Binary wildcard (e.g., 0b0**)
        if self.match_token(&[TokenType::BinaryWildcard]) {
            let wildcard_str = self.previous().value;
            let pattern = &wildcard_str[2..]; // strip 0b
            let width = pattern.len() as i64;
            let mut fixed_value: i64 = 0;
            let mut wildcard_positions: Vec<i64> = Vec::new();
            for (bit_pos, ch) in pattern.chars().rev().enumerate() {
                match ch {
                    '1' => fixed_value |= 1 << bit_pos,
                    '*' => wildcard_positions.push(bit_pos as i64),
                    _ => {} // '0' is default
                }
            }
            return Ok(json!({
                "type": "binary_wildcard",
                "pattern": pattern,
                "width": width,
                "original": wildcard_str,
                "fixed_value": fixed_value,
                "wildcard_positions": wildcard_positions
            }));
        }

        // Parenthesized expression
        if self.match_token(&[TokenType::Lparen]) {
            let expr = self.parse_expression()?;
            self.consume(&TokenType::Rparen, "Expected ')' after expression")?;
            return Ok(expr);
        }

        // Verilog-style braces: concatenation or repetition
        if self.match_token(&[TokenType::Lbrace]) {
            return self.parse_verilog_braces();
        }

        // ctz() and clz() builtins
        if self.match_token(&[TokenType::Ctz]) || self.match_token(&[TokenType::Clz]) {
            let builtin_name = self.previous().value.clone();
            self.consume(&TokenType::Lparen, &format!("Expected '(' after {}", builtin_name))?;
            let operand = self.parse_expression()?;
            self.consume(&TokenType::Rparen, &format!("Expected ')' after {} argument", builtin_name))?;
            return Ok(json!({
                "type": "builtin_call",
                "builtin": builtin_name,
                "operand": operand
            }));
        }

        // Identifier (with optional array access, bit slice, CAM lookup)
        if self.match_token(&[TokenType::Identifier]) {
            let name = self.previous().value.clone();

            // Check if this is a loop variable - substitute its value
            let mut expr = if self.loop_vars.contains_key(&name) {
                json!({
                    "type": "literal",
                    "value": self.loop_vars[&name]
                })
            } else if self.register_aliases.contains_key(&name) {
                let alias_value = self.register_aliases[&name].clone();
                if alias_value.get("type").and_then(|v| v.as_str()) == Some("wildcard_array") {
                    json!({
                        "type": "identifier",
                        "name": name,
                        "_is_wildcard_alias": true
                    })
                } else {
                    alias_value
                }
            } else {
                json!({
                    "type": "identifier",
                    "name": name
                })
            };

            // Handle array access and bit slicing
            while self.check(&TokenType::Lbracket) {
                // Look ahead to determine if bit slice (contains :) or array access
                let saved_pos = self.current;
                self.advance(); // consume [

                let mut is_bit_slice = false;
                let mut temp_pos = self.current;
                let mut bracket_depth = 0;
                while temp_pos < self.tokens.len() {
                    let tok_type = &self.tokens[temp_pos].type_;
                    if *tok_type == TokenType::Lbracket {
                        bracket_depth += 1;
                    } else if *tok_type == TokenType::Rbracket {
                        if bracket_depth == 0 {
                            break;
                        }
                        bracket_depth -= 1;
                    } else if *tok_type == TokenType::Colon && bracket_depth == 0 {
                        is_bit_slice = true;
                        break;
                    }
                    temp_pos += 1;
                }

                // Restore position
                self.current = saved_pos;

                if is_bit_slice {
                    let bit_range = self.parse_bit_slice()?;
                    expr = json!({
                        "type": "bit_slice",
                        "target": expr,
                        "range": bit_range
                    });
                    break; // Only one bit slice allowed
                } else {
                    let index = self.parse_array_access()?;

                    // Check wildcard alias
                    let is_wildcard = expr.get("_is_wildcard_alias")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false);

                    if is_wildcard {
                        let alias_name = expr.get("name")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string();
                        if let Some(expanded) = self.expand_wildcard_alias(&alias_name, &index) {
                            expr = expanded;
                        } else {
                            expr = json!({
                                "type": "array_access",
                                "target": expr,
                                "index": index
                            });
                        }
                    } else {
                        // Check for wildcard merge
                        if let Some(merged) = self.merge_wildcard_index(&expr, &index) {
                            expr = merged;
                        } else {
                            expr = json!({
                                "type": "array_access",
                                "target": expr,
                                "index": index
                            });
                        }
                    }
                }
            }

            // Handle CAM associative lookup: name@[key]
            if self.check(&TokenType::At) {
                self.consume(&TokenType::At, "Expected '@'")?;
                self.consume(&TokenType::Lbracket, "Expected '[' after '@' for CAM lookup")?;
                let key = self.parse_expression()?;
                self.consume(&TokenType::Rbracket, "Expected ']' after CAM lookup key")?;

                // Optional set index
                let set_index = if self.check(&TokenType::Lbracket) {
                    self.consume(&TokenType::Lbracket, "Expected '['")?;
                    let si = self.parse_expression()?;
                    self.consume(&TokenType::Rbracket, "Expected ']'")?;
                    Some(si)
                } else {
                    None
                };

                let cam_name = expr.get("name").and_then(|v| v.as_str()).map(String::from);
                let cam_info = cam_name.as_ref().and_then(|cn| self.cam_declarations.get(cn)).cloned();

                let mut cam_expr = json!({
                    "type": "cam_lookup",
                    "target": expr,
                    "key": key,
                    "cam_name": cam_name,
                    "cam_info": cam_info,
                });
                if let Some(si) = set_index {
                    cam_expr["set_index"] = si;
                }
                expr = cam_expr;
            }

            return Ok(expr);
        }

        Err(format!("Unexpected token: {} '{}'", self.peek().type_, self.peek().value))
    }

    // -----------------------------------------------------------------------
    // Sub-expression parsers
    // -----------------------------------------------------------------------

    pub fn parse_array_access(&mut self) -> Result<Value, String> {
        self.consume(&TokenType::Lbracket, "Expected '['")?;
        let index = self.parse_expression()?;
        self.consume(&TokenType::Rbracket, "Expected ']'")?;
        Ok(index)
    }

    pub fn parse_bit_slice(&mut self) -> Result<Vec<Value>, String> {
        self.consume(&TokenType::Lbracket, "Expected '['")?;
        let high_expr = self.parse_expression()?;
        self.consume(&TokenType::Colon, "Expected ':'")?;
        let low_expr = self.parse_expression()?;
        self.consume(&TokenType::Rbracket, "Expected ']'")?;

        // Try to evaluate to integers
        let high = if self.can_evaluate(&high_expr) {
            Value::from(self.evaluate_expression(&high_expr)?)
        } else {
            high_expr
        };
        let low = if self.can_evaluate(&low_expr) {
            Value::from(self.evaluate_expression(&low_expr)?)
        } else {
            low_expr
        };

        Ok(vec![high, low])
    }

    pub fn parse_array_dimension(&mut self) -> Result<(i64, i64), String> {
        self.consume(&TokenType::Lbracket, "Expected '['")?;
        let high_tok = self.consume(&TokenType::Number, "Expected number")?;
        let high: i64 = high_tok.value.parse().unwrap_or(0);
        self.consume(&TokenType::Colon, "Expected ':'")?;
        let low_tok = self.consume(&TokenType::Number, "Expected number")?;
        let low: i64 = low_tok.value.parse().unwrap_or(0);
        self.consume(&TokenType::Rbracket, "Expected ']'")?;
        Ok((high, low))
    }

    fn parse_verilog_braces(&mut self) -> Result<Value, String> {
        // LBRACE was already consumed
        let saved_pos = self.current;

        // Check if repetition: NUMBER followed by {
        if self.check(&TokenType::Number)
            && self.current + 1 < self.tokens.len()
            && self.tokens[self.current + 1].type_ == TokenType::Lbrace
        {
            let count: i64 = self.advance().value.parse().unwrap_or(0);
            self.consume(&TokenType::Lbrace, "Expected '{'")?;
            let expr = self.parse_expression()?;
            self.consume(&TokenType::Rbrace, "Expected '}'")?;

            if self.check(&TokenType::Comma) {
                // Concatenation with repetition as first element
                self.current = saved_pos;
                return self.parse_concatenation_internal();
            } else if self.check(&TokenType::Rbrace) {
                self.consume(&TokenType::Rbrace, "Expected '}'")?;
                return Ok(json!({
                    "type": "repetition",
                    "count": count,
                    "expression": expr
                }));
            } else {
                return Err(format!(
                    "Unexpected token after repetition: {}",
                    self.peek().value
                ));
            }
        }

        self.current = saved_pos;
        self.parse_concatenation_internal()
    }

    fn parse_concatenation_internal(&mut self) -> Result<Value, String> {
        let mut expressions = Vec::new();
        expressions.push(self.parse_expression()?);

        while self.match_token(&[TokenType::Comma]) {
            expressions.push(self.parse_expression()?);
        }

        self.consume(&TokenType::Rbrace, "Expected '}'")?;

        Ok(json!({
            "type": "concatenation",
            "parts": expressions
        }))
    }

    pub fn parse_loop_value(&mut self) -> Result<i64, String> {
        if self.check(&TokenType::Number) {
            let tok = self.advance();
            Ok(tok.value.parse().unwrap_or(0))
        } else if self.check(&TokenType::HexNumber) {
            let tok = self.advance();
            Ok(i64::from_str_radix(
                tok.value.trim_start_matches("0x").trim_start_matches("0X"),
                16,
            )
            .unwrap_or(0))
        } else {
            Err("Expected numeric value in for loop".to_string())
        }
    }

    // -----------------------------------------------------------------------
    // Wildcard helpers
    // -----------------------------------------------------------------------

    pub fn expression_has_wildcard(&self, expr: &Value) -> bool {
        if !expr.is_object() {
            return false;
        }
        let expr_type = expr.get("type").and_then(|v| v.as_str()).unwrap_or("");
        if expr_type == "binary_wildcard" {
            return true;
        }
        if expr_type == "array_access" {
            if self.expression_has_wildcard(expr.get("index").unwrap_or(&Value::Null)) {
                return true;
            }
            if self.expression_has_wildcard(expr.get("target").unwrap_or(&Value::Null)) {
                return true;
            }
        }
        if expr_type == "bit_slice" {
            if self.expression_has_wildcard(expr.get("target").unwrap_or(&Value::Null)) {
                return true;
            }
        }
        for key in &["left", "right", "condition", "if_true", "if_false", "operand", "target"] {
            if let Some(sub) = expr.get(key) {
                if sub.is_object() && self.expression_has_wildcard(sub) {
                    return true;
                }
            }
        }
        false
    }

    fn merge_wildcard_index(&self, expr: &Value, index: &Value) -> Option<Value> {
        fn find_and_replace_wildcard(node: &Value, idx: &Value) -> (Value, bool) {
            if !node.is_object() {
                return (node.clone(), false);
            }

            let node_type = node.get("type").and_then(|v| v.as_str()).unwrap_or("");

            if node_type == "binary_wildcard" {
                let pattern = node.get("pattern").and_then(|v| v.as_str()).unwrap_or("");
                let mut fixed_bits = String::new();
                let mut wildcard_width = 0;
                for c in pattern.chars() {
                    if c == '*' {
                        wildcard_width += 1;
                    } else {
                        fixed_bits.push(c);
                    }
                }
                let _ = wildcard_width;

                if !fixed_bits.is_empty() {
                    let fixed_literal = json!({
                        "type": "sized_literal",
                        "value": i64::from_str_radix(&fixed_bits, 2).unwrap_or(0),
                        "width": fixed_bits.len(),
                        "format": "bin",
                        "original_digits": fixed_bits
                    });
                    return (
                        json!({
                            "type": "concatenation",
                            "parts": [fixed_literal, idx]
                        }),
                        true,
                    );
                } else {
                    return (idx.clone(), true);
                }
            }

            if node_type == "array_access" {
                let (new_index, found) = find_and_replace_wildcard(
                    node.get("index").unwrap_or(&Value::Null),
                    idx,
                );
                if found {
                    return (
                        json!({
                            "type": "array_access",
                            "target": node.get("target").unwrap_or(&Value::Null),
                            "index": new_index
                        }),
                        true,
                    );
                }
            }

            if node_type == "bit_slice" {
                let (new_target, found) = find_and_replace_wildcard(
                    node.get("target").unwrap_or(&Value::Null),
                    idx,
                );
                if found {
                    return (
                        json!({
                            "type": "bit_slice",
                            "target": new_target,
                            "range": node.get("range").unwrap_or(&Value::Null)
                        }),
                        true,
                    );
                }
            }

            (node.clone(), false)
        }

        let (new_expr, found) = find_and_replace_wildcard(expr, index);
        if found {
            Some(new_expr)
        } else {
            None
        }
    }

    fn expand_wildcard_alias(&self, alias_name: &str, index_expr: &Value) -> Option<Value> {
        let alias_info = self.register_aliases.get(alias_name)?;
        if alias_info.get("type").and_then(|v| v.as_str()) != Some("wildcard_array") {
            return None;
        }
        let parent_expr = alias_info.get("parent_expr")?.clone();
        let mut expanded = parent_expr;
        self.substitute_wildcard_in_expr(&mut expanded, index_expr);
        Some(expanded)
    }

    fn substitute_wildcard_in_expr(&self, expr: &mut Value, index_expr: &Value) {
        let expr_type = expr.get("type").and_then(|v| v.as_str()).unwrap_or("").to_string();

        if expr_type == "array_access" {
            let index_type = expr
                .get("index")
                .and_then(|v| v.get("type"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();

            if index_type == "binary_wildcard" {
                let wildcard_info = expr.get("index").cloned().unwrap_or(Value::Null);
                let fixed_value = wildcard_info
                    .get("fixed_value")
                    .and_then(|v| v.as_i64())
                    .unwrap_or(0);
                let wildcard_positions: Vec<i64> = wildcard_info
                    .get("wildcard_positions")
                    .and_then(|v| v.as_array())
                    .map(|a| a.iter().filter_map(|v| v.as_i64()).collect())
                    .unwrap_or_default();
                let result_width = wildcard_info
                    .get("width")
                    .and_then(|v| v.as_i64())
                    .unwrap_or(5);

                if !wildcard_positions.is_empty() {
                    let shift_amount = *wildcard_positions.iter().min().unwrap_or(&0);
                    if shift_amount == 0 {
                        expr["index"] = json!({
                            "type": "binary_op",
                            "operator": "|",
                            "left": {"type": "literal", "value": fixed_value, "bit_width": result_width},
                            "right": index_expr,
                            "bit_width": result_width
                        });
                    } else {
                        expr["index"] = json!({
                            "type": "binary_op",
                            "operator": "|",
                            "left": {"type": "literal", "value": fixed_value, "bit_width": result_width},
                            "right": {
                                "type": "binary_op",
                                "operator": "<<",
                                "left": index_expr,
                                "right": {"type": "literal", "value": shift_amount},
                                "bit_width": result_width
                            },
                            "bit_width": result_width
                        });
                    }
                } else {
                    expr["index"] = json!({"type": "literal", "value": fixed_value, "bit_width": result_width});
                }
            } else {
                // Recursively substitute in index
                if let Some(idx) = expr.get_mut("index") {
                    self.substitute_wildcard_in_expr(idx, index_expr);
                }
            }

            // Also check target
            if let Some(target) = expr.get_mut("target") {
                if target.is_object() {
                    self.substitute_wildcard_in_expr(target, index_expr);
                }
            }
        } else if expr_type == "bit_slice" {
            if let Some(target) = expr.get_mut("target") {
                if target.is_object() {
                    self.substitute_wildcard_in_expr(target, index_expr);
                }
            }
        }
    }
}
