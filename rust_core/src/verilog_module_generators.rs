use serde_json::Value;
use std::collections::HashMap;
use std::fmt;

// ---------------------------------------------------------------------------
// PortInfo — describes a port on a generated module
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
pub enum PortDirection {
    Input,
    Output,
}

impl fmt::Display for PortDirection {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            PortDirection::Input => write!(f, "input"),
            PortDirection::Output => write!(f, "output"),
        }
    }
}

#[derive(Debug, Clone)]
pub struct PortInfo {
    pub name: String,
    pub direction: PortDirection,
    pub width: u32,
}

// ---------------------------------------------------------------------------
// ModuleGenerator trait
// ---------------------------------------------------------------------------

pub trait ModuleGenerator {
    /// Generate a complete Verilog module definition.
    fn generate_module(&self) -> String;
    /// Generate a Verilog instantiation of this module.
    fn generate_instance(&self, instance_name: &str) -> String;
    /// Return the list of ports for wiring.
    fn get_ports(&self) -> Vec<PortInfo>;
}

// ---------------------------------------------------------------------------
// Select type for muxes
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
pub enum MuxSelectType {
    Binary,
    OneHot,
    Priority,
}

// ---------------------------------------------------------------------------
// MuxGenerator
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct MuxGenerator {
    pub name: String,
    pub num_inputs: u32,
    pub data_width: u32,
    pub select_type: MuxSelectType,
    pub has_default: bool,
}

impl MuxGenerator {
    pub fn new(
        name: String,
        num_inputs: u32,
        data_width: u32,
        select_type: MuxSelectType,
        has_default: bool,
    ) -> Self {
        Self {
            name,
            num_inputs,
            data_width,
            select_type,
            has_default,
        }
    }

    fn select_width(&self) -> u32 {
        if self.num_inputs > 1 {
            bit_length(self.num_inputs - 1)
        } else {
            1
        }
    }

    fn generate_binary_mux(&self) -> String {
        let sw = self.select_width();
        let dw = self.data_width;
        let ni = self.num_inputs;

        let mut v = format!("module {}(\n", self.name);

        for i in 0..ni {
            v += &format!("    input wire [{}:0] in_{},\n", dw - 1, i);
        }
        v += &format!("    input wire [{}:0] sel,\n", sw - 1);
        v += &format!("    output logic [{}:0] out\n", dw - 1);
        v += ");\n\n";

        v += "    always_comb begin\n";
        v += "        case (sel)\n";
        for i in 0..ni {
            v += &format!("            {}'d{}: out = in_{};\n", sw, i, i);
        }
        v += &format!("            default: out = {}'d0;\n", dw);
        v += "        endcase\n";
        v += "    end\n\n";
        v += "endmodule\n";
        v
    }

    fn generate_one_hot_mux(&self) -> String {
        let dw = self.data_width;
        let ni = self.num_inputs;

        let mut v = format!("module {}(\n", self.name);

        for i in 0..ni {
            v += &format!("    input wire [{}:0] in_{},\n", dw - 1, i);
        }
        for i in 0..ni {
            v += &format!("    input wire sel_{},\n", i);
        }
        // Strip trailing ",\n" from last sel and re-add with comma before output
        v = v.trim_end_matches(",\n").to_string();
        v += ",\n";
        v += &format!("    output logic [{}:0] out\n", dw - 1);
        v += ");\n\n";

        v += "    always_comb begin\n";
        v += "        out = ";
        let terms: Vec<String> = (0..ni)
            .map(|i| format!("(sel_{} ? in_{} : {}'d0)", i, i, dw))
            .collect();
        v += &terms.join(" | ");
        v += ";\n";
        v += "    end\n\n";
        v += "endmodule\n";
        v
    }

    fn generate_priority_mux(&self) -> String {
        let dw = self.data_width;
        let ni = self.num_inputs;

        let mut v = format!("module {}(\n", self.name);

        for i in 0..ni {
            v += &format!("    input wire [{}:0] in_{},\n", dw - 1, i);
        }
        for i in 0..ni {
            v += &format!("    input wire sel_{},\n", i);
        }
        if self.has_default {
            v += &format!("    input wire [{}:0] default_in,\n", dw - 1);
        }
        v = v.trim_end_matches(",\n").to_string();
        v += ",\n";
        v += &format!("    output logic [{}:0] out\n", dw - 1);
        v += ");\n\n";

        v += "    always_comb begin\n";

        if ni == 0 {
            if self.has_default {
                v += "        out = default_in;\n";
            } else {
                v += &format!("        out = {}'d0;\n", dw);
            }
        } else {
            for i in 0..ni {
                if i == 0 {
                    v += &format!("        if (sel_{}) begin\n", i);
                } else {
                    v += &format!("        end else if (sel_{}) begin\n", i);
                }
                v += &format!("            out = in_{};\n", i);
            }
            v += "        end else begin\n";
            if self.has_default {
                v += "            out = default_in;\n";
            } else {
                v += &format!("            out = {}'d0;\n", dw);
            }
            v += "        end\n";
        }

        v += "    end\n\n";
        v += "endmodule\n";
        v
    }

    /// Generate instantiation with port connections.
    pub fn get_port_connections(
        &self,
        input_signals: &[String],
        select_signal: &SelectSignal,
        output_signal: &str,
        default_signal: Option<&str>,
    ) -> String {
        let mut connections = Vec::new();

        for (i, sig) in input_signals.iter().enumerate() {
            connections.push(format!("    .in_{}({})", i, sig));
        }

        match &self.select_type {
            MuxSelectType::OneHot | MuxSelectType::Priority => match select_signal {
                SelectSignal::Individual(sels) => {
                    for (i, sel_sig) in sels.iter().enumerate() {
                        connections.push(format!("    .sel_{}({})", i, sel_sig));
                    }
                }
                SelectSignal::Vector(sig) => {
                    for i in 0..self.num_inputs {
                        connections.push(format!("    .sel_{}({}[{}])", i, sig, i));
                    }
                }
            },
            MuxSelectType::Binary => {
                let sig = match select_signal {
                    SelectSignal::Vector(s) => s.as_str(),
                    SelectSignal::Individual(v) => {
                        if v.is_empty() {
                            "sel"
                        } else {
                            v[0].as_str()
                        }
                    }
                };
                connections.push(format!("    .sel({})", sig));
            }
        }

        if self.select_type == MuxSelectType::Priority && self.has_default {
            if let Some(def) = default_signal {
                connections.push(format!("    .default_in({})", def));
            }
        }

        connections.push(format!("    .out({})", output_signal));

        format!(
            "{} {}_inst(\n{}\n);",
            self.name,
            self.name,
            connections.join(",\n")
        )
    }
}

/// Select signal can be either a single vector name or individual signal names.
#[derive(Debug, Clone)]
pub enum SelectSignal {
    Vector(String),
    Individual(Vec<String>),
}

impl ModuleGenerator for MuxGenerator {
    fn generate_module(&self) -> String {
        match self.select_type {
            MuxSelectType::OneHot => self.generate_one_hot_mux(),
            MuxSelectType::Priority => self.generate_priority_mux(),
            MuxSelectType::Binary => self.generate_binary_mux(),
        }
    }

    fn generate_instance(&self, instance_name: &str) -> String {
        let mut connections = Vec::new();

        for i in 0..self.num_inputs {
            connections.push(format!("    .in_{}(in_{})", i, i));
        }

        match self.select_type {
            MuxSelectType::Binary => {
                connections.push("    .sel(sel)".to_string());
            }
            MuxSelectType::OneHot | MuxSelectType::Priority => {
                for i in 0..self.num_inputs {
                    connections.push(format!("    .sel_{}(sel_{})", i, i));
                }
                if self.select_type == MuxSelectType::Priority && self.has_default {
                    connections.push("    .default_in(default_in)".to_string());
                }
            }
        }

        connections.push("    .out(out)".to_string());

        format!(
            "{} {}(\n{}\n);",
            self.name,
            instance_name,
            connections.join(",\n")
        )
    }

    fn get_ports(&self) -> Vec<PortInfo> {
        let mut ports = Vec::new();
        let dw = self.data_width;

        for i in 0..self.num_inputs {
            ports.push(PortInfo {
                name: format!("in_{}", i),
                direction: PortDirection::Input,
                width: dw,
            });
        }

        match self.select_type {
            MuxSelectType::Binary => {
                ports.push(PortInfo {
                    name: "sel".to_string(),
                    direction: PortDirection::Input,
                    width: self.select_width(),
                });
            }
            MuxSelectType::OneHot | MuxSelectType::Priority => {
                for i in 0..self.num_inputs {
                    ports.push(PortInfo {
                        name: format!("sel_{}", i),
                        direction: PortDirection::Input,
                        width: 1,
                    });
                }
                if self.select_type == MuxSelectType::Priority && self.has_default {
                    ports.push(PortInfo {
                        name: "default_in".to_string(),
                        direction: PortDirection::Input,
                        width: dw,
                    });
                }
            }
        }

        ports.push(PortInfo {
            name: "out".to_string(),
            direction: PortDirection::Output,
            width: dw,
        });

        ports
    }
}

// ---------------------------------------------------------------------------
// CountDirection
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
pub enum CountDirection {
    Up,
    Down,
}

// ---------------------------------------------------------------------------
// CounterGenerator
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct CounterGenerator {
    pub name: String,
    pub width: u32,
    pub max_value: Option<u32>,
    pub has_enable: bool,
    pub has_reset_value: bool,
    pub count_direction: CountDirection,
}

impl CounterGenerator {
    pub fn new(
        name: String,
        width: u32,
        max_value: Option<u32>,
        has_enable: bool,
        has_reset_value: bool,
        count_direction: CountDirection,
    ) -> Self {
        Self {
            name,
            width,
            max_value,
            has_enable,
            has_reset_value,
            count_direction,
        }
    }

    pub fn get_port_connections(
        &self,
        enable_signal: Option<&str>,
        reset_value_signal: Option<&str>,
        output_signal: &str,
    ) -> String {
        let mut connections = vec![
            "    .clk(clk)".to_string(),
            "    .reset(reset)".to_string(),
        ];

        if self.has_reset_value {
            if let Some(rv) = reset_value_signal {
                connections.push(format!("    .reset_value({})", rv));
            }
        }

        if self.has_enable {
            if let Some(en) = enable_signal {
                connections.push(format!("    .enable({})", en));
            }
        }

        connections.push(format!("    .count({})", output_signal));

        format!(
            "{} {}_inst(\n{}\n);",
            self.name,
            self.name,
            connections.join(",\n")
        )
    }
}

impl ModuleGenerator for CounterGenerator {
    fn generate_module(&self) -> String {
        let w = self.width;
        let mut v = format!("module {}(\n", self.name);
        v += "    input wire clk,\n";
        v += "    input wire reset,\n";

        if self.has_reset_value {
            v += &format!("    input wire [{}:0] reset_value,\n", w - 1);
        }
        if self.has_enable {
            v += "    input wire enable,\n";
        }
        v += &format!("    output logic [{}:0] count\n", w - 1);
        v += ");\n\n";

        v += "    always_ff @(posedge clk) begin\n";
        v += "        if (reset) begin\n";
        if self.has_reset_value {
            v += "            count <= reset_value;\n";
        } else {
            v += &format!("            count <= {}'d0;\n", w);
        }
        v += "        end";

        if self.has_enable {
            v += " else if (enable) begin\n";
        } else {
            v += " else begin\n";
        }

        match (&self.max_value, &self.count_direction) {
            (Some(max_val), CountDirection::Up) => {
                v += &format!(
                    "            if (count >= {}'d{}) begin\n",
                    w, max_val
                );
                v += &format!("                count <= {}'d0;\n", w);
                v += "            end else begin\n";
                v += "                count <= count + 1;\n";
                v += "            end\n";
            }
            (Some(max_val), CountDirection::Down) => {
                v += &format!("            if (count == {}'d0) begin\n", w);
                v += &format!("                count <= {}'d{};\n", w, max_val);
                v += "            end else begin\n";
                v += "                count <= count - 1;\n";
                v += "            end\n";
            }
            (None, CountDirection::Up) => {
                v += "            count <= count + 1;\n";
            }
            (None, CountDirection::Down) => {
                v += "            count <= count - 1;\n";
            }
        }

        v += "        end\n";
        v += "    end\n\n";
        v += "endmodule\n";
        v
    }

    fn generate_instance(&self, instance_name: &str) -> String {
        let mut connections = vec![
            "    .clk(clk)".to_string(),
            "    .reset(reset)".to_string(),
        ];
        if self.has_reset_value {
            connections.push("    .reset_value(reset_value)".to_string());
        }
        if self.has_enable {
            connections.push("    .enable(enable)".to_string());
        }
        connections.push("    .count(count)".to_string());

        format!(
            "{} {}(\n{}\n);",
            self.name,
            instance_name,
            connections.join(",\n")
        )
    }

    fn get_ports(&self) -> Vec<PortInfo> {
        let mut ports = vec![
            PortInfo {
                name: "clk".to_string(),
                direction: PortDirection::Input,
                width: 1,
            },
            PortInfo {
                name: "reset".to_string(),
                direction: PortDirection::Input,
                width: 1,
            },
        ];
        if self.has_reset_value {
            ports.push(PortInfo {
                name: "reset_value".to_string(),
                direction: PortDirection::Input,
                width: self.width,
            });
        }
        if self.has_enable {
            ports.push(PortInfo {
                name: "enable".to_string(),
                direction: PortDirection::Input,
                width: 1,
            });
        }
        ports.push(PortInfo {
            name: "count".to_string(),
            direction: PortDirection::Output,
            width: self.width,
        });
        ports
    }
}

// ---------------------------------------------------------------------------
// LatencyMode
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum LatencyMode {
    Static,
    Variable,
}

// ---------------------------------------------------------------------------
// LatencyCounterGenerator
// ---------------------------------------------------------------------------

/// Result of generate_inline_logic: declarations, combinational logic, sequential logic.
#[derive(Debug, Clone, Default)]
pub struct InlineLogic {
    pub declarations: String,
    pub comb_logic: String,
    pub seq_logic: String,
}

#[derive(Debug, Clone)]
pub struct LatencyCounterGenerator {
    pub name: String,
    pub width: u32,
    pub latency_mode: LatencyMode,
    pub static_latency: u32,
    pub min_latency: u32,
    pub max_latency: u32,
}

impl LatencyCounterGenerator {
    pub fn new(
        name: String,
        width: u32,
        latency_mode: LatencyMode,
        static_latency: u32,
        min_latency: u32,
        max_latency: u32,
    ) -> Self {
        Self {
            name,
            width,
            latency_mode,
            static_latency,
            min_latency,
            max_latency,
        }
    }

