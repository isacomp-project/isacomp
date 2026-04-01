// ISA Parser - Rust port of isa_parser.py
// Parses ISA specification files into ResourceGraph representations.

use std::collections::HashMap;
use std::fs;
use std::path::Path;

use serde_json::{json, Value};

use crate::isa_lexer::{ISALexer, ISAToken, TokenType};
use crate::resource_graph::ResourceGraph;

mod declarations;
mod expressions;
mod nodes;
mod statements;

// ---------------------------------------------------------------------------
// FP type constants
// ---------------------------------------------------------------------------

pub fn fp_type_widths() -> HashMap<&'static str, i64> {
    let mut m = HashMap::new();
    m.insert("fp16", 16);
    m.insert("bf16", 16);
    m.insert("fp32", 32);
    m.insert("fp64", 64);
    m.insert("fp128", 128);
    m.insert("fpcmp_res", 1);
    m
}

pub fn fp_type_info() -> HashMap<&'static str, Value> {
    let mut m = HashMap::new();
    m.insert("fp16", json!({"exp_bits": 5, "mant_bits": 10, "ieee_name": "binary16"}));
    m.insert("bf16", json!({"exp_bits": 8, "mant_bits": 7, "ieee_name": "bfloat16"}));
    m.insert("fp32", json!({"exp_bits": 8, "mant_bits": 23, "ieee_name": "binary32"}));
    m.insert("fp64", json!({"exp_bits": 11, "mant_bits": 52, "ieee_name": "binary64"}));
    m.insert("fp128", json!({"exp_bits": 15, "mant_bits": 112, "ieee_name": "binary128"}));
    m.insert("fpcmp_res", json!({"exp_bits": 0, "mant_bits": 0, "ieee_name": "comparison_result"}));
    m
}

// ---------------------------------------------------------------------------
// ISAParser
// ---------------------------------------------------------------------------

pub struct ISAParser {
    lexer: ISALexer,
    pub tokens: Vec<ISAToken>,
    pub current: usize,
    pub current_file: Option<String>,
    pub defines: HashMap<String, String>,
    pub loop_vars: HashMap<String, i64>,
    pub enable_condition: Option<Value>,
    pub register_aliases: HashMap<String, Value>,
    pub intermediate_values: HashMap<String, String>, // var_name -> node_id
    pub cam_declarations: HashMap<String, Value>,
}

impl ISAParser {
    pub fn new() -> Self {
        ISAParser {
            lexer: ISALexer::new(),
            tokens: Vec::new(),
            current: 0,
            current_file: None,
            defines: HashMap::new(),
            loop_vars: HashMap::new(),
            enable_condition: None,
            register_aliases: HashMap::new(),
            intermediate_values: HashMap::new(),
            cam_declarations: HashMap::new(),
        }
    }

    pub fn with_defines(defines: HashMap<String, String>) -> Self {
        let mut parser = Self::new();
        parser.defines = defines;
        parser
    }

    // -----------------------------------------------------------------------
    // File parsing entry point
    // -----------------------------------------------------------------------

    pub fn parse_file(
        &mut self,
        filename: &str,
        existing_graph: Option<&mut ResourceGraph>,
    ) -> Result<ResourceGraph, String> {
        let path = Path::new(filename);
        if !path.exists() {
            return Err(format!("File not found: {}", filename));
        }

        self.current_file = Some(filename.to_string());

        // Read the file
        let text = fs::read_to_string(path)
            .map_err(|e| format!("Failed to read {}: {}", filename, e))?;

        // Preprocess: strip C-style comments and handle #define/#ifdef
        let processed = self.preprocess(&text);

        // Parse
        let skip_aspect_merge = existing_graph.is_some();
        self.parse(&processed, existing_graph, skip_aspect_merge)
    }

    pub fn parse(
        &mut self,
        text: &str,
        existing_graph: Option<&mut ResourceGraph>,
        _skip_aspect_merge: bool,
    ) -> Result<ResourceGraph, String> {
        // Tokenize
        self.tokens = self.lexer.tokenize(text)?;
        self.current = 0;

        // If caller provided a graph, parse into it in-place and return a clone;
        // otherwise create and return a new one.
        if let Some(graph) = existing_graph {
            while !self.is_at_end() {
                self.parse_top_level(graph)?;
            }
            graph.classify_architectural_state();
            Ok(graph.clone())
        } else {
            let mut graph = ResourceGraph::new();
            while !self.is_at_end() {
                self.parse_top_level(&mut graph)?;
            }
            graph.classify_architectural_state();
            Ok(graph)
        }
    }

