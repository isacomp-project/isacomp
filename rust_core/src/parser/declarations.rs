// Declaration parsing: isa_state, mem, var, fp_var, assume, flush, aspect, cam
// Ported from isa_parser.py declaration methods.

use std::collections::HashMap;

use serde_json::{json, Value};

use crate::isa_lexer::TokenType;
use crate::resource_graph::{Edge, Node, ResourceGraph};

use super::{fp_type_info, fp_type_widths, ISAParser};

impl ISAParser {
    // -----------------------------------------------------------------------
    // isa_state declaration
    // -----------------------------------------------------------------------

    pub fn parse_isa_state_declaration(
        &mut self,
        graph: &mut ResourceGraph,
    ) -> Result<(), String> {
        self.consume(&TokenType::IsaState, "Expected 'isa_state'")?;

        let name = self.consume(&TokenType::Identifier, "Expected identifier")?.value;

        // Parse bit range: isa_state name[high:low];
        let (high, low) = self.parse_array_dimension()?;
        let bit_width = high - low + 1;

        // Check for optional array dimension: isa_state name[high:low][addr_high:addr_low];
        let mut dimension = None;
        let mut addr_bits = None;
        if self.check(&TokenType::Lbracket) {
            let (addr_high, addr_low) = self.parse_array_dimension()?;
            let abits = addr_high - addr_low + 1;
            dimension = Some((addr_high, addr_low));
            addr_bits = Some(abits);
        }

        // Check for register aliasing: isa_state name[...] of parent[...][...];
        let mut register_alias = None;
        if self.check(&TokenType::Of) {
            self.consume(&TokenType::Of, "Expected 'of'")?;
            // Parse the parent expression (e.g., xregs[0b0**][7:0])
            let parent_expr = self.parse_expression()?;
            register_alias = Some(parent_expr);
        }

        self.consume(&TokenType::Semicolon, "Expected ';'")?;

        // Handle register aliasing
        if let Some(alias_expr) = register_alias {
            // Check if the alias contains a wildcard
            if self.expression_has_wildcard(&alias_expr) {
                // Wildcard array alias
                self.register_aliases.insert(
                    name.clone(),
                    json!({
                        "type": "wildcard_array",
                        "parent_expr": alias_expr
                    }),
                );
            } else {
                // Simple scalar alias
                self.register_aliases.insert(name.clone(), alias_expr);
            }
            return Ok(());
        }

        // Create node for the ISA state
        let mut node_data: HashMap<String, Value> = HashMap::new();
        node_data.insert("type".to_string(), json!("isa_state"));
        node_data.insert("name".to_string(), json!(name));
        node_data.insert("display_name".to_string(), json!(name));
        node_data.insert("bit_width".to_string(), json!(bit_width));
        node_data.insert("bit_range".to_string(), json!([high, low]));
        let dimension_count = if dimension.is_some() { 2 } else { 1 };
        node_data.insert("dimension_count".to_string(), json!(dimension_count));

        // Store dimensions as list of [high, low] pairs (matching Python's dimensions field)
        if let Some(dim) = dimension {
            node_data.insert("dimensions".to_string(), json!([[high, low], [dim.0, dim.1]]));
            node_data.insert("dimension".to_string(), json!([dim.0, dim.1]));
            let abits = addr_bits.unwrap_or(0);
            node_data.insert("addr_bits".to_string(), json!(abits));
            // array_depth = number of entries (addr_high - addr_low + 1)
            node_data.insert("array_depth".to_string(), json!(dim.0 - dim.1 + 1));
            node_data.insert("is_memory".to_string(), json!(true));
        } else {
            node_data.insert("dimensions".to_string(), json!([[high, low]]));
            node_data.insert("is_memory".to_string(), json!(false));
        }

        let node = Node::new(
            Some(name.clone()),
            Some(node_data),
            true,  // is_arch_state
            false, // used_as_index
            None,  // indexed_by
            false, // is_uarch_state
            None,  // uarch_time
            None,  // pipe_time
            true,  // from_isa_spec
            false, // already_split
            0,     // latency
            false, // variable_latency
            false, // is_shared
            None,  // pipe_id
            None,  // dual_issue_time
        );
        graph.add_node(node);

        Ok(())
    }

    // -----------------------------------------------------------------------
    // mem declaration
    // -----------------------------------------------------------------------