    /// Generate inline Verilog logic (not a separate module).
    pub fn generate_inline_logic(
        &self,
        counter_reg: &str,
        target_reg: Option<&str>,
        start_expr: &str,
        complete_name: &str,
        idle_name: Option<&str>,
    ) -> InlineLogic {
        let mut result = InlineLogic::default();
        let w = self.width;

        if self.latency_mode == LatencyMode::Variable {
            let target_reg = target_reg.unwrap_or("latency_target");
            let latency_range = self.max_latency - self.min_latency;

            result.declarations += &format!(
                "    reg [{}:0] {};  // Latency counter\n",
                w - 1,
                counter_reg
            );
            result.declarations += &format!(
                "    reg [{}:0] {};   // Random target ({}-{})\n",
                w - 1,
                target_reg,
                self.min_latency,
                self.max_latency
            );

            result.comb_logic += &format!(
                "    assign {} = ({} != {}'d0) && ({} == {});\n",
                complete_name, counter_reg, w, counter_reg, target_reg
            );
            if let Some(idle) = idle_name {
                result.comb_logic += &format!(
                    "    assign {} = ({} == {}'d0);\n",
                    idle, counter_reg, w
                );
            }

            result.seq_logic += &format!(
                "    // Latency counter FSM (random {}-{} cycles)\n",
                self.min_latency, self.max_latency
            );
            result.seq_logic += "    always @(posedge clk) begin\n";
            result.seq_logic += "        if (reset) begin\n";
            result.seq_logic += &format!("            {} <= {}'d0;\n", counter_reg, w);
            result.seq_logic += &format!(
                "            {} <= {}'d{};\n",
                target_reg, w, self.min_latency
            );
            result.seq_logic += "        end else begin\n";
            result.seq_logic += &format!(
                "            if ({} == {}'d0) begin\n",
                counter_reg, w
            );
            result.seq_logic += &format!("                if ({}) begin\n", start_expr);
            result.seq_logic += &format!(
                "                    {} <= {}'d1;\n",
                counter_reg, w
            );
            result.seq_logic += &format!(
                "                    {} <= ({}'d{}) + ($random & {}'d{});\n",
                target_reg, w, self.min_latency, w, latency_range
            );
            result.seq_logic += "                end\n";
            result.seq_logic += &format!(
                "            end else if ({} == {}) begin\n",
                counter_reg, target_reg
            );
            result.seq_logic += &format!("                {} <= {}'d0;\n", counter_reg, w);
            result.seq_logic += "            end else begin\n";
            result.seq_logic += &format!(
                "                {} <= {} + {}'d1;\n",
                counter_reg, counter_reg, w
            );
            result.seq_logic += "            end\n";
            result.seq_logic += "        end\n";
            result.seq_logic += "    end\n";
        } else {
            // Static latency
            if self.static_latency == 0 {
                let counter_bits: u32 = 2;
                result.declarations += &format!(
                    "    reg [{}:0] {};  // Latency counter (always complete for latency-0)\n",
                    counter_bits - 1,
                    counter_reg
                );

                result.comb_logic += &format!(
                    "    assign {} = 1'b1;  // Latency 0: always complete (no stall)\n",
                    complete_name
                );
                if let Some(idle) = idle_name {
                    result.comb_logic += &format!(
                        "    assign {} = 1'b1;  // Latency 0: always idle\n",
                        idle
                    );
                }

                result.seq_logic += "    // Latency counter FSM (latency 0) - no stall needed\n";
                result.seq_logic += "    always @(posedge clk) begin\n";
                result.seq_logic += "        if (reset) begin\n";
                result.seq_logic += &format!(
                    "            {} <= {}'d0;\n",
                    counter_reg, counter_bits
                );
                result.seq_logic += "        end\n";
                result.seq_logic += "    end\n";
            } else {
                let counter_bits = std::cmp::max(
                    2,
                    ceil_log2(self.static_latency + 1),
                );

                result.declarations += &format!(
                    "    reg [{}:0] {};  // Latency counter (0=idle, {}=complete)\n",
                    counter_bits - 1,
                    counter_reg,
                    self.static_latency
                );

                result.comb_logic += &format!(
                    "    assign {} = ({} == {}'d{});\n",
                    complete_name, counter_reg, counter_bits, self.static_latency
                );
                if let Some(idle) = idle_name {
                    result.comb_logic += &format!(
                        "    assign {} = ({} == {}'d0);\n",
                        idle, counter_reg, counter_bits
                    );
                }

                result.seq_logic += &format!(
                    "    // Latency counter FSM ({}-cycle stall)\n",
                    self.static_latency
                );
                result.seq_logic += "    always @(posedge clk) begin\n";
                result.seq_logic += "        if (reset) begin\n";
                result.seq_logic += &format!(
                    "            {} <= {}'d0;\n",
                    counter_reg, counter_bits
                );
                result.seq_logic += "        end else begin\n";
                result.seq_logic += &format!(
                    "            if ({} == {}'d0) begin\n",
                    counter_reg, counter_bits
                );
                result.seq_logic += &format!("                if ({}) begin\n", start_expr);
                result.seq_logic += &format!(
                    "                    {} <= {}'d1;\n",
                    counter_reg, counter_bits
                );
                result.seq_logic += "                end\n";
                result.seq_logic += &format!(
                    "            end else if ({} == {}'d{}) begin\n",
                    counter_reg, counter_bits, self.static_latency
                );
                result.seq_logic += &format!(
                    "                {} <= {}'d0;\n",
                    counter_reg, counter_bits
                );
                result.seq_logic += "            end else begin\n";
                result.seq_logic += &format!(
                    "                {} <= {} + {}'d1;\n",
                    counter_reg, counter_reg, counter_bits
                );
                result.seq_logic += "            end\n";
                result.seq_logic += "        end\n";
                result.seq_logic += "    end\n";
            }
        }

        result
    }
}

// The LatencyCounterGenerator produces inline logic rather than a module,
// so the trait methods produce placeholder wrappers.
impl ModuleGenerator for LatencyCounterGenerator {
    fn generate_module(&self) -> String {
        // Wrap inline logic in a module for standalone use.
        let il = self.generate_inline_logic(
            "counter",
            Some("target"),
            "start",
            "complete",
            Some("idle"),
        );
        let mut v = format!("module {}(\n", self.name);
        v += "    input wire clk,\n";
        v += "    input wire reset,\n";
        v += "    input wire start,\n";
        v += "    output wire complete,\n";
        v += "    output wire idle\n";
        v += ");\n\n";
        v += &il.declarations;
        v += "\n";
        v += &il.comb_logic;
        v += "\n";
        v += &il.seq_logic;
        v += "\nendmodule\n";
        v
    }

    fn generate_instance(&self, instance_name: &str) -> String {
        format!(
            "{} {}(\n    .clk(clk),\n    .reset(reset),\n    .start(start),\n    .complete(complete),\n    .idle(idle)\n);",
            self.name, instance_name
        )
    }

    fn get_ports(&self) -> Vec<PortInfo> {
        vec![
            PortInfo { name: "clk".to_string(), direction: PortDirection::Input, width: 1 },
            PortInfo { name: "reset".to_string(), direction: PortDirection::Input, width: 1 },
            PortInfo { name: "start".to_string(), direction: PortDirection::Input, width: 1 },
            PortInfo { name: "complete".to_string(), direction: PortDirection::Output, width: 1 },
            PortInfo { name: "idle".to_string(), direction: PortDirection::Output, width: 1 },
        ]
    }
}

// ---------------------------------------------------------------------------
// ALUGenerator (stub — advanced, not needed for RV32I single-cycle)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct ALUGenerator {
    pub name: String,
    pub input_width: u32,
    pub output_width: u32,
    pub operations: HashMap<String, AluOperation>,
}

#[derive(Debug, Clone)]
pub struct AluOperation {
    pub opcode: u32,
    pub description: String,
}

impl ALUGenerator {
    pub fn new(name: String, input_width: u32, output_width: u32) -> Self {
        let mut operations = HashMap::new();
        let defaults = [
            ("+", 0, "ADD"),
            ("-", 1, "SUB"),
            ("&", 2, "AND"),
            ("|", 3, "OR"),
            ("^", 4, "XOR"),
            ("<<", 5, "SLL"),
            (">>", 6, "SRL"),
            (">>>", 7, "SRA"),
        ];
        for (op, code, desc) in &defaults {
            operations.insert(
                op.to_string(),
                AluOperation {
                    opcode: *code,
                    description: desc.to_string(),
                },
            );
        }
        Self {
            name,
            input_width,
            output_width,
            operations,
        }
    }

    fn operator_to_verilog(op: &str) -> &str {
        match op {
            "+" => "+",
            "-" => "-",
            "&" => "&",
            "|" => "|",
            "^" => "^",
            "<<" => "<<",
            ">>" => ">>",
            ">>>" => ">>>",
            "*" => "*",
            "/" => "/",
            "%" => "%",
            "==" => "==",
            "!=" => "!=",
            "<" => "<",
            ">" => ">",
            "<=" => "<=",
            ">=" => ">=",
            other => other,
        }
    }
}

impl ModuleGenerator for ALUGenerator {
    fn generate_module(&self) -> String {
        let opcode_width = if self.operations.len() > 1 {
            bit_length(self.operations.len() as u32 - 1)
        } else {
            1
        };
        let iw = self.input_width;
        let ow = self.output_width;

        let mut v = format!("module {}(\n", self.name);
        v += &format!("    input wire [{}:0] operand_a,\n", iw - 1);
        v += &format!("    input wire [{}:0] operand_b,\n", iw - 1);
        v += &format!("    input wire [{}:0] opcode,\n", opcode_width - 1);
        v += &format!("    output logic [{}:0] result,\n", ow - 1);
        v += "    output wire zero_flag,\n";
        v += "    output wire negative_flag,\n";
        v += "    output wire overflow_flag\n";
        v += ");\n\n";

        v += "    always_comb begin\n";
        v += "        case (opcode)\n";

        // Sort operations by opcode for deterministic output
        let mut ops: Vec<_> = self.operations.iter().collect();
        ops.sort_by_key(|(_, op)| op.opcode);

        for (operator, op_info) in &ops {
            let verilog_op = Self::operator_to_verilog(operator);
            v += &format!(
                "            {}'d{}: result = operand_a {} operand_b; // {}\n",
                opcode_width, op_info.opcode, verilog_op, op_info.description
            );
        }

        v += &format!("            default: result = {}'d0;\n", ow);
        v += "        endcase\n";
        v += "    end\n\n";

        v += "    assign zero_flag = (result == 0);\n";
        v += &format!(
            "    assign negative_flag = result[{}];\n",
            ow - 1
        );
        v += "    assign overflow_flag = 1'b0; // Simplified - would need proper overflow detection\n\n";
        v += "endmodule\n";
        v
    }

    fn generate_instance(&self, instance_name: &str) -> String {
        format!(
            "{} {}(\n    .operand_a(operand_a),\n    .operand_b(operand_b),\n    .opcode(opcode),\n    .result(result),\n    .zero_flag(zero_flag),\n    .negative_flag(negative_flag),\n    .overflow_flag(overflow_flag)\n);",
            self.name, instance_name
        )
    }

    fn get_ports(&self) -> Vec<PortInfo> {
        let opcode_width = if self.operations.len() > 1 {
            bit_length(self.operations.len() as u32 - 1)
        } else {
            1
        };
        vec![
            PortInfo { name: "operand_a".to_string(), direction: PortDirection::Input, width: self.input_width },
            PortInfo { name: "operand_b".to_string(), direction: PortDirection::Input, width: self.input_width },
            PortInfo { name: "opcode".to_string(), direction: PortDirection::Input, width: opcode_width },
            PortInfo { name: "result".to_string(), direction: PortDirection::Output, width: self.output_width },
            PortInfo { name: "zero_flag".to_string(), direction: PortDirection::Output, width: 1 },
            PortInfo { name: "negative_flag".to_string(), direction: PortDirection::Output, width: 1 },
            PortInfo { name: "overflow_flag".to_string(), direction: PortDirection::Output, width: 1 },
        ]
    }
}

// ---------------------------------------------------------------------------
// HazardDetectorGenerator (stub)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct HazardDetectorGenerator {
    pub name: String,
    pub num_sources: u32,
    pub num_destinations: u32,
    pub address_width: u32,
}

impl HazardDetectorGenerator {
    pub fn new(name: String, num_sources: u32, num_destinations: u32, address_width: u32) -> Self {
        Self { name, num_sources, num_destinations, address_width }
    }
}

impl ModuleGenerator for HazardDetectorGenerator {
    fn generate_module(&self) -> String {
        let aw = self.address_width;
        let ns = self.num_sources;
        let nd = self.num_destinations;

        let mut v = format!("module {}(\n", self.name);

        for i in 0..ns {
            v += &format!("    input wire [{}:0] src_{}_addr,\n", aw - 1, i);
            v += &format!("    input wire src_{}_valid,\n", i);
        }
        for i in 0..nd {
            v += &format!("    input wire [{}:0] dest_{}_addr,\n", aw - 1, i);
            v += &format!("    input wire dest_{}_valid,\n", i);
            v += &format!("    input wire dest_{}_ready,\n", i);
        }

        v += "    output logic stall,\n";
        v += "    output logic flush,\n";

        for i in 0..ns {
            v += &format!("    output logic [{}:0] forward_src_{}", nd - 1, i);
            if i < ns - 1 {
                v += ",";
            }
            v += "\n";
        }

        v += ");\n\n";

        v += "    always_comb begin\n";
        v += "        stall = 1'b0;\n";
        v += "        flush = 1'b0;\n";
        for i in 0..ns {
            v += &format!("        forward_src_{} = {}'d0;\n", i, nd);
        }
        v += "\n";

        for src_idx in 0..ns {
            v += &format!("        // Check source {} for hazards\n", src_idx);
            v += &format!("        if (src_{}_valid) begin\n", src_idx);
            for dest_idx in 0..nd {
                v += &format!(
                    "            if (dest_{}_valid && (src_{}_addr == dest_{}_addr)) begin\n",
                    dest_idx, src_idx, dest_idx
                );
                v += &format!("                if (dest_{}_ready) begin\n", dest_idx);
                v += &format!(
                    "                    // Forward from destination {}\n",
                    dest_idx
                );
                v += &format!(
                    "                    forward_src_{}[{}] = 1'b1;\n",
                    src_idx, dest_idx
                );
                v += "                end else begin\n";
                v += "                    // Data not ready - stall pipeline\n";
                v += "                    stall = 1'b1;\n";
                v += "                end\n";
                v += "            end\n";
            }
            v += "        end\n\n";
        }

        v += "    end\n\n";
        v += "endmodule\n";
        v
    }

    fn generate_instance(&self, instance_name: &str) -> String {
        format!("{} {}(\n    // ports omitted - use get_port_connections\n);", self.name, instance_name)
    }

    fn get_ports(&self) -> Vec<PortInfo> {
        let mut ports = Vec::new();
        for i in 0..self.num_sources {
            ports.push(PortInfo { name: format!("src_{}_addr", i), direction: PortDirection::Input, width: self.address_width });
            ports.push(PortInfo { name: format!("src_{}_valid", i), direction: PortDirection::Input, width: 1 });
        }
        for i in 0..self.num_destinations {
            ports.push(PortInfo { name: format!("dest_{}_addr", i), direction: PortDirection::Input, width: self.address_width });
            ports.push(PortInfo { name: format!("dest_{}_valid", i), direction: PortDirection::Input, width: 1 });
            ports.push(PortInfo { name: format!("dest_{}_ready", i), direction: PortDirection::Input, width: 1 });
        }
        ports.push(PortInfo { name: "stall".to_string(), direction: PortDirection::Output, width: 1 });
        ports.push(PortInfo { name: "flush".to_string(), direction: PortDirection::Output, width: 1 });
        for i in 0..self.num_sources {
            ports.push(PortInfo { name: format!("forward_src_{}", i), direction: PortDirection::Output, width: self.num_destinations });
        }
        ports
    }
}

// ---------------------------------------------------------------------------
// Stub generators for advanced hardware (cache, TLB, ibuf, BTB, renamer)
// These produce placeholder modules; full implementations can be added later.
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct ReadOnlyCacheGenerator {
    pub name: String,
    pub num_read_ports: u32,
    pub block_size: u32,
    pub associativity: u32,
    pub num_rows: u32,
    pub address_width: u32,
    pub data_width: u32,
    pub replacement_policy: String,
    pub has_flush: bool,
}

impl ReadOnlyCacheGenerator {
    fn offset_width(&self) -> u32 {
        if self.block_size <= 1 { 0 } else { (self.block_size - 1).next_power_of_two().trailing_zeros().max(1) }
    }
    fn index_width(&self) -> u32 {
        if self.num_rows <= 1 { 1 } else { (self.num_rows as f64).log2().ceil() as u32 }
    }
    fn tag_width(&self) -> u32 {
        self.address_width - self.offset_width() - self.index_width()
    }
    fn words_per_line(&self) -> u32 {
        self.block_size * 8 / self.data_width
    }

    fn generate_module_header(&self) -> String {
        let mut v = format!("module {} #(\n", self.name);
        v += &format!("    parameter BLOCK_SIZE = {},\n", self.block_size);
        v += &format!("    parameter ASSOCIATIVITY = {},\n", self.associativity);
        v += &format!("    parameter NUM_ROWS = {},\n", self.num_rows);
        v += &format!("    parameter ADDR_WIDTH = {},\n", self.address_width);
        v += &format!("    parameter DATA_WIDTH = {}\n", self.data_width);
        v += ")(\n";
        v += "    input  wire clk,\n";
        v += "    input  wire reset,\n";
        for i in 0..self.num_read_ports {
            v += &format!("\n    // Read port {}\n", i);
            v += &format!("    input  wire [ADDR_WIDTH-1:0] read_addr_{},\n", i);
            v += &format!("    input  wire read_req_{},\n", i);
            v += &format!("    output reg [DATA_WIDTH-1:0] read_data_{},\n", i);
            v += &format!("    output reg read_valid_{},\n", i);
        }
        if self.has_flush {
            v += "\n    // Flush control (invalidates all cache entries)\n";
            v += "    input  wire flush,\n";
        }
        v += "\n    // Refill interface to backing memory\n";
        v += "    output reg [ADDR_WIDTH-1:0] refill_addr,\n";
        v += "    output reg refill_req,\n";
        v += "    input  wire [DATA_WIDTH-1:0] refill_data,\n";
        v += "    input  wire refill_valid\n";
        v += ");\n\n";
        v
    }