    fn parse_top_level(&mut self, graph: &mut ResourceGraph) -> Result<(), String> {
        if self.check(&TokenType::IsaState) {
            self.parse_isa_state_declaration(graph)?;
        } else if self.check(&TokenType::Mem) {
            self.parse_mem_declaration(graph)?;
        } else if self.check(&TokenType::Var) {
            self.parse_var_declaration(graph)?;
        } else if self.check(&TokenType::FpType) || self.check(&TokenType::FpcmpRes) {
            self.parse_fp_var_declaration(graph)?;
        } else if self.check(&TokenType::Assume) {
            self.parse_assume_statement(graph)?;
        } else if self.check(&TokenType::Flush) {
            self.parse_flush_statement(graph)?;
        } else if self.check(&TokenType::Aspect) {
            self.parse_aspect_declaration(graph)?;
        } else if self.check(&TokenType::For) {
            self.parse_for_loop(graph)?;
        } else if self.check(&TokenType::If) {
            self.parse_if_statement(graph)?;
        } else if self.check(&TokenType::Case) {
            self.parse_case_statement(graph)?;
        } else if self.check(&TokenType::Cam) {
            self.parse_cam_declaration(graph)?;
        } else if self.check(&TokenType::Identifier) {
            self.parse_assignment(graph)?;
        } else {
            // Skip unknown tokens
            self.advance();
        }
        Ok(())
    }

    // -----------------------------------------------------------------------
    // Preprocessing
    // -----------------------------------------------------------------------

    fn preprocess(&self, text: &str) -> String {
        let mut result = String::new();
        let mut in_block_comment = false;
        // Stack of (active, seen_true_branch) for nested #ifdef/#ifndef
        // active: whether the current branch should emit code
        // seen_true_branch: whether any branch in this #ifdef block was true
        let mut ifdef_stack: Vec<(bool, bool)> = Vec::new();

        for line in text.lines() {
            if in_block_comment {
                if let Some(pos) = line.find("*/") {
                    in_block_comment = false;
                    let after = &line[pos + 2..];
                    // Still need to check ifdef state for the rest of the line
                    if ifdef_stack.iter().all(|(active, _)| *active) {
                        result.push_str(after);
                    }
                    result.push('\n');
                } else {
                    result.push('\n');
                }
                continue;
            }

            let mut processed_line = line.to_string();

            // Remove block comments that start and end on the same line
            while let Some(start) = processed_line.find("/*") {
                if let Some(end) = processed_line[start + 2..].find("*/") {
                    let before = &processed_line[..start];
                    let after = &processed_line[start + 2 + end + 2..];
                    processed_line = format!("{}{}", before, after);
                } else {
                    in_block_comment = true;
                    processed_line = processed_line[..start].to_string();
                    break;
                }
            }

            // Remove line comments
            if let Some(pos) = processed_line.find("//") {
                processed_line = processed_line[..pos].to_string();
            }

            let trimmed = processed_line.trim();

            // Handle preprocessor directives
            if trimmed.starts_with("#ifdef ") {
                let symbol = trimmed[7..].trim().to_string();
                let is_defined = self.defines.contains_key(&symbol);
                // Only active if all parent scopes are active AND this condition is true
                let parent_active = ifdef_stack.iter().all(|(active, _)| *active);
                let active = parent_active && is_defined;
                ifdef_stack.push((active, active));
                result.push('\n');
                continue;
            }
            if trimmed.starts_with("#ifndef ") {
                let symbol = trimmed[8..].trim().to_string();
                let is_defined = self.defines.contains_key(&symbol);
                let parent_active = ifdef_stack.iter().all(|(active, _)| *active);
                let active = parent_active && !is_defined;
                ifdef_stack.push((active, active));
                result.push('\n');
                continue;
            }
            if trimmed.starts_with("#else") {
                if !ifdef_stack.is_empty() {
                    let len = ifdef_stack.len();
                    let parent_active = len <= 1
                        || ifdef_stack[..len - 1].iter().all(|(a, _)| *a);
                    let seen_true = ifdef_stack[len - 1].1;
                    // #else is active if parent is active and no branch was true yet
                    let new_active = parent_active && !seen_true;
                    ifdef_stack[len - 1].0 = new_active;
                    if new_active {
                        ifdef_stack[len - 1].1 = true;
                    }
                }
                result.push('\n');
                continue;
            }
            if trimmed.starts_with("#endif") {
                ifdef_stack.pop();
                result.push('\n');
                continue;
            }
            if trimmed.starts_with("#define") || trimmed.starts_with("#include") {
                result.push('\n');
                continue;
            }

            // Only emit line if all ifdef scopes are active
            if ifdef_stack.iter().all(|(active, _)| *active) {
                result.push_str(&processed_line);
            }
            result.push('\n');
        }

        result
    }

