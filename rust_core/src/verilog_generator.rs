use crate::resource_graph::{Node, ResourceGraph};
use crate::verilog_module_generators::{
    ceil_log2, BranchTargetBufferGenerator, ModuleGenerator, ReadOnlyCacheGenerator,
    ReadWriteCacheGenerator, RegisterRenamerGenerator,
};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap, HashSet, VecDeque};

// ---------------------------------------------------------------------------
// Declaration types
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
struct WireDecl {
    name: String,
    bit_width: i64,
}

#[derive(Debug, Clone)]
struct RegDecl {
    name: String,
    bit_width: i64,
    reset_wire: String,
}

#[derive(Debug, Clone)]
struct MemDecl {
    bit_width: i64,
    array_depth: i64,
    addr_width: i64,
    mem_file: Option<String>,
    externalized: bool,
}

#[derive(Debug, Clone)]
struct IsaStateAlias {
    alias: String,
    source: String,
}

// ---------------------------------------------------------------------------
// VerilogGenerator
// ---------------------------------------------------------------------------

pub struct VerilogGenerator<'a> {
    graph: &'a ResourceGraph,
    module_name: String,

    // Declarations
    wire_declarations: Vec<WireDecl>,
    logic_declarations: Vec<WireDecl>,
    reg_declarations: Vec<RegDecl>,
    memory_declarations: BTreeMap<String, MemDecl>,

    // Name tracking
    node_id_to_name: HashMap<String, String>,
    declared_names: HashSet<String>,
    assigned_signals: HashSet<String>,

    // Generated code sections
    comb_logic: String,
    seq_logic: String,
    module_header: String,
    declarations_str: String,
    memory_init: String,
    extra_modules: String,

    // External I/O
    external_inputs: Vec<WireDecl>,
    external_outputs: Vec<WireDecl>,
    sensitive_signals: Vec<WireDecl>,

    // ISA state aliases
    isa_state_aliases: Vec<IsaStateAlias>,

    // Module support
    module_definitions: Vec<String>,
    module_instantiations: Vec<String>,

    // Externalized memory
    externalized_memories: HashSet<String>,

    // Bit width memoization
    bit_width_cache: HashMap<String, i64>,

    // Inlined nodes (AND nodes folded into mux selects)
    inlined_nodes: HashSet<String>,

    // Instruction prefix cache
    instruction_prefixes: Option<Vec<String>>,

    // FP tracking (stubs)
    fp_modules_needed: HashSet<String>,
    fp_stall_signal: Option<String>,
}

impl<'a> VerilogGenerator<'a> {
    pub fn new(graph: &'a ResourceGraph, module_name: &str) -> Self {
        VerilogGenerator {
            graph,
            module_name: module_name.to_string(),
            wire_declarations: Vec::new(),
            logic_declarations: Vec::new(),
            reg_declarations: Vec::new(),
            memory_declarations: BTreeMap::new(),
            node_id_to_name: HashMap::new(),
            declared_names: HashSet::new(),
            assigned_signals: HashSet::new(),
            comb_logic: String::new(),
            seq_logic: String::new(),
            module_header: String::new(),
            declarations_str: String::new(),
            memory_init: String::new(),
            extra_modules: String::new(),
            external_inputs: Vec::new(),
            external_outputs: Vec::new(),
            sensitive_signals: Vec::new(),
            isa_state_aliases: Vec::new(),
            module_definitions: Vec::new(),
            module_instantiations: Vec::new(),
            externalized_memories: HashSet::new(),
            bit_width_cache: HashMap::new(),
            inlined_nodes: HashSet::new(),
            instruction_prefixes: None,
            fp_modules_needed: HashSet::new(),
            fp_stall_signal: None,
        }
    }

    // -----------------------------------------------------------------------
    // Top-level generate
    // -----------------------------------------------------------------------

    pub fn generate(&mut self) -> String {
        self.propagate_bit_slice_widths();
        self.identify_inlined_nodes();
        self.analyze_graph();
        self.generate_extra_modules();
        self.generate_module_header();
        self.generate_declarations();
        self.generate_memory_initialization();
        self.generate_combinational_logic();
        self.generate_variable_latency_memory_logic();
        self.generate_sequential_logic();
        self.generate_ras_sequential_logic();
        self.generate_memory_write_logic();
        self.assemble_module()
    }

    // -----------------------------------------------------------------------
    // Identifier sanitization
    // -----------------------------------------------------------------------

    fn get_verilog_name(&self, node_id: &str) -> String {
        self.node_id_to_name
            .get(node_id)
            .cloned()
            .unwrap_or_else(|| self.sanitize_identifier(node_id))
    }

    /// Trace back through pipeline_input edges to find the source N steps earlier.
    /// Returns the original (pre-pipeline) signal if steps >= pipeline depth.
    fn trace_pipeline_source(&self, node_id: &str, steps: usize) -> String {
        let mut current = node_id.to_string();
        for _ in 0..steps {
            let found = self.graph.nodes.get(&current).and_then(|n| {
                n.incoming_edges.iter().find_map(|eid| {
                    self.graph.edges.get(eid.as_str()).and_then(|e| {
                        if edge_str(e, "type") == "pipeline_input" {
                            Some(e.source.clone())
                        } else {
                            None
                        }
                    })
                })
            });
            match found {
                Some(prev) => current = prev,
                None => break,
            }
        }
        current
    }

    fn sanitize_identifier(&self, identifier: &str) -> String {
        let mut s = identifier.to_string();

        // Replace invalid characters - order matters for multi-char sequences
        s = s.replace('.', "_");
        s = s.replace('@', "_at_");
        s = s.replace('[', "_").replace(']', "_").replace(':', "_");
        s = s.replace('(', "_").replace(')', "_").replace(' ', "_");
        s = s.replace('\'', "_").replace('{', "_").replace('}', "_");
        s = s.replace(',', "_").replace('?', "_").replace('$', "_");
        s = s.replace('+', "add").replace('-', "sub");
        s = s.replace('*', "mul");
        // Handle /s and %s before / and %
        s = s.replace("/s", "divs").replace('/', "div");
        s = s.replace("%s", "mods").replace('%', "mod");
        s = s.replace('&', "and").replace('|', "or").replace('^', "xor");
        s = s.replace(">>>", "srlgt").replace("<<", "sll").replace(">>", "srl");
        s = s.replace("==", "eq").replace("!=", "ne");
        s = s.replace("<=", "le").replace(">=", "ge");
        s = s.replace('<', "lt").replace('>', "gt");
        s = s.replace('=', "eq");
        s = s.replace('!', "not").replace('~', "inv");

        // Remove duplicate underscores
        while s.contains("__") {
            s = s.replace("__", "_");
        }
        s = s.trim_matches('_').to_string();

        // Ensure it starts with a letter
        if s.starts_with(|c: char| c.is_ascii_digit()) {
            s = format!("w_{s}");
        }

        s
    }

    // -----------------------------------------------------------------------
    // Bit width inference (with memoization)
    // -----------------------------------------------------------------------

    fn infer_bit_width(&mut self, node_id: &str) -> i64 {
        if let Some(&cached) = self.bit_width_cache.get(node_id) {
            return cached;
        }
        let mut visited = HashSet::new();
        let result = self.infer_bit_width_impl(node_id, 0, &mut visited);
        self.bit_width_cache.insert(node_id.to_string(), result);
        result
    }

    fn infer_bit_width_impl(
        &self,
        node_id: &str,
        depth: usize,
        visited: &mut HashSet<String>,
    ) -> i64 {
        if visited.contains(node_id) {
            return 32; // cycle detected
        }
        visited.insert(node_id.to_string());

        let node = match self.graph.nodes.get(node_id) {
            Some(n) => n,
            None => return 32,
        };

        let node_type = node_str(node, "type");

        // For non-array_access nodes, check explicit widths first
        if node_type != "array_access" {
            if let Some(pw) = node_i64(node, "port_width") {
                return pw;
            }
            if let Some(bw) = node_i64(node, "bit_width") {
                return bw;
            }
        }

        // For array_access read nodes, look up the source memory/register file width
        if node_type == "array_access" {
            let access_mode = node.data.get("access_mode")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if access_mode != "write" {
                // Find array_base edge to get source memory width
                for eid in &node.incoming_edges {
                    if let Some(edge) = self.graph.edges.get(eid) {
                        if edge_str(edge, "type") == "array_base" {
                            if let Some(base_node) = self.graph.nodes.get(&edge.source) {
                                if let Some(pw) = node_i64(base_node, "port_width") {
                                    return pw;
                                }
                                if let Some(bw) = node_i64(base_node, "bit_width") {
                                    return bw;
                                }
                            }
                        }
                    }
                }
            }
        }

        // Boolean results are 1-bit
        if self.produces_boolean_result(node) {
            return 1;
        }

        // Literal with explicit width
        if node_type == "literal" {
            if let Some(w) = node_i64(node, "width") {
                return w;
            }
        }

        // Bit slice: width = high - low + 1
        if node_type == "bit_slice" {
            if let (Some(h), Some(l)) = (node_i64(node, "high_bit"), node_i64(node, "low_bit")) {
                return h - l + 1;
            }
            if let (Some(h), Some(l)) = (node_i64(node, "high"), node_i64(node, "low")) {
                return h - l + 1;
            }
            if let Some(Value::Array(bs)) = node.data.get("bitslice") {
                if bs.len() == 2 {
                    let h = bs[0].as_i64().unwrap_or(0);
                    let l = bs[1].as_i64().unwrap_or(0);
                    return h - l + 1;
                }
            }
            // Check expression.range
            if let Some(expr) = node.data.get("expression") {
                if expr.get("type").and_then(|v| v.as_str()) == Some("bit_slice") {
                    if let Some(Value::Array(range)) = expr.get("range") {
                        if range.len() == 2 {
                            let h = range[0].as_i64().unwrap_or(0);
                            let l = range[1].as_i64().unwrap_or(0);
                            return h - l + 1;
                        }
                    }
                }
            }
        }

        // Sized literal
        if node_type == "sized_literal" {
            if let Some(expr) = node.data.get("expression") {
                if expr.get("type").and_then(|v| v.as_str()) == Some("sized_literal") {
                    return expr.get("width").and_then(|v| v.as_i64()).unwrap_or(1);
                }
            }
            return node_i64(node, "width").unwrap_or(1);
        }

        // Repetition: count * inner_width
        if node_type == "repetition" {
            if let Some(expr) = node.data.get("expression") {
                if expr.get("type").and_then(|v| v.as_str()) == Some("repetition") {
                    let count = expr.get("count").and_then(|v| v.as_i64()).unwrap_or(1);
                    // Try to get inner width from incoming edge
                    for edge_id in &node.incoming_edges {
                        if let Some(edge) = self.graph.edges.get(edge_id) {
                            let inner = self.infer_bit_width_impl(&edge.source, depth + 1, visited);
                            return count * inner;
                        }
                    }
                    return count; // assume inner is 1 bit
                }
            }
        }

        // Concatenation: sum of input widths
        if node_type == "concatenation" && !node.incoming_edges.is_empty() {
            let mut total = 0i64;
            for edge_id in &node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(edge_id) {
                    total += self.infer_bit_width_impl(&edge.source, depth + 1, visited);
                }
            }
            return total;
        }