    fn generate_parameters(&self) -> String {
        let wpl = self.words_per_line();
        let word_offset_width = if wpl > 1 { ceil_log2(wpl as u32) } else { 1 };
        let mut v = "    // Derived parameters\n".to_string();
        v += &format!("    localparam OFFSET_WIDTH = {};\n", self.offset_width());
        v += &format!("    localparam INDEX_WIDTH = {};\n", self.index_width());
        v += "    localparam TAG_WIDTH = ADDR_WIDTH - OFFSET_WIDTH - INDEX_WIDTH;\n";
        v += &format!("    localparam WORDS_PER_LINE = {};\n", wpl);
        v += &format!("    localparam WORD_OFFSET_WIDTH = {};\n\n", word_offset_width);
        v
    }

    fn generate_storage_arrays(&self) -> String {
        let mut v = "    // Storage arrays\n".to_string();
        if self.associativity == 1 {
            v += "    reg [TAG_WIDTH-1:0] tag_array [0:NUM_ROWS-1];\n";
            v += "    reg valid_array [0:NUM_ROWS-1];\n";
            v += "    reg [DATA_WIDTH*WORDS_PER_LINE-1:0] data_array [0:NUM_ROWS-1];\n";
        } else {
            v += "    reg [TAG_WIDTH-1:0] tag_array [0:NUM_ROWS-1][0:ASSOCIATIVITY-1];\n";
            v += "    reg valid_array [0:NUM_ROWS-1][0:ASSOCIATIVITY-1];\n";
            v += "    reg [DATA_WIDTH*WORDS_PER_LINE-1:0] data_array [0:NUM_ROWS-1][0:ASSOCIATIVITY-1];\n";
            if self.replacement_policy == "lru" {
                let lru_width = self.associativity - 1;
                v += &format!("    reg [{}:0] lru_array [0:NUM_ROWS-1];\n", lru_width);
            }
        }
        v += "\n";
        v
    }

    fn generate_address_decoding(&self) -> String {
        let mut v = "    // Address decoding\n".to_string();
        for i in 0..self.num_read_ports {
            v += &format!("    wire [TAG_WIDTH-1:0] tag_{i} = read_addr_{i}[ADDR_WIDTH-1:ADDR_WIDTH-TAG_WIDTH];\n");
            v += &format!("    wire [INDEX_WIDTH-1:0] index_{i} = read_addr_{i}[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH];\n");
            if self.words_per_line() > 1 {
                v += &format!("    wire [WORD_OFFSET_WIDTH-1:0] word_offset_{i} = read_addr_{i}[OFFSET_WIDTH-1:OFFSET_WIDTH-WORD_OFFSET_WIDTH];\n");
            }
            v += "\n";
        }
        v
    }

    fn generate_hit_logic(&self) -> String {
        let mut v = "    // Hit detection\n".to_string();
        for i in 0..self.num_read_ports {
            if self.associativity == 1 {
                v += &format!("    wire hit_{i} = valid_array[index_{i}] && (tag_array[index_{i}] == tag_{i});\n");
            } else {
                v += &format!("    wire [{}:0] way_hit_{i};\n", self.associativity - 1);
                for way in 0..self.associativity {
                    v += &format!("    assign way_hit_{i}[{way}] = valid_array[index_{i}][{way}] && (tag_array[index_{i}][{way}] == tag_{i});\n");
                }
                v += &format!("    wire hit_{i} = |way_hit_{i};\n");
                let way_bits = ((self.associativity - 1) as f64).log2().ceil() as u32 + 1;
                v += &format!("    reg [{wb}:0] hit_way_{i};\n", wb = way_bits - 1);
                v += &format!("    always @* begin\n");
                v += &format!("        hit_way_{i} = 0;\n");
                for way in 0..self.associativity {
                    v += &format!("        if (way_hit_{i}[{way}]) hit_way_{i} = {way};\n");
                }
                v += "    end\n";
            }
            v += "\n";
        }
        v
    }

    fn generate_read_logic(&self) -> String {
        let mut v = "    // Read data selection\n".to_string();
        for i in 0..self.num_read_ports {
            v += &format!("    always @* begin\n");
            v += &format!("        read_valid_{i} = read_req_{i} && hit_{i};\n");
            if self.associativity == 1 {
                if self.words_per_line() > 1 {
                    v += &format!("        read_data_{i} = data_array[index_{i}][word_offset_{i}*DATA_WIDTH +: DATA_WIDTH];\n");
                } else {
                    v += &format!("        read_data_{i} = data_array[index_{i}];\n");
                }
            } else {
                if self.words_per_line() > 1 {
                    v += &format!("        read_data_{i} = data_array[index_{i}][hit_way_{i}][word_offset_{i}*DATA_WIDTH +: DATA_WIDTH];\n");
                } else {
                    v += &format!("        read_data_{i} = data_array[index_{i}][hit_way_{i}];\n");
                }
            }
            v += "    end\n\n";
        }
        v
    }

    fn generate_refill_fsm(&self) -> String {
        let wpl = self.words_per_line();
        let mut v = "    // Refill FSM states (using localparam for iverilog compatibility)\n".to_string();
        v += "    localparam IDLE = 2'b00;\n";
        v += "    localparam REFILL = 2'b01;\n";
        v += "    localparam UPDATE = 2'b10;\n\n";
        v += "    reg [1:0] state, next_state;\n";
        v += "    reg [ADDR_WIDTH-1:0] miss_addr;\n";
        v += "    reg [INDEX_WIDTH-1:0] refill_index;\n";
        v += "    reg [TAG_WIDTH-1:0] refill_tag;\n";
        if wpl > 1 {
            let word_cnt_bits = ((wpl - 1) as f64).log2().ceil() as u32;
            let word_cnt_bits = word_cnt_bits.max(1);
            v += &format!("    reg [{}:0] refill_word_cnt;\n", word_cnt_bits - 1);
            v += "    reg [DATA_WIDTH*WORDS_PER_LINE-1:0] refill_line_data;\n";
        }
        if self.associativity > 1 {
            let way_bits = ((self.associativity - 1) as f64).log2().ceil() as u32 + 1;
            v += &format!("    reg [{}:0] refill_way;\n", way_bits - 1);
        }
        // Warming register: blocks refill acceptance on first REFILL cycle
        // to allow the pipeline register for refill_addr to capture the correct address.
        // Without this, a coinciding memory completion can cause stale data acceptance.
        v += "    reg refill_warming;\n";
        v += "\n";

        // Miss detection
        v += "    // Miss detection\n";
        v += "    wire miss = ";
        let miss_conds: Vec<String> = (0..self.num_read_ports).map(|i| format!("(read_req_{i} && !hit_{i})")).collect();
        v += &miss_conds.join(" || ");
        v += ";\n";

        v += "    reg [ADDR_WIDTH-1:0] miss_addr_comb;\n";
        v += "    always @* begin\n";
        v += "        miss_addr_comb = read_addr_0;\n";
        for i in 0..self.num_read_ports {
            v += &format!("        if (read_req_{i} && !hit_{i}) miss_addr_comb = read_addr_{i};\n");
        }
        v += "    end\n\n";

        // FSM state register
        v += "    // FSM state register\n";
        v += "    always @(posedge clk) begin\n";
        v += "        if (reset) begin\n";
        v += "            state <= IDLE;\n";
        v += "            miss_addr <= 0;\n";
        v += "            refill_index <= 0;\n";
        v += "            refill_tag <= 0;\n";
        if wpl > 1 {
            v += "            refill_word_cnt <= 0;\n";
            v += "            refill_line_data <= 0;\n";
        }
        v += "            refill_warming <= 0;\n";
        v += "        end else begin\n";
        v += "            state <= next_state;\n";
        v += "            if (state == IDLE && miss) begin\n";
        v += "                miss_addr <= miss_addr_comb;\n";
        v += "                refill_index <= miss_addr_comb[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH];\n";
        v += "                refill_tag <= miss_addr_comb[ADDR_WIDTH-1:ADDR_WIDTH-TAG_WIDTH];\n";
        v += "            end\n";
        if wpl > 1 {
            v += "            if (state == REFILL && refill_valid && !refill_warming) begin\n";
            v += "                refill_line_data[refill_word_cnt*DATA_WIDTH +: DATA_WIDTH] <= refill_data;\n";
            v += "                refill_word_cnt <= refill_word_cnt + 1;\n";
            v += "            end\n";
            v += "            if (state == UPDATE) refill_word_cnt <= 0;\n";
        }
        v += "            // Warming: set on IDLE->REFILL transition, cleared next cycle\n";
        v += "            if (state == IDLE && miss) refill_warming <= 1'b1;\n";
        v += "            else refill_warming <= 1'b0;\n";
        v += "        end\n";
        v += "    end\n\n";

        // FSM next state logic
        v += "    // FSM next state logic\n";
        v += "    always @* begin\n";
        v += "        next_state = state;\n";
        v += "        refill_req = 1'b0;\n";
        v += "        refill_addr = miss_addr;\n";
        v += "        case (state)\n";
        v += "            IDLE: begin\n";
        v += "                if (miss) next_state = REFILL;\n";
        v += "            end\n";
        v += "            REFILL: begin\n";
        v += "                refill_req = 1'b1;\n";
        if wpl > 1 {
            v += "                refill_addr = {refill_tag, refill_index, refill_word_cnt, {(OFFSET_WIDTH-WORD_OFFSET_WIDTH){1'b0}}};\n";
            v += "                if (refill_valid && !refill_warming && refill_word_cnt == WORDS_PER_LINE-1) next_state = UPDATE;\n";
        } else {
            v += "                if (refill_valid && !refill_warming) next_state = UPDATE;\n";
        }
        v += "            end\n";
        v += "            UPDATE: begin\n";
        v += "                next_state = IDLE;\n";
        v += "            end\n";
        v += "            default: next_state = IDLE;\n";
        v += "        endcase\n";
        v += "    end\n\n";

        // Cache update logic
        v += "    // Cache update on refill complete\n";
        v += "    integer init_i;\n";
        if self.associativity > 1 { v += "    integer init_j;\n"; }
        v += "    always @(posedge clk) begin\n";
        if self.has_flush {
            v += "        if (reset || flush) begin\n";
        } else {
            v += "        if (reset) begin\n";
        }
        if self.associativity == 1 {
            v += "            for (init_i = 0; init_i < NUM_ROWS; init_i = init_i + 1) begin\n";
            v += "                valid_array[init_i] <= 1'b0;\n";
            v += "            end\n";
        } else {
            v += "            for (init_i = 0; init_i < NUM_ROWS; init_i = init_i + 1) begin\n";
            v += "                for (init_j = 0; init_j < ASSOCIATIVITY; init_j = init_j + 1) begin\n";
            v += "                    valid_array[init_i][init_j] <= 1'b0;\n";
            v += "                end\n";
            v += "            end\n";
        }
        v += "        end else if (state == UPDATE) begin\n";
        if self.associativity == 1 {
            v += "            valid_array[refill_index] <= 1'b1;\n";
            v += "            tag_array[refill_index] <= refill_tag;\n";
            if wpl > 1 {
                v += "            data_array[refill_index] <= refill_line_data;\n";
            } else {
                v += "            data_array[refill_index] <= refill_data;\n";
            }
        } else {
            v += "            valid_array[refill_index][refill_way] <= 1'b1;\n";
            v += "            tag_array[refill_index][refill_way] <= refill_tag;\n";
            if wpl > 1 {
                v += "            data_array[refill_index][refill_way] <= refill_line_data;\n";
            } else {
                v += "            data_array[refill_index][refill_way] <= refill_data;\n";
            }
        }
        v += "        end\n";
        v += "    end\n\n";
        v
    }

    fn generate_replacement_logic(&self) -> String {
        if self.associativity == 1 { return String::new(); }
        let mut v = "    // Replacement policy logic\n".to_string();
        if self.replacement_policy == "lru" {
            v += "    // LRU replacement\n";
            v += "    integer lru_init_i;\n";
            v += "    always @(posedge clk) begin\n";
            v += "        if (reset) begin\n";
            v += "            for (lru_init_i = 0; lru_init_i < NUM_ROWS; lru_init_i = lru_init_i + 1) begin\n";
            v += "                lru_array[lru_init_i] <= 0;\n";
            v += "            end\n";
            v += "            refill_way <= 0;\n";
            v += "        end else begin\n";
            for i in 0..self.num_read_ports {
                v += &format!("            if (hit_{i}) begin\n");
                v += &format!("                lru_array[index_{i}] <= hit_way_{i};\n");
                v += &format!("            end\n");
            }
            v += "            if (state == IDLE && miss) begin\n";
            v += "                refill_way <= 0;\n";
            for way in 0..self.associativity {
                v += &format!("                if (!valid_array[miss_addr_comb[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH]][{way}]) refill_way <= {way};\n");
            }
            v += "                else refill_way <= lru_array[miss_addr_comb[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH]] ^ 1;\n";
            v += "            end\n";
            v += "        end\n";
            v += "    end\n\n";
        } else if self.replacement_policy == "random" {
            v += "    // Random replacement using LFSR\n";
            v += "    reg [7:0] lfsr;\n";
            v += "    always @(posedge clk) begin\n";
            v += "        if (reset) begin\n";
            v += "            lfsr <= 8'hA5;\n";
            v += "            refill_way <= 0;\n";
            v += "        end else begin\n";
            v += "            lfsr <= {lfsr[6:0], lfsr[7] ^ lfsr[5] ^ lfsr[4] ^ lfsr[3]};\n";
            v += "            if (state == IDLE && miss) begin\n";
            let way_bits = ((self.associativity - 1) as f64).log2().ceil() as u32 + 1;
            v += &format!("                refill_way <= lfsr[{}:0];\n", way_bits - 1);
            v += "            end\n";
            v += "        end\n";
            v += "    end\n\n";
        } else if self.replacement_policy == "fifo" {
            v += "    // FIFO replacement\n";
            let way_bits = ((self.associativity - 1) as f64).log2().ceil() as u32 + 1;
            v += &format!("    reg [{}:0] fifo_ptr [0:NUM_ROWS-1];\n", way_bits - 1);
            v += "    integer fifo_init_i;\n";
            v += "    always @(posedge clk) begin\n";
            v += "        if (reset) begin\n";
            v += "            for (fifo_init_i = 0; fifo_init_i < NUM_ROWS; fifo_init_i = fifo_init_i + 1) begin\n";
            v += "                fifo_ptr[fifo_init_i] <= 0;\n";
            v += "            end\n";
            v += "            refill_way <= 0;\n";
            v += "        end else begin\n";
            v += "            if (state == IDLE && miss) begin\n";
            v += "                refill_way <= fifo_ptr[miss_addr_comb[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH]];\n";
            v += "            end\n";
            v += "            if (state == UPDATE) begin\n";
            v += "                fifo_ptr[refill_index] <= (fifo_ptr[refill_index] + 1) % ASSOCIATIVITY;\n";
            v += "            end\n";
            v += "        end\n";
            v += "    end\n\n";
        }
        v
    }
}

impl ModuleGenerator for ReadOnlyCacheGenerator {
    fn generate_module(&self) -> String {
        let mut v = self.generate_module_header();
        v += &self.generate_parameters();
        v += &self.generate_storage_arrays();
        v += &self.generate_address_decoding();
        v += &self.generate_hit_logic();
        v += &self.generate_read_logic();
        v += &self.generate_refill_fsm();
        v += &self.generate_replacement_logic();
        v += "endmodule\n";
        v
    }
    fn generate_instance(&self, instance_name: &str) -> String {
        format!("{} {}();", self.name, instance_name)
    }
    fn get_ports(&self) -> Vec<PortInfo> { vec![] }
}

#[derive(Debug, Clone)]
pub struct ReadWriteCacheGenerator {
    pub name: String,
    pub num_read_ports: u32,
    pub num_write_ports: u32,
    pub block_size: u32,
    pub associativity: u32,
    pub num_rows: u32,
    pub address_width: u32,
    pub data_width: u32,
    pub replacement_policy: String,
    pub write_allocate: bool,
    pub write_read_fwd: bool,
}

impl ReadWriteCacheGenerator {
    fn offset_width(&self) -> u32 {
        if self.block_size <= 1 { 0 } else { (self.block_size - 1).next_power_of_two().trailing_zeros().max(1) }
    }
    fn index_width(&self) -> u32 {
        if self.num_rows <= 1 { 1 } else { (self.num_rows as f64).log2().ceil() as u32 }
    }
    fn words_per_line(&self) -> u32 {
        self.block_size * 8 / self.data_width
    }
    fn byte_enable_width(&self) -> u32 {
        self.data_width / 8
    }

