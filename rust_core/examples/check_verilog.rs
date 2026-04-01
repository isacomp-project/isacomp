use isacomp_core::graph_merger::ResourceGraphMerger;
use isacomp_core::verilog_generator;

fn main() {
    let base = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().join("riscv32");
    let instructions = ["add", "addi", "sub", "lui"];
    let mut merger = ResourceGraphMerger::new(None);
    for name in &instructions {
        let path = base.join(format!("{}.isa", name));
        merger.add_instruction(name, &path.to_string_lossy()).unwrap();
    }
    let merged = merger.merge_graphs(Some("pc")).unwrap();

    // Debug: print memory_write_port, shared_wr, and write_enable-related nodes
    for (nid, node) in &merged.nodes {
        let ntype = node.data.get("type").and_then(|v| v.as_str()).unwrap_or("?");
        if ntype == "memory_write_port" || nid.contains("shared_wr") || nid.contains("rf[rd]") || nid.contains("write_enable") || nid.contains("rd_ne") {
            eprintln!("\nNODE {} : type={}", nid, ntype);
            eprintln!("  data keys: {:?}", node.data.keys().collect::<Vec<_>>());
            for eid in &node.incoming_edges {
                if let Some(e) = merged.edges.get(eid) {
                    let et = e.data.get("type").and_then(|v| v.as_str()).unwrap_or("?");
                    eprintln!("  <- {} [{}]", e.source, et);
                }
            }
            for eid in &node.outgoing_edges {
                if let Some(e) = merged.edges.get(eid) {
                    let et = e.data.get("type").and_then(|v| v.as_str()).unwrap_or("?");
                    eprintln!("  -> {} [{}]", e.target, et);
                }
            }
        }
    }

    // Debug: check write_enable edges specifically
    eprintln!("\n--- write_enable edges ---");
    for (eid, edge) in &merged.edges {
        let et = edge.data.get("type").and_then(|v| v.as_str()).unwrap_or("?");
        if et == "write_enable" {
            eprintln!("  {} -> {} [{}]", edge.source, edge.target, et);
        }
    }

    let verilog = verilog_generator::generate_verilog(&merged, "riscv32i_test");
    std::fs::write("/tmp/rust_4instr.v", &verilog).unwrap();
    eprintln!("\nVerilog: {} lines", verilog.lines().count());
}