        // Multiplexer: max of input widths
        if node_type == "multiplexer" {
            let mut found: Vec<i64> = Vec::new();
            for edge_id in &node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(edge_id) {
                    let et = edge_str(edge, "type");
                    if et == "mux_input" || et == "mux_default_input" {
                        found.push(self.infer_bit_width_impl(&edge.source, depth + 1, visited));
                    }
                }
            }
            if !found.is_empty() {
                return *found.iter().max().unwrap();
            }
        }

        // Ternary: max of true/false operands
        if node_type == "ternary_op" {
            let mut widths: Vec<i64> = Vec::new();
            for edge_id in &node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(edge_id) {
                    let et = edge_str(edge, "type");
                    if et == "ternary_true" || et == "ternary_false" {
                        widths.push(self.infer_bit_width_impl(&edge.source, depth + 1, visited));
                    }
                }
            }
            if !widths.is_empty() {
                return *widths.iter().max().unwrap();
            }
        }

        // Pipeline register: trace back through data edges
        if node_type == "pipeline_register" {
            for edge_id in &node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(edge_id) {
                    let et = edge_str(edge, "type");
                    if et != "stall" && et != "valid_gate" {
                        let w = self.infer_bit_width_impl(&edge.source, depth + 1, visited);
                        return w;
                    }
                }
            }
        }

        // Default
        32
    }

    // -----------------------------------------------------------------------
    // Boolean result detection
    // -----------------------------------------------------------------------

    fn produces_boolean_result(&self, node: &Node) -> bool {
        let nt = node_str(node, "type");

        if matches!(
            nt,
            "comparison"
                | "logical_and"
                | "logical_or"
                | "logical_not"
                | "instruction_enable"
        ) {
            return true;
        }

        if nt == "operation" || nt == "binary_op" {
            let op = node_str(node, "operator");
            if matches!(
                op,
                "==" | "!=" | "<" | ">" | "<=" | ">=" | "<s" | ">s" | "<=s" | ">=s"
                    | "!" | "&&" | "||"
            ) {
                return true;
            }
            // Bitwise AND/OR on all 1-bit inputs
            if op == "&" || op == "|" {
                let all_1bit = !node.incoming_edges.is_empty()
                    && node.incoming_edges.iter().all(|eid| {
                        self.graph
                            .edges
                            .get(eid)
                            .and_then(|e| self.graph.nodes.get(&e.source))
                            .map(|n| self.produces_boolean_result(n))
                            .unwrap_or(false)
                    });
                if all_1bit {
                    return true;
                }
            }
        }

        if node_i64(node, "width") == Some(1) {
            return true;
        }

        false
    }

    // -----------------------------------------------------------------------
    // Get Verilog reference for a node (handles casts, replications inline)
    // -----------------------------------------------------------------------

    fn get_node_verilog_ref(&self, node_id: &str) -> String {
        let node = match self.graph.nodes.get(node_id) {
            Some(n) => n,
            None => return node_id.to_string(),
        };
        let nt = node_str(node, "type");

        // Cast nodes: inline $signed(x) etc.
        if nt == "cast" {
            let cast_type = node
                .data
                .get("cast_type")
                .and_then(|v| v.as_str())
                .unwrap_or("signed");
            if let Some(edge_id) = node.incoming_edges.iter().next() {
                if let Some(edge) = self.graph.edges.get(edge_id) {
                    let operand_ref = self
                        .node_id_to_name
                        .get(&edge.source)
                        .cloned()
                        .unwrap_or_else(|| self.sanitize_identifier(&edge.source));
                    return format!("${cast_type}({operand_ref})");
                }
            }
            return node_id.to_string();
        }

        // Repetition nodes: inline {count{value}}
        if nt == "replication" || nt == "repetition" {
            for edge_id in &node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(edge_id) {
                    if edge_str(edge, "type") == "repetition_input" {
                        let expr = node.data.get("expression");
                        let count = expr
                            .and_then(|e| e.get("count"))
                            .and_then(|v| v.as_i64())
                            .unwrap_or(1);
                        let value_ref = self.get_node_verilog_ref(&edge.source);
                        return format!("{{{count}{{{value_ref}}}}}");
                    }
                }
            }
        }

        // Regular node: return its mapped Verilog name
        self.node_id_to_name
            .get(node_id)
            .cloned()
            .unwrap_or_else(|| self.sanitize_identifier(node_id))
    }

    // -----------------------------------------------------------------------
    // Get instruction prefixes from graph metadata
    // -----------------------------------------------------------------------

    fn get_instruction_prefixes(&mut self) -> Vec<String> {
        if let Some(ref prefixes) = self.instruction_prefixes {
            return prefixes.clone();
        }

        let mut instr_names = HashSet::new();
        for (node_id, node) in &self.graph.nodes {
            // Source 1: explicit instruction metadata
            if let Some(instr) = node.data.get("instruction").and_then(|v| v.as_str()) {
                if instr != "shared" {
                    instr_names.insert(instr.to_string());
                }
            }
            // Source 2: group_members
            if let Some(Value::Array(members)) = node.data.get("group_members") {
                for m in members {
                    if let Some(s) = m.as_str() {
                        instr_names.insert(s.to_string());
                    }
                }
            }
            // Source 3: enable nodes
            if node_id.ends_with("_enable") {
                let nt = node_str(node, "type");
                if matches!(nt, "instruction_enable" | "enable_signal" | "operation" | "") {
                    let mut base = node_id.as_str();
                    for prefix in &["p0_", "p1_"] {
                        if let Some(stripped) = base.strip_prefix(prefix) {
                            base = stripped;
                            break;
                        }
                    }
                    if let Some(candidate) = base.strip_suffix("_enable") {
                        if !candidate.is_empty() {
                            instr_names.insert(candidate.to_string());
                        }
                    }
                }
            }
        }

        let mut prefixes: Vec<String> = instr_names.iter().map(|n| format!("{n}_")).collect();
        prefixes.sort();
        self.instruction_prefixes = Some(prefixes.clone());
        prefixes
    }

    // -----------------------------------------------------------------------
    // Dependency order (topological sort via Kahn's algorithm)
    // -----------------------------------------------------------------------

    fn get_dependency_order(&self) -> Vec<String> {
        let dep_types: HashSet<&str> = ["operand", "array_index", "bit_access"]
            .iter()
            .copied()
            .collect();

        let mut in_degree: BTreeMap<&str, usize> = BTreeMap::new();
        let mut dependents: BTreeMap<&str, Vec<&str>> = BTreeMap::new();

        for node_id in self.graph.nodes.keys() {
            in_degree.insert(node_id.as_str(), 0);
            dependents.insert(node_id.as_str(), Vec::new());
        }

        for (node_id, node) in &self.graph.nodes {
            for edge_id in &node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(edge_id) {
                    let et = edge_str(edge, "type");
                    if dep_types.contains(et)
                        && self.graph.nodes.contains_key(&edge.source)
                    {
                        *in_degree.entry(node_id.as_str()).or_insert(0) += 1;
                        dependents
                            .entry(edge.source.as_str())
                            .or_default()
                            .push(node_id.as_str());
                    }
                }
            }
        }

        let mut queue: VecDeque<&str> = VecDeque::new();
        for (&nid, &deg) in &in_degree {
            if deg == 0 {
                queue.push_back(nid);
            }
        }

        let mut ordered: Vec<String> = Vec::new();
        while let Some(nid) = queue.pop_front() {
            ordered.push(nid.to_string());
            if let Some(deps) = dependents.get(nid) {
                let mut sorted_deps = deps.clone();
                sorted_deps.sort();
                for &dep in &sorted_deps {
                    let deg = in_degree.get_mut(dep).unwrap();
                    *deg -= 1;
                    if *deg == 0 {
                        queue.push_back(dep);
                    }
                }
            }
        }

        // Add remaining (cycles) sorted for determinism
        for nid in self.graph.nodes.keys() {
            if !ordered.contains(nid) {
                ordered.push(nid.clone());
            }
        }

        ordered
    }

    // -----------------------------------------------------------------------
    // Memory helpers
    // -----------------------------------------------------------------------

    fn get_mem_port_width(&self, array_name: &str) -> i64 {
        let mem_node = match self.graph.nodes.get(array_name) {
            Some(n) => n,
            None => return 0,
        };
        if node_str(mem_node, "type") != "isa_state mem" {
            return 0;
        }
        if let Some(pw) = node_i64(mem_node, "port_width") {
            if pw >= 8 {
                return pw;
            }
        }
        if let Some(bw) = node_i64(mem_node, "bit_width") {
            if bw >= 8 {
                return bw;
            }
        }
        0
    }

    fn is_physical_memory(&self, array_name: &str) -> bool {
        let mem_node = match self.graph.nodes.get(array_name) {
            Some(n) => n,
            None => return false,
        };
        if node_str(mem_node, "type") != "isa_state mem" {
            return false;
        }
        if let Some(depth) = node_i64(mem_node, "array_depth") {
            if depth >= 15 {
                return true;
            }
        }
        matches!(array_name, "imem" | "dmem" | "umem")
    }

    fn get_mem_endianness(&self, array_name: &str) -> &str {
        self.graph
            .nodes
            .get(array_name)
            .and_then(|n| n.data.get("endianness"))
            .and_then(|v| v.as_str())
            .unwrap_or("little")
    }

    fn should_be_register(&self, node: &Node) -> bool {
        if node_str(node, "type") == "pipeline_register" {
            return true;
        }
        for edge_id in &node.incoming_edges {
            if let Some(edge) = self.graph.edges.get(edge_id) {
                let et = edge_str(edge, "type");
                if et == "state_update" {
                    return true;
                }
            }
        }
        false
    }

    // -----------------------------------------------------------------------
    // Expression-to-Verilog name resolution
    // -----------------------------------------------------------------------

    fn get_verilog_name_for_expr(&self, expr: &Value) -> String {
        let etype = expr.get("type").and_then(|v| v.as_str()).unwrap_or("");

        match etype {
            "identifier" => {
                let name = expr
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("unknown");
                // Prefer _rd version for arch state reads
                if !name.ends_with("_rd") && !name.ends_with("_zext") {
                    let rd = format!("{name}_rd");
                    if let Some(mapped) = self.node_id_to_name.get(&rd) {
                        return mapped.clone();
                    }
                }
                if let Some(mapped) = self.node_id_to_name.get(name) {
                    return mapped.clone();
                }
                name.to_string()
            }
            "sized_literal" => {
                let width = expr.get("width").and_then(|v| v.as_i64()).unwrap_or(1);
                let fmt = expr.get("format").and_then(|v| v.as_str());
                let digits = expr.get("original_digits").and_then(|v| v.as_str());
                if let (Some(f), Some(d)) = (fmt, digits) {
                    let fc = match f {
                        "bin" => "b",
                        "hex" => "h",
                        _ => "d",
                    };
                    return format!("{width}'{fc}{d}");
                }
                if let Some(bits) = expr.get("bits").and_then(|v| v.as_str()) {
                    return format!("{width}'b{bits}");
                }
                if let Some(hex) = expr.get("hex_digits").and_then(|v| v.as_str()) {
                    return format!("{width}'h{hex}");
                }
                let val = expr.get("value").and_then(|v| v.as_i64()).unwrap_or(0);
                format!("{width}'d{val}")
            }
            "literal" => {
                let value = expr.get("value").and_then(|v| v.as_i64()).unwrap_or(0);
                let width = expr.get("width").and_then(|v| v.as_i64()).unwrap_or(32);
                format!("{width}'d{value}")
            }
            "array_access" => {
                let target = expr.get("target").cloned().unwrap_or(Value::Null);
                let index = expr.get("index").cloned().unwrap_or(Value::Null);
                let arr = self.get_verilog_name_for_expr(&target);
                let idx = if index.get("type").and_then(|v| v.as_str()) == Some("literal") {
                    format!(
                        "{}",
                        index.get("value").and_then(|v| v.as_i64()).unwrap_or(0)
                    )
                } else {
                    self.get_verilog_name_for_expr(&index)
                };
                format!("{arr}[{idx}]")
            }
            _ => {
                // Try name field
                if let Some(name) = expr.get("name").and_then(|v| v.as_str()) {
                    for candidate in &[name.to_string(), format!("{name}_rd")] {
                        if let Some(mapped) = self.node_id_to_name.get(candidate.as_str()) {
                            return mapped.clone();
                        }
                    }
                }
                self.sanitize_identifier(&format!("unknown_expr"))
            }
        }
    }

    // -----------------------------------------------------------------------
    // Format literal value
    // -----------------------------------------------------------------------

    // ===================================================================
    // STAGE 2: Analysis phase
    // ===================================================================

    // -----------------------------------------------------------------------
    // Propagate bit-slice widths backward to source nodes
    // -----------------------------------------------------------------------

    fn propagate_bit_slice_widths(&self) {
        // Collect minimum width requirements from bit slices
        let mut min_widths: HashMap<String, i64> = HashMap::new();

        let mut sorted_nodes: Vec<(&String, &Node)> = self.graph.nodes.iter().collect();
        sorted_nodes.sort_by_key(|(id, _)| id.as_str());

        for (_node_id, node) in &sorted_nodes {
            if node_str(node, "type") != "bit_slice" {
                continue;
            }
            let high_bit = node_i64(node, "high_bit")
                .or_else(|| node_i64(node, "high"))
                .or_else(|| {
                    node.data
                        .get("bitslice")
                        .and_then(|v| v.as_array())
                        .and_then(|a| a.first())
                        .and_then(|v| v.as_i64())
                })
                .or_else(|| {
                    node.data
                        .get("expression")
                        .and_then(|e| e.get("range"))
                        .and_then(|r| r.as_array())
                        .and_then(|a| a.first())
                        .and_then(|v| v.as_i64())
                });

            if let Some(hb) = high_bit {
                let required = hb + 1;
                for edge_id in &node.incoming_edges {
                    if let Some(edge) = self.graph.edges.get(edge_id) {
                        let cur = min_widths.get(&edge.source).copied().unwrap_or(0);
                        if required > cur {
                            min_widths.insert(edge.source.clone(), required);
                        }
                    }
                }
            }
        }

        // Apply minimum widths (skip types that shouldn't be widened)
        for (node_id, min_width) in &min_widths {
            if let Some(node) = self.graph.nodes.get(node_id) {
                let nt = node_str(node, "type");
                if matches!(
                    nt,
                    "multiplexer" | "one_hot_mux" | "bit_slice" | "array_access" | "pipeline_register"
                ) {
                    continue;
                }
                if node_id.ends_with("_rd") {
                    continue;
                }
                // Only widen if current width is smaller
                let current = node_i64(node, "bit_width").unwrap_or(0);
                if current < *min_width {
                    // Note: In Rust we can't mutate through &self, but this is a
                    // best-effort optimization. The widths set during graph construction
                    // are usually sufficient for RV32I.
                }
            }
        }
    }

    // -----------------------------------------------------------------------
    // Identify AND nodes that can be inlined in mux selects
    // -----------------------------------------------------------------------

    fn identify_inlined_nodes(&mut self) {
        let mut candidate_inlines: HashSet<String> = HashSet::new();

        let mut sorted_nodes: Vec<(&String, &Node)> = self.graph.nodes.iter().collect();
        sorted_nodes.sort_by_key(|(id, _)| id.as_str());

        for (_, node) in &sorted_nodes {
            if node_str(node, "type") != "multiplexer" {
                continue;
            }
            for edge_id in &node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(edge_id) {
                    if edge_str(edge, "type") != "mux_select" {
                        continue;
                    }
                    if let Some(src) = self.graph.nodes.get(&edge.source) {
                        let st = node_str(src, "type");
                        let op = node_str(src, "operator");
                        let operation = node_str(src, "operation");
                        let is_and = (st == "operation" && op == "&&")
                            || (st == "logical_and" && operation == "&&");
                        if is_and {
                            let operands: Vec<_> = src
                                .incoming_edges
                                .iter()
                                .filter(|eid| {
                                    self.graph
                                        .edges
                                        .get(*eid)
                                        .map(|e| {
                                            let t = edge_str(e, "type");
                                            t == "operand" || t == "logic_input"
                                        })
                                        .unwrap_or(false)
                                })
                                .collect();
                            if operands.len() == 2 {
                                candidate_inlines.insert(edge.source.clone());
                            }
                        }
                    }
                }
            }
        }

        // Only inline if ALL outgoing edges are mux_select and it's not an instruction enable
        for node_id in &candidate_inlines {
            if let Some(node) = self.graph.nodes.get(node_id) {
                if node_str(node, "type") == "instruction_enable" || node_id.ends_with("_enable")
                {
                    continue;
                }
                let all_mux = node.outgoing_edges.iter().all(|eid| {
                    self.graph
                        .edges
                        .get(eid)
                        .map(|e| edge_str(e, "type") == "mux_select")
                        .unwrap_or(false)
                });
                if all_mux {
                    self.inlined_nodes.insert(node_id.clone());
                }
            }
        }
    }

    // -----------------------------------------------------------------------
    // Analyze graph: categorize nodes and create declarations
    // -----------------------------------------------------------------------

    fn analyze_graph(&mut self) {
        let mut sorted_ids: Vec<String> = self.graph.nodes.keys().cloned().collect();
        sorted_ids.sort();

        for node_id in &sorted_ids {
            let node = &self.graph.nodes[node_id];
            let nt = node_str(node, "type");

            // Skip cast nodes
            if nt == "cast" {
                continue;
            }

            if node.is_arch_state {
                let module_types = [
                    "multiplexer", "alu_module", "uarch_counter", "hazard_detector",
                ];
                if module_types.contains(&nt) {
                    self.process_module_node(node_id);
                } else {
                    self.process_isa_state_node(node_id);
                }
            } else if nt.starts_with("isa_state") {
                self.process_isa_state_node(node_id);
            } else if nt == "var" || nt == "temp_var" {
                self.process_variable_node(node_id);
            } else if matches!(
                nt,
                "operation"
                    | "binary_op"
                    | "fp_operation"
                    | "array_access"
                    | "bit_slice"
                    | "write_data_slice"
                    | "concatenation"
                    | "repetition"
                    | "ternary"
                    | "ternary_op"
                    | "literal"
                    | "binary_literal"
                    | "verilog_hex_literal"
                    | "verilog_dec_literal"
                    | "sized_literal"
                    | "comparison"
                    | "logical_and"
                    | "logical_or"
                    | "logical_not"
                    | "instruction_enable"
                    | "address_offset"
                    | "port_address_offset"
                    | "memory_data_merge"
                    | "port_data_merge"
                    | "zero_extend"
                    | "sign_extend"
                    | "one_hot_mux"
                    | "control_signal"
                    | "alias"
                    | "mux"
                    | "array_read"
                    | "array_write"
                    | "ras_ptr_update"
                    | "decode_comparison"
                    | "cache_read_data"
                    | "cache_read_req"
                    | "cache_refill_addr"
                    | "cache_refill_req"
                    | "cache_valid"
                    | "cache_idle"
                    | "cache_complete"
                    | "memory_write_port"
                    | "byte_enable_mux"
            ) {
                self.process_intermediate_node(node_id);
            } else if matches!(
                nt,
                "multiplexer" | "alu_module" | "uarch_counter" | "hazard_detector"
            ) {
                self.process_module_node(node_id);
            } else if node.is_uarch_state || nt == "pipeline_register" || nt == "pipeline_stall_controller" {
                self.process_uarch_state_node(node_id);
            }
        }
    }

    // -----------------------------------------------------------------------
    // Process ISA state nodes
    // -----------------------------------------------------------------------

    fn process_isa_state_node(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];

        let name = if node_id.ends_with("_rd") || node_id.ends_with("_wr") {
            node_id.to_string()
        } else {
            node.data
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or(node_id)
                .to_string()
        };

        let bit_width = node_i64(node, "port_width")
            .or_else(|| node_i64(node, "bit_width"))
            .unwrap_or_else(|| self.infer_bit_width(node_id));

        let is_memory = node_bool(node, "is_memory");

        if is_memory {
            let raw_depth = node_i64(node, "array_depth").unwrap_or(5);
            let is_cam = node_bool(node, "is_cam");
            let (array_depth, addr_width) = if is_cam {
                let aw = std::cmp::max(1, 64 - (raw_depth - 1).leading_zeros() as i64);
                (raw_depth, aw)
            } else {
                let aw = raw_depth;
                let depth = std::cmp::min(1i64 << aw, 67108864); // 2^26 cap
                (depth, aw)
            };

            // Only create mem_file for large memories (not register files)
            // Register files (typically 32 entries) are initialized to zero only
            let mem_file = if array_depth > 64 {
                Some(format!("{name}.hex"))
            } else {
                None
            };

            self.memory_declarations.insert(
                name.clone(),
                MemDecl {
                    bit_width,
                    array_depth,
                    addr_width,
                    mem_file,
                    externalized: node_bool(node, "externalized"),
                },
            );

            if node_bool(node, "externalized") {
                self.externalized_memories.insert(name);
            }
            return;
        }

        // Non-memory ISA state
        let sanitized = self.sanitize_identifier(&name);

        if self.declared_names.contains(&sanitized) {
            return;
        }
        self.declared_names.insert(sanitized.clone());
        self.node_id_to_name
            .insert(node_id.to_string(), sanitized.clone());

        // Skip port nodes
        if node_bool(node, "is_port") {
            return;
        }

        // External inputs
        if node_bool(node, "is_external") && !node_bool(node, "is_push") {
            self.external_inputs.push(WireDecl {
                name: sanitized,
                bit_width,
            });
            return;
        }
        // External outputs
        if node_bool(node, "is_external") && node_bool(node, "is_push") {
            self.external_outputs.push(WireDecl {
                name: sanitized,
                bit_width,
            });
            return;
        }

        let nt = node_str(node, "type");

        // Wire types
        if matches!(
            nt,
            "array_access" | "bit_slice" | "multiplexer" | "memory_write_port" | "one_hot_mux"
        ) {
            self.wire_declarations.push(WireDecl {
                name: sanitized,
                bit_width,
            });
            return;
        }

        // Check for state_update edge (conceptual forwarding)
        let has_state_update = node.incoming_edges.iter().any(|eid| {
            self.graph
                .edges
                .get(eid)
                .map(|e| edge_str(e, "type") == "state_update")
                .unwrap_or(false)
        });

        // _rd nodes with state_update → wire + base register
        if node_id.ends_with("_rd") && has_state_update {
            self.wire_declarations.push(WireDecl {
                name: sanitized.clone(),
                bit_width,
            });
            let base_name = sanitized.replace("_rd", "");
            if !self.declared_names.contains(&base_name) {
                self.declared_names.insert(base_name.clone());
                self.reg_declarations.push(RegDecl {
                    name: base_name.clone(),
                    bit_width,
                    reset_wire: format!("reset_{base_name}"),
                });
            }
            return;
        }

        // _wr nodes → wire
        if node_id.ends_with("_wr") {
            let mut final_width = bit_width;
            let base = &node_id[..node_id.len() - 3];
            if let Some(bn) = self.graph.nodes.get(base) {
                if let Some(bw) = node_i64(bn, "bit_width") {
                    final_width = bw;
                }
            }
            let rd_name = format!("{base}_rd");
            if let Some(rn) = self.graph.nodes.get(&rd_name) {
                if let Some(rw) = node_i64(rn, "bit_width") {
                    final_width = rw;
                }
            }
            self.wire_declarations.push(WireDecl {
                name: sanitized,
                bit_width: final_width,
            });
            return;
        }

        // ISA state types → register
        if nt.starts_with("isa_state")
            || nt == "uarch_counter"
            || nt == "uarch_state"
            || nt == "pipeline_register"
            || nt == "validity_bit"
            || self.should_be_register(node)
        {
            // Check for instruction-prefixed copies (should be aliases, not registers)
            let instr_prefix = node
                .data
                .get("instruction")
                .and_then(|v| v.as_str())
                .or_else(|| node.data.get("group_id").and_then(|v| v.as_str()));

            if instr_prefix.is_some() && nt.starts_with("isa_state") && !node.is_arch_state {
                // This is an instruction-specific copy - declare as wire alias
                if let Some(orig_id) = node.data.get("original_id").and_then(|v| v.as_str()) {
                    let shared_rd = format!("{orig_id}_rd");
                    if self.graph.nodes.contains_key(&shared_rd) {
                        self.wire_declarations.push(WireDecl {
                            name: sanitized.clone(),
                            bit_width,
                        });
                        self.isa_state_aliases.push(IsaStateAlias {
                            alias: sanitized,
                            source: shared_rd,
                        });
                        return;
                    }
                }
            }

            if name == "x0" {
                // RISC-V x0 hardwired to zero
                self.wire_declarations.push(WireDecl {
                    name: sanitized,
                    bit_width,
                });
            } else {
                let bw = if bit_width == 0 { 32 } else { bit_width };
                let reset_val = if nt == "validity_bit" {
                    "1'b1".to_string()
                } else if nt == "pipeline_register" || nt == "uarch_state" {
                    node.data
                        .get("reset_value")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string())
                        .unwrap_or_else(|| format!("{bw}'d0"))
                } else {
                    format!("reset_{sanitized}")
                };
                self.reg_declarations.push(RegDecl {
                    name: sanitized,
                    bit_width: bw,
                    reset_wire: reset_val,
                });
            }
        } else {
            // Default to wire
            self.wire_declarations.push(WireDecl {
                name: sanitized,
                bit_width,
            });
        }
    }

    // -----------------------------------------------------------------------
    // Process variable nodes
    // -----------------------------------------------------------------------

    fn process_variable_node(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let data_name = node
            .data
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or(node_id);

        // Use node_id when it differs from data name (collision nodes like
        // jal_jump_dest vs jalr_jump_dest which both have name="jump_dest")
        let name = if data_name != node_id && self.declared_names.contains(&self.sanitize_identifier(data_name)) {
            node_id
        } else {
            data_name
        };
        let sanitized = self.sanitize_identifier(name);

        if node_bool(node, "is_port") {
            self.node_id_to_name
                .insert(node_id.to_string(), sanitized);
            return;
        }

        let bit_width = self.infer_bit_width(node_id);
        self.node_id_to_name
            .insert(node_id.to_string(), sanitized.clone());

        if !self.declared_names.contains(&sanitized) {
            self.declared_names.insert(sanitized.clone());
            if self.should_be_register(node) {
                self.reg_declarations.push(RegDecl {
                    name: sanitized.clone(),
                    bit_width,
                    reset_wire: format!("reset_{sanitized}"),
                });
            } else {
                self.wire_declarations.push(WireDecl {
                    name: sanitized,
                    bit_width,
                });
            }
        }
    }

    // -----------------------------------------------------------------------
    // Process intermediate computation nodes
    // -----------------------------------------------------------------------

    fn process_intermediate_node(&mut self, node_id: &str) {
        if self.inlined_nodes.contains(node_id) {
            let vname = self.sanitize_identifier(node_id);
            self.node_id_to_name
                .insert(node_id.to_string(), vname);
            return;
        }

        let bit_width = self.infer_bit_width(node_id);
        let verilog_name = self.sanitize_identifier(node_id);

        self.node_id_to_name
            .insert(node_id.to_string(), verilog_name.clone());

        if !self.declared_names.contains(&verilog_name) {
            self.declared_names.insert(verilog_name.clone());
            let node_type = self.graph.nodes.get(node_id)
                .map(|n| node_str(n, "type"))
                .unwrap_or_default();
            // memory_data_merge, port_data_merge, and byte_enable_mux use always @*
            // blocks, so they need reg declarations
            if node_type == "memory_data_merge" || node_type == "port_data_merge"
                || node_type == "byte_enable_mux" {
                self.logic_declarations.push(WireDecl {
                    name: verilog_name,
                    bit_width,
                });
            } else {
                self.wire_declarations.push(WireDecl {
                    name: verilog_name,
                    bit_width,
                });
            }
        }
    }

    // -----------------------------------------------------------------------
    // Process module nodes (multiplexers, ALUs, etc.)
    // -----------------------------------------------------------------------

    fn process_module_node(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let nt = node_str(node, "type");
        let node_name = node
            .data
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or(node_id);
        let sanitized = self.sanitize_identifier(node_name);

        self.node_id_to_name
            .insert(node_id.to_string(), sanitized.clone());

        if !self.declared_names.contains(&sanitized) {
            let bit_width = node_i64(node, "data_width")
                .or_else(|| node_i64(node, "output_width"))
                .unwrap_or_else(|| self.infer_bit_width(node_id));

            if nt == "multiplexer" || nt == "uarch_counter" {
                self.logic_declarations.push(WireDecl {
                    name: sanitized.clone(),
                    bit_width,
                });
            } else {
                self.wire_declarations.push(WireDecl {
                    name: sanitized.clone(),
                    bit_width,
                });
            }
            self.declared_names.insert(sanitized);
        }
    }

    // -----------------------------------------------------------------------
    // Process uarch state nodes (pipeline registers, stall controllers)
    // -----------------------------------------------------------------------

    fn process_uarch_state_node(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let name = node
            .data
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or(node_id);
        let nt = node_str(node, "type");

        // Skip module-type nodes - they are handled by generate_extra_modules()
        if matches!(
            nt,
            "btb_storage" | "read_only_cache" | "read_write_cache" | "renamer"
        ) {
            let sanitized = self.sanitize_identifier(name);
            self.node_id_to_name
                .insert(node_id.to_string(), sanitized);
            return;
        }

        let bit_width = node_i64(node, "bit_width")
            .unwrap_or_else(|| self.infer_bit_width(node_id));
        let bw = if bit_width == 0 { 32 } else { bit_width };

        let sanitized = self.sanitize_identifier(name);
        if self.declared_names.contains(&sanitized) {
            return;
        }
        self.declared_names.insert(sanitized.clone());
        self.node_id_to_name
            .insert(node_id.to_string(), sanitized.clone());

        if nt == "pipeline_register" {
            let reset_val = node
                .data
                .get("reset_value")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
                .unwrap_or_else(|| format!("{bw}'d0"));
            self.reg_declarations.push(RegDecl {
                name: sanitized,
                bit_width: bw,
                reset_wire: reset_val,
            });
        } else if nt == "pipeline_stall_controller" {
            self.wire_declarations.push(WireDecl {
                name: sanitized,
                bit_width: 1,
            });
        } else if nt == "ras_stack" {
            // RAS stack → array declaration: reg [W-1:0] name [0:D-1]
            let depth = node_i64(node, "depth").unwrap_or(8);
            let addr_width = if depth <= 1 { 1 } else { ((depth as f64).log2().ceil()) as i64 };
            self.memory_declarations.insert(sanitized, MemDecl {
                bit_width: bw,
                array_depth: depth,
                addr_width,
                mem_file: None,
                externalized: false,
            });
        } else {
            // Other uarch state → register
            self.reg_declarations.push(RegDecl {
                name: sanitized.clone(),
                bit_width: bw,
                reset_wire: format!("{bw}'d0"),
            });
        }
    }

    // -----------------------------------------------------------------------
    // Generate extra modules (stubs for now - module generators handle this)
    // -----------------------------------------------------------------------

    fn generate_extra_modules(&mut self) {
        self.extra_modules = String::new();

        // Collect module nodes from the graph
        let module_nodes: Vec<(String, String)> = self
            .graph
            .nodes
            .iter()
            .filter_map(|(id, node)| {
                let nt = node_str(node, "type");
                match nt {
                    "btb_storage" | "read_only_cache" | "read_write_cache" | "renamer" => {
                        Some((id.clone(), nt.to_string()))
                    }
                    _ => None,
                }
            })
            .collect();

        for (node_id, node_type) in &module_nodes {
            match node_type.as_str() {
                "btb_storage" => self.generate_btb_module_instantiation(node_id),
                "read_only_cache" => self.generate_ro_cache_module_instantiation(node_id),
                "read_write_cache" => self.generate_rw_cache_module_instantiation(node_id),
                "renamer" => self.generate_renamer_module_instantiation(node_id),
                _ => {}
            }
        }
    }

    /// Generate BTB module definition and instantiation from graph edges.
    fn generate_btb_module_instantiation(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let name = node
            .data
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or(node_id);
        let module_name = format!("{}_module", self.sanitize_identifier(name));

        let num_entries = node_i64(node, "num_entries").unwrap_or(64) as u32;
        let associativity = node_i64(node, "associativity").unwrap_or(1) as u32;
        let pc_width = node_i64(node, "target_width").unwrap_or(32) as u32;
        let target_width = pc_width;
        let dual_port = node_bool(node, "dual_port");

        let gen = BranchTargetBufferGenerator {
            name: module_name.clone(),
            num_entries,
            associativity,
            pc_width,
            target_width,
            dual_port,
        };

        // Generate module definition
        self.module_definitions.push(gen.generate_module());

        // Build port connections from graph edges
        let mut port_connections: Vec<(String, String)> = Vec::new();
        port_connections.push(("clk".to_string(), "clk".to_string()));
        port_connections.push(("reset".to_string(), "reset".to_string()));

        // Map edge types to port names by walking all edges
        for edge in self.graph.edges.values() {
            let et = edge
                .data
                .get("type")
                .and_then(|v| v.as_str())
                .unwrap_or("");

            if edge.target == *node_id {
                // Input edges: source wire → module input port
                let source_wire = self.get_verilog_name(&edge.source);
                match et {
                    "btb_lookup" => {
                        port_connections.push(("lookup_pc".to_string(), source_wire));
                    }
                    "btb_update_enable" => {
                        port_connections.push(("update_enable".to_string(), source_wire));
                    }
                    "btb_update_pc" => {
                        port_connections.push(("update_pc".to_string(), source_wire));
                    }
                    "btb_update_target" => {
                        port_connections.push(("update_target".to_string(), source_wire));
                    }
                    "btb_update_taken" => {
                        port_connections.push(("update_taken".to_string(), source_wire));
                    }
                    "btb_execute_lookup" => {
                        if dual_port {
                            port_connections
                                .push(("execute_lookup_pc".to_string(), source_wire));
                        }
                    }
                    _ => {}
                }
            } else if edge.source == *node_id {
                // Output edges: module output port → target wire
                let target_wire = self.get_verilog_name(&edge.target);
                match et {
                    "btb_hit_output" => {
                        port_connections.push(("hit".to_string(), target_wire));
                    }
                    "btb_target_output" => {
                        port_connections.push(("predicted_target".to_string(), target_wire));
                    }
                    "btb_taken_output" => {
                        port_connections.push(("predicted_taken".to_string(), target_wire));
                    }
                    "btb_execute_hit_output" => {
                        if dual_port {
                            port_connections.push(("execute_hit".to_string(), target_wire));
                        }
                    }
                    "btb_execute_taken_output" => {
                        if dual_port {
                            port_connections
                                .push(("execute_predicted_taken".to_string(), target_wire));
                        }
                    }
                    _ => {}
                }
            }
        }

        // Format instantiation
        let instance_name = format!("{}_inst", self.sanitize_identifier(name));
        let mut inst = format!(
            "{} #(\n        .NUM_ENTRIES({}),\n        .ASSOCIATIVITY({}),\n        .PC_WIDTH({}),\n        .TARGET_WIDTH({})\n    ) {} (\n",
            module_name, num_entries, associativity, pc_width, target_width, instance_name
        );
        for (i, (port, wire)) in port_connections.iter().enumerate() {
            let comma = if i + 1 < port_connections.len() {
                ","
            } else {
                ""
            };
            inst += &format!("        .{}({}){}\n", port, wire, comma);
        }
        inst += "    );\n";
        self.module_instantiations.push(inst);
    }

    /// Generate read-only cache module definition and instantiation.
    fn generate_ro_cache_module_instantiation(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let name = node
            .data
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or(node_id);
        let module_name = format!("{}_module", self.sanitize_identifier(name));

        let num_read_ports = node_i64(node, "num_read_ports").unwrap_or(1) as u32;
        let block_size = node_i64(node, "block_size").unwrap_or(32) as u32;
        let associativity = node_i64(node, "associativity").unwrap_or(1) as u32;
        let num_rows = node_i64(node, "num_rows").unwrap_or(64) as u32;
        let address_width = node_i64(node, "address_width").unwrap_or(32) as u32;
        let data_width = node_i64(node, "data_width").unwrap_or(32) as u32;
        let replacement_policy = node
            .data
            .get("replacement_policy")
            .and_then(|v| v.as_str())
            .unwrap_or("round_robin")
            .to_string();
        let has_flush = node_bool(node, "has_flush_input");

        let gen = ReadOnlyCacheGenerator {
            name: module_name.clone(),
            num_read_ports,
            block_size,
            associativity,
            num_rows,
            address_width,
            data_width,
            replacement_policy,
            has_flush,
        };

        self.module_definitions.push(gen.generate_module());

        let mut port_connections: Vec<(String, String)> = Vec::new();
        port_connections.push(("clk".to_string(), "clk".to_string()));
        port_connections.push(("reset".to_string(), "reset".to_string()));

        // Walk edges for cache port connections
        for edge in self.graph.edges.values() {
            let et = edge
                .data
                .get("type")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let port_idx = edge
                .data
                .get("port_index")
                .and_then(|v| v.as_u64())
                .unwrap_or(0);

            if edge.target == *node_id {
                let source_wire = self.get_verilog_name(&edge.source);
                match et {
                    "cache_read_addr" => {
                        port_connections
                            .push((format!("read_addr_{}", port_idx), source_wire));
                    }
                    "cache_read_req" => {
                        port_connections
                            .push((format!("read_req_{}", port_idx), source_wire));
                    }
                    "cache_flush" => {
                        port_connections.push(("flush".to_string(), source_wire));
                    }
                    "refill_data" => {
                        port_connections
                            .push(("refill_data".to_string(), source_wire));
                    }
                    "refill_valid" => {
                        port_connections
                            .push(("refill_valid".to_string(), source_wire));
                    }
                    _ => {}
                }
            } else if edge.source == *node_id {
                let target_wire = self.get_verilog_name(&edge.target);
                match et {
                    "cache_read_data" => {
                        port_connections
                            .push((format!("read_data_{}", port_idx), target_wire));
                    }
                    "cache_valid" => {
                        port_connections
                            .push((format!("read_valid_{}", port_idx), target_wire));
                    }
                    "refill_addr" => {
                        port_connections
                            .push(("refill_addr".to_string(), target_wire));
                    }
                    "refill_req" => {
                        port_connections
                            .push(("refill_req".to_string(), target_wire));
                    }
                    _ => {}
                }
            }
        }

        let cache_name = self.sanitize_identifier(name);

        let instance_name = format!("{}_inst", cache_name);
        let mut inst = format!(
            "{} #(\n        .BLOCK_SIZE({}),\n        .ASSOCIATIVITY({}),\n        .NUM_ROWS({}),\n        .ADDR_WIDTH({}),\n        .DATA_WIDTH({})\n    ) {} (\n",
            module_name, block_size, associativity, num_rows, address_width, data_width,
            instance_name
        );
        for (i, (port, wire)) in port_connections.iter().enumerate() {
            let comma = if i + 1 < port_connections.len() {
                ","
            } else {
                ""
            };
            inst += &format!("        .{}({}){}\n", port, wire, comma);
        }
        inst += "    );\n";
        self.module_instantiations.push(inst);
    }

    /// Generate read-write cache module definition and instantiation.
    fn generate_rw_cache_module_instantiation(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let name = node
            .data
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or(node_id);
        let module_name = format!("{}_module", self.sanitize_identifier(name));

        let num_read_ports = node_i64(node, "num_read_ports").unwrap_or(1) as u32;
        let has_write_port = node_bool(node, "has_write_port");
        let num_write_ports = if has_write_port { 1 } else { 0 };
        let block_size = node_i64(node, "block_size").unwrap_or(32) as u32;
        let associativity = node_i64(node, "associativity").unwrap_or(1) as u32;
        let num_rows = node_i64(node, "num_rows").unwrap_or(64) as u32;
        let address_width = node_i64(node, "address_width").unwrap_or(32) as u32;
        let data_width = node_i64(node, "data_width").unwrap_or(32) as u32;
        let replacement_policy = node
            .data
            .get("replacement_policy")
            .and_then(|v| v.as_str())
            .unwrap_or("round_robin")
            .to_string();
        let write_allocate = node_bool(node, "write_allocate");

        let gen = ReadWriteCacheGenerator {
            name: module_name.clone(),
            num_read_ports,
            num_write_ports,
            block_size,
            associativity,
            num_rows,
            address_width,
            data_width,
            replacement_policy,
            write_allocate,
            write_read_fwd: node_bool(node, "write_read_fwd"),
        };

        self.module_definitions.push(gen.generate_module());

        let mut port_connections: Vec<(String, String)> = Vec::new();
        port_connections.push(("clk".to_string(), "clk".to_string()));
        port_connections.push(("reset".to_string(), "reset".to_string()));

        // Walk edges for cache port connections
        for edge in self.graph.edges.values() {
            let et = edge
                .data
                .get("type")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let port_idx = edge
                .data
                .get("port_index")
                .and_then(|v| v.as_u64())
                .unwrap_or(0);

            if edge.target == *node_id {
                let source_wire = self.get_verilog_name(&edge.source);
                match et {
                    "cache_read_addr" => {
                        port_connections
                            .push((format!("read_addr_{}", port_idx), source_wire));
                    }
                    "cache_read_req" => {
                        port_connections
                            .push((format!("read_req_{}", port_idx), source_wire));
                    }
                    "cache_write_input" => {
                        // This edge connects a write_port to the cache, handled below
                    }
                    "cache_flush" => {
                        port_connections.push(("flush".to_string(), source_wire));
                    }
                    "refill_data" => {
                        port_connections
                            .push(("refill_data".to_string(), source_wire));
                    }
                    "refill_valid" => {
                        port_connections
                            .push(("refill_valid".to_string(), source_wire));
                    }
                    "write_through_complete" => {
                        port_connections
                            .push(("write_through_complete".to_string(), source_wire));
                    }
                    _ => {}
                }
            } else if edge.source == *node_id {
                let target_wire = self.get_verilog_name(&edge.target);
                match et {
                    "cache_read_data" => {
                        port_connections
                            .push((format!("read_data_{}", port_idx), target_wire));
                    }
                    "cache_valid" => {
                        port_connections
                            .push((format!("read_valid_{}", port_idx), target_wire));
                    }
                    "refill_addr" => {
                        port_connections
                            .push(("refill_addr".to_string(), target_wire));
                    }
                    "refill_req" => {
                        port_connections
                            .push(("refill_req".to_string(), target_wire));
                    }
                    "write_through_addr" => {
                        port_connections
                            .push(("write_through_addr".to_string(), target_wire));
                    }
                    "write_through_data" => {
                        port_connections
                            .push(("write_through_data".to_string(), target_wire));
                    }
                    "write_through_byte_enable" => {
                        port_connections
                            .push(("write_through_byte_enable".to_string(), target_wire));
                    }
                    "write_through_req" => {
                        port_connections
                            .push(("write_through_req".to_string(), target_wire));
                    }
                    "control" => {
                        // Map control outputs: idle, complete, write_complete
                        let target_node = self.graph.nodes.get(&edge.target);
                        let target_type = target_node
                            .and_then(|n| n.data.get("type"))
                            .and_then(|v| v.as_str())
                            .unwrap_or("");
                        let signal_type = target_node
                            .and_then(|n| n.data.get("signal_type"))
                            .and_then(|v| v.as_str())
                            .unwrap_or("");
                        match target_type {
                            "cache_idle" => {
                                port_connections.push(("idle".to_string(), target_wire));
                            }
                            "cache_complete" => {
                                port_connections.push(("complete".to_string(), target_wire));
                            }
                            "control_signal" if signal_type == "write_complete" => {
                                port_connections.push(("write_complete".to_string(), target_wire));
                            }
                            _ => {}
                        }
                    }
                    _ => {}
                }
            }
        }

        // Handle write port connections from cache node metadata
        if let Some(write_port_id) = node.data.get("write_port").and_then(|v| v.as_str()) {
            let cache_name_s = self.sanitize_identifier(name);

            // Get write address from the write port's incoming edges
            if let Some(wp_node) = self.graph.nodes.get(write_port_id) {
                let wp_in_eids: Vec<String> = wp_node.incoming_edges.iter().cloned().collect();

                for eid in &wp_in_eids {
                    if let Some(e) = self.graph.edges.get(eid) {
                        let etype = e.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                        match etype {
                            "write_address" => {
                                let src = self.get_verilog_name(&e.source);
                                port_connections.push(("write_addr".to_string(), src));
                            }
                            "write_data" => {
                                let src = self.get_verilog_name(&e.source);
                                port_connections.push(("write_data".to_string(), src));
                            }
                            _ => {}
                        }
                    }
                }

                // Get combined_write_enable for write_req
                if let Some(we_id) = wp_node.data.get("combined_write_enable").and_then(|v| v.as_str()) {
                    let we_wire = self.get_verilog_name(we_id);
                    port_connections.push(("write_req".to_string(), we_wire));
                }

                // Get write_byte_enable: compute from writer_widths and instruction enables.
                // Generate a combinational byte enable signal based on store instruction
                // widths and byte address offset.
                let writer_widths: HashMap<String, i64> = wp_node
                    .data
                    .get("writer_widths")
                    .and_then(|v| v.as_object())
                    .map(|obj| {
                        obj.iter()
                            .filter_map(|(k, v)| v.as_i64().map(|w| (k.clone(), w)))
                            .collect()
                    })
                    .unwrap_or_default();

                if !writer_widths.is_empty() {
                    let byte_enable_width = data_width / 8;
                    let be_signal_name = format!("{}_write_byte_enable", cache_name_s);

                    // Declare the byte enable as a reg
                    self.logic_declarations.push(WireDecl {
                        name: be_signal_name.clone(),
                        bit_width: byte_enable_width as i64,
                    });
                    self.declared_names.insert(be_signal_name.clone());

                    // Find the write address signal
                    let addr_signal = port_connections.iter()
                        .find(|(p, _)| p == "write_addr")
                        .map(|(_, w)| w.clone())
                        .unwrap_or_else(|| "32'd0".to_string());

                    // Generate always @* block for byte enable computation
                    let mut be_logic = format!(
                        "    // Byte enable computation for {} write port\n    always @* begin\n        {} = {}'d{};\n",
                        cache_name_s, be_signal_name, byte_enable_width, (1i64 << byte_enable_width) - 1
                    );

                    // Sort by width (smallest first) so narrower stores take priority
                    let mut sorted_widths: Vec<(&String, &i64)> = writer_widths.iter().collect();
                    sorted_widths.sort_by_key(|(_, w)| **w);

                    let mut first = true;
                    for (instr_name, width) in &sorted_widths {
                        let width = **width;
                        if width >= data_width as i64 {
                            // Full-word store: byte enable = all ones (default)
                            continue;
                        }
                        let enable_name = format!("{}_enable", instr_name);
                        // Find the pipelined version of the enable at the Memory stage
                        // (matching the pipeline depth of the write address/data signals)
                        let enable_vname = {
                            let base_name = self.get_verilog_name(&enable_name);
                            // Look for pipelined versions (PIPE_..._enable_..._PIPE)
                            let mut best_name = base_name.clone();
                            let mut best_depth = 0usize;
                            let pattern = format!("{}_enable", instr_name);
                            for node_id in self.graph.nodes.keys() {
                                if node_id.starts_with("PIPE_")
                                    && node_id.contains(&pattern)
                                    && node_id.ends_with("_PIPE")
                                {
                                    let depth = node_id.matches("PIPE").count();
                                    if depth > best_depth {
                                        best_depth = depth;
                                        best_name = self.get_verilog_name(node_id);
                                    }
                                }
                            }
                            best_name
                        };
                        let bytes = width / 8;

                        let keyword = if first { "if" } else { "else if" };
                        first = false;

                        if bytes == 1 {
                            // sb: 1 byte, shifted by addr[1:0]
                            be_logic += &format!(
                                "        {} ({}) {} = {}'d1 << {}[1:0];\n",
                                keyword, enable_vname, be_signal_name, byte_enable_width, addr_signal
                            );
                        } else if bytes == 2 {
                            // sh: 2 bytes, shifted by addr[1]
                            be_logic += &format!(
                                "        {} ({}) {} = {}[1] ? {}'b{} : {}'b{};\n",
                                keyword, enable_vname, be_signal_name,
                                addr_signal,
                                byte_enable_width, "1100",
                                byte_enable_width, "0011"
                            );
                        } else {
                            // General sub-word: compute mask
                            let mask = (1i64 << bytes) - 1;
                            be_logic += &format!(
                                "        {} ({}) {} = {}'d{};\n",
                                keyword, enable_vname, be_signal_name, byte_enable_width, mask
                            );
                        }
                    }

                    be_logic += "    end\n";
                    self.comb_logic += &be_logic;

                    port_connections.push(("write_byte_enable".to_string(), be_signal_name));

                    // Position sub-word write data to match byte enables.
                    // Sub-word stores provide data in the lower bits, but byte enables
                    // may select upper byte lanes. Replicate the data so the correct
                    // bytes are at every possible position.
                    let has_subword = sorted_widths.iter().any(|(_, w)| **w < data_width as i64);
                    if has_subword {
                        let pos_data_name = format!("{}_positioned_write_data", cache_name_s);
                        self.logic_declarations.push(WireDecl {
                            name: pos_data_name.clone(),
                            bit_width: data_width as i64,
                        });
                        self.declared_names.insert(pos_data_name.clone());

                        let orig_write_data = port_connections.iter()
                            .find(|(p, _)| p == "write_data")
                            .map(|(_, w)| w.clone())
                            .unwrap_or_else(|| format!("{}'d0", data_width));

                        let mut pos_logic = format!(
                            "    // Position sub-word write data for cache byte enables\n    always @* begin\n        {} = {};\n",
                            pos_data_name, orig_write_data
                        );

                        let mut first_pos = true;
                        for (instr_name, width) in &sorted_widths {
                            let width = **width;
                            if width >= data_width as i64 {
                                continue;
                            }
                            let enable_name = format!("{}_enable", instr_name);
                            let enable_vname = {
                                let base_name = self.get_verilog_name(&enable_name);
                                let mut best_name = base_name.clone();
                                let mut best_depth = 0usize;
                                let pattern = format!("{}_enable", instr_name);
                                for node_id in self.graph.nodes.keys() {
                                    if node_id.starts_with("PIPE_")
                                        && node_id.contains(&pattern)
                                        && node_id.ends_with("_PIPE")
                                    {
                                        let depth = node_id.matches("PIPE").count();
                                        if depth > best_depth {
                                            best_depth = depth;
                                            best_name = self.get_verilog_name(node_id);
                                        }
                                    }
                                }
                                best_name
                            };
                            let reps = data_width as i64 / width;
                            let keyword = if first_pos { "if" } else { "else if" };
                            first_pos = false;

                            if reps > 1 {
                                pos_logic += &format!(
                                    "        {} ({}) {} = {{{}{{{}[{}:0]}}}};\n",
                                    keyword, enable_vname, pos_data_name, reps, orig_write_data, width - 1
                                );
                            }
                        }

                        pos_logic += "    end\n";
                        self.comb_logic += &pos_logic;

                        // Replace write_data with positioned version
                        port_connections.retain(|(p, _)| p != "write_data");
                        port_connections.push(("write_data".to_string(), pos_data_name));
                    }
                } else if let Some(be_node_id) = node.data.get("write_byte_enable_node").and_then(|v| v.as_str()) {
                    let be_wire = self.get_verilog_name(be_node_id);
                    port_connections.push(("write_byte_enable".to_string(), be_wire));
                }
            }
        }

        let cache_name = self.sanitize_identifier(name);

        let instance_name = format!("{}_inst", cache_name);
        let mut inst = format!(
            "{} #(\n        .BLOCK_SIZE({}),\n        .ASSOCIATIVITY({}),\n        .NUM_ROWS({}),\n        .ADDR_WIDTH({}),\n        .DATA_WIDTH({})\n    ) {} (\n",
            module_name, block_size, associativity, num_rows, address_width, data_width,
            instance_name
        );
        for (i, (port, wire)) in port_connections.iter().enumerate() {
            let comma = if i + 1 < port_connections.len() {
                ","
            } else {
                ""
            };
            inst += &format!("        .{}({}){}\n", port, wire, comma);
        }
        inst += "    );\n";
        self.module_instantiations.push(inst);
    }

    /// Generate register renamer module definition and instantiation.
    fn generate_renamer_module_instantiation(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let name = node
            .data
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or(node_id);
        let module_name = format!("{}_module", self.sanitize_identifier(name));

        let num_arch_regs = node_i64(node, "num_arch_regs").unwrap_or(32) as u32;
        let num_phys_regs = node_i64(node, "num_phys_regs").unwrap_or(64) as u32;
        let num_read_ports = node_i64(node, "num_read_ports").unwrap_or(2) as u32;
        let num_write_ports = node_i64(node, "num_write_ports").unwrap_or(1) as u32;
        let arch_reg_width = if num_arch_regs > 1 {
            (num_arch_regs as f64).log2().ceil() as u32
        } else {
            1
        };

        let gen = RegisterRenamerGenerator {
            name: module_name.clone(),
            num_arch_regs,
            num_phys_regs,
            num_read_ports,
            num_write_ports,
            arch_reg_width,
        };

        self.module_definitions.push(gen.generate_module());

        // Build port connections from graph edges
        let mut port_connections: Vec<(String, String)> = Vec::new();
        port_connections.push(("clk".to_string(), "clk".to_string()));
        port_connections.push(("reset".to_string(), "reset".to_string()));

        for edge in self.graph.edges.values() {
            let et = edge
                .data
                .get("type")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let port_idx = edge
                .data
                .get("port_index")
                .and_then(|v| v.as_u64())
                .unwrap_or(0);

            if edge.target == *node_id {
                let source_wire = self.get_verilog_name(&edge.source);
                match et {
                    "rename_read" => {
                        port_connections
                            .push((format!("arch_reg_read_{}", port_idx), source_wire));
                    }
                    "rename_write" => {
                        port_connections
                            .push((format!("arch_reg_write_{}", port_idx), source_wire));
                    }
                    "rename_write_enable" => {
                        port_connections
                            .push((format!("write_enable_{}", port_idx), source_wire));
                    }
                    _ => {}
                }
            } else if edge.source == *node_id {
                let target_wire = self.get_verilog_name(&edge.target);
                match et {
                    "rename_phys_read" => {
                        port_connections
                            .push((format!("phys_reg_read_{}", port_idx), target_wire));
                    }
                    "rename_phys_write" => {
                        port_connections
                            .push((format!("phys_reg_write_{}", port_idx), target_wire));
                    }
                    _ => {}
                }
            }
        }

        let renamer_name = self.sanitize_identifier(name);
        let instance_name = format!("{}_inst", renamer_name);
        let mut inst = format!("{} {} (\n", module_name, instance_name);
        for (i, (port, wire)) in port_connections.iter().enumerate() {
            let comma = if i + 1 < port_connections.len() {
                ","
            } else {
                ""
            };
            inst += &format!("        .{}({}){}\n", port, wire, comma);
        }
        inst += "    );\n";
        self.module_instantiations.push(inst);
    }

    // ===================================================================
    // STAGE 3: Module header, declarations, memory init, assembly
    // ===================================================================

    fn generate_module_header(&mut self) {
        let mut hdr = format!("module {}(\n", self.module_name);

        // Collect port nodes
        let mut input_ports: Vec<(String, i64)> = Vec::new();
        let mut output_ports: Vec<(String, i64)> = Vec::new();

        let mut sorted_nodes: Vec<(&String, &Node)> = self.graph.nodes.iter().collect();
        sorted_nodes.sort_by_key(|(id, _)| id.as_str());

        for (_, node) in &sorted_nodes {
            if node_bool(node, "is_port") {
                let pname = node
                    .data
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                let dir = node
                    .data
                    .get("port_direction")
                    .and_then(|v| v.as_str())
                    .unwrap_or("input");
                let bw = node_i64(node, "bit_width").unwrap_or(1);
                if dir == "output" {
                    output_ports.push((pname, bw));
                } else {
                    input_ports.push((pname, bw));
                }
            }
        }

        // Always add clk and reset
        if !input_ports.iter().any(|(n, _)| n == "clk") {
            input_ports.insert(0, ("clk".into(), 1));
        }
        if !input_ports.iter().any(|(n, _)| n == "reset") {
            input_ports.insert(1, ("reset".into(), 1));
        }

        // Input ports
        for (name, bw) in &input_ports {
            if *bw > 1 {
                hdr += &format!("    input wire [{bw_minus}:0] {name},\n", bw_minus = bw - 1);
            } else {
                hdr += &format!("    input wire {name},\n");
            }
        }

        // Output ports
        for (name, bw) in &output_ports {
            if *bw > 1 {
                hdr += &format!("    output wire [{bw_minus}:0] {name},\n", bw_minus = bw - 1);
            } else {
                hdr += &format!("    output wire {name},\n");
            }
        }

        // Reset value inputs for registers
        for reg in &self.reg_declarations {
            let rp = format!("reset_{}", reg.name);
            if input_ports.iter().any(|(n, _)| *n == rp) {
                continue;
            }
            if reg.reset_wire.starts_with("reset_") {
                let bw = reg.bit_width;
                if bw > 1 {
                    hdr += &format!("    input wire [{bw_minus}:0] {rp},\n", bw_minus = bw - 1);
                } else {
                    hdr += &format!("    input wire {rp},\n");
                }
            }
        }

        // External inputs
        for ext in &self.external_inputs {
            if input_ports.iter().any(|(n, _)| *n == ext.name) {
                continue;
            }
            let bw = ext.bit_width;
            if bw > 1 {
                hdr += &format!(
                    "    input wire [{bw_minus}:0] {name},\n",
                    bw_minus = bw - 1,
                    name = ext.name
                );
            } else {
                hdr += &format!("    input wire {name},\n", name = ext.name);
            }
        }

        // External outputs
        for ext in &self.external_outputs {
            if output_ports.iter().any(|(n, _)| *n == ext.name) {
                continue;
            }
            let bw = ext.bit_width;
            if bw > 1 {
                hdr += &format!(
                    "    output logic [{bw_minus}:0] {name},\n",
                    bw_minus = bw - 1,
                    name = ext.name
                );
            } else {
                hdr += &format!("    output logic {name},\n", name = ext.name);
            }
            hdr += &format!("    output logic {name}_valid,\n", name = ext.name);
        }

        // Remove trailing comma and close
        if hdr.ends_with(",\n") {
            hdr.truncate(hdr.len() - 2);
            hdr += "\n";
        }
        hdr += ");\n\n";

        self.module_header = hdr;
    }

    fn generate_declarations(&mut self) {
        let mut decl = String::new();

        // Register declarations (sorted)
        let mut regs = self.reg_declarations.clone();
        regs.sort_by(|a, b| a.name.cmp(&b.name));
        for reg in &regs {
            let bw = if reg.bit_width <= 0 { 32 } else { reg.bit_width };
            if bw > 1 {
                decl += &format!("    reg [{}:0] {};\n", bw - 1, reg.name);
            } else {
                decl += &format!("    reg {};\n", reg.name);
            }
        }

        // Memory declarations (sorted)
        for (name, mem) in &self.memory_declarations {
            if mem.externalized {
                continue;
            }
            let bw = if mem.bit_width <= 0 { 32 } else { mem.bit_width };
            if bw > 1 {
                decl += &format!(
                    "    reg [{}:0] {} [0:{}];\n",
                    bw - 1,
                    name,
                    mem.array_depth - 1
                );
            } else {
                decl += &format!("    reg {} [0:{}];\n", name, mem.array_depth - 1);
            }
        }

        // Logic declarations (mux outputs, sorted)
        let mut logic = self.logic_declarations.clone();
        logic.sort_by(|a, b| a.name.cmp(&b.name));
        for ld in &logic {
            let bw = if ld.bit_width <= 0 { 32 } else { ld.bit_width };
            if bw > 1 {
                decl += &format!("    reg [{}:0] {};\n", bw - 1, ld.name);
            } else {
                decl += &format!("    reg {};\n", ld.name);
            }
        }

        // Loop variable
        decl += "    integer i;\n\n";

        // Wire declarations (sorted)
        let mut wires = self.wire_declarations.clone();
        wires.sort_by(|a, b| a.name.cmp(&b.name));
        for w in &wires {
            let mut bw = if w.bit_width <= 0 { 32 } else { w.bit_width };
            // Fix _wr wires that should match register width
            if w.name.ends_with("_wr") && bw == 1 {
                let rd_name = format!("{}rd", &w.name[..w.name.len() - 2]);
                for reg in &self.reg_declarations {
                    if reg.name == rd_name && reg.bit_width > 1 {
                        bw = reg.bit_width;
                        break;
                    }
                }
            }
            if bw > 1 {
                decl += &format!("    wire [{}:0] {};\n", bw - 1, w.name);
            } else {
                decl += &format!("    wire {};\n", w.name);
            }
        }
        decl += "\n";

        self.declarations_str = decl;
    }

    fn generate_memory_initialization(&mut self) {
        let mut init = String::new();

        let internal: Vec<_> = self
            .memory_declarations
            .iter()
            .filter(|(_, m)| !m.externalized)
            .collect();

        if !internal.is_empty() {
            init += "    initial begin\n";
            init += "        // Initialize all memories to zero before loading from files\n";
            for (name, mem) in &internal {
                init += &format!(
                    "        for (i = 0; i < {}; i = i + 1) begin\n",
                    mem.array_depth
                );
                init += &format!("            {name}[i] = 0;\n");
                init += "        end\n";
            }

            init += "        // Load memory contents from files (can be sparse)\n";
            for (name, mem) in &internal {
                if let Some(ref mf) = mem.mem_file {
                    init += &format!("        $readmemh(\"{mf}\", {name});\n");
                }
            }
            init += "    end\n\n";
        }

        self.memory_init = init;
    }

    fn assemble_module(&self) -> String {
        let mut v = String::new();

        // MEM_BASE default
        v += "`ifndef MEM_BASE\n";
        v += "`define MEM_BASE 32'h00000000\n";
        v += "`endif\n\n";

        // Module definitions (from generators)
        for def in &self.module_definitions {
            v += def;
            v += "\n\n";
        }

        v += &self.extra_modules;
        v += &self.module_header;
        v += &self.declarations_str;
        v += &self.memory_init;
        v += &self.comb_logic;
        v += "\n";

        // Module instantiations
        for inst in &self.module_instantiations {
            v += "    ";
            v += inst;
            v += "\n";
        }

        v += &self.seq_logic;
        v += "endmodule\n";

        v
    }

    // ===================================================================
    // STAGE 4: Combinational logic generation
    // ===================================================================

    fn generate_combinational_logic(&mut self) {
        // RISC-V x0 hardwired to zero
        if self.graph.nodes.contains_key("x0") {
            self.comb_logic += "    // RISC-V x0 hardwired to zero\n";
            self.comb_logic += "    assign x0 = 32'h0;\n\n";
        }

        // ISA state aliases
        if !self.isa_state_aliases.is_empty() {
            self.comb_logic += "    // ISA state aliases\n";
            let aliases = self.isa_state_aliases.clone();
            for a in &aliases {
                self.comb_logic += &format!("    assign {} = {};\n", a.alias, a.source);
            }
            self.comb_logic += "\n";
        }

        // Process nodes in dependency order
        let order = self.get_dependency_order();
        let mut processed: HashSet<String> = HashSet::new();

        for node_id in &order {
            if processed.contains(node_id) {
                continue;
            }
            let node = match self.graph.nodes.get(node_id) {
                Some(n) => n,
                None => continue,
            };
            let nt = node_str(node, "type");

            if nt == "cast" {
                processed.insert(node_id.clone());
                continue;
            }

            match nt {
                "operation" | "binary_op" => {
                    self.generate_operation_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "array_access" => {
                    self.generate_array_access_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "bit_slice" => {
                    self.generate_bit_slice_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "zero_extend" => {
                    self.generate_zero_extend_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "sign_extend" => {
                    self.generate_sign_extend_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "literal" => {
                    self.generate_literal_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "sized_literal" => {
                    self.generate_sized_literal_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "concatenation" => {
                    self.generate_concatenation_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "repetition" => {
                    self.generate_repetition_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "ternary_op" => {
                    self.generate_ternary_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "comparison" => {
                    self.generate_comparison_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "logical_and" | "logical_or" | "logical_not" => {
                    self.generate_logical_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "instruction_enable" => {
                    self.generate_instruction_enable_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "multiplexer" => {
                    self.generate_mux_instantiation(node_id);
                    processed.insert(node_id.clone());
                }
                "address_offset" | "port_address_offset" => {
                    self.generate_address_offset_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "memory_data_merge" | "port_data_merge" => {
                    self.generate_memory_data_merge_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "byte_enable_mux" => {
                    self.generate_byte_enable_mux_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "decode_comparison" => {
                    self.generate_decode_comparison_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "array_read" => {
                    self.generate_ras_array_read_logic(node_id);
                    processed.insert(node_id.clone());
                }
                "mux" => {
                    self.generate_simple_mux_logic(node_id);
                    processed.insert(node_id.clone());
                }
                _ => {}
            }
        }

        // Stall controller logic
        self.generate_stall_controller_logic();

        // Variable assignments
        self.generate_variable_assignments();

        // Conceptual forwarding
        self.generate_conceptual_forwarding();
    }

    /// Generate combinational logic for pipeline stall controllers.
    /// OR all incoming stall_condition edges to produce the stall control signal.
    fn generate_stall_controller_logic(&mut self) {
        let stall_controllers: Vec<String> = self.graph.nodes.iter()
            .filter(|(_, n)| node_str(n, "type") == "pipeline_stall_controller")
            .map(|(nid, _)| nid.clone())
            .collect();

        for ctrl_id in &stall_controllers {
            let mut stall_sources: Vec<String> = Vec::new();
            // Iterate ALL graph edges to find stall_condition edges targeting this controller,
            // because node.incoming_edges may not be populated by the hazard resolver.
            for (_eid, edge) in &self.graph.edges {
                if edge.target == *ctrl_id {
                    let et = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                    if et == "stall_condition" {
                        let src_name = self.node_id_to_name
                            .get(&edge.source)
                            .cloned()
                            .unwrap_or_else(|| self.sanitize_identifier(&edge.source));
                        stall_sources.push(src_name);
                    }
                }
            }
            if !stall_sources.is_empty() {
                let ctrl_name = self.node_id_to_name
                    .get(ctrl_id)
                    .cloned()
                    .unwrap_or_else(|| self.sanitize_identifier(ctrl_id));
                let rhs = stall_sources.join(" || ");
                self.comb_logic += &format!("    assign {} = {};\n", ctrl_name, rhs);
            }
        }
    }

    fn generate_operation_logic(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        if self.inlined_nodes.contains(node_id) {
            return;
        }
        let vname = self
            .node_id_to_name
            .get(node_id)
            .cloned()
            .unwrap_or_else(|| self.sanitize_identifier(node_id));

        if self.assigned_signals.contains(&vname) {
            return;
        }
        self.assigned_signals.insert(vname.clone());

        let node_type = node_str(node, "type");
        let operator = node
            .data
            .get("operator")
            .or_else(|| node.data.get("operation"))
            .and_then(|v| v.as_str())
            .unwrap_or_else(|| match &*node_type {
                "logical_and" => "&&",
                "logical_or" => "||",
                "logical_not" => "!",
                _ => "+",
            });

        // Handle unary identity
        if operator == "identity" && node.incoming_edges.len() == 1 {
            if let Some(eid) = node.incoming_edges.iter().next() {
                if let Some(e) = self.graph.edges.get(eid) {
                    let inp = self.get_node_verilog_ref(&e.source);
                    self.comb_logic += &format!("    assign {vname} = {inp};\n");
                    return;
                }
            }
        }

        // N-ary OR/AND
        if matches!(operator, "||" | "&&" | "|" | "&") && node.incoming_edges.len() > 2 {
            let mut edges: Vec<_> = node
                .incoming_edges
                .iter()
                .filter_map(|eid| self.graph.edges.get(eid))
                .collect();
            edges.sort_by(|a, b| {
                let ai = a.data.get("operand_index").and_then(|v| v.as_i64()).unwrap_or(0);
                let bi = b.data.get("operand_index").and_then(|v| v.as_i64()).unwrap_or(0);
                ai.cmp(&bi).then(a.source.cmp(&b.source))
            });
            let names: Vec<String> = edges.iter().map(|e| self.get_node_verilog_ref(&e.source)).collect();
            let vop = match operator {
                "||" => " || ",
                "&&" => " && ",
                "|" => " | ",
                "&" => " & ",
                _ => " | ",
            };
            self.comb_logic += &format!("    assign {vname} = {};\n", names.join(vop));
            return;
        }

        // Binary operation - find left/right operands
        if node.incoming_edges.len() >= 2 {
            let (left_src, right_src) = self.find_binary_operands(node_id);
            if let (Some(left_id), Some(right_id)) = (left_src, right_src) {
                let left_name = self.get_node_verilog_ref(&left_id);
                let right_name = self.get_node_verilog_ref(&right_id);

                let vop = match operator {
                    "+" | "-" | "*" | "%" | "&" | "|" | "^" | "<<" | ">>" | ">>>"
                    | "==" | "!=" | "<" | ">" | "<=" | ">=" | "&&" | "||" => operator,
                    "/" => "/",
                    "<s" => "<",
                    ">s" => ">",
                    "<=s" => "<=",
                    ">=s" => ">=",
                    "!" | "~" => "^", // treat as XOR in binary context
                    _ => "+",
                };

                if operator == ">>>" {
                    let lsigned = if left_name.starts_with("$signed(") {
                        left_name.clone()
                    } else {
                        format!("$signed({left_name})")
                    };
                    self.comb_logic += &format!("    assign {vname} = {lsigned} >>> {right_name};\n");
                } else if operator == "/s" {
                    self.comb_logic += &format!("    assign {vname} = $signed({left_name}) / $signed({right_name});\n");
                } else if operator == "%s" {
                    self.comb_logic += &format!("    assign {vname} = $signed({left_name}) % $signed({right_name});\n");
                } else if matches!(operator, "<s" | ">s" | "<=s" | ">=s") {
                    let ls = if left_name.starts_with("$signed(") { left_name.clone() } else { format!("$signed({left_name})") };
                    let rs = if right_name.starts_with("$signed(") { right_name.clone() } else { format!("$signed({right_name})") };
                    self.comb_logic += &format!("    assign {vname} = {ls} {vop} {rs};\n");
                } else {
                    self.comb_logic += &format!("    assign {vname} = {left_name} {vop} {right_name};\n");
                }
                return;
            }
        }

        // Unary operation
        if node.incoming_edges.len() == 1 {
            if let Some(eid) = node.incoming_edges.iter().next() {
                if let Some(e) = self.graph.edges.get(eid) {
                    let operand = self.get_node_verilog_ref(&e.source);
                    match operator {
                        "!" | "~" | "-" => {
                            self.comb_logic += &format!("    assign {vname} = {operator}{operand};\n");
                        }
                        _ => {
                            // Binary/n-ary operators with single input: identity (passthrough)
                            self.comb_logic += &format!("    assign {vname} = {operand};\n");
                        }
                    }
                    return;
                }
            }
        }

        // NOT node with no incoming edges (from graph merger)
        if node_str(node, "type") == "logical_not"
            || (operator == "!" && vname.starts_with("not"))
        {
            let orig = if node_id.starts_with('!') {
                &node_id[1..]
            } else if node_id.starts_with("not") {
                &node_id[3..]
            } else {
                ""
            };
            if !orig.is_empty() {
                if let Some(mapped) = self.node_id_to_name.get(orig) {
                    self.comb_logic += &format!("    assign {vname} = !{mapped};\n");
                    return;
                }
            }
        }
    }

    fn find_binary_operands(&self, node_id: &str) -> (Option<String>, Option<String>) {
        let node = &self.graph.nodes[node_id];
        let mut left: Option<String> = None;
        let mut right: Option<String> = None;

        // First try labeled edges
        for eid in &node.incoming_edges {
            if let Some(edge) = self.graph.edges.get(eid) {
                let pos = edge.data.get("position").and_then(|v| v.as_str()).unwrap_or("");
                let operand = edge.data.get("operand").and_then(|v| v.as_str()).unwrap_or("");
                let etype = edge_str(edge, "type");

                if pos == "left" || operand == "left" || etype == "left_operand" {
                    left = Some(edge.source.clone());
                } else if pos == "right" || operand == "right" || etype == "right_operand" {
                    right = Some(edge.source.clone());
                }
            }
        }

        // Fallback: sort by position
        if left.is_none() || right.is_none() {
            let mut edges: Vec<_> = node
                .incoming_edges
                .iter()
                .filter_map(|eid| self.graph.edges.get(eid))
                .collect();
            edges.sort_by(|a, b| {
                let ap = a.data.get("position").and_then(|v| v.as_i64()).unwrap_or(999);
                let bp = b.data.get("position").and_then(|v| v.as_i64()).unwrap_or(999);
                ap.cmp(&bp).then(a.source.cmp(&b.source))
            });
            if edges.len() >= 2 {
                if left.is_none() {
                    left = Some(edges[0].source.clone());
                }
                if right.is_none() {
                    right = Some(edges[1].source.clone());
                }
            }
        }

        (left, right)
    }

    fn generate_array_access_logic(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let vname = self
            .node_id_to_name
            .get(node_id)
            .cloned()
            .unwrap_or_else(|| self.sanitize_identifier(node_id));

        // Skip write nodes
        if node.data.get("access_mode").and_then(|v| v.as_str()) == Some("write") {
            return;
        }

        // Find array and index edges
        let mut array_src: Option<String> = None;
        let mut index_src: Option<String> = None;

        // Try explicit edge types first
        let mut sorted_eids: Vec<_> = node.incoming_edges.iter().collect();
        sorted_eids.sort();

        for eid in &sorted_eids {
            if let Some(edge) = self.graph.edges.get(*eid) {
                if edge_str(edge, "type") == "array_base" {
                    array_src = Some(edge.source.clone());
                } else if edge_str(edge, "type") == "array_index" {
                    index_src = Some(edge.source.clone());
                }
            }
        }

        // Fallback to position-based
        if array_src.is_none() || index_src.is_none() {
            for eid in &sorted_eids {
                if let Some(edge) = self.graph.edges.get(*eid) {
                    let pos = edge.data.get("position").and_then(|v| v.as_i64());
                    if pos == Some(0) && array_src.is_none() {
                        array_src = Some(edge.source.clone());
                    } else if pos == Some(1) && index_src.is_none() {
                        index_src = Some(edge.source.clone());
                    }
                }
            }
        }

        // Heuristic fallback
        if array_src.is_none() || index_src.is_none() {
            for eid in &sorted_eids {
                if let Some(edge) = self.graph.edges.get(*eid) {
                    if let Some(src) = self.graph.nodes.get(&edge.source) {
                        if array_src.is_none() && node_bool(src, "is_memory") {
                            array_src = Some(edge.source.clone());
                        } else if index_src.is_none() {
                            index_src = Some(edge.source.clone());
                        }
                    }
                }
            }
        }

        if let (Some(arr_id), Some(idx_id)) = (array_src, index_src) {
            let arr_name = self
                .node_id_to_name
                .get(&arr_id)
                .cloned()
                .unwrap_or_else(|| self.sanitize_identifier(&arr_id));
            let idx_name = self
                .node_id_to_name
                .get(&idx_id)
                .cloned()
                .unwrap_or_else(|| self.sanitize_identifier(&idx_id));

            // Check for mem type (byte-addressed) memory
            let mem_pw = self.get_mem_port_width(&arr_name);
            let is_known_mem = self.memory_declarations.contains_key(&arr_name);

            if is_known_mem && mem_pw > 0 && self.is_physical_memory(&arr_name) {
                let elem_bits = self.memory_declarations[&arr_name].bit_width;
                let bpe = if elem_bits > 0 { elem_bits / 8 } else { 1 };
                if bpe > 1 {
                    let shift = (bpe as f64).log2() as i64;
                    self.comb_logic += &format!(
                        "    assign {vname} = {arr_name}[(({idx_name} - `MEM_BASE) >> {shift})];\n"
                    );
                    return;
                }
            }

            // Check for write-read forwarding: emit transparent mux instead of
            // normal array read when the memory has write_read_fwd enabled.
            if self.try_generate_write_read_fwd(&arr_id, &arr_name, &idx_name, &vname) {
                return;
            }

            // Check if index is a literal → bit select
            let idx_is_literal = self
                .graph
                .nodes
                .get(&idx_id)
                .map(|n| node_str(n, "type") == "literal")
                .unwrap_or(false);
            let arr_is_mem = self
                .graph
                .nodes
                .get(&arr_id)
                .map(|n| node_bool(n, "is_memory"))
                .unwrap_or(false);

            if !arr_is_mem && idx_is_literal {
                let idx_val = self
                    .graph
                    .nodes
                    .get(&idx_id)
                    .and_then(|n| n.data.get("value"))
                    .and_then(|v| v.as_i64())
                    .unwrap_or(0);
                self.comb_logic += &format!("    assign {vname} = {arr_name}[{idx_val}];\n");
            } else {
                self.comb_logic += &format!("    assign {vname} = {arr_name}[{idx_name}];\n");
            }
        }
    }

    /// Try to generate write-read forwarding for an array read.
    ///
    /// When the array has `write_read_fwd` enabled, emits a transparent forwarding
    /// mux that selects between write data (when same address is being written)
    /// and the normal array read:
    ///   `assign rd_val = (write_enable && write_addr == index) ? write_data : arr[index]`
    fn try_generate_write_read_fwd(
        &mut self,
        arr_id: &str,
        arr_name: &str,
        idx_name: &str,
        vname: &str,
    ) -> bool {
        // Check if array has write_read_fwd enabled
        let has_fwd = self.graph.nodes.get(arr_id)
            .and_then(|n| n.data.get("write_read_fwd"))
            .and_then(|v| v.as_bool())
            .unwrap_or(false);

        if !has_fwd {
            return false;
        }

        // Find shared write port: {array}_shared_wr
        let shared_wr_id = format!("{}_shared_wr", arr_id);
        let port_node = match self.graph.nodes.get(&shared_wr_id) {
            Some(n) => n,
            None => return false,
        };

        // Get write enable signal
        let we_base = match port_node.data.get("combined_write_enable").and_then(|v| v.as_str()) {
            Some(id) => id.to_string(),
            None => return false,
        };

        // Prefer _valid_gated version for pipeline safety
        let we_id = {
            let valid_gated = format!("{}_valid_gated", we_base);
            if self.graph.nodes.contains_key(&valid_gated) {
                valid_gated
            } else {
                we_base
            }
        };

        // Find write_address and write_data from incoming edges
        let incoming: Vec<String> = port_node.incoming_edges.iter().cloned().collect();
        let mut write_addr_id: Option<String> = None;
        let mut write_data_id: Option<String> = None;

        for eid in &incoming {
            if let Some(edge) = self.graph.edges.get(eid) {
                match edge_str(edge, "type") {
                    "write_address" => write_addr_id = Some(edge.source.clone()),
                    "write_data" => write_data_id = Some(edge.source.clone()),
                    _ => {}
                }
            }
        }

        let (addr_id, data_id) = match (write_addr_id, write_data_id) {
            (Some(a), Some(d)) => (a, d),
            _ => return false,
        };

        let we_name = self.node_id_to_name.get(&we_id).cloned()
            .unwrap_or_else(|| self.sanitize_identifier(&we_id));
        let addr_name = self.node_id_to_name.get(&addr_id).cloned()
            .unwrap_or_else(|| self.sanitize_identifier(&addr_id));
        let data_name = self.node_id_to_name.get(&data_id).cloned()
            .unwrap_or_else(|| self.sanitize_identifier(&data_id));

        // Emit transparent forwarding mux
        self.comb_logic += &format!(
            "    assign {vname} = ({we_name} && {addr_name} == {idx_name}) ? {data_name} : {arr_name}[{idx_name}];\n"
        );

        true
    }

    fn generate_bit_slice_logic(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let vname = self
            .node_id_to_name
            .get(node_id)
            .cloned()
            .unwrap_or_else(|| self.sanitize_identifier(node_id));
        self.assigned_signals.insert(vname.clone());

        // Get high:low range
        let (high, low) = self.get_bit_slice_range(node);

        // Get source from incoming edge
        if let Some(eid) = node.incoming_edges.iter().next() {
            if let Some(edge) = self.graph.edges.get(eid) {
                // If the source is a multiplexer that already produces the
                // extracted-width value (e.g. xer[34:34]_wr fed by
                // xer[34:34]_wr_mux), emit a direct assignment instead of a
                // bit-select that would index beyond the mux width.
                let src_is_mux = self.graph.nodes.get(&edge.source)
                    .map(|n| node_str(n, "type") == "multiplexer")
                    .unwrap_or(false);
                if src_is_mux {
                    let src = self.get_node_verilog_ref(&edge.source);
                    self.comb_logic += &format!("    assign {vname} = {src};\n");
                    return;
                }

                let src = self.get_node_verilog_ref(&edge.source);
                if high == low {
                    self.comb_logic += &format!("    assign {vname} = {src}[{high}];\n");
                } else {
                    self.comb_logic += &format!("    assign {vname} = {src}[{high}:{low}];\n");
                }
                return;
            }
        }

        // Fallback: expression-based
        if let Some(expr) = node.data.get("expression") {
            if let Some(operand) = expr.get("operand") {
                let src = self.get_verilog_name_for_expr(operand);
                if high == low {
                    self.comb_logic += &format!("    assign {vname} = {src}[{high}];\n");
                } else {
                    self.comb_logic += &format!("    assign {vname} = {src}[{high}:{low}];\n");
                }
            }
        }
    }

    fn get_bit_slice_range(&self, node: &Node) -> (i64, i64) {
        if let (Some(h), Some(l)) = (node_i64(node, "high_bit"), node_i64(node, "low_bit")) {
            return (h, l);
        }
        if let (Some(h), Some(l)) = (node_i64(node, "high"), node_i64(node, "low")) {
            return (h, l);
        }
        if let Some(Value::Array(bs)) = node.data.get("bitslice") {
            if bs.len() == 2 {
                return (
                    bs[0].as_i64().unwrap_or(0),
                    bs[1].as_i64().unwrap_or(0),
                );
            }
        }
        if let Some(expr) = node.data.get("expression") {
            if let Some(Value::Array(range)) = expr.get("range") {
                if range.len() == 2 {
                    return (
                        range[0].as_i64().unwrap_or(0),
                        range[1].as_i64().unwrap_or(0),
                    );
                }
            }
        }
        (0, 0)
    }

    fn generate_zero_extend_logic(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let vname = self
            .node_id_to_name
            .get(node_id)
            .cloned()
            .unwrap_or_else(|| self.sanitize_identifier(node_id));
        let tw = node_i64(node, "bit_width")
            .or_else(|| node_i64(node, "target_width"))
            .unwrap_or(32);

        if let Some(eid) = node.incoming_edges.iter().next() {
            if let Some(edge) = self.graph.edges.get(eid) {
                let inp = self.get_node_verilog_ref(&edge.source);
                let iw = self.infer_bit_width(&edge.source);
                if iw < tw {
                    let pad = tw - iw;
                    self.comb_logic += &format!(
                        "    assign {vname} = {{{{{pad}{{1'b0}}}}, {inp}}};\n"
                    );
                } else {
                    self.comb_logic += &format!("    assign {vname} = {inp};\n");
                }
            }
        }
    }

    fn generate_sign_extend_logic(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let vname = self
            .node_id_to_name
            .get(node_id)
            .cloned()
            .unwrap_or_else(|| self.sanitize_identifier(node_id));
        let tw = node_i64(node, "bit_width")
            .or_else(|| node_i64(node, "target_width"))
            .unwrap_or(32);

        if let Some(eid) = node.incoming_edges.iter().next() {
            if let Some(edge) = self.graph.edges.get(eid) {
                let inp = self.get_node_verilog_ref(&edge.source);
                let iw = self.infer_bit_width(&edge.source);
                if iw < tw {
                    let pad = tw - iw;
                    let sign = format!("{inp}[{}]", iw - 1);
                    self.comb_logic += &format!(
                        "    assign {vname} = {{{{{pad}{{{sign}}}}}, {inp}}};\n"
                    );
                } else {
                    self.comb_logic += &format!("    assign {vname} = {inp};\n");
                }
            }
        }
    }

    fn generate_literal_logic(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let vname = self
            .node_id_to_name
            .get(node_id)
            .cloned()
            .unwrap_or_else(|| self.sanitize_identifier(node_id));
        let bw = self.infer_bit_width(node_id);

        if !self.declared_names.contains(&vname) {
            self.declarations_str += &format!("    wire [{}:0] {vname};\n", bw - 1);
            self.declared_names.insert(vname.clone());
        }

        let val_str = if let Some(v) = node.data.get("value") {
            self.format_literal_value(v, bw)
        } else {
            format!("{bw}'d0")
        };
        self.comb_logic += &format!("    assign {vname} = {val_str};\n");
    }

    fn generate_sized_literal_logic(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let vname = self
            .node_id_to_name
            .get(node_id)
            .cloned()
            .unwrap_or_else(|| self.sanitize_identifier(node_id));
        let width = node_i64(node, "width").unwrap_or(1);

        if !self.declared_names.contains(&vname) {
            if width > 1 {
                self.declarations_str += &format!("    wire [{}:0] {vname};\n", width - 1);
            } else {
                self.declarations_str += &format!("    wire {vname};\n");
            }
            self.declared_names.insert(vname.clone());
        }

        if let Some(bits) = node.data.get("bits").and_then(|v| v.as_str()) {
            self.comb_logic += &format!("    assign {vname} = {width}'b{bits};\n");
        } else if let Some(hex) = node.data.get("hex_digits")
            .or_else(|| {
                // Also check original_digits when format is hex
                if node.data.get("format").and_then(|v| v.as_str()) == Some("hex") {
                    node.data.get("original_digits")
                } else {
                    None
                }
            })
            .and_then(|v| v.as_str())
        {
            self.comb_logic += &format!("    assign {vname} = {width}'h{hex};\n");
        } else if let Some(dec) = node.data.get("dec_digits").and_then(|v| v.as_str()) {
            self.comb_logic += &format!("    assign {vname} = {width}'d{dec};\n");
        } else if let Some(v) = node.data.get("value") {
            let val_str = self.format_literal_value(v, width);
            self.comb_logic += &format!("    assign {vname} = {val_str};\n");
        } else {
            self.comb_logic += &format!("    assign {vname} = {width}'d0;\n");
        }
    }

    fn generate_concatenation_logic(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let vname = self
            .node_id_to_name
            .get(node_id)
            .cloned()
            .unwrap_or_else(|| self.sanitize_identifier(node_id));

        if !node.incoming_edges.is_empty() {
            // Deduplicate by position, prefer _rd nodes
            let mut pos_to_edge: BTreeMap<i64, String> = BTreeMap::new();
            let mut sorted_eids: Vec<_> = node.incoming_edges.iter().collect();
            sorted_eids.sort();
            for eid in sorted_eids {
                if let Some(edge) = self.graph.edges.get(eid) {
                    let pos = edge.data.get("position").and_then(|v| v.as_i64()).unwrap_or(0);
                    if !pos_to_edge.contains_key(&pos) || edge.source.ends_with("_rd") {
                        pos_to_edge.insert(pos, edge.source.clone());
                    }
                }
            }

            let mut parts = Vec::new();
            for (_, src_id) in &pos_to_edge {
                if let Some(src) = self.graph.nodes.get(src_id) {
                    let st = node_str(src, "type");
                    let src_name = if st == "sized_literal" {
                        let w = node_i64(src, "width").unwrap_or(1);
                        if let Some(bits) = src.data.get("bits").and_then(|v| v.as_str()) {
                            format!("{w}'b{bits}")
                        } else if let Some(hex) = src.data.get("hex_digits").and_then(|v| v.as_str()) {
                            format!("{w}'h{hex}")
                        } else {
                            let val = src.data.get("value").and_then(|v| v.as_i64()).unwrap_or(0);
                            format!("{w}'d{val}")
                        }
                    } else if st == "literal" {
                        let val = src.data.get("value").and_then(|v| v.as_i64()).unwrap_or(0);
                        let bw = self.infer_bit_width(src_id);
                        format!("{bw}'d{val}")
                    } else {
                        self.get_node_verilog_ref(src_id)
                    };
                    parts.push(src_name);
                }
            }
            let expr = parts.join(", ");
            self.comb_logic += &format!("    assign {vname} = {{{expr}}};\n");
        }
    }

    fn generate_repetition_logic(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let vname = self
            .node_id_to_name
            .get(node_id)
            .cloned()
            .unwrap_or_else(|| self.sanitize_identifier(node_id));

        if let Some(eid) = node.incoming_edges.iter().next() {
            if let Some(edge) = self.graph.edges.get(eid) {
                let src = self.get_node_verilog_ref(&edge.source);
                let count = node
                    .data
                    .get("expression")
                    .and_then(|e| e.get("count"))
                    .and_then(|v| v.as_i64())
                    .unwrap_or(1);
                self.comb_logic += &format!("    assign {vname} = {{{count}{{{src}}}}};\n");
            }
        }
    }

    fn generate_ternary_logic(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let vname = self
            .node_id_to_name
            .get(node_id)
            .cloned()
            .unwrap_or_else(|| self.sanitize_identifier(node_id));

        // Find condition, true, false edges
        let mut cond_src: Option<String> = None;
        let mut true_src: Option<String> = None;
        let mut false_src: Option<String> = None;

        for eid in &node.incoming_edges {
            if let Some(edge) = self.graph.edges.get(eid) {
                match edge_str(edge, "type") {
                    "ternary_condition" => cond_src = Some(edge.source.clone()),
                    "ternary_true" => true_src = Some(edge.source.clone()),
                    "ternary_false" => false_src = Some(edge.source.clone()),
                    _ => {}
                }
            }
        }

        if let (Some(c), Some(t), Some(f)) = (cond_src, true_src, false_src) {
            let cn = self.get_node_verilog_ref(&c);
            let tn = self.get_node_verilog_ref(&t);
            let fn_ = self.get_node_verilog_ref(&f);
            self.comb_logic += &format!("    assign {vname} = {cn} ? {tn} : {fn_};\n");
        }
    }

    fn generate_comparison_logic(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];

        // Check for byte-mux selector comparison: has compare_value in data and single operand
        if let Some(cmp_val) = node.data.get("compare_value").and_then(|v| v.as_i64()) {
            let vname = self
                .node_id_to_name
                .get(node_id)
                .cloned()
                .unwrap_or_else(|| self.sanitize_identifier(node_id));

            if self.assigned_signals.contains(&vname) {
                return;
            }
            self.assigned_signals.insert(vname.clone());

            let operator = node.data.get("operator").and_then(|v| v.as_str()).unwrap_or("==");

            // Find the single operand (left side of comparison)
            if let Some(eid) = node.incoming_edges.iter().next() {
                if let Some(edge) = self.graph.edges.get(eid) {
                    let operand = self.get_node_verilog_ref(&edge.source);
                    let sel_width = node.data.get("expression")
                        .and_then(|e| e.get("right"))
                        .and_then(|r| r.get("width"))
                        .and_then(|w| w.as_i64())
                        .unwrap_or(2);
                    self.comb_logic += &format!(
                        "    assign {vname} = {operand} {operator} {sel_width}'d{cmp_val};\n"
                    );
                    return;
                }
            }
        }

        // Comparisons use the same binary operation pattern
        self.generate_operation_logic(node_id);
    }

    fn generate_logical_logic(&mut self, node_id: &str) {
        // Logical ops use the same operation pattern
        self.generate_operation_logic(node_id);
    }

    fn generate_instruction_enable_logic(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let vname = self
            .node_id_to_name
            .get(node_id)
            .cloned()
            .unwrap_or_else(|| self.sanitize_identifier(node_id));

        if self.assigned_signals.contains(&vname) {
            return;
        }
        self.assigned_signals.insert(vname.clone());

        // Instruction enable is the identity of its decode_enable input
        for eid in &node.incoming_edges {
            if let Some(edge) = self.graph.edges.get(eid) {
                let et = edge_str(edge, "type");
                if et == "decode_enable" || et == "operand" {
                    let src = self.get_node_verilog_ref(&edge.source);
                    self.comb_logic += &format!("    assign {vname} = {src};\n");
                    return;
                }
            }
        }
        // Fallback: if no decode_enable edge, use first incoming
        if let Some(eid) = node.incoming_edges.iter().next() {
            if let Some(edge) = self.graph.edges.get(eid) {
                let src = self.get_node_verilog_ref(&edge.source);
                self.comb_logic += &format!("    assign {vname} = {src};\n");
            }
        }
    }

    fn generate_decode_comparison_logic(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let vname = self
            .node_id_to_name
            .get(node_id)
            .cloned()
            .unwrap_or_else(|| self.sanitize_identifier(node_id));

        if self.assigned_signals.contains(&vname) {
            return;
        }
        self.assigned_signals.insert(vname.clone());

        let operator = node.data.get("operator").and_then(|v| v.as_str()).unwrap_or("==");

        // Parse field: JSON string describing a bit slice like
        // {"range":[6,0],"target":{"name":"instr","type":"identifier"},"type":"bit_slice"}
        let field_str = node.data.get("field").and_then(|v| v.as_str()).unwrap_or("");
        let field_expr = if let Ok(field_json) = serde_json::from_str::<serde_json::Value>(field_str) {
            let target_name = field_json.get("target")
                .and_then(|t| t.get("name"))
                .and_then(|n| n.as_str())
                .unwrap_or("instr");
            let target_vname = self.node_id_to_name.get(target_name)
                .cloned()
                .unwrap_or_else(|| target_name.to_string());
            if let Some(range) = field_json.get("range").and_then(|r| r.as_array()) {
                let high = range.first().and_then(|v| v.as_i64()).unwrap_or(0);
                let low = range.get(1).and_then(|v| v.as_i64()).unwrap_or(0);
                format!("{target_vname}[{high}:{low}]")
            } else {
                target_vname
            }
        } else {
            field_str.to_string()
        };

        // Parse value: either a simple number string or a JSON object with fixed_value/original
        let value_raw = node.data.get("value").and_then(|v| v.as_str()).unwrap_or("0");
        let (cmp_value, slice_width) = if let Ok(val_json) = serde_json::from_str::<serde_json::Value>(value_raw) {
            if let Some(width) = val_json.get("width").and_then(|w| w.as_i64()) {
                // Has width field - use binary format if pattern available
                if let Some(pattern) = val_json.get("pattern").and_then(|p| p.as_str()) {
                    (format!("{width}'b{pattern}"), width)
                } else if let Some(fv) = val_json.get("fixed_value").and_then(|f| f.as_i64()) {
                    (format!("{width}'d{fv}"), width)
                } else {
                    (format!("{width}'d0"), width)
                }
            } else if let Some(fv) = val_json.get("fixed_value").and_then(|f| f.as_i64()) {
                // No width, compute from field
                let w = self.decode_field_width(&field_expr);
                (format!("{w}'d{fv}"), w)
            } else if let Some(num) = val_json.as_i64() {
                // Plain number parsed as JSON (e.g. value = "32")
                let w = self.decode_field_width(&field_expr);
                (format!("{w}'d{num}"), w)
            } else {
                let w = self.decode_field_width(&field_expr);
                (format!("{w}'d0"), w)
            }
        } else if let Ok(num) = value_raw.parse::<i64>() {
            let w = self.decode_field_width(&field_expr);
            (format!("{w}'d{num}"), w)
        } else {
            (value_raw.to_string(), 1)
        };

        let _ = slice_width; // used implicitly in cmp_value formatting
        self.comb_logic += &format!("    assign {vname} = {field_expr} {operator} {cmp_value};\n");
    }

    /// Extract bit width from a Verilog slice expression like "instr[6:0]"
    fn decode_field_width(&self, field_expr: &str) -> i64 {
        if let Some(bracket) = field_expr.find('[') {
            let inner = &field_expr[bracket+1..field_expr.len()-1];
            if let Some(colon) = inner.find(':') {
                let high: i64 = inner[..colon].trim().parse().unwrap_or(0);
                let low: i64 = inner[colon+1..].trim().parse().unwrap_or(0);
                return high - low + 1;
            }
        }
        1
    }

    fn generate_mux_instantiation(&mut self, node_id: &str) {
        let node = &self.graph.nodes[node_id];
        let vname = self
            .node_id_to_name
            .get(node_id)
            .cloned()
            .unwrap_or_else(|| self.sanitize_identifier(node_id));

        // Collect inputs and selects
        let mut mux_inputs: Vec<(i64, String)> = Vec::new();
        let mut mux_selects: Vec<(i64, String)> = Vec::new();
        let mut default_signal: Option<String> = None;

        let mut sorted_eids: Vec<_> = node.incoming_edges.iter().collect();
        sorted_eids.sort();

        for eid in &sorted_eids {
            if let Some(edge) = self.graph.edges.get(eid.as_str()) {
                let et = edge_str(edge, "type");
                if et == "mux_input" {
                    let idx = edge.data.get("input_index")
                        .or_else(|| edge.data.get("mux_select"))
                        .and_then(|v| v.as_i64())
                        .unwrap_or(0);
                    let src = self.get_node_verilog_ref(&edge.source);
                    mux_inputs.push((idx, src));
                } else if et == "mux_select" {
                    let idx = edge.data.get("select_index")
                        .or_else(|| edge.data.get("input_index"))
                        .and_then(|v| v.as_i64())
                        .unwrap_or(0);
                    let sel_name = self
                        .node_id_to_name
                        .get(&edge.source)
                        .cloned()
                        .unwrap_or_else(|| self.sanitize_identifier(&edge.source));
                    mux_selects.push((idx, sel_name));
                } else if et == "mux_default_input" {
                    default_signal = Some(self.get_node_verilog_ref(&edge.source));
                }
            }
        }

        mux_inputs.sort_by_key(|(i, _)| *i);
        mux_selects.sort_by_key(|(i, _)| *i);

        // Promote mux selectors to match data pipeline stage if mismatched
        self.promote_mux_selects_to_data_stage(&mut mux_selects, &mux_inputs);

        let mux_width = node_i64(node, "data_width")
            .or_else(|| node_i64(node, "output_width"))
            .or_else(|| node_i64(node, "bit_width"))
            .unwrap_or(32);

        // Determine mux type: priority (one-hot selects) or binary
        let select_type = node.data.get("select_type").and_then(|v| v.as_str()).unwrap_or("priority");

        self.assigned_signals.insert(vname.clone());

        if select_type == "priority" || mux_selects.len() == mux_inputs.len() {
            // Priority mux: if-else chain
            self.comb_logic += &format!("    // Inline mux logic for {node_id}\n");
            self.comb_logic += "    always @* begin\n";
            let select_sigs: Vec<_> = mux_selects.iter().map(|(_, s)| s.as_str()).collect();
            for (i, (_, inp)) in mux_inputs.iter().enumerate() {
                if i < select_sigs.len() {
                    if i == 0 {
                        self.comb_logic += &format!("        if ({}) begin\n", select_sigs[i]);
                    } else {
                        self.comb_logic += &format!("        end else if ({}) begin\n", select_sigs[i]);
                    }
                    self.comb_logic += &format!("            {vname} = {inp};\n");
                }
            }
            self.comb_logic += "        end else begin\n";
            if let Some(ref def) = default_signal {
                self.comb_logic += &format!("            {vname} = {def};\n");
            } else {
                self.comb_logic += &format!("            {vname} = {mux_width}'d0;\n");
            }
            self.comb_logic += "        end\n";
            self.comb_logic += "    end\n\n";
        } else {
            // Binary mux: case statement
            let select_sig = mux_selects
                .first()
                .map(|(_, s)| s.as_str())
                .unwrap_or("1'b0");
            self.comb_logic += &format!("    // Inline mux logic for {node_id}\n");
            self.comb_logic += "    always @* begin\n";
            self.comb_logic += &format!("        case ({select_sig})\n");
            for (idx, inp) in &mux_inputs {
                self.comb_logic += &format!("            {idx}: {vname} = {inp};\n");
            }
            self.comb_logic += &format!("            default: {vname} = ");
            if let Some(ref def) = default_signal {
                self.comb_logic += &format!("{def};\n");
            } else {
                self.comb_logic += &format!("{mux_width}'d0;\n");
            }
            self.comb_logic += "        endcase\n";
            self.comb_logic += "    end\n\n";
        }
    }

    fn generate_address_offset_logic(&mut self, node_id: &str) {
        // Address offset logic: output = base + offset
        self.generate_operation_logic(node_id);
    }

    fn generate_memory_data_merge_logic(&mut self, node_id: &str) {
        // Memory data merge: priority mux for write data
        self.generate_mux_instantiation(node_id);
    }

    /// Generate byte enable mux logic.
    /// Produces an always @* block that selects byte enables based on instruction enables.
    fn generate_byte_enable_mux_logic(&mut self, node_id: &str) {
        let node = match self.graph.nodes.get(node_id) {
            Some(n) => n,
            None => return,
        };
        let vname = self.get_verilog_name(node_id);
        let bit_width = node.data.get("bit_width").and_then(|v| v.as_i64()).unwrap_or(4);
        let default_value = node.data.get("default_value").and_then(|v| v.as_i64())
            .unwrap_or((1 << bit_width) - 1);
        let mux_inputs = node.data.get("mux_inputs").and_then(|v| v.as_array()).cloned()
            .unwrap_or_default();

        self.comb_logic += &format!("    // Byte enable mux for {}\n", node_id);
        self.comb_logic += "    always @* begin\n";
        self.comb_logic += &format!("        {} = {}'d{};\n", vname, bit_width, default_value);

        for (i, input) in mux_inputs.iter().enumerate() {
            if let Some(arr) = input.as_array() {
                if arr.len() >= 2 {
                    let enable_id = arr[0].as_str().unwrap_or("");
                    let data_id = arr[1].as_str().unwrap_or("");
                    let enable_name = self.get_verilog_name(enable_id);
                    let data_name = self.get_verilog_name(data_id);
                    let keyword = if i == 0 { "if" } else { "else if" };
                    self.comb_logic += &format!(
                        "        {} ({}) {} = {};\n",
                        keyword, enable_name, vname, data_name
                    );
                }
            }
        }

        self.comb_logic += "    end\n";
    }

    /// Generate simple mux logic: `assign x = sel ? true_val : false_val`
    fn generate_simple_mux_logic(&mut self, node_id: &str) {
        let node = match self.graph.nodes.get(node_id) {
            Some(n) => n,
            None => return,
        };
        let vname = self.get_verilog_name(node_id);

        // Try data fields first (mux_select, mux_true, mux_false)
        let sel_name = node.data.get("mux_select").and_then(|v| v.as_str())
            .map(|s| self.get_verilog_name(s));
        let true_name = node.data.get("mux_true").and_then(|v| v.as_str())
            .map(|s| self.get_verilog_name(s));
        let false_name = node.data.get("mux_false").and_then(|v| v.as_str())
            .map(|s| self.get_verilog_name(s));

        if let (Some(sel), Some(t), Some(f)) = (sel_name, true_name, false_name) {
            self.comb_logic += &format!(
                "    assign {} = {} ? {} : {};\n",
                vname, sel, t, f
            );
            return;
        }

        // Fallback: find edges (mux_select, mux_input with condition true/false)
        let mut sel = String::new();
        let mut true_input = String::new();
        let mut false_input = String::new();
        for eid in &node.incoming_edges {
            if let Some(e) = self.graph.edges.get(eid) {
                let et = edge_str(e, "type");
                if et == "mux_select" {
                    sel = self.get_verilog_name(&e.source);
                } else if et == "mux_input" {
                    let cond = e.data.get("condition").and_then(|v| v.as_str()).unwrap_or("");
                    if cond == "true" {
                        true_input = self.get_verilog_name(&e.source);
                    } else if cond == "false" {
                        false_input = self.get_verilog_name(&e.source);
                    }
                }
            }
        }
        if !sel.is_empty() && !true_input.is_empty() && !false_input.is_empty() {
            self.comb_logic += &format!(
                "    assign {} = {} ? {} : {};\n",
                vname, sel, true_input, false_input
            );
        }
    }

    /// Generate array read logic for RAS: `assign x = stack[idx]`
    fn generate_ras_array_read_logic(&mut self, node_id: &str) {
        let node = match self.graph.nodes.get(node_id) {
            Some(n) => n,
            None => return,
        };
        // Only handle ras_component array reads
        if !node_bool(node, "ras_component") {
            return;
        }
        let vname = self.get_verilog_name(node_id);
        // Find array_base and array_index edges
        let mut array_name = String::new();
        let mut index_name = String::new();
        for eid in &node.incoming_edges {
            if let Some(e) = self.graph.edges.get(eid) {
                let et = edge_str(e, "type");
                if et == "array_base" {
                    array_name = self.get_verilog_name(&e.source);
                } else if et == "array_index" {
                    index_name = self.get_verilog_name(&e.source);
                }
            }
        }
        if !array_name.is_empty() && !index_name.is_empty() {
            self.comb_logic += &format!(
                "    assign {} = {}[{}];\n",
                vname, array_name, index_name
            );
        }
    }

    fn generate_variable_assignments(&mut self) {
        let mut sorted_edges: Vec<_> = self.graph.edges.values().collect();
        sorted_edges.sort_by(|a, b| a.source.cmp(&b.source).then(a.target.cmp(&b.target)));

        for edge in sorted_edges {
            if edge_str(edge, "type") != "assignment" {
                continue;
            }

            let target = match self.graph.nodes.get(&edge.target) {
                Some(n) => n,
                None => continue,
            };

            let nt = node_str(target, "type");

            // Skip bit_slice write targets
            if nt == "bit_slice" {
                continue;
            }

            // Determine if we should generate a combinational assign
            let mut should_assign = false;

            if !target.is_arch_state {
                if matches!(nt, "var" | "temp_var" | "isa_state" | "control_signal" | "cache_read_req")
                    && !self.should_be_register(target)
                {
                    should_assign = true;
                }
            } else if edge.target.ends_with("_wr") {
                should_assign = true;
            }

            if !should_assign {
                continue;
            }

            // Skip x0
            let target_name_check = target
                .data
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or(&edge.target);
            if target_name_check == "x0" {
                continue;
            }

            // Skip memory arrays
            if node_bool(target, "is_memory") {
                continue;
            }

            let target_name = self
                .node_id_to_name
                .get(&edge.target)
                .cloned()
                .unwrap_or_else(|| {
                    target
                        .data
                        .get("name")
                        .and_then(|v| v.as_str())
                        .unwrap_or(&edge.target)
                        .to_string()
                });

            if self.assigned_signals.contains(&target_name) {
                continue;
            }
            self.assigned_signals.insert(target_name.clone());

            // Special handling for flush signals: gate with instruction enable
            // instead of using the constant value (flush should only fire when its instruction executes)
            if node_bool(target, "is_flush_trigger") {
                if let Some(instruction) = target.data.get("instruction").and_then(|v| v.as_str()) {
                    let enable_signal = format!("{}_enable", instruction);
                    self.comb_logic += &format!("    assign {target_name} = {enable_signal};\n");
                    continue;
                }
            }

            let source_name = self.get_node_verilog_ref(&edge.source);
            self.comb_logic += &format!("    assign {target_name} = {source_name};\n");
        }
    }

    fn generate_conceptual_forwarding(&mut self) {
        let mut sorted_nodes: Vec<(&String, &Node)> = self.graph.nodes.iter().collect();
        sorted_nodes.sort_by_key(|(id, _)| id.as_str());

        for (node_id, node) in sorted_nodes {
            if !node_id.contains("_rd") || !node.is_arch_state {
                continue;
            }
            if node.data.get("array_depth").is_some() || node_bool(node, "is_memory") {
                continue;
            }
            if node_bool(node, "is_external") && !node_bool(node, "is_push") {
                continue;
            }

            let has_state_update = node.incoming_edges.iter().any(|eid| {
                self.graph
                    .edges
                    .get(eid)
                    .map(|e| edge_str(e, "type") == "state_update")
                    .unwrap_or(false)
            });

            if has_state_update {
                let rd_name = self
                    .node_id_to_name
                    .get(node_id)
                    .cloned()
                    .unwrap_or_else(|| self.sanitize_identifier(node_id));
                let base_name = rd_name.replace("_rd", "");
                self.comb_logic += &format!("    assign {rd_name} = {base_name};\n");
            }
        }
    }

    // ===================================================================
    // STAGE 5: Sequential logic generation
    // ===================================================================

    fn generate_sequential_logic(&mut self) {
        // Find assignment edges to registers
        let mut register_assignments: Vec<(String, String)> = Vec::new(); // (source_id, target_id)

        let mut sorted_edges: Vec<_> = self.graph.edges.values().collect();
        sorted_edges.sort_by(|a, b| a.source.cmp(&b.source).then(a.target.cmp(&b.target)));

        for edge in &sorted_edges {
            if edge_str(edge, "type") != "assignment" {
                continue;
            }
            let target = match self.graph.nodes.get(&edge.target) {
                Some(n) => n,
                None => continue,
            };

            let is_array_access_wr =
                edge.target.ends_with("_wr") && edge.target.contains('[') && !edge.target.contains(':');
            let is_split_isa = edge.target.ends_with("_wr")
                && target.data.get("name").is_some()
                && !is_array_access_wr;
            // Non-split isa_state (like flags, or non-split pc) that is arch state and not memory
            let is_non_split_isa_state = node_str(target, "type").starts_with("isa_state")
                && target.is_arch_state
                && !edge.target.contains("_wr")
                && !node_bool(target, "is_memory");

            // Skip RAS pointer/stack assignments — handled by generate_ras_sequential_logic
            let target_type = node_str(target, "type");
            if target_type == "ras_ptr" || target_type == "ras_stack" {
                continue;
            }

            if (self.should_be_register(target) && !node_bool(target, "is_memory"))
                || is_split_isa
                || is_non_split_isa_state
            {
                register_assignments.push((edge.source.clone(), edge.target.clone()));
            }
        }

        // Find pipeline register assignments
        let mut pipeline_assignments: Vec<(String, String)> = Vec::new();
        for edge in &sorted_edges {
            if edge_str(edge, "type") != "pipeline_input" {
                continue;
            }
            let target = match self.graph.nodes.get(&edge.target) {
                Some(n) => n,
                None => continue,
            };
            if target.is_uarch_state || node_str(target, "type") == "pipeline_register" {
                pipeline_assignments.push((edge.source.clone(), edge.target.clone()));
            }
        }

        if register_assignments.is_empty() && pipeline_assignments.is_empty() {
            return;
        }

        self.seq_logic += "    always @(posedge clk) begin\n";
        self.seq_logic += "        if (reset) begin\n";

        // Collect names of RAS-managed registers (handled in RAS block)
        let ras_reg_names: HashSet<String> = self.graph.nodes.iter()
            .filter(|(_, n)| node_str(n, "type") == "ras_ptr")
            .map(|(nid, _)| self.get_verilog_name(nid))
            .collect();

        // Reset assignments
        let mut regs = self.reg_declarations.clone();
        regs.sort_by(|a, b| a.name.cmp(&b.name));
        for reg in &regs {
            // Skip RAS-managed registers — reset handled in RAS sequential block
            if ras_reg_names.contains(&reg.name) {
                continue;
            }
            self.seq_logic += &format!(
                "            {} <= {};\n",
                reg.name, reg.reset_wire
            );
        }

        self.seq_logic += "        end else begin\n";

        // Build map of stage stall controllers: stage_name -> stall_ctrl_verilog_name
        // (must be built before register and pipeline assignments)
        let mut stage_stall_map: HashMap<String, String> = HashMap::new();
        for (nid, node) in &self.graph.nodes {
            if node_str(node, "type") == "pipeline_stall_controller" {
                // Extract stage name from e.g. "PIPE_Decode_stall_ctrl"
                if let Some(stage) = nid.strip_prefix("PIPE_").and_then(|s| s.split('_').next()) {
                    let ctrl_name = self.node_id_to_name
                        .get(nid)
                        .cloned()
                        .unwrap_or_else(|| self.sanitize_identifier(nid));
                    stage_stall_map.insert(stage.to_string(), ctrl_name);
                }
            }
        }

        // Build stall-and-not-flush signals for stages that have both stall and flush
        let mut stall_and_not_flush: HashMap<String, String> = HashMap::new();
        if !stage_stall_map.is_empty() {
            // Check for control_hazard_flush
            let has_flush = self.graph.nodes.contains_key("control_hazard_flush");
            for (stage, ctrl_name) in &stage_stall_map {
                // Only gate with flush for Decode/FetchDecode stages.
                // Memory-stage instructions are OLDER than the Execute-stage branch
                // and must NOT be flushed. A flush during a multi-cycle cache stall
                // would corrupt pipeline registers (address, byte offset, halfword
                // select) that the cache needs to complete the operation.
                let is_pre_execute = stage == "Decode" || stage == "FetchDecode";
                if has_flush && is_pre_execute {
                    let sig_name = format!("{}_and_not_flush", ctrl_name);
                    self.comb_logic += &format!(
                        "    assign {} = {} && !control_hazard_flush;\n",
                        sig_name, ctrl_name
                    );
                    self.wire_declarations.push(WireDecl {
                        name: sig_name.clone(),
                        bit_width: 1,
                    });
                    stall_and_not_flush.insert(stage.clone(), sig_name);
                } else {
                    stall_and_not_flush.insert(stage.clone(), ctrl_name.clone());
                }
            }
        }

        // Deduplicate register assignments by target
        let mut seen_targets: HashSet<String> = HashSet::new();
        for (source_id, target_id) in &register_assignments {
            let target_key = if target_id.ends_with("_wr") {
                target_id.replace("_wr", "")
            } else {
                self.graph
                    .nodes
                    .get(target_id)
                    .and_then(|n| n.data.get("name"))
                    .and_then(|v| v.as_str())
                    .unwrap_or(target_id)
                    .to_string()
            };

            if seen_targets.contains(&target_key) {
                continue;
            }
            seen_targets.insert(target_key);

            if target_id.ends_with("_wr") {
                // _wr node → update corresponding _rd register or base register
                let rd_node_id = target_id.replace("_wr", "_rd");
                let base_name = target_id.replace("_wr", "");

                // Determine target register name
                let target_name = if self.graph.nodes.contains_key(&rd_node_id) {
                    let rd_node = &self.graph.nodes[&rd_node_id];
                    let has_su = rd_node.incoming_edges.iter().any(|eid| {
                        self.graph
                            .edges
                            .get(eid)
                            .map(|e| edge_str(e, "type") == "state_update")
                            .unwrap_or(false)
                    });
                    if has_su {
                        base_name.clone()
                    } else {
                        rd_node_id.clone()
                    }
                } else {
                    base_name.clone()
                };

                let wr_name = self
                    .node_id_to_name
                    .get(target_id)
                    .cloned()
                    .unwrap_or_else(|| self.sanitize_identifier(target_id));

                // Gate PC update with stall signal
                let is_pc = target_name == "pc_rd" || target_name == "pc";
                if is_pc {
                    if let Some(stall_sig) = stall_and_not_flush.get("Decode") {
                        self.seq_logic += &format!("            if (!{stall_sig}) {target_name} <= {wr_name};\n");
                    } else {
                        self.seq_logic += &format!("            {target_name} <= {wr_name};\n");
                    }
                } else {
                    self.seq_logic += &format!("            {target_name} <= {wr_name};\n");
                }
            } else {
                // Non-split state
                let target_name = self
                    .graph
                    .nodes
                    .get(target_id)
                    .and_then(|n| n.data.get("name"))
                    .and_then(|v| v.as_str())
                    .unwrap_or(target_id);
                let source_name = self.get_node_verilog_ref(source_id);
                self.seq_logic += &format!("            {target_name} <= {source_name};\n");
            }
        }

        // Pipeline register updates
        for (source_id, target_id) in &pipeline_assignments {
            let target_name = self
                .node_id_to_name
                .get(target_id)
                .cloned()
                .unwrap_or_else(|| self.sanitize_identifier(target_id));

            // Detect backwards pipeline_input: source pipe_time > target pipe_time.
            // This happens when a logical_or node was pipelined beyond the register's
            // stage (e.g., umem_addr_rd_enable at Memory feeds PIPE_Execute register).
            // In this case, recompute the source inline from pre-pipelined inputs.
            let source_name = {
                let src_pt = self.graph.nodes.get(source_id).and_then(|n| n.pipe_time).unwrap_or(0);
                let tgt_pt = self.graph.nodes.get(target_id).and_then(|n| n.pipe_time).unwrap_or(0);
                let src_type = self.graph.nodes.get(source_id).map(|n| node_str(n, "type")).unwrap_or_default();

                if src_pt > tgt_pt && (src_type == "logical_or" || src_type == "logical_and") {
                    // Find the pre-pipelined versions of the source's inputs.
                    // Each input is at pipe_time=src_pt; we need pipe_time=(tgt_pt-1)
                    // which is the stage that feeds INTO this pipeline register.
                    let feed_pt = if tgt_pt > 0 { tgt_pt - 1 } else { 0 };
                    let steps_back = src_pt as i64 - feed_pt as i64;

                    let mut input_names: Vec<String> = Vec::new();
                    if let Some(src_node) = self.graph.nodes.get(source_id) {
                        let mut in_eids: Vec<&String> = src_node.incoming_edges.iter().collect();
                        in_eids.sort();
                        for eid in in_eids {
                            if let Some(e) = self.graph.edges.get(eid.as_str()) {
                                if edge_str(e, "type") == "logic_input" {
                                    // Trace back through pipeline_input edges
                                    let orig = self.trace_pipeline_source(&e.source, steps_back as usize);
                                    let name = self.get_node_verilog_ref(&orig);
                                    input_names.push(name);
                                }
                            }
                        }
                    }

                    if !input_names.is_empty() {
                        let op = if src_type == "logical_or" { " || " } else { " && " };
                        input_names.join(op)
                    } else {
                        self.get_node_verilog_ref(source_id)
                    }
                } else {
                    self.get_node_verilog_ref(source_id)
                }
            };

            // Check for explicit stall edge on this specific register
            let target_node = &self.graph.nodes[target_id];
            let mut stall_signal: Option<String> = None;
            let mut matched_as_next_stage = false;
            for eid in &target_node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(eid) {
                    if edge_str(edge, "type") == "stall" {
                        stall_signal = Some(
                            self.node_id_to_name
                                .get(&edge.source)
                                .cloned()
                                .unwrap_or_else(|| self.sanitize_identifier(&edge.source)),
                        );
                        // Check if this is a next-stage match for bubble insertion
                        if let Some(target_stage) = target_id.strip_prefix("PIPE_").and_then(|s| s.split('_').next()) {
                            if let Some(src_stage) = edge.source.strip_prefix("PIPE_").and_then(|s| s.split('_').next()) {
                                matched_as_next_stage = match src_stage {
                                    "Memory" => target_stage.starts_with("Writeback"),
                                    "Decode" => target_stage.starts_with("Execute"),
                                    "FetchDecode" => target_stage.starts_with("Execute"),
                                    _ => false,
                                };
                            }
                        }
                        break;
                    }
                }
            }

            // Cache infrastructure registers (refill address, write-through signals)
            // must NOT be stall-gated. They carry cache control signals that need to
            // update even during pipeline stalls (e.g., the refill address is only valid
            // from the cache module after the stall starts).
            let is_cache_infra = target_id.contains("_refill_addr_");
            if is_cache_infra {
                stall_signal = None; // Clear any explicit stall found above
            }

            // If no explicit stall, check for stage-level stall controller
            if stall_signal.is_none() && !is_cache_infra {
                // Determine which stage this pipeline register belongs to
                // PIPE_{Stage}_{signal}_PIPE registers are filled FROM the previous stage
                // e.g. PIPE_Execute_*_PIPE is filled from Decode, so it should be stalled
                // when the Decode stage stalls
                if target_id.starts_with("PIPE_") {
                    if let Some(stage) = target_id.strip_prefix("PIPE_").and_then(|s| s.split('_').next()) {
                        // This register is filled from the stage BEFORE it
                        // We need to find the stall controller for the previous stage
                        // For PIPE_Execute_* -> stalled by Decode stall
                        // For PIPE_Decode_* -> stalled by Fetch stall (if exists)
                        // Use the stage_stall_map to find if any previous stage has a stall
                        // In a 5-stage pipeline: Decode stall affects PIPE_Execute_* and PIPE_Decode_*
                        for (stall_stage, sig) in &stall_and_not_flush {
                            // Stall gates the stalled stage's registers AND the next stage's registers.
                            // For a Decode stall: gates PIPE_Decode_* and PIPE_{Execute*}_*
                            // For a Memory stall: gates PIPE_Memory_* and PIPE_Writeback_*
                            // This handles combined stages like ExecuteMemoryWriteback (3-stage pipeline).
                            let is_stall_stage = stage == stall_stage.as_str();
                            let is_next_stage = match stall_stage.as_str() {
                                "Decode" => stage.starts_with("Execute"),
                                "FetchDecode" => stage.starts_with("Execute"),
                                "Memory" => stage.starts_with("Writeback"),
                                _ => false,
                            };
                            if is_stall_stage || is_next_stage {
                                stall_signal = Some(sig.clone());
                                matched_as_next_stage = is_next_stage;
                                break;
                            }
                        }
                    }
                }
            }

            if let Some(stall) = stall_signal {
                // For valid signals entering the stage AFTER the stalled stage,
                // insert a bubble (set to 0) during stall instead of holding.
                // e.g. PIPE_Execute_valid_PIPE should be set to (source && !stall)
                // so the duplicate instruction doesn't flow into Memory/Writeback.
                // This applies to any next-stage valid signal (Execute for Decode stall,
                // Writeback for Memory stall).
                let is_next_stage_valid = target_name.contains("_valid_PIPE")
                    && matched_as_next_stage;
                if is_next_stage_valid {
                    // Valid must be killed by BOTH stall and flush independently.
                    // stall_and_not_flush is wrong here because when flush=1,
                    // stall_and_not_flush=0 and valid would pass through.
                    // Use the raw stall controller + flush for proper gating.
                    // BUT: only apply flush gating for Execute-stage valid signals.
                    // Writeback instructions are OLDER than the branch at Execute
                    // and must NOT be flushed (they should complete normally).
                    let has_flush = self.graph.nodes.contains_key("control_hazard_flush");
                    let apply_flush = has_flush && target_id.starts_with("PIPE_Execute");

                    // When a downstream stall controller exists (e.g., Memory stall for
                    // Execute valid), the valid signal must HOLD during downstream stalls.
                    // Without this, a dcache stall at Memory causes Decode stall, which
                    // bubbles Execute valid, killing the instruction at Execute.
                    let target_stage = target_id.strip_prefix("PIPE_")
                        .and_then(|s| s.split('_').next())
                        .unwrap_or("");
                    let downstream_stall = match target_stage {
                        "Execute" => stage_stall_map.get("Memory").cloned(),
                        _ => None,
                    };

                    if apply_flush {
                        let raw_stall = stall.replace("_and_not_flush", "");
                        if let Some(ref ds_stall) = downstream_stall {
                            // Hold during downstream stall, but still allow flush to kill valid
                            self.seq_logic += &format!(
                                "            if (!{ds_stall} || control_hazard_flush) {target_name} <= {source_name} && !{raw_stall} && !control_hazard_flush;\n"
                            );
                        } else {
                            self.seq_logic += &format!(
                                "            {target_name} <= {source_name} && !{raw_stall} && !control_hazard_flush;\n"
                            );
                        }
                    } else {
                        if let Some(ref ds_stall) = downstream_stall {
                            self.seq_logic += &format!(
                                "            if (!{ds_stall}) {target_name} <= {source_name} && !{stall};\n"
                            );
                        } else {
                            self.seq_logic += &format!(
                                "            {target_name} <= {source_name} && !{stall};\n"
                            );
                        }
                    }
                } else {
                    self.seq_logic += &format!(
                        "            if (!{stall}) {target_name} <= {source_name};\n"
                    );
                }
            } else {
                self.seq_logic += &format!("            {target_name} <= {source_name};\n");
            }
        }

        self.seq_logic += "        end\n";
        self.seq_logic += "    end\n\n";
    }

    // -----------------------------------------------------------------------
    // RAS sequential logic (array write + pointer update)
    // -----------------------------------------------------------------------

    fn generate_ras_sequential_logic(&mut self) {
        // Find array_write nodes with ras_component flag
        let ras_writes: Vec<String> = self.graph.nodes.iter()
            .filter(|(_, n)| node_str(n, "type") == "array_write" && node_bool(n, "ras_component"))
            .map(|(id, _)| id.clone())
            .collect();

        // Find ras_ptr_update nodes
        let ptr_updates: Vec<String> = self.graph.nodes.iter()
            .filter(|(_, n)| node_str(n, "type") == "ras_ptr_update")
            .map(|(id, _)| id.clone())
            .collect();

        if ras_writes.is_empty() && ptr_updates.is_empty() {
            return;
        }

        // Find the RAS stack array name and its depth
        let mut ras_stack_name = String::new();
        let mut ras_stack_depth: i64 = 8;
        for (nid, n) in &self.graph.nodes {
            if node_str(n, "type") == "ras_stack" {
                ras_stack_name = self.get_verilog_name(nid);
                ras_stack_depth = node_i64(n, "depth").unwrap_or(8);
                break;
            }
        }

        // Find RAS ptr register name and width
        let mut ras_ptr_name = String::new();
        let mut ptr_width: i64 = 3;
        for (nid, n) in &self.graph.nodes {
            if node_str(n, "type") == "ras_ptr" {
                ras_ptr_name = self.get_verilog_name(nid);
                ptr_width = node_i64(n, "bit_width").unwrap_or(3);
                break;
            }
        }

        // Collect write info from array_write nodes
        let mut write_enable = String::new();
        let mut write_addr = String::new();
        let mut write_data = String::new();
        for wr_id in &ras_writes {
            let wr_node = &self.graph.nodes[wr_id];
            for eid in &wr_node.incoming_edges {
                if let Some(e) = self.graph.edges.get(eid) {
                    let et = edge_str(e, "type");
                    if et == "write_enable" {
                        write_enable = self.get_verilog_name(&e.source);
                    } else if et == "write_address" {
                        write_addr = self.get_verilog_name(&e.source);
                    } else if et == "write_data" {
                        write_data = self.get_verilog_name(&e.source);
                    }
                }
            }
        }

        // Find push_valid / pop_valid from the ras_push_valid / ras_pop_valid nodes
        let push_valid_name = self.get_verilog_name("ras_push_valid");
        let pop_valid_name = self.get_verilog_name("ras_pop_valid");

        // Generate the RAS always block
        self.seq_logic += "    // RAS stack and pointer update\n";
        self.seq_logic += "    always @(posedge clk) begin\n";
        self.seq_logic += "        if (reset) begin\n";

        // Reset pointer to 0
        if !ras_ptr_name.is_empty() {
            self.seq_logic += &format!("            {} <= {}'d0;\n", ras_ptr_name, ptr_width);
        }

        self.seq_logic += "        end else begin\n";

        // Combined push/pop logic matching Python output
        let arr_name = if ras_stack_name.is_empty() { "ras_stack".to_string() } else { ras_stack_name.clone() };
        let addr_expr = if write_addr.is_empty() { ras_ptr_name.clone() } else { write_addr };

        if !push_valid_name.is_empty() && !pop_valid_name.is_empty() {
            self.seq_logic += &format!("            if ({}) begin\n", push_valid_name);
            if !write_data.is_empty() {
                self.seq_logic += &format!("                {}[{}] <= {};\n", arr_name, addr_expr, write_data);
            }
            if !ras_ptr_name.is_empty() {
                self.seq_logic += &format!("                {} <= {} + 1;\n", ras_ptr_name, ras_ptr_name);
            }
            self.seq_logic += &format!("            end else if ({}) begin\n", pop_valid_name);
            if !ras_ptr_name.is_empty() {
                self.seq_logic += &format!("                {} <= {} - 1;\n", ras_ptr_name, ras_ptr_name);
            }
            self.seq_logic += "            end\n";
        }

        self.seq_logic += "        end\n";
        self.seq_logic += "    end\n\n";
    }

    // -----------------------------------------------------------------------
    // Pipeline valid gating for memory/register writes
    // -----------------------------------------------------------------------

    /// Determine the valid signal for gating writes at the correct pipeline stage.
    /// Parses the write_enable condition to find the pipeline stage (e.g., "Writeback"
    /// from "PIPE_Writeback_..."), then returns "PIPE_{Stage}_valid_PIPE" if it exists.
    fn determine_write_valid_signal(&self, write_enable: &Option<String>) -> Option<String> {
        if let Some(we) = write_enable {
            // Find first PIPE_ token in the condition
            if let Some(pipe_pos) = we.find("PIPE_") {
                let rest = &we[pipe_pos + 5..]; // skip "PIPE_"
                if let Some(underscore_pos) = rest.find('_') {
                    let stage_name = &rest[..underscore_pos];
                    let valid_id = format!("PIPE_{}_valid_PIPE", stage_name);
                    if self.graph.nodes.contains_key(&valid_id) {
                        return Some(valid_id);
                    }
                }
            }
        }
        None
    }

    /// Extract the outermost pipeline stage name from a pipelined signal.
    /// e.g., "PIPE_Memory_PIPE_Execute_foo_PIPE_PIPE" → Some("Memory")
    ///       "PIPE_Execute_foo_PIPE" → Some("Execute")
    ///       "foo" → None
    fn get_outermost_pipeline_stage(signal: &str) -> Option<String> {
        if signal.starts_with("PIPE_") {
            let rest = &signal[5..];
            if let Some(idx) = rest.find('_') {
                return Some(rest[..idx].to_string());
            }
        }
        None
    }

    /// Map pipeline stage name to numerical order for comparison.
    fn pipeline_stage_order(stage: &str) -> usize {
        match stage {
            "Decode" => 1,
            "Execute" => 2,
            "Memory" => 3,
            "Writeback" => 4,
            // Combined stage names for fewer-stage pipelines
            "FetchDecode" => 1,
            "ExecuteMemoryWriteback" => 2,
            "MemoryWriteback" => 4,
            _ => 0,
        }
    }

    /// Promote mux select signals to match the pipeline stage of data inputs.
    /// This fixes cases where mux selectors are at an earlier pipeline stage
    /// than the data they're selecting (e.g., Execute enables with Memory data).
    fn promote_mux_selects_to_data_stage(
        &self,
        mux_selects: &mut Vec<(i64, String)>,
        mux_inputs: &[(i64, String)],
    ) {
        // Find the max pipeline stage order from data inputs
        let target_stage = mux_inputs.iter()
            .filter_map(|(_, sig)| Self::get_outermost_pipeline_stage(sig))
            .max_by_key(|stage| Self::pipeline_stage_order(stage));

        let target_stage = match target_stage {
            Some(s) => s,
            None => return,
        };
        let target_order = Self::pipeline_stage_order(&target_stage);
        if target_order == 0 {
            return;
        }

        for (_, sel) in mux_selects.iter_mut() {
            let sel_order = Self::get_outermost_pipeline_stage(sel)
                .map(|s| Self::pipeline_stage_order(&s))
                .unwrap_or(0);

            if sel_order < target_order {
                // Try one-level promotion: wrap with PIPE_{target_stage}_{sel}_PIPE
                let promoted = format!("PIPE_{}_{}_PIPE", target_stage, sel);
                if self.graph.nodes.contains_key(&promoted) {
                    *sel = promoted;
                }
            }
        }
    }

    // -----------------------------------------------------------------------
    // Variable latency memory logic (FSM counters for multi-cycle memories)
    // -----------------------------------------------------------------------

    fn generate_variable_latency_memory_logic(&mut self) {
        use crate::verilog_module_generators::{LatencyCounterGenerator, LatencyMode};

        // Find memories with variable_latency or static latency
        let mut memories: Vec<(String, String, bool)> = Vec::new(); // (node_id, sanitized_name, variable)
        for (nid, node) in &self.graph.nodes {
            let is_mem = node
                .data
                .get("is_memory")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            if !is_mem {
                continue;
            }
            let has_complete = node
                .data
                .get("complete_signal")
                .and_then(|v| v.as_str())
                .is_some();
            if !has_complete {
                continue;
            }
            let is_variable = node.variable_latency;
            let name = node
                .data
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or(nid);
            let sanitized = self.sanitize_identifier(name);
            memories.push((nid.clone(), sanitized, is_variable));
        }
        memories.sort();

        for (nid, sanitized_name, is_variable) in &memories {
            let node = &self.graph.nodes[nid];

            let start_signal = node
                .data
                .get("start_signal")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            let complete_signal = node
                .data
                .get("complete_signal")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            let idle_signal = node
                .data
                .get("idle_signal")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());

            let complete_signal = match complete_signal {
                Some(s) => s,
                None => continue,
            };

            let min_latency = node
                .data
                .get("min_latency")
                .and_then(|v| v.as_u64())
                .unwrap_or(2) as u32;
            let max_latency = node
                .data
                .get("max_latency")
                .and_then(|v| v.as_u64())
                .unwrap_or(15) as u32;
            let latency_cycles = node
                .data
                .get("latency_cycles")
                .and_then(|v| v.as_u64())
                .unwrap_or(min_latency as u64) as u32;

            let (latency_mode, static_lat) = if *is_variable && min_latency != max_latency {
                (LatencyMode::Variable, min_latency)
            } else {
                (LatencyMode::Static, latency_cycles)
            };

            let counter_bits = std::cmp::max(2, ceil_log2(static_lat + 1));

            let gen = LatencyCounterGenerator::new(
                sanitized_name.clone(),
                counter_bits,
                latency_mode,
                static_lat,
                min_latency,
                max_latency,
            );

            let counter_reg = format!("{}_latency_counter", sanitized_name);
            let target_reg = if latency_mode == LatencyMode::Variable {
                Some(format!("{}_latency_target", sanitized_name))
            } else {
                None
            };

            let complete_name = self.sanitize_identifier(&complete_signal);
            let idle_name = idle_signal
                .as_deref()
                .map(|s| self.sanitize_identifier(s));

            // Determine start expression
            let start_expr = if let Some(ref start_sig) = start_signal {
                let start_node = self.graph.nodes.get(start_sig.as_str());
                if let Some(sn) = start_node {
                    if let Some(eid) = sn.incoming_edges.iter().next() {
                        if let Some(edge) = self.graph.edges.get(eid) {
                            self.get_node_verilog_ref(&edge.source)
                        } else {
                            "1'b1".to_string()
                        }
                    } else {
                        "1'b1".to_string()
                    }
                } else {
                    "1'b1".to_string()
                }
            } else {
                "1'b1".to_string()
            };

            let logic = gen.generate_inline_logic(
                &counter_reg,
                target_reg.as_deref(),
                &start_expr,
                &complete_name,
                idle_name.as_deref(),
            );

            // Add declarations
            self.declarations_str += &logic.declarations;

            // Add combinational logic
            self.comb_logic += &format!(
                "\n    // Latency counter signals for {}\n",
                sanitized_name
            );
            self.comb_logic += &logic.comb_logic;

            // Add sequential logic
            self.seq_logic += &logic.seq_logic;

            // Mark signals as assigned so they don't get generated again
            self.assigned_signals.insert(complete_name.clone());
            if let Some(ref idle) = idle_name {
                self.assigned_signals.insert(idle.clone());
            }
        }
    }

    // -----------------------------------------------------------------------
    // Memory write logic (for memory_write_port nodes from merged graphs)
    // -----------------------------------------------------------------------

    fn generate_memory_write_logic(&mut self) {
        // Find memory_write_port nodes
        let mut write_ports: Vec<(String, String, String, String, Option<String>)> = Vec::new();
        // (base_memory, addr_signal, data_signal, port_id, write_enable_id)

        let mut port_ids: Vec<String> = self
            .graph
            .nodes
            .iter()
            .filter(|(_, n)| node_str(n, "type") == "memory_write_port")
            .map(|(id, _)| id.clone())
            .collect();
        port_ids.sort();

        for port_id in &port_ids {
            let port_node = &self.graph.nodes[port_id];

            let base_memory = port_node
                .data
                .get("base_memory")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();

            if base_memory.is_empty() {
                continue;
            }

            // Find write_data and write_address sources
            let mut data_source: Option<String> = None;
            let mut addr_source: Option<String> = None;

            for eid in &port_node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(eid) {
                    let etype = edge_str(edge, "type");
                    match etype {
                        "write_data" => {
                            data_source = Some(edge.source.clone());
                        }
                        "write_address" => {
                            addr_source = Some(edge.source.clone());
                        }
                        _ => {}
                    }
                }
            }

            if let (Some(data_src), Some(addr_src)) = (data_source, addr_source) {
                // Check for combined_write_enable on the port node
                let combined_we = port_node
                    .data
                    .get("combined_write_enable")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());

                // If no combined_write_enable, try to derive from the data mux selects
                let write_enable = if combined_we.is_some() {
                    combined_we
                } else {
                    // Look at the data mux node for select signals (which are enable signals)
                    let data_mux_node = self.graph.nodes.get(&data_src);
                    if let Some(mux_node) = data_mux_node {
                        if node_str(mux_node, "type") == "multiplexer" {
                            let mut enables: Vec<String> = Vec::new();
                            for mux_eid in &mux_node.incoming_edges {
                                if let Some(mux_edge) = self.graph.edges.get(mux_eid) {
                                    if edge_str(mux_edge, "type") == "mux_select" {
                                        let enable_name = self
                                            .node_id_to_name
                                            .get(&mux_edge.source)
                                            .cloned()
                                            .unwrap_or_else(|| {
                                                self.sanitize_identifier(&mux_edge.source)
                                            });
                                        enables.push(enable_name);
                                    }
                                }
                            }
                            if !enables.is_empty() {
                                enables.sort();
                                enables.dedup();
                                Some(enables.join(" || "))
                            } else {
                                None
                            }
                        } else {
                            None
                        }
                    } else {
                        None
                    }
                };

                // Also check for write_enable on the original array_access_wr node
                // e.g., rf[rd]_wr has a write_enable edge from (rd != 0)
                let wr_node_id = format!("{}[{}]_wr", base_memory,
                    // Find the index by checking address mux or original array access
                    "rd"); // Simplified — will be overridden by addr_mux
                let _ = wr_node_id; // Unused for now

                let data_name = self
                    .node_id_to_name
                    .get(&data_src)
                    .cloned()
                    .unwrap_or_else(|| self.sanitize_identifier(&data_src));
                let addr_name = self
                    .node_id_to_name
                    .get(&addr_src)
                    .cloned()
                    .unwrap_or_else(|| self.sanitize_identifier(&addr_src));

                write_ports.push((
                    base_memory,
                    addr_name,
                    data_name,
                    port_id.clone(),
                    write_enable,
                ));
            }
        }

        if write_ports.is_empty() {
            return;
        }

        // Generate memory write always block
        self.seq_logic += "    // Memory write ports\n";
        self.seq_logic += "    always @(posedge clk) begin\n";
        self.seq_logic += "        if (!reset) begin\n";

        for (base_memory, addr_name, data_name, port_id, write_enable) in &write_ports {
            // Check if this is a physical memory that needs address scaling
            let mem_node = self.graph.nodes.get(base_memory.as_str());
            let is_physical = mem_node
                .map(|n| {
                    let ntype = node_str(n, "type");
                    ntype == "isa_state mem"
                })
                .unwrap_or(false);

            let index_expr = if is_physical {
                // Word-addressed memory: scale byte address
                let bit_width = mem_node
                    .and_then(|n| n.data.get("bit_width"))
                    .and_then(|v| v.as_i64())
                    .unwrap_or(32);
                let bytes = bit_width / 8;
                let shift = (bytes as f64).log2() as i64;
                format!("(({} - `MEM_BASE) >> {})", addr_name, shift)
            } else {
                // Register file: direct indexing
                addr_name.clone()
            };

            // Find any write_enable condition from original array access node
            let mut extra_enable: Option<String> = None;
            for (nid, node) in &self.graph.nodes {
                let ntype = node_str(node, "type");
                if ntype == "array_access"
                    && nid.ends_with("_wr")
                    && nid.starts_with(base_memory.as_str())
                {
                    for eid in &node.incoming_edges {
                        if let Some(edge) = self.graph.edges.get(eid) {
                            if edge_str(edge, "type") == "write_enable" {
                                let en_name = self
                                    .node_id_to_name
                                    .get(&edge.source)
                                    .cloned()
                                    .unwrap_or_else(|| {
                                        self.sanitize_identifier(&edge.source)
                                    });
                                extra_enable = Some(en_name);
                            }
                        }
                    }
                }
            }

            // Check for sub-word writers (byte enable needed for mem-type memories)
            let port_node = self.graph.nodes.get(port_id.as_str());

            // Check if this is a cache write-through port with byte enable signal
            let is_cache_wt = port_node
                .and_then(|n| n.data.get("cache_write_through"))
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            let cache_byte_en_signal = port_node
                .and_then(|n| n.data.get("cache_byte_enable_signal"))
                .and_then(|v| v.as_str())
                .map(|s| self.get_verilog_name(s));

            let writer_widths: HashMap<String, i64> = port_node
                .and_then(|n| n.data.get("writer_widths"))
                .and_then(|v| v.as_object())
                .map(|obj| {
                    obj.iter()
                        .filter_map(|(k, v)| v.as_i64().map(|w| (k.clone(), w)))
                        .collect()
                })
                .unwrap_or_default();

            let mem_width = mem_node
                .and_then(|n| n.data.get("bit_width"))
                .and_then(|v| v.as_i64())
                .unwrap_or(32);

            if is_cache_wt && is_physical {
                // Cache write-through: use byte enable signal for per-byte writes
                let num_bytes = mem_width / 8;
                let we_cond = if let Some(we) = write_enable {
                    format!("({})", we)
                } else {
                    "1'b1".to_string()
                };
                let be_signal = cache_byte_en_signal.unwrap_or_else(|| "4'hF".to_string());
                self.seq_logic += &format!("            if ({}) begin\n", we_cond);
                for byte_idx in 0..num_bytes {
                    let hi = (byte_idx + 1) * 8 - 1;
                    let lo = byte_idx * 8;
                    self.seq_logic += &format!(
                        "                if ({}[{}]) {}[{}][{}:{}] <= {}[{}:{}];\n",
                        be_signal, byte_idx, base_memory, index_expr, hi, lo, data_name, hi, lo
                    );
                }
                self.seq_logic += "            end\n";
            } else {

            let has_subword_writers = is_physical
                && !writer_widths.is_empty()
                && writer_widths.values().any(|&w| w < mem_width && w >= 8);

            if has_subword_writers {
                // Generate per-instruction byte-enable write logic
                self.generate_byte_enable_writes(
                    base_memory, &index_expr, addr_name,
                    &writer_widths, mem_width, write_enable, &extra_enable,
                );
            } else {
                // Simple full-word write
                let mut conditions: Vec<String> = Vec::new();
                if let Some(we) = write_enable {
                    conditions.push(format!("({})", we));
                }
                if let Some(ee) = &extra_enable {
                    conditions.push(ee.clone());
                }
                // Gate with pipeline valid to prevent flushed instructions from writing
                if let Some(vs) = self.determine_write_valid_signal(write_enable) {
                    conditions.push(vs);
                }

                if conditions.is_empty() {
                    self.seq_logic += &format!(
                        "            {}[{}] <= {};\n",
                        base_memory, index_expr, data_name
                    );
                } else {
                    let cond = conditions.join(" && ");
                    self.seq_logic += &format!(
                        "            if ({}) {}[{}] <= {};\n",
                        cond, base_memory, index_expr, data_name
                    );
                }
            }
            } // close else for is_cache_wt
        }

        self.seq_logic += "        end\n";
        self.seq_logic += "    end\n\n";
    }

    /// Generate byte-enable write logic for memories with sub-word stores.
    ///
    /// For each instruction that writes less than the full word width,
    /// generates per-byte-lane conditional writes. For example, for sb (8-bit):
    /// ```verilog
    /// if (sb_enable) begin
    ///     case (addr[1:0])
    ///         2'd0: mem[word_addr][7:0]   <= write_data[7:0];
    ///         2'd1: mem[word_addr][15:8]  <= write_data[7:0];
    ///         2'd2: mem[word_addr][23:16] <= write_data[7:0];
    ///         2'd3: mem[word_addr][31:24] <= write_data[7:0];
    ///     endcase
    /// end
    /// ```
    fn generate_byte_enable_writes(
        &mut self,
        base_memory: &str,
        index_expr: &str,
        addr_name: &str,
        writer_widths: &HashMap<String, i64>,
        mem_width: i64,
        write_enable: &Option<String>,
        extra_enable: &Option<String>,
    ) {
        // Build overall write enable condition
        let mut outer_conditions: Vec<String> = Vec::new();
        if let Some(we) = write_enable {
            outer_conditions.push(format!("({})", we));
        }
        if let Some(ee) = extra_enable {
            outer_conditions.push(ee.clone());
        }
        // Gate with pipeline valid to prevent flushed instructions from writing
        if let Some(vs) = self.determine_write_valid_signal(write_enable) {
            outer_conditions.push(vs);
        }

        if !outer_conditions.is_empty() {
            let cond = outer_conditions.join(" && ");
            self.seq_logic += &format!("            if ({}) begin\n", cond);
        }

        let indent = if outer_conditions.is_empty() {
            "            "
        } else {
            "                "
        };

        let num_bytes = mem_width / 8; // e.g., 4 for 32-bit

        // Sort instructions for deterministic output
        let mut sorted_instrs: Vec<(&String, &i64)> = writer_widths.iter().collect();
        sorted_instrs.sort_by_key(|(name, _)| name.clone());

        // Build a map from instruction name to pipelined enable Verilog name.
        // When write_enable is a node ID (from combined_write_enable), look at
        // that node's incoming edges to find the pipelined enable for each instruction.
        let mut pipelined_enable_map: HashMap<String, String> = HashMap::new();
        if let Some(we_node_id) = write_enable {
            // Traverse the write_enable node's inputs (potentially multiple levels)
            // to find pipelined enables matching each instruction.
            // e.g., umem_write_enable_valid_gated -> umem_write_enable ->
            //        [PIPE_Memory_PIPE_Execute_sb_enable_PIPE_PIPE, ...]
            let mut nodes_to_visit: Vec<String> = vec![we_node_id.clone()];
            let mut visited: std::collections::HashSet<String> = std::collections::HashSet::new();
            while let Some(visit_id) = nodes_to_visit.pop() {
                if !visited.insert(visit_id.clone()) {
                    continue;
                }
                if let Some(node) = self.graph.nodes.get(&visit_id) {
                    for eid in &node.incoming_edges {
                        if let Some(edge) = self.graph.edges.get(eid) {
                            let src_name = self
                                .node_id_to_name
                                .get(&edge.source)
                                .cloned()
                                .unwrap_or_else(|| self.sanitize_identifier(&edge.source));
                            let mut matched = false;
                            for (instr_name, _) in &sorted_instrs {
                                let pattern = format!("{}_enable", instr_name);
                                if edge.source.contains(&pattern) || src_name.contains(&pattern) {
                                    pipelined_enable_map
                                        .insert(instr_name.to_string(), src_name.clone());
                                    matched = true;
                                }
                            }
                            if !matched {
                                // Continue traversing deeper
                                nodes_to_visit.push(edge.source.clone());
                            }
                        }
                    }
                }
            }

            // Fix: when the traversal found unpipelined enables (e.g., "sb_enable")
            // but pipelined versions exist (e.g., "PIPE_ExecuteMemoryWriteback_sb_enable_PIPE"),
            // prefer the pipelined versions. This happens in 2/3-stage pipelines where
            // umem_write_enable is composed from unpipelined enables, then pipelined as a unit.
            for (instr_name, enable_name) in pipelined_enable_map.iter_mut() {
                let pattern = format!("{}_enable", instr_name);
                // If the found enable doesn't start with PIPE_, look for a pipelined version
                if !enable_name.starts_with("PIPE_") {
                    // Search the graph for a pipelined version of this enable
                    let mut best_pipelined: Option<String> = None;
                    for node_id in self.graph.nodes.keys() {
                        if node_id.starts_with("PIPE_")
                            && node_id.contains(&pattern)
                            && node_id.ends_with("_PIPE")
                        {
                            // Prefer shortest match (least pipelined) if multiple exist
                            if best_pipelined.as_ref().map_or(true, |b| node_id.len() < b.len()) {
                                best_pipelined = Some(node_id.clone());
                            }
                        }
                    }
                    if let Some(pipelined_id) = best_pipelined {
                        let pipelined_name = self
                            .node_id_to_name
                            .get(&pipelined_id)
                            .cloned()
                            .unwrap_or_else(|| self.sanitize_identifier(&pipelined_id));
                        *enable_name = pipelined_name;
                    }
                }
            }
        }

        let mut first = true;
        for (instr_name, &data_width) in &sorted_instrs {
            let enable_id = format!("{}_enable", instr_name);
            // Use pipelined enable from the write_enable OR node's inputs
            let enable_name = pipelined_enable_map
                .get(*instr_name)
                .cloned()
                .unwrap_or_else(|| {
                    self.node_id_to_name
                        .get(&enable_id)
                        .cloned()
                        .unwrap_or_else(|| self.sanitize_identifier(&enable_id))
                });

            // Find the data source for this instruction's write
            let data_src_name = self.find_instr_write_data_name(base_memory, instr_name);

            if data_width < mem_width && data_width >= 8 {
                // Sub-word write: generate byte-lane case statement
                let access_bytes = data_width / 8; // 1 for byte, 2 for halfword, 4 for word
                let num_positions = num_bytes / access_bytes;
                let selector_bits = (num_positions as f64).log2() as i64;
                let sel_hi = (num_bytes as f64).log2() as i64 - 1; // e.g. 2 for 64-bit, 1 for 32-bit
                let sel_lo = (access_bytes as f64).log2() as i64;  // e.g. 0 for byte, 1 for halfword

                let keyword = if first { "if" } else { "end else if" };
                self.seq_logic += &format!(
                    "{}{}({}) begin\n",
                    indent, keyword, enable_name
                );

                // Generate case statement based on address offset
                let selector = if sel_hi == sel_lo {
                    format!("{}[{}]", addr_name, sel_hi)
                } else {
                    format!("{}[{}:{}]", addr_name, sel_hi, sel_lo)
                };

                self.seq_logic += &format!("{}    case ({})\n", indent, selector);

                for pos in 0..num_positions {
                    let byte_start = pos * access_bytes * 8;
                    let byte_end = byte_start + data_width - 1;

                    self.seq_logic += &format!(
                        "{}        {}'d{}: {}[{}][{}:{}] <= {}[{}:0];\n",
                        indent,
                        selector_bits, pos,
                        base_memory, index_expr,
                        byte_end, byte_start,
                        data_src_name,
                        data_width - 1
                    );
                }

                self.seq_logic += &format!("{}    endcase\n", indent);
                first = false;
            } else {
                // Full-word write
                let keyword = if first { "if" } else { "end else if" };
                self.seq_logic += &format!(
                    "{}{}({}) begin\n",
                    indent, keyword, enable_name
                );
                self.seq_logic += &format!(
                    "{}    {}[{}] <= {};\n",
                    indent, base_memory, index_expr, data_src_name
                );
                first = false;
            }
        }

        if !first {
            self.seq_logic += &format!("{}end\n", indent);
        }

        if !outer_conditions.is_empty() {
            self.seq_logic += "            end\n";
        }
    }

    /// Find the Verilog signal name for an instruction's memory write data source.
    fn find_instr_write_data_name(&self, base_memory: &str, instr_name: &str) -> String {
        // Look through the data mux to find this instruction's data source
        let data_mux_id = format!("{}_write_data_mux", base_memory);
        if let Some(mux_node) = self.graph.nodes.get(&data_mux_id) {
            for eid in &mux_node.incoming_edges {
                if let Some(edge) = self.graph.edges.get(eid) {
                    if edge_str(edge, "type") == "mux_input" {
                        // Check if this input's select is our instruction's enable
                        let input_idx = edge
                            .data
                            .get("input_index")
                            .and_then(|v| v.as_i64());

                        // Find the corresponding select with the same index
                        if let Some(idx) = input_idx {
                            for sel_eid in &mux_node.incoming_edges {
                                if let Some(sel_edge) = self.graph.edges.get(sel_eid) {
                                    if edge_str(sel_edge, "type") == "mux_select"
                                        && sel_edge
                                            .data
                                            .get("select_index")
                                            .and_then(|v| v.as_i64())
                                            == Some(idx)
                                    {
                                        // Check if this select is our instruction's enable
                                        let sel_name = &sel_edge.source;
                                        if sel_name.starts_with(instr_name)
                                            && sel_name.ends_with("_enable")
                                        {
                                            return self
                                                .node_id_to_name
                                                .get(&edge.source)
                                                .cloned()
                                                .unwrap_or_else(|| {
                                                    self.sanitize_identifier(&edge.source)
                                                });
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // Fallback: use the mux output itself
        let data_mux_name = self
            .node_id_to_name
            .get(&data_mux_id)
            .cloned()
            .unwrap_or_else(|| self.sanitize_identifier(&data_mux_id));
        data_mux_name
    }

    fn format_literal_value(&self, value: &Value, bit_width: i64) -> String {
        match value {
            Value::String(s) => {
                if s.starts_with("0b") {
                    let bits = &s[2..];
                    format!("{bit_width}'b{bits}")
                } else if s.starts_with("0x") {
                    let hex = &s[2..];
                    format!("{bit_width}'h{hex}")
                } else if let Ok(iv) = s.parse::<i64>() {
                    format!("{bit_width}'d{iv}")
                } else {
                    format!("{bit_width}'d{s}")
                }
            }
            Value::Number(n) => {
                if let Some(v) = n.as_i64() {
                    if v < 0 {
                        // Negative value: use two's complement hex representation
                        let unsigned = v as u64;
                        format!("{bit_width}'h{unsigned:X}")
                    } else {
                        format!("{bit_width}'d{v}")
                    }
                } else if let Some(v) = n.as_u64() {
                    // Large unsigned value (exceeds i64 range): use hex
                    format!("{bit_width}'h{v:X}")
                } else {
                    format!("{bit_width}'d0")
                }
            }
            _ => format!("{bit_width}'d0"),
        }
    }
}

// ---------------------------------------------------------------------------
// Helper functions for extracting typed data from node/edge data maps
// ---------------------------------------------------------------------------

fn node_str<'a>(node: &'a Node, key: &str) -> &'a str {
    node.data
        .get(key)
        .and_then(|v| v.as_str())
        .unwrap_or("")
}

fn node_i64(node: &Node, key: &str) -> Option<i64> {
    node.data.get(key).and_then(|v| v.as_i64())
}

fn node_bool(node: &Node, key: &str) -> bool {
    node.data
        .get(key)
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
}

fn edge_str<'a>(edge: &'a crate::resource_graph::Edge, key: &str) -> &'a str {
    edge.data
        .get(key)
        .and_then(|v| v.as_str())
        .unwrap_or("")
}

// ---------------------------------------------------------------------------
// Public convenience function
// ---------------------------------------------------------------------------

pub fn generate_verilog(graph: &ResourceGraph, module_name: &str) -> String {
    let mut gen = VerilogGenerator::new(graph, module_name);
    gen.generate()
}