    fn generate_rw_module_header(&self) -> String {
        let bew = self.byte_enable_width();
        let mut v = format!("module {} #(\n", self.name);
        v += &format!("    parameter BLOCK_SIZE = {},\n", self.block_size);
        v += &format!("    parameter ASSOCIATIVITY = {},\n", self.associativity);
        v += &format!("    parameter NUM_ROWS = {},\n", self.num_rows);
        v += &format!("    parameter ADDR_WIDTH = {},\n", self.address_width);
        v += &format!("    parameter DATA_WIDTH = {}\n", self.data_width);
        v += ")(\n";
        v += "    input  wire clk,\n";
        v += "    input  wire reset,\n";
        for i in 0..self.num_read_ports {
            v += &format!("\n    // Read port {}\n", i);
            v += &format!("    input  wire [ADDR_WIDTH-1:0] read_addr_{},\n", i);
            v += &format!("    input  wire read_req_{},\n", i);
            v += &format!("    output reg [DATA_WIDTH-1:0] read_data_{},\n", i);
            v += &format!("    output reg read_valid_{},\n", i);
        }
        v += "\n    // Write port\n";
        v += "    input  wire [ADDR_WIDTH-1:0] write_addr,\n";
        v += "    input  wire [DATA_WIDTH-1:0] write_data,\n";
        v += &format!("    input  wire [{}-1:0] write_byte_enable,\n", bew);
        v += "    input  wire write_req,\n";
        v += "    output reg write_complete,\n";
        v += "\n    // Refill interface to backing memory (read misses)\n";
        v += "    output reg [ADDR_WIDTH-1:0] refill_addr,\n";
        v += "    output reg refill_req,\n";
        v += "    input  wire [DATA_WIDTH-1:0] refill_data,\n";
        v += "    input  wire refill_valid,\n";
        v += "\n    // Write-through interface to backing memory\n";
        v += "    output reg [ADDR_WIDTH-1:0] write_through_addr,\n";
        v += "    output reg [DATA_WIDTH-1:0] write_through_data,\n";
        v += &format!("    output reg [{}-1:0] write_through_byte_enable,\n", bew);
        v += "    output reg write_through_req,\n";
        v += "    input  wire write_through_complete,\n";
        v += "\n    // Control signals\n";
        v += "    output wire idle,\n";
        v += "    output wire complete\n";
        v += ");\n\n";
        v
    }

    fn generate_rw_parameters(&self) -> String {
        let wpl = self.words_per_line();
        let word_offset_width = if wpl > 1 { ceil_log2(wpl as u32) } else { 1 };
        let mut v = "    // Derived parameters\n".to_string();
        v += &format!("    localparam OFFSET_WIDTH = {};\n", self.offset_width());
        v += &format!("    localparam INDEX_WIDTH = {};\n", self.index_width());
        v += "    localparam TAG_WIDTH = ADDR_WIDTH - OFFSET_WIDTH - INDEX_WIDTH;\n";
        v += &format!("    localparam WORDS_PER_LINE = {};\n", wpl);
        v += &format!("    localparam WORD_OFFSET_WIDTH = {};\n", word_offset_width);
        v += &format!("    localparam BYTE_ENABLE_WIDTH = {};\n\n", self.byte_enable_width());
        v
    }

    fn generate_rw_storage(&self) -> String {
        let mut v = "    // Storage arrays\n".to_string();
        if self.associativity == 1 {
            v += "    reg [TAG_WIDTH-1:0] tag_array [0:NUM_ROWS-1];\n";
            v += "    reg valid_array [0:NUM_ROWS-1];\n";
            v += "    reg [DATA_WIDTH*WORDS_PER_LINE-1:0] data_array [0:NUM_ROWS-1];\n";
        } else {
            v += "    reg [TAG_WIDTH-1:0] tag_array [0:NUM_ROWS-1][0:ASSOCIATIVITY-1];\n";
            v += "    reg valid_array [0:NUM_ROWS-1][0:ASSOCIATIVITY-1];\n";
            v += "    reg [DATA_WIDTH*WORDS_PER_LINE-1:0] data_array [0:NUM_ROWS-1][0:ASSOCIATIVITY-1];\n";
            if self.replacement_policy == "lru" {
                let lru_width = self.associativity - 1;
                v += &format!("    reg [{}:0] lru_array [0:NUM_ROWS-1];\n", lru_width);
            }
        }
        v += "\n";
        v
    }

    fn generate_rw_addr_decode(&self) -> String {
        let wpl = self.words_per_line();
        let mut v = "    // Address decoding - read ports\n".to_string();
        for i in 0..self.num_read_ports {
            v += &format!("    wire [TAG_WIDTH-1:0] read_tag_{i} = read_addr_{i}[ADDR_WIDTH-1:ADDR_WIDTH-TAG_WIDTH];\n");
            v += &format!("    wire [INDEX_WIDTH-1:0] read_index_{i} = read_addr_{i}[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH];\n");
            if wpl > 1 {
                v += &format!("    wire [WORD_OFFSET_WIDTH-1:0] read_word_offset_{i} = read_addr_{i}[OFFSET_WIDTH-1:OFFSET_WIDTH-WORD_OFFSET_WIDTH];\n");
            }
            v += "\n";
        }
        v += "    // Address decoding - write port\n";
        v += "    wire [TAG_WIDTH-1:0] write_tag = write_addr[ADDR_WIDTH-1:ADDR_WIDTH-TAG_WIDTH];\n";
        v += "    wire [INDEX_WIDTH-1:0] write_index = write_addr[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH];\n";
        if wpl > 1 {
            v += "    wire [WORD_OFFSET_WIDTH-1:0] write_word_offset = write_addr[OFFSET_WIDTH-1:OFFSET_WIDTH-WORD_OFFSET_WIDTH];\n";
        }
        v += "\n";
        v
    }

    fn generate_rw_hit_logic(&self) -> String {
        let mut v = "    // Hit detection - read ports\n".to_string();
        for i in 0..self.num_read_ports {
            if self.associativity == 1 {
                v += &format!("    wire read_hit_{i} = valid_array[read_index_{i}] && (tag_array[read_index_{i}] == read_tag_{i});\n");
            } else {
                v += &format!("    wire [{}:0] read_way_hit_{i};\n", self.associativity - 1);
                for way in 0..self.associativity {
                    v += &format!("    assign read_way_hit_{i}[{way}] = valid_array[read_index_{i}][{way}] && (tag_array[read_index_{i}][{way}] == read_tag_{i});\n");
                }
                v += &format!("    wire read_hit_{i} = |read_way_hit_{i};\n");
                let way_bits = ((self.associativity - 1) as f64).log2().ceil() as u32 + 1;
                v += &format!("    reg [{wb}:0] read_hit_way_{i};\n", wb = way_bits - 1);
                v += "    always @* begin\n";
                v += &format!("        read_hit_way_{i} = 0;\n");
                for way in 0..self.associativity {
                    v += &format!("        if (read_way_hit_{i}[{way}]) read_hit_way_{i} = {way};\n");
                }
                v += "    end\n";
            }
            v += "\n";
        }
        v += "    // Hit detection - write port\n";
        if self.associativity == 1 {
            v += "    wire write_hit = valid_array[write_index] && (tag_array[write_index] == write_tag);\n";
            v += "    wire pending_write_hit = valid_array[pending_index] && (tag_array[pending_index] == pending_tag);\n";
        } else {
            v += &format!("    wire [{}:0] write_way_hit;\n", self.associativity - 1);
            for way in 0..self.associativity {
                v += &format!("    assign write_way_hit[{way}] = valid_array[write_index][{way}] && (tag_array[write_index][{way}] == write_tag);\n");
            }
            v += "    wire write_hit = |write_way_hit;\n";
            let way_bits = ((self.associativity - 1) as f64).log2().ceil() as u32 + 1;
            v += &format!("    reg [{}:0] write_hit_way;\n", way_bits - 1);
            v += "    always @* begin\n";
            v += "        write_hit_way = 0;\n";
            for way in 0..self.associativity {
                v += &format!("        if (write_way_hit[{way}]) write_hit_way = {way};\n");
            }
            v += "    end\n";
            v += &format!("    wire [{}:0] pending_way_hit;\n", self.associativity - 1);
            for way in 0..self.associativity {
                v += &format!("    assign pending_way_hit[{way}] = valid_array[pending_index][{way}] && (tag_array[pending_index][{way}] == pending_tag);\n");
            }
            v += "    wire pending_write_hit = |pending_way_hit;\n";
            v += &format!("    reg [{}:0] pending_hit_way;\n", way_bits - 1);
            v += "    always @* begin\n";
            v += "        pending_hit_way = 0;\n";
            for way in 0..self.associativity {
                v += &format!("        if (pending_way_hit[{way}]) pending_hit_way = {way};\n");
            }
            v += "    end\n";
        }
        v += "\n";
        v
    }

    fn generate_rw_read_logic(&self) -> String {
        let wpl = self.words_per_line();
        let mut v = "    // Read data selection\n".to_string();
        for i in 0..self.num_read_ports {
            v += &format!("    reg [DATA_WIDTH-1:0] cache_read_data_{i};\n");
            v += "    always @* begin\n";
            if self.associativity == 1 {
                if wpl > 1 {
                    v += &format!("        cache_read_data_{i} = data_array[read_index_{i}][read_word_offset_{i}*DATA_WIDTH +: DATA_WIDTH];\n");
                } else {
                    v += &format!("        cache_read_data_{i} = data_array[read_index_{i}];\n");
                }
            } else {
                if wpl > 1 {
                    v += &format!("        cache_read_data_{i} = data_array[read_index_{i}][read_hit_way_{i}][read_word_offset_{i}*DATA_WIDTH +: DATA_WIDTH];\n");
                } else {
                    v += &format!("        cache_read_data_{i} = data_array[read_index_{i}][read_hit_way_{i}];\n");
                }
            }
            v += "    end\n";

            if self.write_read_fwd {
                v += &format!("\n    // Write-read forwarding for port {i}\n");
                v += &format!("    wire fwd_match_{i} = write_req && (write_addr == read_addr_{i});\n");
                v += "    always @* begin\n";
                v += &format!("        if (state == READ_UPDATE) begin\n");
                v += &format!("            read_data_{i} = refill_data;\n");
                v += &format!("            read_valid_{i} = 1'b1;\n");
                v += &format!("        end else if (fwd_match_{i}) begin\n");
                v += &format!("            read_data_{i} = write_data;\n");
                v += &format!("            read_valid_{i} = read_req_{i};\n");
                v += "        end else begin\n";
                v += &format!("            read_data_{i} = cache_read_data_{i};\n");
                v += &format!("            read_valid_{i} = read_req_{i} && read_hit_{i};\n");
                v += "        end\n";
                v += "    end\n\n";
            } else {
                v += "    always @* begin\n";
                v += &format!("        if (state == READ_UPDATE) begin\n");
                v += &format!("            read_data_{i} = refill_data;\n");
                v += &format!("            read_valid_{i} = 1'b1;\n");
                v += "        end else begin\n";
                v += &format!("            read_data_{i} = cache_read_data_{i};\n");
                v += &format!("            read_valid_{i} = read_req_{i} && read_hit_{i};\n");
                v += "        end\n";
                v += "    end\n\n";
            }
        }
        v
    }

    fn generate_rw_write_logic(&self) -> String {
        let bew = self.byte_enable_width();
        let wpl = self.words_per_line();
        let mut v = "    // Write data with byte enables (uses pending values for WRITE_THROUGH state)\n".to_string();
        v += "    reg [DATA_WIDTH-1:0] merged_write_data;\n";
        v += "    reg [DATA_WIDTH-1:0] pending_current_data;\n\n";
        v += "    always @* begin\n";
        if self.associativity == 1 {
            if wpl > 1 {
                v += "        pending_current_data = data_array[pending_index][pending_word_offset*DATA_WIDTH +: DATA_WIDTH];\n";
            } else {
                v += "        pending_current_data = data_array[pending_index];\n";
            }
        } else {
            if wpl > 1 {
                v += "        pending_current_data = data_array[pending_index][pending_hit_way][pending_word_offset*DATA_WIDTH +: DATA_WIDTH];\n";
            } else {
                v += "        pending_current_data = data_array[pending_index][pending_hit_way];\n";
            }
        }
        v += "        merged_write_data = pending_current_data;\n";
        for byte_idx in 0..bew {
            v += &format!("        if (pending_byte_enable[{byte_idx}]) merged_write_data[{}:{}] = pending_write_data[{}:{}];\n",
                (byte_idx+1)*8-1, byte_idx*8, (byte_idx+1)*8-1, byte_idx*8);
        }
        v += "    end\n\n";
        v
    }