    pub fn parse_mem_declaration(&mut self, graph: &mut ResourceGraph) -> Result<(), String> {
        self.consume(&TokenType::Mem, "Expected 'mem'")?;

        let name = self.consume(&TokenType::Identifier, "Expected identifier")?.value;
        let addr_dimension = self.parse_array_dimension()?;

        self.consume(&TokenType::Semicolon, "Expected ';'")?;

        let addr_bits = addr_dimension.0 - addr_dimension.1 + 1;

        let mut node_data: HashMap<String, Value> = HashMap::new();
        node_data.insert("type".to_string(), json!("isa_state mem"));
        node_data.insert("name".to_string(), json!(name));
        node_data.insert("display_name".to_string(), json!(name));
        node_data.insert("bit_width".to_string(), Value::Null);
        node_data.insert("addr_bits".to_string(), json!(addr_bits));
        node_data.insert("array_depth".to_string(), json!(addr_bits));
        node_data.insert("addr_dimension".to_string(), json!([addr_dimension.0, addr_dimension.1]));
        node_data.insert("is_memory".to_string(), json!(true));
        node_data.insert("width_inferred".to_string(), json!(true));
        node_data.insert("access_widths".to_string(), json!([]));

        let node = Node::new(
            Some(name),
            Some(node_data),
            true,  // is_arch_state (memories are always arch state)
            false, None, false, None, None,
            true,  // from_isa_spec
            false, 0, false, false, None, None,
        );
        graph.add_node(node);

        Ok(())
    }

    // -----------------------------------------------------------------------
    // var declaration
    // -----------------------------------------------------------------------

    pub fn parse_var_declaration(&mut self, graph: &mut ResourceGraph) -> Result<(), String> {
        self.consume(&TokenType::Var, "Expected 'var'")?;

        let name = self.consume(&TokenType::Identifier, "Expected identifier")?.value;

        if !self.check(&TokenType::Lbracket) {
            return Err(format!(
                "Variable '{}' must have an explicit width. Use: var {}[high:low];",
                name, name
            ));
        }

        let bit_range = self.parse_array_dimension()?;
        let bit_width = bit_range.0 - bit_range.1 + 1;

        self.consume(&TokenType::Semicolon, "Expected ';'")?;

        let mut node_data: HashMap<String, Value> = HashMap::new();
        node_data.insert("type".to_string(), json!("var"));
        node_data.insert("name".to_string(), json!(name));
        node_data.insert("display_name".to_string(), json!(name));
        node_data.insert("width".to_string(), json!(bit_width));
        node_data.insert("bit_width".to_string(), json!(bit_width));
        node_data.insert("bit_range".to_string(), json!([bit_range.0, bit_range.1]));
        node_data.insert("width_explicit".to_string(), json!(true));

        let node = Node::new(
            Some(name),
            Some(node_data),
            false, false, None, false, None, None,
            true,  // from_isa_spec
            false, 0, false, false, None, None,
        );
        graph.add_node(node);

        Ok(())
    }

    // -----------------------------------------------------------------------
    // FP variable declaration
    // -----------------------------------------------------------------------

    pub fn parse_fp_var_declaration(&mut self, graph: &mut ResourceGraph) -> Result<(), String> {
        let fp_type = if self.check(&TokenType::FpType) {
            self.consume(&TokenType::FpType, "Expected FP type")?.value
        } else {
            self.consume(&TokenType::FpcmpRes, "Expected fpcmp_res")?.value
        };

        let widths = fp_type_widths();
        let type_infos = fp_type_info();

        let bit_width = *widths
            .get(fp_type.as_str())
            .ok_or_else(|| format!("Unknown FP type: {}", fp_type))?;
        let type_info = type_infos
            .get(fp_type.as_str())
            .cloned()
            .unwrap_or(Value::Null);

        // Parse one or more comma-separated names
        let mut names = Vec::new();
        names.push(self.consume(&TokenType::Identifier, "Expected variable name")?.value);

        while self.check(&TokenType::Comma) {
            self.consume(&TokenType::Comma, "Expected ','")?;
            names.push(self.consume(&TokenType::Identifier, "Expected variable name")?.value);
        }

        self.consume(&TokenType::Semicolon, "Expected ';'")?;

        for name in names {
            let mut node_data: HashMap<String, Value> = HashMap::new();
            node_data.insert("type".to_string(), json!("fp_var"));
            node_data.insert("name".to_string(), json!(name));
            node_data.insert("display_name".to_string(), json!(name));
            node_data.insert("width".to_string(), json!(bit_width));
            node_data.insert("bit_width".to_string(), json!(bit_width));
            node_data.insert("bit_range".to_string(), json!([bit_width - 1, 0]));
            node_data.insert("width_explicit".to_string(), json!(true));
            node_data.insert("fp_type".to_string(), json!(fp_type));
            node_data.insert("fp_type_info".to_string(), type_info.clone());
            node_data.insert("value_type".to_string(), json!("floating_point"));

            let node = Node::new(
                Some(name),
                Some(node_data),
                false, false, None, false, None, None,
                true, false, 0, false, false, None, None,
            );
            graph.add_node(node);
        }

        Ok(())
    }