    // -----------------------------------------------------------------------
    // Token navigation helpers
    // -----------------------------------------------------------------------

    pub fn match_token(&mut self, types: &[TokenType]) -> bool {
        for token_type in types {
            if self.check(token_type) {
                self.advance();
                return true;
            }
        }
        false
    }

    pub fn check(&self, token_type: &TokenType) -> bool {
        if self.is_at_end() {
            return false;
        }
        &self.peek().type_ == token_type
    }

    pub fn advance(&mut self) -> ISAToken {
        if !self.is_at_end() {
            self.current += 1;
        }
        self.previous()
    }

    pub fn is_at_end(&self) -> bool {
        self.current >= self.tokens.len()
    }

    pub fn peek(&self) -> ISAToken {
        if self.current >= self.tokens.len() {
            ISAToken {
                type_: TokenType::Eof,
                value: String::new(),
                line: 0,
                column: 0,
            }
        } else {
            self.tokens[self.current].clone()
        }
    }

    pub fn previous(&self) -> ISAToken {
        if self.current == 0 {
            self.peek() // no previous token; return current/placeholder
        } else {
            self.tokens[self.current - 1].clone()
        }
    }

    pub fn consume(&mut self, token_type: &TokenType, message: &str) -> Result<ISAToken, String> {
        if self.check(token_type) {
            Ok(self.advance())
        } else {
            let current_token = self.peek();
            Err(format!(
                "{}. Got {} '{}' at line {}",
                message, current_token.type_, current_token.value, current_token.line
            ))
        }
    }

    // -----------------------------------------------------------------------
    // Expression evaluation (for compile-time constants)
    // -----------------------------------------------------------------------

    pub fn can_evaluate(&self, expr: &Value) -> bool {
        match expr.get("type").and_then(|v| v.as_str()) {
            Some("literal") | Some("sized_literal") => true,
            Some("binary_op") => {
                let left = expr.get("left").unwrap_or(&Value::Null);
                let right = expr.get("right").unwrap_or(&Value::Null);
                self.can_evaluate(left) && self.can_evaluate(right)
            }
            Some("identifier") => {
                let name = expr.get("name").and_then(|v| v.as_str()).unwrap_or("");
                self.loop_vars.contains_key(name)
            }
            _ => false,
        }
    }