    fn generate_rw_fsm(&self) -> String {
        let wpl = self.words_per_line();
        let bew = self.byte_enable_width();
        let mut v = "    // FSM states\n".to_string();
        v += "    localparam IDLE = 3'b000;\n";
        v += "    localparam READ_REFILL = 3'b001;\n";
        v += "    localparam READ_UPDATE = 3'b010;\n";
        v += "    localparam WRITE_THROUGH = 3'b011;\n";
        v += "    localparam WRITE_WAIT = 3'b100;\n";
        if self.write_allocate {
            v += "    localparam WRITE_ALLOC_REFILL = 3'b101;\n";
            v += "    localparam WRITE_ALLOC_UPDATE = 3'b110;\n";
        }
        v += "\n";
        v += "    reg [2:0] state, next_state;\n";
        v += "    reg [ADDR_WIDTH-1:0] miss_addr;\n";
        v += "    reg [INDEX_WIDTH-1:0] pending_index;\n";
        v += "    reg [TAG_WIDTH-1:0] pending_tag;\n";
        v += "    reg [DATA_WIDTH-1:0] pending_write_data;\n";
        v += "    reg [BYTE_ENABLE_WIDTH-1:0] pending_byte_enable;\n";
        if wpl > 1 {
            let word_cnt_bits = ((wpl - 1) as f64).log2().ceil() as u32;
            let word_cnt_bits = word_cnt_bits.max(1);
            v += &format!("    reg [{}:0] refill_word_cnt;\n", word_cnt_bits - 1);
            v += "    reg [DATA_WIDTH*WORDS_PER_LINE-1:0] refill_line_data;\n";
            v += "    reg [WORD_OFFSET_WIDTH-1:0] pending_word_offset;\n";
        }
        if self.associativity > 1 {
            let way_bits = ((self.associativity - 1) as f64).log2().ceil() as u32 + 1;
            v += &format!("    reg [{}:0] refill_way;\n", way_bits - 1);
        }
        // Warming register: blocks refill acceptance on first READ_REFILL cycle
        v += "    reg refill_warming;\n";
        v += "\n";

        // Miss detection
        v += "    // Miss detection\n";
        v += "    wire read_miss = ";
        let miss_conds: Vec<String> = (0..self.num_read_ports).map(|i| format!("(read_req_{i} && !read_hit_{i})")).collect();
        v += &miss_conds.join(" || ");
        v += ";\n";
        v += "    reg [ADDR_WIDTH-1:0] miss_addr_comb;\n";
        v += "    always @* begin\n";
        v += "        miss_addr_comb = read_addr_0;\n";
        for i in 0..self.num_read_ports {
            v += &format!("        if (read_req_{i} && !read_hit_{i}) miss_addr_comb = read_addr_{i};\n");
        }
        v += "    end\n\n";

        // Control signals
        v += "    // Control signals\n";
        v += "    assign idle = (state == IDLE);\n";
        v += "    assign complete = (state == IDLE && !read_miss) ||\n";
        v += "                       (state == READ_UPDATE) ||\n";
        v += "                       ((state == WRITE_WAIT) && write_through_complete && !read_miss);\n\n";

        // FSM state register
        v += "    // FSM state register\n";
        v += "    always @(posedge clk) begin\n";
        v += "        if (reset) begin\n";
        v += "            state <= IDLE;\n";
        v += "            miss_addr <= 0;\n";
        v += "            pending_index <= 0;\n";
        v += "            pending_tag <= 0;\n";
        v += "            pending_write_data <= 0;\n";
        v += "            pending_byte_enable <= 0;\n";
        if wpl > 1 {
            v += "            refill_word_cnt <= 0;\n";
            v += "            refill_line_data <= 0;\n";
            v += "            pending_word_offset <= 0;\n";
        }
        v += "            refill_warming <= 0;\n";
        v += "        end else begin\n";
        v += "            state <= next_state;\n\n";
        v += "            // Capture miss address on read miss (from IDLE or WRITE_WAIT→READ_REFILL)\n";
        v += "            if ((state == IDLE || (state == WRITE_WAIT && write_through_complete)) && read_miss) begin\n";
        v += "                miss_addr <= miss_addr_comb;\n";
        v += "                pending_index <= miss_addr_comb[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH];\n";
        v += "                pending_tag <= miss_addr_comb[ADDR_WIDTH-1:ADDR_WIDTH-TAG_WIDTH];\n";
        v += "            end\n\n";
        v += "            // Capture write data\n";
        v += "            if (state == IDLE && write_req) begin\n";
        v += "                pending_write_data <= write_data;\n";
        v += "                pending_byte_enable <= write_byte_enable;\n";
        v += "                pending_index <= write_index;\n";
        v += "                pending_tag <= write_tag;\n";
        if wpl > 1 {
            v += "                pending_word_offset <= write_word_offset;\n";
        }
        v += "            end\n";
        if wpl > 1 {
            v += "\n            // Accumulate refill data\n";
            v += "            if (state == READ_REFILL && refill_valid && !refill_warming) begin\n";
            v += "                refill_line_data[refill_word_cnt*DATA_WIDTH +: DATA_WIDTH] <= refill_data;\n";
            v += "                refill_word_cnt <= refill_word_cnt + 1;\n";
            v += "            end\n";
            v += "            if (state == READ_UPDATE) refill_word_cnt <= 0;\n";
        }
        v += "            // Warming: set on transitions to READ_REFILL, cleared next cycle\n";
        v += "            if ((state == IDLE && read_miss) || (state == WRITE_WAIT && write_through_complete && read_miss)) refill_warming <= 1'b1;\n";
        v += "            else refill_warming <= 1'b0;\n";
        v += "        end\n";
        v += "    end\n\n";

        // FSM next state logic
        v += "    // FSM next state logic\n";
        v += "    always @* begin\n";
        v += "        next_state = state;\n";
        v += "        refill_req = 1'b0;\n";
        v += "        refill_addr = miss_addr;\n";
        v += "        write_through_req = 1'b0;\n";
        v += "        write_through_addr = write_addr;\n";
        v += "        write_through_data = write_data;\n";
        v += "        write_through_byte_enable = write_byte_enable;\n";
        v += "        write_complete = 1'b0;\n\n";
        v += "        case (state)\n";
        v += "            IDLE: begin\n";
        v += "                if (write_req) begin\n";
        v += "                    next_state = WRITE_THROUGH;\n";
        v += "                end else if (read_miss) begin\n";
        v += "                    next_state = READ_REFILL;\n";
        v += "                end\n";
        v += "            end\n\n";
        v += "            READ_REFILL: begin\n";
        v += "                refill_req = 1'b1;\n";
        if wpl > 1 {
            v += "                refill_addr = {pending_tag, pending_index, refill_word_cnt, {(OFFSET_WIDTH-WORD_OFFSET_WIDTH){1'b0}}};\n";
            v += "                if (refill_valid && !refill_warming && refill_word_cnt == WORDS_PER_LINE-1) next_state = READ_UPDATE;\n";
        } else {
            v += "                if (refill_valid && !refill_warming) next_state = READ_UPDATE;\n";
        }
        v += "            end\n\n";
        v += "            READ_UPDATE: begin\n";
        v += "                next_state = IDLE;\n";
        v += "            end\n\n";

        // WRITE_THROUGH
        v += "            WRITE_THROUGH: begin\n";
        v += "                write_through_req = 1'b1;\n";
        v += "                write_through_addr = {pending_tag, pending_index, ";
        if wpl > 1 { v += "pending_word_offset, "; }
        v += "{(OFFSET_WIDTH";
        if wpl > 1 { v += "-WORD_OFFSET_WIDTH"; }
        v += "){1'b0}}};\n";
        v += "                write_through_data = pending_write_data;\n";
        v += "                write_through_byte_enable = pending_byte_enable;\n";
        v += "                next_state = WRITE_WAIT;\n";
        v += "            end\n\n";

        // WRITE_WAIT
        v += "            WRITE_WAIT: begin\n";
        v += "                write_through_req = 1'b1;\n";
        v += "                write_through_addr = {pending_tag, pending_index, ";
        if wpl > 1 { v += "pending_word_offset, "; }
        v += "{(OFFSET_WIDTH";
        if wpl > 1 { v += "-WORD_OFFSET_WIDTH"; }
        v += "){1'b0}}};\n";
        v += "                write_through_data = pending_write_data;\n";
        v += "                write_through_byte_enable = pending_byte_enable;\n";
        v += "                if (write_through_complete) begin\n";
        v += "                    write_complete = 1'b1;\n";
        v += "                    if (read_miss) begin\n";
        v += "                        // Read arrived during write; service it now\n";
        v += "                        next_state = READ_REFILL;\n";
        v += "                    end else begin\n";
        v += "                        next_state = IDLE;\n";
        v += "                    end\n";
        v += "                end\n";
        v += "            end\n\n";

        v += "            default: next_state = IDLE;\n";
        v += "        endcase\n";
        v += "    end\n\n";

        // Cache update logic
        v += "    // Cache update on refill complete and write hit\n";
        v += "    integer init_i;\n";
        if self.associativity > 1 { v += "    integer init_j;\n"; }
        v += "    always @(posedge clk) begin\n";
        v += "        if (reset) begin\n";
        if self.associativity == 1 {
            v += "            for (init_i = 0; init_i < NUM_ROWS; init_i = init_i + 1) begin\n";
            v += "                valid_array[init_i] <= 1'b0;\n";
            v += "            end\n";
        } else {
            v += "            for (init_i = 0; init_i < NUM_ROWS; init_i = init_i + 1) begin\n";
            v += "                for (init_j = 0; init_j < ASSOCIATIVITY; init_j = init_j + 1) begin\n";
            v += "                    valid_array[init_i][init_j] <= 1'b0;\n";
            v += "                end\n";
            v += "            end\n";
        }
        v += "        end else begin\n";
        v += "            // Update cache on read refill complete\n";
        v += "            if (state == READ_UPDATE) begin\n";
        if self.associativity == 1 {
            v += "                valid_array[pending_index] <= 1'b1;\n";
            v += "                tag_array[pending_index] <= pending_tag;\n";
            if wpl > 1 {
                v += "                data_array[pending_index] <= refill_line_data;\n";
            } else {
                v += "                data_array[pending_index] <= refill_data;\n";
            }
        } else {
            v += "                valid_array[pending_index][refill_way] <= 1'b1;\n";
            v += "                tag_array[pending_index][refill_way] <= pending_tag;\n";
            if wpl > 1 {
                v += "                data_array[pending_index][refill_way] <= refill_line_data;\n";
            } else {
                v += "                data_array[pending_index][refill_way] <= refill_data;\n";
            }
        }
        v += "            end\n\n";
        v += "            // Invalidate cache on write hit (write-through ensures memory is updated;\n";
        v += "            // invalidate forces next read to refill with fresh data from memory)\n";
        v += "            if (state == WRITE_WAIT && write_through_complete && pending_write_hit) begin\n";
        if self.associativity == 1 {
            v += "                valid_array[pending_index] <= 1'b0;\n";
        } else {
            v += "                valid_array[pending_index][pending_hit_way] <= 1'b0;\n";
        }
        v += "            end\n";
        v += "        end\n";
        v += "    end\n\n";
        v
    }

    fn generate_rw_replacement_logic(&self) -> String {
        if self.associativity == 1 { return String::new(); }
        let mut v = "    // Replacement policy logic\n".to_string();
        if self.replacement_policy == "lru" {
            v += "    // LRU replacement\n";
            v += "    integer lru_init_i;\n";
            v += "    always @(posedge clk) begin\n";
            v += "        if (reset) begin\n";
            v += "            for (lru_init_i = 0; lru_init_i < NUM_ROWS; lru_init_i = lru_init_i + 1) begin\n";
            v += "                lru_array[lru_init_i] <= 0;\n";
            v += "            end\n";
            v += "            refill_way <= 0;\n";
            v += "        end else begin\n";
            for i in 0..self.num_read_ports {
                v += &format!("            if (read_hit_{i}) begin\n");
                v += &format!("                lru_array[read_index_{i}] <= read_hit_way_{i};\n");
                v += "            end\n";
            }
            v += "            if (write_req && write_hit) begin\n";
            v += "                lru_array[write_index] <= write_hit_way;\n";
            v += "            end\n";
            v += "            if (state == IDLE && read_miss) begin\n";
            v += "                refill_way <= 0;\n";
            for way in 0..self.associativity {
                v += &format!("                if (!valid_array[miss_addr_comb[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH]][{way}]) refill_way <= {way};\n");
            }
            v += "                else refill_way <= lru_array[miss_addr_comb[OFFSET_WIDTH+INDEX_WIDTH-1:OFFSET_WIDTH]] ^ 1;\n";
            v += "            end\n";
            v += "        end\n";
            v += "    end\n\n";
        } else if self.replacement_policy == "random" {
            v += "    // Random replacement using LFSR\n";
            v += "    reg [7:0] lfsr;\n";
            v += "    always @(posedge clk) begin\n";
            v += "        if (reset) begin\n";
            v += "            lfsr <= 8'hA5;\n";
            v += "            refill_way <= 0;\n";
            v += "        end else begin\n";
            v += "            lfsr <= {lfsr[6:0], lfsr[7] ^ lfsr[5] ^ lfsr[4] ^ lfsr[3]};\n";
            v += "            if (state == IDLE && read_miss) begin\n";
            let way_bits = ((self.associativity - 1) as f64).log2().ceil() as u32 + 1;
            v += &format!("                refill_way <= lfsr[{}:0];\n", way_bits - 1);
            v += "            end\n";
            v += "        end\n";
            v += "    end\n\n";
        }
        v
    }
}

impl ModuleGenerator for ReadWriteCacheGenerator {
    fn generate_module(&self) -> String {
        let mut v = self.generate_rw_module_header();
        v += &self.generate_rw_parameters();
        v += &self.generate_rw_storage();
        v += &self.generate_rw_addr_decode();
        v += &self.generate_rw_hit_logic();
        v += &self.generate_rw_read_logic();
        v += &self.generate_rw_write_logic();
        v += &self.generate_rw_fsm();
        v += &self.generate_rw_replacement_logic();
        v += "endmodule\n";
        v
    }
    fn generate_instance(&self, instance_name: &str) -> String {
        format!("{} {}();", self.name, instance_name)
    }
    fn get_ports(&self) -> Vec<PortInfo> { vec![] }
}

#[derive(Debug, Clone)]
pub struct TLBModuleGenerator {
    pub name: String,
    pub num_entries: u32,
    pub associativity: u32,
    pub num_levels: u32,
    pub vpn_widths: Vec<u32>,
    pub pte_width: u32,
    pub replacement_policy: String,
    pub has_flush: bool,
}

impl TLBModuleGenerator {
    fn total_tag_width(&self) -> u32 { self.vpn_widths.iter().sum() }
    fn depth_width(&self) -> u32 { (self.num_levels as f64).log2().ceil().max(1.0) as u32 }
    fn num_sets(&self) -> u32 { self.num_entries / self.associativity }
    fn tlb_index_width(&self) -> u32 { ((self.num_sets() - 1) as f64).log2().ceil().max(1.0) as u32 }
    fn way_bits(&self) -> u32 { ((self.associativity - 1) as f64).log2().ceil().max(1.0) as u32 }
}

impl ModuleGenerator for TLBModuleGenerator {
    fn generate_module(&self) -> String {
        let depth_width = self.depth_width();
        let index_width = self.tlb_index_width();
        let way_bits = self.way_bits();
        let num_sets = self.num_sets();
        let ttw = self.total_tag_width();

        let mut v = format!("module {} #(\n", self.name);
        v += &format!("    parameter NUM_ENTRIES = {},\n", self.num_entries);
        v += &format!("    parameter ASSOCIATIVITY = {},\n", self.associativity);
        v += &format!("    parameter NUM_LEVELS = {},\n", self.num_levels);
        v += &format!("    parameter PTE_WIDTH = {},\n", self.pte_width);
        v += &format!("    parameter TOTAL_TAG_WIDTH = {}\n", ttw);
        v += ")(\n";
        v += "    input  wire clk,\n";
        v += "    input  wire reset,\n";
        v += "\n    // VPN inputs for lookup\n";
        for (i, width) in self.vpn_widths.iter().enumerate() {
            v += &format!("    input  wire [{}:0] vpn{},\n", width - 1, i);
        }
        v += "\n    // Per-depth lookup results\n";
        for depth in 1..=self.num_levels {
            v += &format!("    output reg hit_depth{},\n", depth);
            v += &format!("    output reg [PTE_WIDTH-1:0] data_depth{},\n", depth);
        }
        v += "\n    // PTW interface (for refill)\n";
        v += &format!("    input  wire [{}:0] ptw_pte_data,\n", self.pte_width - 1);
        v += &format!("    input  wire [{}:0] ptw_depth,\n", depth_width - 1);
        v += "    input  wire ptw_valid,\n";
        v += "    output reg ptw_miss,\n";
        v += "\n    // Control signals\n";
        v += "    input  wire lookup_req,\n";
        v += "    output reg idle,\n";
        v += "    output reg complete,\n";
        if self.has_flush {
            v += "\n    // Flush (invalidate all entries)\n";
            v += "    input  wire flush\n";
        } else {
            // Remove trailing comma
            v = v.trim_end_matches(",\n").to_string();
            v += "\n";
        }
        v += ");\n\n";

        // Parameters
        v += "    // Derived parameters\n";
        v += &format!("    localparam NUM_SETS = {};\n", num_sets);
        v += &format!("    localparam INDEX_WIDTH = {};\n", index_width);
        v += &format!("    localparam DEPTH_WIDTH = {};\n", depth_width);
        v += &format!("    localparam WAY_BITS = {};\n", way_bits);
        for (i, width) in self.vpn_widths.iter().enumerate() {
            v += &format!("    localparam VPN{}_WIDTH = {};\n", i, width);
        }
        v += "\n";

        // Storage arrays
        v += "    // TLB entry storage (per set, per way)\n";
        v += "    reg valid_array [0:NUM_SETS-1][0:ASSOCIATIVITY-1];\n";
        v += "    reg [DEPTH_WIDTH-1:0] depth_array [0:NUM_SETS-1][0:ASSOCIATIVITY-1];\n";
        for (i, _) in self.vpn_widths.iter().enumerate() {
            v += &format!("    reg [VPN{i}_WIDTH-1:0] vpn{i}_array [0:NUM_SETS-1][0:ASSOCIATIVITY-1];\n");
        }
        v += "    reg [PTE_WIDTH-1:0] pte_array [0:NUM_SETS-1][0:ASSOCIATIVITY-1];\n";
        if self.replacement_policy == "lru" {
            v += "    reg [WAY_BITS-1:0] lru_array [0:NUM_SETS-1];\n";
        }
        v += "\n";

        // Index extraction
        v += "    // Index extraction (from lowest VPN bits)\n";
        v += "    wire [INDEX_WIDTH-1:0] lookup_index = vpn0[INDEX_WIDTH-1:0];\n\n";

        // Match logic
        v += "    // Multi-level tag matching\n";
        for way in 0..self.associativity {
            v += &format!("\n    // Way {} matching\n", way);
            for lvl in 0..self.num_levels {
                v += &format!("    wire vpn{lvl}_match_w{way} = (vpn{lvl}_array[lookup_index][{way}] == vpn{lvl});\n");
            }
            for depth in 1..=self.num_levels {
                let match_terms: Vec<String> = ((self.num_levels - depth)..self.num_levels)
                    .map(|lvl| format!("vpn{lvl}_match_w{way}"))
                    .collect();
                let match_expr = if match_terms.is_empty() { "1'b1".to_string() } else { match_terms.join(" && ") };
                v += &format!("    wire depth{depth}_match_w{way} = valid_array[lookup_index][{way}] && (depth_array[lookup_index][{way}] == {depth}) && {match_expr};\n");
            }
        }
        v += "\n";
        for depth in 1..=self.num_levels {
            let hit_terms: Vec<String> = (0..self.associativity).map(|way| format!("depth{depth}_match_w{way}")).collect();
            v += &format!("    wire any_hit_depth{depth} = {};\n", hit_terms.join(" || "));
        }
        let all_hit_terms: Vec<String> = (1..=self.num_levels).map(|d| format!("any_hit_depth{d}")).collect();
        v += &format!("    wire any_hit = {};\n\n", all_hit_terms.join(" || "));

        // Read logic
        v += "    // Hit way selection per depth\n";
        for depth in 1..=self.num_levels {
            v += &format!("    reg [WAY_BITS-1:0] hit_way_depth{};\n", depth);
        }
        v += "\n    always @* begin\n";
        for depth in 1..=self.num_levels {
            v += &format!("        hit_way_depth{depth} = 0;\n");
            for way in 0..self.associativity {
                v += &format!("        if (depth{depth}_match_w{way}) hit_way_depth{depth} = {way};\n");
            }
        }
        v += "    end\n\n";
        v += "    // Output hit and data per depth\n";
        v += "    always @* begin\n";
        for depth in 1..=self.num_levels {
            v += &format!("        hit_depth{depth} = lookup_req && any_hit_depth{depth};\n");
            v += &format!("        data_depth{depth} = pte_array[lookup_index][hit_way_depth{depth}];\n");
        }
        v += "        ptw_miss = lookup_req && !any_hit;\n";
        v += "        idle = 1'b1;\n";
        v += "        complete = lookup_req && any_hit;\n";
        v += "    end\n\n";

        // PTW FSM stub
        v += "    // PTW FSM - handled externally, TLB accepts updates via ptw_valid\n\n";

        // Update logic
        v += "    // TLB update on PTW completion or flush\n";
        v += "    reg [WAY_BITS-1:0] update_way;\n";
        v += "    integer init_i, init_j;\n\n";
        v += "    always @(posedge clk) begin\n";
        if self.has_flush {
            v += "        if (reset || flush) begin\n";
        } else {
            v += "        if (reset) begin\n";
        }
        v += "            for (init_i = 0; init_i < NUM_SETS; init_i = init_i + 1) begin\n";
        v += "                for (init_j = 0; init_j < ASSOCIATIVITY; init_j = init_j + 1) begin\n";
        v += "                    valid_array[init_i][init_j] <= 1'b0;\n";
        v += "                end\n";
        v += "            end\n";
        v += "        end else if (ptw_valid) begin\n";
        v += "            valid_array[lookup_index][update_way] <= 1'b1;\n";
        v += "            depth_array[lookup_index][update_way] <= ptw_depth;\n";
        for i in 0..self.num_levels as usize {
            v += &format!("            vpn{i}_array[lookup_index][update_way] <= vpn{i};\n");
        }
        v += "            pte_array[lookup_index][update_way] <= ptw_pte_data;\n";
        v += "        end\n";
        v += "    end\n\n";

        // Replacement logic
        if self.associativity == 1 {
            v += "    // Direct-mapped: update_way always 0\n    always @* update_way = 0;\n\n";
        } else {
            v += "    // LRU replacement\n";
            v += "    integer lru_init_i;\n";
            v += "    always @(posedge clk) begin\n";
            v += "        if (reset) begin\n";
            v += "            for (lru_init_i = 0; lru_init_i < NUM_SETS; lru_init_i = lru_init_i + 1) begin\n";
            v += "                lru_array[lru_init_i] <= 0;\n";
            v += "            end\n";
            v += "            update_way <= 0;\n";
            v += "        end else begin\n";
            v += "            if (lookup_req && any_hit) begin\n";
            for depth in 1..=self.num_levels {
                v += &format!("                if (any_hit_depth{depth}) lru_array[lookup_index] <= hit_way_depth{depth};\n");
            }
            v += "            end\n";
            v += "            if (lookup_req && !any_hit) begin\n";
            v += "                update_way <= 0;\n";
            for way in 0..self.associativity {
                v += &format!("                if (!valid_array[lookup_index][{way}]) update_way <= {way};\n");
            }
            v += "                else update_way <= lru_array[lookup_index] ^ 1;\n";
            v += "            end\n";
            v += "        end\n";
            v += "    end\n\n";
        }

        v += "endmodule\n";
        v
    }
    fn generate_instance(&self, instance_name: &str) -> String {
        format!("{} {}();", self.name, instance_name)
    }
    fn get_ports(&self) -> Vec<PortInfo> { vec![] }
}