    // -----------------------------------------------------------------------
    // assume statement
    // -----------------------------------------------------------------------

    pub fn parse_assume_statement(&mut self, graph: &mut ResourceGraph) -> Result<(), String> {
        self.consume(&TokenType::Assume, "Expected 'assume'")?;
        let assume_expr = self.parse_expression()?;
        self.consume(&TokenType::Semicolon, "Expected ';'")?;
        graph.assume_expressions.push(assume_expr);
        Ok(())
    }

    // -----------------------------------------------------------------------
    // flush statement
    // -----------------------------------------------------------------------

    pub fn parse_flush_statement(&mut self, graph: &mut ResourceGraph) -> Result<(), String> {
        self.consume(&TokenType::Flush, "Expected 'flush'")?;
        let cache_name = self.consume(&TokenType::Identifier, "Expected cache name")?.value;
        self.consume(&TokenType::Semicolon, "Expected ';'")?;

        // Create constant 1 node
        let const_node_id = format!("flush_{}_const", cache_name);
        let mut const_data: HashMap<String, Value> = HashMap::new();
        const_data.insert("type".to_string(), json!("literal"));
        const_data.insert("value".to_string(), json!(1));
        const_data.insert("bit_width".to_string(), json!(1));
        const_data.insert("display_name".to_string(), json!(format!("Flush {} const", cache_name)));
        let const_node = Node::new(Some(const_node_id.clone()), Some(const_data), false, false, None, false, None, None, false, false, 0, false, false, None, None);
        graph.add_node(const_node);

        // Create flush signal node
        let flush_node_id = format!("flush_{}", cache_name);
        let mut flush_data: HashMap<String, Value> = HashMap::new();
        flush_data.insert("type".to_string(), json!("var"));
        flush_data.insert("name".to_string(), json!(&flush_node_id));
        flush_data.insert("display_name".to_string(), json!(format!("Flush {}", cache_name)));
        flush_data.insert("bit_width".to_string(), json!(1));
        flush_data.insert("is_flush_trigger".to_string(), json!(true));
        flush_data.insert("target_cache".to_string(), json!(cache_name));
        let flush_node = Node::new(Some(flush_node_id.clone()), Some(flush_data), false, false, None, false, None, None, false, false, 0, false, false, None, None);
        graph.add_node(flush_node);

        // Edge: const -> flush signal
        let mut edge_data: HashMap<String, Value> = HashMap::new();
        edge_data.insert("type".to_string(), json!("assignment"));
        let edge = Edge::new(const_node_id, flush_node_id.clone(), None, Some(edge_data));
        graph.add_edge(edge);

        // Create placeholder target
        let placeholder_id = format!("{}_flush_target", cache_name);
        let mut ph_data: HashMap<String, Value> = HashMap::new();
        ph_data.insert("type".to_string(), json!("flush_target_placeholder"));
        ph_data.insert("cache_name".to_string(), json!(cache_name));
        ph_data.insert("awaiting_cache".to_string(), json!(true));
        ph_data.insert("display_name".to_string(), json!(format!("{} flush target (placeholder)", cache_name)));
        let ph_node = Node::new(Some(placeholder_id.clone()), Some(ph_data), false, false, None, false, None, None, false, false, 0, false, false, None, None);
        graph.add_node(ph_node);

        // Edge: flush signal -> placeholder
        let mut flush_edge_data: HashMap<String, Value> = HashMap::new();
        flush_edge_data.insert("type".to_string(), json!("cache_flush"));
        flush_edge_data.insert("target_cache".to_string(), json!(cache_name));
        flush_edge_data.insert("untied".to_string(), json!(true));
        let flush_edge = Edge::new(flush_node_id, placeholder_id, None, Some(flush_edge_data));
        graph.add_edge(flush_edge);

        Ok(())
    }

    // -----------------------------------------------------------------------
    // aspect declaration
    // -----------------------------------------------------------------------