    pub fn evaluate_expression(&self, expr: &Value) -> Result<i64, String> {
        match expr.get("type").and_then(|v| v.as_str()) {
            Some("literal") => Ok(expr.get("value").and_then(|v| v.as_i64()).unwrap_or(0)),
            Some("sized_literal") => Ok(expr.get("value").and_then(|v| v.as_i64()).unwrap_or(0)),
            Some("identifier") => {
                let name = expr.get("name").and_then(|v| v.as_str()).unwrap_or("");
                self.loop_vars
                    .get(name)
                    .copied()
                    .ok_or_else(|| format!("Cannot evaluate identifier: {}", name))
            }
            Some("binary_op") => {
                let left = self.evaluate_expression(
                    expr.get("left").unwrap_or(&Value::Null),
                )?;
                let right = self.evaluate_expression(
                    expr.get("right").unwrap_or(&Value::Null),
                )?;
                let op = expr
                    .get("operator")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                match op {
                    "+" => Ok(left + right),
                    "-" => Ok(left - right),
                    "*" => Ok(left * right),
                    "/" => {
                        if right == 0 {
                            Err("Division by zero in '/' operator".to_string())
                        } else {
                            Ok(left / right)
                        }
                    }
                    "/s" => {
                        if right == 0 {
                            Err("Division by zero in '/s' operator".to_string())
                        } else {
                            Ok(left / right) // Rust truncates toward zero
                        }
                    }
                    "%" => {
                        if right == 0 {
                            Err("Modulo by zero in '%' operator".to_string())
                        } else {
                            Ok(left % right)
                        }
                    }
                    "%s" => {
                        if right == 0 {
                            Err("Modulo by zero in '%s' operator".to_string())
                        } else {
                            Ok(left % right) // Rust % has sign of dividend
                        }
                    }
                    "<<" => {
                        if right < 0 || right >= 64 {
                            Err(format!("Shift amount out of range: {}", right))
                        } else {
                            Ok(left << right)
                        }
                    }
                    ">>" => {
                        if right < 0 || right >= 64 {
                            Err(format!("Shift amount out of range: {}", right))
                        } else {
                            Ok(left >> right)
                        }
                    }
                    ">>>" => {
                        if right < 0 || right >= 64 {
                            Err(format!("Shift amount out of range: {}", right))
                        } else {
                            Ok(left >> right) // arithmetic shift = Rust >>
                        }
                    }
                    "&" => Ok(left & right),
                    "|" => Ok(left | right),
                    "^" => Ok(left ^ right),
                    "==" => Ok(if left == right { 1 } else { 0 }),
                    "!=" => Ok(if left != right { 1 } else { 0 }),
                    "<" => Ok(if left < right { 1 } else { 0 }),
                    ">" => Ok(if left > right { 1 } else { 0 }),
                    "<=" => Ok(if left <= right { 1 } else { 0 }),
                    ">=" => Ok(if left >= right { 1 } else { 0 }),
                    _ => Err(format!("Unknown operator: {}", op)),
                }
            }
            _ => Err(format!(
                "Cannot evaluate expression type: {:?}",
                expr.get("type")
            )),
        }
    }

    // -----------------------------------------------------------------------
    // Helper: expression to string (for if/else target matching)
    // -----------------------------------------------------------------------

    pub fn expr_to_string(&self, expr: &Value) -> String {
        if expr.is_null() {
            return String::new();
        }
        let expr_type = expr.get("type").and_then(|v| v.as_str()).unwrap_or("");
        match expr_type {
            "identifier" => expr
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
            "literal" => expr
                .get("value")
                .and_then(|v| v.as_i64())
                .unwrap_or(0)
                .to_string(),
            "sized_literal" => {
                let fmt = match expr.get("format").and_then(|v| v.as_str()).unwrap_or("bin") {
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
                format!("{}'{}{}", width, fmt, digits)
            }
            "bit_slice" => {
                let target = expr.get("target").unwrap_or(&Value::Null);
                let range = expr.get("range").unwrap_or(&Value::Null);
                let high = range.get(0).unwrap_or(&Value::Null);
                let low = range.get(1).unwrap_or(&Value::Null);
                format!(
                    "{}[{}:{}]",
                    self.expr_to_string(target),
                    high,
                    low
                )
            }
            "array_access" => {
                let target = expr.get("target").unwrap_or(&Value::Null);
                let index = expr.get("index").unwrap_or(&Value::Null);
                format!(
                    "{}[{}]",
                    self.expr_to_string(target),
                    self.expr_to_string(index)
                )
            }
            "binary_op" => {
                let left = expr.get("left").unwrap_or(&Value::Null);
                let right = expr.get("right").unwrap_or(&Value::Null);
                let op = expr.get("operator").and_then(|v| v.as_str()).unwrap_or("");
                format!(
                    "({} {} {})",
                    self.expr_to_string(left),
                    op,
                    self.expr_to_string(right)
                )
            }
            _ => format!("{}", expr),
        }
    }

    // -----------------------------------------------------------------------
    // Helper: get graph reference safely
    // -----------------------------------------------------------------------
}