#[derive(Debug, Clone)]
pub struct InstructionBufferGenerator {
    pub name: String,
    pub fetch_width: u32,
    pub buffer_size: u32,
    pub address_width: u32,
    pub data_width: u32,
    pub has_flush: bool,
    pub output_offsets: Vec<u32>,
}

impl InstructionBufferGenerator {
    fn fetch_bytes(&self) -> u32 { self.fetch_width / 8 }
    fn buffer_capacity_bytes(&self) -> u32 { self.buffer_size * self.fetch_bytes() }
    fn ptr_width(&self) -> u32 { ((self.buffer_capacity_bytes() - 1) as f64).log2().ceil() as u32 }
    fn data_bytes(&self) -> u32 { self.data_width / 8 }
    fn effective_offsets(&self) -> Vec<u32> {
        if self.output_offsets.is_empty() { vec![0] } else { self.output_offsets.clone() }
    }
}

impl ModuleGenerator for InstructionBufferGenerator {
    fn generate_module(&self) -> String {
        let offsets = self.effective_offsets();
        let fb = self.fetch_bytes();
        let ptr_width = self.ptr_width();
        let data_bytes = self.data_bytes();
        let max_offset = *offsets.iter().max().unwrap_or(&0);
        let min_bytes_needed = max_offset + data_bytes;
        let consume_width = ((fb - 1) as f64).log2().ceil().max(1.0) as u32;

        let mut v = format!("module {} #(\n", self.name);
        v += &format!("    parameter FETCH_WIDTH = {},\n", self.fetch_width);
        v += &format!("    parameter BUFFER_SIZE = {},\n", self.buffer_size);
        v += &format!("    parameter ADDR_WIDTH = {},\n", self.address_width);
        v += &format!("    parameter DATA_WIDTH = {}\n", self.data_width);
        v += ")(\n";
        v += "    input  wire clk,\n";
        v += "    input  wire reset,\n";
        v += "\n    // Fetch interface to backing memory\n";
        v += "    output reg [ADDR_WIDTH-1:0] fetch_addr,\n";
        v += "    output reg fetch_req,\n";
        v += "    input  wire [FETCH_WIDTH-1:0] fetch_data,\n";
        v += "    input  wire fetch_valid,\n";
        v += "\n    // Instruction output ports (one per PC+N access)\n";
        for (i, offset) in offsets.iter().enumerate() {
            v += &format!("    output wire [DATA_WIDTH-1:0] out_data_{},  // byte offset {}\n", i, offset);
            v += &format!("    output wire out_valid_{},\n", i);
        }
        v += "\n    // Consume interface (from decode)\n";
        v += &format!("    input  wire [{}:0] consume_bytes,\n", consume_width);
        v += "    input  wire consume_valid,\n";
        v += "\n    // Reset address (initial fetch address, e.g., reset PC)\n";
        v += "    input  wire [ADDR_WIDTH-1:0] reset_addr";
        if self.has_flush {
            v += ",\n\n    // Flush + redirect control (e.g., branch misprediction)\n";
            v += "    input  wire flush,\n";
            v += "    input  wire [ADDR_WIDTH-1:0] redirect_addr";
        }
        v += "\n);\n\n";

        // Parameters
        v += "    // Derived parameters\n";
        v += "    localparam FETCH_BYTES = FETCH_WIDTH / 8;\n";
        v += "    localparam BUF_BYTES = BUFFER_SIZE * FETCH_BYTES;\n";
        v += &format!("    localparam PTR_WIDTH = {};\n", ptr_width);
        v += "    localparam DATA_BYTES = DATA_WIDTH / 8;\n";
        v += &format!("    localparam MAX_OFFSET = {};\n\n", max_offset);

        // Storage
        v += "    // Buffer storage (byte-addressable circular buffer)\n";
        v += "    reg [7:0] buffer [0:BUF_BYTES-1];\n";
        v += "    reg [PTR_WIDTH:0] wr_ptr;\n";
        v += "    reg [PTR_WIDTH:0] rd_ptr;\n";
        v += "    reg [PTR_WIDTH:0] count;\n\n";
        v += "    // Buffer occupancy\n";
        v += "    wire buf_full  = (count + FETCH_BYTES > BUF_BYTES);\n";
        v += &format!("    wire buf_has_data = (count >= {});\n\n", min_bytes_needed);

        // Output logic
        v += "    // Output alignment - multi-offset output ports\n";
        v += "    genvar gi;\n";
        for (i, offset) in offsets.iter().enumerate() {
            v += &format!("\n    // Output port {}: byte offset {} from rd_ptr\n", i, offset);
            v += "    generate\n";
            v += &format!("        for (gi = 0; gi < DATA_BYTES; gi = gi + 1) begin : gen_out_{}\n", i);
            v += &format!("            wire [PTR_WIDTH:0] idx_{} = (rd_ptr + {} + gi) & (BUF_BYTES-1);\n", i, offset);
            v += &format!("            assign out_data_{}[gi*8 +: 8] = buffer[idx_{}];\n", i, i);
            v += "        end\n";
            v += "    endgenerate\n";
            v += &format!("    assign out_valid_{} = buf_has_data;\n", i);
        }
        v += "\n";

        // Fetch FSM
        v += "    // Fetch and consume logic\n";
        v += "    integer i;\n";
        v += "    always @(posedge clk) begin\n";
        v += "        if (reset) begin\n";
        v += "            wr_ptr <= 0;\n";
        v += "            rd_ptr <= 0;\n";
        v += "            count  <= 0;\n";
        v += "            fetch_addr <= reset_addr;\n";
        v += "            fetch_req <= 1'b1;\n";
        if self.has_flush {
            v += "        end else if (flush && buf_has_data) begin\n";
            v += "            wr_ptr <= 0;\n";
            v += "            rd_ptr <= 0;\n";
            v += "            count  <= 0;\n";
            v += "            fetch_addr <= redirect_addr;\n";
            v += "            fetch_req <= 1'b1;\n";
        }
        v += "        end else begin\n";
        v += "            if (consume_valid && buf_has_data) begin\n";
        v += "                rd_ptr <= (rd_ptr + consume_bytes) & (BUF_BYTES-1);\n";
        v += "                count  <= count - consume_bytes;\n";
        v += "            end\n\n";
        v += "            if (fetch_valid && fetch_req && !buf_full) begin\n";
        v += "                for (i = 0; i < FETCH_BYTES; i = i + 1) begin\n";
        v += "                    buffer[(wr_ptr + i) & (BUF_BYTES-1)] <= fetch_data[i*8 +: 8];\n";
        v += "                end\n";
        v += "                wr_ptr <= (wr_ptr + FETCH_BYTES) & (BUF_BYTES-1);\n";
        v += "                count  <= count + FETCH_BYTES\n";
        v += "                           - ((consume_valid && buf_has_data) ? consume_bytes : 0);\n";
        v += "                fetch_addr <= fetch_addr + FETCH_BYTES;\n";
        v += "            end\n\n";
        v += "            fetch_req  <= !buf_full;\n";
        v += "        end\n";
        v += "    end\n\n";

        v += "endmodule\n";
        v
    }
    fn generate_instance(&self, instance_name: &str) -> String {
        format!("{} {}();", self.name, instance_name)
    }
    fn get_ports(&self) -> Vec<PortInfo> { vec![] }
}

#[derive(Debug, Clone)]
pub struct BranchTargetBufferGenerator {
    pub name: String,
    pub num_entries: u32,
    pub associativity: u32,
    pub pc_width: u32,
    pub target_width: u32,
    pub dual_port: bool,
}

impl BranchTargetBufferGenerator {
    fn num_sets(&self) -> u32 { self.num_entries / self.associativity }
    fn btb_index_width(&self) -> u32 { ((self.num_sets() - 1) as f64).log2().ceil().max(1.0) as u32 }
    fn btb_tag_width(&self) -> u32 { self.pc_width - self.btb_index_width() - 2 }
}

impl ModuleGenerator for BranchTargetBufferGenerator {
    fn generate_module(&self) -> String {
        let index_width = self.btb_index_width();
        let tag_width = self.btb_tag_width();

        let mut v = format!("module {} #(\n", self.name);
        v += &format!("    parameter NUM_ENTRIES = {},\n", self.num_entries);
        v += &format!("    parameter ASSOCIATIVITY = {},\n", self.associativity);
        v += &format!("    parameter PC_WIDTH = {},\n", self.pc_width);
        v += &format!("    parameter TARGET_WIDTH = {}\n", self.target_width);
        v += ")(\n";
        v += "    input  wire clk,\n";
        v += "    input  wire reset,\n";
        v += "\n    // Lookup interface (Fetch stage)\n";
        v += "    input  wire [PC_WIDTH-1:0] lookup_pc,\n";
        v += "    output reg  hit,\n";
        v += "    output reg  [TARGET_WIDTH-1:0] predicted_target,\n";
        v += "    output reg  predicted_taken,\n";
        if self.dual_port {
            v += "\n    // Execute stage lookup interface (for misprediction detection)\n";
            v += "    input  wire [PC_WIDTH-1:0] execute_lookup_pc,\n";
            v += "    output reg  execute_hit,\n";
            v += "    output reg  execute_predicted_taken,\n";
        }
        v += "\n    // Update interface (Execute stage)\n";
        v += "    input  wire update_enable,\n";
        v += "    input  wire [PC_WIDTH-1:0] update_pc,\n";
        v += "    input  wire [TARGET_WIDTH-1:0] update_target,\n";
        v += "    input  wire update_taken\n";
        v += ");\n\n";

        // Storage arrays
        v += "    // Derived parameters\n";
        v += "    localparam NUM_SETS = NUM_ENTRIES / ASSOCIATIVITY;\n";
        v += &format!("    localparam INDEX_WIDTH = {};\n", index_width);
        v += "    localparam TAG_WIDTH = PC_WIDTH - INDEX_WIDTH - 2;\n\n";
        v += "    // Storage arrays\n";
        if self.associativity == 1 {
            v += "    reg [TAG_WIDTH-1:0] tag_array [0:NUM_SETS-1];\n";
            v += "    reg [TARGET_WIDTH-1:0] target_array [0:NUM_SETS-1];\n";
            v += "    reg taken_array [0:NUM_SETS-1];\n";
            v += "    reg valid_array [0:NUM_SETS-1];\n";
            v += "\n    initial begin : init_arrays\n";
            v += "        integer i;\n";
            v += "        for (i = 0; i < NUM_SETS; i = i + 1) begin\n";
            v += "            valid_array[i] = 1'b0;\n";
            v += "            taken_array[i] = 1'b0;\n";
            v += &format!("            tag_array[i] = {}'b0;\n", tag_width);
            v += &format!("            target_array[i] = {}'d0;\n", self.target_width);
            v += "        end\n";
            v += "    end\n";
        } else {
            v += "    reg [TAG_WIDTH-1:0] tag_array [0:NUM_SETS-1][0:ASSOCIATIVITY-1];\n";
            v += "    reg [TARGET_WIDTH-1:0] target_array [0:NUM_SETS-1][0:ASSOCIATIVITY-1];\n";
            v += "    reg taken_array [0:NUM_SETS-1][0:ASSOCIATIVITY-1];\n";
            v += "    reg valid_array [0:NUM_SETS-1][0:ASSOCIATIVITY-1];\n";
            let rway_bits = ((self.associativity - 1) as f64).log2().ceil() as u32;
            let rway_bits = rway_bits.max(1);
            v += &format!("    reg [{}:0] replace_way [0:NUM_SETS-1];\n", rway_bits - 1);
            v += "\n    initial begin : init_arrays\n";
            v += "        integer i, w;\n";
            v += "        for (i = 0; i < NUM_SETS; i = i + 1) begin\n";
            v += "            replace_way[i] = 0;\n";
            v += "            for (w = 0; w < ASSOCIATIVITY; w = w + 1) begin\n";
            v += "                valid_array[i][w] = 1'b0;\n";
            v += "                taken_array[i][w] = 1'b0;\n";
            v += &format!("                tag_array[i][w] = {}'b0;\n", tag_width);
            v += &format!("                target_array[i][w] = {}'d0;\n", self.target_width);
            v += "            end\n";
            v += "        end\n";
            v += "    end\n";
        }
        v += "\n";

        // Address decoding
        v += "    // Address decoding - Fetch stage lookup\n";
        v += "    wire [TAG_WIDTH-1:0] lookup_tag = lookup_pc[PC_WIDTH-1:INDEX_WIDTH+2];\n";
        v += "    wire [INDEX_WIDTH-1:0] lookup_index = lookup_pc[INDEX_WIDTH+1:2];\n\n";
        if self.dual_port {
            v += "    // Address decoding - Execute stage lookup\n";
            v += "    wire [TAG_WIDTH-1:0] execute_lookup_tag = execute_lookup_pc[PC_WIDTH-1:INDEX_WIDTH+2];\n";
            v += "    wire [INDEX_WIDTH-1:0] execute_lookup_index = execute_lookup_pc[INDEX_WIDTH+1:2];\n\n";
        }
        v += "    // Address decoding - update\n";
        v += "    wire [TAG_WIDTH-1:0] update_tag = update_pc[PC_WIDTH-1:INDEX_WIDTH+2];\n";
        v += "    wire [INDEX_WIDTH-1:0] update_index = update_pc[INDEX_WIDTH+1:2];\n\n";

        // Lookup logic
        v += "    // Fetch stage lookup logic (combinational)\n";
        v += "    always @* begin\n";
        if self.associativity == 1 {
            v += "        hit = valid_array[lookup_index] && (tag_array[lookup_index] == lookup_tag);\n";
            v += "        predicted_target = target_array[lookup_index];\n";
            v += "        predicted_taken = taken_array[lookup_index];\n";
        } else {
            v += "        hit = 1'b0;\n";
            v += &format!("        predicted_target = {}'d0;\n", self.target_width);
            v += "        predicted_taken = 1'b0;\n";
            v += "        begin : lookup_ways\n";
            v += "            integer way;\n";
            v += "            for (way = 0; way < ASSOCIATIVITY; way = way + 1) begin\n";
            v += "                if (valid_array[lookup_index][way] && (tag_array[lookup_index][way] == lookup_tag)) begin\n";
            v += "                    hit = 1'b1;\n";
            v += "                    predicted_target = target_array[lookup_index][way];\n";
            v += "                    predicted_taken = taken_array[lookup_index][way];\n";
            v += "                end\n";
            v += "            end\n";
            v += "        end\n";
        }
        v += "    end\n\n";

        if self.dual_port {
            v += "    // Execute stage lookup logic (for misprediction detection)\n";
            v += "    always @* begin\n";
            if self.associativity == 1 {
                v += "        execute_hit = valid_array[execute_lookup_index] && (tag_array[execute_lookup_index] == execute_lookup_tag);\n";
                v += "        execute_predicted_taken = taken_array[execute_lookup_index];\n";
            } else {
                v += "        execute_hit = 1'b0;\n";
                v += "        execute_predicted_taken = 1'b0;\n";
                v += "        begin : execute_lookup_ways\n";
                v += "            integer way;\n";
                v += "            for (way = 0; way < ASSOCIATIVITY; way = way + 1) begin\n";
                v += "                if (valid_array[execute_lookup_index][way] && (tag_array[execute_lookup_index][way] == execute_lookup_tag)) begin\n";
                v += "                    execute_hit = 1'b1;\n";
                v += "                    execute_predicted_taken = taken_array[execute_lookup_index][way];\n";
                v += "                end\n";
                v += "            end\n";
                v += "        end\n";
            }
            v += "    end\n\n";
        }

        // Update logic
        v += "    // Update logic (synchronous)\n";
        if self.associativity == 1 {
            v += "    always @(posedge clk) begin\n";
            v += "        if (reset) begin\n";
            v += "            begin : reset_btb\n";
            v += "                integer i;\n";
            v += "                for (i = 0; i < NUM_SETS; i = i + 1) begin\n";
            v += "                    valid_array[i] <= 1'b0;\n";
            v += "                    taken_array[i] <= 1'b0;\n";
            v += &format!("                    tag_array[i] <= {}'b0;\n", tag_width);
            v += &format!("                    target_array[i] <= {}'d0;\n", self.target_width);
            v += "                end\n";
            v += "            end\n";
            v += "        end else if (update_enable) begin\n";
            v += "            tag_array[update_index] <= update_tag;\n";
            v += "            target_array[update_index] <= update_target;\n";
            v += "            taken_array[update_index] <= update_taken;\n";
            v += "            valid_array[update_index] <= 1'b1;\n";
            v += "        end\n";
            v += "    end\n\n";
        } else {
            let way_width = ((self.associativity - 1) as f64).log2().ceil().max(1.0) as u32;
            v += &format!("    reg [{}:0] victim_way;\n", way_width - 1);
            v += "    reg found_match;\n\n";
            v += "    always @(posedge clk) begin\n";
            v += "        if (reset) begin\n";
            v += "            begin : reset_btb\n";
            v += "                integer i, w;\n";
            v += "                for (i = 0; i < NUM_SETS; i = i + 1) begin\n";
            v += "                    replace_way[i] <= 0;\n";
            v += "                    for (w = 0; w < ASSOCIATIVITY; w = w + 1) begin\n";
            v += "                        valid_array[i][w] <= 1'b0;\n";
            v += "                        taken_array[i][w] <= 1'b0;\n";
            v += &format!("                        tag_array[i][w] <= {}'b0;\n", tag_width);
            v += &format!("                        target_array[i][w] <= {}'d0;\n", self.target_width);
            v += "                    end\n";
            v += "                end\n";
            v += "            end\n";
            v += "        end else if (update_enable) begin\n";
            v += "            found_match = 1'b0;\n";
            v += "            victim_way = replace_way[update_index];\n";
            v += "            begin : find_match\n";
            v += "                integer w;\n";
            v += "                for (w = 0; w < ASSOCIATIVITY; w = w + 1) begin\n";
            v += "                    if (valid_array[update_index][w] && (tag_array[update_index][w] == update_tag)) begin\n";
            v += "                        found_match = 1'b1;\n";
            v += &format!("                        victim_way = w[{}:0];\n", way_width - 1);
            v += "                    end\n";
            v += "                end\n";
            v += "            end\n";
            v += "            tag_array[update_index][victim_way] <= update_tag;\n";
            v += "            target_array[update_index][victim_way] <= update_target;\n";
            v += "            taken_array[update_index][victim_way] <= update_taken;\n";
            v += "            valid_array[update_index][victim_way] <= 1'b1;\n";
            v += "            if (!found_match) begin\n";
            v += "                replace_way[update_index] <= (replace_way[update_index] + 1) % ASSOCIATIVITY;\n";
            v += "            end\n";
            v += "        end\n";
            v += "    end\n\n";
        }

        v += "endmodule\n";
        v
    }
    fn generate_instance(&self, instance_name: &str) -> String {
        format!("{} {}();", self.name, instance_name)
    }
    fn get_ports(&self) -> Vec<PortInfo> { vec![] }
}