    pub fn parse_aspect_declaration(&mut self, graph: &mut ResourceGraph) -> Result<(), String> {
        self.consume(&TokenType::Aspect, "Expected 'aspect'")?;

        // Parse aspect file name
        let mut aspect_file_parts = Vec::new();
        while !self.check(&TokenType::Gates)
            && !self.check(&TokenType::Semicolon)
            && !self.is_at_end()
        {
            let token = self.peek();
            match token.type_ {
                TokenType::Identifier | TokenType::Colon | TokenType::Dot => {
                    aspect_file_parts.push(token.value.clone());
                    self.advance();
                }
                TokenType::Divide => {
                    aspect_file_parts.push(token.value.clone());
                    self.advance();
                }
                _ => break,
            }
        }
        let aspect_file: String = aspect_file_parts.join("");

        // Parse gated states
        let mut gated_states: Vec<String> = Vec::new();
        let mut prioritized_states: HashMap<String, i64> = HashMap::new();

        if self.check(&TokenType::Gates) {
            self.consume(&TokenType::Gates, "Expected 'gates'")?;
            let (state_name, priority) = self.parse_gated_state()?;
            if let Some(p) = priority {
                prioritized_states.insert(state_name, p);
            } else {
                gated_states.push(state_name);
            }

            while self.check(&TokenType::Comma) {
                self.consume(&TokenType::Comma, "Expected ','")?;
                let (state_name, priority) = self.parse_gated_state()?;
                if let Some(p) = priority {
                    prioritized_states.insert(state_name, p);
                } else {
                    gated_states.push(state_name);
                }
            }
        }

        self.consume(&TokenType::Semicolon, "Expected ';'")?;

        let order = graph.aspect_declarations.len();
        graph.aspect_declarations.push(json!({
            "file": aspect_file,
            "gated_states": gated_states,
            "prioritized_states": prioritized_states,
            "order": order
        }));

        Ok(())
    }

    fn parse_gated_state(&mut self) -> Result<(String, Option<i64>), String> {
        let state_name = self.consume(&TokenType::Identifier, "Expected state name")?.value;
        let mut priority = None;

        if self.check(&TokenType::Colon) {
            self.consume(&TokenType::Colon, "Expected ':'")?;
            let priority_token = self.consume(&TokenType::Number, "Expected priority number after ':'")?;
            let p: i64 = priority_token.value.parse().unwrap_or(0);
            if p < 1 {
                return Err(format!(
                    "Priority must be >= 1, got {} for state '{}'",
                    p, state_name
                ));
            }
            priority = Some(p);
        }

        Ok((state_name, priority))
    }

    // -----------------------------------------------------------------------
    // CAM declaration
    // -----------------------------------------------------------------------

    pub fn parse_cam_declaration(&mut self, graph: &mut ResourceGraph) -> Result<(), String> {
        self.consume(&TokenType::Cam, "Expected 'cam'")?;

        let name = self.consume(&TokenType::Identifier, "Expected CAM name")?.value;

        // Parse key width
        let key_dim = self.parse_array_dimension()?;
        let key_width = key_dim.0 - key_dim.1 + 1;

        // Parse value width
        let val_dim = self.parse_array_dimension()?;
        let val_width = val_dim.0 - val_dim.1 + 1;

        // Parse number of entries (ways)
        let mut num_ways: i64 = 1;
        if self.check(&TokenType::Lbracket) {
            let ways_dim = self.parse_array_dimension()?;
            num_ways = ways_dim.0 - ways_dim.1 + 1;
        }

        self.consume(&TokenType::Semicolon, "Expected ';'")?;

        let cam_info = json!({
            "key_width": key_width,
            "value_width": val_width,
            "num_ways": num_ways,
        });

        self.cam_declarations.insert(name.clone(), cam_info.clone());

        // Create a node for the CAM
        let mut node_data: HashMap<String, Value> = HashMap::new();
        node_data.insert("type".to_string(), json!("cam"));
        node_data.insert("name".to_string(), json!(name));
        node_data.insert("display_name".to_string(), json!(name));
        node_data.insert("key_width".to_string(), json!(key_width));
        node_data.insert("value_width".to_string(), json!(val_width));
        node_data.insert("num_ways".to_string(), json!(num_ways));
        node_data.insert("bit_width".to_string(), json!(val_width));

        let node = Node::new(
            Some(name),
            Some(node_data),
            true, false, None, false, None, None,
            true, false, 0, false, false, None, None,
        );
        graph.add_node(node);

        Ok(())
    }
}