#[derive(Debug, Clone)]
pub struct RegisterRenamerGenerator {
    pub name: String,
    pub num_arch_regs: u32,
    pub num_phys_regs: u32,
    pub num_read_ports: u32,
    pub num_write_ports: u32,
    pub arch_reg_width: u32,
}

impl RegisterRenamerGenerator {
    fn phys_reg_width(&self) -> u32 {
        if self.num_phys_regs > 1 { (self.num_phys_regs as f64).log2().ceil() as u32 } else { 1 }
    }
}

impl ModuleGenerator for RegisterRenamerGenerator {
    fn generate_module(&self) -> String {
        let prw = self.phys_reg_width();
        let arw = self.arch_reg_width;
        let extra_regs = self.num_phys_regs - self.num_arch_regs;

        let mut v = format!("// Register Renaming Unit: {} arch regs -> {} phys regs\n", self.num_arch_regs, self.num_phys_regs);
        v += "// Speculative allocation at Decode, committed RAT for flush recovery\n";
        v += &format!("module {} (\n", self.name);
        v += "    input  wire clk,\n";
        v += "    input  wire reset,\n";
        v += "    input  wire stall,\n";
        v += "    input  wire flush,\n\n";

        for i in 0..self.num_read_ports {
            v += &format!("    // Read port {} (source register lookup at Decode)\n", i);
            v += &format!("    input  wire [{}:0] read_arch_{},\n", arw - 1, i);
            v += &format!("    input  wire read_valid_{},\n", i);
            v += &format!("    output wire [{}:0] read_phys_{},\n\n", prw - 1, i);
        }
        for i in 0..self.num_write_ports {
            v += &format!("    // Write port {} (destination register allocation at Decode)\n", i);
            v += &format!("    input  wire [{}:0] write_arch_{},\n", arw - 1, i);
            v += &format!("    input  wire write_valid_{},\n", i);
            v += &format!("    output wire [{}:0] write_phys_{},\n", prw - 1, i);
            v += &format!("    output wire [{}:0] write_old_phys_{},\n\n", prw - 1, i);
        }
        for i in 0..self.num_write_ports {
            v += &format!("    // Commit port {} (Writeback-stage committed RAT update)\n", i);
            v += &format!("    input  wire [{}:0] commit_arch_{},\n", arw - 1, i);
            v += &format!("    input  wire [{}:0] commit_phys_{},\n", prw - 1, i);
            v += &format!("    input  wire commit_valid_{},\n\n", i);
        }
        v += "    // Free port (register reclamation at Writeback)\n";
        v += &format!("    input  wire [{}:0] free_phys,\n", prw - 1);
        v += "    input  wire free_valid,\n\n";
        v += "    // Status\n";
        v += "    output wire free_list_empty,\n";
        v += &format!("    output wire [{}:0] free_count\n", prw);
        v += ");\n\n";

        // Rename tables
        v += "    // Speculative Rename Table (RAT): updated at Decode on allocation\n";
        v += &format!("    reg [{}:0] rename_table [0:{}];\n\n", prw - 1, self.num_arch_regs - 1);
        v += "    // Committed Rename Table (C-RAT): updated at Writeback on commit\n";
        v += &format!("    reg [{}:0] committed_rat [0:{}];\n\n", prw - 1, self.num_arch_regs - 1);
        v += "    // Initialize both rename tables: arch[i] -> phys[i]\n";
        v += "    integer init_i;\n";
        v += "    initial begin\n";
        v += &format!("        for (init_i = 0; init_i < {}; init_i = init_i + 1) begin\n", self.num_arch_regs);
        v += &format!("            rename_table[init_i] = init_i[{}:0];\n", prw - 1);
        v += &format!("            committed_rat[init_i] = init_i[{}:0];\n", prw - 1);
        v += "        end\n";
        v += "    end\n\n";

        // Free list
        v += "    // Free List: FIFO of available physical registers\n";
        v += &format!("    reg [{}:0] free_list [0:{}];\n", prw - 1, self.num_phys_regs - 1);
        v += &format!("    reg [{}:0] free_head;\n", prw);
        v += &format!("    reg [{}:0] free_tail;\n", prw);
        v += &format!("    reg [{}:0] free_cnt;\n\n", prw);
        v += &format!("    reg [{}:0] committed_free_head;\n", prw);
        v += &format!("    reg [{}:0] committed_free_cnt;\n\n", prw);
        v += "    // Initialize free list with extra physical registers\n";
        v += "    integer fl_init_i;\n";
        v += "    initial begin\n";
        v += "        free_head = 0;\n";
        v += &format!("        free_tail = {};\n", extra_regs);
        v += &format!("        free_cnt = {};\n", extra_regs);
        v += "        committed_free_head = 0;\n";
        v += &format!("        committed_free_cnt = {};\n", extra_regs);
        v += &format!("        for (fl_init_i = 0; fl_init_i < {}; fl_init_i = fl_init_i + 1) begin\n", extra_regs);
        v += &format!("            free_list[fl_init_i] = {} + fl_init_i;\n", self.num_arch_regs);
        v += "        end\n";
        v += "    end\n\n";
        v += "    assign free_list_empty = (free_cnt == 0);\n";
        v += "    assign free_count = free_cnt;\n\n";

        // Lookup logic
        v += "    // Read port lookup logic (combinational, from speculative RAT)\n";
        for i in 0..self.num_read_ports {
            v += &format!("    assign read_phys_{i} = (read_arch_{i} == 0) ? {}'d0 : rename_table[read_arch_{i}];\n", prw);
        }
        v += "\n";

        // Allocation logic
        v += "    // Allocation logic for destination registers (at Decode)\n";
        for i in 0..self.num_write_ports {
            if i == 0 {
                v += &format!("    wire [{}:0] alloc_phys_{} = free_list[free_head];\n", prw - 1, i);
            } else {
                v += &format!("    wire [{}:0] alloc_phys_{} = free_list[(free_head + {}) % {}];\n", prw - 1, i, i, self.num_phys_regs);
            }
            v += &format!("    assign write_phys_{i} = (write_arch_{i} == 0) ? {}'d0 : alloc_phys_{i};\n", prw);
            v += &format!("    assign write_old_phys_{i} = rename_table[write_arch_{i}];\n");
        }
        v += "\n";
        for i in 0..self.num_write_ports {
            v += &format!("    wire do_alloc_{i} = write_valid_{i} && write_arch_{i} != 0 && !free_list_empty;\n");
            v += &format!("    wire do_commit_{i} = commit_valid_{i} && commit_arch_{i} != 0;\n");
        }
        v += "\n";

        // Sequential logic
        v += "    // Sequential logic: allocation (Decode), commit (Writeback), flush recovery\n";
        v += "    always @(posedge clk) begin\n";
        v += "        if (reset) begin\n";
        v += &format!("            for (init_i = 0; init_i < {}; init_i = init_i + 1) begin\n", self.num_arch_regs);
        v += &format!("                rename_table[init_i] <= init_i[{}:0];\n", prw - 1);
        v += &format!("                committed_rat[init_i] <= init_i[{}:0];\n", prw - 1);
        v += "            end\n";
        v += "            free_head <= 0;\n";
        v += &format!("            free_tail <= {};\n", extra_regs);
        v += &format!("            free_cnt <= {};\n", extra_regs);
        v += "            committed_free_head <= 0;\n";
        v += &format!("            committed_free_cnt <= {};\n", extra_regs);
        v += &format!("            for (fl_init_i = 0; fl_init_i < {}; fl_init_i = fl_init_i + 1) begin\n", extra_regs);
        v += &format!("                free_list[fl_init_i] <= {} + fl_init_i;\n", self.num_arch_regs);
        v += "            end\n";

        // Flush
        v += "        end else if (flush) begin\n";
        for i in 0..self.num_write_ports {
            v += &format!("            if (do_commit_{i}) begin\n");
            v += &format!("                committed_rat[commit_arch_{i}] <= commit_phys_{i};\n");
            v += "            end\n";
        }
        let commit_sum: Vec<String> = (0..self.num_write_ports).map(|i| format!("do_commit_{i}")).collect();
        let cs = commit_sum.join(" + ");
        v += &format!("            committed_free_head <= (committed_free_head + ({})) % {};\n", cs, self.num_phys_regs);
        v += &format!("            committed_free_cnt <= committed_free_cnt - ({}) + free_valid;\n", cs);
        v += "            if (free_valid) begin\n";
        v += "                free_list[free_tail] <= free_phys;\n";
        v += &format!("                free_tail <= (free_tail + 1) % {};\n", self.num_phys_regs);
        v += "            end\n";
        v += "            free_cnt <= free_cnt + free_valid;\n";

        // Normal operation
        v += "        end else begin\n";
        v += "            // Speculative RAT update (Decode-stage allocation)\n";
        v += "            if (!stall) begin\n";
        for i in 0..self.num_write_ports {
            v += &format!("                if (do_alloc_{i}) begin\n");
            v += &format!("                    rename_table[write_arch_{i}] <= alloc_phys_{i};\n");
            v += "                end\n";
        }
        let alloc_sum: Vec<String> = (0..self.num_write_ports).map(|i| format!("do_alloc_{i}")).collect();
        let als = alloc_sum.join(" + ");
        v += &format!("                free_head <= (free_head + ({})) % {};\n", als, self.num_phys_regs);
        v += "            end\n";

        v += "            // Committed RAT update (Writeback-stage commit)\n";
        for i in 0..self.num_write_ports {
            v += &format!("            if (do_commit_{i}) begin\n");
            v += &format!("                committed_rat[commit_arch_{i}] <= commit_phys_{i};\n");
            v += "            end\n";
        }
        v += &format!("            committed_free_head <= (committed_free_head + ({})) % {};\n", cs, self.num_phys_regs);
        v += &format!("            committed_free_cnt <= committed_free_cnt - ({}) + free_valid;\n", cs);
        v += "            if (free_valid) begin\n";
        v += "                free_list[free_tail] <= free_phys;\n";
        v += &format!("                free_tail <= (free_tail + 1) % {};\n", self.num_phys_regs);
        v += "            end\n";
        let alloc_cnt: Vec<String> = (0..self.num_write_ports).map(|i| format!("(!stall && do_alloc_{i})")).collect();
        let alc = alloc_cnt.join(" + ");
        v += &format!("            free_cnt <= free_cnt - ({}) + free_valid;\n", alc);
        v += "        end\n";
        v += "    end\n\n";

        v += "endmodule\n";
        v
    }
    fn generate_instance(&self, instance_name: &str) -> String {
        format!("{} {}();", self.name, instance_name)
    }
    fn get_ports(&self) -> Vec<PortInfo> { vec![] }
}

// ---------------------------------------------------------------------------
// Factory function: create_module_generator_from_node
// ---------------------------------------------------------------------------

/// Create the appropriate module generator from node data (a HashMap of
/// `serde_json::Value`s, matching the Python ResourceGraph `Node.data`).
pub fn create_module_generator_from_node(
    node_data: &HashMap<String, Value>,
) -> Option<Box<dyn ModuleGenerator>> {
    let node_type = node_data.get("type")?.as_str()?;

    match node_type {
        "multiplexer" => {
            let operation = get_str(node_data, "operation").unwrap_or("binary_select");
            let select_type = match operation {
                "one_hot_select" => MuxSelectType::OneHot,
                "priority_select" => MuxSelectType::Priority,
                _ => MuxSelectType::Binary,
            };

            let data_width = get_u32(node_data, "data_width")
                .or_else(|| get_u32(node_data, "bit_width"))
                .unwrap_or(32);

            Some(Box::new(MuxGenerator::new(
                get_string(node_data, "name").unwrap_or_else(|| "mux".to_string()),
                get_u32(node_data, "num_inputs").unwrap_or(2),
                data_width,
                select_type,
                get_bool(node_data, "has_default").unwrap_or(false),
            )))
        }

        "alu_module" => {
            Some(Box::new(ALUGenerator::new(
                get_string(node_data, "name").unwrap_or_else(|| "alu".to_string()),
                get_u32(node_data, "input_width").unwrap_or(32),
                get_u32(node_data, "output_width").unwrap_or(32),
            )))
        }

        "uarch_counter" | "serialization_counter" | "memory_port_counter"
        | "memory_access_counter" => {
            let width = get_u32(node_data, "width")
                .or_else(|| get_u32(node_data, "bit_width"))
                .unwrap_or(32);
            let max_value = get_u32(node_data, "max_value")
                .or_else(|| get_u32(node_data, "max_count"));

            Some(Box::new(CounterGenerator::new(
                get_string(node_data, "name").unwrap_or_else(|| "counter".to_string()),
                width,
                max_value,
                true,
                true,
                CountDirection::Up,
            )))
        }

        "hazard_detection_unit" | "hazard_detector" => {
            Some(Box::new(HazardDetectorGenerator::new(
                get_string(node_data, "name").unwrap_or_else(|| "hazard_detector".to_string()),
                get_u32(node_data, "num_sources").unwrap_or(2),
                get_u32(node_data, "num_destinations").unwrap_or(2),
                get_u32(node_data, "address_width").unwrap_or(5),
            )))
        }

        "read_only_cache" => Some(Box::new(ReadOnlyCacheGenerator {
            name: get_string(node_data, "name").unwrap_or_else(|| "cache".to_string()),
            num_read_ports: get_u32(node_data, "num_read_ports").unwrap_or(1),
            block_size: get_u32(node_data, "block_size").unwrap_or(32),
            associativity: get_u32(node_data, "associativity").unwrap_or(1),
            num_rows: get_u32(node_data, "num_rows").unwrap_or(64),
            address_width: get_u32(node_data, "address_width").unwrap_or(32),
            data_width: get_u32(node_data, "data_width").unwrap_or(32),
            replacement_policy: get_string(node_data, "replacement_policy")
                .unwrap_or_else(|| "lru".to_string()),
            has_flush: get_bool(node_data, "has_flush_input").unwrap_or(false),
        })),

        "read_write_cache" => Some(Box::new(ReadWriteCacheGenerator {
            name: get_string(node_data, "name").unwrap_or_else(|| "cache".to_string()),
            num_read_ports: get_u32(node_data, "num_read_ports").unwrap_or(1),
            num_write_ports: get_u32(node_data, "num_write_ports").unwrap_or(1),
            block_size: get_u32(node_data, "block_size").unwrap_or(32),
            associativity: get_u32(node_data, "associativity").unwrap_or(1),
            num_rows: get_u32(node_data, "num_rows").unwrap_or(64),
            address_width: get_u32(node_data, "address_width").unwrap_or(32),
            data_width: get_u32(node_data, "data_width").unwrap_or(32),
            replacement_policy: get_string(node_data, "replacement_policy")
                .unwrap_or_else(|| "lru".to_string()),
            write_allocate: get_bool(node_data, "write_allocate").unwrap_or(false),
            write_read_fwd: get_bool(node_data, "write_read_fwd").unwrap_or(false),
        })),

        "tlb_cache" => Some(Box::new(TLBModuleGenerator {
            name: get_string(node_data, "name").unwrap_or_else(|| "tlb".to_string()),
            num_entries: get_u32(node_data, "num_entries").unwrap_or(64),
            associativity: get_u32(node_data, "associativity").unwrap_or(4),
            num_levels: get_u32(node_data, "num_levels").unwrap_or(2),
            vpn_widths: get_u32_array(node_data, "vpn_widths").unwrap_or_else(|| vec![10, 10]),
            pte_width: get_u32(node_data, "pte_width").unwrap_or(32),
            replacement_policy: get_string(node_data, "replacement_policy")
                .unwrap_or_else(|| "lru".to_string()),
            has_flush: get_bool(node_data, "has_flush_input").unwrap_or(true),
        })),

        "instruction_buffer" => Some(Box::new(InstructionBufferGenerator {
            name: get_string(node_data, "name").unwrap_or_else(|| "ibuf".to_string()),
            fetch_width: get_u32(node_data, "fetch_width").unwrap_or(32),
            buffer_size: get_u32(node_data, "buffer_size").unwrap_or(4),
            address_width: get_u32(node_data, "address_width").unwrap_or(32),
            data_width: get_u32(node_data, "data_width").unwrap_or(32),
            has_flush: get_bool(node_data, "has_flush_input").unwrap_or(false),
            output_offsets: get_u32_array(node_data, "output_offsets").unwrap_or_else(|| vec![0]),
        })),

        "btb_storage" => Some(Box::new(BranchTargetBufferGenerator {
            name: get_string(node_data, "name").unwrap_or_else(|| "btb".to_string()),
            num_entries: get_u32(node_data, "num_entries").unwrap_or(64),
            associativity: get_u32(node_data, "associativity").unwrap_or(1),
            pc_width: get_u32(node_data, "pc_width").unwrap_or(32),
            target_width: get_u32(node_data, "target_width").unwrap_or(32),
            dual_port: get_bool(node_data, "dual_port").unwrap_or(false),
        })),

        "renamer" => Some(Box::new(RegisterRenamerGenerator {
            name: get_string(node_data, "name").unwrap_or_else(|| "renamer".to_string()),
            num_arch_regs: get_u32(node_data, "num_arch_regs").unwrap_or(32),
            num_phys_regs: get_u32(node_data, "num_physical_regs").unwrap_or(64),
            num_read_ports: get_u32(node_data, "num_reads").unwrap_or(2),
            num_write_ports: get_u32(node_data, "num_writes").unwrap_or(1),
            arch_reg_width: get_u32(node_data, "arch_reg_width").unwrap_or(5),
        })),

        _ => None,
    }
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

/// Number of bits required to represent `n` (equivalent to Python's `int.bit_length()`).
fn bit_length(n: u32) -> u32 {
    if n == 0 {
        0
    } else {
        32 - n.leading_zeros()
    }
}

/// Ceiling of log2(n), minimum 1.
pub fn ceil_log2(n: u32) -> u32 {
    if n <= 1 {
        1
    } else {
        32 - (n - 1).leading_zeros()
    }
}

fn get_str<'a>(data: &'a HashMap<String, Value>, key: &str) -> Option<&'a str> {
    data.get(key)?.as_str()
}

fn get_string(data: &HashMap<String, Value>, key: &str) -> Option<String> {
    data.get(key)?.as_str().map(|s| s.to_string())
}

fn get_u32(data: &HashMap<String, Value>, key: &str) -> Option<u32> {
    data.get(key)?.as_u64().map(|v| v as u32)
}

fn get_bool(data: &HashMap<String, Value>, key: &str) -> Option<bool> {
    data.get(key)?.as_bool()
}

fn get_u32_array(data: &HashMap<String, Value>, key: &str) -> Option<Vec<u32>> {
    let arr = data.get(key)?.as_array()?;
    arr.iter()
        .map(|v| v.as_u64().map(|n| n as u32))
        .collect()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_binary_mux_4_to_1() {
        let mux = MuxGenerator::new(
            "mux_4to1".to_string(),
            4,
            32,
            MuxSelectType::Binary,
            false,
        );
        let module = mux.generate_module();
        assert!(module.contains("module mux_4to1("));
        assert!(module.contains("input wire [31:0] in_0"));
        assert!(module.contains("input wire [31:0] in_3"));
        assert!(module.contains("input wire [1:0] sel"));
        assert!(module.contains("output logic [31:0] out"));
        assert!(module.contains("case (sel)"));
        assert!(module.contains("2'd0: out = in_0;"));
        assert!(module.contains("2'd3: out = in_3;"));
        assert!(module.contains("endmodule"));
    }

    #[test]
    fn test_one_hot_mux() {
        let mux = MuxGenerator::new(
            "mux_oh".to_string(),
            3,
            16,
            MuxSelectType::OneHot,
            false,
        );
        let module = mux.generate_module();
        assert!(module.contains("module mux_oh("));
        assert!(module.contains("sel_0"));
        assert!(module.contains("sel_2"));
        assert!(module.contains("(sel_0 ? in_0 : 16'd0)"));
    }

    #[test]
    fn test_priority_mux_with_default() {
        let mux = MuxGenerator::new(
            "mux_pri".to_string(),
            2,
            32,
            MuxSelectType::Priority,
            true,
        );
        let module = mux.generate_module();
        assert!(module.contains("input wire [31:0] default_in"));
        assert!(module.contains("if (sel_0) begin"));
        assert!(module.contains("end else if (sel_1) begin"));
        assert!(module.contains("out = default_in;"));
    }

    #[test]
    fn test_priority_mux_zero_inputs() {
        let mux = MuxGenerator::new(
            "mux_empty".to_string(),
            0,
            32,
            MuxSelectType::Priority,
            true,
        );
        let module = mux.generate_module();
        assert!(module.contains("out = default_in;"));
    }

    #[test]
    fn test_counter_up() {
        let ctr = CounterGenerator::new(
            "counter_32b".to_string(),
            32,
            None,
            true,
            true,
            CountDirection::Up,
        );
        let module = ctr.generate_module();
        assert!(module.contains("module counter_32b("));
        assert!(module.contains("input wire [31:0] reset_value"));
        assert!(module.contains("input wire enable"));
        assert!(module.contains("count <= count + 1;"));
    }

    #[test]
    fn test_counter_with_max() {
        let ctr = CounterGenerator::new(
            "ctr".to_string(),
            8,
            Some(255),
            true,
            false,
            CountDirection::Up,
        );
        let module = ctr.generate_module();
        assert!(module.contains("if (count >= 8'd255)"));
        assert!(module.contains("count <= 8'd0;"));
    }

    #[test]
    fn test_counter_down_with_max() {
        let ctr = CounterGenerator::new(
            "ctr_down".to_string(),
            4,
            Some(10),
            false,
            false,
            CountDirection::Down,
        );
        let module = ctr.generate_module();
        assert!(module.contains("if (count == 4'd0)"));
        assert!(module.contains("count <= 4'd10;"));
        assert!(module.contains("count <= count - 1;"));
    }

    #[test]
    fn test_latency_counter_static() {
        let lc = LatencyCounterGenerator::new(
            "lc_static".to_string(),
            4,
            LatencyMode::Static,
            3,
            2,
            15,
        );
        let il = lc.generate_inline_logic("cnt", None, "go", "done", Some("is_idle"));
        assert!(il.declarations.contains("reg [1:0] cnt"));
        assert!(il.comb_logic.contains("assign done = (cnt == 2'd3)"));
        assert!(il.comb_logic.contains("assign is_idle = (cnt == 2'd0)"));
        assert!(il.seq_logic.contains("3-cycle stall"));
    }

    #[test]
    fn test_latency_counter_zero() {
        let lc = LatencyCounterGenerator::new(
            "lc_zero".to_string(),
            4,
            LatencyMode::Static,
            0,
            0,
            0,
        );
        let il = lc.generate_inline_logic("cnt", None, "go", "done", Some("is_idle"));
        assert!(il.comb_logic.contains("assign done = 1'b1"));
        assert!(il.comb_logic.contains("assign is_idle = 1'b1"));
    }

    #[test]
    fn test_latency_counter_variable() {
        let lc = LatencyCounterGenerator::new(
            "lc_var".to_string(),
            4,
            LatencyMode::Variable,
            2,
            2,
            15,
        );
        let il = lc.generate_inline_logic("cnt", Some("tgt"), "start", "done", None);
        assert!(il.declarations.contains("reg [3:0] cnt"));
        assert!(il.declarations.contains("reg [3:0] tgt"));
        assert!(il.comb_logic.contains("(cnt != 4'd0) && (cnt == tgt)"));
        assert!(il.seq_logic.contains("$random"));
    }

    #[test]
    fn test_mux_port_connections_binary() {
        let mux = MuxGenerator::new(
            "my_mux".to_string(),
            2,
            32,
            MuxSelectType::Binary,
            false,
        );
        let result = mux.get_port_connections(
            &["sig_a".to_string(), "sig_b".to_string()],
            &SelectSignal::Vector("ctrl".to_string()),
            "result",
            None,
        );
        assert!(result.contains(".in_0(sig_a)"));
        assert!(result.contains(".in_1(sig_b)"));
        assert!(result.contains(".sel(ctrl)"));
        assert!(result.contains(".out(result)"));
    }

    #[test]
    fn test_mux_port_connections_one_hot() {
        let mux = MuxGenerator::new(
            "oh_mux".to_string(),
            2,
            32,
            MuxSelectType::OneHot,
            false,
        );
        let sels = SelectSignal::Individual(vec!["s0".to_string(), "s1".to_string()]);
        let result = mux.get_port_connections(
            &["a".to_string(), "b".to_string()],
            &sels,
            "y",
            None,
        );
        assert!(result.contains(".sel_0(s0)"));
        assert!(result.contains(".sel_1(s1)"));
    }

    #[test]
    fn test_create_module_generator_mux() {
        let mut data = HashMap::new();
        data.insert("type".to_string(), Value::String("multiplexer".to_string()));
        data.insert("name".to_string(), Value::String("test_mux".to_string()));
        data.insert("num_inputs".to_string(), Value::Number(4.into()));
        data.insert(
            "operation".to_string(),
            Value::String("one_hot_select".to_string()),
        );

        let gen = create_module_generator_from_node(&data);
        assert!(gen.is_some());
        let module = gen.unwrap().generate_module();
        assert!(module.contains("module test_mux("));
        assert!(module.contains("sel_0"));
    }

    #[test]
    fn test_create_module_generator_counter() {
        let mut data = HashMap::new();
        data.insert(
            "type".to_string(),
            Value::String("uarch_counter".to_string()),
        );
        data.insert("name".to_string(), Value::String("my_ctr".to_string()));
        data.insert("width".to_string(), Value::Number(8.into()));
        data.insert("max_value".to_string(), Value::Number(100.into()));

        let gen = create_module_generator_from_node(&data);
        assert!(gen.is_some());
        let module = gen.unwrap().generate_module();
        assert!(module.contains("module my_ctr("));
    }

    #[test]
    fn test_create_module_generator_unknown_returns_none() {
        let mut data = HashMap::new();
        data.insert(
            "type".to_string(),
            Value::String("unknown_type".to_string()),
        );
        assert!(create_module_generator_from_node(&data).is_none());
    }

    #[test]
    fn test_alu_generator() {
        let alu = ALUGenerator::new("alu_32b".to_string(), 32, 32);
        let module = alu.generate_module();
        assert!(module.contains("module alu_32b("));
        assert!(module.contains("operand_a"));
        assert!(module.contains("operand_b"));
        assert!(module.contains("zero_flag"));
        assert!(module.contains("case (opcode)"));
    }

    #[test]
    fn test_hazard_detector_generator() {
        let hd = HazardDetectorGenerator::new("haz_det".to_string(), 2, 2, 5);
        let module = hd.generate_module();
        assert!(module.contains("module haz_det("));
        assert!(module.contains("src_0_addr"));
        assert!(module.contains("dest_1_ready"));
        assert!(module.contains("stall"));
        assert!(module.contains("forward_src_0"));
    }

    #[test]
    fn test_get_ports_mux_binary() {
        let mux = MuxGenerator::new("m".to_string(), 3, 8, MuxSelectType::Binary, false);
        let ports = mux.get_ports();
        // 3 inputs + sel + out = 5
        assert_eq!(ports.len(), 5);
        assert_eq!(ports[3].name, "sel");
        assert_eq!(ports[3].width, 2); // ceil(log2(3)) = 2
    }

    #[test]
    fn test_bit_length() {
        assert_eq!(bit_length(0), 0);
        assert_eq!(bit_length(1), 1);
        assert_eq!(bit_length(2), 2);
        assert_eq!(bit_length(3), 2);
        assert_eq!(bit_length(4), 3);
        assert_eq!(bit_length(7), 3);
        assert_eq!(bit_length(8), 4);
    }

    #[test]
    fn test_ceil_log2() {
        assert_eq!(ceil_log2(1), 1);
        assert_eq!(ceil_log2(2), 1);
        assert_eq!(ceil_log2(3), 2);
        assert_eq!(ceil_log2(4), 2);
        assert_eq!(ceil_log2(5), 3);
    }
}
