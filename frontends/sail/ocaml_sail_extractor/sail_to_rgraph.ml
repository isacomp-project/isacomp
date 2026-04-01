(****************************************************************************)
(* SAIL to ResourceGraph Extractor                                          *)
(*                                                                          *)
(* Standalone tool to extract RISC-V instruction semantics from SAIL       *)
(* specifications and output ResourceGraph JSON for isacomp                 *)
(****************************************************************************)

open Libsail
open Ast
open Ast_defs
module Big_int = Nat_big_num

(* JSON generation helpers *)
module JSON = struct
  let escape_string s =
    let buf = Buffer.create (String.length s) in
    String.iter (fun c ->
      match c with
      | '"' -> Buffer.add_string buf "\\\""
      | '\\' -> Buffer.add_string buf "\\\\"
      | '\n' -> Buffer.add_string buf "\\n"
      | '\r' -> Buffer.add_string buf "\\r"
      | '\t' -> Buffer.add_string buf "\\t"
      | c -> Buffer.add_char buf c
    ) s;
    Buffer.contents buf

  let string s = Printf.sprintf "\"%s\"" (escape_string s)
  let int i = string_of_int i
  let bool b = if b then "true" else "false"
  let option f = function
    | None -> "null"
    | Some v -> f v

  let field name value = Printf.sprintf "\"%s\": %s" name value
  let obj fields = Printf.sprintf "{%s}" (String.concat ", " fields)
  let array items = Printf.sprintf "[%s]" (String.concat ", " items)
end

(* ResourceGraph data structures *)
type rg_node_id = string
type rg_edge_id = string

type rg_node = {
  id: rg_node_id;
  node_type: string;
  name: string option;  (* identifier name - required by Verilog generator for var nodes *)
  display_name: string option;
  operator: string option;
  value: string option;
  bit_width: int option;
  is_arch_state: bool;
  is_memory: bool;
  array_size: int option;
  array_depth: int option;  (* address width in bits for memory/array nodes *)
  bitslice: (int * int) option;  (* (high, low) for bit_slice nodes *)
  dimensions: (int * int) list option;  (* [(high, low), ...] for multi-dimensional arrays *)
}

type rg_edge = {
  id: rg_edge_id;
  source: rg_node_id;
  target: rg_node_id;
  edge_type: string;
  position: string option;  (* operand position: "left", "right", or None *)
  enable: rg_node_id option;  (* write enable condition node ID *)
}

type decode_constraint = {
  high_bit: int;
  low_bit: int;
  value: string;
  operator: string;  (* "==" or "!=" *)
}

type rg_graph = {
  nodes: rg_node list;
  edges: rg_edge list;
  decode_constraints: decode_constraint list;
}

(* ID generation *)
let node_counter = ref 0
let edge_counter = ref 0

let fresh_node_id () =
  let id = !node_counter in
  incr node_counter;
  Printf.sprintf "n%d" id

let fresh_edge_id () =
  let id = !edge_counter in
  incr edge_counter;
  Printf.sprintf "e%d" id

(* Node constructor with defaults *)
let make_node ?(name=None) ?(display_name=None) ?(operator=None) ?(value=None)
              ?(bit_width=None) ?(is_arch_state=false) ?(is_memory=false)
              ?(array_size=None) ?(array_depth=None) ?(bitslice=None) ?(dimensions=None) node_type =
  (* Debug: Track wX_bits node creation *)
  (match operator with
  | Some "wX_bits" ->
      Printf.printf "        *** CREATING wX_bits NODE: type=%s, display=%s ***\n%!"
        node_type (Option.value ~default:"None" display_name)
  | _ -> ());
  (* name defaults to display_name if not explicitly provided *)
  let name = match name with
    | Some _ -> name
    | None -> display_name
  in
  {
    id = fresh_node_id ();
    node_type;
    name;
    display_name;
    operator;
    value;
    bit_width;
    is_arch_state;
    is_memory;
    array_size;
    array_depth;
    bitslice;
    dimensions;
  }

(* Graph builder *)
module GraphBuilder = struct
  type t = {
    mutable nodes: rg_node list;
    mutable edges: rg_edge list;
    mutable helper_graphs: (string, rg_graph) Hashtbl.t;  (* Store helper functions for inlining *)
    mutable decode_constraints: (int * int * string) list;  (* (high_bit, low_bit, value) *)
    mutable match_counter: int;  (* Counter for unique match node names *)
    mutable instr_prefix: string;  (* Instruction name prefix for unique naming *)
    mutable global_constants: (string, int) Hashtbl.t;  (* Global constant values from let bindings *)
    mutable memory_access_width: int option;  (* Known memory access width in bytes (1=byte, 2=half, 4=word) for per-width splitting *)
    mutable memory_is_unsigned: bool;  (* For loads: true = zero-extend, false = sign-extend *)
    mutable m_ext_variant: string option;  (* M-extension variant: "mul", "mulh", "mulhsu", "mulhu", "div", "divu", "rem", "remu" *)
  }

  let create () = { nodes = []; edges = []; helper_graphs = Hashtbl.create 10; decode_constraints = []; match_counter = 0; instr_prefix = ""; global_constants = Hashtbl.create 10; memory_access_width = None; memory_is_unsigned = false; m_ext_variant = None }

  let create_with_helpers helper_tbl = { nodes = []; edges = []; helper_graphs = helper_tbl; decode_constraints = []; match_counter = 0; instr_prefix = ""; global_constants = Hashtbl.create 10; memory_access_width = None; memory_is_unsigned = false; m_ext_variant = None }

  let add_node builder rg_node =
    builder.nodes <- rg_node :: builder.nodes;
    rg_node

  let add_edge builder rg_edge =
    builder.edges <- rg_edge :: builder.edges;
    rg_edge

  (* Names that should NOT be prefixed (architectural state and shared decode fields) *)
  let arch_state_names = ["rf"; "pc_rd"; "pc_wr"; "imem"; "dmem"; "csr"; "frf"; "fcsr"; "instr";
                          "PC"; "rs1"; "rs2"; "rd"; "funct3"; "funct7"; "opcode"]

  (* Prefix a local variable name with instruction prefix if applicable *)
  let prefix_local_name builder name =
    (* Replace SAIL prime (') with _v to avoid name collisions in Verilog sanitization.
       Without this, rm' becomes rm_ which sanitizes to rm (same as the unprime'd variable). *)
    let name = String.concat "_v" (String.split_on_char '\'' name) in
    if builder.instr_prefix <> "" && not (List.mem name arch_state_names) then
      Printf.sprintf "%s_%s" builder.instr_prefix name
    else
      name

  (* Find a node by display_name (tries both prefixed and unprefixed) *)
  let find_node builder name =
    let prefixed = prefix_local_name builder name in
    List.find_opt (fun n ->
      match n.display_name with
      | Some dn -> dn = name || dn = prefixed
      | None -> false
    ) builder.nodes

  (* Edge constructor *)
  let make_edge ?(position=None) ?(enable=None) (source : rg_node) (target : rg_node) (edge_type_str : string) : rg_edge =
    {
      id = fresh_edge_id ();
      source = source.id;
      target = target.id;
      edge_type = edge_type_str;
      position = position;
      enable = enable;
    }

  (* Helper to create and add an rg_edge in one step *)
  let connect ?(position=None) ?(enable=None) (builder : t) (source : rg_node) (target : rg_node) (edge_type_str : string) : unit =
    let rg_edge = make_edge ~position ~enable source target edge_type_str in
    ignore (add_edge builder rg_edge)

  (* Try to resolve an rg_node to a constant integer value.
     Handles literals and single-level arithmetic on literals. *)
  let rec try_resolve_constant (builder : t) (node : rg_node) : int option =
    match node.node_type, node.value with
    | "literal", Some v -> (try Some (int_of_string v) with _ -> None)
    | _ ->
      (match node.operator with
       | Some "+" | Some "-" ->
         (* Find operand edges to this node, respecting left/right positions *)
         let operand_edges = List.filter (fun (e : rg_edge) ->
           e.target = node.id && e.edge_type = "operand"
         ) builder.edges in
         let left_node = List.find_map (fun (e : rg_edge) ->
           if e.position = Some "left" then
             List.find_opt (fun (n : rg_node) -> n.id = e.source) builder.nodes
           else None
         ) operand_edges in
         let right_node = List.find_map (fun (e : rg_edge) ->
           if e.position = Some "right" then
             List.find_opt (fun (n : rg_node) -> n.id = e.source) builder.nodes
           else None
         ) operand_edges in
         (match left_node, right_node with
          | Some left, Some right ->
            let va = try_resolve_constant builder left in
            let vb = try_resolve_constant builder right in
            (match va, vb, node.operator with
             | Some a, Some b, Some "+" -> Some (a + b)
             | Some a, Some b, Some "-" -> Some (a - b)
             | _ -> None)
          | _ ->
            (* Fallback: try positional (only safe for commutative ops) *)
            let operand_nodes = List.filter_map (fun (e : rg_edge) ->
              List.find_opt (fun (n : rg_node) -> n.id = e.source) builder.nodes
            ) operand_edges in
            (match operand_nodes, node.operator with
             | [a; b], Some "+" ->
               (match try_resolve_constant builder a, try_resolve_constant builder b with
                | Some a, Some b -> Some (a + b) | _ -> None)
             | _ -> None))
       | _ -> None)

  let to_graph (builder : t) : rg_graph =
    (* Cleanup: Find and replace width_select nodes marked with "REPLACE_WITH_" *)
    let replacement_map = Hashtbl.create 10 in

    (* Build replacement mapping from marked nodes *)
    List.iter (fun (n : rg_node) ->
      match n.display_name with
      | Some name when String.starts_with ~prefix:"REPLACE_WITH_" name ->
          let replacement_id = String.sub name 13 (String.length name - 13) in  (* Skip "REPLACE_WITH_" *)
          Hashtbl.add replacement_map n.id replacement_id;
          Printf.printf "      Cleanup: will replace node %s with %s\n%!" n.id replacement_id
      | _ -> ()
    ) builder.nodes;

    (* Redirect edges *)
    let cleaned_edges = List.map (fun (e : rg_edge) ->
      match Hashtbl.find_opt replacement_map e.source with
      | Some new_source -> {e with source = new_source}
      | None -> e
    ) builder.edges in

    (* Remove marked nodes and their incoming edges *)
    let marked_ids = Hashtbl.fold (fun k _ acc -> k :: acc) replacement_map [] in
    let cleaned_nodes = List.filter (fun (n : rg_node) ->
      not (List.mem n.id marked_ids)
    ) builder.nodes in
    let final_edges = List.filter (fun (e : rg_edge) ->
      not (List.mem e.target marked_ids)
    ) cleaned_edges in

    if Hashtbl.length replacement_map > 0 then
      Printf.printf "    Cleanup complete: replaced %d nodes\n%!" (Hashtbl.length replacement_map);

    (* Convert decode constraints to typed records *)
    let constraints = List.rev_map (fun (h, l, v) ->
      if String.length v > 0 && v.[0] = '!' then
        { high_bit = h; low_bit = l; value = String.sub v 1 (String.length v - 1); operator = "!=" }
      else
        { high_bit = h; low_bit = l; value = v; operator = "==" }
    ) builder.decode_constraints in

    { nodes = List.rev cleaned_nodes; edges = List.rev final_edges; decode_constraints = constraints }

  (* Initialize architectural state nodes that isacomp expects *)
  let add_architectural_state ?(use_real_fetch=false) builder =
    (* Add instruction word register - NOT architectural state, computed from imem[pc] *)
    let instr_node = make_node
      ~display_name:(Some "instr")
      ~bit_width:(Some 32)
      ~is_arch_state:false
      "var" in
    let _ = add_node builder instr_node in

    (* Add program counter - split into read and write *)
    let pc_rd_node = make_node
      ~display_name:(Some "pc_rd")
      ~bit_width:(Some 32)
      ~is_arch_state:true
      "isa_state" in
    let _ = add_node builder pc_rd_node in

    let pc_wr_node = make_node
      ~display_name:(Some "pc_wr")
      ~bit_width:(Some 32)
      ~is_arch_state:true
      "isa_state" in
    let _ = add_node builder pc_wr_node in

    (* Add register file as architectural array *)
    let rf_node = make_node
      ~display_name:(Some "rf")
      ~is_arch_state:true
      ~bit_width:(Some 32)
      ~is_memory:true
      ~array_size:(Some 32)
      ~array_depth:(Some 5)  (* 5-bit address = 32 registers *)
      ~dimensions:(Some [(31, 0); (4, 0)])  (* [data_width][index_width] *)
      "isa_state" in
    let _ = add_node builder rf_node in

    (* Add instruction memory as architectural array *)
    let imem_node = make_node
      ~display_name:(Some "imem")
      ~bit_width:(Some 32)
      ~dimensions:(Some [(31, 0); (12, 0)])
      ~is_arch_state:true
      ~is_memory:true
      ~array_size:(Some 1024)
      ~array_depth:(Some 13)  (* 13-bit byte address *)
      "isa_state" in
    let _ = add_node builder imem_node in

    (* Add data memory as architectural array — 64-bit doubleword-indexed for D extension.
       Dimensions: [(data_high, data_low), (addr_high, addr_low)]
       With 64-bit data doublewords and 13-bit address (8192 entries). *)
    let dmem_node = make_node
      ~display_name:(Some "dmem")
      ~bit_width:(Some 64)
      ~dimensions:(Some [(63, 0); (12, 0)])  (* 64-bit data, 13-bit address *)
      ~is_arch_state:true
      ~is_memory:true
      ~array_size:(Some 8192)
      ~array_depth:(Some 13)
      "isa_state" in
    let _ = add_node builder dmem_node in

    (* Add CSR register file as architectural array *)
    (* CSRs are indexed by 12-bit address (4096 entries), each 32 bits wide *)
    let _csr_node = make_node
      ~display_name:(Some "csr")
      ~bit_width:(Some 32)
      ~dimensions:(Some [(31, 0); (11, 0)])  (* 32-bit data, 12-bit address *)
      ~is_arch_state:true
      ~is_memory:true
      ~array_size:(Some 4096)
      ~array_depth:(Some 12)  (* 12-bit address = 4096 CSRs *)
      "isa_state" in
    let _ = add_node builder _csr_node in

    (* Only add synthetic fetch if NOT using real fetch function *)
    if not use_real_fetch then begin
      (* Add word-address shift: pc_word_addr = pc_rd[31:2] (byte to word address) *)
      let pc_word_addr = make_node
        ~display_name:(Some "pc_rd[31:2]")
        ~bitslice:(Some (31, 2))
        ~bit_width:(Some 30)
        "bit_slice" in
      let pc_word_addr = add_node builder pc_word_addr in
      connect builder pc_rd_node pc_word_addr "bit_access";

      (* Add synthetic fetch: instr = imem[pc_rd[31:2]] *)
      let fetch_node = make_node
        ~display_name:(Some "imem[pc_rd]")
        ~operator:(Some "array_access")
        "array_access" in
      let fetch_node = add_node builder fetch_node in

      (* Connect: imem -> fetch (array being accessed) *)
      connect builder imem_node fetch_node "array_base";
      (* Connect: pc_word_addr -> fetch (word-addressed index) *)
      connect builder pc_word_addr fetch_node "array_index";
      (* Connect: fetch -> instr (assignment, since instr is a var) *)
      connect builder fetch_node instr_node "assignment"
    end;

    ()

  (* Helper: find or create a named ISA state node *)
  let find_or_create_state builder name width =
    match find_node builder name with
    | Some node -> node
    | None ->
        let node = make_node ~display_name:(Some name) ~bit_width:(Some width)
          ~is_arch_state:true "isa_state" in
        add_node builder node

  (* Add privilege-mode state nodes for system instructions *)
  let add_privilege_state builder =
    let _priv = find_or_create_state builder "priv_mode" 2 in
    let _mstatus = find_or_create_state builder "mstatus" 32 in
    let _mepc = find_or_create_state builder "mepc" 32 in
    let _mcause = find_or_create_state builder "mcause" 32 in
    let _mtval = find_or_create_state builder "mtval" 32 in
    let _mtvec = find_or_create_state builder "mtvec" 32 in
    let _sepc = find_or_create_state builder "sepc" 32 in
    let _scause = find_or_create_state builder "scause" 32 in
    let _stval = find_or_create_state builder "stval" 32 in
    let _stvec = find_or_create_state builder "stvec" 32 in
    let _medeleg = find_or_create_state builder "medeleg" 32 in
    let _mie = find_or_create_state builder "mie" 32 in
    let _satp = find_or_create_state builder "satp" 32 in
    ()

  (* Emit concrete MRET graph: pc <- mepc, restore privilege from mstatus.MPP *)
  let emit_mret_graph builder =
    add_privilege_state builder;
    let mepc = find_or_create_state builder "mepc" 32 in
    let mstatus = find_or_create_state builder "mstatus" 32 in
    let priv = find_or_create_state builder "priv_mode" 2 in

    (* pc_wr <- mepc *)
    let pc_wr = match find_node builder "pc_wr" with
      | Some n -> n | None -> find_or_create_state builder "pc_wr" 32 in
    connect builder mepc pc_wr "assignment";

    (* Extract mstatus.MPP [12:11] -> new privilege *)
    let mpp_slice = make_node ~display_name:(Some "mstatus.MPP")
      ~operator:(Some "bit_slice") ~bit_width:(Some 2)
      ~bitslice:(Some (12, 11)) "bit_slice" in
    let mpp_slice = add_node builder mpp_slice in
    connect builder mstatus mpp_slice "bit_access";

    (* priv_mode <- mstatus.MPP *)
    connect builder mpp_slice priv "assignment";

    (* Extract mstatus.MPIE [7] *)
    let mpie_slice = make_node ~display_name:(Some "mstatus.MPIE")
      ~operator:(Some "bit_slice") ~bit_width:(Some 1)
      ~bitslice:(Some (7, 7)) "bit_slice" in
    let mpie_slice = add_node builder mpie_slice in
    connect builder mstatus mpie_slice "bit_access";

    (* mstatus update: MIE <- MPIE, MPIE <- 1, MPP <- User(0) *)
    let mstatus_update = make_node ~display_name:(Some "mstatus_mret_update")
      ~operator:(Some "mret_mstatus_update") ~bit_width:(Some 32) "operation" in
    let mstatus_update = add_node builder mstatus_update in
    connect builder mstatus mstatus_update "operand";
    connect builder mpie_slice mstatus_update "operand";
    connect builder mstatus_update mstatus "assignment";

    Printf.printf "    Emitted concrete MRET graph\n%!"

  (* Emit concrete SRET graph: pc <- sepc, restore privilege from mstatus.SPP *)
  let emit_sret_graph builder =
    add_privilege_state builder;
    let sepc = find_or_create_state builder "sepc" 32 in
    let mstatus = find_or_create_state builder "mstatus" 32 in
    let priv = find_or_create_state builder "priv_mode" 2 in

    (* pc_wr <- sepc *)
    let pc_wr = match find_node builder "pc_wr" with
      | Some n -> n | None -> find_or_create_state builder "pc_wr" 32 in
    connect builder sepc pc_wr "assignment";

    (* Extract mstatus.SPP [8] -> new privilege (0=User, 1=Supervisor) *)
    let spp_slice = make_node ~display_name:(Some "mstatus.SPP")
      ~operator:(Some "bit_slice") ~bit_width:(Some 1)
      ~bitslice:(Some (8, 8)) "bit_slice" in
    let spp_slice = add_node builder spp_slice in
    connect builder mstatus spp_slice "bit_access";

    (* priv_mode <- zero_extend(mstatus.SPP) *)
    let spp_ext = make_node ~display_name:(Some "zero_extend(SPP)")
      ~operator:(Some "zero_extend") ~bit_width:(Some 2) "operation" in
    let spp_ext = add_node builder spp_ext in
    connect builder spp_slice spp_ext "operand";
    connect builder spp_ext priv "assignment";

    (* mstatus update: SIE <- SPIE, SPIE <- 1, SPP <- 0 *)
    let spie_slice = make_node ~display_name:(Some "mstatus.SPIE")
      ~operator:(Some "bit_slice") ~bit_width:(Some 1)
      ~bitslice:(Some (5, 5)) "bit_slice" in
    let spie_slice = add_node builder spie_slice in
    connect builder mstatus spie_slice "bit_access";

    let mstatus_update = make_node ~display_name:(Some "mstatus_sret_update")
      ~operator:(Some "sret_mstatus_update") ~bit_width:(Some 32) "operation" in
    let mstatus_update = add_node builder mstatus_update in
    connect builder mstatus mstatus_update "operand";
    connect builder spie_slice mstatus_update "operand";
    connect builder mstatus_update mstatus "assignment";

    Printf.printf "    Emitted concrete SRET graph\n%!"

  (* Emit concrete ECALL graph: trap to appropriate privilege level *)
  let emit_ecall_graph builder =
    add_privilege_state builder;
    let priv = find_or_create_state builder "priv_mode" 2 in
    let mstatus = find_or_create_state builder "mstatus" 32 in
    let mepc = find_or_create_state builder "mepc" 32 in
    let mcause = find_or_create_state builder "mcause" 32 in
    let mtval = find_or_create_state builder "mtval" 32 in
    let mtvec = find_or_create_state builder "mtvec" 32 in
    let medeleg = find_or_create_state builder "medeleg" 32 in

    let pc_rd = match find_node builder "pc_rd" with
      | Some n -> n | None -> find_or_create_state builder "pc_rd" 32 in
    let pc_wr = match find_node builder "pc_wr" with
      | Some n -> n | None -> find_or_create_state builder "pc_wr" 32 in

    (* Compute exception cause: 8 + priv_mode *)
    let cause_base = make_node ~display_name:(Some "8") ~value:(Some "8")
      ~bit_width:(Some 32) "literal" in
    let cause_base = add_node builder cause_base in
    let cause_ext = make_node ~display_name:(Some "zero_extend(priv)")
      ~operator:(Some "zero_extend") ~bit_width:(Some 32) "operation" in
    let cause_ext = add_node builder cause_ext in
    connect builder priv cause_ext "operand";
    let cause_val = make_node ~display_name:(Some "8 + priv_mode")
      ~operator:(Some "+") ~bit_width:(Some 32) "operation" in
    let cause_val = add_node builder cause_val in
    connect builder cause_base cause_val "operand";
    connect builder cause_ext cause_val "operand";

    (* mepc <- pc *)
    connect builder pc_rd mepc "assignment";

    (* mcause <- cause *)
    connect builder cause_val mcause "assignment";

    (* mtval <- 0 *)
    let zero32 = make_node ~display_name:(Some "0") ~value:(Some "0")
      ~bit_width:(Some 32) "literal" in
    let zero32 = add_node builder zero32 in
    connect builder zero32 mtval "assignment";

    (* mstatus update: MPIE <- MIE, MIE <- 0, MPP <- cur_priv *)
    let mstatus_update = make_node ~display_name:(Some "mstatus_ecall_update")
      ~operator:(Some "ecall_mstatus_update") ~bit_width:(Some 32) "operation" in
    let mstatus_update = add_node builder mstatus_update in
    connect builder mstatus mstatus_update "operand";
    connect builder priv mstatus_update "operand";
    connect builder mstatus_update mstatus "assignment";

    (* Delegation check: if medeleg[cause] then trap to S-mode, else M-mode *)
    (* For simplicity, model as: target_priv = medeleg[cause] ? S : M *)
    let deleg_check = make_node ~display_name:(Some "medeleg[cause]")
      ~operator:(Some "bit_select") ~bit_width:(Some 1) "operation" in
    let deleg_check = add_node builder deleg_check in
    connect builder medeleg deleg_check "operand";
    connect builder cause_val deleg_check "operand";

    (* pc <- mtvec (base address, simplified — ignoring vectored mode) *)
    let mtvec_base = make_node ~display_name:(Some "mtvec.BASE")
      ~operator:(Some "bit_slice") ~bit_width:(Some 30)
      ~bitslice:(Some (31, 2)) "bit_slice" in
    let mtvec_base = add_node builder mtvec_base in
    connect builder mtvec mtvec_base "bit_access";

    let mtvec_addr = make_node ~display_name:(Some "mtvec.BASE << 2")
      ~operator:(Some "<<") ~bit_width:(Some 32) "operation" in
    let mtvec_addr = add_node builder mtvec_addr in
    let two = make_node ~display_name:(Some "2") ~value:(Some "2")
      ~bit_width:(Some 32) "literal" in
    let two = add_node builder two in
    connect builder mtvec_base mtvec_addr "operand";
    connect builder two mtvec_addr "operand";

    connect builder mtvec_addr pc_wr "assignment";

    (* Connect delegation check as metadata *)
    ignore deleg_check;

    Printf.printf "    Emitted concrete ECALL graph\n%!"

  (* Emit concrete WFI graph: pc <- pc + 4 (NOP-like, wait for interrupt) *)
  let emit_wfi_graph builder =
    let pc_rd = match find_node builder "pc_rd" with
      | Some n -> n | None -> find_or_create_state builder "pc_rd" 32 in
    let pc_wr = match find_node builder "pc_wr" with
      | Some n -> n | None -> find_or_create_state builder "pc_wr" 32 in
    let four = make_node ~display_name:(Some "4") ~value:(Some "4")
      ~bit_width:(Some 32) "literal" in
    let four = add_node builder four in
    let add_node_ = make_node ~display_name:(Some "pc + 4")
      ~operator:(Some "+") ~bit_width:(Some 32) "operation" in
    let add_node_ = add_node builder add_node_ in
    connect builder pc_rd add_node_ "operand";
    connect builder four add_node_ "operand";
    connect builder add_node_ pc_wr "assignment";
    Printf.printf "    Emitted concrete WFI graph\n%!"

  (* Emit concrete SFENCE_VMA graph: pc <- pc + 4 + TLB flush signal *)
  let emit_sfence_vma_graph builder =
    let pc_rd = match find_node builder "pc_rd" with
      | Some n -> n | None -> find_or_create_state builder "pc_rd" 32 in
    let pc_wr = match find_node builder "pc_wr" with
      | Some n -> n | None -> find_or_create_state builder "pc_wr" 32 in
    let four = make_node ~display_name:(Some "4") ~value:(Some "4")
      ~bit_width:(Some 32) "literal" in
    let four = add_node builder four in
    let add_node_ = make_node ~display_name:(Some "pc + 4")
      ~operator:(Some "+") ~bit_width:(Some 32) "operation" in
    let add_node_ = add_node builder add_node_ in
    connect builder pc_rd add_node_ "operand";
    connect builder four add_node_ "operand";
    connect builder add_node_ pc_wr "assignment";
    (* TLB flush signal *)
    let flush_node = make_node ~display_name:(Some "tlb_flush")
      ~operator:(Some "flush") ~bit_width:(Some 1) "operation" in
    let _ = add_node builder flush_node in
    Printf.printf "    Emitted concrete SFENCE_VMA graph\n%!"

  (* Emit concrete FENCEI graph: pc <- pc + 4 + icache flush signal *)
  let emit_fencei_graph builder =
    let pc_rd = match find_node builder "pc_rd" with
      | Some n -> n | None -> find_or_create_state builder "pc_rd" 32 in
    let pc_wr = match find_node builder "pc_wr" with
      | Some n -> n | None -> find_or_create_state builder "pc_wr" 32 in
    let four = make_node ~display_name:(Some "4") ~value:(Some "4")
      ~bit_width:(Some 32) "literal" in
    let four = add_node builder four in
    let add_node_ = make_node ~display_name:(Some "pc + 4")
      ~operator:(Some "+") ~bit_width:(Some 32) "operation" in
    let add_node_ = add_node builder add_node_ in
    connect builder pc_rd add_node_ "operand";
    connect builder four add_node_ "operand";
    connect builder add_node_ pc_wr "assignment";
    (* Icache flush signal *)
    let flush_node = make_node ~display_name:(Some "icache_flush")
      ~operator:(Some "flush") ~bit_width:(Some 1) "operation" in
    let _ = add_node builder flush_node in
    Printf.printf "    Emitted concrete FENCEI graph\n%!"

  (* Emit concrete EBREAK graph: mepc <- pc; mcause <- 3; pc <- mtvec *)
  let emit_ebreak_graph builder =
    add_privilege_state builder;
    let pc_rd = match find_node builder "pc_rd" with
      | Some n -> n | None -> find_or_create_state builder "pc_rd" 32 in
    let pc_wr = match find_node builder "pc_wr" with
      | Some n -> n | None -> find_or_create_state builder "pc_wr" 32 in
    let mepc = find_or_create_state builder "mepc" 32 in
    let mcause = find_or_create_state builder "mcause" 32 in
    let mtvec = find_or_create_state builder "mtvec" 32 in
    let mstatus = find_or_create_state builder "mstatus" 32 in
    let priv = find_or_create_state builder "priv_mode" 2 in

    (* mepc <- pc *)
    connect builder pc_rd mepc "assignment";

    (* mcause <- 3 (breakpoint) *)
    let three = make_node ~display_name:(Some "3") ~value:(Some "3")
      ~bit_width:(Some 32) "literal" in
    let three = add_node builder three in
    connect builder three mcause "assignment";

    (* mstatus update: MPIE <- MIE, MIE <- 0, MPP <- cur_priv *)
    let mstatus_update = make_node ~display_name:(Some "mstatus_ebreak_update")
      ~operator:(Some "ebreak_mstatus_update") ~bit_width:(Some 32) "operation" in
    let mstatus_update = add_node builder mstatus_update in
    connect builder mstatus mstatus_update "operand";
    connect builder priv mstatus_update "operand";
    connect builder mstatus_update mstatus "assignment";

    (* pc <- mtvec.BASE << 2 *)
    let mtvec_base = make_node ~display_name:(Some "mtvec.BASE")
      ~operator:(Some "bit_slice") ~bit_width:(Some 30)
      ~bitslice:(Some (31, 2)) "bit_slice" in
    let mtvec_base = add_node builder mtvec_base in
    connect builder mtvec mtvec_base "bit_access";
    let mtvec_addr = make_node ~display_name:(Some "mtvec.BASE << 2")
      ~operator:(Some "<<") ~bit_width:(Some 32) "operation" in
    let mtvec_addr = add_node builder mtvec_addr in
    let two = make_node ~display_name:(Some "2") ~value:(Some "2")
      ~bit_width:(Some 32) "literal" in
    let two = add_node builder two in
    connect builder mtvec_base mtvec_addr "operand";
    connect builder two mtvec_addr "operand";
    connect builder mtvec_addr pc_wr "assignment";

    Printf.printf "    Emitted concrete EBREAK graph\n%!"

  (* Inline a function's graph into the current builder *)
  let _inline_function (builder : t) (func_graph : rg_graph) : unit =
    (* Add all nodes from func_graph, renaming IDs to avoid conflicts *)
    let id_mapping = Hashtbl.create 100 in

    List.iter (fun (node : rg_node) ->
      let new_node : rg_node = { node with id = fresh_node_id () } in
      Hashtbl.add id_mapping node.id new_node.id;
      ignore (add_node builder new_node)
    ) func_graph.nodes;

    (* Add all edges, updating source/target IDs *)
    List.iter (fun edge ->
      let new_source = Hashtbl.find id_mapping edge.source in
      let new_target = Hashtbl.find id_mapping edge.target in
      let new_edge = {
        edge with
        id = fresh_edge_id ();
        source = new_source;
        target = new_target;
      } in
      ignore (add_edge builder new_edge)
    ) func_graph.edges

  (* Inline a function and wire up arguments to parameters *)
  let inline_function_call (builder : t) (func_graph : rg_graph) (param_names : string list) (arg_nodes : rg_node list) : rg_node option =
    Printf.printf "          inline_function_call: %d params, %d args\n%!" (List.length param_names) (List.length arg_nodes);

    (* Record nodes before inlining *)
    let nodes_before = List.length builder.nodes in

    (* Inline the function body *)
    let id_mapping = Hashtbl.create 100 in
    List.iter (fun (node : rg_node) ->
      let new_node : rg_node = { node with id = fresh_node_id () } in
      Hashtbl.add id_mapping node.id new_node.id;
      ignore (add_node builder new_node)
    ) func_graph.nodes;

    List.iter (fun edge ->
      let new_source = Hashtbl.find id_mapping edge.source in
      let new_target = Hashtbl.find id_mapping edge.target in
      let new_edge = {
        edge with
        id = fresh_edge_id ();
        source = new_source;
        target = new_target;
      } in
      ignore (add_edge builder new_edge)
    ) func_graph.edges;

    Printf.printf "          Inlined %d nodes\n%!" (List.length builder.nodes - nodes_before);

    (* Find inlined parameter nodes and redirect them to actual arguments *)
    List.iter2 (fun (param_name : string) (arg_node : rg_node) ->
      Printf.printf "          Processing parameter '%s'\n%!" param_name;

      (* Find the inlined parameter node by display_name *)
      let param_node_opt = List.find_opt (fun node ->
        match node.display_name with
        | Some name -> name = param_name && List.mem node.id (List.map snd (Hashtbl.to_seq id_mapping |> List.of_seq))
        | None -> false
      ) builder.nodes in

      match param_node_opt with
      | Some param_node ->
          Printf.printf "          Found parameter node %s, redirecting edges\n%!" param_node.id;

          (* Find all edges FROM the parameter node and redirect them to come FROM the argument instead *)
          builder.edges <- List.map (fun edge ->
            if edge.source = param_node.id then
              { edge with source = arg_node.id }
            else
              edge
          ) builder.edges;

          Printf.printf "          Redirected edges from %s to %s\n%!" param_node.id arg_node.id
      | None ->
          Printf.printf "          Warning: Could not find parameter node for '%s'\n%!" param_name
    ) param_names arg_nodes;

    (* Find the return value node - typically an operation or the last computed value *)
    (* For wX, the return is unit (no return value), but we return the write operation *)
    (* Look for the array_write or conditional node as the "return" *)
    let return_node_opt = List.find_opt (fun (node : rg_node) ->
      List.mem node.id (List.map snd (Hashtbl.to_seq id_mapping |> List.of_seq)) &&
      (node.node_type = "array_write" || node.node_type = "conditional" || node.node_type = "operation")
    ) (List.rev builder.nodes) in  (* Search from end - last node is likely the return *)

    (match return_node_opt with
    | Some ret -> Printf.printf "          Found return node: %s (type=%s)\n%!" ret.id ret.node_type
    | None -> Printf.printf "          Warning: No return node found\n%!");

    return_node_opt

  (* Wire up the fetch function to architectural state after inlining *)
  let wire_fetch_function builder =
    match (find_node builder "pc_rd", find_node builder "instr") with
    | (Some pc_rd_node, Some instr_node) ->
        (* Find all PC variable nodes in the inlined fetch function *)
        (* These are var nodes with display_name="PC" that were just inlined *)
        let pc_var_nodes = List.filter (fun node ->
          node.display_name = Some "PC" &&
          node.node_type = "var"
        ) builder.nodes in

        (* Connect pc_rd to all PC variable nodes *)
        List.iter (fun pc_var ->
          connect builder pc_rd_node pc_var "pc_input"
        ) pc_var_nodes;

        Printf.printf "      Connected pc_rd to %d PC variable nodes\n%!" (List.length pc_var_nodes);

        (* Find the fetch output node: F_Base(ihi bitvector_concat ilo) *)
        (* This is an operation node with display_name containing "F_Base" and "concat" *)
        let fetch_output = List.find_opt (fun node ->
          match node.display_name with
          | Some name ->
              String.contains name 'F' &&
              String.contains name '_' &&
              String.contains name 'B' &&
              node.node_type = "operation"
          | None -> false
        ) builder.nodes in

        (match fetch_output with
        | Some output_node ->
            (* Connect fetch output to instr *)
            connect builder output_node instr_node "fetched_instruction";
            Printf.printf "      Connected fetch output to instr\n%!"
        | None ->
            Printf.printf "      Warning: Could not find fetch output node (F_Base)\n%!")
    | _ -> ()

  (* Wire up BTYPE parameters to their sources *)
  let wire_btype_parameters builder =
    Printf.printf "      DEBUG: wire_btype_parameters called\n%!";
    match (find_node builder "pc_rd", find_node builder "instr") with
    | (Some pc_rd_node, Some instr_node) ->
        (* 1. Connect PC var nodes to pc_rd *)
        let pc_var_nodes = List.filter (fun node ->
          node.display_name = Some "PC" &&
          node.node_type = "var"
        ) builder.nodes in

        List.iter (fun (pc_var : rg_node) ->
          Printf.printf "        Connecting pc_rd to PC var %s\n%!" pc_var.id;
          connect builder pc_rd_node pc_var "value"
        ) pc_var_nodes;

        (* 2. Extract rs1 [19:15] and connect to rs1 var *)
        let rs1_var_nodes = List.filter (fun node ->
          node.display_name = Some "rs1" &&
          node.node_type = "var"
        ) builder.nodes in

        if List.length rs1_var_nodes > 0 then begin
          let rs1_extract = make_node
            ~display_name:(Some "rs1")
            ~operator:(Some "bit_slice")
            ~bit_width:(Some 5)
            ~bitslice:(Some (19, 15))
            "bit_slice" in
          let rs1_extract_node = add_node builder rs1_extract in
          connect builder instr_node rs1_extract_node "bit_access";

          List.iter (fun (rs1_var : rg_node) ->
            Printf.printf "        Connecting rs1 extraction to rs1 var %s\n%!" rs1_var.id;
            connect builder rs1_extract_node rs1_var "value"
          ) rs1_var_nodes
        end;

        (* 3. Extract rs2 [24:20] and connect to rs2 var *)
        let rs2_var_nodes = List.filter (fun node ->
          node.display_name = Some "rs2" &&
          node.node_type = "var"
        ) builder.nodes in

        if List.length rs2_var_nodes > 0 then begin
          let rs2_extract = make_node
            ~display_name:(Some "rs2")
            ~operator:(Some "bit_slice")
            ~bit_width:(Some 5)
            ~bitslice:(Some (24, 20))
            "bit_slice" in
          let rs2_extract_node = add_node builder rs2_extract in
          connect builder instr_node rs2_extract_node "bit_access";

          List.iter (fun (rs2_var : rg_node) ->
            Printf.printf "        Connecting rs2 extraction to rs2 var %s\n%!" rs2_var.id;
            connect builder rs2_extract_node rs2_var "value"
          ) rs2_var_nodes
        end;

        (* 4. Extract immediate and connect to imm var *)
        (* Use find_node to locate the imm var by prefixed or unprefixed name *)
        let imm_var_opt = List.find_opt (fun node ->
          (node.display_name = Some "imm" ||
           node.display_name = Some (prefix_local_name builder "imm")) &&
          node.node_type = "var"
        ) builder.nodes in

        if imm_var_opt <> None then begin
        let imm_var_nodes = match imm_var_opt with Some n -> [n] | None -> [] in
          (* BTYPE immediate: {instr[31], instr[7], instr[30:25], instr[11:8], 1'b0} *)
          (* Build the immediate extraction *)
          let bit_31 = make_node ~display_name:(Some "instr[31]") ~operator:(Some "bit_slice") ~bit_width:(Some 1) ~bitslice:(Some (31, 31)) "bit_slice" in
          let bit_31_node = add_node builder bit_31 in
          connect builder instr_node bit_31_node "bit_access";

          let bit_7 = make_node ~display_name:(Some "instr[7]") ~operator:(Some "bit_slice") ~bit_width:(Some 1) ~bitslice:(Some (7, 7)) "bit_slice" in
          let bit_7_node = add_node builder bit_7 in
          connect builder instr_node bit_7_node "bit_access";

          let bits_30_25 = make_node ~display_name:(Some "instr[30:25]") ~operator:(Some "bit_slice") ~bit_width:(Some 6) ~bitslice:(Some (30, 25)) "bit_slice" in
          let bits_30_25_node = add_node builder bits_30_25 in
          connect builder instr_node bits_30_25_node "bit_access";

          let bits_11_8 = make_node ~display_name:(Some "instr[11:8]") ~operator:(Some "bit_slice") ~bit_width:(Some 4) ~bitslice:(Some (11, 8)) "bit_slice" in
          let bits_11_8_node = add_node builder bits_11_8 in
          connect builder instr_node bits_11_8_node "bit_access";

          let bit_0 = make_node ~display_name:(Some "0") ~value:(Some "0") ~bit_width:(Some 1) "literal" in
          let bit_0_node = add_node builder bit_0 in

          (* Concatenate as tree: {bit_31, bit_7, bits_30_25, bits_11_8, bit_0} *)
          (* concat(bit_31, bit_7) -> 2 bits *)
          let concat1 = make_node ~display_name:(Some "imm_concat1") ~operator:(Some "concat") ~bit_width:(Some 2) "operation" in
          let concat1_node = add_node builder concat1 in
          connect ~position:(Some "0") builder bit_31_node concat1_node "operand";  (* high bits *)
          connect ~position:(Some "1") builder bit_7_node concat1_node "operand";   (* low bits *)

          (* concat(concat1, bits_30_25) -> 8 bits *)
          let concat2 = make_node ~display_name:(Some "imm_concat2") ~operator:(Some "concat") ~bit_width:(Some 8) "operation" in
          let concat2_node = add_node builder concat2 in
          connect ~position:(Some "0") builder concat1_node concat2_node "operand";  (* high bits *)
          connect ~position:(Some "1") builder bits_30_25_node concat2_node "operand"; (* low bits *)

          (* concat(concat2, bits_11_8) -> 12 bits *)
          let concat3 = make_node ~display_name:(Some "imm_concat3") ~operator:(Some "concat") ~bit_width:(Some 12) "operation" in
          let concat3_node = add_node builder concat3 in
          connect ~position:(Some "0") builder concat2_node concat3_node "operand";  (* high bits *)
          connect ~position:(Some "1") builder bits_11_8_node concat3_node "operand"; (* low bits *)

          (* concat(concat3, bit_0) -> 13 bits *)
          let concat4 = make_node ~display_name:(Some "imm_concat4") ~operator:(Some "concat") ~bit_width:(Some 13) "operation" in
          let concat4_node = add_node builder concat4 in
          connect ~position:(Some "0") builder concat3_node concat4_node "operand";  (* high bits *)
          connect ~position:(Some "1") builder bit_0_node concat4_node "operand";    (* low bits *)

          (* Sign-extend 13-bit immediate to 32 bits *)
          let sign_ext = make_node
            ~display_name:(Some "sign_ext_imm")
            ~operator:(Some "sign_extend")
            ~bit_width:(Some 32)
            "sign_extend" in
          let sign_ext_node = add_node builder sign_ext in
          connect builder concat4_node sign_ext_node "operand";

          List.iter (fun (imm_var : rg_node) ->
            Printf.printf "        Connecting sign-extended imm to imm var %s\n%!" imm_var.id;
            connect builder sign_ext_node imm_var "value"
          ) imm_var_nodes
        end;

        Printf.printf "      DEBUG: BTYPE parameter wiring complete\n%!"
    | _ ->
        Printf.printf "      DEBUG: Could not wire BTYPE parameters (missing pc_rd or instr)\n%!"

  (* Wire STORE S-type immediate: connect sign_ext_stype_imm -> imm var node *)
  (* Called after visit_funcl_with_name so the imm var node exists *)
  let wire_store_stype_imm builder =
    let sign_ext_nodes = List.filter (fun node ->
      node.display_name = Some "sign_ext_stype_imm"
    ) builder.nodes in
    let imm_var_nodes = List.filter (fun node ->
      (node.display_name = Some "imm" ||
       node.display_name = Some (prefix_local_name builder "imm")) &&
      node.node_type = "var"
    ) builder.nodes in
    match sign_ext_nodes, imm_var_nodes with
    | [sign_ext], imm_vars when List.length imm_vars > 0 ->
        List.iter (fun (imm_var : rg_node) ->
          Printf.printf "        Connecting S-type sign-extended imm to imm var %s\n%!" imm_var.id;
          connect builder sign_ext imm_var "value"
        ) imm_vars
    | [], _ ->
        Printf.printf "        Warning: sign_ext_stype_imm node not found for STORE wiring\n%!"
    | _, [] ->
        Printf.printf "        Warning: imm var node not found for STORE wiring\n%!"
    | _ ->
        Printf.printf "        Warning: multiple sign_ext_stype_imm nodes found\n%!"

  (* Add PC increment logic: pc_wr = pc_rd + 4 *)
  let add_pc_increment builder =
    match (find_node builder "pc_rd", find_node builder "pc_wr") with
    | (Some pc_rd_node, Some pc_wr_node) ->
        (* Check if pc_wr already has incoming value edges (from jump/branch instructions) *)
        let pc_wr_has_value = List.exists (fun edge ->
          edge.target = pc_wr_node.id &&
          (edge.edge_type = "value" || edge.edge_type = "assignment")
        ) builder.edges in

        if pc_wr_has_value then
          Printf.printf "        PC already updated by instruction, skipping default increment\n%!"
        else begin
          (* Create literal 4 *)
          let four_node = make_node
            ~display_name:(Some "4")
            ~value:(Some "4")
            ~bit_width:(Some 32)
            "literal" in
          let four_node = add_node builder four_node in

          (* Create pc_rd + 4 operation *)
          (* Use display_name "(pc_rd + 4)" to match ISA parser convention *)
          let add_op_node = make_node
            ~display_name:(Some "(pc_rd + 4)")
            ~operator:(Some "+")
            ~bit_width:(Some 32)
            "operation" in
          let add_op_node = add_node builder add_op_node in

          (* Connect: pc_rd -> add, 4 -> add *)
          connect builder pc_rd_node add_op_node "operand";
          connect builder four_node add_op_node "operand";

          (* Connect: add -> pc_wr (use 'assignment' to match ISA parser convention) *)
          connect builder add_op_node pc_wr_node "assignment";

          Printf.printf "        Added PC increment: pc_wr = pc_rd + 4\n%!"
        end
    | _ ->
        Printf.printf "        Warning: pc_rd or pc_wr not found, skipping PC increment\n%!"

  (* Transform PC-updating conditionals into multiplexers *)
  (* SAIL uses control flow: if (taken) then jump_to(target) else RETIRE_SUCCESS *)
  (* We need data flow: pc_wr = taken ? target : pc+4 *)
  let transform_pc_conditionals (builder : t) =
    Printf.printf "      DEBUG: transform_pc_conditionals called\n%!";
    match (find_node builder "pc_rd", find_node builder "pc_wr") with
    | (Some pc_rd_node, Some pc_wr_node) ->
        Printf.printf "      DEBUG: Found pc_rd and pc_wr nodes\n%!";
        (* Find conditionals that have pc_update in their branches *)
        let conditionals : rg_node list = List.filter (fun n -> n.node_type = "conditional") builder.nodes in
        Printf.printf "      DEBUG: Found %d conditional nodes\n%!" (List.length conditionals);

        List.iter (fun (cond_node : rg_node) ->
          (* Check if this conditional has a pc_update in one of its branches *)
          (* Note: edges go FROM branches TO conditional, so conditional is the TARGET *)
          let then_edge : rg_edge option = List.find_opt (fun e -> e.target = cond_node.id && e.edge_type = "then_branch") builder.edges in
          let else_edge : rg_edge option = List.find_opt (fun e -> e.target = cond_node.id && e.edge_type = "else_branch") builder.edges in
          let cond_edge : rg_edge option = List.find_opt (fun e -> e.target = cond_node.id && e.edge_type = "condition") builder.edges in
          Printf.printf "        Conditional node %s: then=%s else=%s cond=%s\n%!" cond_node.id
            (match then_edge with Some _ -> "yes" | None -> "no")
            (match else_edge with Some _ -> "yes" | None -> "no")
            (match cond_edge with Some _ -> "yes" | None -> "no");

          (match (then_edge, else_edge, cond_edge) with
          | (Some then_e, Some else_e, Some cond_e) ->
              (* Edges go FROM branches TO conditional, so use .source to get the branch nodes *)
              let then_node = List.find_opt (fun (n : rg_node) -> n.id = then_e.source) builder.nodes in
              let else_node = List.find_opt (fun (n : rg_node) -> n.id = else_e.source) builder.nodes in
              let condition_node = List.find_opt (fun (n : rg_node) -> n.id = cond_e.source) builder.nodes in

              (match (then_node, else_node, condition_node) with
              | (Some then_n, Some _else_n, Some cond_n) ->
                  Printf.printf "        Conditional then branch type: %s\n%!" then_n.node_type;
                  (* Check if then branch is pc_update *)
                  if then_n.node_type = "pc_update" then begin
                    Printf.printf "        Found PC-updating conditional, transforming to multiplexer\n%!";

                    (* pc_update's argument connects directly to pc_wr, not the pc_update node itself *)
                    (* Find what connects to the pc_update node (the branch target) *)
                    let target_arg_edge = List.find_opt (fun e ->
                      e.target = then_n.id && (e.edge_type = "argument" || e.edge_type = "operand")
                    ) builder.edges in

                    (match target_arg_edge with
                    | Some ta_edge ->
                        let branch_target_node = List.find (fun (n : rg_node) -> n.id = ta_edge.source) builder.nodes in

                        (* Find and remove the edge from branch_target to pc_wr *)
                        builder.edges <- List.filter (fun e ->
                          not (e.source = branch_target_node.id && e.target = pc_wr_node.id)
                        ) builder.edges;

                        (* Create pc+4 for fallthrough *)
                        let four_node = make_node
                          ~display_name:(Some "4")
                          ~value:(Some "4")
                          ~bit_width:(Some 32)
                          "literal" in
                        let four_node = add_node builder four_node in

                        (* Use display_name "(pc_rd + 4)" to match ISA parser convention *)
                        let pc_plus_4 = make_node
                          ~display_name:(Some "(pc_rd + 4)")
                          ~operator:(Some "+")
                          ~bit_width:(Some 32)
                          "operation" in
                        let pc_plus_4 = add_node builder pc_plus_4 in
                        connect builder pc_rd_node pc_plus_4 "operand";
                        connect builder four_node pc_plus_4 "operand";

                        (* Create ternary_op to match ISA parser convention *)
                        (* ISA parser produces: res ? branch_dest : (pc_rd + 4) *)
                        let ternary_node = make_node
                          ~display_name:(Some (Printf.sprintf "%s ? branch_dest : (pc_rd + 4)"
                            (Option.value ~default:"cond" cond_n.display_name)))
                          ~bit_width:(Some 32)
                          "ternary_op" in
                        let ternary_node = add_node builder ternary_node in

                        (* Connect using ISA-standard ternary edge types *)
                        connect builder cond_n ternary_node "ternary_condition";
                        connect builder branch_target_node ternary_node "ternary_true";
                        connect builder pc_plus_4 ternary_node "ternary_false";

                        (* Connect: ternary -> pc_wr *)
                        connect builder ternary_node pc_wr_node "assignment";

                        (* Remove the conditional node and its edges from the graph *)
                        let edges_before = List.length builder.edges in
                        builder.edges <- List.filter (fun e ->
                          not (e.target = cond_node.id || e.source = cond_node.id)
                        ) builder.edges;
                        let edges_after = List.length builder.edges in

                        let nodes_before = List.length builder.nodes in
                        builder.nodes <- List.filter (fun (n : rg_node) ->
                          n.id <> cond_node.id
                        ) builder.nodes;
                        let nodes_after = List.length builder.nodes in

                        Printf.printf "        Transformed conditional to: pc_wr = %s ? branch_target : pc+4\n%!"
                          (Option.value ~default:"cond" cond_n.display_name);
                        Printf.printf "        Removed conditional %s: edges %d->%d, nodes %d->%d\n%!"
                          cond_node.id edges_before edges_after nodes_before nodes_after
                    | None ->
                        Printf.printf "        Warning: Could not find branch target argument\n%!")
                  end
              | _ -> ())
          | _ -> ())
        ) conditionals
    | _ ->
        Printf.printf "        Warning: pc_rd or pc_wr not found in transform_pc_conditionals\n%!"

  (* Get string representation of an identifier *)
  let string_of_id (Id_aux (id_aux, _)) =
    match id_aux with
    | Id s | Operator s -> s
    | And_bool -> "and"
    | Or_bool -> "or"

  (* Helper to detect STORE variants (STORE_WORD, STORE_HALF, STORE_BYTE, or base STORE) *)
  let is_store_variant name =
    name = "STORE" || name = "STORE_WORD" || name = "STORE_HALF" || name = "STORE_BYTE"

  (* Extract instruction name from mapping pattern expression *)
  let rec extract_instr_name_from_mpexp (MPat_aux (mpat_aux, _)) =
    match mpat_aux with
    | MPat_pat mpat -> extract_instr_name_from_mpat mpat
    | MPat_when (mpat, _) -> extract_instr_name_from_mpat mpat

  and extract_instr_name_from_mpat (MP_aux (mp_aux, _)) =
    match mp_aux with
    | MP_id id -> Some (string_of_id id)
    | MP_app (id, _) -> Some (string_of_id id)
    | MP_cons (mp, _) -> extract_instr_name_from_mpat mp
    | MP_string_append mps ->
        (* String append expects a list of patterns *)
        (match mps with
        | mp :: _ -> extract_instr_name_from_mpat mp
        | [] -> None)
    | MP_list mps ->
        (match mps with
        | mp :: _ -> extract_instr_name_from_mpat mp
        | [] -> None)
    | MP_tuple mps ->
        (match mps with
        | mp :: _ -> extract_instr_name_from_mpat mp
        | [] -> None)
    | MP_typ (mp, _) -> extract_instr_name_from_mpat mp
    | MP_as (mp, _) -> extract_instr_name_from_mpat mp
    | _ -> None

  (* Get bit width of a literal *)
  let rec get_lit_width lit =
    match lit with
    | L_aux (L_bin digits, _) ->
        (* L_bin contains a non_empty list of bin_digit (B0 | B1) *)
        (* Use SAIL's built-in function to get the length *)
        let total_bits = Ast_util.bin_lit_length digits in
        Printf.printf "          get_lit_width: L_bin with %d bits\n%!" total_bits;
        total_bits
    | L_aux (L_hex chars, _) ->
        let char_count = List.length chars in
        Printf.printf "          get_lit_width: L_hex with %d chars\n%!" char_count;
        char_count * 4
    | L_aux (L_num _, _) ->
        (* Numeric literal - we can't determine the intended bit width from the value alone *)
        Printf.printf "          get_lit_width: L_num (unknown width, returning 0)\n%!";
        0
    | L_aux (lit_type, _) ->
        let type_str = match lit_type with
          | L_unit -> "L_unit"
          | L_true -> "L_true"
          | L_false -> "L_false"
          | L_num _ -> "L_num"
          | L_hex _ -> "L_hex"
          | L_bin _ -> "L_bin"
          | L_string _ -> "L_string"
          | L_undef -> "L_undef"
          | L_real _ -> "L_real"
        in
        Printf.printf "          get_lit_width: %s (unknown width, returning 0)\n%!" type_str;
        0

  (* Get bit width of a mapping pattern *)
  and get_mpat_width (MP_aux (mp_aux, _annot)) =
    match mp_aux with
    | MP_lit lit ->
        Printf.printf "          get_mpat_width: MP_lit (no annotation width)\n%!";
        get_lit_width lit
    | MP_app (id, args) ->
        (* Check if it's a known mapping function *)
        let name = string_of_id id in
        Printf.printf "          get_mpat_width: MP_app(%s)\n%!" name;
        if name = "encdec_reg" || name = "encdec_creg" || name = "encdec_freg"
           || name = "encdec_amoop" || name = "encdec_vreg" || name = "encdec_nreg" then
          5  (* 5-bit encoding *)
        else if name = "bool_bits" || name = "bool_not_bits" || name = "bool_bit" then
          1  (* Boolean encoding is 1 bit *)
        else if name = "encdec_csrop" || name = "width_enc" then
          2  (* 2-bit encoding *)
        else if name = "encdec_iop" || name = "encdec_bop" || name = "encdec_sop"
                || name = "encdec_mul_op" || name = "encdec_biop"
                || name = "encdec_rounding_mode" || name = "width_enc_wide" then
          3  (* 3-bit encoding *)
        else if name = "encdec_uop" || name = "encdec_lsop" then
          7  (* 7-bit encoding (opcodes) *)
        else begin
          (* Generic fallback: try to infer width from literal arguments *)
          let arg_widths = List.filter_map (fun arg ->
            let w = get_mpat_width arg in
            if w > 0 then Some w else None
          ) args in
          match arg_widths with
          | [w] -> Printf.printf "          get_mpat_width: inferred %d from arg\n%!" w; w
          | _ ->
              Printf.printf "          get_mpat_width: unknown MP_app '%s'\n%!" name;
              0  (* Unknown width *)
        end
    | MP_id _ ->
        Printf.printf "          get_mpat_width: MP_id\n%!";
        0  (* Variable, unknown width *)
    | MP_vector_concat parts ->
        Printf.printf "          get_mpat_width: MP_vector_concat with %d parts\n%!" (List.length parts);
        (* Sum of all parts *)
        List.fold_left (fun acc mp -> acc + get_mpat_width mp) 0 parts
    | MP_typ (mp, typ) ->
        Printf.printf "          get_mpat_width: MP_typ with type\n%!";
        (* Extract bit width from type - e.g., bits(7) *)
        (match typ with
        | Typ_aux (Typ_app (id, [A_aux (A_nexp (Nexp_aux (Nexp_constant n, _)), _)]), _)
          when string_of_id id = "bitvector" || string_of_id id = "bits" ->
            let width = Big_int.to_int n in
            Printf.printf "            Type is bits(%d)\n%!" width;
            width
        | _ ->
            Printf.printf "            Type is not a simple bitvector, recursing\n%!";
            get_mpat_width mp)
    | MP_as (mp, _) ->
        Printf.printf "          get_mpat_width: MP_as\n%!";
        get_mpat_width mp
    | MP_vector_subrange (_, hi, lo) ->
        let width = Big_int.to_int hi - Big_int.to_int lo + 1 in
        Printf.printf "          get_mpat_width: MP_vector_subrange [%d:%d] = %d bits\n%!"
          (Big_int.to_int hi) (Big_int.to_int lo) width;
        width
    | _ ->
        Printf.printf "          get_mpat_width: unknown pattern\n%!";
        0

  (* Flatten vector concatenation into list (right-to-left order) *)
  (* IMPORTANT: Preserve MP_typ wrappers on leaf nodes so get_mpat_width can *)
  (* extract bit widths from type annotations (e.g., rs1 : bits(5)) *)
  and flatten_vector_concat (MP_aux (mp_aux, _) as mp) =
    match mp_aux with
    | MP_vector_concat parts ->
        Printf.printf "        flatten: MP_vector_concat with %d parts\n%!" (List.length parts);
        (* In SAIL, a @ b means a goes to MSB (highest bits), b goes to LSB (lowest bits) *)
        (* Example: funct7 @ rs2 @ rs1 @ funct3 @ rd @ opcode *)
        (*   funct7 should be bits [31:25], opcode should be bits [6:0] *)
        (* To process LSB-first with fold_left starting at bit 0, reverse the list *)
        List.concat_map flatten_vector_concat (List.rev parts)
    | MP_typ (mp', _) ->
        (* Only unwrap if inner pattern is a concat that needs further flattening *)
        (match mp' with
         | MP_aux (MP_vector_concat _, _) ->
             Printf.printf "        flatten: MP_typ wrapping concat (unwrapping)\n%!";
             flatten_vector_concat mp'
         | _ ->
             Printf.printf "        flatten: MP_typ wrapping leaf (preserving type)\n%!";
             [mp])  (* Preserve MP_typ wrapper so get_mpat_width can read the type *)
    | MP_as (mp', _) ->
        Printf.printf "        flatten: MP_as (unwrapping)\n%!";
        flatten_vector_concat mp'
    | MP_lit _ ->
        Printf.printf "        flatten: MP_lit (returning as-is)\n%!";
        [mp]
    | MP_app _ ->
        Printf.printf "        flatten: MP_app (returning as-is)\n%!";
        [mp]
    | _ ->
        Printf.printf "        flatten: other pattern (returning as-is)\n%!";
        [mp]  (* Base case: return single pattern *)

  (* Extract decode pattern from mapping clause *)
  and extract_decode_pattern builder left_mpexp right_mpexp =
    (* Extract instruction name from left side *)
    let instr_name = extract_instr_name_from_mpexp left_mpexp in
    match instr_name with
    | Some name ->
        Printf.printf "      Extracting decode for %s\n%!" name;

        (* Extract right side as mpat *)
        let right_mpat = match right_mpexp with
          | MPat_aux (MPat_pat mp, _) -> Some mp
          | MPat_aux (MPat_when (mp, _), _) -> Some mp
        in

        (match right_mpat with
        | Some mp ->
            (* Flatten concatenation *)
            let parts = flatten_vector_concat mp in
            Printf.printf "        Flattened into %d parts\n%!" (List.length parts);

            (* Process each part from LSB to MSB *)
            let num_parts = List.length parts in
            let _final_bit = List.fold_left (fun (bit_pos, part_idx) part ->
              let raw_width = get_mpat_width part in

              (* Unwrap MP_typ for special case checks *)
              let inner_check = match part with
                | MP_aux (MP_typ (mp', _), _) -> mp'
                | _ -> part
              in

              (* Adjust width for special cases *)
              let width =
                (* Special case 1: RISC-V opcodes at bit 0 are always 7 bits *)
                if bit_pos = 0 && raw_width = 1 then begin
                  (match inner_check with
                  | MP_aux (MP_lit _, _) ->
                      Printf.printf "        Adjusting opcode literal width from %d to 7 bits\n%!" raw_width;
                      7
                  | _ -> raw_width)
                end
                (* Special case 2: Last part with unknown width - fill remaining bits *)
                else if part_idx = num_parts - 1 && raw_width = 0 then
                  32 - bit_pos
                else
                  raw_width
              in

              let high_bit = bit_pos + width - 1 in
              Printf.printf "        DEBUG: bit_pos=%d, width=%d, high_bit=%d (part %d/%d)\n%!" bit_pos width high_bit (part_idx + 1) num_parts;

              (* Unwrap MP_typ to get the inner pattern for processing *)
              let inner_part = match part with
                | MP_aux (MP_typ (mp', _), _) -> mp'
                | _ -> part
              in

              (* Process the part *)
              (match inner_part with
              | MP_aux (MP_lit lit, _) ->
                  let lit_str = Ast_util.string_of_lit lit in
                  Printf.printf "        [%d:%d] constant = %s\n%!" high_bit bit_pos lit_str;
                  (* Store decode constraint: bit range and expected value *)
                  builder.decode_constraints <- (high_bit, bit_pos, lit_str) :: builder.decode_constraints
              | MP_aux (MP_app (id, args), _) ->
                  let func_name = string_of_id id in
                  if func_name = "encdec_reg" || func_name = "encdec_creg" then begin
                    (* Extract field name from args *)
                    let field_name = match args with
                      | [MP_aux (MP_id fid, _)] -> string_of_id fid
                      | _ -> "unknown"
                    in
                    Printf.printf "        [%d:%d] %s (register field)\n%!" high_bit bit_pos field_name;

                    (* Create bit_slice node: field = instr[high:low] *)
                    (match find_node builder "instr" with
                    | Some instr_node ->
                        let slice_node = make_node
                          ~display_name:(Some field_name)
                          ~operator:(Some "bit_slice")
                          ~bit_width:(Some width)
                          ~bitslice:(Some (high_bit, bit_pos))
                          "bit_slice" in
                        let slice_id = add_node builder slice_node in

                        (* Add edge from instr to slice with bit_access type *)
                        connect builder instr_node slice_id "bit_access"
                    | None ->
                        Printf.printf "          Warning: instr node not found\n%!")
                  end else if func_name = "bool_bits" || func_name = "bool_not_bits" || func_name = "width_enc" then begin
                    (* Encoding functions: extract inner field name and create bit_slice *)
                    (* Examples: bool_bits(is_unsigned), width_enc(width) *)
                    let field_name = match args with
                      | [MP_aux (MP_id fid, _)] -> string_of_id fid
                      | _ -> "unknown"
                    in
                    Printf.printf "        [%d:%d] %s (encoded field via %s)\n%!" high_bit bit_pos field_name func_name;

                    (* Create bit_slice node: field = instr[high:low] *)
                    (match find_node builder "instr" with
                    | Some instr_node ->
                        let slice_node = make_node
                          ~display_name:(Some field_name)
                          ~operator:(Some "bit_slice")
                          ~bit_width:(Some width)
                          ~bitslice:(Some (high_bit, bit_pos))
                          "bit_slice" in
                        let slice_id = add_node builder slice_node in

                        (* Add edge from instr to slice with bit_access type *)
                        connect builder instr_node slice_id "bit_access"
                    | None ->
                        Printf.printf "          Warning: instr node not found\n%!")
                  end
              | MP_aux (MP_id fid, _) ->
                  let field_name = string_of_id fid in
                  Printf.printf "        [%d:%d] %s (immediate field)\n%!" high_bit bit_pos field_name;

                  (* Create bit_slice node: imm = instr[high:low] *)
                  (match find_node builder "instr" with
                  | Some instr_node ->
                      let slice_node = make_node
                        ~display_name:(Some field_name)
                        ~operator:(Some "bit_slice")
                        ~bit_width:(Some width)
                        ~bitslice:(Some (high_bit, bit_pos))
                        "bit_slice" in
                      let slice_id = add_node builder slice_node in

                      (* Add edge from instr to slice with bit_access type *)
                      connect builder instr_node slice_id "bit_access"
                  | None ->
                      Printf.printf "          Warning: instr node not found\n%!")
              | _ ->
                  Printf.printf "        [%d:%d] unknown pattern\n%!" high_bit bit_pos
              );

              (* Move to next bit position and part index *)
              (bit_pos + width, part_idx + 1)
            ) (0, 0) parts in
            ()
        | None ->
            Printf.printf "        Could not extract right side pattern\n%!")
    | None ->
        Printf.printf "      Could not extract instruction name\n%!"

  (* Extract operation parameter from left side of mapping clause *)
  (* For RTYPE(rs2, rs1, rd, ADD), returns Some "ADD" *)
  and extract_operation_param left_mpexp =
    let extract_from_mpat (MP_aux (mp_aux, _)) =
      match mp_aux with
      | MP_app (_id, args) ->
          (* Last argument is the operation for RTYPE *)
          (match List.rev args with
          | MP_aux (MP_id op_id, _) :: _ -> Some (string_of_id op_id)
          | _ -> None)
      | _ -> None
    in
    match left_mpexp with
    | MPat_aux (MPat_pat mp, _) -> extract_from_mpat mp
    | MPat_aux (MPat_when (mp, _), _) -> extract_from_mpat mp

  (* Extract literal values from a mapping clause's right side (bitvector pattern) *)
  (* Returns a list of (high_bit, low_bit, value_int) for each MP_lit in the pattern *)
  and extract_literals_from_mpexp right_mpexp =
    let right_mpat = match right_mpexp with
      | MPat_aux (MPat_pat mp, _) -> Some mp
      | MPat_aux (MPat_when (mp, _), _) -> Some mp
    in
    match right_mpat with
    | Some mp ->
        let parts = flatten_vector_concat mp in
        let _final = List.fold_left (fun (bit_pos, acc) part ->
          let width = get_mpat_width part in
          let width = if width = 0 then 0 else width in
          let inner = match part with
            | MP_aux (MP_typ (mp', _), _) -> mp'
            | _ -> part
          in
          let entry = match inner with
            | MP_aux (MP_lit lit, _) when width > 0 ->
                let lit_str = Ast_util.string_of_lit lit in
                let clean = Str.global_replace (Str.regexp "_") "" lit_str in
                let value = if String.length clean > 2 && String.sub clean 0 2 = "0b" then
                  int_of_string clean
                else if String.length clean > 2 && String.sub clean 0 2 = "0x" then
                  int_of_string clean
                else
                  (try int_of_string clean with _ -> 0) in
                Some (bit_pos + width - 1, bit_pos, value)
            | _ -> None
          in
          (bit_pos + width, match entry with Some e -> e :: acc | None -> acc)
        ) (0, []) parts in
        List.rev (snd _final)
    | None -> []

  (* Extract funct7 and funct3 from a mapping clause's right side *)
  (* For R-type: funct7 is bits [31:25], funct3 is bits [14:12] *)
  and extract_funct_from_clause (_left_mpexp, right_mpexp) =
    let literals = extract_literals_from_mpexp right_mpexp in
    let funct7 = List.find_opt (fun (h, l, _) -> h = 31 && l = 25) literals in
    let funct3 = List.find_opt (fun (h, l, _) -> h = 14 && l = 12) literals in
    match funct7, funct3 with
    | Some (_, _, f7), Some (_, _, f3) -> Some (f7, f3)
    | _, Some (_, _, f3) -> Some (0, f3)  (* No funct7 (e.g., I-type) *)
    | _ -> None

  (* Extract operation encodings from mapping clauses dynamically *)
  and extract_op_encodings clauses =
    List.filter_map (fun ((left_mpexp, _right_mpexp) as clause) ->
      match extract_operation_param left_mpexp with
      | Some op_name ->
          (match extract_funct_from_clause clause with
          | Some (f7, f3) -> Some (op_name, f7, f3)
          | None ->
              Printf.printf "        Warning: could not extract funct7/funct3 for %s\n%!" op_name;
              None)
      | None -> None
    ) clauses

  (* Process multiple mapping clauses to generate decode logic *)
  (* For RTYPE with 10 clauses, creates comparisons and multiplexers like ISA parser does for enables *)
  (* Returns the decode output node ID (if created) to be connected later *)
  and extract_decode_patterns builder instr_name clauses =
    Printf.printf "      Processing %d mapping clauses for %s\n%!" (List.length clauses) instr_name;

    (* First, do standard decode pattern extraction for register fields *)
    (* Use the first clause as representative for field extraction *)
    (match clauses with
    | (left_mpexp, right_mpexp) :: _ ->
        extract_decode_pattern builder left_mpexp right_mpexp
    | [] -> ());

    (* For multi-clause patterns (like RTYPE with ADD/SUB/AND/OR/etc.),
       compute bit-level intersection of decode constraints across ALL clauses.
       e.g., SHIFTIOP has funct3=001,101,101 -> common bits[13:12]=01 *)
    if List.length clauses > 1 then begin
      (* Extract constraints from each clause independently *)
      let per_clause_constraints = List.map (fun (left, right) ->
        let tmp_builder = create () in
        extract_decode_pattern tmp_builder left right;
        tmp_builder.decode_constraints  (* List of (high, low, value) *)
      ) clauses in

      (* Parse binary literal string to int. Handles "0b0110011", "0b0", etc. *)
      let parse_bin_lit s =
        try int_of_string s
        with _ -> try int_of_string ("0b" ^ s) with _ -> 0
      in

      (* Convert constraints to (known_mask, known_values) over 32 instruction bits *)
      let constraints_to_mask constraints =
        List.fold_left (fun (mask, vals) (h, l, v) ->
          let parsed = parse_bin_lit v in
          let width = h - l + 1 in
          let field_mask = ((1 lsl width) - 1) lsl l in
          let field_vals = (parsed land ((1 lsl width) - 1)) lsl l in
          (mask lor field_mask, vals lor field_vals)
        ) (0, 0) constraints
      in

      (* Compute bit-level intersection: bits that are known AND agree across all clauses *)
      let (common_mask, common_val) = match per_clause_constraints with
        | [] -> (0, 0)
        | first :: rest ->
            let (m0, v0) = constraints_to_mask first in
            List.fold_left (fun (cm, cv) clause ->
              let (m, v) = constraints_to_mask clause in
              (* A bit is common if: known in both AND same value *)
              let agree = cm land m land (lnot (cv lxor v)) in
              (agree, cv land agree)
            ) (m0, v0) rest
      in

      (* Extract contiguous bit runs from common_mask and emit as constraints *)
      let rec extract_runs pos acc =
        if pos >= 32 then List.rev acc
        else if common_mask land (1 lsl pos) = 0 then extract_runs (pos + 1) acc
        else begin
          (* Find end of contiguous run *)
          let rec find_end p =
            if p >= 32 || common_mask land (1 lsl p) = 0 then p - 1
            else find_end (p + 1)
          in
          let high = find_end pos in
          let width = high - pos + 1 in
          let field_val = (common_val lsr pos) land ((1 lsl width) - 1) in
          (* Format as binary string *)
          let val_str = Buffer.create (width + 2) in
          Buffer.add_string val_str "0b";
          for i = width - 1 downto 0 do
            Buffer.add_char val_str (if field_val land (1 lsl i) <> 0 then '1' else '0')
          done;
          extract_runs (high + 1) ((high, pos, Buffer.contents val_str) :: acc)
        end
      in
      let common = extract_runs 0 [] in

      Printf.printf "      Multi-clause: %d constraints from first clause, %d common bit-runs across all %d clauses\n%!"
        (List.length builder.decode_constraints) (List.length common) (List.length clauses);

      (* Replace builder's constraints with the bitwise-common ones *)
      builder.decode_constraints <- common;

      (* For varying bit fields, compute exclusion constraints (!=) for values
         not present in any clause. This ensures mutual exclusion with sibling
         instructions sharing the same opcode (e.g., ITYPE vs SHIFTIOP). *)
      let per_field_values : (int * int, int list) Hashtbl.t = Hashtbl.create 16 in
      List.iter (fun clause_constraints ->
        List.iter (fun (h, l, v) ->
          let key = (h, l) in
          let parsed = parse_bin_lit v in
          let existing = match Hashtbl.find_opt per_field_values key with
            | Some vs -> vs | None -> [] in
          if not (List.mem parsed existing) then
            Hashtbl.replace per_field_values key (parsed :: existing)
        ) clause_constraints
      ) per_clause_constraints;
      (* Only add exclusions for small fields (funct3, funct7 sub-fields)
         where not all values are present — avoids constraining registers/immediates *)
      let exclusions = ref [] in
      Hashtbl.iter (fun (h, l) values ->
        let width = h - l + 1 in
        let full_range = 1 lsl width in
        (* Only constrain fields up to 4 bits where not all values are used,
           and which are NOT already in the common constraints *)
        let in_common = List.exists (fun (ch, cl, _) -> ch = h && cl = l) common in
        if width <= 4 && List.length values < full_range && not in_common then begin
          for v = 0 to full_range - 1 do
            if not (List.mem v values) then begin
              let val_str = Buffer.create (width + 2) in
              Buffer.add_string val_str "0b";
              for i = width - 1 downto 0 do
                Buffer.add_char val_str (if v land (1 lsl i) <> 0 then '1' else '0')
              done;
              exclusions := (h, l, Buffer.contents val_str) :: !exclusions
            end
          done
        end
      ) per_field_values;
      if !exclusions <> [] then begin
        Printf.printf "      Added %d exclusion constraints for %s\n%!"
          (List.length !exclusions) instr_name;
        List.iter (fun (h, l, v) ->
          Printf.printf "        instr[%d:%d] != %s\n%!" h l v
        ) !exclusions
      end;
      builder.decode_constraints <- builder.decode_constraints @
        List.map (fun (h, l, v) -> (h, l, "!" ^ v)) !exclusions
    end;

    (* Generate decode logic for patterns with multiple clauses OR special cases like ITYPE/BTYPE/JAL *)
    (* ITYPE and BTYPE have only 1 mapping clause but need decode for funct3-based operation selection *)
    (* JAL needs decode to extract and reassemble rearranged immediate fields *)
    (* JALR uses standard I-type immediate decode, so no custom logic needed *)
    if List.length clauses > 1 || instr_name = "ITYPE" || instr_name = "BTYPE" || instr_name = "UTYPE" || instr_name = "SHIFTIOP" || instr_name = "JAL" || is_store_variant instr_name then begin
      Printf.printf "      Generating decode logic for %d variants (pattern: %s)\n%!" (List.length clauses) instr_name;

      (* Check if this is JAL - extract and concatenate rearranged immediate *)
      if instr_name = "JAL" then begin
        Printf.printf "      Generating JAL immediate extraction\n%!";
        (match find_node builder "instr" with
        | Some instr_node ->
            (* JAL immediate is rearranged in instruction:
               Bit 31: imm[19]
               Bits [19:12]: imm[18..11]
               Bit 20: imm[10]
               Bits [30:21]: imm[9..0]

               Need to reassemble as: imm[19] @ imm[18..11] @ imm[10] @ imm[9..0] @ 0
               This gives a 21-bit signed immediate (bit 20 is the sign bit)
            *)

            (* Extract imm[19] from instr[31] *)
            let imm_19 = make_node
              ~display_name:(Some "instr[31]")
              ~operator:(Some "bit_slice")
              ~bit_width:(Some 1)
              ~bitslice:(Some (31, 31))
              "bit_slice" in
            let imm_19_id = add_node builder imm_19 in
            connect builder instr_node imm_19_id "bit_access";

            (* Extract imm[18..11] from instr[19:12] *)
            let imm_18_11 = make_node
              ~display_name:(Some "instr[19:12]")
              ~operator:(Some "bit_slice")
              ~bit_width:(Some 8)
              ~bitslice:(Some (19, 12))
              "bit_slice" in
            let imm_18_11_id = add_node builder imm_18_11 in
            connect builder instr_node imm_18_11_id "bit_access";

            (* Extract imm[10] from instr[20] *)
            let imm_10 = make_node
              ~display_name:(Some "instr[20]")
              ~operator:(Some "bit_slice")
              ~bit_width:(Some 1)
              ~bitslice:(Some (20, 20))
              "bit_slice" in
            let imm_10_id = add_node builder imm_10 in
            connect builder instr_node imm_10_id "bit_access";

            (* Extract imm[9..0] from instr[30:21] *)
            let imm_9_0 = make_node
              ~display_name:(Some "instr[30:21]")
              ~operator:(Some "bit_slice")
              ~bit_width:(Some 10)
              ~bitslice:(Some (30, 21))
              "bit_slice" in
            let imm_9_0_id = add_node builder imm_9_0 in
            connect builder instr_node imm_9_0_id "bit_access";

            (* Create literal 0 bit *)
            let zero_bit = make_node
              ~display_name:(Some "1'b0")
              ~operator:(Some "constant")
              ~value:(Some "0")
              ~bit_width:(Some 1)
              "constant" in
            let zero_bit_id = add_node builder zero_bit in

            (* Concatenate: {imm[19], imm[18..11], imm[10], imm[9..0], 1'b0} *)
            (* Build from right to left *)

            (* Step 1: concat imm[9..0] and 1'b0 *)
            (* {instr[30:21], 1'b0} - instr[30:21] is HIGH, 1'b0 is LOW *)
            let concat1 = make_node
              ~display_name:(Some "{instr[30:21], 1'b0}")
              ~operator:(Some "concat")
              ~bit_width:(Some 11)
              "concat" in
            let concat1_id = add_node builder concat1 in
            connect ~position:(Some "0") builder imm_9_0_id concat1_id "concat_input";      (* HIGH bits *)
            connect ~position:(Some "1") builder zero_bit_id concat1_id "concat_input";     (* LOW bits *)

            (* Step 2: concat imm[10] and previous *)
            (* {instr[20], instr[30:21], 1'b0} - instr[20] is HIGH, concat1 is LOW *)
            let concat2 = make_node
              ~display_name:(Some "{instr[20], instr[30:21], 1'b0}")
              ~operator:(Some "concat")
              ~bit_width:(Some 12)
              "concat" in
            let concat2_id = add_node builder concat2 in
            connect ~position:(Some "0") builder imm_10_id concat2_id "concat_input";       (* HIGH bits *)
            connect ~position:(Some "1") builder concat1_id concat2_id "concat_input";      (* LOW bits *)

            (* Step 3: concat imm[18..11] and previous *)
            (* {instr[19:12], instr[20], instr[30:21], 1'b0} - instr[19:12] is HIGH, concat2 is LOW *)
            let concat3 = make_node
              ~display_name:(Some "{instr[19:12], instr[20], instr[30:21], 1'b0}")
              ~operator:(Some "concat")
              ~bit_width:(Some 20)
              "concat" in
            let concat3_id = add_node builder concat3 in
            connect ~position:(Some "0") builder imm_18_11_id concat3_id "concat_input";    (* HIGH bits *)
            connect ~position:(Some "1") builder concat2_id concat3_id "concat_input";      (* LOW bits *)

            (* Step 4: concat imm[19] and previous to get full 21-bit immediate *)
            (* {instr[31], instr[19:12], instr[20], instr[30:21], 1'b0} - instr[31] is HIGH, concat3 is LOW *)
            let imm_21bit = make_node
              ~display_name:(Some "imm_21bit")
              ~operator:(Some "concat")
              ~bit_width:(Some 21)
              "concat" in
            let imm_21bit_id = add_node builder imm_21bit in
            connect ~position:(Some "0") builder imm_19_id imm_21bit_id "concat_input";     (* HIGH bits *)
            connect ~position:(Some "1") builder concat3_id imm_21bit_id "concat_input";    (* LOW bits *)

            (* Step 5: sign-extend to 32 bits *)
            let imm_full = make_node
              ~display_name:(Some "imm")
              ~operator:(Some "sign_extend")
              ~bit_width:(Some 32)
              "sign_extend" in
            let imm_full_id = add_node builder imm_full in
            connect builder imm_21bit_id imm_full_id "operand";

            Printf.printf "        Created JAL immediate concat + sign-extend chain\n%!";
            None  (* JAL doesn't produce a decode mux *)
        | None ->
            Printf.printf "        Warning: instr node not found\n%!";
            None)
      end else if is_store_variant instr_name then begin
        Printf.printf "      Generating STORE S-type immediate extraction\n%!";
        (match find_node builder "instr" with
        | Some instr_node ->
            (* STORE S-type immediate:
               imm[11:5] = instr[31:25]
               imm[4:0]  = instr[11:7]
               Reconstruct: {instr[31:25], instr[11:7]} = 12-bit signed immediate *)

            (* Extract imm[11:5] from instr[31:25] *)
            let imm_hi = make_node
              ~display_name:(Some "instr[31:25]")
              ~operator:(Some "bit_slice")
              ~bit_width:(Some 7)
              ~bitslice:(Some (31, 25))
              "bit_slice" in
            let imm_hi_id = add_node builder imm_hi in
            connect builder instr_node imm_hi_id "bit_access";

            (* Extract imm[4:0] from instr[11:7] *)
            let imm_lo = make_node
              ~display_name:(Some "instr[11:7]")
              ~operator:(Some "bit_slice")
              ~bit_width:(Some 5)
              ~bitslice:(Some (11, 7))
              "bit_slice" in
            let imm_lo_id = add_node builder imm_lo in
            connect builder instr_node imm_lo_id "bit_access";

            (* Concatenate: {instr[31:25], instr[11:7]} *)
            let imm_concat = make_node
              ~display_name:(Some "stype_imm_concat")
              ~operator:(Some "concat")
              ~bit_width:(Some 12)
              "concatenation" in
            let imm_concat_id = add_node builder imm_concat in
            connect ~position:(Some "0") builder imm_hi_id imm_concat_id "concat_input";   (* HIGH bits *)
            connect ~position:(Some "1") builder imm_lo_id imm_concat_id "concat_input";   (* LOW bits *)

            (* Sign-extend 12-bit immediate to 32 bits *)
            let sign_ext = make_node
              ~display_name:(Some "sign_ext_stype_imm")
              ~operator:(Some "sign_extend")
              ~bit_width:(Some 32)
              "sign_extend" in
            let sign_ext_node = add_node builder sign_ext in
            connect builder imm_concat_id sign_ext_node "operand";

            Printf.printf "        Created STORE S-type immediate concat + sign-extend chain\n%!";
            None
        | None ->
            Printf.printf "        Warning: instr node not found\n%!";
            None)
      end else if instr_name = "ITYPE" then begin
        Printf.printf "      Generating ITYPE decode logic\n%!";
        (* Add exclusion constraints for funct3 values not used by ITYPE.
           ITYPE uses funct3 values {000,010,011,100,110,111} — values {001,101}
           belong to SHIFTIOP. This prevents decode overlap. *)
        let used_funct3 = [0; 2; 3; 4; 6; 7] in
        for f3 = 0 to 7 do
          if not (List.mem f3 used_funct3) then begin
            let val_str = Printf.sprintf "0b%c%c%c"
              (if f3 land 4 <> 0 then '1' else '0')
              (if f3 land 2 <> 0 then '1' else '0')
              (if f3 land 1 <> 0 then '1' else '0') in
            builder.decode_constraints <- builder.decode_constraints @
              [(14, 12, "!" ^ val_str)];
            Printf.printf "        ITYPE exclusion: funct3 != %s\n%!" val_str
          end
        done;
        (match find_node builder "instr" with
        | Some instr_node ->
            (* For ITYPE, extract only funct3 [14:12] *)
            let funct3_node = make_node
              ~display_name:(Some "funct3")
              ~operator:(Some "bit_slice")
              ~bit_width:(Some 3)
              ~bitslice:(Some (14, 12))
              "bit_slice" in
            let funct3_id = add_node builder funct3_node in
            connect builder instr_node funct3_id "bit_access";

            (* Use funct3 directly as the operation selector *)
            (* funct3=0b000->ADDI=0, 0b010->SLTI=1, 0b011->SLTIU=2, *)
            (* 0b111->ANDI=3, 0b110->ORI=4, 0b100->XORI=5 *)
            (* We need to map funct3 encoding to operation index *)

            (* Create mapping using nested ite (if-then-else) *)
            (* Map funct3 to operation index:
               0b000 (0) -> 0 (ADDI)
               0b010 (2) -> 1 (SLTI)
               0b011 (3) -> 2 (SLTIU)
               0b111 (7) -> 3 (ANDI)
               0b110 (6) -> 4 (ORI)
               0b100 (4) -> 5 (XORI)
            *)

            (* Build decode using comparisons and mux, similar to RTYPE *)
            (* Create constant nodes and comparisons for each operation *)
            let op_mappings = [
              ("ADDI",  0, 0);  (* funct3=0b000 -> op=0 *)
              ("SLTI",  2, 1);  (* funct3=0b010 -> op=1 *)
              ("SLTIU", 3, 2);  (* funct3=0b011 -> op=2 *)
              ("ANDI",  7, 3);  (* funct3=0b111 -> op=3 *)
              ("ORI",   6, 4);  (* funct3=0b110 -> op=4 *)
              ("XORI",  4, 5);  (* funct3=0b100 -> op=5 *)
            ] in

            let op_values = ref [] in
            List.iter (fun (op_name, f3, op_idx) ->
              (* Create constant for expected funct3 value *)
              let f3_const = make_node
                ~display_name:(Some (Printf.sprintf "const_0x%x" f3))
                ~operator:(Some "constant")
                ~value:(Some (string_of_int f3))
                ~bit_width:(Some 3)
                "constant" in
              let f3_const_id = add_node builder f3_const in

              (* Create comparison: funct3 == expected_f3 *)
              let f3_cmp = make_node
                ~display_name:(Some (Printf.sprintf "%s_f3_match" op_name))
                ~operator:(Some "==")
                "comparison" in
              let f3_cmp_id = add_node builder f3_cmp in
              connect builder funct3_id f3_cmp_id "operand";
              connect builder f3_const_id f3_cmp_id "operand";

              (* Create constant for operation index *)
              let op_const = make_node
                ~display_name:(Some (Printf.sprintf "op_%s" op_name))
                ~operator:(Some "constant")
                ~value:(Some (string_of_int op_idx))
                ~bit_width:(Some 32)
                "constant" in
              let op_const_id = add_node builder op_const in

              op_values := (f3_cmp_id, op_const_id) :: !op_values
            ) op_mappings;

            (* Build multiplexer using nested ite *)
            let mux_idx = ref 0 in
            let rec build_mux remaining =
              match remaining with
              | [] -> None
              | [(_enable_id, value_id)] -> Some value_id
              | (enable_id, value_id) :: rest ->
                  let else_branch = build_mux rest in
                  (match else_branch with
                  | Some else_id ->
                      let mux_name = Printf.sprintf "%s_%d"
                        (prefix_local_name builder "op_select") !mux_idx in
                      mux_idx := !mux_idx + 1;
                      let ite_node = make_node
                        ~display_name:(Some mux_name)
                        ~operator:(Some "?:")
                        ~bit_width:(Some 32)
                        "ternary_op" in
                      let ite_id = add_node builder ite_node in
                      connect builder enable_id ite_id "ternary_condition";
                      connect builder value_id ite_id "ternary_true";
                      connect builder else_id ite_id "ternary_false";
                      Some ite_id
                  | None -> Some value_id)
            in
            (match build_mux !op_values with
            | Some mux_output ->
                Printf.printf "        Created ITYPE decode mux\n%!";
                Some mux_output
            | None ->
                Printf.printf "        Warning: could not build ITYPE mux\n%!";
                None)
        | None ->
            Printf.printf "        Warning: instr node not found\n%!";
            None)
      end else if instr_name = "BTYPE" then begin
        Printf.printf "      Generating BTYPE decode logic\n%!";
        (match find_node builder "instr" with
        | Some instr_node ->
            (* For BTYPE, extract funct3 [14:12] *)
            let funct3_node = make_node
              ~display_name:(Some "funct3")
              ~operator:(Some "bit_slice")
              ~bit_width:(Some 3)
              ~bitslice:(Some (14, 12))
              "bit_slice" in
            let funct3_id = add_node builder funct3_node in
            connect builder instr_node funct3_id "bit_access";

            (* Map funct3 to operation index:
               BEQ:  0b000 (0) -> 0
               BNE:  0b001 (1) -> 1
               BLT:  0b100 (4) -> 2
               BGE:  0b101 (5) -> 3
               BLTU: 0b110 (6) -> 4
               BGEU: 0b111 (7) -> 5
            *)

            let op_mappings = [
              ("BEQ",  0, 0);
              ("BNE",  1, 1);
              ("BLT",  4, 2);
              ("BGE",  5, 3);
              ("BLTU", 6, 4);
              ("BGEU", 7, 5);
            ] in

            let op_values = ref [] in
            List.iter (fun (op_name, f3, op_idx) ->
              (* Create constant for expected funct3 value *)
              let f3_const = make_node
                ~display_name:(Some (Printf.sprintf "const_0x%x" f3))
                ~operator:(Some "constant")
                ~value:(Some (string_of_int f3))
                ~bit_width:(Some 3)
                "constant" in
              let f3_const_id = add_node builder f3_const in

              (* Create comparison: funct3 == expected_f3 *)
              let f3_cmp = make_node
                ~display_name:(Some (Printf.sprintf "%s_f3_match" op_name))
                ~operator:(Some "==")
                "comparison" in
              let f3_cmp_id = add_node builder f3_cmp in
              connect builder funct3_id f3_cmp_id "operand";
              connect builder f3_const_id f3_cmp_id "operand";

              (* Create constant for operation index *)
              let op_const = make_node
                ~display_name:(Some (Printf.sprintf "op_%s" op_name))
                ~operator:(Some "constant")
                ~value:(Some (string_of_int op_idx))
                ~bit_width:(Some 32)
                "constant" in
              let op_const_id = add_node builder op_const in

              op_values := (f3_cmp_id, op_const_id) :: !op_values
            ) op_mappings;

            (* Build multiplexer using nested ite *)
            let mux_idx = ref 0 in
            let rec build_mux remaining =
              match remaining with
              | [] -> None
              | [(_enable_id, value_id)] -> Some value_id
              | (enable_id, value_id) :: rest ->
                  let else_branch = build_mux rest in
                  (match else_branch with
                  | Some else_id ->
                      let mux_name = Printf.sprintf "%s_%d"
                        (prefix_local_name builder "op_select") !mux_idx in
                      mux_idx := !mux_idx + 1;
                      let ite_node = make_node
                        ~display_name:(Some mux_name)
                        ~operator:(Some "?:")
                        ~bit_width:(Some 32)
                        "ternary_op" in
                      let ite_id = add_node builder ite_node in
                      connect builder enable_id ite_id "ternary_condition";
                      connect builder value_id ite_id "ternary_true";
                      connect builder else_id ite_id "ternary_false";
                      Some ite_id
                  | None -> Some value_id)
            in
            (match build_mux !op_values with
            | Some mux_output ->
                Printf.printf "        Created BTYPE decode mux\n%!";
                Some mux_output
            | None ->
                Printf.printf "        Warning: could not build BTYPE mux\n%!";
                None)
        | None ->
            Printf.printf "        Warning: instr node not found\n%!";
            None)
      end else if instr_name = "UTYPE" then begin
        Printf.printf "      Generating UTYPE decode logic\n%!";
        (match find_node builder "instr" with
        | Some instr_node ->
            (* For UTYPE, extract immediate field [31:12] (20 bits) *)
            let imm_20bit = make_node
              ~display_name:(Some "imm_20bit")
              ~operator:(Some "bit_slice")
              ~bit_width:(Some 20)
              ~bitslice:(Some (31, 12))
              "bit_slice" in
            let imm_20bit_id = add_node builder imm_20bit in
            connect builder instr_node imm_20bit_id "bit_access";

            (* Create 12-bit zero constant (this is the 0x000 hex literal) *)
            let zero_12bit = make_node
              ~display_name:(Some "0x000")
              ~operator:(Some "constant")
              ~value:(Some "0")
              ~bit_width:(Some 12)
              "verilog_hex_literal" in
            let zero_12bit_id = add_node builder zero_12bit in

            (* Concatenate: imm_20bit @ 0x000 = 32 bits *)
            let imm_full = make_node
              ~display_name:(Some "imm @ 0x000")
              ~operator:(Some "concat")
              ~bit_width:(Some 32)
              "concat" in
            let imm_full_id = add_node builder imm_full in
            connect ~position:(Some "0") builder imm_20bit_id imm_full_id "concat_input";  (* HIGH bits *)
            connect ~position:(Some "1") builder zero_12bit_id imm_full_id "concat_input";  (* LOW bits *)

            Printf.printf "        Created UTYPE immediate extraction (imm @ 0x000)\n%!";

            (* Generate decode logic for LUI vs AUIPC *)
            (* Extract opcode field [6:0] *)
            let opcode_node = make_node
              ~display_name:(Some "opcode")
              ~operator:(Some "bit_slice")
              ~bit_width:(Some 7)
              ~bitslice:(Some (6, 0))
              "bit_slice" in
            let opcode_id = add_node builder opcode_node in
            connect builder instr_node opcode_id "bit_access";

            (* Map opcode to operation index:
               LUI:   0b0110111 (55) -> 0
               AUIPC: 0b0010111 (23) -> 1
            *)
            let op_mappings = [
              ("LUI",   55, 0);
              ("AUIPC", 23, 1);
            ] in

            let op_values = ref [] in
            List.iter (fun (op_name, opcode_val, op_idx) ->
              (* Create constant for expected opcode value *)
              let opcode_const = make_node
                ~display_name:(Some (Printf.sprintf "const_0x%02x" opcode_val))
                ~operator:(Some "constant")
                ~value:(Some (string_of_int opcode_val))
                ~bit_width:(Some 7)
                "constant" in
              let opcode_const_id = add_node builder opcode_const in

              (* Create comparison: opcode == expected_opcode *)
              let opcode_cmp = make_node
                ~display_name:(Some (Printf.sprintf "%s_opcode_match" op_name))
                ~operator:(Some "==")
                "comparison" in
              let opcode_cmp_id = add_node builder opcode_cmp in
              connect builder opcode_id opcode_cmp_id "operand";
              connect builder opcode_const_id opcode_cmp_id "operand";

              (* Create constant for operation index *)
              let op_const = make_node
                ~display_name:(Some (Printf.sprintf "op_%s" op_name))
                ~operator:(Some "constant")
                ~value:(Some (string_of_int op_idx))
                ~bit_width:(Some 32)
                "constant" in
              let op_const_id = add_node builder op_const in

              op_values := (opcode_cmp_id, op_const_id) :: !op_values
            ) op_mappings;

            (* Build multiplexer using ite *)
            let rec build_mux remaining =
              match remaining with
              | [] -> None
              | [(_enable_id, value_id)] -> Some value_id
              | (enable_id, value_id) :: rest ->
                  let else_branch = build_mux rest in
                  (match else_branch with
                  | Some else_id ->
                      let ite_node = make_node
                        ~display_name:(Some (prefix_local_name builder "op_select"))
                        ~operator:(Some "?:")
                        ~bit_width:(Some 32)
                        "ternary_op" in
                      let ite_id = add_node builder ite_node in
                      connect builder enable_id ite_id "ternary_condition";
                      connect builder value_id ite_id "ternary_true";
                      connect builder else_id ite_id "ternary_false";
                      Some ite_id
                  | None -> Some value_id)
            in
            (match build_mux !op_values with
            | Some mux_output ->
                Printf.printf "        Created UTYPE decode mux\n%!";
                Some mux_output
            | None ->
                Printf.printf "        Warning: could not build UTYPE mux\n%!";
                None)
        | None ->
            Printf.printf "        Warning: instr node not found\n%!";
            None)
      end else if instr_name = "SHIFTIOP" then begin
        Printf.printf "      Generating SHIFTIOP decode logic\n%!";
        (match find_node builder "instr" with
        | Some instr_node ->
            (* For SHIFTIOP, extract funct7 [31:25] and funct3 [14:12] *)
            let funct7_node = make_node
              ~display_name:(Some "funct7")
              ~operator:(Some "bit_slice")
              ~bit_width:(Some 7)
              ~bitslice:(Some (31, 25))
              "bit_slice" in
            let funct7_id = add_node builder funct7_node in
            connect builder instr_node funct7_id "bit_access";

            let funct3_node = make_node
              ~display_name:(Some "funct3")
              ~operator:(Some "bit_slice")
              ~bit_width:(Some 3)
              ~bitslice:(Some (14, 12))
              "bit_slice" in
            let funct3_id = add_node builder funct3_node in
            connect builder instr_node funct3_id "bit_access";

            (* Map funct7+funct3 to operation index:
               SLLI: funct7=0x00 (0),  funct3=0x1 (1) -> 0
               SRLI: funct7=0x00 (0),  funct3=0x5 (5) -> 1
               SRAI: funct7=0x20 (32), funct3=0x5 (5) -> 2
            *)
            let op_mappings = [
              ("SLLI", 0x00, 0x1, 0);
              ("SRLI", 0x00, 0x5, 1);
              ("SRAI", 0x20, 0x5, 2);
            ] in

            let op_values = ref [] in
            List.iter (fun (op_name, f7_val, f3_val, op_idx) ->
              (* Create constant for expected funct7 value *)
              let f7_const = make_node
                ~display_name:(Some (Printf.sprintf "const_0x%02x" f7_val))
                ~operator:(Some "constant")
                ~value:(Some (string_of_int f7_val))
                ~bit_width:(Some 7)
                "constant" in
              let f7_const_id = add_node builder f7_const in

              (* Create comparison: funct7 == expected_f7 *)
              let f7_cmp = make_node
                ~display_name:(Some (Printf.sprintf "%s_f7_match" op_name))
                ~operator:(Some "==")
                "comparison" in
              let f7_cmp_id = add_node builder f7_cmp in
              connect builder funct7_id f7_cmp_id "operand";
              connect builder f7_const_id f7_cmp_id "operand";

              (* Create constant for expected funct3 value *)
              let f3_const = make_node
                ~display_name:(Some (Printf.sprintf "const_0x%x" f3_val))
                ~operator:(Some "constant")
                ~value:(Some (string_of_int f3_val))
                ~bit_width:(Some 3)
                "constant" in
              let f3_const_id = add_node builder f3_const in

              (* Create comparison: funct3 == expected_f3 *)
              let f3_cmp = make_node
                ~display_name:(Some (Printf.sprintf "%s_f3_match" op_name))
                ~operator:(Some "==")
                "comparison" in
              let f3_cmp_id = add_node builder f3_cmp in
              connect builder funct3_id f3_cmp_id "operand";
              connect builder f3_const_id f3_cmp_id "operand";

              (* Create AND: enable = (f7_match && f3_match) *)
              let enable_node = make_node
                ~display_name:(Some (Printf.sprintf "%s_enable" op_name))
                ~operator:(Some "&&")
                "logical_and" in
              let enable_id = add_node builder enable_node in
              connect builder f7_cmp_id enable_id "logic_input";
              connect builder f3_cmp_id enable_id "logic_input";

              (* Create constant for operation index *)
              let op_const = make_node
                ~display_name:(Some (Printf.sprintf "op_%s" op_name))
                ~operator:(Some "constant")
                ~value:(Some (string_of_int op_idx))
                ~bit_width:(Some 32)
                "constant" in
              let op_const_id = add_node builder op_const in

              op_values := (enable_id, op_const_id) :: !op_values
            ) op_mappings;

            (* Build multiplexer using nested ite *)
            let mux_idx = ref 0 in
            let rec build_mux remaining =
              match remaining with
              | [] -> None
              | [(_enable_id, value_id)] -> Some value_id
              | (enable_id, value_id) :: rest ->
                  let else_branch = build_mux rest in
                  (match else_branch with
                  | Some else_id ->
                      let mux_name = Printf.sprintf "%s_%d"
                        (prefix_local_name builder "op_select") !mux_idx in
                      mux_idx := !mux_idx + 1;
                      let ite_node = make_node
                        ~display_name:(Some mux_name)
                        ~operator:(Some "?:")
                        ~bit_width:(Some 32)
                        "ternary_op" in
                      let ite_id = add_node builder ite_node in
                      connect builder enable_id ite_id "ternary_condition";
                      connect builder value_id ite_id "ternary_true";
                      connect builder else_id ite_id "ternary_false";
                      Some ite_id
                  | None -> Some value_id)
            in
            (match build_mux !op_values with
            | Some mux_output ->
                Printf.printf "        Created SHIFTIOP decode mux\n%!";
                Some mux_output
            | None ->
                Printf.printf "        Warning: could not build SHIFTIOP mux\n%!";
                None)
        | None ->
            Printf.printf "        Warning: instr node not found\n%!";
            None)
      end else begin
        (* RTYPE and other patterns *)
        (* Extract operation encodings using hard-coded table *)
        let op_encodings = extract_op_encodings clauses in

        if List.length op_encodings > 0 then begin
          List.iter (fun (op_name, f7, f3) ->
            Printf.printf "        %s: funct7=0x%02x funct3=0x%x\n%!" op_name f7 f3
          ) op_encodings;
          (match find_node builder "instr" with
          | Some instr_node ->
              (* Create funct7 and funct3 bit slices *)
              let funct7_node = make_node
              ~display_name:(Some "funct7")
              ~operator:(Some "bit_slice")
              ~bit_width:(Some 7)
              ~bitslice:(Some (31, 25))
              "bit_slice" in
            let funct7_id = add_node builder funct7_node in
            connect builder instr_node funct7_id "bit_access";

            let funct3_node = make_node
              ~display_name:(Some "funct3")
              ~operator:(Some "bit_slice")
              ~bit_width:(Some 3)
              ~bitslice:(Some (14, 12))
              "bit_slice" in
            let funct3_id = add_node builder funct3_node in
            connect builder instr_node funct3_id "bit_access";

            (* For each operation, create: constant for op_name, comparisons, and enable signal *)
            let op_values = ref [] in
            let op_counter = ref 0 in
            List.iter (fun (op_name, f7, f3) ->
              (* Create constant nodes for expected funct7 and funct3 values *)
              let f7_const = make_node
                ~display_name:(Some (Printf.sprintf "const_0x%02x" f7))
                ~operator:(Some "constant")
                ~value:(Some (string_of_int f7))
                ~bit_width:(Some 7)
                "constant" in
              let f7_const_id = add_node builder f7_const in

              let f3_const = make_node
                ~display_name:(Some (Printf.sprintf "const_0x%x" f3))
                ~operator:(Some "constant")
                ~value:(Some (string_of_int f3))
                ~bit_width:(Some 3)
                "constant" in
              let f3_const_id = add_node builder f3_const in

              (* Create comparisons: funct7 == expected_f7 *)
              let f7_cmp = make_node
                ~display_name:(Some (Printf.sprintf "%s_f7_match" op_name))
                ~operator:(Some "==")
                "comparison" in
              let f7_cmp_id = add_node builder f7_cmp in
              connect builder funct7_id f7_cmp_id "operand";
              connect builder f7_const_id f7_cmp_id "operand";

              (* Create comparison: funct3 == expected_f3 *)
              let f3_cmp = make_node
                ~display_name:(Some (Printf.sprintf "%s_f3_match" op_name))
                ~operator:(Some "==")
                "comparison" in
              let f3_cmp_id = add_node builder f3_cmp in
              connect builder funct3_id f3_cmp_id "operand";
              connect builder f3_const_id f3_cmp_id "operand";

              (* Create AND: enable = (f7_match && f3_match) *)
              let enable_node = make_node
                ~display_name:(Some (Printf.sprintf "%s_enable" op_name))
                ~operator:(Some "&&")
                "logical_and" in
              let enable_id = add_node builder enable_node in
              connect builder f7_cmp_id enable_id "logic_input";
              connect builder f3_cmp_id enable_id "logic_input";

              (* Create constant for operation index *)
              (* Use enumeration order as index for multiplexer selection *)
              let op_index = string_of_int !op_counter in
              incr op_counter;
              let op_const = make_node
                ~display_name:(Some (Printf.sprintf "op_%s" op_name))
                ~operator:(Some "constant")
                ~value:(Some op_index)
                ~bit_width:(Some 32)
                "constant" in
              let op_const_id = add_node builder op_const in

              op_values := (enable_id, op_const_id) :: !op_values
            ) op_encodings;

            (* Create multiplexer to select operation based on enables *)
            (* For now, use a series of ite (if-then-else) operations *)
            let rec build_mux remaining =
              match remaining with
              | [] -> None
              | [(_enable_id, value_id)] -> Some value_id  (* Last case, no ite needed *)
              | (enable_id, value_id) :: rest ->
                  let else_branch = build_mux rest in
                  (match else_branch with
                  | Some else_id ->
                      let ite_node = make_node
                        ~display_name:(Some (prefix_local_name builder "op_select"))
                        ~operator:(Some "?:")
                        ~bit_width:(Some 32)
                        "ternary_op" in
                      let ite_id = add_node builder ite_node in
                      connect builder enable_id ite_id "ternary_condition";
                      connect builder value_id ite_id "ternary_true";
                      connect builder else_id ite_id "ternary_false";
                      Some ite_id
                  | None -> Some value_id)
            in
            (match build_mux !op_values with
            | Some mux_output ->
                (* Return decode output to be connected later *)
                Printf.printf "        Created decode mux, will connect to op after execute clause\n%!";
                Some mux_output
            | None ->
                Printf.printf "        Warning: could not build mux\n%!";
                None)
        | None ->
            Printf.printf "        Warning: instr node not found\n%!";
            None)
      end else begin
        None
      end
      end  (* Close RTYPE/other patterns else branch *)
    end else begin
      None
    end

  (* Walk SAIL expressions and build graph *)
  let rec visit_exp builder (E_aux (exp_aux, _annot)) =
    (* Handle variable shadowing: if a var node with this name already
       exists, rename the old one so the newest binding keeps the
       canonical name.  This ensures the Verilog generator picks up
       the final value (e.g. overflow-checked quotient in DIV). *)
    let rename_shadowed_vars prefixed_name =
      let shadow_counter = ref 0 in
      builder.nodes <- List.map (fun (n : rg_node) ->
        match n.node_type, n.display_name with
        | "var", Some dn when dn = prefixed_name ->
            let idx = !shadow_counter in
            incr shadow_counter;
            let renamed = Printf.sprintf "%s_shadowed_%d" prefixed_name idx in
            Printf.printf "        Variable shadowing: renaming %s (%s) -> %s\n%!" dn n.id renamed;
            { n with display_name = Some renamed; name = Some renamed }
        | _ -> n
      ) builder.nodes
    in
    (* Debug: Print expression types *)
    (match exp_aux with
      | E_block exps -> Printf.printf "          visit_exp: E_block (%d exprs)\n%!" (List.length exps)
      | E_id id -> Printf.printf "          visit_exp: E_id(%s)\n%!" (string_of_id id)
      | E_lit _ -> Printf.printf "          visit_exp: E_lit\n%!"
      | E_app _ -> () (* Already handled by deeper debug *)
      | E_assign _ -> Printf.printf "          visit_exp: E_assign\n%!"
      | E_return _ -> Printf.printf "          visit_exp: E_return\n%!"
      | E_tuple _ -> Printf.printf "          visit_exp: E_tuple\n%!"
      | E_if _ -> Printf.printf "          visit_exp: E_if\n%!"
      | E_match _ -> Printf.printf "          visit_exp: E_match\n%!"
      | E_let _ -> Printf.printf "          visit_exp: E_let\n%!"
      | E_typ _ -> Printf.printf "          visit_exp: E_typ\n%!"
      | E_var _ -> Printf.printf "          visit_exp: E_var\n%!"
      | E_internal_return _ -> Printf.printf "          visit_exp: E_internal_return\n%!"
      | E_internal_plet _ -> Printf.printf "          visit_exp: E_internal_plet\n%!"
      | E_internal_value _ -> Printf.printf "          visit_exp: E_internal_value\n%!"
      | _ -> Printf.printf "          visit_exp: OTHER\n%!");

    match exp_aux with

    (* Binary arithmetic operations *)
    (* IMPORTANT: Exclude functions that need special handling in the general E_app handler *)
    | E_app (id, [left; right]) when
        let op_name = string_of_id id in
        not (List.mem op_name ["wX"; "wX_bits"; "wGPR"; "write_register"; "extend_value";
                                (* FP register access *)
                                "rF_or_X_S"; "rF_or_X_D"; "rF_or_X_H";
                                "wF_or_X_S"; "wF_or_X_D"; "wF_or_X_H";
                                "wF_S"; "wF_D"; "wF_H"; "wF_bits";
                                (* FP helpers *)
                                "accrue_fflags"; "select_instr_or_fcsr_rm";
                                (* M-extension: handled in general E_app as identity *)
                                "to_bits_truncate"])
        (* Also exclude Berkeley softfloat intrinsics: riscv_f*, riscv_i*ToF*, riscv_ui*ToF* *)
        && not (String.length op_name > 6 && String.sub op_name 0 6 = "riscv_"
                && (op_name.[6] = 'f' || op_name.[6] = 'i' || op_name.[6] = 'u')) ->
        let op_name = string_of_id id in
        let operator = match op_name with
          | "add_bits" | "add_int" | "add_vec" | "add_atom" -> Some "+"
          | "sub_bits" | "sub_int" | "sub_vec" | "sub_atom" -> Some "-"
          | "mult" | "mult_int" | "mult_vec" | "mult_atom" -> Some "*"
          | "div" | "div_int" -> Some "/"
          | "append" -> Some "@"  (* Bit concatenation *)
          | "eq_bits" | "eq_int" -> Some "=="
          | "neq_bits" | "neq_int" -> Some "!="
          | "lt_int" -> Some "<"
          | "lteq_int" -> Some "<="
          | "gt_int" -> Some ">"
          | "gteq_int" -> Some ">="
          | "and_bool" | "and" -> Some "&&"
          | "and_vec" -> Some "&"
          | "or_bool" | "or" -> Some "||"
          | "or_vec" -> Some "|"
          | "xor_vec" -> Some "^"
          | "shift_bits_left" | "shiftl" -> Some "<<"
          | "shift_bits_right" | "shiftr" -> Some ">>"
          | "shift_bits_right_arith" -> Some ">>>"
          (* SAIL signed comparison operators -> Verilog generator conventions *)
          | "<_s" -> Printf.printf "        MAPPED <_s -> <s\n%!"; Some "<s"
          | ">_s" -> Printf.printf "        MAPPED >_s -> >s\n%!"; Some ">s"
          | "<=_s" -> Printf.printf "        MAPPED <=_s -> <=s\n%!"; Some "<=s"
          | ">=_s" -> Printf.printf "        MAPPED >=_s -> >=s\n%!"; Some ">=s"
          (* SAIL unsigned comparison operators -> plain Verilog (unsigned by default) *)
          | "<_u" -> Printf.printf "        MAPPED <_u -> <\n%!"; Some "<"
          | ">_u" -> Printf.printf "        MAPPED >_u -> >\n%!"; Some ">"
          | "<=_u" -> Printf.printf "        MAPPED <=_u -> <=\n%!"; Some "<="
          | ">=_u" -> Printf.printf "        MAPPED >=_u -> >=\n%!"; Some ">="
          (* M-extension: integer division/remainder helpers *)
          | "quot_round_zero" | "quot_positive_round_zero" ->
              (match builder.m_ext_variant with
               | Some "divu" | Some "remu" -> Some "/"
               | _ -> Some "/s")
          | "rem_round_zero" | "rem_positive_round_zero" ->
              (match builder.m_ext_variant with
               | Some "divu" | Some "remu" -> Some "%"
               | _ -> Some "%s")
          | _ -> Some op_name
        in
        (* Signed division overflow check elimination:
           SAIL compares mathematical (unbounded) integers: quotient >= 2^(xlen-1).
           This can't be represented correctly in 32-bit bitvectors: negative signed
           quotients appear as large unsigned values, incorrectly triggering the check.
           Verilog's $signed() /s already handles INT_MIN/-1 correctly (returns INT_MIN),
           so the overflow check is redundant in hardware.  Replace gteq_int with
           constant false to disable it. *)
        if op_name = "gteq_int" && builder.m_ext_variant = Some "div" then begin
          (* Signed division overflow: SAIL checks quotient >= 2^(xlen-1) on mathematical
             integers, which can't be done correctly with 32-bit bitvectors.  Replace with
             the equivalent hardware check: rs1 == INT_MIN && rs2 == -1 (the only input
             combination that produces quotient >= 2^31).  This also avoids C/Verilator
             undefined behavior from INT_MIN / -1. *)
          Printf.printf "        DIV overflow check: replacing gteq_int with (rs1==INT_MIN && rs2==-1)\n%!";
          let _ = visit_exp builder left in
          let _ = visit_exp builder right in
          let prefix = builder.instr_prefix in
          let rs1_name = prefix ^ "_rs1_bits" in
          let rs2_name = prefix ^ "_rs2_bits" in
          let rs1_node = match find_node builder "rs1_bits" with
            | Some n -> n
            | None -> make_node ~display_name:(Some rs1_name) "var" |> add_node builder in
          let rs2_node = match find_node builder "rs2_bits" with
            | Some n -> n
            | None -> make_node ~display_name:(Some rs2_name) "var" |> add_node builder in
          (* rs1_bits == 32'h80000000 *)
          let int_min = make_node ~display_name:(Some "2147483648") ~value:(Some "2147483648")
                                  ~bit_width:(Some 32) "literal" |> add_node builder in
          let cmp1 = make_node ~operator:(Some "==") ~display_name:(Some "rs1==INT_MIN")
                               ~bit_width:(Some 1) "comparison" |> add_node builder in
          connect ~position:(Some "left") builder rs1_node cmp1 "operand";
          connect ~position:(Some "right") builder int_min cmp1 "operand";
          (* rs2_bits == 32'hFFFFFFFF *)
          let neg_one = make_node ~display_name:(Some "4294967295") ~value:(Some "4294967295")
                                  ~bit_width:(Some 32) "literal" |> add_node builder in
          let cmp2 = make_node ~operator:(Some "==") ~display_name:(Some "rs2==-1")
                               ~bit_width:(Some 1) "comparison" |> add_node builder in
          connect ~position:(Some "left") builder rs2_node cmp2 "operand";
          connect ~position:(Some "right") builder neg_one cmp2 "operand";
          (* cmp1 && cmp2 *)
          let and_node = make_node ~operator:(Some "&&") ~display_name:(Some "div_overflow")
                                   ~bit_width:(Some 1) "operation" |> add_node builder in
          connect ~position:(Some "left") builder cmp1 and_node "operand";
          connect ~position:(Some "right") builder cmp2 and_node "operand";
          and_node
        end else
        let left_node = visit_exp builder left in
        (* For concat: imm @ 0x000, calculate hex literal width from left operand *)
        (* Visit right node normally first *)
        let right_node_temp = visit_exp builder right in
        (* If this is concat with hex literal and left has known width, calculate right width *)
        let right_node = if op_name = "append" && right_node_temp.node_type = "verilog_hex_literal" then begin
          match left_node.bit_width with
          | Some left_width when left_width > 0 && left_width < 32 ->
              (* Calculate hex literal width as 32 - left_width *)
              let hex_width = 32 - left_width in
              Printf.printf "        DEBUG: append detected, left_width=%d, setting hex literal width=%d\n%!" left_width hex_width;
              let s = Option.value ~default:"hex" right_node_temp.value in
              let display_name = Option.value ~default:"0xhex" right_node_temp.display_name in
              make_node ~display_name:(Some display_name) ~value:(Some s) ~bit_width:(Some hex_width) "verilog_hex_literal"
              |> add_node builder
          | _ ->
              Printf.printf "        DEBUG: append detected but left width not suitable for calculation\n%!";
              right_node_temp
        end else
          right_node_temp
        in
        let display = match operator with
          | Some op ->
              Printf.sprintf "%s %s %s"
                (Option.value ~default:"?" left_node.display_name)
                op
                (Option.value ~default:"?" right_node.display_name)
          | None -> op_name
        in
        (* sign_extend/zero_extend: left arg is type constant (ignored), right arg is data.
           Handle separately to set proper node_type for the Verilog generator. *)
        if op_name = "sign_extend" || op_name = "zero_extend"
           || op_name = "sail_sign_extend" || op_name = "sail_zero_extend" then begin
          let ext_type = if op_name = "zero_extend" || op_name = "sail_zero_extend"
                         then "zero_extend" else "sign_extend" in
          Printf.printf "        DEBUG: %s -> type=%s, bit_width=32 (xlen)\n%!" op_name ext_type;
          let ext_node = make_node ~operator:(Some ext_type) ~display_name:(Some display)
                                   ~bit_width:(Some 32) ext_type in
          let ext_node = add_node builder ext_node in
          (* Only connect the data operand (right), not the type constant (left) *)
          connect builder right_node ext_node "operand";
          ext_node
        end else begin
          (* For concat with known widths, set the concatenation result width to sum of operand widths *)
          let op_node = if op_name = "append" && right_node.bit_width <> None && left_node.bit_width <> None then
            let left_w = Option.get left_node.bit_width in
            let right_w = Option.get right_node.bit_width in
            let concat_width = left_w + right_w in
            Printf.printf "        DEBUG: append result width = %d + %d = %d\n%!" left_w right_w concat_width;
            make_node ~operator ~display_name:(Some display) ~bit_width:(Some concat_width) "operation"
          else
            make_node ~operator ~display_name:(Some display) "operation"
          in
          let op_node = add_node builder op_node in
          connect ~position:(Some "left") builder left_node op_node "operand";
          connect ~position:(Some "right") builder right_node op_node "operand";
          op_node
        end

    (* Function application with 0, 1, or 3+ args *)
    | E_app (id, args) ->
        let func_name = string_of_id id in
        Printf.printf "        DEBUG: E_app func_name='%s'\n%!" func_name;
        let arg_nodes_initial = List.map (visit_exp builder) args in

        (* Special handling for bitvector_concat with hex literal: calculate hex width from left operand *)
        let arg_nodes = if func_name = "bitvector_concat" && List.length arg_nodes_initial = 2 then begin
          Printf.printf "        DEBUG: bitvector_concat detected with 2 args\n%!";
          match arg_nodes_initial with
          | [left_node; right_node] ->
              Printf.printf "        DEBUG: left type=%s bit_width=%s, right type=%s\n%!"
                left_node.node_type
                (match left_node.bit_width with Some w -> string_of_int w | None -> "none")
                right_node.node_type;
              (* If right arg is a hex literal, calculate its width: 32 - left_width *)
              if right_node.node_type = "verilog_hex_literal" then begin
                Printf.printf "        DEBUG: Right is hex literal\n%!";
                match left_node.bit_width with
                | Some left_width when left_width > 0 && left_width < 32 ->
                    let hex_width = 32 - left_width in
                    Printf.printf "        DEBUG: Recreating hex literal with width=%d (32 - %d)\n%!" hex_width left_width;
                    let s = Option.value ~default:"hex" right_node.value in
                    let display_name = Option.value ~default:"0xhex" right_node.display_name in
                    let new_right = make_node ~display_name:(Some display_name) ~value:(Some s)
                                             ~bit_width:(Some hex_width) "verilog_hex_literal"
                                   |> add_node builder in
                    [left_node; new_right]
                | _ ->
                    Printf.printf "        DEBUG: Left width doesn't meet criteria\n%!";
                    arg_nodes_initial
              end else begin
                Printf.printf "        DEBUG: Right is not hex literal\n%!";
                arg_nodes_initial
              end
          | _ ->
              Printf.printf "        DEBUG: Pattern match failed\n%!";
              arg_nodes_initial
        end else
          arg_nodes_initial
        in

        (* IMPORTANT: Check for register writes FIRST, before inlining *)
        (* wX_bits should create array_write, not be inlined *)
        let is_register_write = List.mem func_name ["wX"; "wX_bits"; "wGPR"; "write_register"] in

        (* Only attempt inlining for non-register-write functions *)
        (* REMOVED rX and rX_bits from inlinable list so they create array_read nodes *)
        let inlinable_funcs = [] in  (* Previously ["rX"; "rX_bits"], but we want array_read nodes *)
        let param_names_map = [
          ("wX", ["r"; "in_v"]);
          ("wX_bits", ["i"; "data"]);
          ("rX", ["r"]);
          ("rX_bits", ["r"]);
        ] in

        (* Attempt inlining if function is inlinable (but NOT for register writes) *)
        let inlining_result =
          if (not is_register_write) && List.mem func_name inlinable_funcs then begin
            Printf.printf "        DEBUG: Attempting to inline function '%s'\n%!" func_name;
            match Hashtbl.find_opt builder.helper_graphs func_name with
            | Some func_graph ->
                Printf.printf "        DEBUG: Found helper graph for '%s', inlining...\n%!" func_name;
                (try
                  let param_names = List.assoc func_name param_names_map in
                  inline_function_call builder func_graph param_names arg_nodes
                with Not_found ->
                  Printf.printf "        DEBUG: Parameter names not found for '%s'\n%!" func_name;
                  None)
            | None ->
                Printf.printf "        DEBUG: No helper graph found for '%s'\n%!" func_name;
                None
          end else
            None
        in

        (* If inlining succeeded, return the inlined result *)
        (match inlining_result with
        | Some result_node ->
            Printf.printf "        DEBUG: Successfully inlined '%s', returning result\n%!" func_name;
            result_node
        | None ->
            (* Inlining didn't happen, continue with normal handling *)
            Printf.printf "        DEBUG: Processing '%s' with normal handling\n%!" func_name;

            (* bool_to_bit/bool_to_bits: identity in hardware (comparisons already produce bits) *)
            if (func_name = "bool_to_bit" || func_name = "bool_to_bits") && List.length arg_nodes >= 1 then
              List.hd arg_nodes
            else

            (* float_class_onehot_bits: identity - the hardware fclass already produces
               one-hot encoding, this SAIL mapping just converts enum->bits *)
            if (func_name = "float_class_onehot_bits" || func_name = "float_class_onehot_bits_forwards") && List.length arg_nodes >= 1 then
              List.hd arg_nodes
            else

            (* M-extension: unsigned()/signed() are identity in hardware when signedness
               is already handled by the operator (e.g., /s vs /, %s vs %).
               In Verilog, bits don't change - only interpretation does. *)
            if (func_name = "unsigned" || func_name = "signed"
                || func_name = "sail_unsigned" || func_name = "sail_signed")
               && builder.m_ext_variant <> None
               && List.length arg_nodes >= 1 then begin
              Printf.printf "        DEBUG: %s -> identity (M-extension context)\n%!" func_name;
              List.hd arg_nodes
            end else

            (* M-extension: mult_to_bits_half(xlen, signed_rs1, signed_rs2, rs1_bits, rs2_bits, result_part) *)
            if func_name = "mult_to_bits_half" && List.length arg_nodes >= 5 then begin
              Printf.printf "        DEBUG: mult_to_bits_half with m_ext_variant=%s\n%!"
                (match builder.m_ext_variant with Some v -> v | None -> "none");
              let rs1_node = List.nth arg_nodes 3 in
              let rs2_node = List.nth arg_nodes 4 in
              match builder.m_ext_variant with
              | Some "mulh" ->
                  (* MULH: upper 32 bits of signed(rs1) * signed(rs2) *)
                  let ext1 = make_node ~operator:(Some "sign_extend") ~display_name:(Some "sext_rs1_64")
                                       ~bit_width:(Some 64) "sign_extend" |> add_node builder in
                  connect builder rs1_node ext1 "operand";
                  let ext2 = make_node ~operator:(Some "sign_extend") ~display_name:(Some "sext_rs2_64")
                                       ~bit_width:(Some 64) "sign_extend" |> add_node builder in
                  connect builder rs2_node ext2 "operand";
                  let mul64 = make_node ~operator:(Some "*") ~display_name:(Some "product_64")
                                        ~bit_width:(Some 64) "operation" |> add_node builder in
                  connect ~position:(Some "left") builder ext1 mul64 "operand";
                  connect ~position:(Some "right") builder ext2 mul64 "operand";
                  let slice = make_node ~operator:(Some "bit_slice") ~display_name:(Some "product_hi")
                                        ~bit_width:(Some 32) ~bitslice:(Some (63, 32)) "bit_slice"
                              |> add_node builder in
                  connect builder mul64 slice "operand";
                  slice
              | Some "mulhsu" ->
                  (* MULHSU: upper 32 bits of signed(rs1) * unsigned(rs2) *)
                  let ext1 = make_node ~operator:(Some "sign_extend") ~display_name:(Some "sext_rs1_64")
                                       ~bit_width:(Some 64) "sign_extend" |> add_node builder in
                  connect builder rs1_node ext1 "operand";
                  let ext2 = make_node ~operator:(Some "zero_extend") ~display_name:(Some "zext_rs2_64")
                                       ~bit_width:(Some 64) "zero_extend" |> add_node builder in
                  connect builder rs2_node ext2 "operand";
                  let mul64 = make_node ~operator:(Some "*") ~display_name:(Some "product_64")
                                        ~bit_width:(Some 64) "operation" |> add_node builder in
                  connect ~position:(Some "left") builder ext1 mul64 "operand";
                  connect ~position:(Some "right") builder ext2 mul64 "operand";
                  let slice = make_node ~operator:(Some "bit_slice") ~display_name:(Some "product_hi")
                                        ~bit_width:(Some 32) ~bitslice:(Some (63, 32)) "bit_slice"
                              |> add_node builder in
                  connect builder mul64 slice "operand";
                  slice
              | Some "mulhu" ->
                  (* MULHU: upper 32 bits of unsigned(rs1) * unsigned(rs2) *)
                  let ext1 = make_node ~operator:(Some "zero_extend") ~display_name:(Some "zext_rs1_64")
                                       ~bit_width:(Some 64) "zero_extend" |> add_node builder in
                  connect builder rs1_node ext1 "operand";
                  let ext2 = make_node ~operator:(Some "zero_extend") ~display_name:(Some "zext_rs2_64")
                                       ~bit_width:(Some 64) "zero_extend" |> add_node builder in
                  connect builder rs2_node ext2 "operand";
                  let mul64 = make_node ~operator:(Some "*") ~display_name:(Some "product_64")
                                        ~bit_width:(Some 64) "operation" |> add_node builder in
                  connect ~position:(Some "left") builder ext1 mul64 "operand";
                  connect ~position:(Some "right") builder ext2 mul64 "operand";
                  let slice = make_node ~operator:(Some "bit_slice") ~display_name:(Some "product_hi")
                                        ~bit_width:(Some 32) ~bitslice:(Some (63, 32)) "bit_slice"
                              |> add_node builder in
                  connect builder mul64 slice "operand";
                  slice
              | _ ->
                  (* MUL (default): lower 32 bits of rs1 * rs2 *)
                  let mul_node = make_node ~operator:(Some "*") ~display_name:(Some "rs1 * rs2")
                                           ~bit_width:(Some 32) "operation" |> add_node builder in
                  connect ~position:(Some "left") builder rs1_node mul_node "operand";
                  connect ~position:(Some "right") builder rs2_node mul_node "operand";
                  mul_node
            end else

            (* to_bits_truncate: identity/truncation - return the data operand *)
            if func_name = "to_bits_truncate" && List.length arg_nodes >= 1 then begin
              Printf.printf "        DEBUG: to_bits_truncate -> identity\n%!";
              List.nth arg_nodes (List.length arg_nodes - 1)
            end else

            (* negate/negate_atom/negate_int: unary negation -> 0 - x *)
            if (func_name = "negate" || func_name = "negate_atom" || func_name = "negate_int") && List.length arg_nodes >= 1 then begin
              Printf.printf "        DEBUG: %s -> unary negation\n%!" func_name;
              let operand = List.hd arg_nodes in
              let zero = make_node ~display_name:(Some "0") ~value:(Some "0")
                                   ~bit_width:(Some 32) "literal" |> add_node builder in
              let neg_node = make_node ~operator:(Some "-") ~display_name:(Some "negate")
                                       ~bit_width:(Some 32) "operation" |> add_node builder in
              connect ~position:(Some "left") builder zero neg_node "operand";
              connect ~position:(Some "right") builder operand neg_node "operand";
              neg_node
            end else

            (* pow2: power of 2 = 1 << n *)
            if func_name = "pow2" && List.length arg_nodes >= 1 then begin
              Printf.printf "        DEBUG: pow2 -> 1 << n\n%!";
              let n_node = List.hd arg_nodes in
              let one = make_node ~display_name:(Some "1") ~value:(Some "1")
                                  ~bit_width:(Some 32) "literal" |> add_node builder in
              let shift_node = make_node ~operator:(Some "<<") ~display_name:(Some "1 << n")
                                         ~bit_width:(Some 32) "operation" |> add_node builder in
              connect ~position:(Some "left") builder one shift_node "operand";
              connect ~position:(Some "right") builder n_node shift_node "operand";
              shift_node
            end else

            (* Check if this is a known built-in that should be an operation node *)
        let (node_type, operator) = match func_name with
          (* Type conversions and extensions *)
          | "sign_extend" | "zero_extend" | "truncate"
          | "sail_sign_extend" | "sail_zero_extend"
          | "to_bits" | "unsigned" | "signed"
          | "sail_unsigned" | "sail_signed" ->
              ("operation", Some func_name)

          (* Arithmetic operations - normalize SAIL variants to standard operators *)
          | "add_vec" | "add_bits" | "add_atom" ->
              ("operation", Some "+")
          | "sub_vec" | "sub_bits" | "sub_atom" ->
              ("operation", Some "-")
          | "mult_vec" | "mult_bits" | "mult_atom" ->
              ("operation", Some "*")

          (* Bitwise operations - normalize SAIL vector ops to standard operators *)
          | "and_vec" ->
              ("operation", Some "&")
          | "or_vec" ->
              ("operation", Some "|")
          | "xor_vec" ->
              ("operation", Some "^")
          | "not_vec" ->
              ("operation", Some "~")
          | "not_bool" | "not" ->
              ("operation", Some "!")

          (* Shift operations - normalize SAIL shift operators *)
          | "shift_bits_left" | "shiftl" ->
              ("operation", Some "<<")
          | "shift_bits_right" | "shiftr" ->
              ("operation", Some ">>")
          | "shift_bits_right_arith" ->
              ("operation", Some ">>>")

          (* Concatenation *)
          | "bitvector_concat" | "concat_vec" ->
              ("concat", Some "concat")

          (* Other vector operations - keep SAIL names *)
          | "vector_access" | "vector_update" ->
              ("operation", Some func_name)

          (* Subrange/slicing operations *)
          | "subrange" | "subrange_bits" | "subrange_vec" | "subrange_vec_dec"
          | "sail_truncate" | "sail_truncateLSB" ->
              ("bit_slice", Some func_name)

          (* Comparison operations *)
          | "eq_bit" | "neq_bit" | "eq_bits" | "neq_bits"
          | "lt_int" | "gt_int" | "lteq_int" | "gteq_int"
          | "lt" | "gt" | "lteq" | "gteq"
          | "lt_bits" | "gt_bits" | "lteq_bits" | "gteq_bits"
          | "_s" | "_u" ->
              ("comparison", Some func_name)

          (* Floating-point register read functions *)
          | "rF_or_X_S" | "rF_or_X_D" | "rF_or_X_H"
          | "F_S" | "F_D" | "F_H" | "rF_bits" ->
              ("fp_reg_read", Some func_name)

          (* Floating-point register write functions *)
          | "wF_or_X_S" | "wF_or_X_D" | "wF_or_X_H"
          | "wF_S" | "wF_D" | "wF_H" | "wF_bits" ->
              ("fp_reg_write", Some func_name)

          (* Floating-point negate: sign-bit flip, not an FP intrinsic *)
          | "negate_S" | "negate_D" | "negate_H" | "negate_BF16" ->
              ("fp_negate", Some "fp_negate")
          | "accrue_fflags" ->
              ("fp_fflags_update", Some func_name)
          | "select_instr_or_fcsr_rm" ->
              ("fp_rounding_mode", Some func_name)
          | "encdec_rounding_mode" | "encdec_rounding_mode_forwards"
          | "encdec_rounding_mode_backwards" ->
              (* Identity: SAIL rounding mode encoding matches IEEE 754, just passthrough *)
              ("identity", Some "encdec_rounding_mode")

          (* Floating-point classification *)
          | "float_classify" ->
              ("fp_operation", Some "fp_class")

          (* SAIL-defined FP comparison helpers - map to isacomp standard names *)
          | "fle_S" | "fle_D" | "fle_H" -> ("fp_operation", Some "fp_le")
          | "flt_S" | "flt_D" | "flt_H" -> ("fp_operation", Some "fp_lt")
          | "feq_quiet_S" | "feq_quiet_D" | "feq_quiet_H" -> ("fp_operation", Some "fp_eq")

          (* SAIL-defined FP NaN/zero classification helpers - bit-level ops, not FP intrinsics *)
          | "f_is_NaN_S" | "f_is_NaN_D" | "f_is_NaN_H" -> ("fp_bit_test", Some "fp_is_nan")
          | "f_is_SNaN_S" | "f_is_SNaN_D" | "f_is_SNaN_H" -> ("fp_bit_test", Some "fp_is_snan")
          | "f_is_QNaN_S" | "f_is_QNaN_D" | "f_is_QNaN_H" -> ("fp_bit_test", Some "fp_is_qnan")
          | "f_is_neg_zero_S" | "f_is_neg_zero_D" | "f_is_neg_zero_H" -> ("fp_bit_test", Some "fp_is_neg_zero")
          | "f_is_pos_zero_S" | "f_is_pos_zero_D" | "f_is_pos_zero_H" -> ("fp_bit_test", Some "fp_is_pos_zero")

          (* Canonical NaN constructors - just a constant, not an FP intrinsic *)
          | "canonical_NaN_S" | "canonical_NaN_D" | "canonical_NaN_H"
          | "canonical_NaN_BF16" | "canonical_NaN" ->
              ("fp_constant", Some "fp_canonical_nan")

          (* NaN boxing/unboxing *)
          | "nan_box" -> ("fp_operation", Some "fp_nan_box")
          | "nan_unbox" -> ("fp_operation", Some "fp_nan_unbox")

          (* FP structure split/make *)
          | "fsplit_S" | "fsplit_D" | "fsplit_H" -> ("fp_operation", Some "fp_split")
          | "fmake_S" | "fmake_D" | "fmake_H" -> ("operation", Some "bitvector_concat")
          | "float_is_snan" | "float_is_qnan" | "float_is_zero"
          | "float_is_subnormal" | "float_is_normal" | "float_is_inf"
          | "float_is_positive" | "float_is_negative" ->
              ("fp_operation", Some func_name)

          (* Register/memory read functions *)
          | "X" | "F" | "rX" | "rX_bits" | "read_register" ->
              ("array_access", None)

          (* Register/memory write functions - will be converted to array_write below *)
          | "wX" | "wX_bits" | "wGPR" | "write_register" ->
              ("register_write", Some func_name)

          (* Virtual memory operations - simplified to direct memory access *)
          | "vmem_read" | "vmem_write" ->
              ("vmem_operation", Some func_name)

          (* CSR operations - special-case to produce array read-modify-write *)
          | "doCSR" ->
              ("csr_operation", Some func_name)

          (* Memory operation helpers - skip these *)
          | "Read" | "Write" | "ReadWrite" | "Execute" ->
              ("memory_access_type", Some func_name)

          (* Data extension helpers *)
          | "extend_value" ->
              ("operation", Some func_name)

          (* PC access *)
          | "get_arch_pc" | "PC" | "get_PC" | "set_PC" ->
              ("isa_state", None)

          (* PC update functions - special handling to inline the PC update *)
          | "jump_to" | "branch_to" | "set_next_pc" ->
              ("pc_update", Some func_name)

          (* Match operation - treat as conditional *)
          | "match" ->
              ("conditional", Some func_name)

          (* Default: check for Berkeley softfloat intrinsic prefix, then fall through *)
          | _ ->
              let is_softfloat =
                String.length func_name > 6 && String.sub func_name 0 6 = "riscv_"
                && (func_name.[6] = 'f' || func_name.[6] = 'i' || func_name.[6] = 'u')
              in
              if is_softfloat then
                (* Berkeley softfloat intrinsic - classify by operation type *)
                (* Formats: riscv_f<prec><Op> (e.g. riscv_f32Add)
                            riscv_i<prec>ToF<prec> (e.g. riscv_i32ToF32)
                            riscv_ui<prec>ToF<prec> (e.g. riscv_ui64ToF32) *)
                let after_prefix = String.sub func_name 6 (String.length func_name - 6) in
                let normalized_op =
                  let len = String.length after_prefix in
                  (* Strip leading type char(s) and precision digits *)
                  let i = ref 0 in
                  (* Skip leading type indicator: f, i, ui *)
                  if !i < len && (after_prefix.[!i] = 'f' || after_prefix.[!i] = 'i' || after_prefix.[!i] = 'u') then begin
                    incr i;
                    if !i < len && after_prefix.[!i] = 'i' then incr i  (* 'ui' prefix *)
                  end;
                  (* Capture precision digits before skipping *)
                  let prec_start = !i in
                  while !i < len && after_prefix.[!i] >= '0' && after_prefix.[!i] <= '9' do incr i done;
                  let prec_str = String.sub after_prefix prec_start (!i - prec_start) in
                  let is_fp64 = (prec_str = "64") in
                  let d_suffix = if is_fp64 then "_d" else "" in
                  let op_name = if !i < len then
                    String.sub after_prefix !i (len - !i)
                  else after_prefix
                  in
                  (* Normalize to standard operation names *)
                  match String.lowercase_ascii op_name with
                  | "add" -> "fp_add" ^ d_suffix
                  | "sub" -> "fp_sub" ^ d_suffix
                  | "mul" -> "fp_mul" ^ d_suffix
                  | "div" -> "fp_div" ^ d_suffix
                  | "muladd" -> "fp_muladd" ^ d_suffix
                  | "sqrt" -> "fp_sqrt" ^ d_suffix
                  | "roundtoint" -> "fp_round" ^ d_suffix
                  | "eq" -> "fp_eq" ^ d_suffix
                  | "lt" | "lt_quiet" -> "fp_lt" ^ d_suffix
                  | "le" | "le_quiet" -> "fp_le" ^ d_suffix
                  | _ ->
                      (* Parse conversions from full after_prefix (e.g. "f32ToI32", "i32ToF32")
                         to produce specific names like fp_cvt_w_s, fp_cvt_s_w *)
                      let try_parse_conversion () =
                        (* Find "To" in after_prefix *)
                        let ap_len = String.length after_prefix in
                        let to_pos = ref (-1) in
                        for k = 0 to ap_len - 2 do
                          if !to_pos = -1 && after_prefix.[k] = 'T' && after_prefix.[k+1] = 'o' then
                            to_pos := k
                        done;
                        if !to_pos > 0 && !to_pos < ap_len - 2 then begin
                          let src_str = String.lowercase_ascii (String.sub after_prefix 0 !to_pos) in
                          let dst_str = String.lowercase_ascii (String.sub after_prefix (!to_pos + 2) (ap_len - !to_pos - 2)) in
                          (* Map type+precision to ISA type suffix *)
                          let type_of s =
                            if s = "f32" then Some "s"
                            else if s = "f64" then Some "d"
                            else if s = "f16" then Some "h"
                            else if String.length s >= 4 && String.sub s 0 2 = "ui" then
                              (match String.sub s 2 (String.length s - 2) with
                               | "32" -> Some "wu" | "64" -> Some "lu" | _ -> None)
                            else if String.length s >= 3 && s.[0] = 'i' then
                              (match String.sub s 1 (String.length s - 1) with
                               | "32" -> Some "w" | "64" -> Some "l" | _ -> None)
                            else None
                          in
                          (* For RV32 targets, 64-bit integer conversions (l/lu) are dead code
                             since xlen=32.  Map them to their 32-bit equivalents (w/wu) so
                             the Verilog generator doesn't attempt 64-bit FPU instantiation. *)
                          let clamp32 t = match t with
                            | "l" -> "w" | "lu" -> "wu" | other -> other in
                          match type_of src_str, type_of dst_str with
                          | Some src_t, Some dst_t ->
                              Some ("fp_cvt_" ^ clamp32 dst_t ^ "_" ^ clamp32 src_t)
                          | _ -> None
                        end else None
                      in
                      (match try_parse_conversion () with
                       | Some op -> op
                       | None -> "fp_" ^ String.lowercase_ascii op_name)
                in
                ("fp_operation", Some normalized_op)
              else
                ("operation", Some func_name)
        in
        Printf.printf "        DEBUG: E_app '%s' classified as type='%s'\n%!" func_name node_type;

        let display = match operator with
          | Some op -> Printf.sprintf "%s(%s)" op
                        (String.concat ", " (List.filter_map (fun n -> n.display_name) arg_nodes))
          | None -> func_name
        in

        (* Debug: Print classification before special handling *)
        Printf.printf "        DEBUG: func_name='%s', node_type='%s', operator='%s', args=%d\n%!"
          func_name node_type (Option.value ~default:"None" operator) (List.length arg_nodes);

        (* Special handling for register write functions - create array_write node *)
        Printf.printf "        *** CHECKING BRANCHES: func_name='%s', node_type='%s' ***\n%!" func_name node_type;
        if node_type = "register_write" then begin
          Printf.printf "        DEBUG: register_write detected for %s with %d args\n%!" func_name (List.length arg_nodes);
          (* wX(rd, value) or wX_bits(rd, value) - args are: index, value *)
          match arg_nodes with
          | [idx_node; value_node] ->
              Printf.printf "        DEBUG: Matched 2-arg pattern for register write\n%!";
              (* Find or create rf isa_state node *)
              let rf_node = match find_node builder "rf" with
                | Some node -> node
                | None ->
                    let dims = Some [(31, 0); (4, 0)] in
                    let node = make_node ~display_name:(Some "rf") ~is_arch_state:true
                                        ~bit_width:(Some 32) ~dimensions:dims "isa_state" in
                    add_node builder node
              in

              (* Create array_write node *)
              let write_name = Printf.sprintf "rf[%s]_wr"
                (Option.value ~default:"_" idx_node.display_name) in
              let write_node = make_node ~display_name:(Some write_name)
                                         ~operator
                                         "array_write" in
              let write_node = add_node builder write_node in

              (* Connect: rf -> array_write *)
              connect builder rf_node write_node "array_base";
              (* Connect: index -> array_write *)
              connect builder idx_node write_node "array_index";
              (* For wX_bits, add conditional write logic (x0 is hardwired to zero) *)
              let write_enable_id =
                if func_name = "wX_bits" || func_name = "wX" then begin
                  Printf.printf "        Adding conditional write for %s (rd != 0)\n%!" func_name;
                  (* Create zero literal *)
                  let zero_node = make_node ~display_name:(Some "0") ~value:(Some "0")
                                           ~bit_width:(Some 5) "literal" in
                  let zero_node = add_node builder zero_node in

                  (* Create comparison: rd != 0 *)
                  let cmp_display = Printf.sprintf "%s != 0"
                    (Option.value ~default:"rd" idx_node.display_name) in
                  let cmp_node = make_node ~display_name:(Some cmp_display)
                                          ~operator:(Some "!=") "comparison" in
                  let cmp_node = add_node builder cmp_node in

                  (* Connect: idx -> comparison, zero -> comparison *)
                  connect builder idx_node cmp_node "operand";
                  connect builder zero_node cmp_node "operand";

                  Printf.printf "        Added write_enable condition: %s\n%!" cmp_display;
                  Some cmp_node.id
                end else None
              in
              (* Connect: value -> array_write (with enable on assignment edge) *)
              connect ~enable:write_enable_id builder value_node write_node "assignment";

              Printf.printf "        Created array_write node for %s\n%!" func_name;
              write_node
          | _ ->
              Printf.eprintf "Warning: register write function %s has wrong number of args (%d)\n%!"
                            func_name (List.length arg_nodes);
              let func_node = make_node ~display_name:(Some display) ~operator node_type in
              add_node builder func_node
        end else if node_type = "vmem_operation" then begin
          (* Simplified memory operations: abstract away vmem_read/vmem_write *)
          Printf.printf "        *** BRANCH: vmem_operation ***\n%!";
          Printf.printf "        DEBUG: vmem_operation detected: %s with %d args\n%!" func_name (List.length arg_nodes);

          if func_name = "vmem_read" then begin
            (* vmem_read(rs1, offset, width, access_kind, aq, rl, res) *)
            (* Create memory read node matching ISA pattern:
               - Use byte address so Verilog generator handles scaling + byte selection
               - When memory_access_width is set, set access width accordingly
               - Verilog generator's narrow load detection handles byte-offset extraction *)
            Printf.printf "        DEBUG: vmem_read detected, memory_access_width=%s\n%!"
              (match builder.memory_access_width with Some w -> string_of_int w | None -> "none");
            match arg_nodes with
            | rs_idx_node :: offset_node :: _width_node :: _ ->
                (* Find or create rf node *)
                let rf_node = match find_node builder "rf" with
                  | Some node -> node
                  | None ->
                      let dims = Some [(31, 0); (4, 0)] in
                      let node = make_node ~display_name:(Some "rf") ~is_arch_state:true
                                          ~bit_width:(Some 32) ~dimensions:dims "isa_state" in
                      add_node builder node
                in

                (* Find or create dmem node — 64-bit doubleword-indexed for D extension support *)
                let dmem_node = match find_node builder "dmem" with
                  | Some node -> node
                  | None ->
                      let node = make_node ~display_name:(Some "dmem")
                                          ~bit_width:(Some 64)
                                          ~dimensions:(Some [(63, 0); (12, 0)])
                                          ~is_arch_state:true ~is_memory:true
                                          ~array_size:(Some 8192) "isa_state" in
                      add_node builder node
                in

                (* Step 1: Read register value: base_addr = rf[rs1] *)
                let rf_read_node = make_node
                  ~display_name:(Some (Printf.sprintf "rf[%s]"
                    (Option.value ~default:"rs1" rs_idx_node.display_name)))
                  ~operator:(Some "array_access")
                  ~bit_width:(Some 32)
                  "array_access" in
                let rf_read_node = add_node builder rf_read_node in
                connect builder rf_node rf_read_node "array_base";
                connect builder rs_idx_node rf_read_node "array_index";

                (* Step 2: Calculate byte address: addr = rf[rs1] + offset *)
                let addr_full_node = make_node
                  ~display_name:(Some (Printf.sprintf "rf[%s] + %s"
                    (Option.value ~default:"rs1" rs_idx_node.display_name)
                    (Option.value ~default:"offset" offset_node.display_name)))
                  ~operator:(Some "+")
                  ~bit_width:(Some 32)
                  "operation" in
                let addr_full_node = add_node builder addr_full_node in
                connect builder rf_read_node addr_full_node "operand";
                connect builder offset_node addr_full_node "operand";

                (* Step 3: Convert byte address to doubleword address (>> 3) for 64-bit dmem *)
                let word_addr_node = make_node
                  ~display_name:(Some "dword_addr")
                  ~operator:(Some ">>")
                  ~bit_width:(Some 32)
                  "operation" in
                let word_addr_node = add_node builder word_addr_node in
                let shift_const = make_node
                  ~display_name:(Some "3")
                  ~value:(Some "3")
                  ~bit_width:(Some 32)
                  "literal" in
                let shift_const = add_node builder shift_const in
                connect builder addr_full_node word_addr_node "operand";
                connect builder shift_const word_addr_node "operand";

                (* Step 4: Read memory at doubleword address — returns 64 bits *)
                let mem_read = make_node
                  ~display_name:(Some "dmem[addr]_rd")
                  ~operator:(Some "array_access")
                  ~bit_width:(Some 64)
                  "array_access" in
                let mem_read = add_node builder mem_read in
                connect builder dmem_node mem_read "array_base";
                connect builder word_addr_node mem_read "array_index";

                (* Step 5: Extract the relevant bytes from the 64-bit doubleword *)
                let result_node = match builder.memory_access_width with
                  | Some 1 ->
                      (* Byte load: extract byte at addr[2:0] within 64-bit doubleword *)
                      let byte_off = make_node
                        ~display_name:(Some "byte_offset")
                        ~operator:(Some "bit_slice")
                        ~bit_width:(Some 3)
                        ~bitslice:(Some (2, 0))
                        "bit_slice" in
                      let byte_off = add_node builder byte_off in
                      connect builder addr_full_node byte_off "bit_access";
                      (* Shift right by (byte_offset * 8) = byte_offset << 3 *)
                      let shift_amt = make_node
                        ~display_name:(Some "byte_shift")
                        ~operator:(Some "<<")
                        ~bit_width:(Some 6)
                        "operation" in
                      let shift_amt = add_node builder shift_amt in
                      let three_const = make_node
                        ~display_name:(Some "3")
                        ~value:(Some "3")
                        ~bit_width:(Some 6)
                        "literal" in
                      let three_const = add_node builder three_const in
                      connect builder byte_off shift_amt "operand";
                      connect builder three_const shift_amt "operand";
                      let shifted_word = make_node
                        ~display_name:(Some "shifted_dword")
                        ~operator:(Some ">>")
                        ~bit_width:(Some 64)
                        "operation" in
                      let shifted_word = add_node builder shifted_word in
                      connect builder mem_read shifted_word "operand";
                      connect builder shift_amt shifted_word "operand";
                      (* Truncate to 8 bits *)
                      let byte_val = make_node
                        ~display_name:(Some "byte_val")
                        ~operator:(Some "bit_slice")
                        ~bit_width:(Some 8)
                        ~bitslice:(Some (7, 0))
                        "bit_slice" in
                      let byte_val = add_node builder byte_val in
                      connect builder shifted_word byte_val "bit_access";
                      byte_val
                  | Some 2 ->
                      (* Half-word load: extract half at addr[2:1] within 64-bit doubleword *)
                      let half_off = make_node
                        ~display_name:(Some "half_offset")
                        ~operator:(Some "bit_slice")
                        ~bit_width:(Some 2)
                        ~bitslice:(Some (2, 1))
                        "bit_slice" in
                      let half_off = add_node builder half_off in
                      connect builder addr_full_node half_off "bit_access";
                      (* Shift right by (half_offset * 16) = half_offset << 4 *)
                      let shift_amt = make_node
                        ~display_name:(Some "half_shift")
                        ~operator:(Some "<<")
                        ~bit_width:(Some 6)
                        "operation" in
                      let shift_amt = add_node builder shift_amt in
                      let four_const = make_node
                        ~display_name:(Some "4")
                        ~value:(Some "4")
                        ~bit_width:(Some 6)
                        "literal" in
                      let four_const = add_node builder four_const in
                      connect builder half_off shift_amt "operand";
                      connect builder four_const shift_amt "operand";
                      let shifted_word = make_node
                        ~display_name:(Some "shifted_dword")
                        ~operator:(Some ">>")
                        ~bit_width:(Some 64)
                        "operation" in
                      let shifted_word = add_node builder shifted_word in
                      connect builder mem_read shifted_word "operand";
                      connect builder shift_amt shifted_word "operand";
                      (* Truncate to 16 bits *)
                      let half_val = make_node
                        ~display_name:(Some "half_val")
                        ~operator:(Some "bit_slice")
                        ~bit_width:(Some 16)
                        ~bitslice:(Some (15, 0))
                        "bit_slice" in
                      let half_val = add_node builder half_val in
                      connect builder shifted_word half_val "bit_access";
                      half_val
                  | Some 4 | None ->
                      (* Word load: extract 32 bits at addr[2] within 64-bit doubleword *)
                      let word_off = make_node
                        ~display_name:(Some "word_offset")
                        ~operator:(Some "bit_slice")
                        ~bit_width:(Some 1)
                        ~bitslice:(Some (2, 2))
                        "bit_slice" in
                      let word_off = add_node builder word_off in
                      connect builder addr_full_node word_off "bit_access";
                      (* Shift right by (word_offset * 32) = word_offset << 5 *)
                      let shift_amt = make_node
                        ~display_name:(Some "word_shift")
                        ~operator:(Some "<<")
                        ~bit_width:(Some 6)
                        "operation" in
                      let shift_amt = add_node builder shift_amt in
                      let five_const = make_node
                        ~display_name:(Some "5")
                        ~value:(Some "5")
                        ~bit_width:(Some 6)
                        "literal" in
                      let five_const = add_node builder five_const in
                      connect builder word_off shift_amt "operand";
                      connect builder five_const shift_amt "operand";
                      let shifted_dword = make_node
                        ~display_name:(Some "shifted_dword")
                        ~operator:(Some ">>")
                        ~bit_width:(Some 64)
                        "operation" in
                      let shifted_dword = add_node builder shifted_dword in
                      connect builder mem_read shifted_dword "operand";
                      connect builder shift_amt shifted_dword "operand";
                      (* Truncate to 32 bits *)
                      let word_val = make_node
                        ~display_name:(Some "word_val")
                        ~operator:(Some "bit_slice")
                        ~bit_width:(Some 32)
                        ~bitslice:(Some (31, 0))
                        "bit_slice" in
                      let word_val = add_node builder word_val in
                      connect builder shifted_dword word_val "bit_access";
                      word_val
                  | Some 8 ->
                      (* Double-word load: return full 64-bit value *)
                      mem_read
                  | _ ->
                      (* Unknown width: return full 64-bit value *)
                      mem_read
                in

                (* Sign/zero extend sub-word loads to 32 bits *)
                let extended_node = match builder.memory_access_width with
                  | Some 1 ->
                      if builder.memory_is_unsigned then begin
                        (* LBU: zero-extend byte to 32 bits *)
                        let zext = make_node ~display_name:(Some "zext_byte")
                          ~operator:(Some "zero_extend") ~bit_width:(Some 32)
                          "zero_extend" in
                        let zext = add_node builder zext in
                        connect builder result_node zext "operand";
                        zext
                      end else begin
                        (* LB: sign-extend byte to 32 bits *)
                        let sext = make_node ~display_name:(Some "sext_byte")
                          ~operator:(Some "sign_extend") ~bit_width:(Some 32)
                          "sign_extend" in
                        let sext = add_node builder sext in
                        connect builder result_node sext "operand";
                        sext
                      end
                  | Some 2 ->
                      if builder.memory_is_unsigned then begin
                        (* LHU: zero-extend half to 32 bits *)
                        let zext = make_node ~display_name:(Some "zext_half")
                          ~operator:(Some "zero_extend") ~bit_width:(Some 32)
                          "zero_extend" in
                        let zext = add_node builder zext in
                        connect builder result_node zext "operand";
                        zext
                      end else begin
                        (* LH: sign-extend half to 32 bits *)
                        let sext = make_node ~display_name:(Some "sext_half")
                          ~operator:(Some "sign_extend") ~bit_width:(Some 32)
                          "sign_extend" in
                        let sext = add_node builder sext in
                        connect builder result_node sext "operand";
                        sext
                      end
                  | _ -> result_node
                in

                Printf.printf "        Created memory read with doubleword addressing (%s access, %s)\n%!"
                  (match builder.memory_access_width with
                   | Some 1 -> "byte" | Some 2 -> "half" | Some 8 -> "double" | _ -> "word")
                  (if builder.memory_is_unsigned then "unsigned" else "signed");
                extended_node
            | _ ->
                Printf.eprintf "Warning: vmem_read has unexpected args (%d)\n%!" (List.length arg_nodes);
                let func_node = make_node ~display_name:(Some display) ~operator node_type in
                add_node builder func_node
          end else begin
            (* vmem_write(rs_idx, offset, width, data, ...) *)
            (* Create memory write node matching ISA pattern:
               - Use byte address (not word-truncated) so Verilog generator handles scaling
               - When memory_access_width is set, slice data to correct width
               - Set is_write=true so merger creates proper memory_write_port *)
            Printf.printf "        DEBUG: vmem_write detected with %d args, memory_access_width=%s\n%!"
              (List.length arg_nodes)
              (match builder.memory_access_width with Some w -> string_of_int w | None -> "none");

            match arg_nodes with
            | rs_idx_node :: offset_node :: _width_node :: data_node :: _ ->
                (* Find or create rf node *)
                let rf_node = match find_node builder "rf" with
                  | Some node -> node
                  | None ->
                      let dims = Some [(31, 0); (4, 0)] in
                      let node = make_node ~display_name:(Some "rf") ~is_arch_state:true
                                          ~bit_width:(Some 32) ~dimensions:dims "isa_state" in
                      add_node builder node
                in

                (* Find or create dmem node — 64-bit doubleword-indexed for D extension support *)
                let dmem_node = match find_node builder "dmem" with
                  | Some node -> node
                  | None ->
                      let node = make_node ~display_name:(Some "dmem")
                                          ~bit_width:(Some 64)
                                          ~dimensions:(Some [(63, 0); (12, 0)])
                                          ~is_arch_state:true ~is_memory:true
                                          ~array_size:(Some 8192) "isa_state" in
                      add_node builder node
                in

                (* Step 1: Read register value: base_addr = rf[rs1] *)
                let rf_read_node = make_node
                  ~display_name:(Some (Printf.sprintf "rf[%s]"
                    (Option.value ~default:"rs1" rs_idx_node.display_name)))
                  ~operator:(Some "array_access")
                  ~bit_width:(Some 32)
                  "array_access" in
                let rf_read_node = add_node builder rf_read_node in
                connect builder rf_node rf_read_node "array_base";
                connect builder rs_idx_node rf_read_node "array_index";

                (* Step 2: Calculate byte address: addr = rf[rs1] + offset *)
                let addr_full_node = make_node
                  ~display_name:(Some (Printf.sprintf "rf[%s] + %s"
                    (Option.value ~default:"rs1" rs_idx_node.display_name)
                    (Option.value ~default:"offset" offset_node.display_name)))
                  ~operator:(Some "+")
                  ~bit_width:(Some 32)
                  "operation" in
                let addr_full_node = add_node builder addr_full_node in
                connect builder rf_read_node addr_full_node "operand";
                connect builder offset_node addr_full_node "operand";

                (* Step 3: Convert byte address to doubleword address (>> 3) for 64-bit dmem *)
                let word_addr_node = make_node
                  ~display_name:(Some "dword_addr")
                  ~operator:(Some ">>")
                  ~bit_width:(Some 32)
                  "operation" in
                let word_addr_node = add_node builder word_addr_node in
                let shift_const = make_node
                  ~display_name:(Some "3")
                  ~value:(Some "3")
                  ~bit_width:(Some 32)
                  "literal" in
                let shift_const = add_node builder shift_const in
                connect builder addr_full_node word_addr_node "operand";
                connect builder shift_const word_addr_node "operand";

                (* Determine write data based on memory_access_width.
                   For sub-word stores, we do read-modify-write:
                   1. Read current word from dmem[word_addr]
                   2. Compute byte offset from byte address
                   3. Shift store data to correct byte lane
                   4. Mask and merge with current word
                   5. Write merged word back *)
                let write_data_node = match builder.memory_access_width with
                  | Some 1 ->  (* BYTE store: read-modify-write on 64-bit doubleword *)
                      Printf.printf "        Creating BYTE store read-modify-write logic (64-bit)\n%!";
                      (* Read current doubleword *)
                      let cur_word = make_node ~display_name:(Some "dmem_cur_dword")
                        ~operator:(Some "array_access") ~bit_width:(Some 64)
                        "array_access" in
                      let cur_word = add_node builder cur_word in
                      connect builder dmem_node cur_word "array_base";
                      connect builder word_addr_node cur_word "array_index";
                      (* byte_off = addr[2:0] *)
                      let byte_off = make_node ~display_name:(Some "byte_off")
                        ~operator:(Some "bit_slice") ~bit_width:(Some 3)
                        ~bitslice:(Some (2, 0)) "bit_slice" in
                      let byte_off = add_node builder byte_off in
                      connect builder addr_full_node byte_off "bit_access";
                      (* shift_amt = byte_off * 8 *)
                      let eight = make_node ~display_name:(Some "8") ~value:(Some "8")
                        ~bit_width:(Some 64) "literal" in
                      let eight = add_node builder eight in
                      let shift_amt = make_node ~display_name:(Some "byte_shift")
                        ~operator:(Some "*") ~bit_width:(Some 64) "operation" in
                      let shift_amt = add_node builder shift_amt in
                      connect builder byte_off shift_amt "operand";
                      connect builder eight shift_amt "operand";
                      (* byte_mask = 0xFF << shift_amt *)
                      let mask_const = make_node ~display_name:(Some "0xFF")
                        ~value:(Some "255") ~bit_width:(Some 64) "literal" in
                      let mask_const = add_node builder mask_const in
                      let byte_mask = make_node ~display_name:(Some "byte_mask")
                        ~operator:(Some "<<") ~bit_width:(Some 64) "operation" in
                      let byte_mask = add_node builder byte_mask in
                      connect ~position:(Some "0") builder mask_const byte_mask "operand";
                      connect ~position:(Some "1") builder shift_amt byte_mask "operand";
                      (* inv_mask = ~byte_mask *)
                      let inv_mask = make_node ~display_name:(Some "inv_byte_mask")
                        ~operator:(Some "~") ~bit_width:(Some 64) "operation" in
                      let inv_mask = add_node builder inv_mask in
                      connect builder byte_mask inv_mask "operand";
                      (* cleared = cur_dword & inv_mask *)
                      let cleared = make_node ~display_name:(Some "cleared_byte")
                        ~operator:(Some "&") ~bit_width:(Some 64) "operation" in
                      let cleared = add_node builder cleared in
                      connect builder cur_word cleared "operand";
                      connect builder inv_mask cleared "operand";
                      (* data_byte = data[7:0] zero-extended to 64 *)
                      let data_byte = make_node ~display_name:(Some "store_byte")
                        ~operator:(Some "bit_slice") ~bit_width:(Some 8)
                        ~bitslice:(Some (7, 0)) "bit_slice" in
                      let data_byte = add_node builder data_byte in
                      connect builder data_node data_byte "bit_access";
                      let data_zext = make_node ~display_name:(Some "store_byte_zext")
                        ~operator:(Some "zero_extend") ~bit_width:(Some 64)
                        "zero_extend" in
                      let data_zext = add_node builder data_zext in
                      connect builder data_byte data_zext "operand";
                      (* shifted_data = data_zext << shift_amt *)
                      let shifted = make_node ~display_name:(Some "shifted_byte")
                        ~operator:(Some "<<") ~bit_width:(Some 64) "operation" in
                      let shifted = add_node builder shifted in
                      connect ~position:(Some "0") builder data_zext shifted "operand";
                      connect ~position:(Some "1") builder shift_amt shifted "operand";
                      (* merged = cleared | shifted_data *)
                      let merged = make_node ~display_name:(Some "merged_byte_dword")
                        ~operator:(Some "|") ~bit_width:(Some 64) "operation" in
                      let merged = add_node builder merged in
                      connect builder cleared merged "operand";
                      connect builder shifted merged "operand";
                      merged
                  | Some 2 ->  (* HALF store: read-modify-write on 64-bit doubleword *)
                      Printf.printf "        Creating HALF store read-modify-write logic (64-bit)\n%!";
                      (* Read current doubleword *)
                      let cur_word = make_node ~display_name:(Some "dmem_cur_dword")
                        ~operator:(Some "array_access") ~bit_width:(Some 64)
                        "array_access" in
                      let cur_word = add_node builder cur_word in
                      connect builder dmem_node cur_word "array_base";
                      connect builder word_addr_node cur_word "array_index";
                      (* half_off = addr[2:1] (0-3) *)
                      let half_off = make_node ~display_name:(Some "half_off")
                        ~operator:(Some "bit_slice") ~bit_width:(Some 2)
                        ~bitslice:(Some (2, 1)) "bit_slice" in
                      let half_off = add_node builder half_off in
                      connect builder addr_full_node half_off "bit_access";
                      (* shift_amt = half_off * 16 *)
                      let sixteen = make_node ~display_name:(Some "16") ~value:(Some "16")
                        ~bit_width:(Some 64) "literal" in
                      let sixteen = add_node builder sixteen in
                      let shift_amt = make_node ~display_name:(Some "half_shift")
                        ~operator:(Some "*") ~bit_width:(Some 64) "operation" in
                      let shift_amt = add_node builder shift_amt in
                      connect builder half_off shift_amt "operand";
                      connect builder sixteen shift_amt "operand";
                      (* half_mask = 0xFFFF << shift_amt *)
                      let mask_const = make_node ~display_name:(Some "0xFFFF")
                        ~value:(Some "65535") ~bit_width:(Some 64) "literal" in
                      let mask_const = add_node builder mask_const in
                      let half_mask = make_node ~display_name:(Some "half_mask")
                        ~operator:(Some "<<") ~bit_width:(Some 64) "operation" in
                      let half_mask = add_node builder half_mask in
                      connect ~position:(Some "0") builder mask_const half_mask "operand";
                      connect ~position:(Some "1") builder shift_amt half_mask "operand";
                      (* inv_mask = ~half_mask *)
                      let inv_mask = make_node ~display_name:(Some "inv_half_mask")
                        ~operator:(Some "~") ~bit_width:(Some 64) "operation" in
                      let inv_mask = add_node builder inv_mask in
                      connect builder half_mask inv_mask "operand";
                      (* cleared = cur_dword & inv_mask *)
                      let cleared = make_node ~display_name:(Some "cleared_half")
                        ~operator:(Some "&") ~bit_width:(Some 64) "operation" in
                      let cleared = add_node builder cleared in
                      connect builder cur_word cleared "operand";
                      connect builder inv_mask cleared "operand";
                      (* data_half = data[15:0] zero-extended to 64 *)
                      let data_half = make_node ~display_name:(Some "store_half")
                        ~operator:(Some "bit_slice") ~bit_width:(Some 16)
                        ~bitslice:(Some (15, 0)) "bit_slice" in
                      let data_half = add_node builder data_half in
                      connect builder data_node data_half "bit_access";
                      let data_zext = make_node ~display_name:(Some "store_half_zext")
                        ~operator:(Some "zero_extend") ~bit_width:(Some 64)
                        "zero_extend" in
                      let data_zext = add_node builder data_zext in
                      connect builder data_half data_zext "operand";
                      (* shifted_data = data_zext << shift_amt *)
                      let shifted = make_node ~display_name:(Some "shifted_half")
                        ~operator:(Some "<<") ~bit_width:(Some 64) "operation" in
                      let shifted = add_node builder shifted in
                      connect ~position:(Some "0") builder data_zext shifted "operand";
                      connect ~position:(Some "1") builder shift_amt shifted "operand";
                      (* merged = cleared | shifted_data *)
                      let merged = make_node ~display_name:(Some "merged_half_dword")
                        ~operator:(Some "|") ~bit_width:(Some 64) "operation" in
                      let merged = add_node builder merged in
                      connect builder cleared merged "operand";
                      connect builder shifted merged "operand";
                      merged
                  | Some 4 | None ->  (* WORD store: read-modify-write on 64-bit doubleword *)
                      Printf.printf "        Creating WORD store read-modify-write logic (64-bit)\n%!";
                      (* Read current doubleword *)
                      let cur_dword = make_node ~display_name:(Some "dmem_cur_dword")
                        ~operator:(Some "array_access") ~bit_width:(Some 64)
                        "array_access" in
                      let cur_dword = add_node builder cur_dword in
                      connect builder dmem_node cur_dword "array_base";
                      connect builder word_addr_node cur_dword "array_index";
                      (* word_off = addr[2] (0 or 1) *)
                      let word_off = make_node ~display_name:(Some "word_off")
                        ~operator:(Some "bit_slice") ~bit_width:(Some 1)
                        ~bitslice:(Some (2, 2)) "bit_slice" in
                      let word_off = add_node builder word_off in
                      connect builder addr_full_node word_off "bit_access";
                      (* shift_amt = word_off * 32 *)
                      let thirtytwo = make_node ~display_name:(Some "32") ~value:(Some "32")
                        ~bit_width:(Some 64) "literal" in
                      let thirtytwo = add_node builder thirtytwo in
                      let shift_amt = make_node ~display_name:(Some "word_shift")
                        ~operator:(Some "*") ~bit_width:(Some 64) "operation" in
                      let shift_amt = add_node builder shift_amt in
                      connect builder word_off shift_amt "operand";
                      connect builder thirtytwo shift_amt "operand";
                      (* word_mask = 0xFFFFFFFF << shift_amt *)
                      let mask_const = make_node ~display_name:(Some "0xFFFFFFFF")
                        ~value:(Some "4294967295") ~bit_width:(Some 64) "literal" in
                      let mask_const = add_node builder mask_const in
                      let word_mask = make_node ~display_name:(Some "word_mask")
                        ~operator:(Some "<<") ~bit_width:(Some 64) "operation" in
                      let word_mask = add_node builder word_mask in
                      connect ~position:(Some "0") builder mask_const word_mask "operand";
                      connect ~position:(Some "1") builder shift_amt word_mask "operand";
                      (* inv_mask = ~word_mask *)
                      let inv_mask = make_node ~display_name:(Some "inv_word_mask")
                        ~operator:(Some "~") ~bit_width:(Some 64) "operation" in
                      let inv_mask = add_node builder inv_mask in
                      connect builder word_mask inv_mask "operand";
                      (* cleared = cur_dword & inv_mask *)
                      let cleared = make_node ~display_name:(Some "cleared_word")
                        ~operator:(Some "&") ~bit_width:(Some 64) "operation" in
                      let cleared = add_node builder cleared in
                      connect builder cur_dword cleared "operand";
                      connect builder inv_mask cleared "operand";
                      (* data_word = data[31:0] zero-extended to 64 *)
                      let data_zext = make_node ~display_name:(Some "store_word_zext")
                        ~operator:(Some "zero_extend") ~bit_width:(Some 64)
                        "zero_extend" in
                      let data_zext = add_node builder data_zext in
                      connect builder data_node data_zext "operand";
                      (* shifted_data = data_zext << shift_amt *)
                      let shifted = make_node ~display_name:(Some "shifted_word")
                        ~operator:(Some "<<") ~bit_width:(Some 64) "operation" in
                      let shifted = add_node builder shifted in
                      connect ~position:(Some "0") builder data_zext shifted "operand";
                      connect ~position:(Some "1") builder shift_amt shifted "operand";
                      (* merged = cleared | shifted_data *)
                      let merged = make_node ~display_name:(Some "merged_word_dword")
                        ~operator:(Some "|") ~bit_width:(Some 64) "operation" in
                      let merged = add_node builder merged in
                      connect builder cleared merged "operand";
                      connect builder shifted merged "operand";
                      merged
                  | Some 8 ->  (* DOUBLE store: full 64-bit write *)
                      Printf.printf "        Creating DOUBLE store (64-bit direct write)\n%!";
                      data_node
                  | Some w ->
                      Printf.printf "        Warning: unexpected memory_access_width=%d\n%!" w;
                      data_node
                in

                (* Step 4: Write memory using doubleword address — always 64-bit *)
                let write_node = make_node
                  ~display_name:(Some "dmem[addr]_wr")
                  ~operator:(Some "array_write")
                  ~bit_width:(Some 64)
                  "array_access" in  (* Use array_access type, matching ISA convention *)
                let write_node = add_node builder write_node in

                (* Connect: dmem -> write node (array_base) *)
                connect builder dmem_node write_node "array_base";
                (* Connect: doubleword address -> write node (array_index) *)
                connect builder word_addr_node write_node "array_index";
                (* Connect: data -> write node (assignment) *)
                connect builder write_data_node write_node "assignment";
                Printf.printf "        Created memory write: dmem[dword_addr] = data (64-bit)\n%!";
                write_node
            | _ ->
                Printf.eprintf "Warning: vmem_write has unexpected args (%d)\n%!" (List.length arg_nodes);
                let func_node = make_node ~display_name:(Some display) ~operator node_type in
                add_node builder func_node
          end
        end else if func_name = "subrange_bits" && List.length arg_nodes = 3 then begin
          (* subrange_bits(source, upper, lower) - extract bits [upper:lower] from source *)
          Printf.printf "        *** CHECKING: subrange_bits with 3 args ***\n%!";
          let source_data = List.nth arg_nodes 0 in
          let upper_bound = List.nth arg_nodes 1 in
          let lower_bound = List.nth arg_nodes 2 in

          Printf.printf "          source: %s (op: %s)\n%!"
            source_data.id (Option.value ~default:"none" source_data.operator);
          Printf.printf "          upper: %s (op: %s)\n%!"
            upper_bound.id (Option.value ~default:"none" upper_bound.operator);
          Printf.printf "          lower: %s (op: %s)\n%!"
            lower_bound.id (Option.value ~default:"none" lower_bound.operator);

          (* First, try to resolve both bounds to constant integers *)
          let upper_val = try_resolve_constant builder upper_bound in
          let lower_val = try_resolve_constant builder lower_bound in

          match upper_val, lower_val with
          | Some hi, Some lo ->
            (* Both bounds are constant - create a proper bit_slice *)
            Printf.printf "        Resolved subrange_bits to constant range [%d:%d]\n%!" hi lo;
            let width = hi - lo + 1 in
            let slice_node = make_node
              ~display_name:(Some (Printf.sprintf "%s[%d:%d]"
                (Option.value ~default:"data" source_data.display_name) hi lo))
              ~operator:(Some "bit_slice")
              ~bit_width:(Some width)
              ~bitslice:(Some (hi, lo))
              "bit_slice" in
            let slice_node = add_node builder slice_node in
            connect builder source_data slice_node "bit_access";
            slice_node
          | _ ->

          (* Could not resolve bounds to constants - fall through to dynamic handling *)

          (* Check if upper bound involves arithmetic (indicates dynamic width) *)
          let is_dynamic_width = match upper_bound.operator with
            | Some "-" | Some "*" | Some "+" -> true
            | _ -> false
          in

          if is_dynamic_width then begin
            Printf.printf "        *** BRANCH: subrange_bits with DYNAMIC WIDTH for STORE! ***\n%!";

            (* Find the width field by tracing back through the arithmetic *)
            (* upper_bound should be "width * 8 - 1", so find the width node *)
            let width_field_opt = List.find_opt (fun e ->
              e.target = upper_bound.id &&
              (match List.find_opt (fun (n : rg_node) -> n.id = e.source) builder.nodes with
               | Some n -> n.operator = Some "*"
               | None -> false)
            ) builder.edges in

            let width_node = match width_field_opt with
              | Some edge ->
                  (* Found the multiply node, now find its width input *)
                  let mult_node_id = edge.source in
                  let width_edge_opt = List.find_opt (fun e ->
                    e.target = mult_node_id &&
                    (match List.find_opt (fun (n : rg_node) -> n.id = e.source) builder.nodes with
                     | Some n -> n.operator = Some "bit_slice" &&
                                 (match n.display_name with
                                  | Some name -> String.contains name 'w' || name = "width"
                                  | None -> false)
                     | None -> false)
                  ) builder.edges in
                  (match width_edge_opt with
                   | Some e -> List.find_opt (fun (n : rg_node) -> n.id = e.source) builder.nodes
                   | None -> None)
              | None -> None
            in

            match width_node with
            | Some width_n ->
                Printf.printf "        Found width field: %s\n%!" width_n.id;

                (* Create explicit byte/half/word slices from source data *)
                let byte_slice = make_node
                  ~display_name:(Some (Printf.sprintf "%s[7:0]"
                    (Option.value ~default:"data" source_data.display_name)))
                  ~operator:(Some "bit_slice")
                  ~bit_width:(Some 8)
                  ~bitslice:(Some (7, 0))
                  "bit_slice" in
                let byte_slice = add_node builder byte_slice in
                connect builder source_data byte_slice "bit_access";

                let half_slice = make_node
                  ~display_name:(Some (Printf.sprintf "%s[15:0]"
                    (Option.value ~default:"data" source_data.display_name)))
                  ~operator:(Some "bit_slice")
                  ~bit_width:(Some 16)
                  ~bitslice:(Some (15, 0))
                  "bit_slice" in
                let half_slice = add_node builder half_slice in
                connect builder source_data half_slice "bit_access";

                let word_slice = make_node
                  ~display_name:(Some (Printf.sprintf "%s[31:0]"
                    (Option.value ~default:"data" source_data.display_name)))
                  ~operator:(Some "bit_slice")
                  ~bit_width:(Some 32)
                  ~bitslice:(Some (31, 0))
                  "bit_slice" in
                let word_slice = add_node builder word_slice in
                connect builder source_data word_slice "bit_access";

                (* Create width-aware conditional selection *)
                (* width encoding: 0=byte, 1=half, 2=word *)

                (* Inner conditional: width == 1 ? half : byte *)
                let lit_1 = make_node
                  ~display_name:(Some "1")
                  ~value:(Some "1")
                  ~bit_width:(Some 2)
                  "literal" in
                let lit_1 = add_node builder lit_1 in

                let cmp_is_half = make_node
                  ~display_name:(Some "width == 1")
                  ~operator:(Some "==")
                  "comparison" in
                let cmp_is_half = add_node builder cmp_is_half in
                connect builder width_n cmp_is_half "operand";
                connect builder lit_1 cmp_is_half "operand";

                let inner_cond = make_node
                  ~display_name:(Some "width==1 ? half : byte")
                  ~operator:(Some "conditional")
                  ~bit_width:(Some 16)  (* Max of byte(8) and half(16) *)
                  "conditional" in
                let inner_cond = add_node builder inner_cond in
                connect builder cmp_is_half inner_cond "ternary_condition";
                connect builder half_slice inner_cond "ternary_true";
                connect builder byte_slice inner_cond "ternary_false";

                (* Outer conditional: width == 2 ? word : (inner) *)
                let lit_2 = make_node
                  ~display_name:(Some "2")
                  ~value:(Some "2")
                  ~bit_width:(Some 2)
                  "literal" in
                let lit_2 = add_node builder lit_2 in

                let cmp_is_word = make_node
                  ~display_name:(Some "width == 2")
                  ~operator:(Some "==")
                  "comparison" in
                let cmp_is_word = add_node builder cmp_is_word in
                connect builder width_n cmp_is_word "operand";
                connect builder lit_2 cmp_is_word "operand";

                let outer_cond = make_node
                  ~display_name:(Some "width==2 ? word : (half|byte)")
                  ~operator:(Some "conditional")
                  ~bit_width:(Some 32)
                  "conditional" in
                let outer_cond = add_node builder outer_cond in
                connect builder cmp_is_word outer_cond "ternary_condition";
                connect builder word_slice outer_cond "ternary_true";
                connect builder inner_cond outer_cond "ternary_false";

                Printf.printf "        Created width-aware STORE data selection\n%!";
                outer_cond

            | None ->
                Printf.printf "        Warning: Could not find width field, falling back to normal bit_slice\n%!";
                let func_node = make_node ~display_name:(Some display) ~operator node_type in
                let func_node = add_node builder func_node in
                List.iter (fun arg_node -> connect builder arg_node func_node "operand") arg_nodes;
                func_node
          end else begin
            (* Not dynamic width, normal bit_slice *)
            Printf.printf "        Normal (non-dynamic) subrange_bits\n%!";
            let func_node = make_node ~display_name:(Some display) ~operator node_type in
            let func_node = add_node builder func_node in
            List.iter (fun arg_node -> connect builder arg_node func_node "operand") arg_nodes;
            func_node
          end
        end else if func_name = "extend_value" then begin
          (* extend_value(is_unsigned, data) - conditional sign/zero extend to 32 bits *)
          Printf.printf "        *** BRANCH: extend_value (HANDLER INVOKED!) ***\n%!";
          Printf.printf "        *** EXTEND_VALUE HANDLER: func_name=%s, args=%d ***\n%!" func_name (List.length arg_nodes);
          List.iteri (fun i arg ->
            Printf.printf "          Arg %d: display_name=%s, operator=%s, type=%s\n%!"
              i
              (Option.value ~default:"None" arg.display_name)
              (Option.value ~default:"None" arg.operator)
              arg.node_type
          ) arg_nodes;

          match arg_nodes with
          | is_unsigned_node :: data_node :: _ ->
              Printf.printf "        *** Matched 2+ arg pattern! ***\n%!";

              (* Check if data_node gets its value from a width_select node *)
              (* Find incoming "definition" edge to data_node *)
              let width_select_opt = List.find_opt (fun e ->
                e.target = data_node.id && e.edge_type = "definition"
              ) builder.edges in

              let source_node_opt = match width_select_opt with
                | Some edge ->
                    List.find_opt (fun (n : rg_node) -> n.id = edge.source) builder.nodes
                | None -> None
              in

              let is_width_select = match source_node_opt with
                | Some node -> node.operator = Some "width_select"
                | None -> false
              in

              Printf.printf "        data_node: %s, operator: %s, is_width_select: %b\n%!"
                data_node.id
                (match data_node.operator with Some op -> op | None -> "none")
                is_width_select;

              (* Check if data_node is fed by the special width_select node from vmem_read *)
              if is_width_select then begin
                let width_select_node = Option.get source_node_opt in
                Printf.printf "        Found width_select node: %s\n%!" width_select_node.id;
                Printf.printf "        Detected width_select node - creating width-aware extensions\n%!";

                (* Find the byte, half, word, and width_field inputs to width_select *)
                (* Edges go FROM source nodes TO width_select, so check target = width_select_node.id *)
                let byte_opt = List.find_opt (fun e -> e.target = width_select_node.id && e.edge_type = "byte_option") builder.edges in
                let half_opt = List.find_opt (fun e -> e.target = width_select_node.id && e.edge_type = "half_option") builder.edges in
                let word_opt = List.find_opt (fun e -> e.target = width_select_node.id && e.edge_type = "word_option") builder.edges in
                let width_field = List.find_opt (fun e -> e.target = width_select_node.id && e.edge_type = "width_field") builder.edges in

                match (byte_opt, half_opt, word_opt, width_field) with
                | (Some byte_edge, Some half_edge, Some word_edge, Some width_edge) ->
                    (* Edge target is width_select, so source is the input node we want *)
                    let byte_node = List.find_opt (fun (n : rg_node) -> n.id = byte_edge.source) builder.nodes |> Option.get in
                    let half_node = List.find_opt (fun (n : rg_node) -> n.id = half_edge.source) builder.nodes |> Option.get in
                    let word_node = List.find_opt (fun (n : rg_node) -> n.id = word_edge.source) builder.nodes |> Option.get in
                    let width_node = List.find_opt (fun (n : rg_node) -> n.id = width_edge.source) builder.nodes |> Option.get in

                    (* Check if is_unsigned is a runtime variable (bit_slice) or compile-time constant *)
                    let is_runtime_unsigned = match is_unsigned_node.operator with
                      | Some "bit_slice" -> true
                      | _ -> false
                    in

                    let byte_extended, half_extended =
                      if is_runtime_unsigned then begin
                        (* Create both sign and zero extensions, then conditional select *)
                        let byte_sign_ext = make_node
                          ~display_name:(Some "sign_extend_byte(8->32)")
                          ~operator:(Some "sign_extend")
                          ~bit_width:(Some 32)
                          "sign_extend" in
                        let byte_sign_ext = add_node builder byte_sign_ext in
                        connect builder byte_node byte_sign_ext "operand";

                        let byte_zero_ext = make_node
                          ~display_name:(Some "zero_extend_byte(8->32)")
                          ~operator:(Some "zero_extend")
                          ~bit_width:(Some 32)
                          "zero_extend" in
                        let byte_zero_ext = add_node builder byte_zero_ext in
                        connect builder byte_node byte_zero_ext "operand";

                        let byte_ext_cond = make_node
                          ~display_name:(Some "byte_extend_select")
                          ~operator:(Some "conditional")
                          ~bit_width:(Some 32)
                          "conditional" in
                        let byte_ext_cond = add_node builder byte_ext_cond in
                        connect builder is_unsigned_node byte_ext_cond "ternary_condition";
                        connect builder byte_zero_ext byte_ext_cond "ternary_true";
                        connect builder byte_sign_ext byte_ext_cond "ternary_false";

                        let half_sign_ext = make_node
                          ~display_name:(Some "sign_extend_half(16->32)")
                          ~operator:(Some "sign_extend")
                          ~bit_width:(Some 32)
                          "sign_extend" in
                        let half_sign_ext = add_node builder half_sign_ext in
                        connect builder half_node half_sign_ext "operand";

                        let half_zero_ext = make_node
                          ~display_name:(Some "zero_extend_half(16->32)")
                          ~operator:(Some "zero_extend")
                          ~bit_width:(Some 32)
                          "zero_extend" in
                        let half_zero_ext = add_node builder half_zero_ext in
                        connect builder half_node half_zero_ext "operand";

                        let half_ext_cond = make_node
                          ~display_name:(Some "half_extend_select")
                          ~operator:(Some "conditional")
                          ~bit_width:(Some 32)
                          "conditional" in
                        let half_ext_cond = add_node builder half_ext_cond in
                        connect builder is_unsigned_node half_ext_cond "ternary_condition";
                        connect builder half_zero_ext half_ext_cond "ternary_true";
                        connect builder half_sign_ext half_ext_cond "ternary_false";

                        (byte_ext_cond, half_ext_cond)
                      end else begin
                        (* Compile-time constant, use only one extend type *)
                        let extend_op = match is_unsigned_node.value with
                          | Some "true" | Some "1" -> "zero_extend"
                          | _ -> "sign_extend"
                        in

                        let byte_ext = make_node
                          ~display_name:(Some (Printf.sprintf "%s_byte(8->32)" extend_op))
                          ~operator:(Some extend_op)
                          ~bit_width:(Some 32)
                          extend_op in
                        let byte_ext = add_node builder byte_ext in
                        connect builder byte_node byte_ext "operand";

                        let half_ext = make_node
                          ~display_name:(Some (Printf.sprintf "%s_half(16->32)" extend_op))
                          ~operator:(Some extend_op)
                          ~bit_width:(Some 32)
                          extend_op in
                        let half_ext = add_node builder half_ext in
                        connect builder half_node half_ext "operand";

                        (byte_ext, half_ext)
                      end
                    in

                    (* Create width comparisons: width == 0b10 (word), width == 0b01 (half) *)
                    let is_word = make_node
                      ~display_name:(Some "width==0b10(word)")
                      ~operator:(Some "==")
                      "comparison" in
                    let is_word = add_node builder is_word in
                    connect builder width_node is_word "operand";
                    let word_enc = make_node ~value:(Some "2") ~bit_width:(Some 2) "literal" in
                    let word_enc = add_node builder word_enc in
                    connect builder word_enc is_word "operand";

                    let is_half = make_node
                      ~display_name:(Some "width==0b01(half)")
                      ~operator:(Some "==")
                      "comparison" in
                    let is_half = add_node builder is_half in
                    connect builder width_node is_half "operand";
                    let half_enc = make_node ~value:(Some "1") ~bit_width:(Some 2) "literal" in
                    let half_enc = add_node builder half_enc in
                    connect builder half_enc is_half "operand";

                    (* Create nested conditionals: word ? word : (half ? half_ext : byte_ext) *)
                    let inner_cond = make_node
                      ~display_name:(Some "select_extended_half_or_byte")
                      ~operator:(Some "conditional")
                      ~bit_width:(Some 32)
                      "conditional" in
                    let inner_cond = add_node builder inner_cond in
                    connect builder is_half inner_cond "ternary_condition";
                    connect builder half_extended inner_cond "ternary_true";
                    connect builder byte_extended inner_cond "ternary_false";

                    let outer_cond = make_node
                      ~display_name:(Some "select_extended_width")
                      ~operator:(Some "conditional")
                      ~bit_width:(Some 32)
                      "conditional" in
                    let outer_cond = add_node builder outer_cond in
                    connect builder is_word outer_cond "ternary_condition";
                    connect builder word_node outer_cond "ternary_true";
                    connect builder inner_cond outer_cond "ternary_false";

                    (* Mark width_select node for later cleanup by storing replacement mapping *)
                    (* We'll do edge redirection after all SAIL processing is complete *)
                    (* For now, just tag the width_select node so we can find it later *)
                    let marked_node = {width_select_node with
                      display_name = Some (Printf.sprintf "REPLACE_WITH_%s" outer_cond.id)
                    } in
                    builder.nodes <- List.map (fun (n : rg_node) ->
                      if n.id = width_select_node.id then marked_node else n
                    ) builder.nodes;

                    Printf.printf "        Created width-aware extension, marked width_select %s for replacement with %s\n%!"
                      width_select_node.id outer_cond.id;
                    outer_cond

                | _ ->
                    Printf.eprintf "Warning: width_select node missing required edges\n%!";
                    data_node

              end else begin
                (* Original single-width extension logic *)
                (* Check if is_unsigned is true (zero extend) or false (sign extend) *)
                let is_zero_extend = match is_unsigned_node.value with
                  | Some "true" | Some "1" -> true
                  | _ -> false
                in

                (* Get source width from data node *)
                let source_width = match data_node.bit_width with
                  | Some w -> w
                  | None ->
                      (* Try to infer from display name (e.g., "dmem[addr]_8bit") *)
                      (match data_node.display_name with
                      | Some name when String.contains name '_' ->
                          (try
                            let parts = String.split_on_char '_' name in
                            let last = List.hd (List.rev parts) in
                            (* Extract number from "8bit", "16bit", "32bit" *)
                            if String.length last > 3 && String.sub last (String.length last - 3) 3 = "bit" then
                              int_of_string (String.sub last 0 (String.length last - 3))
                            else 8
                          with _ -> 8)
                      | _ -> 8)  (* Default to 8 bits (byte load) *)
                in

                let target_width = 32 in  (* RISC-V register width *)

                (* Only create extension if source is smaller than target *)
                if source_width < target_width then begin
                  let extend_op = if is_zero_extend then "zero_extend" else "sign_extend" in
                  let extend_node = make_node
                    ~display_name:(Some (Printf.sprintf "%s(%dbit->%dbit)" extend_op source_width target_width))
                    ~operator:(Some extend_op)
                    ~bit_width:(Some target_width)
                    extend_op in  (* Use extend_op as node_type for SMT converter *)
                  let extend_node = add_node builder extend_node in

                  (* Connect data as operand *)
                  connect builder data_node extend_node "operand";

                  Printf.printf "        Created %s: %d bits -> %d bits\n%!" extend_op source_width target_width;
                  extend_node
                end else begin
                  (* No extension needed, just pass through *)
                  Printf.printf "        No extension needed (%d >= %d), passing through\n%!" source_width target_width;
                  data_node
                end
              end

          | _ ->
              Printf.eprintf "Warning: extend_value has unexpected args (%d)\n%!" (List.length arg_nodes);
              let func_node = make_node ~display_name:(Some display) ~operator:(Some "extend_value") "operation" in
              add_node builder func_node
        end else if func_name = "get_next_pc" then begin
          (* get_next_pc() - inlines to PC + 4 for JAL/JALR *)
          Printf.printf "        *** BRANCH: get_next_pc (inlining to PC+4) ***\n%!";

          (* Find or create pc_rd node *)
          let pc_rd_node = match find_node builder "pc_rd" with
            | Some node -> node
            | None ->
                let node = make_node ~display_name:(Some "pc_rd") ~bit_width:(Some 32)
                  ~is_arch_state:true "isa_state" in
                add_node builder node
          in

          (* Create literal 4 *)
          let lit_4 = make_node
            ~display_name:(Some "4")
            ~value:(Some "4")
            ~bit_width:(Some 32)
            "literal" in
          let lit_4 = add_node builder lit_4 in

          (* Create PC + 4 operation *)
          let pc_plus_4 = make_node
            ~display_name:(Some "pc_rd + 4")
            ~operator:(Some "+")
            ~bit_width:(Some 32)
            "operation" in
          let pc_plus_4 = add_node builder pc_plus_4 in
          connect builder pc_rd_node pc_plus_4 "operand";
          connect builder lit_4 pc_plus_4 "operand";

          Printf.printf "        Inlined get_next_pc() to PC + 4\n%!";
          pc_plus_4
        end else if func_name = "update_elp_state" then begin
          (* update_elp_state(reg) - SAIL extension for ELP (Expected Landing Pad) *)
          (* This is metadata that doesn't affect core semantics, so pass through the argument *)
          Printf.printf "        *** BRANCH: update_elp_state (pass-through) ***\n%!";
          match arg_nodes with
          | [arg] -> arg
          | _ ->
              Printf.eprintf "Warning: update_elp_state has unexpected args (%d)\n%!" (List.length arg_nodes);
              (* Return empty node if no args *)
              make_node ~display_name:(Some "update_elp_state") "var" |> add_node builder
        end else if node_type = "csr_operation" then begin
          (* doCSR(csr, rs1_val, rd, op, access_type) *)
          (* Model as: old_val = csr[csr_addr]; new_val = f(old_val, rs1_val); csr[csr_addr] = new_val; rf[rd] = old_val *)
          Printf.printf "        *** BRANCH: csr_operation ***\n%!";
          Printf.printf "        DEBUG: doCSR detected with %d args\n%!" (List.length arg_nodes);

          match arg_nodes with
          | csr_addr_node :: rs1_val_node :: rd_node :: op_node :: _rest ->
              (* Find or create CSR array - must find the isa_state node, not a
                 bitslice or var that happens to be named "csr" *)
              let csr_node =
                let existing = List.find_opt (fun (n : rg_node) ->
                  n.node_type = "isa_state" &&
                  (match n.display_name with Some dn -> dn = "csr" | None -> false)
                ) builder.nodes in
                match existing with
                | Some node -> node
                | None ->
                    let node = make_node ~display_name:(Some "csr")
                      ~bit_width:(Some 32) ~dimensions:(Some [(31, 0); (11, 0)])
                      ~is_arch_state:true ~array_size:(Some 4096) "isa_state" in
                    add_node builder node
              in

              (* Step 1: Read CSR: old_val = csr[csr_addr] *)
              let csr_read_node = make_node
                ~display_name:(Some (Printf.sprintf "csr[%s]"
                  (Option.value ~default:"csr_addr" csr_addr_node.display_name)))
                ~operator:(Some "array_access")
                ~bit_width:(Some 32)
                "array_access" in
              let csr_read_node = add_node builder csr_read_node in
              connect builder csr_node csr_read_node "array_base";
              connect builder csr_addr_node csr_read_node "array_index";

              (* Step 2: Compute new value based on CSR operation (op_node encodes CSRRW/CSRRS/CSRRC) *)
              (* For CSRRW: new_val = rs1_val *)
              (* For CSRRS: new_val = old_val | rs1_val *)
              (* For CSRRC: new_val = old_val & ~rs1_val *)
              (* We use a generic csr_modify node with op as selector *)
              let csr_modify_node = make_node
                ~display_name:(Some "csr_modify")
                ~operator:(Some "csr_modify")
                ~bit_width:(Some 32)
                "operation" in
              let csr_modify_node = add_node builder csr_modify_node in
              connect builder csr_read_node csr_modify_node "operand";
              connect builder rs1_val_node csr_modify_node "operand";
              connect builder op_node csr_modify_node "operand";

              (* Step 3: Write CSR: csr[csr_addr] = new_val *)
              let csr_write_node = make_node
                ~display_name:(Some (Printf.sprintf "csr[%s]_wr"
                  (Option.value ~default:"csr_addr" csr_addr_node.display_name)))
                ~operator:(Some "array_write")
                "array_write" in
              let csr_write_node = add_node builder csr_write_node in
              connect builder csr_node csr_write_node "array_base";
              connect builder csr_addr_node csr_write_node "array_index";
              connect builder csr_modify_node csr_write_node "assignment";

              (* Step 4: Writeback to rd: rf[rd] = old_val *)
              let rf_node = match find_node builder "rf" with
                | Some node -> node
                | None ->
                    let dims = Some [(31, 0); (4, 0)] in
                    let node = make_node ~display_name:(Some "rf") ~is_arch_state:true
                                        ~bit_width:(Some 32) ~dimensions:dims "isa_state" in
                    add_node builder node
              in

              let rf_write_name = Printf.sprintf "rf[%s]_wr"
                (Option.value ~default:"rd" rd_node.display_name) in
              let rf_write_node = make_node ~display_name:(Some rf_write_name)
                ~operator:(Some "array_write") "array_write" in
              let rf_write_node = add_node builder rf_write_node in
              connect builder rf_node rf_write_node "array_base";
              connect builder rd_node rf_write_node "array_index";

              (* Add conditional: rd != 0 (x0 is hardwired zero) *)
              let zero_node = make_node ~display_name:(Some "0") ~value:(Some "0")
                ~bit_width:(Some 5) "literal" in
              let zero_node = add_node builder zero_node in
              let cmp_node = make_node ~display_name:(Some (Printf.sprintf "%s != 0"
                (Option.value ~default:"rd" rd_node.display_name)))
                ~operator:(Some "!=") "comparison" in
              let cmp_node = add_node builder cmp_node in
              connect builder rd_node cmp_node "operand";
              connect builder zero_node cmp_node "operand";
              connect ~enable:(Some cmp_node.id) builder csr_read_node rf_write_node "assignment";

              Printf.printf "        Created CSR read-modify-write graph\n%!";
              (* Return the old CSR value as the result of this expression *)
              csr_read_node
          | _ ->
              Printf.eprintf "Warning: doCSR has unexpected args (%d)\n%!" (List.length arg_nodes);
              let func_node = make_node ~display_name:(Some display) ~operator node_type in
              add_node builder func_node

        end else if node_type = "fp_reg_read" then begin
          (* Floating-point register read: rF_or_X_S(idx) -> frf[idx] *)
          Printf.printf "        *** BRANCH: fp_reg_read ***\n%!";
          match arg_nodes with
          | [idx_node] | idx_node :: _ ->
              (* Find or create fp register file *)
              (* D extension (rF_or_X_D, F_D) needs 64-bit frf *)
              let is_d_ext = match operator with
                | Some op -> String.length op >= 2 &&
                             String.sub op (String.length op - 2) 2 = "_D"
                | None -> false
              in
              let fp_rf_node = match find_node builder "frf" with
                | Some node -> node
                | None ->
                    let (bw, dims) = if is_d_ext then
                      (64, Some [(63, 0); (4, 0)])
                    else
                      (32, Some [(31, 0); (4, 0)])
                    in
                    let node = make_node ~display_name:(Some "frf") ~is_arch_state:true
                                        ~is_memory:true ~array_depth:(Some 5)
                                        ~dimensions:dims ~bit_width:(Some bw) "isa_state" in
                    add_node builder node
              in
              let read_name = Printf.sprintf "frf[%s]_rd"
                (Option.value ~default:"_" idx_node.display_name) in
              let read_node = make_node ~display_name:(Some read_name)
                                       "array_access" in
              let read_node = add_node builder read_node in
              connect builder fp_rf_node read_node "array_base";
              connect builder idx_node read_node "array_index";
              Printf.printf "        Created fp array_access node %s\n%!" read_name;
              read_node
          | [] ->
              let func_node = make_node ~display_name:(Some display) ~operator node_type in
              add_node builder func_node

        end else if node_type = "fp_reg_write" then begin
          (* Floating-point register write: wF_or_X_S(idx, value) -> frf[idx] = value *)
          Printf.printf "        *** BRANCH: fp_reg_write ***\n%!";
          match arg_nodes with
          | [idx_node; value_node] ->
              (* Find or create fp register file *)
              (* D extension (wF_or_X_D, wF_D) needs 64-bit frf *)
              let is_d_ext = match operator with
                | Some op -> String.length op >= 2 &&
                             String.sub op (String.length op - 2) 2 = "_D"
                | None -> false
              in
              let fp_rf_node = match find_node builder "frf" with
                | Some node -> node
                | None ->
                    let (bw, dims) = if is_d_ext then
                      (64, Some [(63, 0); (4, 0)])
                    else
                      (32, Some [(31, 0); (4, 0)])
                    in
                    let node = make_node ~display_name:(Some "frf") ~is_arch_state:true
                                        ~is_memory:true ~array_depth:(Some 5)
                                        ~dimensions:dims ~bit_width:(Some bw) "isa_state" in
                    add_node builder node
              in
              let write_name = Printf.sprintf "frf[%s]_wr"
                (Option.value ~default:"_" idx_node.display_name) in
              let write_node = make_node ~display_name:(Some write_name)
                                         ~operator
                                         "array_write" in
              let write_node = add_node builder write_node in
              connect builder fp_rf_node write_node "array_base";
              connect builder idx_node write_node "array_index";
              connect builder value_node write_node "assignment";
              Printf.printf "        Created fp array_write node %s\n%!" write_name;
              write_node
          | _ ->
              let func_node = make_node ~display_name:(Some display) ~operator node_type in
              add_node builder func_node

        end else if node_type = "fp_fflags_update" then begin
          (* accrue_fflags(flags) -> fcsr |= flags
             Uses separate fcsr (read) and fcsr_wr (write) isa_state nodes
             to avoid graph cycles, matching the pc_rd/pc_wr pattern. *)
          (* Find or create fcsr read node *)
          let fcsr_node = match find_node builder "fcsr" with
            | Some node -> node
            | None ->
                let node = make_node ~display_name:(Some "fcsr") ~is_arch_state:true
                                    ~bit_width:(Some 32) "isa_state" in
                add_node builder node
          in
          (* Find or create fcsr write node *)
          let fcsr_wr_node = match find_node builder "fcsr_wr" with
            | Some node -> node
            | None ->
                let node = make_node ~display_name:(Some "fcsr_wr") ~is_arch_state:true
                                    ~bit_width:(Some 32) "isa_state" in
                add_node builder node
          in
          (* Create OR operation: fcsr.fflags | new_flags
             Use unique name per instruction so the merger doesn't share them *)
          let flags_name = match arg_nodes with
            | [flags_node] | flags_node :: _ ->
                Option.value ~default:"flags" flags_node.display_name
            | [] -> "flags"
          in
          let or_name = Printf.sprintf "fcsr | %s" flags_name in
          let or_node = make_node ~display_name:(Some or_name)
                                  ~operator:(Some "|") "operation" in
          let or_node = add_node builder or_node in
          (* Connect: fcsr -> OR (read current fflags) *)
          connect builder fcsr_node or_node "operand";
          (* Connect: flags argument -> OR *)
          (match arg_nodes with
           | [flags_node] | flags_node :: _ ->
               connect builder flags_node or_node "operand"
           | [] -> ());
          (* Write OR result to fcsr_wr (separate write port, no cycle) *)
          connect builder or_node fcsr_wr_node "assignment";
          or_node

        end else if node_type = "fp_operation" then begin
          (* Softfloat intrinsic call: create fp_operation node with normalized operator *)
          Printf.printf "        *** BRANCH: fp_operation (op=%s) ***\n%!"
            (Option.value ~default:"?" operator);

          (* Special handling for fp_muladd: detect negation pattern to produce
             fp_fmadd / fp_fmsub / fp_fnmsub / fp_fnmadd directly.
             SAIL calls riscv_f32MulAdd(rm, op1, op2, op3) where:
               FMADD:  op1=rs1,           op2=rs2, op3=rs3
               FMSUB:  op1=rs1,           op2=rs2, op3=negate(rs3)
               FNMSUB: op1=negate(rs1),   op2=rs2, op3=rs3
               FNMADD: op1=negate(rs1),   op2=rs2, op3=negate(rs3) *)
          if operator = Some "fp_muladd" || operator = Some "fp_muladd_d" then begin
            let fma_d_sfx = if operator = Some "fp_muladd_d" then "_d" else "" in
            (* arg_nodes are [rm; op1; op2; op3] — first is rounding mode *)
            let non_rm_args = match arg_nodes with
              | _ :: rest -> rest  (* skip rounding mode *)
              | [] -> []
            in
            (* Check if an arg node is an fp_negate (now emitted as bxor with 0x80000000),
               and if so unwrap it to get the un-negated source *)
            let unwrap_negate (n : rg_node) =
              let is_negate =
                (* Old style: fp_operation with fp_negate operator *)
                (n.operator = Some "fp_negate") ||
                (* New style: bxor with 0x80000000 sign-mask *)
                (n.operator = Some "bxor" && n.node_type = "operation")
              in
              if is_negate then begin
                (* Find the non-literal input to this negate node *)
                let negate_inputs = List.filter (fun (e : rg_edge) ->
                  e.target = n.id && (e.edge_type = "operand" || e.edge_type = "fp_operand")
                ) builder.edges in
                (* For bxor negate, skip the literal mask operand *)
                let non_literal_inputs = List.filter (fun (e : rg_edge) ->
                  match List.find_opt (fun (node : rg_node) -> node.id = e.source) builder.nodes with
                  | Some src -> src.node_type <> "literal"
                  | None -> true
                ) negate_inputs in
                let inputs = if non_literal_inputs <> [] then non_literal_inputs else negate_inputs in
                match inputs with
                | e :: _ ->
                    let src = List.find (fun (node : rg_node) -> node.id = e.source) builder.nodes in
                    (true, src)  (* negated, unwrapped source *)
                | [] -> (false, n)  (* can't unwrap, treat as not negated *)
              end else
                (false, n)
            in
            let op1, op2, op3 = match non_rm_args with
              | [a; b; c] -> (a, b, c)
              | a :: b :: c :: _ -> (a, b, c)
              | _ ->
                  let dummy = make_node ~display_name:(Some "0") ~value:(Some "0") "literal" in
                  let dummy = add_node builder dummy in
                  (dummy, dummy, dummy)
            in
            let (a_neg, real_op1) = unwrap_negate op1 in
            let (_b_neg, real_op2) = unwrap_negate op2 in
            let (c_neg, real_op3) = unwrap_negate op3 in
            (* Determine FMA variant *)
            let fma_variant = match a_neg, c_neg with
              | false, false -> "fp_fmadd" ^ fma_d_sfx    (* rs1*rs2 + rs3 *)
              | false, true  -> "fp_fmsub" ^ fma_d_sfx    (* rs1*rs2 - rs3 *)
              | true,  false -> "fp_fnmsub" ^ fma_d_sfx   (* -(rs1*rs2) + rs3 *)
              | true,  true  -> "fp_fnmadd" ^ fma_d_sfx   (* -(rs1*rs2) - rs3 *)
            in
            Printf.printf "        FMA variant: %s (a_neg=%b, c_neg=%b)\n%!" fma_variant a_neg c_neg;
            let fma_display = Printf.sprintf "%s(%s, %s, %s)"
              fma_variant
              (Option.value ~default:"?" real_op1.display_name)
              (Option.value ~default:"?" real_op2.display_name)
              (Option.value ~default:"?" real_op3.display_name) in
            let func_node = make_node ~display_name:(Some fma_display)
                                       ~operator:(Some fma_variant) "fp_operation" in
            let func_node = add_node builder func_node in
            (* Connect rounding mode *)
            (match arg_nodes with
             | rm_node :: _ -> connect builder rm_node func_node "operand"
             | [] -> ());
            (* Connect unwrapped operands with position info *)
            connect ~position:(Some "0") builder real_op1 func_node "operand";
            connect ~position:(Some "1") builder real_op2 func_node "operand";
            connect ~position:(Some "2") builder real_op3 func_node "operand";
            func_node
          end else begin
            let func_node = make_node ~display_name:(Some display) ~operator "fp_operation" in
            let func_node = add_node builder func_node in
            (* Connect arguments as operands with explicit positions *)
            List.iteri (fun i arg_node ->
              connect ~position:(Some (string_of_int i)) builder arg_node func_node "operand"
            ) arg_nodes;
            func_node
          end

        end else if node_type = "fp_rounding_mode" then begin
          (* select_instr_or_fcsr_rm: if rm == 7 (dynamic), use fcsr[7:5], else use rm.
             Emit as a ternary_op node matching the reference ISA pattern. *)
          Printf.printf "        *** BRANCH: fp_rounding_mode -> ternary mux ***\n%!";
          let fcsr_node = match find_node builder "fcsr" with
            | Some node -> node
            | None ->
                let node = make_node ~display_name:(Some "fcsr") ~is_arch_state:true
                                    ~bit_width:(Some 32) "isa_state" in
                add_node builder node
          in
          (* Get the rm argument (instruction rounding mode field) *)
          let rm_arg = match arg_nodes with
            | [rm] -> rm
            | _ ->
                let node = make_node ~display_name:(Some "rm") ~bit_width:(Some 3) "var" in
                add_node builder node
          in
          (* Build: (rm == 3'b111) ? fcsr[7:5] : rm *)
          (* 1. Condition: rm == 7 *)
          let seven_lit = make_node ~display_name:(Some "7") ~value:(Some "7")
                                    ~bit_width:(Some 3) "literal" in
          let seven_lit = add_node builder seven_lit in
          let cond_node = make_node ~display_name:(Some "rm_eq_7")
                                    ~operator:(Some "==") ~bit_width:(Some 1) "comparison" in
          let cond_node = add_node builder cond_node in
          connect builder rm_arg cond_node "operand";
          connect builder seven_lit cond_node "operand";
          (* 2. True branch: fcsr[7:5] *)
          let fcsr_slice = make_node ~display_name:(Some "fcsr_frm")
                                     ~bitslice:(Some (7, 5))
                                     ~bit_width:(Some 3) "bit_slice" in
          let fcsr_slice = add_node builder fcsr_slice in
          connect builder fcsr_node fcsr_slice "operand";
          (* 3. Ternary mux: cond ? fcsr[7:5] : rm *)
          let mux_node = make_node ~display_name:(Some "eff_rm")
                                   ~operator:(Some "ternary")
                                   ~bit_width:(Some 3) "ternary_op" in
          let mux_node = add_node builder mux_node in
          connect builder cond_node mux_node "ternary_condition";
          connect builder fcsr_slice mux_node "ternary_true";
          connect builder rm_arg mux_node "ternary_false";
          mux_node

        end else if node_type = "fp_negate" then begin
          (* FP negate is just a sign-bit flip: {~x[31], x[30:0]} *)
          Printf.printf "        *** BRANCH: fp_negate -> bit_xor ***\n%!";
          let input_node = match arg_nodes with
            | [a] -> a
            | a :: _ -> a
            | [] ->
                let node = make_node ~display_name:(Some "0") ~value:(Some "0") "literal" in
                add_node builder node
          in
          (* XOR with sign bit mask: 0x80000000 *)
          let mask = make_node ~display_name:(Some "0x80000000")
                               ~value:(Some "2147483648")
                               ~bit_width:(Some 32) "literal" in
          let mask = add_node builder mask in
          let xor_node = make_node ~display_name:(Some "negate")
                                   ~operator:(Some "bxor")
                                   ~bit_width:(Some 32) "operation" in
          let xor_node = add_node builder xor_node in
          connect builder input_node xor_node "operand";
          connect builder mask xor_node "operand";
          xor_node

        end else if node_type = "fp_bit_test" then begin
          (* FP bit-level classification tests - emit as comparison operations *)
          Printf.printf "        *** BRANCH: fp_bit_test (op=%s) ***\n%!"
            (Option.value ~default:"?" operator);
          let input_node = match arg_nodes with
            | [a] -> a
            | a :: _ -> a
            | [] ->
                let node = make_node ~display_name:(Some "0") ~value:(Some "0") "literal" in
                add_node builder node
          in
          let op = Option.value ~default:"fp_is_nan" operator in
          (match op with
           | "fp_is_nan" ->
               (* NaN: exponent all 1s AND mantissa non-zero *)
               let exp_slice = make_node ~display_name:(Some "exp") ~bitslice:(Some (30, 23))
                                         ~bit_width:(Some 8) "bit_slice" in
               let exp_slice = add_node builder exp_slice in
               connect builder input_node exp_slice "operand";
               let mant_slice = make_node ~display_name:(Some "mant") ~bitslice:(Some (22, 0))
                                          ~bit_width:(Some 23) "bit_slice" in
               let mant_slice = add_node builder mant_slice in
               connect builder input_node mant_slice "operand";
               let ff_lit = make_node ~display_name:(Some "0xFF") ~value:(Some "255") ~bit_width:(Some 8) "literal" in
               let ff_lit = add_node builder ff_lit in
               let zero_lit = make_node ~display_name:(Some "0") ~value:(Some "0") ~bit_width:(Some 23) "literal" in
               let zero_lit = add_node builder zero_lit in
               let exp_eq = make_node ~display_name:(Some "exp_all_ones") ~operator:(Some "eq") ~bit_width:(Some 1) "operation" in
               let exp_eq = add_node builder exp_eq in
               connect builder exp_slice exp_eq "operand";
               connect builder ff_lit exp_eq "operand";
               let mant_ne = make_node ~display_name:(Some "mant_nonzero") ~operator:(Some "ne") ~bit_width:(Some 1) "operation" in
               let mant_ne = add_node builder mant_ne in
               connect builder mant_slice mant_ne "operand";
               connect builder zero_lit mant_ne "operand";
               let and_node = make_node ~display_name:(Some "is_nan") ~operator:(Some "band") ~bit_width:(Some 1) "operation" in
               let and_node = add_node builder and_node in
               connect builder exp_eq and_node "operand";
               connect builder mant_ne and_node "operand";
               and_node
           | "fp_is_snan" ->
               (* Signaling NaN: NaN with mantissa[22]=0 *)
               let exp_slice = make_node ~display_name:(Some "exp") ~bitslice:(Some (30, 23))
                                         ~bit_width:(Some 8) "bit_slice" in
               let exp_slice = add_node builder exp_slice in
               connect builder input_node exp_slice "operand";
               let mant_slice = make_node ~display_name:(Some "mant") ~bitslice:(Some (22, 0))
                                          ~bit_width:(Some 23) "bit_slice" in
               let mant_slice = add_node builder mant_slice in
               connect builder input_node mant_slice "operand";
               let bit22 = make_node ~display_name:(Some "mant22") ~bitslice:(Some (22, 22))
                                     ~bit_width:(Some 1) "bit_slice" in
               let bit22 = add_node builder bit22 in
               connect builder input_node bit22 "operand";
               let ff_lit = make_node ~display_name:(Some "0xFF") ~value:(Some "255") ~bit_width:(Some 8) "literal" in
               let ff_lit = add_node builder ff_lit in
               let zero23 = make_node ~display_name:(Some "0") ~value:(Some "0") ~bit_width:(Some 23) "literal" in
               let zero23 = add_node builder zero23 in
               let zero1 = make_node ~display_name:(Some "0") ~value:(Some "0") ~bit_width:(Some 1) "literal" in
               let zero1 = add_node builder zero1 in
               let exp_eq = make_node ~display_name:(Some "exp_ff") ~operator:(Some "eq") ~bit_width:(Some 1) "operation" in
               let exp_eq = add_node builder exp_eq in
               connect builder exp_slice exp_eq "operand";
               connect builder ff_lit exp_eq "operand";
               let mant_ne = make_node ~display_name:(Some "mant_nz") ~operator:(Some "ne") ~bit_width:(Some 1) "operation" in
               let mant_ne = add_node builder mant_ne in
               connect builder mant_slice mant_ne "operand";
               connect builder zero23 mant_ne "operand";
               let bit22_eq = make_node ~display_name:(Some "quiet_bit_0") ~operator:(Some "eq") ~bit_width:(Some 1) "operation" in
               let bit22_eq = add_node builder bit22_eq in
               connect builder bit22 bit22_eq "operand";
               connect builder zero1 bit22_eq "operand";
               let and_node = make_node ~display_name:(Some "is_snan") ~operator:(Some "band") ~bit_width:(Some 1) "operation" in
               let and_node = add_node builder and_node in
               connect builder exp_eq and_node "operand";
               connect builder mant_ne and_node "operand";
               connect builder bit22_eq and_node "operand";
               and_node
           | "fp_is_qnan" ->
               (* Quiet NaN: NaN with mantissa[22]=1 *)
               let exp_slice = make_node ~display_name:(Some "exp") ~bitslice:(Some (30, 23))
                                         ~bit_width:(Some 8) "bit_slice" in
               let exp_slice = add_node builder exp_slice in
               connect builder input_node exp_slice "operand";
               let bit22 = make_node ~display_name:(Some "mant22") ~bitslice:(Some (22, 22))
                                     ~bit_width:(Some 1) "bit_slice" in
               let bit22 = add_node builder bit22 in
               connect builder input_node bit22 "operand";
               let ff_lit = make_node ~display_name:(Some "0xFF") ~value:(Some "255") ~bit_width:(Some 8) "literal" in
               let ff_lit = add_node builder ff_lit in
               let one_lit = make_node ~display_name:(Some "1") ~value:(Some "1") ~bit_width:(Some 1) "literal" in
               let one_lit = add_node builder one_lit in
               let exp_eq = make_node ~display_name:(Some "exp_ff") ~operator:(Some "eq") ~bit_width:(Some 1) "operation" in
               let exp_eq = add_node builder exp_eq in
               connect builder exp_slice exp_eq "operand";
               connect builder ff_lit exp_eq "operand";
               let bit22_eq = make_node ~display_name:(Some "quiet_bit_1") ~operator:(Some "eq") ~bit_width:(Some 1) "operation" in
               let bit22_eq = add_node builder bit22_eq in
               connect builder bit22 bit22_eq "operand";
               connect builder one_lit bit22_eq "operand";
               let and_node = make_node ~display_name:(Some "is_qnan") ~operator:(Some "band") ~bit_width:(Some 1) "operation" in
               let and_node = add_node builder and_node in
               connect builder exp_eq and_node "operand";
               connect builder bit22_eq and_node "operand";
               and_node
           | "fp_is_neg_zero" ->
               (* Negative zero: value == 0x80000000 *)
               let lit = make_node ~display_name:(Some "0x80000000") ~value:(Some "2147483648")
                                   ~bit_width:(Some 32) "literal" in
               let lit = add_node builder lit in
               let eq_node = make_node ~display_name:(Some "is_neg_zero") ~operator:(Some "eq")
                                       ~bit_width:(Some 1) "operation" in
               let eq_node = add_node builder eq_node in
               connect builder input_node eq_node "operand";
               connect builder lit eq_node "operand";
               eq_node
           | "fp_is_pos_zero" ->
               (* Positive zero: value == 0x00000000 *)
               let lit = make_node ~display_name:(Some "0") ~value:(Some "0")
                                   ~bit_width:(Some 32) "literal" in
               let lit = add_node builder lit in
               let eq_node = make_node ~display_name:(Some "is_pos_zero") ~operator:(Some "eq")
                                       ~bit_width:(Some 1) "operation" in
               let eq_node = add_node builder eq_node in
               connect builder input_node eq_node "operand";
               connect builder lit eq_node "operand";
               eq_node
           | _ ->
               (* Unknown bit test - fall through as generic operation *)
               let func_node = make_node ~display_name:(Some display) ~operator "operation" in
               let func_node = add_node builder func_node in
               List.iter (fun arg_node -> connect builder arg_node func_node "operand") arg_nodes;
               func_node)

        end else if node_type = "identity" then begin
          (* Identity function: just return the input argument directly *)
          Printf.printf "        *** BRANCH: identity (%s) ***\n%!" func_name;
          (match arg_nodes with
           | [arg] -> arg
           | arg :: _ -> arg
           | [] ->
               let func_node = make_node ~display_name:(Some display) ~operator "operation" in
               add_node builder func_node)

        end else if node_type = "fp_constant" then begin
          (* FP constants - emit as literal nodes *)
          Printf.printf "        *** BRANCH: fp_constant (op=%s) ***\n%!"
            (Option.value ~default:"?" operator);
          (match Option.value ~default:"" operator with
           | "fp_canonical_nan" ->
               (* IEEE 754 canonical quiet NaN: 0x7FC00000 (single), 0x7FF8000000000000 (double) *)
               let nan_val = "2143289344" in  (* 0x7FC00000 *)
               let nan_node = make_node ~display_name:(Some "canonical_NaN")
                                        ~value:(Some nan_val) ~bit_width:(Some 32) "literal" in
               add_node builder nan_node
           | _ ->
               let func_node = make_node ~display_name:(Some display) ~operator "literal" in
               add_node builder func_node)

        end else if func_name = "get_arch_pc" || func_name = "get_PC" || func_name = "PC" then begin
          (* get_arch_pc -> return the pc_rd ISA state node (current program counter) *)
          Printf.printf "        *** BRANCH: get_arch_pc -> pc_rd ***\n%!";
          match find_node builder "pc_rd" with
          | Some pc_node -> pc_node
          | None ->
              let pc_node = make_node ~display_name:(Some "pc_rd") ~is_arch_state:true
                                      ~bit_width:(Some 32) "isa_state" in
              add_node builder pc_node

        end else if node_type = "memory_access_type" then begin
          (* Skip Read/Write/Execute enum constructors - they're just metadata *)
          Printf.printf "        *** BRANCH: memory_access_type ***\n%!";
          Printf.printf "        DEBUG: Skipping memory access type '%s'\n%!" func_name;
          (* Create a passthrough operation that will be optimized out *)
          let func_node = make_node ~display_name:(Some display) ~operator node_type in
          let func_node = add_node builder func_node in
          (* Connect arguments as operands so they're available *)
          List.iter (fun arg_node ->
            connect builder arg_node func_node "operand"
          ) arg_nodes;
          func_node
        end else begin
          Printf.printf "        *** BRANCH: generic fallback (func_name='%s', node_type='%s') ***\n%!" func_name node_type;
          (* For concat nodes, calculate result width from operand widths *)
          let (actual_node_type, bit_width_opt) =
            if (func_name = "bitvector_concat" || node_type = "concat"
                || (Option.value ~default:"" operator) = "bitvector_concat")
               && List.length arg_nodes >= 2 then begin
              (* Sum widths of all operands *)
              let widths = List.map (fun (n : rg_node) -> n.bit_width) arg_nodes in
              if List.for_all (fun w -> w <> None) widths then begin
                let total = List.fold_left (fun acc w -> acc + Option.get w) 0 widths in
                (node_type, Some total)
              end else
                (node_type, None)
            end else if func_name = "sign_extend" || func_name = "sail_sign_extend" then begin
              ("sign_extend", Some 32)
            end else if func_name = "zero_extend" || func_name = "sail_zero_extend" then begin
              Printf.printf "        DEBUG: %s -> type=zero_extend, bit_width=32 (xlen)\n%!" func_name;
              ("zero_extend", Some 32)
            end else
              (node_type, None)
          in
          let actual_operator = if actual_node_type = "sign_extend" || actual_node_type = "zero_extend"
                                then Some actual_node_type else operator in
          let func_node = make_node ~display_name:(Some display) ~operator:actual_operator ~bit_width:bit_width_opt actual_node_type in
          let func_node = add_node builder func_node in

          (* Special handling for PC update functions *)
          if node_type = "pc_update" then begin
            (* Connect the first argument (target address) to pc_wr *)
            (match (List.nth_opt arg_nodes 0, find_node builder "pc_wr") with
            | (Some target_node, Some pc_wr_node) ->
                Printf.printf "        Connecting %s target to pc_wr (edge: assignment)\n%!" func_name;
                connect builder target_node pc_wr_node "assignment"
            | _ ->
                Printf.printf "        Warning: Could not connect %s to pc_wr\n%!" func_name);
          end;

          (* Special handling for register file READ access - create array_read node *)
          let result_node = if (func_name = "rX_bits" || func_name = "X") && List.length arg_nodes = 1 then begin
            Printf.printf "        DEBUG: register read detected for %s with %d args\n%!" func_name (List.length arg_nodes);

            (* Get the index argument (rs1, rs2, etc.) *)
            let idx_node = List.hd arg_nodes in

            (* Find or create rf isa_state node *)
            let rf_node = match find_node builder "rf" with
              | Some node -> node
              | None ->
                  let dims = Some [(31, 0); (4, 0)] in
                  let node = make_node ~display_name:(Some "rf") ~is_arch_state:true
                                      ~bit_width:(Some 32) ~dimensions:dims "isa_state" in
                  add_node builder node
            in

            (* Create array_access node with name like "rf[rs1]_rd" (matches .isa format) *)
            let read_name = Printf.sprintf "rf[%s]_rd"
              (Option.value ~default:"_" idx_node.display_name) in
            let read_node = make_node ~display_name:(Some read_name)
                                     ~bit_width:(Some 32)
                                     "array_access" in
            let read_node = add_node builder read_node in

            (* Connect: rf -> array_access *)
            connect builder rf_node read_node "array_base";
            (* Connect: index -> array_access *)
            connect builder idx_node read_node "array_index";

            Printf.printf "        Created array_access node %s for %s\n%!" read_name func_name;
            read_node
          end else begin
            (* Connect arguments based on node type *)
            (* Operations need "operand" edges for SMT verification *)
            let edge_type = if node_type = "operation" || node_type = "comparison" || node_type = "bit_slice" then
              "operand"
            else
              "argument"
            in
            Printf.printf "        DEBUG: Connecting %d args with edge_type='%s' for node_type='%s'\n%!"
              (List.length arg_nodes) edge_type node_type;
            (* For bitvector_concat (including fmake_S/D/H), set position on each
               operand edge so the generator preserves MSB-to-LSB argument order.
               Position "0" = MSB (leftmost), "1" = next, etc. *)
            if (Option.value ~default:"" operator) = "bitvector_concat" then
              List.iteri (fun i arg_node ->
                connect ~position:(Some (string_of_int i)) builder arg_node func_node edge_type
              ) arg_nodes
            else
              List.iter (fun arg_node ->
                connect builder arg_node func_node edge_type
              ) arg_nodes;
            func_node
          end in
          result_node
        end
        )  (* Close the match on inlining_result *)

    (* Variable/identifier reference *)
    | E_id id ->
        let name = string_of_id id in
        (* SAIL enum constants: RETIRE_SUCCESS = 1, RETIRE_FAIL = 0 *)
        if name = "RETIRE_SUCCESS" then begin
          make_node ~display_name:(Some "RETIRE_SUCCESS") ~value:(Some "1")
                    ~bit_width:(Some 1) "literal"
          |> add_node builder
        end else if name = "RETIRE_FAIL" then begin
          make_node ~display_name:(Some "RETIRE_FAIL") ~value:(Some "0")
                    ~bit_width:(Some 1) "literal"
          |> add_node builder
        end else begin
        (* Special case: map "PC" to "pc_rd" architectural state *)
        let lookup_name = if name = "PC" then "pc_rd" else name in
        (* Check if a node with this name already exists (e.g., from decode mapping or arch state) *)
        (match find_node builder lookup_name with
        | Some existing_node ->
            Printf.printf "          E_id(%s): Found existing node %s (lookup: %s)\n%!" name existing_node.id lookup_name;
            existing_node
        | None ->
            (* Check if this is a known global constant (e.g., log2_xlen, xlen_val) *)
            match Hashtbl.find_opt builder.global_constants name with
            | Some const_val ->
                Printf.printf "          E_id(%s): Resolved to global constant %d\n%!" name const_val;
                let value_str = string_of_int const_val in
                let width = if const_val = 0 then 1
                  else if const_val > 0 then
                    let rec log2 v = if v <= 1 then 1 else 1 + log2 (v / 2) in
                    log2 const_val
                  else 32 in
                make_node ~display_name:(Some value_str) ~value:(Some value_str)
                          ~bit_width:(Some width) "literal"
                |> add_node builder
            | None ->
                (* No existing node, create a new var node with instruction prefix *)
                let prefixed_name = prefix_local_name builder name in
                Printf.printf "          E_id(%s): Creating new var node (prefixed: %s)\n%!" name prefixed_name;
                make_node ~display_name:(Some prefixed_name) "var" |> add_node builder)
        end (* end of RETIRE_SUCCESS/RETIRE_FAIL else branch *)

    (* Integer literal *)
    | E_lit (L_aux (L_num n, _)) ->
        let value_str = Big_int.to_string n in
        (* Compute minimum bit width needed to represent this value *)
        let width = try
          let int_val = Big_int.to_int n in
          if int_val = 0 then 1
          else if int_val > 0 then
            let rec log2 v = if v <= 1 then 1 else 1 + log2 (v / 2) in
            log2 int_val
          else 32 (* negative values: assume 32-bit *)
        with Failure _ | Z.Overflow -> 64 (* too large for native int *)
        in
        make_node ~display_name:(Some value_str) ~value:(Some value_str)
                  ~bit_width:(Some width) "literal"
        |> add_node builder

    (* Binary literal *)
    | E_lit (L_aux (L_bin digits, _)) ->
        let bin_str = Ast_util.string_of_bin_lit digits in
        let width = Ast_util.bin_lit_length digits in
        let value_str = (try string_of_int (int_of_string ("0b" ^ bin_str))
                         with Failure _ -> "0b" ^ bin_str) in
        make_node ~display_name:(Some ("0b" ^ bin_str))
                  ~value:(Some value_str)
                  ~bit_width:(Some width) "binary_literal"
        |> add_node builder

    (* Hex literal *)
    | E_lit (L_aux (L_hex digits, _)) ->
        let hex_str = Ast_util.string_of_hex_lit ~case:Uppercase digits in
        let width = Ast_util.hex_lit_length digits in
        let value_str = (try string_of_int (int_of_string ("0x" ^ hex_str))
                         with Failure _ -> "0x" ^ hex_str) in
        make_node ~display_name:(Some ("0x" ^ hex_str))
                  ~value:(Some value_str)
                  ~bit_width:(Some width) "verilog_hex_literal"
        |> add_node builder

    (* String literal — emit as 0 since strings have no hardware meaning;
       these typically appear in dead arms like internal_error(file, line, msg) *)
    | E_lit (L_aux (L_string _s, _)) ->
        make_node ~display_name:(Some "0") ~value:(Some "0") "literal"
        |> add_node builder

    (* Other literals (unit, bool, etc.) *)
    | E_lit _ ->
        (* Use "0" as default value for unit/bool literals for SMT compatibility *)
        make_node ~display_name:(Some "literal") ~value:(Some "0") ~bit_width:(Some 1) "literal"
        |> add_node builder

    (* Assignment: PC := PC + 4 or X[rd] := result *)
    | E_assign (lexp, rexp) ->
        Printf.printf "        DEBUG: E_assign detected\n%!";
        let rhs_node = visit_exp builder rexp in
        let lhs_node = visit_lexp_assign builder lexp rhs_node in
        Printf.printf "        DEBUG: E_assign completed, lhs type=%s\n%!" lhs_node.node_type;
        lhs_node

    (* Block/sequence of expressions *)
    | E_block exps ->
        (* Process all expressions, return the last one *)
        List.fold_left (fun _ exp -> visit_exp builder exp)
                      (make_node ~display_name:(Some "0") ~value:(Some "0") "literal" |> add_node builder) exps

    (* Let binding: let x = expr in body *)
    | E_let (LB_aux (LB_val (pat, bind_exp), _), body_exp) ->
        let bind_node = visit_exp builder bind_exp in
        (* Helper: check if a node is an FP tuple source (fp_operation itself,
           or a mux/ternary that selects between fp_operation nodes).
           When true, also widen all fp_operation inputs to packed width. *)
        let is_fp_tuple_and_widen (node : rg_node) =
          if node.node_type = "fp_operation" then true
          else begin
            (* Check for mux_input edges — the match handler creates "mux_input:N"
               format, so we need to check for the prefix, not just exact match *)
            let is_mux_or_ternary_edge (et : string) =
              et = "mux_input" || et = "ternary_true" || et = "ternary_false"
              || (String.length et > 10 && String.sub et 0 10 = "mux_input:") in
            let has_fp_input = List.exists (fun (e : rg_edge) ->
              e.target = node.id &&
              is_mux_or_ternary_edge e.edge_type &&
              List.exists (fun (n : rg_node) ->
                n.id = e.source && n.node_type = "fp_operation"
              ) builder.nodes
            ) builder.edges in
            if has_fp_input then begin
              (* Widen fp_operation inputs to packed width (5+32=37) *)
              List.iter (fun (e : rg_edge) ->
                if e.target = node.id &&
                   is_mux_or_ternary_edge e.edge_type then
                  builder.nodes <- List.map (fun (n : rg_node) ->
                    if n.id = e.source && n.node_type = "fp_operation" then
                      let vb = Option.value ~default:32 n.bit_width in
                      { n with bit_width = Some (5 + vb) }
                    else n
                  ) builder.nodes
              ) builder.edges;
              true
            end else false
          end
        in
        let rec bind_let_pattern (P_aux (pat_aux, _)) result_node =
          match pat_aux with
          | P_id id ->
              let name = string_of_id id in
              let prefixed_name = prefix_local_name builder name in
              rename_shadowed_vars prefixed_name;
              let var_node = make_node ~display_name:(Some prefixed_name) "var"
                            |> add_node builder in
              connect builder result_node var_node "definition"
          | P_typ (_, inner_pat) ->
              bind_let_pattern inner_pat result_node
          | P_tuple pats ->
              (* When result_node is a concat/tuple from E_tuple, bind each pattern
                 variable to the corresponding element node, not the concat node.
                 This is critical for tuple destructuring like:
                   let (s, e, m) = (val[31:31], val[30:23], val[22:0])
                 where each variable must get its own bitslice, not the full concat. *)
              let elem_edges = List.filter (fun (e : rg_edge) ->
                e.target = result_node.id && e.edge_type = "element"
              ) builder.edges in
              let elem_sources = List.map (fun (e : rg_edge) ->
                match List.find_opt (fun (n : rg_node) -> n.id = e.source) builder.nodes with
                | Some n -> n
                | None -> result_node
              ) elem_edges in
              if List.length elem_sources = List.length pats && List.length pats > 0 then
                List.iter2 (fun sub_pat elem_node ->
                  bind_let_pattern sub_pat elem_node
                ) pats elem_sources
              else if is_fp_tuple_and_widen result_node && List.length pats = 2 then begin
                (* FP operations return (flags, value) tuples.  The generator packs
                   {status_o[4:0], result_o} into the node's output wire.  We must
                   widen the node to 5+value_bits and create bit_slices so the
                   tuple elements map to the correct portions of the packed result. *)
                let value_bits = Option.value ~default:32 result_node.bit_width in
                let packed_width = 5 + value_bits in
                (* Widen result node (fp_operation or mux) to packed width *)
                let updated = { result_node with bit_width = Some packed_width } in
                builder.nodes <- List.map (fun (n : rg_node) ->
                  if n.id = result_node.id then updated else n) builder.nodes;
                (* Flags bit_slice: [packed_width-1 : value_bits]
                   Use instruction-prefixed + unique names to prevent merger collision *)
                let slice_uid = fresh_node_id () in
                let flags_name = if builder.instr_prefix <> "" then
                  Printf.sprintf "%s_fp_flags_%s" builder.instr_prefix slice_uid
                else Printf.sprintf "fp_flags_%s" slice_uid in
                let flags_slice = {
                  id = slice_uid; node_type = "bit_slice";
                  name = Some flags_name; display_name = Some flags_name;
                  operator = None; value = None; bit_width = Some 5;
                  is_arch_state = false; is_memory = false;
                  array_size = None; array_depth = None;
                  bitslice = Some (packed_width - 1, value_bits);
                  dimensions = None;
                } in
                builder.nodes <- flags_slice :: builder.nodes;
                builder.edges <- { id = fresh_edge_id (); source = result_node.id;
                  target = flags_slice.id; edge_type = "bit_access";
                  position = None; enable = None } :: builder.edges;
                (* Value bit_slice: [value_bits-1 : 0] *)
                let vslice_uid = fresh_node_id () in
                let value_name = if builder.instr_prefix <> "" then
                  Printf.sprintf "%s_fp_value_%s" builder.instr_prefix vslice_uid
                else Printf.sprintf "fp_value_%s" vslice_uid in
                let value_slice = {
                  id = vslice_uid; node_type = "bit_slice";
                  name = Some value_name; display_name = Some value_name;
                  operator = None; value = None; bit_width = Some value_bits;
                  is_arch_state = false; is_memory = false;
                  array_size = None; array_depth = None;
                  bitslice = Some (value_bits - 1, 0);
                  dimensions = None;
                } in
                builder.nodes <- value_slice :: builder.nodes;
                builder.edges <- { id = fresh_edge_id (); source = result_node.id;
                  target = value_slice.id; edge_type = "bit_access";
                  position = None; enable = None } :: builder.edges;
                (* Determine tuple element order from pattern names.
                   SAIL has (fflags, value) for arithmetic ops but
                   (result, fflags) for comparisons like fle_S. *)
                let pat0_is_flags = match List.nth pats 0 with
                  | P_aux (P_id id, _) ->
                      let n = string_of_id id in
                      n = "fflags" || n = "flags"
                  | P_aux (P_typ (_, P_aux (P_id id, _)), _) ->
                      let n = string_of_id id in
                      n = "fflags" || n = "flags"
                  | _ -> true (* default: assume flags first *)
                in
                if pat0_is_flags then begin
                  bind_let_pattern (List.nth pats 0) flags_slice;
                  bind_let_pattern (List.nth pats 1) value_slice
                end else begin
                  bind_let_pattern (List.nth pats 0) value_slice;
                  bind_let_pattern (List.nth pats 1) flags_slice
                end
              end
              else
                List.iter (fun sub_pat ->
                  bind_let_pattern sub_pat result_node
                ) pats
          | P_wild -> ()
          | _ ->
              (* Fallback: create a temp var *)
              let var_node = make_node ~display_name:(Some "temp") "var"
                            |> add_node builder in
              connect builder result_node var_node "definition"
        in
        bind_let_pattern pat bind_node;
        visit_exp builder body_exp

    (* Conditional: if cond then exp1 else exp2 *)
    | E_if (cond_exp, then_exp, else_exp) ->
        let cond_node = visit_exp builder cond_exp in
        let then_node = visit_exp builder then_exp in
        let else_node = visit_exp builder else_exp in
        let if_node = make_node ~display_name:(Some "if") "conditional"
                     |> add_node builder in
        connect builder cond_node if_node "condition";
        connect builder then_node if_node "then_branch";
        connect builder else_node if_node "else_branch";
        if_node

    (* Match expression: match scrutinee { case1 => exp1, case2 => exp2 } *)
    | E_match (scrutinee, cases) ->
        let scrut_node = visit_exp builder scrutinee in
        (* Check if scrutinee is a rounding mode option (select_instr_or_fcsr_rm returns
           option(rounding_mode) but extractor returns the rm value directly).
           We need a validity check (rm <= 4) as the control signal instead of the rm value,
           because rm=0 (RNE) is valid but would be false as a boolean. *)
        let is_rm_option = match scrutinee with
          | E_aux (E_app (id, _), _) ->
              let fn = string_of_id id in
              fn = "select_instr_or_fcsr_rm" || fn = "encdec_rounding_mode_forwards"
          | _ -> false
        in
        let control_node = if is_rm_option then begin
          let four_lit = make_node ~display_name:(Some "4") ~value:(Some "4")
                                   ~bit_width:(Some 3) "literal" in
          let four_lit = add_node builder four_lit in
          let valid_node = make_node ~display_name:(Some "rm_valid")
                                     ~operator:(Some "<=") ~bit_width:(Some 1) "comparison" in
          let valid_node = add_node builder valid_node in
          connect builder scrut_node valid_node "operand";
          connect builder four_lit valid_node "operand";
          valid_node
        end else
          scrut_node
        in
        (* Create multiplexer node with unique name to avoid collisions when merged *)
        let match_idx = builder.match_counter in
        builder.match_counter <- builder.match_counter + 1;
        let match_name = if builder.instr_prefix <> "" then
          Printf.sprintf "%s_mux_%d" builder.instr_prefix match_idx
        else
          Printf.sprintf "mux_%d" match_idx
        in
        let match_node = make_node ~display_name:(Some match_name) ~operator:(Some "match") "multiplexer"
                        |> add_node builder in
        (* Control signal (scrutinee determines which case is selected) *)
        connect builder control_node match_node "control";

        (* Helper: recursively extract variable names from a pattern *)
        let rec extract_pattern_vars (P_aux (pat_aux, _)) =
          match pat_aux with
          | P_id id -> [string_of_id id]
          | P_typ (_, inner_pat) -> extract_pattern_vars inner_pat
          | P_app (_, pat_args) ->
              (* For Ok(data), Err(e), etc. - extract vars from arguments *)
              List.concat_map extract_pattern_vars pat_args
          | P_tuple pats ->
              List.concat_map extract_pattern_vars pats
          | P_lit _ -> []  (* Literals don't bind variables *)
          | P_wild -> []   (* Wildcard _ doesn't bind *)
          | _ -> []        (* Other patterns: return empty for now *)
        in

        (* Visit each case and create mux_input edges *)
        List.iteri (fun idx (Pat_aux (pat_aux, _)) ->
          match pat_aux with
          | Pat_exp (pat, exp) ->
              (* Extract and bind pattern variables to scrutinee *)
              let pattern_vars = extract_pattern_vars pat in
              List.iter (fun var_name ->
                let prefixed_var = prefix_local_name builder var_name in
                let var_node = make_node ~display_name:(Some prefixed_var) "var"
                              |> add_node builder in
                (* Bind pattern variable to scrutinee value (e.g., data = vmem_read result) *)
                connect builder scrut_node var_node "definition";
                Printf.printf "          Match: Bound pattern var '%s' (prefixed: %s) to scrutinee\n%!" var_name prefixed_var
              ) pattern_vars;

              (* Now visit body - it can reference pattern vars *)
              let case_node = visit_exp builder exp in
              (* mux_input edge FROM case result TO multiplexer, with input_index encoded in edge type *)
              connect builder case_node match_node (Printf.sprintf "mux_input:%d" idx)
          | Pat_when (pat, _guard, exp) ->
              (* Same for guarded patterns *)
              let pattern_vars = extract_pattern_vars pat in
              List.iter (fun var_name ->
                let prefixed_var = prefix_local_name builder var_name in
                let var_node = make_node ~display_name:(Some prefixed_var) "var"
                              |> add_node builder in
                connect builder scrut_node var_node "definition";
                Printf.printf "          Match: Bound pattern var '%s' (prefixed: %s) to scrutinee (guarded)\n%!" var_name prefixed_var
              ) pattern_vars;

              let case_node = visit_exp builder exp in
              connect builder case_node match_node (Printf.sprintf "mux_input:%d" idx)
        ) cases;
        match_node

    (* Field access: exp.field - treat as operation *)
    | E_field (exp, field) ->
        let exp_node = visit_exp builder exp in
        let field_name = string_of_id field in
        let field_node = make_node ~display_name:(Some ("." ^ field_name)) ~operator:(Some "field") "operation"
                        |> add_node builder in
        connect builder exp_node field_node "base";
        field_node

    (* Vector/List expressions - treat as concatenation operation *)
    | E_vector exps | E_list exps ->
        let elem_nodes = List.map (visit_exp builder) exps in
        let vec_node = make_node ~display_name:(Some "concat") ~operator:(Some "concat") "operation"
                      |> add_node builder in
        List.iter (fun elem ->
          connect builder elem vec_node "element"
        ) elem_nodes;
        vec_node

    (* Internal SAIL expressions - handle like E_assign or E_let *)
    | E_internal_plet (pat, bind_exp, body_exp) ->
        Printf.printf "        DEBUG: E_internal_plet detected\n%!";
        (* Visit the binding expression (e.g., riscv_f32Sqrt call) *)
        let bind_node = visit_exp builder bind_exp in
        (* Helper: check if a node is an FP tuple source (fp_operation itself,
           or a mux/ternary that selects between fp_operation nodes).
           When true, also widen all fp_operation inputs to packed width. *)
        let is_fp_tuple_and_widen (node : rg_node) =
          if node.node_type = "fp_operation" then true
          else begin
            let is_mux_or_ternary_edge (et : string) =
              et = "mux_input" || et = "ternary_true" || et = "ternary_false"
              || (String.length et > 10 && String.sub et 0 10 = "mux_input:") in
            let has_fp_input = List.exists (fun (e : rg_edge) ->
              e.target = node.id &&
              is_mux_or_ternary_edge e.edge_type &&
              List.exists (fun (n : rg_node) ->
                n.id = e.source && n.node_type = "fp_operation"
              ) builder.nodes
            ) builder.edges in
            if has_fp_input then begin
              List.iter (fun (e : rg_edge) ->
                if e.target = node.id &&
                   is_mux_or_ternary_edge e.edge_type then
                  builder.nodes <- List.map (fun (n : rg_node) ->
                    if n.id = e.source && n.node_type = "fp_operation" then
                      let vb = Option.value ~default:32 n.bit_width in
                      { n with bit_width = Some (5 + vb) }
                    else n
                  ) builder.nodes
              ) builder.edges;
              true
            end else false
          end
        in
        (* Bind pattern variables to the result *)
        let rec bind_pattern_vars (P_aux (pat_aux, _)) result_node =
          match pat_aux with
          | P_id id ->
              let name = string_of_id id in
              let prefixed_name = prefix_local_name builder name in
              rename_shadowed_vars prefixed_name;
              let var_node = make_node ~display_name:(Some prefixed_name) "var"
                            |> add_node builder in
              connect builder result_node var_node "definition";
              Printf.printf "        DEBUG: E_internal_plet bound '%s' (prefixed: %s)\n%!" name prefixed_name
          | P_typ (_, inner_pat) ->
              bind_pattern_vars inner_pat result_node
          | P_tuple pats ->
              (* When result_node is a concat/tuple from E_tuple, bind each pattern
                 variable to the corresponding element node, not the concat node. *)
              let elem_edges = List.filter (fun (e : rg_edge) ->
                e.target = result_node.id && e.edge_type = "element"
              ) builder.edges in
              let elem_sources = List.map (fun (e : rg_edge) ->
                match List.find_opt (fun (n : rg_node) -> n.id = e.source) builder.nodes with
                | Some n -> n
                | None -> result_node
              ) elem_edges in
              if List.length elem_sources = List.length pats && List.length pats > 0 then
                List.iter2 (fun sub_pat elem_node ->
                  bind_pattern_vars sub_pat elem_node
                ) pats elem_sources
              else if is_fp_tuple_and_widen result_node && List.length pats = 2 then begin
                (* FP operations return (flags, value) tuples.  The generator packs
                   {status_o[4:0], result_o} into the node's output wire.  We must
                   widen the node to 5+value_bits and create bit_slices so the
                   tuple elements map to the correct portions of the packed result. *)
                let value_bits = Option.value ~default:32 result_node.bit_width in
                let packed_width = 5 + value_bits in
                (* Widen result node (fp_operation or mux) to packed width *)
                let updated = { result_node with bit_width = Some packed_width } in
                builder.nodes <- List.map (fun (n : rg_node) ->
                  if n.id = result_node.id then updated else n) builder.nodes;
                (* Flags bit_slice: [packed_width-1 : value_bits]
                   Use instruction-prefixed + unique names to prevent merger collision *)
                let slice_uid = fresh_node_id () in
                let flags_name = if builder.instr_prefix <> "" then
                  Printf.sprintf "%s_fp_flags_%s" builder.instr_prefix slice_uid
                else Printf.sprintf "fp_flags_%s" slice_uid in
                let flags_slice = {
                  id = slice_uid; node_type = "bit_slice";
                  name = Some flags_name; display_name = Some flags_name;
                  operator = None; value = None; bit_width = Some 5;
                  is_arch_state = false; is_memory = false;
                  array_size = None; array_depth = None;
                  bitslice = Some (packed_width - 1, value_bits);
                  dimensions = None;
                } in
                builder.nodes <- flags_slice :: builder.nodes;
                builder.edges <- { id = fresh_edge_id (); source = result_node.id;
                  target = flags_slice.id; edge_type = "bit_access";
                  position = None; enable = None } :: builder.edges;
                (* Value bit_slice: [value_bits-1 : 0] *)
                let vslice_uid = fresh_node_id () in
                let value_name = if builder.instr_prefix <> "" then
                  Printf.sprintf "%s_fp_value_%s" builder.instr_prefix vslice_uid
                else Printf.sprintf "fp_value_%s" vslice_uid in
                let value_slice = {
                  id = vslice_uid; node_type = "bit_slice";
                  name = Some value_name; display_name = Some value_name;
                  operator = None; value = None; bit_width = Some value_bits;
                  is_arch_state = false; is_memory = false;
                  array_size = None; array_depth = None;
                  bitslice = Some (value_bits - 1, 0);
                  dimensions = None;
                } in
                builder.nodes <- value_slice :: builder.nodes;
                builder.edges <- { id = fresh_edge_id (); source = result_node.id;
                  target = value_slice.id; edge_type = "bit_access";
                  position = None; enable = None } :: builder.edges;
                (* Determine tuple element order from pattern names. *)
                let pat0_is_flags = match List.nth pats 0 with
                  | P_aux (P_id id, _) ->
                      let n = string_of_id id in
                      n = "fflags" || n = "flags"
                  | P_aux (P_typ (_, P_aux (P_id id, _)), _) ->
                      let n = string_of_id id in
                      n = "fflags" || n = "flags"
                  | _ -> true
                in
                if pat0_is_flags then begin
                  bind_pattern_vars (List.nth pats 0) flags_slice;
                  bind_pattern_vars (List.nth pats 1) value_slice
                end else begin
                  bind_pattern_vars (List.nth pats 0) value_slice;
                  bind_pattern_vars (List.nth pats 1) flags_slice
                end
              end
              else
                List.iter (fun sub_pat ->
                  bind_pattern_vars sub_pat result_node
                ) pats
          | P_wild -> ()  (* Wildcard doesn't bind *)
          | _ -> ()
        in
        bind_pattern_vars pat bind_node;
        (* Visit the body expression *)
        let body_node = visit_exp builder body_exp in
        (* Return the body result, but bind_node side effects are captured *)
        body_node

    | E_internal_return exp ->
        Printf.printf "        DEBUG: E_internal_return detected\n%!";
        visit_exp builder exp

    (* Type annotation/cast: just visit the inner expression *)
    | E_typ (_typ, exp) ->
        visit_exp builder exp

    (* Return: visit inner expression *)
    | E_return exp ->
        visit_exp builder exp

    (* Exit: creates a literal 0 (abort/unreachable path) *)
    | E_exit _exp ->
        make_node ~display_name:(Some "exit") ~value:(Some "0") "literal"
        |> add_node builder

    (* Mutable local variable: var x = init in body *)
    | E_var (lexp, init_exp, body_exp) ->
        let init_node = visit_exp builder init_exp in
        let _lhs_node = visit_lexp_assign builder lexp init_node in
        visit_exp builder body_exp

    (* Tuple: treat as concatenation *)
    | E_tuple exps ->
        let elem_nodes = List.map (visit_exp builder) exps in
        (match elem_nodes with
         | [single] -> single
         | _ ->
           let tup_node = make_node ~display_name:(Some "tuple") ~operator:(Some "concat") "operation"
                         |> add_node builder in
           List.iter (fun elem ->
             connect builder elem tup_node "element"
           ) elem_nodes;
           tup_node)

    (* Assert: visit condition for side effects, return unit literal *)
    | E_assert (cond_exp, _msg_exp) ->
        let _cond_node = visit_exp builder cond_exp in
        make_node ~display_name:(Some "assert") ~value:(Some "0") "literal"
        |> add_node builder

    (* Constraint: compile-time constant, emit literal 0 *)
    | E_constraint _ ->
        make_node ~display_name:(Some "const") ~value:(Some "0") "literal"
        |> add_node builder

    (* sizeof: evaluate type-level numeric expression to a constant *)
    | E_sizeof nexp ->
        let rec eval_nexp_local (Nexp_aux (nexp, _)) = match nexp with
          | Nexp_constant n -> Some (Big_int.to_int n)
          | Nexp_id id -> Hashtbl.find_opt builder.global_constants (string_of_id id)
          | Nexp_times (a, b) ->
            (match eval_nexp_local a, eval_nexp_local b with
             | Some a, Some b -> Some (a * b)
             | _ -> None)
          | Nexp_sum (a, b) ->
            (match eval_nexp_local a, eval_nexp_local b with
             | Some a, Some b -> Some (a + b)
             | _ -> None)
          | Nexp_minus (a, b) ->
            (match eval_nexp_local a, eval_nexp_local b with
             | Some a, Some b -> Some (a - b)
             | _ -> None)
          | Nexp_exp a ->
            (match eval_nexp_local a with
             | Some a -> Some (1 lsl a)
             | None -> None)
          | Nexp_neg a ->
            (match eval_nexp_local a with
             | Some a -> Some (-a)
             | None -> None)
          | _ -> None
        in
        let value_str = match eval_nexp_local nexp with
          | Some v ->
            Printf.printf "          E_sizeof: resolved to %d\n%!" v;
            string_of_int v
          | None ->
            Printf.printf "          E_sizeof: could not resolve, defaulting to 0\n%!";
            "0"
        in
        let width = try
          let v = int_of_string value_str in
          if v = 0 then 1
          else if v > 0 then
            let rec log2 x = if x <= 1 then 1 else 1 + log2 (x / 2) in
            log2 v
          else 32
        with _ -> 32 in
        make_node ~display_name:(Some value_str) ~value:(Some value_str)
                  ~bit_width:(Some width) "literal"
        |> add_node builder

    (* Vector append: concatenation of two vectors *)
    | E_vector_append (left, right) ->
        let left_node = visit_exp builder left in
        let right_node = visit_exp builder right in
        let concat_node = make_node ~display_name:(Some "concat") ~operator:(Some "concat") "operation"
                         |> add_node builder in
        connect builder left_node concat_node "left";
        connect builder right_node concat_node "right";
        concat_node

    (* Cons: list cons, treat like concat *)
    | E_cons (head, tail) ->
        let head_node = visit_exp builder head in
        let tail_node = visit_exp builder tail in
        let cons_node = make_node ~display_name:(Some "cons") ~operator:(Some "concat") "operation"
                       |> add_node builder in
        connect builder head_node cons_node "head";
        connect builder tail_node cons_node "tail";
        cons_node

    (* E_for: for loop — visit the body to capture side effects *)
    (* Full compile-time unrolling is not implemented; we run the body once *)
    | E_for (id, _from_exp, _to_exp, _step_exp, _order, body_exp) ->
        Printf.printf "          visit_exp: E_for(%s) — visiting body once\n%!" (string_of_id id);
        visit_exp builder body_exp

    (* E_loop: while/until loop — visit the body once *)
    | E_loop (_loop_type, _measure, _cond_exp, body_exp) ->
        Printf.printf "          visit_exp: E_loop — visiting body once\n%!";
        visit_exp builder body_exp

    (* E_struct: struct construction — visit each field value, return last *)
    | E_struct (_name, fexps) ->
        Printf.printf "          visit_exp: E_struct with %d fields\n%!" (List.length fexps);
        let field_nodes = List.map (fun (FE_aux (FE_fexp (_fid, exp), _)) ->
          visit_exp builder exp
        ) fexps in
        (match List.rev field_nodes with
        | last :: _ -> last
        | [] -> make_node ~display_name:(Some "_struct") "var" |> add_node builder)

    (* E_struct_update: struct field update — visit base and each field *)
    | E_struct_update (base_exp, fexps) ->
        Printf.printf "          visit_exp: E_struct_update with %d fields\n%!" (List.length fexps);
        let base_node = visit_exp builder base_exp in
        List.iter (fun (FE_aux (FE_fexp (_fid, exp), _)) ->
          ignore (visit_exp builder exp)
        ) fexps;
        base_node

    (* Default: create temporary variable for truly unhandled expression types *)
    | exp_type ->
        let type_name = match exp_type with
          | E_internal_value _ -> "E_internal_value"
          | E_throw _ -> "E_throw"
          | E_try _ -> "E_try"
          | E_ref _ -> "E_ref"
          | E_config _ -> "E_config"
          | E_internal_assume _ -> "E_internal_assume"
          | _ -> "E_unknown"
        in
        Printf.eprintf "Warning: unhandled SAIL expression type: %s\n" type_name;
        make_node ~display_name:(Some "_temp") "var"
        |> add_node builder

  and visit_lexp builder (LE_aux (lexp_aux, _)) =
    match lexp_aux with

    (* Array/vector write: X[rd] := value or IMEM[PC] := instr *)
    | LE_vector (vec_lexp, idx_exp) ->
        let vec_node = visit_lexp builder vec_lexp in
        let idx_node = visit_exp builder idx_exp in
        let access_name = match vec_lexp with
          | LE_aux (LE_id id, _) ->
              Printf.sprintf "%s[%s]" (string_of_id id)
                (Option.value ~default:"?" idx_node.display_name)
          | _ -> "array_access_wr"
        in
        let access_node = make_node ~display_name:(Some access_name)
                                   "array_access_wr"
                        |> add_node builder in
        connect builder vec_node access_node "array_base";
        connect builder idx_node access_node "array_index";
        access_node

    (* Bit range write: reg[high:low] := value *)
    | LE_vector_range (vec_lexp, high_exp, low_exp) ->
        let _vec_node = visit_lexp builder vec_lexp in
        let _high_node = visit_exp builder high_exp in
        let _low_node = visit_exp builder low_exp in
        let slice_name = "bit_slice_wr" in
        make_node ~display_name:(Some slice_name)
                 "bit_slice_wr"
        |> add_node builder

    (* Simple variable write: PC := ... *)
    | LE_id id ->
        let name = string_of_id id in
        make_node ~display_name:(Some name) ~is_arch_state:true "isa_state"
        |> add_node builder

    | _ ->
        Printf.eprintf "Warning: unhandled SAIL lvalue type\n";
        make_node ~display_name:(Some "_dest") "var"
        |> add_node builder

  (* Visit lvalue in assignment context - creates proper array_write nodes *)
  and visit_lexp_assign builder (LE_aux (lexp_aux, _)) rhs_node =
    Printf.printf "        DEBUG: visit_lexp_assign called\n%!";
    let lexp_type_str = match lexp_aux with
      | LE_id id -> Printf.sprintf "LE_id(%s)" (string_of_id id)
      | LE_vector _ -> "LE_vector"
      | LE_vector_range _ -> "LE_vector_range"
      | LE_vector_concat _ -> "LE_vector_concat"
      | LE_tuple _ -> "LE_tuple"
      | LE_app (id, _) -> Printf.sprintf "LE_app(%s)" (string_of_id id)
      | LE_field _ -> "LE_field"
      | _ -> "LE_other"
    in
    Printf.printf "        DEBUG: lexp type = %s\n%!" lexp_type_str;
    match lexp_aux with

    (* Array/vector write: X[rd] := value or IMEM[PC] := instr *)
    | LE_vector (vec_lexp, idx_exp) ->
        Printf.printf "        DEBUG: LE_vector detected\n%!";
        (* Get the base array node *)
        let base_name = match vec_lexp with
          | LE_aux (LE_id id, _) -> string_of_id id
          | _ -> "unknown_array"
        in

        (* Find or create the base array isa_state node *)
        let array_node = match find_node builder base_name with
          | Some node -> node
          | None ->
              (* Create array state node if it doesn't exist *)
              let dims = match base_name with
                | "X" | "x" | "rX" ->
                    Some [(31, 0); (4, 0)]  (* 32 registers, 32-bit each *)
                | "F" | "f" ->
                    Some [(31, 0); (4, 0)]  (* Float registers *)
                | _ -> None
              in
              make_node ~display_name:(Some base_name) ~is_arch_state:true
                       ~dimensions:dims "isa_state"
              |> add_node builder
        in

        (* Process index expression *)
        let idx_node = visit_exp builder idx_exp in

        (* Create array_write node *)
        let write_name = Printf.sprintf "%s[_]_wr" base_name in
        let write_node = make_node ~display_name:(Some write_name)
                                    "array_write"
                        |> add_node builder in

        (* Connect: array -> array_write (array_base edge) *)
        connect builder array_node write_node "array_base";

        (* Connect: index -> array_write (array_index edge) *)
        connect builder idx_node write_node "array_index";

        (* Connect: value -> array_write (assignment edge) *)
        connect builder rhs_node write_node "assignment";

        Printf.printf "        Created array_write node for %s\n%!" base_name;
        write_node

    (* Bit range write: reg[high:low] := value *)
    | LE_vector_range (vec_lexp, high_exp, low_exp) ->
        let _vec_node = visit_lexp builder vec_lexp in
        let _high_node = visit_exp builder high_exp in
        let _low_node = visit_exp builder low_exp in
        let slice_name = "bit_slice_wr" in
        let slice_node = make_node ~display_name:(Some slice_name)
                                   "bit_slice_wr"
                        |> add_node builder in
        connect builder rhs_node slice_node "assignment";
        slice_node

    (* Function application write: X(rd) := value (overloaded accessor) *)
    | LE_app (id, args) ->
        let func_name = string_of_id id in
        Printf.printf "        DEBUG: LE_app detected: %s with %d args\n%!" func_name (List.length args);

        (* Check if this is a register write accessor like X(rd) *)
        (match func_name, args with
        | ("X" | "wX" | "wX_bits"), [idx_exp] ->
            Printf.printf "        DEBUG: Recognized register write accessor %s\n%!" func_name;
            (* Create conditional array write: if (idx != 0) then rf[idx] = value *)
            (* This models RISC-V x0 semantics without inlining the 32-case match *)

            let idx_node = visit_exp builder idx_exp in

            (* Create array node *)
            let array_node = match find_node builder "rf" with
              | Some node -> node
              | None ->
                  let dims = Some [(31, 0); (4, 0)] in
                  make_node ~display_name:(Some "rf") ~is_arch_state:true
                           ~bit_width:(Some 32) ~dimensions:dims "isa_state"
                  |> add_node builder
            in

            (* Create comparison: idx != 0 *)
            let zero_lit = make_node ~display_name:(Some "0") ~value:(Some "0")
                                    ~bit_width:(Some 5) "literal"
                          |> add_node builder in
            let cmp_node = make_node ~display_name:(Some (Printf.sprintf "%s != 0"
                                      (Option.value ~default:"idx" idx_node.display_name)))
                                    ~operator:(Some "!=") "operation"
                          |> add_node builder in
            connect builder idx_node cmp_node "operand";
            connect builder zero_lit cmp_node "operand";

            (* Create conditional/multiplexer: if cmp then write else nop *)
            let cond_node = make_node ~display_name:(Some "if (idx != 0)")
                                     "conditional"
                           |> add_node builder in
            connect builder cmp_node cond_node "condition";

            (* Create array_write node *)
            let write_name = Printf.sprintf "rf[%s]_wr"
              (Option.value ~default:"_" idx_node.display_name) in
            let write_node = make_node ~display_name:(Some write_name)
                                       "array_write"
                            |> add_node builder in

            connect builder array_node write_node "array_base";
            connect builder idx_node write_node "array_index";
            connect builder rhs_node write_node "assignment";

            (* Connect write to conditional (true branch) *)
            connect builder write_node cond_node "true_branch";

            Printf.printf "        Created conditional array_write for %s\n%!" func_name;
            cond_node

        | _ ->
            Printf.printf "        DEBUG: Unknown LE_app pattern, treating as operation\n%!";
            let arg_nodes = List.map (visit_exp builder) args in
            let node = make_node ~display_name:(Some func_name) "operation"
                      |> add_node builder in
            List.iter (fun arg -> connect builder arg node "operand") arg_nodes;
            connect builder rhs_node node "assignment";
            node
        )

    (* Simple variable write: PC := ... OR individual register x1..x31 *)
    | LE_id id ->
        let name = string_of_id id in

        (* Check if this is a desugared register file write (x1...x31) *)
        let is_reg_pattern =
          String.length name >= 2 && name.[0] = 'x' &&
          (try let n = int_of_string (String.sub name 1 (String.length name - 1)) in
               n >= 1 && n <= 31
           with _ -> false)
        in

        if is_reg_pattern then begin
          (* This is x<N> from desugared register file - create array_write *)
          (* Extract register number *)
          let reg_num = int_of_string (String.sub name 1 (String.length name - 1)) in
          Printf.printf "        DEBUG: Detected desugared register write to %s (reg %d)\n%!" name reg_num;

          (* Find or create rf node *)
          let rf_node = match find_node builder "rf" with
            | Some node -> node
            | None ->
                let dims = Some [(31, 0); (4, 0)] in
                make_node ~display_name:(Some "rf") ~is_arch_state:true
                         ~bit_width:(Some 32) ~dimensions:dims "isa_state"
                |> add_node builder
          in

          (* Create array_access node (write) - matches ISA format *)
          let write_name = Printf.sprintf "rf[%d]_wr" reg_num in
          let write_node = make_node ~display_name:(Some write_name)
                                     "array_access"
                          |> add_node builder in

          (* Create literal node for the register index *)
          let idx_node = make_node ~display_name:(Some (string_of_int reg_num))
                                   ~value:(Some (string_of_int reg_num)) "literal"
                        |> add_node builder in

          connect builder rf_node write_node "array_base";
          connect builder idx_node write_node "array_index";
          connect builder rhs_node write_node "assignment";

          Printf.printf "        Created array_access node for desugared register %s\n%!" name;
          write_node
        end else begin
          (* Regular variable write (PC, etc.) *)
          let var_node = make_node ~display_name:(Some name) ~is_arch_state:true "isa_state"
                        |> add_node builder in
          connect builder rhs_node var_node "assignment";
          var_node
        end

    | _ ->
        Printf.eprintf "Warning: unhandled SAIL lvalue type in assignment\n";
        let dest_node = make_node ~display_name:(Some "_dest") "var"
                       |> add_node builder in
        connect builder rhs_node dest_node "assignment";
        dest_node

  (* Extract instruction name from pattern *)
  let rec extract_instr_name (P_aux (p_aux, _)) =
    match p_aux with
    | P_app (id, _) -> Some (string_of_id id)
    | P_as (pat, _) -> extract_instr_name pat
    | P_typ (_, pat) -> extract_instr_name pat
    | _ -> None

  (* Extract all identifier names from a pattern (recursively).
     Used to find inner constructor/enum names like FSGNJ_S in
     F_BIN_TYPE_F_S(rs2, rs1, rd, FSGNJ_S). *)
  let rec extract_all_pat_names (P_aux (p_aux, _)) =
    match p_aux with
    | P_app (id, pats) ->
        string_of_id id :: List.concat_map extract_all_pat_names pats
    | P_id id -> [string_of_id id]
    | P_as (pat, _) -> extract_all_pat_names pat
    | P_typ (_, pat) -> extract_all_pat_names pat
    | P_tuple pats -> List.concat_map extract_all_pat_names pats
    | P_vector pats -> List.concat_map extract_all_pat_names pats
    | P_list pats -> List.concat_map extract_all_pat_names pats
    | P_cons (p1, p2) -> extract_all_pat_names p1 @ extract_all_pat_names p2
    | P_var (pat, _) -> extract_all_pat_names pat
    | _ -> []

  (* Visit function clause and return instruction name if found *)
  let visit_funcl_with_name builder _func_name (FCL_aux (FCL_funcl (_id, pexp), _)) =
    match pexp with
    | Pat_aux (Pat_exp (pat, exp), _) ->
        let instr_name = extract_instr_name pat in
        ignore (visit_exp builder exp);
        instr_name
    | Pat_aux (Pat_when (pat, _guard, exp), _) ->
        let instr_name = extract_instr_name pat in
        ignore (visit_exp builder exp);
        instr_name

  (* Visit function clause without extracting name (legacy) *)
  let visit_funcl builder func_name clause =
    let _ = visit_funcl_with_name builder func_name clause in
    ()

  (* Visit top-level function definition with optional per-instruction extraction *)
  let visit_fundef_per_instruction (use_real_fetch : bool) (helper_graphs : (string, rg_graph) Hashtbl.t) ?(global_constants = Hashtbl.create 0) decode_mappings filter_func (FD_aux (FD_function (_rec, _tannot, clauses), _)) =
    (* Extract function name from first clause *)
    let func_name = match clauses with
      | FCL_aux (FCL_funcl (id, _), _) :: _ -> string_of_id id
      | _ -> "unknown"
    in

    (* Only process if matches filter (or no filter specified) *)
    match filter_func with
    | Some target when target <> func_name -> []
    | _ ->
        if func_name = "execute" then begin
          Printf.printf "  Processing execute function with %d clauses (per-instruction mode)\n%!" (List.length clauses);
          (* Process each clause into a separate graph *)
          let raw_graphs = List.concat_map (fun clause ->
            (* First extract instruction name and inner constructor names from pattern *)
            let (instr_name, inner_pat_names) = match clause with
              | FCL_aux (FCL_funcl (_id, pexp), _) ->
                  (match pexp with
                  | Pat_aux (Pat_exp (pat, _), _) ->
                      (extract_instr_name pat, extract_all_pat_names pat)
                  | Pat_aux (Pat_when (pat, _, _), _) ->
                      (extract_instr_name pat, extract_all_pat_names pat))
            in

            match instr_name with
            | Some name ->
                (* Helper: build one instruction graph with optional memory width context *)
                let build_one_variant variant_name mem_width is_unsigned encdec_clauses_for_variant =
                  let builder = create_with_helpers helper_graphs in
                  builder.instr_prefix <- String.lowercase_ascii variant_name;
                  builder.global_constants <- global_constants;
                  builder.memory_access_width <- mem_width;
                  builder.memory_is_unsigned <- is_unsigned;
                  add_architectural_state ~use_real_fetch builder;

                  if use_real_fetch then begin
                    match Hashtbl.find_opt helper_graphs "fetch" with
                    | Some fetch_graph ->
                        Printf.printf "    Inlining real fetch() for %s\n%!" variant_name;
                        _inline_function builder fetch_graph;
                        wire_fetch_function builder
                    | None ->
                        Printf.printf "    Warning: --use-real-fetch enabled but fetch function not found!\n%!"
                  end;

                  let decode_output_opt = (match encdec_clauses_for_variant with
                  | Some cl ->
                      Printf.printf "    Adding decode nodes for %s (%d clauses)\n%!" variant_name (List.length cl);
                      extract_decode_patterns builder variant_name cl
                  | None ->
                      Printf.printf "    No decode mapping found for %s\n%!" variant_name;
                      None) in

                  (* Special-case system instructions *)
                  let is_special_cased =
                    if name = "MRET" then (emit_mret_graph builder; true)
                    else if name = "SRET" then (emit_sret_graph builder; true)
                    else if name = "ECALL" then (emit_ecall_graph builder; true)
                    else if name = "WFI" then (emit_wfi_graph builder; true)
                    else if name = "SFENCE_VMA" then (emit_sfence_vma_graph builder; true)
                    else if name = "FENCEI" then (emit_fencei_graph builder; true)
                    else if name = "EBREAK" then (emit_ebreak_graph builder; true)
                    else false
                  in

                  if not is_special_cased then begin
                    ignore (visit_funcl_with_name builder func_name clause);
                    (match decode_output_opt with
                    | Some decode_output ->
                        (match find_node builder "op" with
                        | Some op_node_id -> connect builder decode_output op_node_id "value"
                        | None -> ())
                    | None -> ());
                    if name = "BTYPE" then wire_btype_parameters builder;
                    if is_store_variant variant_name then wire_store_stype_imm builder;
                    transform_pc_conditionals builder;
                    add_pc_increment builder;
                  end;
                  let graph = to_graph builder in
                  (variant_name, graph)
                in

                (* Check if this instruction should be split into per-variant graphs *)
                let should_split_mem = (name = "STORE" || name = "LOAD") in
                let should_split_fp_mem = (name = "STORE_FP" || name = "LOAD_FP") in
                let should_split_utype = (name = "UTYPE") in
                let all_encdec = Hashtbl.find_opt decode_mappings name in

                if should_split_mem then begin
                  (* SAIL uses a single parametric encdec clause with a word_width variable.
                     We create per-width variants explicitly, each using the same clause
                     but with different memory_access_width/memory_is_unsigned settings.
                     STORE: SB (funct3=000), SH (funct3=001), SW (funct3=010)
                     LOAD: LB (funct3=000), LH (001), LW (010), LBU (100), LHU (101) *)
                  let width_variants = if name = "STORE" then
                    [(1, false, "BYTE"); (2, false, "HALF"); (4, false, "WORD")]
                  else (* LOAD *)
                    [(1, false, "BYTE"); (1, true, "BYTE_UNSIGNED");
                     (2, false, "HALF"); (2, true, "HALF_UNSIGNED");
                     (4, false, "WORD")]
                  in
                  let variants = List.map (fun (width_bytes, is_unsigned, suffix) ->
                    let variant_name = Printf.sprintf "%s_%s" name suffix in
                    Printf.printf "    Splitting %s -> %s (width=%d bytes, unsigned=%b)\n%!"
                      name variant_name width_bytes is_unsigned;
                    let (_n, graph) = build_one_variant variant_name
                      (Some width_bytes) is_unsigned all_encdec in
                    (* Add funct3 decode constraint for this width variant.
                       RISC-V encoding: funct3 = instr[14:12]
                       STORE: funct3 = 0 @ width_enc  (BYTE=000, HALF=001, WORD=010)
                       LOAD:  funct3 = is_unsigned @ width_enc  (LB=000, LH=001, LW=010, LBU=100, LHU=101) *)
                    let width_enc = match width_bytes with 1 -> 0 | 2 -> 1 | 4 -> 2 | _ -> 0 in
                    let funct3 = if name = "LOAD" && is_unsigned then 4 + width_enc else width_enc in
                    let funct3_str = Printf.sprintf "0b%c%c%c"
                      (if funct3 land 4 <> 0 then '1' else '0')
                      (if funct3 land 2 <> 0 then '1' else '0')
                      (if funct3 land 1 <> 0 then '1' else '0') in
                    let graph_with_funct3 = { graph with
                      decode_constraints = graph.decode_constraints @ [{high_bit = 14; low_bit = 12; value = funct3_str; operator = "=="}]
                    } in
                    Some (variant_name, graph_with_funct3)
                  ) width_variants in
                  variants
                end else if should_split_fp_mem then begin
                  (* FP load/store uses the same funct3 width encoding as integer load/store
                     but without unsigned variants.
                     LOAD_FP:  FLH (funct3=001), FLW (funct3=010), FLD (funct3=011)
                     STORE_FP: FSH (funct3=001), FSW (funct3=010), FSD (funct3=011) *)
                  let width_variants =
                    [(2, "HALF"); (4, "WORD"); (8, "DOUBLE")]
                  in
                  let variants = List.map (fun (width_bytes, suffix) ->
                    let variant_name = Printf.sprintf "%s_%s" name suffix in
                    Printf.printf "    Splitting %s -> %s (width=%d bytes)\n%!"
                      name variant_name width_bytes;
                    let (_n, graph) = build_one_variant variant_name
                      (Some width_bytes) false all_encdec in
                    (* funct3 = instr[14:12]: HALF=001, WORD=010, DOUBLE=011 *)
                    let funct3 = match width_bytes with 2 -> 1 | 4 -> 2 | 8 -> 3 | _ -> 0 in
                    let funct3_str = Printf.sprintf "0b%c%c%c"
                      (if funct3 land 4 <> 0 then '1' else '0')
                      (if funct3 land 2 <> 0 then '1' else '0')
                      (if funct3 land 1 <> 0 then '1' else '0') in
                    (* For DOUBLE (8 bytes), upgrade frf and data path to 64-bit for D extension *)
                    let (upgraded_nodes, upgraded_edges) = if width_bytes = 8 then
                      let prefix = String.lowercase_ascii variant_name in
                      let is_store = (name = "STORE_FP") in
                      (* Find frf read node ID for stores *)
                      let frf_read_id = if is_store then
                        match List.find_opt (fun n ->
                          n.node_type = "array_access" &&
                          (n.bit_width = None || n.bit_width = Some 32) &&
                          (match n.display_name with
                           | Some dn -> String.length dn >= 4 && String.sub dn 0 4 = "frf["
                                        && (try let _ = Str.search_forward (Str.regexp_string "_rd") dn 0 in true with Not_found -> false)
                           | None -> false)
                        ) graph.nodes with
                        | Some n -> Some n.id
                        | None -> None
                      else None in
                      (* Find data var node ID for stores *)
                      let data_var_id = if is_store then
                        match List.find_opt (fun n ->
                          n.display_name = Some (prefix ^ "_data") &&
                          (n.node_type = "var" || n.node_type = "operation")
                        ) graph.nodes with
                        | Some n -> Some n.id
                        | None -> None
                      else None in
                      let nodes = List.map (fun n ->
                        (* Upgrade frf memory to 64-bit *)
                        if n.display_name = Some "frf" && n.node_type = "isa_state" then
                          { n with bit_width = Some 64; dimensions = Some [(63, 0); (4, 0)] }
                        (* Upgrade frf array access/write nodes to 64-bit *)
                        else if (n.node_type = "array_access" || n.node_type = "array_write") &&
                                (n.bit_width = None || n.bit_width = Some 32) &&
                                (match n.display_name with
                                 | Some dn -> String.length dn >= 4 && String.sub dn 0 4 = "frf["
                                 | None -> false) then
                          { n with bit_width = Some 64 }
                        (* Upgrade load result var *)
                        else if n.display_name = Some (prefix ^ "_result") &&
                                (n.bit_width = None || n.bit_width = Some 32) then
                          { n with bit_width = Some 64 }
                        (* Upgrade store data vars *)
                        else if is_store &&
                                (n.bit_width = None || n.bit_width = Some 32) &&
                                (n.display_name = Some (prefix ^ "_data") ||
                                 n.display_name = Some (prefix ^ "_Data")) then
                          { n with bit_width = Some 64 }
                        else n
                      ) graph.nodes in
                      (* For stores: rewire data path to bypass width-selection mux,
                         connecting frf read directly to data var (full 64-bit value) *)
                      let edges = if is_store then
                        match (frf_read_id, data_var_id) with
                        | (Some frf_id, Some data_id) ->
                            (* Remove edges TO data var from mux chain *)
                            let filtered = List.filter (fun e ->
                              not (e.target = data_id)
                            ) graph.edges in
                            (* Add direct edge from frf read to data var *)
                            filtered @ [{ id = fresh_edge_id (); source = frf_id;
                                          target = data_id; edge_type = "assignment";
                                          position = None; enable = None }]
                        | _ -> graph.edges
                      else graph.edges in
                      (nodes, edges)
                    else (graph.nodes, graph.edges) in
                    let graph_upgraded = { graph with nodes = upgraded_nodes; edges = upgraded_edges } in
                    let graph_with_funct3 = { graph_upgraded with
                      decode_constraints = graph_upgraded.decode_constraints @ [{high_bit = 14; low_bit = 12; value = funct3_str; operator = "=="}]
                    } in
                    Some (variant_name, graph_with_funct3)
                  ) width_variants in
                  variants
                end else if should_split_utype then begin
                  (* UTYPE has encdec_uop(op) which maps LUI->0b0110111, AUIPC->0b0010111.
                     Split into separate LUI and AUIPC graphs with explicit opcode constraints.
                     op=0 means LUI (result = offset), op=1 means AUIPC (result = pc + offset). *)
                  let utype_variants = [
                    ("LUI",   0b0110111, "0b0110111", 0);
                    ("AUIPC", 0b0010111, "0b0010111", 1);
                  ] in
                  let variants = List.map (fun (variant_name, _opcode_val, opcode_str, op_value) ->
                    Printf.printf "    Splitting %s -> %s (op=%d)\n%!" name variant_name op_value;
                    let (_n, graph) = build_one_variant variant_name
                      None false all_encdec in
                    (* Replace any existing opcode constraint with the specific one *)
                    let non_opcode = List.filter (fun c ->
                      not (c.low_bit = 0 && c.high_bit = 6)
                    ) graph.decode_constraints in
                    (* Wire the op constant: find the {prefix}_op node and connect a constant to it *)
                    let prefix = String.lowercase_ascii variant_name in
                    let op_node_name = prefix ^ "_op" in
                    let op_node_opt = List.find_opt (fun n ->
                      match n.display_name with
                      | Some dn -> dn = op_node_name || dn = "op"
                      | None -> false
                    ) graph.nodes in
                    let (extra_nodes, extra_edges) = match op_node_opt with
                    | Some op_node ->
                        let const_node = make_node
                          ~display_name:(Some (Printf.sprintf "%s_op_const" prefix))
                          ~value:(Some (string_of_int op_value))
                          ~bit_width:(Some 1)
                          "literal" in
                        let edge = { id = fresh_edge_id (); source = const_node.id;
                                     target = op_node.id; edge_type = "value";
                                     position = None; enable = None } in
                        Printf.printf "      Wired %s = %d\n%!" op_node_name op_value;
                        ([const_node], [edge])
                    | None ->
                        Printf.printf "      Warning: could not find op node '%s'\n%!" op_node_name;
                        ([], [])
                    in
                    let graph_with_op = {
                      nodes = graph.nodes @ extra_nodes;
                      edges = graph.edges @ extra_edges;
                      decode_constraints = non_opcode @ [{high_bit = 6; low_bit = 0; value = opcode_str; operator = "=="}]
                    } in
                    Some (variant_name, graph_with_op)
                  ) utype_variants in
                  variants
                end else if name = "MUL" then begin
                  (* M-extension MUL has 4 variants via mul_op struct:
                     MUL (funct3=000), MULH (001), MULHSU (010), MULHU (011).
                     Split into 4 separate graphs with m_ext_variant set. *)
                  let mul_variants = [
                    ("MUL",    "0b000", "mul");
                    ("MULH",   "0b001", "mulh");
                    ("MULHSU", "0b010", "mulhsu");
                    ("MULHU",  "0b011", "mulhu");
                  ] in
                  let variants = List.map (fun (variant_name, funct3_str, m_variant) ->
                    Printf.printf "    Splitting %s -> %s (funct3=%s)\n%!" name variant_name funct3_str;
                    let builder = create_with_helpers helper_graphs in
                    builder.instr_prefix <- String.lowercase_ascii variant_name;
                    builder.global_constants <- global_constants;
                    builder.m_ext_variant <- Some m_variant;
                    add_architectural_state ~use_real_fetch builder;
                    let decode_output_opt = (match all_encdec with
                    | Some cl ->
                        Printf.printf "    Adding decode nodes for %s (%d clauses)\n%!" variant_name (List.length cl);
                        extract_decode_patterns builder variant_name cl
                    | None ->
                        Printf.printf "    No decode mapping found for %s\n%!" variant_name;
                        None) in
                    ignore (visit_funcl_with_name builder func_name clause);
                    (match decode_output_opt with
                    | Some decode_output ->
                        (match find_node builder "op" with
                        | Some op_node_id -> connect builder decode_output op_node_id "value"
                        | None -> ())
                    | None -> ());
                    transform_pc_conditionals builder;
                    add_pc_increment builder;
                    let graph = to_graph builder in
                    let graph_with_funct3 = { graph with
                      decode_constraints = graph.decode_constraints @
                        [{high_bit = 14; low_bit = 12; value = funct3_str; operator = "=="}]
                    } in
                    Some (variant_name, graph_with_funct3)
                  ) mul_variants in
                  variants

                end else if name = "DIV" then begin
                  (* M-extension DIV has 2 variants: DIV (funct3=100), DIVU (funct3=101).
                     Split into signed and unsigned variants. Wire is_unsigned constant. *)
                  let div_variants = [
                    ("DIV",  "0b100", "div",  false);
                    ("DIVU", "0b101", "divu", true);
                  ] in
                  let variants = List.map (fun (variant_name, funct3_str, m_variant, is_unsigned) ->
                    Printf.printf "    Splitting %s -> %s (funct3=%s, unsigned=%b)\n%!"
                      name variant_name funct3_str is_unsigned;
                    let builder = create_with_helpers helper_graphs in
                    builder.instr_prefix <- String.lowercase_ascii variant_name;
                    builder.global_constants <- global_constants;
                    builder.m_ext_variant <- Some m_variant;
                    add_architectural_state ~use_real_fetch builder;
                    let decode_output_opt = (match all_encdec with
                    | Some cl ->
                        extract_decode_patterns builder variant_name cl
                    | None -> None) in
                    ignore (visit_funcl_with_name builder func_name clause);
                    (match decode_output_opt with
                    | Some decode_output ->
                        (match find_node builder "op" with
                        | Some op_node_id -> connect builder decode_output op_node_id "value"
                        | None -> ())
                    | None -> ());
                    transform_pc_conditionals builder;
                    add_pc_increment builder;
                    let graph = to_graph builder in
                    (* Wire is_unsigned constant to the {prefix}_is_unsigned node *)
                    let prefix = String.lowercase_ascii variant_name in
                    let is_unsigned_node_name = prefix ^ "_is_unsigned" in
                    let is_unsigned_node_opt = List.find_opt (fun n ->
                      match n.display_name with
                      | Some dn -> dn = is_unsigned_node_name || dn = "is_unsigned"
                      | None -> false
                    ) graph.nodes in
                    let (extra_nodes, extra_edges) = match is_unsigned_node_opt with
                    | Some iu_node ->
                        let const_val = if is_unsigned then "1" else "0" in
                        let const_node = make_node
                          ~display_name:(Some (Printf.sprintf "%s_unsigned_const" prefix))
                          ~value:(Some const_val)
                          ~bit_width:(Some 1)
                          "literal" in
                        let edge = { id = fresh_edge_id (); source = const_node.id;
                                     target = iu_node.id; edge_type = "value";
                                     position = None; enable = None } in
                        Printf.printf "      Wired %s = %s\n%!" is_unsigned_node_name const_val;
                        ([const_node], [edge])
                    | None ->
                        Printf.printf "      Warning: could not find is_unsigned node '%s'\n%!" is_unsigned_node_name;
                        ([], [])
                    in
                    let graph_with_extras = {
                      nodes = graph.nodes @ extra_nodes;
                      edges = graph.edges @ extra_edges;
                      decode_constraints = graph.decode_constraints @
                        [{high_bit = 14; low_bit = 12; value = funct3_str; operator = "=="}]
                    } in
                    Some (variant_name, graph_with_extras)
                  ) div_variants in
                  variants

                end else if name = "REM" then begin
                  (* M-extension REM has 2 variants: REM (funct3=110), REMU (funct3=111).
                     Same structure as DIV splitting. *)
                  let rem_variants = [
                    ("REM",  "0b110", "rem",  false);
                    ("REMU", "0b111", "remu", true);
                  ] in
                  let variants = List.map (fun (variant_name, funct3_str, m_variant, is_unsigned) ->
                    Printf.printf "    Splitting %s -> %s (funct3=%s, unsigned=%b)\n%!"
                      name variant_name funct3_str is_unsigned;
                    let builder = create_with_helpers helper_graphs in
                    builder.instr_prefix <- String.lowercase_ascii variant_name;
                    builder.global_constants <- global_constants;
                    builder.m_ext_variant <- Some m_variant;
                    add_architectural_state ~use_real_fetch builder;
                    let decode_output_opt = (match all_encdec with
                    | Some cl ->
                        extract_decode_patterns builder variant_name cl
                    | None -> None) in
                    ignore (visit_funcl_with_name builder func_name clause);
                    (match decode_output_opt with
                    | Some decode_output ->
                        (match find_node builder "op" with
                        | Some op_node_id -> connect builder decode_output op_node_id "value"
                        | None -> ())
                    | None -> ());
                    transform_pc_conditionals builder;
                    add_pc_increment builder;
                    let graph = to_graph builder in
                    (* Wire is_unsigned constant *)
                    let prefix = String.lowercase_ascii variant_name in
                    let is_unsigned_node_name = prefix ^ "_is_unsigned" in
                    let is_unsigned_node_opt = List.find_opt (fun n ->
                      match n.display_name with
                      | Some dn -> dn = is_unsigned_node_name || dn = "is_unsigned"
                      | None -> false
                    ) graph.nodes in
                    let (extra_nodes, extra_edges) = match is_unsigned_node_opt with
                    | Some iu_node ->
                        let const_val = if is_unsigned then "1" else "0" in
                        let const_node = make_node
                          ~display_name:(Some (Printf.sprintf "%s_unsigned_const" prefix))
                          ~value:(Some const_val)
                          ~bit_width:(Some 1)
                          "literal" in
                        let edge = { id = fresh_edge_id (); source = const_node.id;
                                     target = iu_node.id; edge_type = "value";
                                     position = None; enable = None } in
                        Printf.printf "      Wired %s = %s\n%!" is_unsigned_node_name const_val;
                        ([const_node], [edge])
                    | None ->
                        Printf.printf "      Warning: could not find is_unsigned node '%s'\n%!" is_unsigned_node_name;
                        ([], [])
                    in
                    let graph_with_extras = {
                      nodes = graph.nodes @ extra_nodes;
                      edges = graph.edges @ extra_edges;
                      decode_constraints = graph.decode_constraints @
                        [{high_bit = 14; low_bit = 12; value = funct3_str; operator = "=="}]
                    } in
                    Some (variant_name, graph_with_extras)
                  ) rem_variants in
                  variants

                end else if name = "F_BIN_TYPE_X_S" || name = "F_BIN_TYPE_X_D" || name = "F_BIN_TYPE_X_H"
                         || name = "F_BIN_X_TYPE_D" || name = "F_BIN_X_TYPE_H" then begin
                  (* FP comparison instruction types have separate execute clauses
                     for FEQ/FLT/FLE that all write to the same output variables.
                     Split into separate instruction types with per-clause funct3.
                     Determine suffix FIRST from inner_pat_names so we can build
                     with unique prefix to avoid Verilog signal name collisions. *)
                  let has_inner sub = List.exists (fun n ->
                    let len_sub = String.length sub in
                    let len_n = String.length n in
                    len_n >= len_sub &&
                    (let found = ref false in
                     for i = 0 to len_n - len_sub do
                       if String.sub n i len_sub = sub then found := true
                     done; !found)
                  ) inner_pat_names in
                  let (suffix, funct3_str) =
                    if has_inner "FEQ" then ("EQ", "0b010")
                    else if has_inner "FLT" then ("LT", "0b001")
                    else if has_inner "FLE" then ("LE", "0b000")
                    else ("UNKNOWN", "0b000")
                  in
                  let vname = Printf.sprintf "%s_%s" name suffix in
                  let (_, graph) = build_one_variant vname None false all_encdec in
                  Printf.printf "    Splitting %s -> %s (funct3=%s)\n%!" name vname funct3_str;
                  let g = { graph with
                    decode_constraints = graph.decode_constraints @
                      [{high_bit=14; low_bit=12; value=funct3_str; operator="=="}]
                  } in
                  [Some (vname, g)]

                end else if name = "F_UN_RM_FX_TYPE_S" || name = "F_UN_RM_FX_TYPE_D" || name = "F_UN_RM_FX_TYPE_H" then begin
                  (* Float-to-int conversion types have clauses for W/WU/L/LU
                     distinguished by rs2 field (bits [24:20]).
                     L/LU are RV64-only, skip them for RV32.
                     Determine suffix FIRST from inner_pat_names for unique prefix. *)
                  let has_inner sub = List.exists (fun n ->
                    let len_sub = String.length sub in
                    let len_n = String.length n in
                    len_n >= len_sub &&
                    (let found = ref false in
                     for i = 0 to len_n - len_sub do
                       if String.sub n i len_sub = sub then found := true
                     done; !found)
                  ) inner_pat_names in
                  (* Skip L/LU clauses (RV64-only) — "FCVT_L" substring matches both *)
                  if has_inner "FCVT_L" then begin
                    Printf.printf "    Skipping RV64-only clause for %s (inner=%s)\n%!" name (String.concat "," inner_pat_names);
                    []
                  end else begin
                    let (suffix, rs2_str) =
                      if has_inner "WU" then ("WU", "0b00001")
                      else ("W", "0b00000")
                    in
                    let vname = Printf.sprintf "%s_%s" name suffix in
                    let (_, graph) = build_one_variant vname None false all_encdec in
                    Printf.printf "    Splitting %s -> %s (rs2=%s)\n%!" name vname rs2_str;
                    let g = { graph with
                      decode_constraints = graph.decode_constraints @
                        [{high_bit=24; low_bit=20; value=rs2_str; operator="=="}]
                    } in
                    [Some (vname, g)]
                  end

                end else if name = "F_UN_RM_XF_TYPE_S" || name = "F_UN_RM_XF_TYPE_D" || name = "F_UN_RM_XF_TYPE_H" then begin
                  (* Int-to-float conversion types — same pattern as float-to-int.
                     L/LU are RV64-only, skip them for RV32.
                     For XF types, inner names are FCVT_S_L/FCVT_S_LU (L at end).
                     Determine suffix FIRST from inner_pat_names for unique prefix. *)
                  let has_inner sub = List.exists (fun n ->
                    let len_sub = String.length sub in
                    let len_n = String.length n in
                    len_n >= len_sub &&
                    (let found = ref false in
                     for i = 0 to len_n - len_sub do
                       if String.sub n i len_sub = sub then found := true
                     done; !found)
                  ) inner_pat_names in
                  let ends_with_l_or_lu = List.exists (fun n ->
                    let len = String.length n in
                    (len >= 2 && String.sub n (len - 2) 2 = "_L") ||
                    (len >= 3 && String.sub n (len - 3) 3 = "_LU")
                  ) inner_pat_names in
                  (* Skip L/LU clauses (RV64-only) *)
                  if has_inner "FCVT_L" || ends_with_l_or_lu then begin
                    Printf.printf "    Skipping RV64-only clause for %s (inner=%s)\n%!" name (String.concat "," inner_pat_names);
                    []
                  end else begin
                    let (suffix, rs2_str) =
                      if has_inner "WU" then ("WU", "0b00001")
                      else ("W", "0b00000")
                    in
                    let vname = Printf.sprintf "%s_%s" name suffix in
                    let (_, graph) = build_one_variant vname None false all_encdec in
                    Printf.printf "    Splitting %s -> %s (rs2=%s)\n%!" name vname rs2_str;
                    let g = { graph with
                      decode_constraints = graph.decode_constraints @
                        [{high_bit=24; low_bit=20; value=rs2_str; operator="=="}]
                    } in
                    [Some (vname, g)]
                  end

                end else if name = "F_BIN_RM_TYPE_S" || name = "F_BIN_RM_TYPE_D" then begin
                  (* F_BIN_RM_TYPE_S/D has a single execute clause with an internal
                     match on 'op' that dispatches to fp_add/fp_sub/fp_mul/fp_div
                     through a multiplexer. Split into 4 separate instruction types,
                     each pruned to contain only one fp_operation.
                     Operation code in bits[31:27]: ADD=00000, SUB=00001, MUL=00010, DIV=00011
                     (bits[26:25] is the fmt field, already constrained by existing decode) *)
                  let d_suffix = if name = "F_BIN_RM_TYPE_D" then "_d" else "" in
                  let variants = [
                    ("FADD", "fp_add" ^ d_suffix, "0b00000");
                    ("FSUB", "fp_sub" ^ d_suffix, "0b00001");
                    ("FMUL", "fp_mul" ^ d_suffix, "0b00010");
                    ("FDIV", "fp_div" ^ d_suffix, "0b00011");
                  ] in
                  let results = List.concat_map (fun (suffix, target_op, funct7_str) ->
                    let vname = Printf.sprintf "%s_%s" name suffix in
                    let (_, graph) = build_one_variant vname None false all_encdec in
                    (* Find ALL multiplexer nodes *)
                    let all_mux_nodes = List.filter (fun (n : rg_node) ->
                      n.node_type = "multiplexer"
                    ) graph.nodes in
                    Printf.printf "      DEBUG: %s has %d multiplexer node(s)\n%!" vname (List.length all_mux_nodes);
                    (* Find the correct mux: the one that has an fp_operation as a mux_input source *)
                    let fp_op_ids = List.filter_map (fun (n : rg_node) ->
                      if n.node_type = "fp_operation" then Some n.id else None
                    ) graph.nodes in
                    let mux_node_opt = List.find_opt (fun (n : rg_node) ->
                      n.node_type = "multiplexer" &&
                      List.exists (fun (e : rg_edge) ->
                        e.target = n.id &&
                        (let et = e.edge_type in
                         et = "mux_input" ||
                         (String.length et > 10 && String.sub et 0 10 = "mux_input:")) &&
                        List.mem e.source fp_op_ids
                      ) graph.edges
                    ) graph.nodes in
                    (match mux_node_opt with
                    | None ->
                        Printf.printf "    Warning: no FP-input multiplexer in %s, using as-is\n%!" vname;
                        [Some (vname, graph)]
                    | Some mux_node ->
                        Printf.printf "      DEBUG: selected mux=%s\n%!" mux_node.id;
                        (* Find the fp_operation to keep *)
                        let kept_op_opt = List.find_opt (fun (n : rg_node) ->
                          n.node_type = "fp_operation" && n.operator = Some target_op
                        ) graph.nodes in
                        (match kept_op_opt with
                        | None ->
                            Printf.printf "    Warning: no %s op in %s\n%!" target_op vname;
                            [Some (vname, graph)]
                        | Some kept_node ->
                            (* Nodes to remove: other fp_ops *)
                            let other_fp_ops = List.filter (fun (n : rg_node) ->
                              n.node_type = "fp_operation" && n.id <> kept_node.id
                            ) graph.nodes in
                            (* Find mux output targets (fflags, rd_val) - check all edge types *)
                            let mux_outputs = List.filter_map (fun (e : rg_edge) ->
                              if e.source = mux_node.id &&
                                 (e.edge_type = "assignment" || e.edge_type = "definition" || e.edge_type = "value") then
                                Some e.target
                              else None
                            ) graph.edges in
                            (* Find the op var (has control edge to mux) *)
                            let op_var_opt = List.find_opt (fun (n : rg_node) ->
                              List.exists (fun (e : rg_edge) ->
                                e.source = n.id && e.target = mux_node.id && e.edge_type = "control"
                              ) graph.edges
                            ) graph.nodes in
                            (* Find variant var nodes (receive any edge from op var, not just "assignment") *)
                            let variant_var_ids = match op_var_opt with
                              | Some op_var ->
                                  List.filter_map (fun (e : rg_edge) ->
                                    if e.source = op_var.id &&
                                       e.target <> mux_node.id &&
                                       (e.edge_type = "assignment" || e.edge_type = "definition" || e.edge_type = "value") then
                                      Some e.target
                                    else None
                                  ) graph.edges
                              | None -> []
                            in
                            (* Collect all node IDs to remove *)
                            let remove_ids = Hashtbl.create 16 in
                            List.iter (fun (n : rg_node) -> Hashtbl.replace remove_ids n.id true) other_fp_ops;
                            Hashtbl.replace remove_ids mux_node.id true;
                            List.iter (fun vid -> Hashtbl.replace remove_ids vid true) variant_var_ids;
                            (match op_var_opt with
                             | Some op_var -> Hashtbl.replace remove_ids op_var.id true
                             | None -> ());
                            (* Also remove the op bitslice node if present *)
                            List.iter (fun (n : rg_node) ->
                              if n.node_type = "bit_slice" &&
                                 (match op_var_opt with
                                  | Some op_var ->
                                      List.exists (fun (e : rg_edge) ->
                                        e.source = n.id && e.target = op_var.id
                                      ) graph.edges
                                  | None -> false) then
                                Hashtbl.replace remove_ids n.id true
                            ) graph.nodes;
                            (* Check if the E_let handler already created bit_slices
                               from the mux (via is_fp_tuple_and_widen).  If so, we can
                               just redirect them to the kept fp_operation instead of
                               creating new bit_slices.  This avoids orphaning them when
                               the mux is removed. *)
                            let existing_mux_bitslices = List.filter (fun (e : rg_edge) ->
                              e.source = mux_node.id && e.edge_type = "bit_access"
                            ) graph.edges in
                            let has_existing_bitslices = existing_mux_bitslices <> [] in
                            (* Filter nodes and edges *)
                            let new_nodes = List.filter (fun (n : rg_node) ->
                              not (Hashtbl.mem remove_ids n.id)
                            ) graph.nodes in
                            let new_edges = List.filter (fun (e : rg_edge) ->
                              not (Hashtbl.mem remove_ids e.source) &&
                              not (Hashtbl.mem remove_ids e.target)
                            ) graph.edges in
                            let (new_output_edges, extra_nodes, updated_nodes) =
                              if has_existing_bitslices then begin
                                (* Redirect existing bit_slices from mux to kept fp_op.
                                   The bit_access edges were filtered out (source was mux),
                                   so create new ones pointing to the kept fp_op.
                                   Note: the fp_op was already widened to packed width by
                                   is_fp_tuple_and_widen, so do NOT re-widen. *)
                                let redirect_edges = List.map (fun (e : rg_edge) ->
                                  { e with id = fresh_edge_id (); source = kept_node.id }
                                ) existing_mux_bitslices in
                                (redirect_edges, [], None)
                              end else begin
                            (* FP operations return (flags, value) tuples packed as
                               {status_o[4:0], result_o[value_bits-1:0]}.  Identify
                               which mux output is fflags vs rd_val by display_name,
                               then route through bit_slices of the packed result. *)
                            let value_bits = Option.value ~default:32 kept_node.bit_width in
                            let packed_width = 5 + value_bits in
                            (* Classify outputs as flags or value by name *)
                            let is_flags_target tid =
                              match List.find_opt (fun (n : rg_node) -> n.id = tid) new_nodes with
                              | Some n ->
                                  let dn = Option.value ~default:"" n.display_name in
                                  let has s = try let _ = Str.search_forward (Str.regexp_string s) dn 0 in true
                                              with Not_found -> false in
                                  has "fflags" || has "flags"
                              | None -> false
                            in
                            let (flags_targets, value_targets) = List.partition is_flags_target mux_outputs in
                            if flags_targets <> [] && value_targets <> [] then begin
                                (* Widen fp_operation to packed width *)
                                let updated_kept = { kept_node with bit_width = Some packed_width } in
                                (* Create flags bit_slice *)
                                let flags_id = fresh_node_id () in
                                let flags_slice = {
                                  id = flags_id; node_type = "bit_slice";
                                  name = Some "fp_flags"; display_name = Some "fp_flags";
                                  operator = None; value = None; bit_width = Some 5;
                                  is_arch_state = false; is_memory = false;
                                  array_size = None; array_depth = None;
                                  bitslice = Some (packed_width - 1, value_bits);
                                  dimensions = None;
                                } in
                                (* Create value bit_slice *)
                                let value_id = fresh_node_id () in
                                let value_slice = {
                                  id = value_id; node_type = "bit_slice";
                                  name = Some "fp_value"; display_name = Some "fp_value";
                                  operator = None; value = None; bit_width = Some value_bits;
                                  is_arch_state = false; is_memory = false;
                                  array_size = None; array_depth = None;
                                  bitslice = Some (value_bits - 1, 0);
                                  dimensions = None;
                                } in
                                (* Edges: fp_op -> bit_slices, bit_slices -> targets *)
                                let edges = [
                                  { id = fresh_edge_id (); source = kept_node.id;
                                    target = flags_id; edge_type = "bit_access"; position = None; enable = None };
                                  { id = fresh_edge_id (); source = kept_node.id;
                                    target = value_id; edge_type = "bit_access"; position = None; enable = None };
                                ] @ List.map (fun tid ->
                                  { id = fresh_edge_id (); source = flags_id;
                                    target = tid; edge_type = "assignment"; position = None; enable = None }
                                ) flags_targets
                                @ List.map (fun tid ->
                                  { id = fresh_edge_id (); source = value_id;
                                    target = tid; edge_type = "assignment"; position = None; enable = None }
                                ) value_targets in
                                (edges, [flags_slice; value_slice], Some updated_kept)
                              end else begin
                                (* Fallback: connect fp_op directly to all outputs *)
                                let edges = List.map (fun target_id ->
                                  { id = fresh_edge_id ();
                                    source = kept_node.id;
                                    target = target_id;
                                    edge_type = "assignment";
                                    position = None; enable = None }
                                ) mux_outputs in
                                (edges, [], None)
                              end
                              end (* has_existing_bitslices else *)
                            in
                            (* Apply node width update if needed *)
                            let final_nodes = match updated_nodes with
                              | Some upd ->
                                  List.map (fun (n : rg_node) ->
                                    if n.id = kept_node.id then upd else n
                                  ) new_nodes @ extra_nodes
                              | None -> new_nodes @ extra_nodes
                            in
                            (* Add operation code decode constraint (bits[31:27])
                               We use [31:27] not full funct7 [31:25] because bits[26:25]
                               is the format field (S=00, D=01) already in existing decode *)
                            let new_decode = graph.decode_constraints @
                              [{high_bit=31; low_bit=27; value=funct7_str; operator="=="}] in
                            Printf.printf "    Split %s -> %s (kept %s, removed %d nodes, op=%s)\n%!"
                              name vname target_op (Hashtbl.length remove_ids) funct7_str;
                            let g = {
                              nodes = final_nodes;
                              edges = new_edges @ new_output_edges;
                              decode_constraints = new_decode } in
                            [Some (vname, g)]))
                  ) variants in
                  results

                end else if name = "F_BIN_TYPE_F_S" || name = "F_BIN_TYPE_F_D" || name = "F_BIN_TYPE_F_H"
                         || name = "F_BIN_F_TYPE_D" || name = "F_BIN_F_TYPE_H" then begin
                  (* FP binary operations: FSGNJ/FSGNJN/FSGNJX (funct7=0010000) +
                     FMIN/FMAX (funct7=0010100). These have separate execute clauses.
                     Use the inner constructor name from the SAIL AST pattern to
                     determine the variant (e.g., FSGNJ_S, FMIN_S, etc.).
                     Determine suffix FIRST so we can build with unique prefix. *)
                  let has_inner sub = List.exists (fun n ->
                    let len_sub = String.length sub in
                    let len_n = String.length n in
                    len_n >= len_sub &&
                    (let found = ref false in
                     for i = 0 to len_n - len_sub do
                       if String.sub n i len_sub = sub then found := true
                     done; !found)
                  ) inner_pat_names in
                  let is_fmin = has_inner "FMIN" in
                  let is_fmax = has_inner "FMAX" in
                  (* Use bits[31:27] for operation code, not full funct7 [31:25],
                     because [26:25] is the fmt field (S=00, D=01) already in decode *)
                  let (suffix, op_code_str, funct3_str) =
                    if is_fmin then ("MIN", "0b00101", "0b000")
                    else if is_fmax then ("MAX", "0b00101", "0b001")
                    else if has_inner "FSGNJN" then ("SGNJN", "0b00100", "0b001")
                    else if has_inner "FSGNJX" then ("SGNJX", "0b00100", "0b010")
                    else ("SGNJ", "0b00100", "0b000")
                  in
                  let vname = Printf.sprintf "%s_%s" name suffix in
                  (* Build graph with unique variant name as prefix *)
                  let (_, graph) = build_one_variant vname None false all_encdec in
                  (* For FMIN/FMAX: SAIL implements these with fp_le comparison + conditional
                     selection, but the cvfpu has native MIN/MAX operations. Transform the graph:
                     1. Change fp_le node to fp_min/fp_max
                     2. Wire fp_min/fp_max result directly to rd_val_S, bypassing conditionals *)
                  let is_d_type = (name = "F_BIN_TYPE_F_D" || name = "F_BIN_F_TYPE_D") in
                  let graph = if is_fmin || is_fmax then begin
                    let d_sfx = if is_d_type then "_d" else "" in
                    let target_op = (if is_fmin then "fp_min" else "fp_max") ^ d_sfx in
                    (* Find the fp_le node (may be fp_le or fp_le_d) *)
                    let fle_node_opt = List.find_opt (fun (n : rg_node) ->
                      n.node_type = "fp_operation" &&
                      (n.operator = Some "fp_le" || n.operator = Some "fp_le_d")
                    ) graph.nodes in
                    match fle_node_opt with
                    | Some fle_node ->
                        Printf.printf "      Transforming %s -> %s (node %s)\n%!" (Option.value fle_node.operator ~default:"?") target_op fle_node.id;
                        (* Change the operator to fp_min/fp_max *)
                        let new_fle = { fle_node with
                          operator = Some target_op;
                          display_name = Some target_op
                        } in
                        let nodes = List.map (fun (n : rg_node) ->
                          if n.id = fle_node.id then new_fle else n
                        ) graph.nodes in
                        (* Find the rd_val node (var where FRF write data comes from).
                           It's the var node whose display_name ends with "_rd_val_S" or "_rd_val_D" *)
                        let rd_val_opt = List.find_opt (fun (n : rg_node) ->
                          n.node_type = "var" &&
                          (match n.display_name with
                           | Some dn ->
                               let len = String.length dn in
                               let ends_with suffix =
                                 let slen = String.length suffix in
                                 len >= slen && String.sub dn (len - slen) slen = suffix
                               in
                               ends_with "rd_val_S" || ends_with "rd_val_D" || ends_with "rd_val_H"
                           | None -> false)
                        ) graph.nodes in
                        (match rd_val_opt with
                        | Some rd_val_node ->
                            Printf.printf "      Rewiring %s -> %s\n%!" target_op (Option.value rd_val_node.display_name ~default:"?");
                            (* Remove the comparison result assignment (keep fflags assignment).
                               The comparison result goes to a var that feeds ternary_ops.
                               The fflags result goes to a var named *fflags*. *)
                            let edges = List.filter (fun (e : rg_edge) ->
                              if e.source = fle_node.id && e.edge_type = "assignment" then
                                (* Keep only the fflags edge *)
                                let target_node = List.find_opt (fun (n : rg_node) ->
                                  n.id = e.target
                                ) graph.nodes in
                                (match target_node with
                                | Some tn ->
                                    (match tn.display_name with
                                     | Some dn -> let has_fflags =
                                         let len_dn = String.length dn in
                                         let needle = "fflags" in
                                         let len_needle = String.length needle in
                                         let found = ref false in
                                         for i = 0 to len_dn - len_needle do
                                           if String.sub dn i len_needle = needle then found := true
                                         done; !found in
                                         has_fflags
                                     | None -> false)
                                | None -> false)
                              else
                                (* Remove ternary_op -> rd_val assignment *)
                                not (e.target = rd_val_node.id && e.edge_type = "assignment" &&
                                     let src = List.find_opt (fun (n : rg_node) -> n.id = e.source) graph.nodes in
                                     match src with
                                     | Some s -> s.node_type = "ternary_op"
                                     | None -> false)
                            ) graph.edges in
                            (* Add new edge: fp_min/fp_max -> rd_val_S *)
                            let new_edge = {
                              id = fresh_edge_id ();
                              source = fle_node.id;
                              target = rd_val_node.id;
                              edge_type = "assignment";
                              position = None;
                              enable = None
                            } in
                            { graph with nodes = nodes; edges = edges @ [new_edge] }
                        | None ->
                            Printf.printf "      Warning: could not find rd_val node for %s\n%!" target_op;
                            { graph with nodes = nodes })
                    | None ->
                        Printf.printf "      Warning: no fp_le node found for %s\n%!" target_op;
                        graph
                  end else graph in
                  Printf.printf "    Splitting %s -> %s (op=%s, funct3=%s)\n%!" name vname op_code_str funct3_str;
                  (* Remove existing funct7 constraint [31:25] and replace with
                     [31:27] operation code + funct3, keeping format bits [26:25] *)
                  let non_funct7 = List.filter (fun c ->
                    not (c.low_bit = 25 && c.high_bit = 31)
                  ) graph.decode_constraints in
                  let g = { graph with
                    decode_constraints = non_funct7 @
                      [{high_bit=31; low_bit=27; value=op_code_str; operator="=="}] @
                      [{high_bit=14; low_bit=12; value=funct3_str; operator="=="}]
                  } in
                  [Some (vname, g)]

                end else if name = "F_UN_TYPE_X_S" || name = "F_UN_TYPE_X_D" || name = "F_UN_TYPE_X_H"
                         || name = "F_UN_X_TYPE_D" || name = "F_UN_X_TYPE_H" then begin
                  (* FMV.X.W (funct3=000) and FCLASS (funct3=001)
                     Determine suffix FIRST from inner_pat_names for unique prefix. *)
                  let has_inner sub = List.exists (fun n ->
                    let len_sub = String.length sub in
                    let len_n = String.length n in
                    len_n >= len_sub &&
                    (let found = ref false in
                     for i = 0 to len_n - len_sub do
                       if String.sub n i len_sub = sub then found := true
                     done; !found)
                  ) inner_pat_names in
                  let (suffix, funct3_str) = if has_inner "FCLASS" then ("FCLASS", "0b001")
                                             else ("FMV_X_W", "0b000") in
                  let vname = Printf.sprintf "%s_%s" name suffix in
                  let (_, graph) = build_one_variant vname None false all_encdec in
                  Printf.printf "    Splitting %s -> %s (funct3=%s)\n%!" name vname funct3_str;
                  let g = { graph with
                    decode_constraints = graph.decode_constraints @
                      [{high_bit=14; low_bit=12; value=funct3_str; operator="=="}]
                  } in
                  [Some (vname, g)]

                end else if name = "F_UN_RM_FF_TYPE_D" || name = "F_UN_RM_FF_TYPE_H" then begin
                  (* D/H extension: F_UN_RM_FF covers FSQRT + FCVT_S_D + FCVT_D_S
                     (S version is just FSQRT, no splitting needed).
                     Distinguished by funct7: 0101101=fsqrt.d, 0100000=fcvt.s.d, 0100001=fcvt.d.s *)
                  let has_inner sub = List.exists (fun n ->
                    let len_sub = String.length sub in
                    let len_n = String.length n in
                    len_n >= len_sub &&
                    (let found = ref false in
                     for i = 0 to len_n - len_sub do
                       if String.sub n i len_sub = sub then found := true
                     done; !found)
                  ) inner_pat_names in
                  let (suffix, funct7_str) =
                    if has_inner "FSQRT" then ("FSQRT", "0b0101101")
                    else if has_inner "FCVT_S_D" then ("FCVT_S", "0b0100000")
                    else if has_inner "FCVT_D_S" then ("FCVT_D", "0b0100001")
                    else ("UNKNOWN", "0b0000000")
                  in
                  let vname = Printf.sprintf "%s_%s" name suffix in
                  let (_, graph) = build_one_variant vname None false all_encdec in
                  Printf.printf "    Splitting %s -> %s (funct7=%s)\n%!" name vname funct7_str;
                  let non_funct7 = List.filter (fun c ->
                    not (c.low_bit = 25 && c.high_bit = 31)
                  ) graph.decode_constraints in
                  let g = { graph with
                    decode_constraints = non_funct7 @
                      [{high_bit=31; low_bit=25; value=funct7_str; operator="=="}]
                  } in
                  [Some (vname, g)]

                end else if name = "CSRReg" || name = "CSRImm" then begin
                  (* Helper: add fcsr aliasing to a CSR instruction graph.
                     When the CSR address is fflags (0x001), frm (0x002), or fcsr (0x003),
                     reads/writes must be redirected to the fcsr register.
                     This matches the reference ISA files in riscv32/csr/. *)
                  let add_fcsr_aliasing (pfx : string) (graph : rg_graph)
                      ~(csr_addr_id : rg_node_id) ~(csr_read_id : rg_node_id)
                      ~(csr_write_id : rg_node_id) ~(rf_write_id : rg_node_id)
                      ~(new_val_id : rg_node_id) : rg_graph =
                    let mk_node id nt nm bw ?op ?value ?bs ?arch () = {
                      id; node_type = nt; name = Some nm; display_name = Some nm;
                      operator = op; value; bit_width = Some bw;
                      is_arch_state = (match arch with Some true -> true | _ -> false);
                      is_memory = false; array_size = None; array_depth = None;
                      bitslice = bs; dimensions = None;
                    } in
                    let mk_edge src tgt et = {
                      id = fresh_edge_id (); source = src; target = tgt;
                      edge_type = et; position = None; enable = None } in
                    (* fcsr isa_state: separate read and write nodes to avoid cycles *)
                    let fcsr_id = pfx ^ "_fcsr" in
                    let fcsr_node = mk_node fcsr_id "isa_state" "fcsr" 32 ~arch:true () in
                    let fcsr_wr_id = pfx ^ "_fcsr_wr" in
                    let fcsr_wr_node = mk_node fcsr_wr_id "isa_state" "fcsr_wr" 32 ~arch:true () in
                    (* Address comparison literals *)
                    let lit1_id = pfx ^ "_lit1" in
                    let lit2_id = pfx ^ "_lit2" in
                    let lit3_id = pfx ^ "_lit3" in
                    let lit1 = mk_node lit1_id "literal" "1" 12 ~value:"1" () in
                    let lit2 = mk_node lit2_id "literal" "2" 12 ~value:"2" () in
                    let lit3 = mk_node lit3_id "literal" "3" 12 ~value:"3" () in
                    (* Address comparisons *)
                    let is_fflags_id = pfx ^ "_is_fflags" in
                    let is_frm_id = pfx ^ "_is_frm" in
                    let is_fcsr_id = pfx ^ "_is_fcsr_addr" in
                    let is_fflags = mk_node is_fflags_id "operation" (pfx ^ "_is_fflags") 1 ~op:"==" () in
                    let is_frm = mk_node is_frm_id "operation" (pfx ^ "_is_frm") 1 ~op:"==" () in
                    let is_fcsr_a = mk_node is_fcsr_id "operation" (pfx ^ "_is_fcsr_addr") 1 ~op:"==" () in
                    (* addr_is_f_csr = fflags | frm | fcsr_addr *)
                    let or1_id = pfx ^ "_or_ff_frm" in
                    let or1 = mk_node or1_id "operation" (pfx ^ "_or_ff_frm") 1 ~op:"|" () in
                    let is_f_csr_id = pfx ^ "_is_f_csr" in
                    let is_f_csr = mk_node is_f_csr_id "operation" (pfx ^ "_is_f_csr") 1 ~op:"|" () in
                    (* Read aliasing: fcsr bitslices *)
                    let fcsr_4_0_id = pfx ^ "_fcsr_4_0" in
                    let fcsr_7_5_id = pfx ^ "_fcsr_7_5" in
                    let fcsr_4_0 = mk_node fcsr_4_0_id "bit_slice" "fcsr[4:0]" 5 ~bs:(4,0) () in
                    let fcsr_7_5 = mk_node fcsr_7_5_id "bit_slice" "fcsr[7:5]" 3 ~bs:(7,5) () in
                    (* Zero-extend to 32 bits *)
                    let fflags_zext_id = pfx ^ "_fflags_zext" in
                    let frm_zext_id = pfx ^ "_frm_zext" in
                    let fflags_zext = mk_node fflags_zext_id "operation" (pfx ^ "_fflags_zext") 32 ~op:"zero_extend" () in
                    let frm_zext = mk_node frm_zext_id "operation" (pfx ^ "_frm_zext") 32 ~op:"zero_extend" () in
                    (* Read mux chain: fflags -> frm -> fcsr -> csr_read *)
                    let rd_mux3_id = pfx ^ "_rd_mux3" in
                    let rd_mux2_id = pfx ^ "_rd_mux2" in
                    let rd_mux1_id = pfx ^ "_rd_mux1" in
                    let rd_mux3 = mk_node rd_mux3_id "ternary_op" (pfx ^ "_rd_mux3") 32 ~op:"ternary_op" () in
                    let rd_mux2 = mk_node rd_mux2_id "ternary_op" (pfx ^ "_rd_mux2") 32 ~op:"ternary_op" () in
                    let rd_mux1 = mk_node rd_mux1_id "ternary_op" (pfx ^ "_rd_mux1") 32 ~op:"ternary_op" () in
                    (* Write aliasing: bitslice new_val and zero-extend for masking *)
                    let nv_4_0_id = pfx ^ "_nv_4_0" in
                    let nv_2_0_id = pfx ^ "_nv_2_0" in
                    let nv_7_0_id = pfx ^ "_nv_7_0" in
                    let nv_4_0 = mk_node nv_4_0_id "bit_slice" "new_val[4:0]" 5 ~bs:(4,0) () in
                    let nv_2_0 = mk_node nv_2_0_id "bit_slice" "new_val[2:0]" 3 ~bs:(2,0) () in
                    let nv_7_0 = mk_node nv_7_0_id "bit_slice" "new_val[7:0]" 8 ~bs:(7,0) () in
                    (* Zero-extend masks: fflags={27'b0,nv[4:0]}, frm={29'b0,nv[2:0]}, fcsr={24'b0,nv[7:0]} *)
                    let wr_fflags_id = pfx ^ "_wr_fflags" in
                    let wr_frm_id = pfx ^ "_wr_frm" in
                    let wr_full_id = pfx ^ "_wr_full" in
                    let wr_fflags = mk_node wr_fflags_id "operation" (pfx ^ "_wr_fflags") 32 ~op:"zero_extend" () in
                    let wr_frm = mk_node wr_frm_id "operation" (pfx ^ "_wr_frm") 32 ~op:"zero_extend" () in
                    let wr_full = mk_node wr_full_id "operation" (pfx ^ "_wr_full") 32 ~op:"zero_extend" () in
                    (* Write mux chain for CSR array: masks value to correct width *)
                    let wr_mux3_id = pfx ^ "_wr_mux3" in
                    let wr_mux2_id = pfx ^ "_wr_mux2" in
                    let wr_mux1_id = pfx ^ "_wr_mux1" in
                    let wr_mux3 = mk_node wr_mux3_id "ternary_op" (pfx ^ "_wr_mux3") 32 ~op:"ternary_op" () in
                    let wr_mux2 = mk_node wr_mux2_id "ternary_op" (pfx ^ "_wr_mux2") 32 ~op:"ternary_op" () in
                    let wr_mux1 = mk_node wr_mux1_id "ternary_op" (pfx ^ "_wr_mux1") 32 ~op:"ternary_op" () in
                    (* Fcsr write-back: compose full 32-bit fcsr from CSR write.
                       fcsr = {24'b0, frm[2:0], fflags[4:0]}.
                       - fflags write (addr=1): {fcsr[7:5], nv[4:0]} preserves frm
                       - frm write    (addr=2): {nv[2:0], fcsr[4:0]} preserves fflags
                       - fcsr write   (addr=3): nv[7:0]              full replacement *)
                    let mk_edge_p src tgt et pos = {
                      id = fresh_edge_id (); source = src; target = tgt;
                      edge_type = et; position = Some pos; enable = None } in
                    let comp_ff_id = pfx ^ "_comp_ff" in
                    let comp_ff = mk_node comp_ff_id "operation" (pfx ^ "_comp_ff") 8 ~op:"bitvector_concat" () in
                    let comp_rm_id = pfx ^ "_comp_rm" in
                    let comp_rm = mk_node comp_rm_id "operation" (pfx ^ "_comp_rm") 8 ~op:"bitvector_concat" () in
                    let comp_ff_z_id = pfx ^ "_comp_ff_z" in
                    let comp_rm_z_id = pfx ^ "_comp_rm_z" in
                    let comp_ff_z = mk_node comp_ff_z_id "operation" (pfx ^ "_comp_ff_z") 32 ~op:"zero_extend" () in
                    let comp_rm_z = mk_node comp_rm_z_id "operation" (pfx ^ "_comp_rm_z") 32 ~op:"zero_extend" () in
                    let fcsr_wb3_id = pfx ^ "_fcsr_wb3" in
                    let fcsr_wb2_id = pfx ^ "_fcsr_wb2" in
                    let fcsr_wb1_id = pfx ^ "_fcsr_wb1" in
                    let fcsr_wb3 = mk_node fcsr_wb3_id "ternary_op" (pfx ^ "_fcsr_wb3") 32 ~op:"ternary_op" () in
                    let fcsr_wb2 = mk_node fcsr_wb2_id "ternary_op" (pfx ^ "_fcsr_wb2") 32 ~op:"ternary_op" () in
                    let fcsr_wb1 = mk_node fcsr_wb1_id "ternary_op" (pfx ^ "_fcsr_wb1") 32 ~op:"ternary_op" () in

                    let aliasing_nodes = [
                      fcsr_node; fcsr_wr_node; lit1; lit2; lit3;
                      is_fflags; is_frm; is_fcsr_a; or1; is_f_csr;
                      fcsr_4_0; fcsr_7_5; fflags_zext; frm_zext;
                      rd_mux3; rd_mux2; rd_mux1;
                      nv_4_0; nv_2_0; nv_7_0;
                      wr_fflags; wr_frm; wr_full;
                      wr_mux3; wr_mux2; wr_mux1;
                      comp_ff; comp_rm; comp_ff_z; comp_rm_z;
                      fcsr_wb3; fcsr_wb2; fcsr_wb1;
                    ] in
                    let aliasing_edges = [
                      (* Address comparisons *)
                      mk_edge csr_addr_id is_fflags_id "operand";
                      mk_edge lit1_id is_fflags_id "operand";
                      mk_edge csr_addr_id is_frm_id "operand";
                      mk_edge lit2_id is_frm_id "operand";
                      mk_edge csr_addr_id is_fcsr_id "operand";
                      mk_edge lit3_id is_fcsr_id "operand";
                      mk_edge is_fflags_id or1_id "operand";
                      mk_edge is_frm_id or1_id "operand";
                      mk_edge or1_id is_f_csr_id "operand";
                      mk_edge is_fcsr_id is_f_csr_id "operand";
                      (* Read aliasing: fcsr bitslices *)
                      mk_edge fcsr_id fcsr_4_0_id "bit_access";
                      mk_edge fcsr_id fcsr_7_5_id "bit_access";
                      mk_edge fcsr_4_0_id fflags_zext_id "operand";
                      mk_edge fcsr_7_5_id frm_zext_id "operand";
                      (* Read mux chain *)
                      mk_edge is_fcsr_id rd_mux3_id "ternary_condition";
                      mk_edge fcsr_id rd_mux3_id "ternary_true";
                      mk_edge csr_read_id rd_mux3_id "ternary_false";
                      mk_edge is_frm_id rd_mux2_id "ternary_condition";
                      mk_edge frm_zext_id rd_mux2_id "ternary_true";
                      mk_edge rd_mux3_id rd_mux2_id "ternary_false";
                      mk_edge is_fflags_id rd_mux1_id "ternary_condition";
                      mk_edge fflags_zext_id rd_mux1_id "ternary_true";
                      mk_edge rd_mux2_id rd_mux1_id "ternary_false";
                      (* Rewire: rd_mux1 -> rf_write instead of csr_read -> rf_write *)
                      mk_edge rd_mux1_id rf_write_id "assignment";
                      (* Write aliasing: bitslice new_val and zero-extend *)
                      mk_edge new_val_id nv_4_0_id "bit_access";
                      mk_edge new_val_id nv_2_0_id "bit_access";
                      mk_edge new_val_id nv_7_0_id "bit_access";
                      mk_edge nv_4_0_id wr_fflags_id "operand";
                      mk_edge nv_2_0_id wr_frm_id "operand";
                      mk_edge nv_7_0_id wr_full_id "operand";
                      (* Write mux chain: for FP CSRs, mask value; for others, pass through *)
                      mk_edge is_fcsr_id wr_mux3_id "ternary_condition";
                      mk_edge wr_full_id wr_mux3_id "ternary_true";
                      mk_edge new_val_id wr_mux3_id "ternary_false";
                      mk_edge is_frm_id wr_mux2_id "ternary_condition";
                      mk_edge wr_frm_id wr_mux2_id "ternary_true";
                      mk_edge wr_mux3_id wr_mux2_id "ternary_false";
                      mk_edge is_fflags_id wr_mux1_id "ternary_condition";
                      mk_edge wr_fflags_id wr_mux1_id "ternary_true";
                      mk_edge wr_mux2_id wr_mux1_id "ternary_false";
                      (* Route masked value to csr_write (replaces new_val -> csr_write) *)
                      mk_edge wr_mux1_id csr_write_id "assignment";
                      (* Fcsr write-back: compose full fcsr value from CSR write *)
                      mk_edge_p fcsr_7_5_id comp_ff_id "operand" "0";
                      mk_edge_p nv_4_0_id comp_ff_id "operand" "1";
                      mk_edge_p nv_2_0_id comp_rm_id "operand" "0";
                      mk_edge_p fcsr_4_0_id comp_rm_id "operand" "1";
                      mk_edge comp_ff_id comp_ff_z_id "operand";
                      mk_edge comp_rm_id comp_rm_z_id "operand";
                      mk_edge is_fcsr_id fcsr_wb3_id "ternary_condition";
                      mk_edge wr_full_id fcsr_wb3_id "ternary_true";
                      mk_edge fcsr_id fcsr_wb3_id "ternary_false";
                      mk_edge is_frm_id fcsr_wb2_id "ternary_condition";
                      mk_edge comp_rm_z_id fcsr_wb2_id "ternary_true";
                      mk_edge fcsr_wb3_id fcsr_wb2_id "ternary_false";
                      mk_edge is_fflags_id fcsr_wb1_id "ternary_condition";
                      mk_edge comp_ff_z_id fcsr_wb1_id "ternary_true";
                      mk_edge fcsr_wb2_id fcsr_wb1_id "ternary_false";
                      mk_edge fcsr_wb1_id fcsr_wr_id "assignment";
                    ] in
                    (* Redirect edges: any consumer of csr_read (other than rf_write)
                       must use the aliased rd_mux1 instead.  This is critical for
                       CSRRS/CSRRC where the OR/AND computation reads the old CSR value;
                       without this, the computation reads stale csr[addr] instead of
                       the dedicated fcsr register. *)
                    let redirect_edges = List.filter_map (fun (e : rg_edge) ->
                      if e.source = csr_read_id && e.target <> rf_write_id then
                        Some { e with id = fresh_edge_id (); source = rd_mux1_id }
                      else
                        None
                    ) graph.edges in
                    (* Remove old csr_read -> rf_write AND new_val -> csr_write assignment edges,
                       AND all csr_read -> X edges (redirected through rd_mux1 above) *)
                    let filtered_edges = List.filter (fun (e : rg_edge) ->
                      not (e.source = csr_read_id && e.target = rf_write_id && e.edge_type = "assignment") &&
                      not (e.source = new_val_id && e.target = csr_write_id && e.edge_type = "assignment") &&
                      not (e.source = csr_read_id && e.target <> rf_write_id)
                    ) graph.edges in
                    { graph with
                      nodes = graph.nodes @ aliasing_nodes;
                      edges = filtered_edges @ aliasing_edges @ redirect_edges }
                  in

                  if name = "CSRReg" then begin
                  (* Split CSRReg into CSRRW/CSRRS/CSRRC.
                     The single execute clause uses a generic csr_modify(old_val, rs1_val, op)
                     node. The VerilogGenerator doesn't implement csr_modify, so we replace it
                     with the actual bitwise operation per CSR variant.
                     funct3: CSRRW=001, CSRRS=010, CSRRC=011 *)
                  let csr_variants = [
                    ("csrrw", "0b001", "csrrw");
                    ("csrrs", "0b010", "csrrs");
                    ("csrrc", "0b011", "csrrc");
                  ] in
                  let results = List.concat_map (fun (vname, funct3_str, csr_op) ->
                    let (_, graph) = build_one_variant vname None false all_encdec in
                    (* Find the csr_modify node *)
                    let modify_node_opt = List.find_opt (fun (n : rg_node) ->
                      n.operator = Some "csr_modify"
                    ) graph.nodes in
                    match modify_node_opt with
                    | None ->
                        Printf.printf "    Warning: no csr_modify in %s\n%!" vname;
                        [Some (vname, graph)]
                    | Some modify_node ->
                        (* Find the csr_modify's inputs: old_val (csr read), rs1_val, op *)
                        let modify_inputs = List.filter (fun (e : rg_edge) ->
                          e.target = modify_node.id && e.edge_type = "operand"
                        ) graph.edges in
                        let input_nodes = List.map (fun (e : rg_edge) ->
                          (List.find (fun (n : rg_node) -> n.id = e.source) graph.nodes, e)
                        ) modify_inputs in
                        (* Identify old_val (array_access), rs1_val (array_access rf read), op (var) *)
                        let old_val_opt = List.find_opt (fun ((n : rg_node), _) ->
                          n.node_type = "array_access" &&
                          (match n.display_name with Some dn ->
                            let len = String.length dn in len >= 3 && String.sub dn 0 3 = "csr"
                           | None -> false)
                        ) input_nodes in
                        let rs1_val_opt = List.find_opt (fun ((n : rg_node), _) ->
                          n.node_type = "array_access" &&
                          (match n.display_name with Some dn ->
                            let len = String.length dn in len >= 2 && String.sub dn 0 2 = "rf"
                           | None -> false)
                        ) input_nodes in
                        let op_var_opt = List.find_opt (fun ((n : rg_node), _) ->
                          n.node_type = "var"
                        ) input_nodes in
                        (* Find modify's output edge (to csr_write) *)
                        let modify_output = List.find_opt (fun (e : rg_edge) ->
                          e.source = modify_node.id && e.edge_type = "assignment"
                        ) graph.edges in
                        (match old_val_opt, rs1_val_opt, modify_output with
                        | Some (old_val_node, _), Some (rs1_val_node, _), Some out_edge ->
                            let csr_write_id = out_edge.target in
                            (* Collect nodes to remove: csr_modify, op var, and related nodes *)
                            let remove_ids = Hashtbl.create 16 in
                            Hashtbl.replace remove_ids modify_node.id true;
                            (match op_var_opt with
                             | Some (op_var, _) ->
                                 Hashtbl.replace remove_ids op_var.id true;
                                 (* Also remove nodes that only feed into op-related computations:
                                    csr_access_type, eq_anything comparisons, zreg literal *)
                                 List.iter (fun (n : rg_node) ->
                                   if n.operator = Some "csr_access_type" ||
                                      n.operator = Some "eq_anything" then
                                     Hashtbl.replace remove_ids n.id true;
                                   (* Remove the access_type var *)
                                   if n.node_type = "var" &&
                                      (match n.display_name with
                                       | Some dn ->
                                           let len = String.length dn in
                                           len >= 11 && String.sub dn (len - 11) 11 = "access_type"
                                       | None -> false) then
                                     Hashtbl.replace remove_ids n.id true;
                                   (* Remove the zreg var *)
                                   if n.node_type = "var" &&
                                      (match n.display_name with
                                       | Some dn ->
                                           let len = String.length dn in
                                           len >= 4 && String.sub dn (len - 4) 4 = "zreg"
                                       | None -> false) then
                                     Hashtbl.replace remove_ids n.id true
                                 ) graph.nodes
                             | None -> ());
                            (* Filter nodes and edges *)
                            let new_nodes = List.filter (fun (n : rg_node) ->
                              not (Hashtbl.mem remove_ids n.id)
                            ) graph.nodes in
                            let new_edges = List.filter (fun (e : rg_edge) ->
                              not (Hashtbl.mem remove_ids e.source) &&
                              not (Hashtbl.mem remove_ids e.target)
                            ) graph.edges in
                            (* Create replacement logic based on CSR operation type *)
                            let (extra_nodes, extra_edges, new_val_src_id) =
                              if csr_op = "csrrw" then
                                (* CSRRW: new_val = rs1_val — wire directly *)
                                let e = { id = fresh_edge_id ();
                                          source = rs1_val_node.id;
                                          target = csr_write_id;
                                          edge_type = "assignment";
                                          position = None; enable = None } in
                                ([], [e], rs1_val_node.id)
                              else if csr_op = "csrrs" then
                                (* CSRRS: new_val = old_val | rs1_val *)
                                let or_node = {
                                  id = Printf.sprintf "%s_or" vname;
                                  node_type = "operation";
                                  name = Some "csr_or";
                                  display_name = Some (Printf.sprintf "%s_csr_or" vname);
                                  operator = Some "|";
                                  value = None;
                                  bit_width = Some 32;
                                  is_arch_state = false;
                                  is_memory = false;
                                  array_size = None;
                                  array_depth = None;
                                  bitslice = None;
                                  dimensions = None;
                                } in
                                let e1 = { id = fresh_edge_id (); source = old_val_node.id;
                                           target = or_node.id; edge_type = "operand"; position = None; enable = None } in
                                let e2 = { id = fresh_edge_id (); source = rs1_val_node.id;
                                           target = or_node.id; edge_type = "operand"; position = None; enable = None } in
                                let e3 = { id = fresh_edge_id (); source = or_node.id;
                                           target = csr_write_id; edge_type = "assignment"; position = None; enable = None } in
                                ([or_node], [e1; e2; e3], or_node.id)
                              else (* CSRRC: new_val = old_val & ~rs1_val *)
                                let not_node = {
                                  id = Printf.sprintf "%s_not" vname;
                                  node_type = "operation";
                                  name = Some "csr_not";
                                  display_name = Some (Printf.sprintf "%s_csr_not" vname);
                                  operator = Some "~";
                                  value = None;
                                  bit_width = Some 32;
                                  is_arch_state = false;
                                  is_memory = false;
                                  array_size = None;
                                  array_depth = None;
                                  bitslice = None;
                                  dimensions = None;
                                } in
                                let and_node = {
                                  id = Printf.sprintf "%s_and" vname;
                                  node_type = "operation";
                                  name = Some "csr_and";
                                  display_name = Some (Printf.sprintf "%s_csr_and" vname);
                                  operator = Some "&";
                                  value = None;
                                  bit_width = Some 32;
                                  is_arch_state = false;
                                  is_memory = false;
                                  array_size = None;
                                  array_depth = None;
                                  bitslice = None;
                                  dimensions = None;
                                } in
                                let e1 = { id = fresh_edge_id (); source = rs1_val_node.id;
                                           target = not_node.id; edge_type = "operand"; position = None; enable = None } in
                                let e2 = { id = fresh_edge_id (); source = old_val_node.id;
                                           target = and_node.id; edge_type = "operand"; position = None; enable = None } in
                                let e3 = { id = fresh_edge_id (); source = not_node.id;
                                           target = and_node.id; edge_type = "operand"; position = None; enable = None } in
                                let e4 = { id = fresh_edge_id (); source = and_node.id;
                                           target = csr_write_id; edge_type = "assignment"; position = None; enable = None } in
                                ([not_node; and_node], [e1; e2; e3; e4], and_node.id)
                            in
                            (* Replace bit-14 decode constraint with full funct3 *)
                            let non_funct3 = List.filter (fun c ->
                              not (c.low_bit >= 12 && c.high_bit <= 14)
                            ) graph.decode_constraints in
                            let new_decode = non_funct3 @
                              [{high_bit=14; low_bit=12; value=funct3_str; operator="=="}] in
                            Printf.printf "    Split %s -> %s (funct3=%s)\n%!" name vname funct3_str;
                            let g = {
                              nodes = new_nodes @ extra_nodes;
                              edges = new_edges @ extra_edges;
                              decode_constraints = new_decode } in
                            (* Find csr_addr (bit_slice) and rf_write (array_write) node IDs *)
                            let csr_addr_id_opt = List.find_opt (fun (n : rg_node) ->
                              n.node_type = "bit_slice" &&
                              (match n.display_name with Some dn ->
                                dn = "csr" || (let len = String.length dn in
                                  len >= 4 && String.sub dn 0 4 = "csr " ) ||
                                (try let _ = Str.search_forward (Str.regexp_string "_csr") dn 0 in true
                                 with Not_found -> false)
                               | None -> false)
                            ) g.nodes in
                            let rf_write_id_opt = List.find_opt (fun (n : rg_node) ->
                              (n.node_type = "array_access" || n.node_type = "array_write") &&
                              (match n.display_name with Some dn ->
                                let len = String.length dn in
                                (len >= 2 && String.sub dn 0 2 = "rf") ||
                                (try let _ = Str.search_forward (Str.regexp_string "_rf") dn 0 in true
                                 with Not_found -> false)
                               | None -> false) &&
                              (* Must be a write target: has incoming assignment edge or is array_write *)
                              (n.node_type = "array_write" ||
                               List.exists (fun (e : rg_edge) ->
                                e.target = n.id && e.edge_type = "assignment"
                              ) g.edges)
                            ) g.nodes in
                            let g = match csr_addr_id_opt, rf_write_id_opt with
                              | Some csr_addr_n, Some rf_write_n ->
                                  add_fcsr_aliasing vname g
                                    ~csr_addr_id:csr_addr_n.id
                                    ~csr_read_id:old_val_node.id
                                    ~csr_write_id
                                    ~rf_write_id:rf_write_n.id
                                    ~new_val_id:new_val_src_id
                              | _ -> g
                            in
                            [Some (vname, g)]
                        | _ ->
                            Printf.printf "    Warning: could not identify csr_modify I/O in %s\n%!" vname;
                            [Some (vname, graph)])
                  ) csr_variants in
                  results

                end else begin
                  (* CSRImm: Split into csrrwi/csrrsi/csrrci — same logic as CSRReg *)
                  let csr_variants = [
                    ("csrrwi", "0b101", "csrrwi");
                    ("csrrsi", "0b110", "csrrsi");
                    ("csrrci", "0b111", "csrrci");
                  ] in
                  let results = List.concat_map (fun (vname, funct3_str, csr_op) ->
                    let (_, graph) = build_one_variant vname None false all_encdec in
                    let modify_node_opt = List.find_opt (fun (n : rg_node) ->
                      n.operator = Some "csr_modify"
                    ) graph.nodes in
                    match modify_node_opt with
                    | None ->
                        Printf.printf "    Warning: no csr_modify in %s\n%!" vname;
                        [Some (vname, graph)]
                    | Some modify_node ->
                        let modify_inputs = List.filter (fun (e : rg_edge) ->
                          e.target = modify_node.id && e.edge_type = "operand"
                        ) graph.edges in
                        let input_nodes = List.map (fun (e : rg_edge) ->
                          (List.find (fun (n : rg_node) -> n.id = e.source) graph.nodes, e)
                        ) modify_inputs in
                        let old_val_opt = List.find_opt (fun ((n : rg_node), _) ->
                          n.node_type = "array_access" &&
                          (match n.display_name with Some dn ->
                            let len = String.length dn in len >= 3 && String.sub dn 0 3 = "csr"
                           | None -> false)
                        ) input_nodes in
                        (* For CSRImm, the "rs1" is an immediate value, not a register read.
                           It could be a var or literal node. Find non-csr, non-var input. *)
                        let imm_val_opt = List.find_opt (fun ((n : rg_node), _) ->
                          n.node_type <> "var" ||
                          (match n.display_name with
                           | Some dn ->
                               not (let len = String.length dn in
                                    (len >= 3 && String.sub dn 0 3 = "csr") ||
                                    (len >= 2 && String.sub dn (len - 2) 2 = "op"))
                           | None -> true)
                        ) (List.filter (fun ((n : rg_node), _) ->
                          n.id <> (match old_val_opt with Some (ov, _) -> ov.id | None -> "")
                        ) input_nodes) in
                        let op_var_opt = List.find_opt (fun ((n : rg_node), _) ->
                          n.node_type = "var" &&
                          (match n.display_name with
                           | Some dn -> let len = String.length dn in
                               len >= 2 && String.sub dn (len - 2) 2 = "op"
                           | None -> false)
                        ) input_nodes in
                        let modify_output = List.find_opt (fun (e : rg_edge) ->
                          e.source = modify_node.id && e.edge_type = "assignment"
                        ) graph.edges in
                        (match old_val_opt, imm_val_opt, modify_output with
                        | Some (old_val_node, _), Some (imm_val_node, _), Some out_edge ->
                            let csr_write_id = out_edge.target in
                            let remove_ids = Hashtbl.create 16 in
                            Hashtbl.replace remove_ids modify_node.id true;
                            (match op_var_opt with
                             | Some (op_var, _) ->
                                 Hashtbl.replace remove_ids op_var.id true;
                                 List.iter (fun (n : rg_node) ->
                                   if n.operator = Some "csr_access_type" ||
                                      n.operator = Some "eq_anything" then
                                     Hashtbl.replace remove_ids n.id true;
                                   if n.node_type = "var" &&
                                      (match n.display_name with
                                       | Some dn ->
                                           let len = String.length dn in
                                           (len >= 11 && String.sub dn (len - 11) 11 = "access_type") ||
                                           (len >= 4 && String.sub dn (len - 4) 4 = "zreg")
                                       | None -> false) then
                                     Hashtbl.replace remove_ids n.id true
                                 ) graph.nodes
                             | None -> ());
                            let new_nodes = List.filter (fun (n : rg_node) ->
                              not (Hashtbl.mem remove_ids n.id)
                            ) graph.nodes in
                            let new_edges = List.filter (fun (e : rg_edge) ->
                              not (Hashtbl.mem remove_ids e.source) &&
                              not (Hashtbl.mem remove_ids e.target)
                            ) graph.edges in
                            let (extra_nodes, extra_edges, new_val_src_id) =
                              if csr_op = "csrrwi" then
                                let e = { id = fresh_edge_id ();
                                          source = imm_val_node.id;
                                          target = csr_write_id;
                                          edge_type = "assignment";
                                          position = None; enable = None } in
                                ([], [e], imm_val_node.id)
                              else if csr_op = "csrrsi" then
                                let or_node = {
                                  id = Printf.sprintf "%s_or" vname;
                                  node_type = "operation";
                                  name = Some "csr_or";
                                  display_name = Some (Printf.sprintf "%s_csr_or" vname);
                                  operator = Some "|";
                                  value = None; bit_width = Some 32;
                                  is_arch_state = false; is_memory = false;
                                  array_size = None; array_depth = None;
                                  bitslice = None; dimensions = None;
                                } in
                                let e1 = { id = fresh_edge_id (); source = old_val_node.id;
                                           target = or_node.id; edge_type = "operand"; position = None; enable = None } in
                                let e2 = { id = fresh_edge_id (); source = imm_val_node.id;
                                           target = or_node.id; edge_type = "operand"; position = None; enable = None } in
                                let e3 = { id = fresh_edge_id (); source = or_node.id;
                                           target = csr_write_id; edge_type = "assignment"; position = None; enable = None } in
                                ([or_node], [e1; e2; e3], or_node.id)
                              else
                                let not_node = {
                                  id = Printf.sprintf "%s_not" vname;
                                  node_type = "operation";
                                  name = Some "csr_not";
                                  display_name = Some (Printf.sprintf "%s_csr_not" vname);
                                  operator = Some "~";
                                  value = None; bit_width = Some 32;
                                  is_arch_state = false; is_memory = false;
                                  array_size = None; array_depth = None;
                                  bitslice = None; dimensions = None;
                                } in
                                let and_node = {
                                  id = Printf.sprintf "%s_and" vname;
                                  node_type = "operation";
                                  name = Some "csr_and";
                                  display_name = Some (Printf.sprintf "%s_csr_and" vname);
                                  operator = Some "&";
                                  value = None; bit_width = Some 32;
                                  is_arch_state = false; is_memory = false;
                                  array_size = None; array_depth = None;
                                  bitslice = None; dimensions = None;
                                } in
                                let e1 = { id = fresh_edge_id (); source = imm_val_node.id;
                                           target = not_node.id; edge_type = "operand"; position = None; enable = None } in
                                let e2 = { id = fresh_edge_id (); source = old_val_node.id;
                                           target = and_node.id; edge_type = "operand"; position = None; enable = None } in
                                let e3 = { id = fresh_edge_id (); source = not_node.id;
                                           target = and_node.id; edge_type = "operand"; position = None; enable = None } in
                                let e4 = { id = fresh_edge_id (); source = and_node.id;
                                           target = csr_write_id; edge_type = "assignment"; position = None; enable = None } in
                                ([not_node; and_node], [e1; e2; e3; e4], and_node.id)
                            in
                            let non_funct3 = List.filter (fun c ->
                              not (c.low_bit >= 12 && c.high_bit <= 14)
                            ) graph.decode_constraints in
                            let new_decode = non_funct3 @
                              [{high_bit=14; low_bit=12; value=funct3_str; operator="=="}] in
                            Printf.printf "    Split %s -> %s (funct3=%s)\n%!" name vname funct3_str;
                            let g = {
                              nodes = new_nodes @ extra_nodes;
                              edges = new_edges @ extra_edges;
                              decode_constraints = new_decode } in
                            (* Find csr_addr and rf_write node IDs for fcsr aliasing *)
                            let csr_addr_id_opt = List.find_opt (fun (n : rg_node) ->
                              n.node_type = "bit_slice" &&
                              (match n.display_name with Some dn ->
                                dn = "csr" || (let len = String.length dn in
                                  len >= 4 && String.sub dn 0 4 = "csr ")
                               | None -> false)
                            ) g.nodes in
                            let rf_write_id_opt = List.find_opt (fun (n : rg_node) ->
                              (n.node_type = "array_access" || n.node_type = "array_write") &&
                              (match n.display_name with Some dn ->
                                let len = String.length dn in len >= 2 && String.sub dn 0 2 = "rf"
                               | None -> false) &&
                              (n.node_type = "array_write" ||
                               List.exists (fun (e : rg_edge) ->
                                e.target = n.id && e.edge_type = "assignment"
                              ) g.edges)
                            ) g.nodes in
                            let g = match csr_addr_id_opt, rf_write_id_opt with
                              | Some csr_addr_n, Some rf_write_n ->
                                  add_fcsr_aliasing vname g
                                    ~csr_addr_id:csr_addr_n.id
                                    ~csr_read_id:old_val_node.id
                                    ~csr_write_id
                                    ~rf_write_id:rf_write_n.id
                                    ~new_val_id:new_val_src_id
                              | _ -> g
                            in
                            [Some (vname, g)]
                        | _ ->
                            [Some (vname, graph)])
                  ) csr_variants in
                  results

                end (* end inner CSRImm else-begin *)
                end else begin
                  (* Normal path: single graph for this instruction *)
                  let (n, g) = build_one_variant name None false all_encdec in
                  [Some (n, g)]
                end
            | None -> []
          ) clauses |> List.filter_map Fun.id
          in
          (* Merge graphs that share the same instruction type name.
             This happens when multiple execute clauses map to the same type
             (e.g., F_UN_TYPE_X_S covers both FCLASS_S and FMV_X_W). *)
          (* DEBUG: check for duplicate names in raw_graphs *)
          let name_counts : (string, int) Hashtbl.t = Hashtbl.create 64 in
          List.iter (fun (name, _graph) ->
            let c = match Hashtbl.find_opt name_counts name with Some n -> n | None -> 0 in
            Hashtbl.replace name_counts name (c + 1)
          ) raw_graphs;
          Hashtbl.iter (fun name count ->
            if count > 1 || (String.length name > 10 && String.sub name 0 10 = "F_BIN_RM_T") then
              Printf.printf "    DEBUG raw_graphs: %s appears %d time(s)\n%!" name count
          ) name_counts;
          let merged_tbl : (string, rg_graph) Hashtbl.t = Hashtbl.create 64 in
          List.iter (fun (name, graph) ->
            match Hashtbl.find_opt merged_tbl name with
            | None -> Hashtbl.replace merged_tbl name graph
            | Some existing ->
                Printf.printf "    DEBUG merged_tbl: MERGING %s (existing %d nodes + new graph %d nodes)\n%!" name (List.length existing.nodes) (List.length graph.nodes);
                let node_ids : (string, bool) Hashtbl.t = Hashtbl.create 64 in
                List.iter (fun (n : rg_node) -> Hashtbl.replace node_ids n.id true) existing.nodes;
                let new_nodes = List.filter (fun (n : rg_node) -> not (Hashtbl.mem node_ids n.id)) graph.nodes in
                let edge_ids : (string, bool) Hashtbl.t = Hashtbl.create 64 in
                List.iter (fun (e : rg_edge) -> Hashtbl.replace edge_ids e.id true) existing.edges;
                let new_edges = List.filter (fun (e : rg_edge) -> not (Hashtbl.mem edge_ids e.id)) graph.edges in
                let merged = {
                  nodes = existing.nodes @ new_nodes;
                  edges = existing.edges @ new_edges;
                  decode_constraints = existing.decode_constraints @ graph.decode_constraints
                } in
                Hashtbl.replace merged_tbl name merged
          ) raw_graphs;
          Hashtbl.fold (fun name graph acc -> (name, graph) :: acc) merged_tbl []
        end else []

  (* Visit top-level function definition with optional filtering (merged mode) *)
  let visit_fundef builder filter_func (FD_aux (FD_function (_rec, _tannot, clauses), _)) =
    (* Extract function name from first clause *)
    let func_name = match clauses with
      | FCL_aux (FCL_funcl (id, _), _) :: _ -> string_of_id id
      | _ -> "unknown"
    in
    (* Debug: print first few function names *)
    let first_funcs = ["execute"; "assembly"; "encdec"; "RTYPE"; "ITYPE"; "BTYPE"; "UTYPE"; "fetch"; "rX"; "wX"; "rX_bits"; "wX_bits"; "step"] in
    if List.mem func_name first_funcs then
      Printf.printf "  Found function: %s\n%!" func_name;

    (* Only process if matches filter (or no filter specified) *)
    match filter_func with
    | Some target when target <> func_name -> ()
    | _ ->
        (* Process execute and other important functions *)
        if func_name = "execute" then
          Printf.printf "  Processing execute clause (found %d clauses)\n%!" (List.length clauses)
        else if List.mem func_name ["fetch"; "rX"; "wX"; "rX_bits"; "wX_bits"; "step"] then
          Printf.printf "  Processing %s function (found %d clauses)\n%!" func_name (List.length clauses);
        List.iter (visit_funcl builder func_name) clauses

  (* Visit scattered function clause *)
  let visit_scattered builder filter_func (SD_aux (sd_aux, _)) =
    match sd_aux with
    | SD_function (id, _) ->
        let func_name = string_of_id id in
        Printf.printf "  Found scattered function: %s\n%!" func_name
    | SD_funcl (FCL_aux (FCL_funcl (id, _pexp), _) as funcl) ->
        let func_name = string_of_id id in
        Printf.printf "  Found scattered clause: %s\n%!" func_name;
        (* Only process if matches filter (or no filter specified) *)
        (match filter_func with
         | Some target when target <> func_name -> ()
         | _ -> visit_funcl builder func_name funcl)
    | _ -> Printf.printf "  Found other scattered def type\n%!"

  (* Visit top-level definition *)
  let rec visit_def builder filter_func def =
    let def_type = match def with
      | DEF_aux (DEF_fundef fdef, _) ->
          (* Print function name for fundefs *)
          let FD_aux (FD_function (_rec, _tannot, clauses), _) = fdef in
          let func_name = match clauses with
            | FCL_aux (FCL_funcl (id, _), _) :: _ -> string_of_id id
            | _ -> "unknown"
          in
          Printf.sprintf "fundef(%s, %d clauses)" func_name (List.length clauses)
      | DEF_aux (DEF_scattered _, _) -> "scattered"
      | DEF_aux (DEF_type _, _) -> "type"
      | DEF_aux (DEF_val _, _) -> "val"
      | DEF_aux (DEF_register _, _) -> "register"
      | DEF_aux (DEF_mapdef (MD_aux (MD_mapping (id, _, _), _)), _) ->
          Printf.sprintf "mapdef(%s)" (string_of_id id)
      | _ -> "other"
    in
    Printf.printf "  Def type: %s\n%!" def_type;
    match def with
    | DEF_aux (DEF_fundef fdef, _) -> visit_fundef builder filter_func fdef
    | DEF_aux (DEF_scattered sd, _) -> visit_scattered builder filter_func sd
    | DEF_aux (DEF_mapdef mapdef, _) ->
        (* Process mapping definitions (decode logic) *)
        visit_mapdef builder mapdef
    | _ -> ()

  (* Visit mapping definition *)
  and visit_mapdef builder (MD_aux (MD_mapping (id, _, mapcl_list), _)) =
    let mapping_name = string_of_id id in

    (* Only process encdec mapping for now *)
    if mapping_name = "encdec" then begin
      Printf.printf "  Processing encdec mapping with %d clauses\n%!" (List.length mapcl_list);

      List.iter (fun mapcl ->
        match mapcl with
        | MCL_aux (MCL_bidir (left_mpexp, right_mpexp), _) ->
            (* left: instruction pattern (e.g., RTYPE(rs2, rs1, rd, ADD)) *)
            (* right: bit pattern (e.g., 0b0000000 @ rs2 @ rs1 @ 0b000 @ rd @ 0b0110011) *)
            Printf.printf "    Found bidir mapping clause\n%!";
            extract_decode_pattern builder left_mpexp right_mpexp
        | _ ->
            Printf.printf "    Skipping non-bidir mapping clause\n%!"
      ) mapcl_list
    end

  (* Debug: print structure of mapping pattern *)
  and _debug_mpexp indent (MPat_aux (mpat_aux, _)) =
    let prefix = String.make (indent * 2) ' ' in
    match mpat_aux with
    | MPat_pat mpat ->
        Printf.printf "%sMPat_pat:\n%!" prefix;
        _debug_mpat (indent + 1) mpat
    | MPat_when (mpat, _) ->
        Printf.printf "%sMPat_when:\n%!" prefix;
        _debug_mpat (indent + 1) mpat

  and _debug_mpat indent (MP_aux (mp_aux, _)) =
    let prefix = String.make (indent * 2) ' ' in
    match mp_aux with
    | MP_id id ->
        Printf.printf "%sMP_id: %s\n%!" prefix (string_of_id id)
    | MP_app (id, args) ->
        Printf.printf "%sMP_app: %s with %d args\n%!" prefix (string_of_id id) (List.length args);
        List.iter (_debug_mpat (indent + 1)) args
    | MP_lit _ ->
        Printf.printf "%sMP_lit: <literal>\n%!" prefix
    | MP_cons (mp1, mp2) ->
        Printf.printf "%sMP_cons:\n%!" prefix;
        _debug_mpat (indent + 1) mp1;
        _debug_mpat (indent + 1) mp2
    | MP_string_append mps ->
        Printf.printf "%sMP_string_append: %d parts\n%!" prefix (List.length mps);
        List.iter (_debug_mpat (indent + 1)) mps
    | MP_list mps ->
        Printf.printf "%sMP_list: %d items\n%!" prefix (List.length mps);
        List.iter (_debug_mpat (indent + 1)) mps
    | MP_tuple mps ->
        Printf.printf "%sMP_tuple: %d items\n%!" prefix (List.length mps);
        List.iter (_debug_mpat (indent + 1)) mps
    | MP_typ (mp, _) ->
        Printf.printf "%sMP_typ:\n%!" prefix;
        _debug_mpat (indent + 1) mp
    | MP_as (mp, _) ->
        Printf.printf "%sMP_as:\n%!" prefix;
        _debug_mpat (indent + 1) mp
    | MP_struct _ ->
        Printf.printf "%sMP_struct\n%!" prefix
    | MP_vector _ ->
        Printf.printf "%sMP_vector\n%!" prefix
    | MP_vector_concat _ ->
        Printf.printf "%sMP_vector_concat\n%!" prefix
    | MP_vector_subrange _ ->
        Printf.printf "%sMP_vector_subrange\n%!" prefix

end

(* Upgrade D extension FP data paths from 32-bit to 64-bit.
   Applied to any instruction whose name contains "_D_" or ends with "_D". *)
let upgrade_d_fp_widths (graph : rg_graph) : rg_graph =
  let has_suffix s dn =
    let len_s = String.length s in
    String.length dn >= len_s && String.sub dn (String.length dn - len_s) len_s = s in
  let has_sub s dn =
    try let _ = Str.search_forward (Str.regexp_string s) dn 0 in true
    with Not_found -> false in
  (* Identify fp_operations that need 64-bit treatment:
     - Operators ending with _d (fp_add_d, fp_sqrt_d, etc.)
     - Operators producing double output (fp_cvt_d_s, fp_cvt_d_w, fp_cvt_d_wu)
     - Operators with double input needing 64-bit CVFPU (fp_cvt_s_d, fp_cvt_w_d, fp_cvt_wu_d) *)
  let is_d_fp_op op =
    has_suffix "_d" op ||
    has_sub "fp_cvt_d_" op ||
    has_sub "fp_cvt_s_d" op || has_sub "fp_cvt_w_d" op || has_sub "fp_cvt_wu_d" op in
  let d_fp_op_ids = List.filter_map (fun n ->
    if n.node_type = "fp_operation" then
      match n.operator with
      | Some op when is_d_fp_op op -> Some n.id
      | _ -> None
    else None
  ) graph.nodes in
  let has_d_ops = d_fp_op_ids <> [] in
  (* Also check if instruction name implies D extension (frf should be 64-bit) *)
  let has_d_frf = List.exists (fun n ->
    n.display_name = Some "frf" && n.node_type = "isa_state" && n.bit_width = Some 64
  ) graph.nodes in
  if not has_d_ops && not has_d_frf then graph
  else begin
    let nodes = List.map (fun n ->
      let dn = Option.value ~default:"" n.display_name in
      (* Upgrade frf isa_state *)
      if n.display_name = Some "frf" && n.node_type = "isa_state" then
        { n with bit_width = Some 64; dimensions = Some [(63, 0); (4, 0)] }
      (* Upgrade frf array access/write *)
      else if (n.node_type = "array_access" || n.node_type = "array_write") &&
              (n.bit_width = None || n.bit_width = Some 32) &&
              (String.length dn >= 4 && String.sub dn 0 4 = "frf[") then
        { n with bit_width = Some 64 }
      (* Upgrade vars with _val_64b, _val_D, _rd_val_64b, _rd_val_D suffix *)
      else if n.node_type = "var" &&
              (n.bit_width = None || n.bit_width = Some 32) &&
              (has_suffix "_val_64b" dn || has_suffix "_val_D" dn ||
               has_suffix "_rd_val_64b" dn || has_suffix "_rd_val_D" dn) then
        { n with bit_width = Some 64 }
      (* Upgrade fp_operations with _d suffix: packed width += 32 (32->64 for value portion) *)
      else if n.node_type = "fp_operation" && List.mem n.id d_fp_op_ids then
        let old_bw = Option.value ~default:37 n.bit_width in
        { n with bit_width = Some (old_bw + 32) }
      (* Upgrade fp_value bit_slices from 32 to 64 *)
      else if n.node_type = "bit_slice" &&
              (n.bit_width = None || n.bit_width = Some 32) &&
              has_sub "fp_value" dn then
        { n with bit_width = Some 64; bitslice = Some (63, 0) }
      (* Upgrade fp_flags bit_slices range from [36:32] to [68:64] *)
      else if n.node_type = "bit_slice" &&
              n.bit_width = Some 5 &&
              has_sub "fp_flags" dn &&
              n.bitslice = Some (36, 32) then
        { n with bitslice = Some (68, 64) }
      (* Upgrade multiplexer nodes carrying packed D FP results *)
      else if n.node_type = "multiplexer" && n.bit_width = Some 37 &&
              List.exists (fun e ->
                e.target = n.id &&
                (let et = e.edge_type in
                 et = "mux_input" ||
                 (String.length et > 10 && String.sub et 0 10 = "mux_input:")) &&
                List.mem e.source d_fp_op_ids
              ) graph.edges then
        { n with bit_width = Some 69 }
      else n
    ) graph.nodes in
    { graph with nodes = nodes }
  end

(* JSON serialization *)
let node_to_json (n : rg_node) =
  let open JSON in
  let bitslice_json = match n.bitslice with
    | Some (high, low) -> Some (array [int high; int low])
    | None -> None
  in
  let dimensions_json = match n.dimensions with
    | Some dims -> Some (array (List.map (fun (high, low) -> array [int high; int low]) dims))
    | None -> None
  in
  (* For sized_literal nodes, emit 'width' as alias for 'bit_width' (Verilog generator uses 'width') *)
  (* For fp_operation nodes, emit 'fp_intrinsic' as alias for 'operator' (Verilog generator uses 'fp_intrinsic') *)
  let extra_data_fields =
    if n.node_type = "sized_literal" then
      match n.bit_width with
      | Some bw -> [field "width" (int bw)]
      | None -> []
    else if n.node_type = "fp_operation" then
      let fp_fields = match n.operator with
      | Some op -> [field "fp_intrinsic" (string op)]
      | None -> [] in
      (* Add value_bits = bit_width - 5 (packed result is {5-bit flags, value_bits result}) *)
      let vb_fields = match n.bit_width with
      | Some bw when bw > 5 -> [field "value_bits" (int (bw - 5))]
      | _ -> [] in
      fp_fields @ vb_fields
    else []
  in
  obj [
    field "id" (string n.id);
    field "data" (obj ([
      field "type" (string n.node_type);
      field "name" (option string n.name);
      field "display_name" (option string n.display_name);
      field "operator" (option string n.operator);
      field "value" (option string n.value);
      field "bit_width" (option int n.bit_width);
      field "is_memory" (bool n.is_memory);
      field "array_size" (option int n.array_size);
      field "array_depth" (option int n.array_depth);
      field "bitslice" (option (fun x -> x) bitslice_json);
      field "dimensions" (option (fun x -> x) dimensions_json);
    ] @ extra_data_fields));
    (* ResourceGraph metadata fields at top level *)
    field "is_arch_state" (bool n.is_arch_state);
    field "is_uarch_state" (bool false);  (* SAIL doesn't track this *)
    field "used_as_index" (bool false);   (* SAIL doesn't track this *)
    field "indexed_by" (option string None);  (* JSON null - will be set by ResourceGraph if needed *)
    field "uarch_time" (int 0);           (* Default *)
    field "latency" (int 1);              (* Default *)
    field "variable_latency" (bool false) (* Default *)
  ]

let edge_to_json (e : rg_edge) =
  let open JSON in
  (* Parse edge types like "mux_input:0" to extract input_index *)
  let edge_type, extra_fields =
    if String.contains e.edge_type ':' then
      let parts = String.split_on_char ':' e.edge_type in
      match parts with
      | [typ; idx] ->
          (typ, [field "input_index" (int (int_of_string idx))])
      | _ -> (e.edge_type, [])
    else
      (e.edge_type, [])
  in
  (* Add position field if present *)
  let extra_fields = match e.position with
    | Some pos -> (field "position" (string pos)) :: extra_fields
    | None -> extra_fields
  in
  (* Add enable field if present *)
  let extra_fields = match e.enable with
    | Some en -> (field "enable" (string en)) :: extra_fields
    | None -> extra_fields
  in
  obj [
    field "id" (string e.id);
    field "source" (string e.source);
    field "target" (string e.target);
    field "data" (obj (
      (field "type" (string edge_type)) :: extra_fields
    ))
  ]

let decode_constraint_to_json (dc : decode_constraint) =
  let open JSON in
  let base = [
    field "high_bit" (int dc.high_bit);
    field "low_bit" (int dc.low_bit);
    field "value" (string dc.value);
  ] in
  let fields = if dc.operator = "!=" then
    base @ [field "operator" (string "!=")]
  else
    base
  in
  obj fields

(* Normalize node types to match what the .isa parser produces.
   The Verilog generator and graph merger expect specific type names. *)
let normalize_graph (graph : rg_graph) : rg_graph =
  let normalize_node (n : rg_node) : rg_node =
    match n.node_type with
    | "constant" ->
        (* constant -> literal: downstream expects 'literal' with int value *)
        { n with node_type = "literal" }
    | "comparison" ->
        (* comparison -> operation: .isa parser emits operations with == != operators *)
        { n with node_type = "operation" }
    | "logical_and" ->
        (* logical_and -> operation: keep operator as && *)
        { n with node_type = "operation";
                 operator = (match n.operator with Some _ -> n.operator | None -> Some "&&") }
    | "concat" ->
        (* concat -> concatenation: match .isa parser naming *)
        { n with node_type = "concatenation" }
    | "conditional" ->
        (* conditional -> ternary_op: match .isa parser naming *)
        { n with node_type = "ternary_op" }
    | "sign_extend" ->
        (* Keep as sign_extend: Verilog generator has dedicated sign_extend handler *)
        { n with operator = Some "sign_extend" }
    | "zero_extend" ->
        (* Keep as zero_extend: Verilog generator has dedicated zero_extend handler *)
        { n with operator = Some "zero_extend" }
    | "operation" when n.operator = Some "sign_extend" ->
        (* operation with sign_extend operator -> sign_extend type *)
        { n with node_type = "sign_extend" }
    | "operation" when n.operator = Some "zero_extend" ->
        (* operation with zero_extend operator -> zero_extend type *)
        { n with node_type = "zero_extend" }
    | "pc_update" ->
        (* pc_update -> operation: PC target computation *)
        { n with node_type = "operation" }
    | "verilog_hex_literal" ->
        (* verilog_hex_literal -> sized_literal: match .isa parser naming *)
        { n with node_type = "sized_literal" }
    | "binary_literal" ->
        (* binary_literal -> literal *)
        { n with node_type = "literal" }
    | "array_write" ->
        (* array_write -> array_access: .isa uses array_access for both read/write *)
        { n with node_type = "array_access" }
    | "operation" when n.operator = Some "concat" ->
        (* operation with concat operator -> concatenation *)
        { n with node_type = "concatenation" }
    | "operation" when n.operator = Some "bitvector_concat" ->
        (* bitvector_concat -> concatenation: SAIL's append operator *)
        { n with node_type = "concatenation" }
    | _ -> n
  in
  let normalize_edge (e : rg_edge) : rg_edge =
    match e.edge_type with
    | "definition" ->
        (* definition -> assignment: .isa parser uses assignment *)
        { e with edge_type = "assignment" }
    | "logic_input" ->
        (* logic_input -> operand: inputs to logical operations *)
        { e with edge_type = "operand" }
    | "argument" ->
        (* argument -> operand: function arguments become operands *)
        { e with edge_type = "operand" }
    | "condition" ->
        (* condition -> ternary_condition: E_if condition edge *)
        { e with edge_type = "ternary_condition" }
    | "then_branch" ->
        (* then_branch -> ternary_true: E_if true branch *)
        { e with edge_type = "ternary_true" }
    | "else_branch" ->
        (* else_branch -> ternary_false: E_if false branch *)
        { e with edge_type = "ternary_false" }
    | _ -> e
  in
  (* Normalize nodes and apply default bit_width=32 for RV32 *)
  let normalized_nodes = List.map (fun n ->
    let n = normalize_node n in
    (* Default bit_width to 32 for nodes that lack it *)
    match n.bit_width with
    | None when List.mem n.node_type ["multiplexer"; "var"; "ternary_op"; "operation"; "array_access"] ->
        { n with bit_width = Some 32 }
    | _ -> n
  ) graph.nodes in

  (* Canonicalize pc_plus_4 node: rename (pc_rd + 4) operation to stable ID
     so the merger can share it across instructions *)
  let pc_plus_4_old_id = ref None in
  let pc_plus_4_lit_old_id = ref None in
  List.iter (fun n ->
    if n.node_type = "operation" && n.operator = Some "+" &&
       n.display_name = Some "(pc_rd + 4)" then
      pc_plus_4_old_id := Some n.id
  ) normalized_nodes;
  (* Find the literal '4' feeding pc_plus_4 *)
  (match !pc_plus_4_old_id with
   | Some old_id ->
       List.iter (fun edge ->
         if edge.target = old_id then
           List.iter (fun (nd : rg_node) ->
             if nd.id = edge.source && nd.node_type = "literal" &&
                (nd.value = Some "4" || nd.value = Some "0x4") then
               pc_plus_4_lit_old_id := Some nd.id
           ) normalized_nodes
       ) graph.edges
   | None -> ());

  let rename_id id =
    if Some id = !pc_plus_4_old_id then "pc_plus_4"
    else if Some id = !pc_plus_4_lit_old_id then "pc_plus_4_lit"
    else id
  in
  let normalized_nodes = List.map (fun (n : rg_node) ->
    { n with id = rename_id n.id }
  ) normalized_nodes in

  (* Build node type map for edge normalization *)
  let node_type_map = List.fold_left (fun acc (n : rg_node) ->
    (n.id, n.node_type) :: acc
  ) [] normalized_nodes in
  let get_node_type id =
    match List.assoc_opt id node_type_map with
    | Some t -> t | None -> ""
  in
  (* Build node info maps for identifying rounding mode sources *)
  let node_operator_map = List.fold_left (fun acc (n : rg_node) ->
    (n.id, Option.value ~default:"" n.operator) :: acc
  ) [] normalized_nodes in
  let get_node_operator id =
    match List.assoc_opt id node_operator_map with
    | Some op -> op | None -> ""
  in
  let node_display_name_map = List.fold_left (fun acc (n : rg_node) ->
    (n.id, Option.value ~default:"" n.display_name) :: acc
  ) [] normalized_nodes in
  let is_rounding_mode_source id =
    let op = get_node_operator id in
    let dn = match List.assoc_opt id node_display_name_map with Some s -> s | None -> "" in
    op = "rounding_mode" ||
    (let len = String.length dn in
     (len >= 5 && String.sub dn (len - 5) 5 = "rm_3b") ||
     (len >= 3 && String.sub dn (len - 3) 3 = "_rm"))
  in

  (* Collect IDs of nodes that are now concatenation type *)
  let is_concat_target id = get_node_type id = "concatenation" in

  (* Normalize edges with full context *)
  let normalized_edges = List.filter_map (fun e ->
    let e = normalize_edge e in
    let e = { e with source = rename_id e.source; target = rename_id e.target } in
    (* Drop state_update edges *)
    if e.edge_type = "state_update" then None
    (* Drop value edges targeting isa_state (back-edges) *)
    else if e.edge_type = "value" && get_node_type e.target = "isa_state" then None
    else begin
      let e =
        (* value -> assignment for var targets *)
        if e.edge_type = "value" && get_node_type e.target = "var" then
          { e with edge_type = "assignment" }
        (* value -> fp_operand/rounding_mode for fp_operation targets *)
        else if e.edge_type = "value" && get_node_type e.target = "fp_operation" then
          if is_rounding_mode_source e.source then
            { e with edge_type = "rounding_mode" }
          else
            { e with edge_type = "fp_operand" }
        (* value -> operand for operation/comparison/bit_slice targets *)
        else if e.edge_type = "value" &&
                List.mem (get_node_type e.target) ["operation"; "bit_slice"; "concatenation"] then
          { e with edge_type = "operand" }
        (* operand -> fp_operand/rounding_mode for fp_operation targets *)
        else if e.edge_type = "operand" && get_node_type e.target = "fp_operation" then
          if is_rounding_mode_source e.source then
            { e with edge_type = "rounding_mode" }
          else
            { e with edge_type = "fp_operand" }
        (* operand -> concat_input for concatenation targets *)
        else if e.edge_type = "operand" && is_concat_target e.target then
          { e with edge_type = "concat_input" }
        else e
      in
      Some e
    end
  ) graph.edges in

  (* Convert 2-input multiplexers to ternary_op nodes.
     SAIL produces if-then-else and 2-arm match as multiplexer with control + mux_input:0/1.
     The Verilog generator's case statement treats mux_input[0] as "control==0" which inverts
     boolean if-then-else semantics. Converting to ternary_op with explicit true/false edges
     avoids this mismatch.
     - For operator="ite": mux_input[0]=true_branch, mux_input[1]=false_branch
     - For operator="match": mux_input[0]=case_0 (false), mux_input[1]=case_1 (true) *)
  let mux_node_ids = List.filter_map (fun (n : rg_node) ->
    if n.node_type = "multiplexer" then Some n.id else None
  ) normalized_nodes in
  (* For each mux node, count mux_input edges and check for control edge *)
  let mux_info = List.filter_map (fun mux_id ->
    let control_edge = ref None in
    let mux_inputs = Hashtbl.create 4 in
    List.iter (fun e ->
      if e.target = mux_id then begin
        if e.edge_type = "control" then control_edge := Some e
        else begin
          (* Check for mux_input or mux_input:N *)
          let is_mux_input, idx =
            if e.edge_type = "mux_input" then (true, -1)
            else if String.length e.edge_type > 10 &&
                    String.sub e.edge_type 0 10 = "mux_input:" then
              let idx_str = String.sub e.edge_type 10 (String.length e.edge_type - 10) in
              (try (true, int_of_string idx_str)
               with Failure _ -> (false, -1))
            else (false, -1)
          in
          if is_mux_input then Hashtbl.replace mux_inputs idx e
        end
      end
    ) normalized_edges;
    match !control_edge with
    | Some ctrl when Hashtbl.length mux_inputs = 2 &&
                     Hashtbl.mem mux_inputs 0 && Hashtbl.mem mux_inputs 1 ->
        (* Find the node to get operator *)
        let op = List.find_opt (fun (n : rg_node) -> n.id = mux_id) normalized_nodes in
        let is_match = match op with
          | Some n -> n.operator = Some "match"
          | None -> false
        in
        Some (mux_id, ctrl, Hashtbl.find mux_inputs 0, Hashtbl.find mux_inputs 1, is_match)
    | _ -> None
  ) mux_node_ids in

  (* Convert identified 2-input muxes *)
  let converted_mux_ids = List.map (fun (id, _, _, _, _) -> id) mux_info in
  let normalized_nodes = List.map (fun (n : rg_node) ->
    if List.mem n.id converted_mux_ids then
      { n with node_type = "ternary_op"; operator = Some "?:" }
    else n
  ) normalized_nodes in
  let normalized_edges = List.map (fun e ->
    match List.find_opt (fun (_mux_id, ctrl, inp0, inp1, _is_match) ->
      e.id = ctrl.id || e.id = inp0.id || e.id = inp1.id
    ) mux_info with
    | Some (_mux_id, ctrl, inp0, inp1, is_match) ->
        if e.id = ctrl.id then { e with edge_type = "ternary_condition" }
        else if e.id = inp0.id then
          (* For match: input[0] = case 0 = false; for ite: input[0] = true branch *)
          { e with edge_type = (if is_match then "ternary_false" else "ternary_true") }
        else if e.id = inp1.id then
          { e with edge_type = (if is_match then "ternary_true" else "ternary_false") }
        else e
    | None -> e
  ) normalized_edges in

  (* Fix op_select mapping: reassign selector literal values so they match
     the execute match arm indices (mux_input:N). The decode handler assigns
     values in encdec clause order, but mux_input indices follow the execute
     match arm order, which may differ. *)
  let normalized_nodes =
    (* Build adjacency maps *)
    let edges_to_target = Hashtbl.create 64 in
    let edges_from_source = Hashtbl.create 64 in
    List.iter (fun e ->
      let existing_to = try Hashtbl.find edges_to_target e.target with Not_found -> [] in
      Hashtbl.replace edges_to_target e.target (e :: existing_to);
      let existing_from = try Hashtbl.find edges_from_source e.source with Not_found -> [] in
      Hashtbl.replace edges_from_source e.source (e :: existing_from)
    ) normalized_edges;
    let node_map = Hashtbl.create 64 in
    List.iter (fun (n : rg_node) -> Hashtbl.replace node_map n.id n) normalized_nodes;

    (* Find multiplexer nodes with 3+ mux_input edges *)
    let case_muxes = List.filter_map (fun (n : rg_node) ->
      if n.node_type <> "multiplexer" then None
      else begin
        let incoming = try Hashtbl.find edges_to_target n.id with Not_found -> [] in
        let control_src = List.find_map (fun e ->
          if e.edge_type = "control" then Some e.source else None
        ) incoming in
        let mux_input_count = List.length (List.filter (fun e ->
          String.length e.edge_type > 10 &&
          String.sub e.edge_type 0 10 = "mux_input:"
        ) incoming) in
        match control_src with
        | Some ctrl_id when mux_input_count >= 3 -> Some (n.id, ctrl_id)
        | _ -> None
      end
    ) normalized_nodes in

    (* For each case mux, fix selector values *)
    let value_fixes = Hashtbl.create 16 in
    List.iter (fun (_mux_id, ctrl_id) ->
      (* Find pattern variables: nodes where ctrl_id -> var via definition/assignment *)
      let outgoing = try Hashtbl.find edges_from_source ctrl_id with Not_found -> [] in
      let pattern_vars = List.filter_map (fun e ->
        if e.edge_type = "definition" || e.edge_type = "assignment" then
          match Hashtbl.find_opt node_map e.target with
          | Some tgt ->
              (match tgt.display_name with
               | Some dn when String.contains dn '_' -> Some (tgt.id, dn)
               | _ -> None)
          | None -> None
        else None
      ) outgoing in

      if pattern_vars = [] then ()
      else begin
        (* Sort by node ID numeric suffix to get match arm order *)
        let sorted_vars = List.sort (fun (id1, _) (id2, _) ->
          let num_of id =
            let s = String.to_seq id |> Seq.filter (fun c -> c >= '0' && c <= '9')
                    |> String.of_seq in
            try int_of_string s with Failure _ -> 0
          in
          compare (num_of id1) (num_of id2)
        ) pattern_vars in

        (* Extract op_name -> mux_input_index *)
        let op_to_idx = Hashtbl.create 16 in
        List.iteri (fun idx (_, dn) ->
          match String.split_on_char '_' dn with
          | _ :: rest when rest <> [] ->
              let op_name = String.concat "_" rest in
              Hashtbl.replace op_to_idx op_name idx
          | _ -> ()
        ) sorted_vars;

        if Hashtbl.length op_to_idx = 0 then ()
        else begin
          (* Find the ternary chain feeding the control var *)
          let ctrl_incoming = try Hashtbl.find edges_to_target ctrl_id with Not_found -> [] in
          let chain_source = List.find_map (fun e ->
            if e.edge_type = "assignment" || e.edge_type = "value" then Some e.source
            else None
          ) ctrl_incoming in

          (* Walk the ternary chain collecting op_X literal nodes *)
          let rec walk_chain node_id =
            match Hashtbl.find_opt node_map node_id with
            | Some n when n.node_type = "ternary_op" ->
                let incoming = try Hashtbl.find edges_to_target node_id with Not_found -> [] in
                let true_src = List.find_map (fun e ->
                  if e.edge_type = "ternary_true" then Some e.source else None
                ) incoming in
                let false_src = List.find_map (fun e ->
                  if e.edge_type = "ternary_false" then Some e.source else None
                ) incoming in
                (* Collect true branch literal *)
                (match true_src with
                 | Some src_id ->
                     (match Hashtbl.find_opt node_map src_id with
                      | Some lit when lit.node_type = "literal" || lit.node_type = "constant" ->
                          (match lit.display_name with
                           | Some dn when String.length dn > 3 && String.sub dn 0 3 = "op_" ->
                               let op_name = String.sub dn 3 (String.length dn - 3) in
                               (match Hashtbl.find_opt op_to_idx op_name with
                                | Some idx -> Hashtbl.replace value_fixes src_id (string_of_int idx)
                                | None -> ())
                           | _ -> ())
                      | _ -> ())
                 | None -> ());
                (* Continue down false branch *)
                (match false_src with
                 | Some fid -> walk_chain fid
                 | None -> ())
            | Some n when n.node_type = "literal" || n.node_type = "constant" ->
                (* Default/last literal in chain *)
                (match n.display_name with
                 | Some dn when String.length dn > 3 && String.sub dn 0 3 = "op_" ->
                     let op_name = String.sub dn 3 (String.length dn - 3) in
                     (match Hashtbl.find_opt op_to_idx op_name with
                      | Some idx -> Hashtbl.replace value_fixes node_id (string_of_int idx)
                      | None -> ())
                 | _ -> ())
            | _ -> ()
          in
          (match chain_source with
           | Some src -> walk_chain src
           | None -> ())
        end
      end
    ) case_muxes;

    (* Apply value fixes *)
    if Hashtbl.length value_fixes > 0 then
      List.map (fun (n : rg_node) ->
        match Hashtbl.find_opt value_fixes n.id with
        | Some new_val -> { n with value = Some new_val }
        | None -> n
      ) normalized_nodes
    else
      normalized_nodes
  in

  (* Dead-code elimination: remove multiplexer nodes with no outgoing edges.
     These are typically the return-value mux from SAIL's execute function
     (e.g. selecting between RETIRE_SUCCESS / internal_error), which is
     dead for store instructions. *)
  let outgoing_sources = List.fold_left (fun acc e ->
    let existing = try Hashtbl.find acc e.source with Not_found -> 0 in
    Hashtbl.replace acc e.source (existing + 1); acc
  ) (Hashtbl.create 64) normalized_edges in
  let dead_mux_ids = List.filter_map (fun (n : rg_node) ->
    if n.node_type = "multiplexer" &&
       (try Hashtbl.find outgoing_sources n.id with Not_found -> 0) = 0
    then Some n.id
    else None
  ) normalized_nodes in
  let normalized_nodes, normalized_edges =
    if dead_mux_ids = [] then (normalized_nodes, normalized_edges)
    else begin
      Printf.printf "  Removing %d dead multiplexer node(s)\n%!" (List.length dead_mux_ids);
      let is_dead id = List.mem id dead_mux_ids in
      let nodes = List.filter (fun (n : rg_node) -> not (is_dead n.id)) normalized_nodes in
      let edges = List.filter (fun e -> not (is_dead e.target)) normalized_edges in
      (nodes, edges)
    end
  in

  (* Connect undriven register variable nodes to instruction bit slices.
     FP instruction patterns from SAIL have var nodes for rd, rs1, rs2, rs3
     that are used as array indices (e.g. frf[rd]) but never assigned from
     instruction bits.  Integer patterns get bit_slice nodes from the decode
     clause, but FP patterns only get bare var nodes.  We create bit_slice
     nodes for each unconnected register var and wire them up. *)
  let target_set = Hashtbl.create 64 in
  List.iter (fun e -> Hashtbl.replace target_set e.target true) normalized_edges;
  let reg_bit_ranges = [("rd", 11, 7); ("rs1", 19, 15); ("rs2", 24, 20); ("rs3", 31, 27); ("rm", 14, 12)] in
  let instr_node_id = List.find_map (fun (n : rg_node) ->
    if n.node_type = "var" && n.display_name = Some "instr" then Some n.id
    else None
  ) normalized_nodes in
  let normalized_nodes, normalized_edges =
    match instr_node_id with
    | None -> (normalized_nodes, normalized_edges)
    | Some instr_id ->
        (* Find unconnected register vars *)
        let unconnected_reg_vars = List.filter (fun (n : rg_node) ->
          n.node_type = "var" &&
          (match n.display_name with
           | Some dn -> List.exists (fun (rn, _, _) ->
               dn = rn ||
               (let suffix = "_" ^ rn in
                let slen = String.length suffix in
                let dlen = String.length dn in
                dlen > slen && String.sub dn (dlen - slen) slen = suffix)
             ) reg_bit_ranges
           | None -> false) &&
          not (Hashtbl.mem target_set n.id)
        ) normalized_nodes in
        if unconnected_reg_vars = [] then (normalized_nodes, normalized_edges)
        else begin
          Printf.printf "  Connecting %d undriven register var(s) to instruction bits\n%!" (List.length unconnected_reg_vars);
          let new_nodes = ref [] in
          let new_edges = ref [] in
          let counter = ref 0 in
          List.iter (fun (n : rg_node) ->
            let dn = Option.get n.display_name in
            let (_, hi, lo) = List.find (fun (rn, _, _) ->
              dn = rn ||
              (let suffix = "_" ^ rn in
               let slen = String.length suffix in
               let dlen = String.length dn in
               dlen > slen && String.sub dn (dlen - slen) slen = suffix)
            ) reg_bit_ranges in
            let slice_id = Printf.sprintf "%s_bitslice_%d" n.id !counter in
            incr counter;
            let slice_node = {
              id = slice_id;
              node_type = "bit_slice";
              name = Some dn;
              display_name = Some dn;
              operator = None;
              value = None;
              bit_width = Some (hi - lo + 1);
              is_arch_state = false;
              is_memory = false;
              array_size = None;
              array_depth = None;
              bitslice = Some (hi, lo);
              dimensions = None;
            } in
            let edge_from_instr = {
              id = Printf.sprintf "e_%s_to_%s" instr_id slice_id;
              source = instr_id;
              target = slice_id;
              edge_type = "bit_access";
              position = None;
              enable = None;
            } in
            let edge_to_var = {
              id = Printf.sprintf "e_%s_to_%s" slice_id n.id;
              source = slice_id;
              target = n.id;
              edge_type = "assignment";
              position = None;
              enable = None;
            } in
            new_nodes := slice_node :: !new_nodes;
            new_edges := edge_from_instr :: edge_to_var :: !new_edges;
            Printf.printf "    %s (%s) <- instr[%d:%d]\n%!" n.id dn hi lo
          ) unconnected_reg_vars;
          (normalized_nodes @ !new_nodes, normalized_edges @ !new_edges)
        end
  in

  (* Connect undriven FP operation selector vars to instruction bits.
     F_BIN_RM_TYPE_S has an 'op' var (selects FADD/FSUB/FMUL/FDIV) that maps
     to instr[28:27].  F_MADD_TYPE_S has an 'op' var (selects FMADD/FMSUB/
     FNMADD/FNMSUB) that maps to instr[3:2]. *)
  let target_set_op = Hashtbl.create 64 in
  List.iter (fun e -> Hashtbl.replace target_set_op e.target true) normalized_edges;
  let normalized_nodes, normalized_edges =
    match instr_node_id with
    | None -> (normalized_nodes, normalized_edges)
    | Some instr_id ->
        (* Pattern-specific op bit ranges *)
        let op_bit_ranges = [
          ("f_bin_rm_type_s_op", 28, 27);   (* FADD=00, FSUB=01, FMUL=10, FDIV=11 *)
          ("f_bin_rm_type_d_op", 28, 27);   (* D extension: same bit positions *)
          ("f_madd_type_s_op", 3, 2);       (* FMADD=00, FMSUB=01, FNMSUB=10, FNMADD=11 *)
          ("f_madd_type_d_op", 3, 2);       (* D extension: same bit positions *)
        ] in
        let unconnected_ops = List.filter (fun (n : rg_node) ->
          n.node_type = "var" &&
          (match n.display_name with
           | Some dn -> List.exists (fun (rn, _, _) -> dn = rn) op_bit_ranges
           | None -> false) &&
          not (Hashtbl.mem target_set_op n.id)
        ) normalized_nodes in
        if unconnected_ops = [] then (normalized_nodes, normalized_edges)
        else begin
          Printf.printf "  Connecting %d undriven FP op selector(s) to instruction bits\n%!" (List.length unconnected_ops);
          let new_nodes = ref [] in
          let new_edges = ref [] in
          let counter = ref 0 in
          List.iter (fun (n : rg_node) ->
            let dn = Option.get n.display_name in
            let (_, hi, lo) = List.find (fun (rn, _, _) -> dn = rn) op_bit_ranges in
            let slice_id = Printf.sprintf "%s_op_bitslice_%d" n.id !counter in
            incr counter;
            let slice_node = {
              id = slice_id;
              node_type = "bit_slice";
              name = Some dn;
              display_name = Some dn;
              operator = None;
              value = None;
              bit_width = Some (hi - lo + 1);
              is_arch_state = false;
              is_memory = false;
              array_size = None;
              array_depth = None;
              bitslice = Some (hi, lo);
              dimensions = None;
            } in
            let edge_from_instr = {
              id = Printf.sprintf "e_%s_to_%s" instr_id slice_id;
              source = instr_id;
              target = slice_id;
              edge_type = "bit_access";
              position = None;
              enable = None;
            } in
            let edge_to_var = {
              id = Printf.sprintf "e_%s_to_%s" slice_id n.id;
              source = slice_id;
              target = n.id;
              edge_type = "assignment";
              position = None;
              enable = None;
            } in
            new_nodes := slice_node :: !new_nodes;
            new_edges := edge_from_instr :: edge_to_var :: !new_edges;
            Printf.printf "    %s (%s) <- instr[%d:%d]\n%!" n.id dn hi lo
          ) unconnected_ops;
          (normalized_nodes @ !new_nodes, normalized_edges @ !new_edges)
        end
  in

  (* Reconstruct S-type store immediates for FP store patterns.
     The S-type immediate is split: imm[11:5]=instr[31:25], imm[4:0]=instr[11:7].
     Integer store patterns get this from the SAIL decode, but FP store patterns
     have unconnected *_imm vars.  Create the concatenation and wire it up. *)
  let target_set2 = Hashtbl.create 64 in
  List.iter (fun e -> Hashtbl.replace target_set2 e.target true) normalized_edges;
  let normalized_nodes, normalized_edges =
    match instr_node_id with
    | None -> (normalized_nodes, normalized_edges)
    | Some instr_id ->
        (* Find unconnected store imm vars *)
        let store_imm_vars = List.filter (fun (n : rg_node) ->
          n.node_type = "var" &&
          (match n.display_name with
           | Some dn ->
               let len = String.length dn in
               len > 4 && String.sub dn (len - 4) 4 = "_imm" &&
               (let prefix = String.lowercase_ascii dn in
                let has s = try ignore (Str.search_forward (Str.regexp_string s) prefix 0); true with Not_found -> false in
                has "store")
           | None -> false) &&
          not (Hashtbl.mem target_set2 n.id)
        ) normalized_nodes in
        if store_imm_vars = [] then (normalized_nodes, normalized_edges)
        else begin
          Printf.printf "  Reconstructing %d S-type store immediate(s)\n%!" (List.length store_imm_vars);
          let new_nodes = ref [] in
          let new_edges = ref [] in
          let counter = ref 0 in
          List.iter (fun (n : rg_node) ->
            let dn = Option.value ~default:"" n.display_name in
            let hi_id = Printf.sprintf "%s_stype_hi_%d" n.id !counter in
            let lo_id = Printf.sprintf "%s_stype_lo_%d" n.id !counter in
            let cat_id = Printf.sprintf "%s_stype_cat_%d" n.id !counter in
            incr counter;
            (* instr[31:25] — upper 7 bits *)
            let hi_node = {
              id = hi_id; node_type = "bit_slice"; name = Some "instr[31:25]";
              display_name = Some "instr[31:25]"; operator = None; value = None;
              bit_width = Some 7; is_arch_state = false; is_memory = false;
              array_size = None; array_depth = None; bitslice = Some (31, 25);
              dimensions = None;
            } in
            (* instr[11:7] — lower 5 bits *)
            let lo_node = {
              id = lo_id; node_type = "bit_slice"; name = Some "instr[11:7]";
              display_name = Some "instr[11:7]"; operator = None; value = None;
              bit_width = Some 5; is_arch_state = false; is_memory = false;
              array_size = None; array_depth = None; bitslice = Some (11, 7);
              dimensions = None;
            } in
            (* Concatenation: hi @ lo = 12-bit S-type immediate *)
            let cat_node = {
              id = cat_id; node_type = "concatenation"; name = Some "stype_imm_concat";
              display_name = Some "stype_imm_concat"; operator = None; value = None;
              bit_width = Some 12; is_arch_state = false; is_memory = false;
              array_size = None; array_depth = None; bitslice = None;
              dimensions = None;
            } in
            new_nodes := hi_node :: lo_node :: cat_node :: !new_nodes;
            new_edges := [
              { id = Printf.sprintf "e_%s_hi" n.id; source = instr_id; target = hi_id;
                edge_type = "bit_access"; position = None; enable = None };
              { id = Printf.sprintf "e_%s_lo" n.id; source = instr_id; target = lo_id;
                edge_type = "bit_access"; position = None; enable = None };
              { id = Printf.sprintf "e_%s_cat_hi" n.id; source = hi_id; target = cat_id;
                edge_type = "concat_input"; position = Some "left"; enable = None };
              { id = Printf.sprintf "e_%s_cat_lo" n.id; source = lo_id; target = cat_id;
                edge_type = "concat_input"; position = Some "right"; enable = None };
              { id = Printf.sprintf "e_%s_assign" n.id; source = cat_id; target = n.id;
                edge_type = "assignment"; position = None; enable = None };
            ] @ !new_edges;
            Printf.printf "    %s (%s) <- {instr[31:25], instr[11:7]}\n%!" n.id dn
          ) store_imm_vars;
          (normalized_nodes @ !new_nodes, normalized_edges @ !new_edges)
        end
  in

  (* Fix width bit_slice nodes: expand from [13:12] to [14:12].
     The SAIL size_enc mapping uses 3 bits (funct3 field) but the extractor
     may only extract 2 bits based on the word_width type's bit width.
     WORD is encoded as 010 (=2 in 3 bits, but only 01=1 in 2 bits). *)
  let normalized_nodes = List.map (fun (n : rg_node) ->
    if n.node_type = "bit_slice" && n.display_name = Some "width" &&
       n.bitslice = Some (13, 12) then begin
      Printf.printf "  Fixing width bitslice: [13:12] -> [14:12]\n%!";
      { n with bitslice = Some (14, 12); bit_width = Some 3 }
    end
    else n
  ) normalized_nodes in

  (* Eliminate nan_box operations for RV32F.
     In SAIL, nan_box pads upper bits with 1s when FLEN > width*8.
     For RV32F (FLEN=32, width=4 bytes), nan_box is identity.
     The extractor produces: nan_box(shift_amount, data) -> data
     We replace nan_box nodes with a direct pass-through of the data operand. *)
  let nan_box_ids = List.filter_map (fun (n : rg_node) ->
    if n.node_type = "operation" && n.operator = Some "nan_box" then Some n.id
    else None
  ) normalized_nodes in
  let normalized_nodes, normalized_edges =
    if nan_box_ids = [] then (normalized_nodes, normalized_edges)
    else begin
      Printf.printf "  Eliminating %d nan_box operation(s) (identity for RV32F)\n%!" (List.length nan_box_ids);
      (* For each nan_box node, find the data operand (the second operand,
         which is the actual loaded value) and bypass the nan_box *)
      let bypass_map = Hashtbl.create 4 in
      List.iter (fun nb_id ->
        (* Find incoming operand edges - the data operand is the one from
           a var/array_access node, not the shift amount computation *)
        let incoming = List.filter (fun e ->
          e.target = nb_id && (e.edge_type = "operand" || e.edge_type = "value")
        ) normalized_edges in
        (* The data operand is the one from a var/array_access (the load result),
           not from an operation (the shift amount computation) *)
        let data_source = List.find_map (fun e ->
          let src_type = List.find_map (fun (n : rg_node) ->
            if n.id = e.source then Some n.node_type else None
          ) normalized_nodes in
          match src_type with
          | Some "var" | Some "array_access" -> Some e.source
          | _ -> None
        ) incoming in
        match data_source with
        | Some src_id -> Hashtbl.replace bypass_map nb_id src_id
        | None ->
            (* Fallback: use the operand with position "right" or the second one *)
            (match incoming with
             | [_; e2] -> Hashtbl.replace bypass_map nb_id e2.source
             | [e1] -> Hashtbl.replace bypass_map nb_id e1.source
             | _ -> ())
      ) nan_box_ids;
      (* Redirect edges: anything that sourced from a nan_box now sources from its data input *)
      let edges = List.filter_map (fun e ->
        if List.mem e.target nan_box_ids then
          (* Drop edges going INTO nan_box nodes *)
          None
        else if Hashtbl.mem bypass_map e.source then
          (* Redirect edges coming FROM nan_box to come from data source *)
          Some { e with source = Hashtbl.find bypass_map e.source }
        else
          Some e
      ) normalized_edges in
      let nodes = List.filter (fun (n : rg_node) ->
        not (List.mem n.id nan_box_ids)
      ) normalized_nodes in
      (nodes, edges)
    end
  in

  { nodes = normalized_nodes;
    edges = normalized_edges;
    decode_constraints = graph.decode_constraints }

(* Lower fp_split nodes into bit_slice operations.
   fp_split(val) produces 3 components: sign=val[31], exp=val[30:23], mant=val[22:0].
   We replace the fp_split node with 3 bit_slice nodes and rewire the outputs.
   The fp_split node's output edges go to var nodes for s, e, m (connected by position). *)
let lower_fp_split (graph : rg_graph) : rg_graph =
  let fp_splits = List.filter (fun (n : rg_node) ->
    n.node_type = "fp_operation" && n.operator = Some "fp_split"
  ) graph.nodes in
  if fp_splits = [] then graph
  else begin
    let remove_ids = Hashtbl.create 8 in
    let extra_nodes = ref [] in
    let extra_edges = ref [] in
    let remove_edges = Hashtbl.create 16 in
    let width_updates = Hashtbl.create 16 in  (* node_id -> new bit_width *)
    List.iter (fun (split_node : rg_node) ->
      Hashtbl.replace remove_ids split_node.id true;
      (* Find the input to this fp_split *)
      let input_edges = List.filter (fun (e : rg_edge) ->
        e.target = split_node.id && (e.edge_type = "operand" || e.edge_type = "fp_operand")
      ) graph.edges in
      let input_src = match input_edges with
        | e :: _ -> Some e.source
        | [] -> None
      in
      (* Find output edges from fp_split to var nodes *)
      let output_edges = List.filter (fun (e : rg_edge) ->
        e.source = split_node.id
      ) graph.edges in
      (* Mark all edges to/from fp_split for removal *)
      List.iter (fun (e : rg_edge) ->
        Hashtbl.replace remove_edges e.id true
      ) input_edges;
      List.iter (fun (e : rg_edge) ->
        Hashtbl.replace remove_edges e.id true
      ) output_edges;
      (* Create bit_slice nodes for sign, exp, mant *)
      match input_src with
      | Some src_id ->
          (* Determine which output var is sign/exp/mant by name *)
          List.iter (fun (e : rg_edge) ->
            let target_node = List.find_opt (fun (n : rg_node) ->
              n.id = e.target
            ) graph.nodes in
            match target_node with
            | Some tgt ->
                let dn = Option.value ~default:"" tgt.display_name in
                let (hi, lo, bw) =
                  if Str.string_match (Str.regexp ".*_s[0-9]*$") dn 0 ||
                     Str.string_match (Str.regexp ".*_sign$") dn 0 then
                    (31, 31, 1)  (* sign bit *)
                  else if Str.string_match (Str.regexp ".*_e[0-9]*$") dn 0 ||
                          Str.string_match (Str.regexp ".*_exp$") dn 0 then
                    (30, 23, 8)  (* exponent *)
                  else
                    (22, 0, 23)  (* mantissa *)
                in
                let slice_id = split_node.id ^ "_slice_" ^ string_of_int hi ^ "_" ^ string_of_int lo in
                let slice_node = {
                  id = slice_id;
                  node_type = "bit_slice";
                  name = Some (Printf.sprintf "[%d:%d]" hi lo);
                  display_name = Some (Printf.sprintf "%s[%d:%d]" (Option.value ~default:"val" tgt.display_name) hi lo);
                  operator = None;
                  value = None;
                  bit_width = Some bw;
                  is_arch_state = false;
                  is_memory = false;
                  array_size = None;
                  array_depth = None;
                  bitslice = Some (hi, lo);
                  dimensions = None;
                } in
                extra_nodes := slice_node :: !extra_nodes;
                (* Edge: input -> bit_slice *)
                extra_edges := { id = fresh_edge_id (); source = src_id; target = slice_id;
                                 edge_type = "bit_access"; position = None; enable = None } :: !extra_edges;
                (* Edge: bit_slice -> var *)
                extra_edges := { id = fresh_edge_id (); source = slice_id; target = tgt.id;
                                 edge_type = "assignment"; position = None; enable = None } :: !extra_edges;
                (* Record width update for target var node *)
                Hashtbl.replace width_updates tgt.id bw;
            | None -> ()
          ) output_edges;
      | None -> ()
    ) fp_splits;
    let new_nodes = List.filter_map (fun (n : rg_node) ->
      if Hashtbl.mem remove_ids n.id then None
      else match Hashtbl.find_opt width_updates n.id with
        | Some bw -> Some { n with bit_width = Some bw }
        | None -> Some n
    ) graph.nodes @ !extra_nodes in
    let new_edges = List.filter (fun (e : rg_edge) ->
      not (Hashtbl.mem remove_edges e.id)
    ) graph.edges @ !extra_edges in
    { graph with nodes = new_nodes; edges = new_edges }
  end

let graph_to_json graph =
  let graph = lower_fp_split graph in
  let graph = normalize_graph graph in
  let open JSON in
  let fields = [
    field "nodes" (array (List.map node_to_json graph.nodes));
    field "edges" (array (List.map edge_to_json graph.edges));
  ] in
  let fields = match graph.decode_constraints with
    | [] -> fields
    | constraints ->
        fields @ [field "decode_constraints" (array (List.map decode_constraint_to_json constraints))]
  in
  obj fields

(* Main extraction function - works with both typed and untyped AST *)
let extract_from_ast ?filter_func defs =
  let builder = GraphBuilder.create () in
  (* Initialize architectural state *)
  GraphBuilder.add_architectural_state builder;
  List.iter (GraphBuilder.visit_def builder filter_func) defs;
  GraphBuilder.to_graph builder

(* Extract per-instruction graphs *)
let extract_per_instruction ?(use_real_fetch=false) ?filter_func defs =
  Printf.printf "Configuration: use_real_fetch=%b\n%!" use_real_fetch;

  (* First pass: collect all decode mappings from mapdefs *)
  Printf.printf "First pass: collecting decode mappings...\n%!";
  (* Store multiple mapping clauses per instruction name *)
  let decode_mappings = Hashtbl.create 50 in

  List.iter (fun def ->
    match def with
    | DEF_aux (DEF_mapdef (MD_aux (MD_mapping (id, _, mapcl_list), _)), _) ->
        let mapping_name = GraphBuilder.string_of_id id in
        if mapping_name = "encdec" then begin
          List.iter (fun mapcl ->
            match mapcl with
            | MCL_aux (MCL_bidir (left_mpexp, right_mpexp), _) ->
                (* Extract instruction name from left side *)
                let instr_name = GraphBuilder.extract_instr_name_from_mpexp left_mpexp in
                (match instr_name with
                | Some name ->
                    Printf.printf "  Found decode mapping for %s\n%!" name;
                    (* Store as list of clauses *)
                    let existing = match Hashtbl.find_opt decode_mappings name with
                      | Some lst -> lst
                      | None -> []
                    in
                    Hashtbl.replace decode_mappings name ((left_mpexp, right_mpexp) :: existing)
                | None -> ())
            | _ -> ()
          ) mapcl_list
        end
    | _ -> ()
  ) defs;

  (* Count total clauses *)
  let total_clauses = Hashtbl.fold (fun _name clauses acc -> acc + List.length clauses) decode_mappings 0 in
  Printf.printf "Collected %d decode mappings (%d total clauses)\n%!" (Hashtbl.length decode_mappings) total_clauses;

  (* Second pass: extract helper functions FIRST so we can inline them *)
  (* Extract in dependency order: base functions first (wX, rX), then wrappers (wX_bits, rX_bits) *)
  Printf.printf "Second pass: extracting helper functions (fetch, rX, wX, etc.)...\n%!";
  let helper_funcs_ordered = ["fetch"; "rX"; "wX"; "rX_bits"; "wX_bits"] in
  let helper_graphs_tbl = Hashtbl.create 10 in

  List.iter (fun target_func ->
    List.iter (fun def ->
      match def with
      | DEF_aux (DEF_fundef (FD_aux (FD_function (_rec, _tannot, clauses), _)), _) ->
          let func_name = match clauses with
            | FCL_aux (FCL_funcl (id, _), _) :: _ -> GraphBuilder.string_of_id id
            | _ -> ""
          in
          if func_name = target_func then begin
            Printf.printf "  Extracting helper function: %s\n%!" func_name;
            (* Pass already-extracted helpers so wX_bits can inline wX *)
            let builder = GraphBuilder.create_with_helpers helper_graphs_tbl in
            List.iter (GraphBuilder.visit_funcl builder func_name) clauses;
            let graph = GraphBuilder.to_graph builder in
            Hashtbl.add helper_graphs_tbl func_name graph
          end
      | _ -> ()
    ) defs
  ) helper_funcs_ordered;

  Printf.printf "Extracted %d helper functions\n%!" (Hashtbl.length helper_graphs_tbl);

  (* Scan for global constants from type definitions and let bindings *)
  Printf.printf "Scanning for global constants...\n%!";
  let global_constants = Hashtbl.create 20 in
  (* Seed with RISC-V config: xlen=32 for RV32 (TODO: make configurable via --xlen) *)
  Hashtbl.replace global_constants "xlen" 32;
  Printf.printf "  Seed constant: xlen = 32\n%!";
  (* Multi-pass evaluation: resolve constants iteratively *)
  let rec eval_typ_arg_as_nexp ctx (A_aux (arg, _)) = match arg with
    | A_nexp nexp -> eval_nexp_with_ctx ctx nexp
    | _ -> None
  and eval_nc_with_ctx ctx (NC_aux (nc, _)) = match nc with
    | NC_equal (a, b) ->
      (match eval_typ_arg_as_nexp ctx a, eval_typ_arg_as_nexp ctx b with
       | Some a, Some b -> Some (a = b) | _ -> None)
    | NC_not_equal (a, b) ->
      (match eval_typ_arg_as_nexp ctx a, eval_typ_arg_as_nexp ctx b with
       | Some a, Some b -> Some (a <> b) | _ -> None)
    | NC_ge (a, b) ->
      (match eval_nexp_with_ctx ctx a, eval_nexp_with_ctx ctx b with
       | Some a, Some b -> Some (a >= b) | _ -> None)
    | NC_gt (a, b) ->
      (match eval_nexp_with_ctx ctx a, eval_nexp_with_ctx ctx b with
       | Some a, Some b -> Some (a > b) | _ -> None)
    | NC_le (a, b) ->
      (match eval_nexp_with_ctx ctx a, eval_nexp_with_ctx ctx b with
       | Some a, Some b -> Some (a <= b) | _ -> None)
    | NC_lt (a, b) ->
      (match eval_nexp_with_ctx ctx a, eval_nexp_with_ctx ctx b with
       | Some a, Some b -> Some (a < b) | _ -> None)
    | NC_and (a, b) ->
      (match eval_nc_with_ctx ctx a, eval_nc_with_ctx ctx b with
       | Some a, Some b -> Some (a && b) | _ -> None)
    | NC_or (a, b) ->
      (match eval_nc_with_ctx ctx a, eval_nc_with_ctx ctx b with
       | Some a, Some b -> Some (a || b) | _ -> None)
    | NC_true -> Some true
    | NC_false -> Some false
    | _ -> None
  and eval_nexp_with_ctx ctx (Nexp_aux (nexp, _)) : int option = match nexp with
    | Nexp_constant n -> (try Some (Big_int.to_int n) with _ -> None)
    | Nexp_id id -> Hashtbl.find_opt ctx (GraphBuilder.string_of_id id)
    | Nexp_var kv ->
      (* Type variables like 'n - try to look them up *)
      let name = Ast_util.string_of_kid kv in
      Hashtbl.find_opt ctx name
    | Nexp_times (a, b) ->
      (match eval_nexp_with_ctx ctx a, eval_nexp_with_ctx ctx b with
       | Some a, Some b -> Some (a * b) | _ -> None)
    | Nexp_sum (a, b) ->
      (match eval_nexp_with_ctx ctx a, eval_nexp_with_ctx ctx b with
       | Some a, Some b -> Some (a + b) | _ -> None)
    | Nexp_minus (a, b) ->
      (match eval_nexp_with_ctx ctx a, eval_nexp_with_ctx ctx b with
       | Some a, Some b -> Some (a - b) | _ -> None)
    | Nexp_exp a ->
      (match eval_nexp_with_ctx ctx a with Some a -> Some (1 lsl a) | None -> None)
    | Nexp_neg a ->
      (match eval_nexp_with_ctx ctx a with Some a -> Some (-a) | None -> None)
    | Nexp_if (cond, then_nexp, else_nexp) ->
      (* Try to evaluate the constraint condition *)
      (match eval_nc_with_ctx ctx cond with
       | Some true -> eval_nexp_with_ctx ctx then_nexp
       | Some false -> eval_nexp_with_ctx ctx else_nexp
       | None ->
         (* If condition unknown, try both branches — if they agree, use that value *)
         (match eval_nexp_with_ctx ctx then_nexp, eval_nexp_with_ctx ctx else_nexp with
          | Some a, Some b when a = b -> Some a
          | _ -> None))
    | _ -> None
  in
  let rec try_eval_exp_with_ctx ctx (E_aux (exp, _)) = match exp with
    | E_lit (L_aux (L_num n, _)) -> (try Some (Big_int.to_int n) with _ -> None)
    | E_sizeof nexp -> eval_nexp_with_ctx ctx nexp
    | E_typ (_, inner) -> try_eval_exp_with_ctx ctx inner  (* type annotation: unwrap *)
    | E_if (cond, then_exp, else_exp) ->
      (* Try evaluating condition *)
      (match try_eval_bool_with_ctx ctx cond with
       | Some true -> try_eval_exp_with_ctx ctx then_exp
       | Some false -> try_eval_exp_with_ctx ctx else_exp
       | None ->
         (* If both branches give same value, use it regardless of condition *)
         (match try_eval_exp_with_ctx ctx then_exp, try_eval_exp_with_ctx ctx else_exp with
          | Some a, Some b when a = b -> Some a
          | _ -> None))
    | E_app (id, [a; b]) ->
      let op = GraphBuilder.string_of_id id in
      (match try_eval_exp_with_ctx ctx a, try_eval_exp_with_ctx ctx b with
       | Some a, Some b ->
         (match op with
          | "add_int" | "add_atom" -> Some (a + b)
          | "sub_int" | "sub_atom" -> Some (a - b)
          | "mult_int" | "mult_atom" -> Some (a * b)
          | "tdiv_int" -> if b <> 0 then Some (a / b) else None
          | _ -> None)
       | _ -> None)
    | E_app (id, [a]) ->
      let op = GraphBuilder.string_of_id id in
      (match try_eval_exp_with_ctx ctx a with
       | Some a ->
         (match op with
          | "pow2" -> Some (1 lsl a)
          | "negate_atom" | "negate_int" -> Some (-a)
          | _ -> None)
       | None -> None)
    | E_id id ->
      let name = GraphBuilder.string_of_id id in
      Hashtbl.find_opt ctx name
    | _ -> None
  and try_eval_bool_with_ctx ctx (E_aux (exp, _)) = match exp with
    | E_app (id, [a; b]) ->
      let op = GraphBuilder.string_of_id id in
      (match try_eval_exp_with_ctx ctx a, try_eval_exp_with_ctx ctx b with
       | Some a, Some b ->
         (match op with
          | "eq_int" | "eq_atom" -> Some (a = b)
          | "neq_int" | "neq_atom" -> Some (a <> b)
          | "gteq_int" | "gteq_atom" -> Some (a >= b)
          | "lteq_int" | "lteq_atom" -> Some (a <= b)
          | "lt_int" | "lt_atom" -> Some (a < b)
          | "gt_int" | "gt_atom" -> Some (a > b)
          | _ -> None)
       | _ -> None)
    | E_lit (L_aux (L_true, _)) -> Some true
    | E_lit (L_aux (L_false, _)) -> Some false
    | _ -> None
  in
  (* Scan type abbreviations (e.g., type log2_xlen : Int = if xlen == 32 then 5 else 6) *)
  let type_abbrevs = List.filter_map (fun def ->
    match def with
    | DEF_aux (DEF_type (TD_aux (TD_abbrev (id, _, A_aux (A_nexp nexp, _)), _)), _) ->
      Some (GraphBuilder.string_of_id id, nexp)
    | _ -> None
  ) defs in
  let type_changed = ref true in
  let type_pass = ref 0 in
  while !type_changed && !type_pass < 5 do
    type_changed := false;
    incr type_pass;
    List.iter (fun (name, nexp) ->
      if not (Hashtbl.mem global_constants name) then
        match eval_nexp_with_ctx global_constants nexp with
        | Some v ->
          Printf.printf "  Type constant (pass %d): %s = %d\n%!" !type_pass name v;
          Hashtbl.replace global_constants name v;
          type_changed := true
        | None -> ()
    ) type_abbrevs
  done;
  (* Collect all let bindings *)
  let let_bindings = List.filter_map (fun def ->
    match def with
    | DEF_aux (DEF_let (LB_aux (LB_val (pat, exp), _)), _) ->
      let name = match pat with
        | P_aux (P_id id, _) -> Some (GraphBuilder.string_of_id id)
        | P_aux (P_typ (_, P_aux (P_id id, _)), _) -> Some (GraphBuilder.string_of_id id)
        | _ -> None
      in
      (match name with Some n -> Some (n, exp) | None -> None)
    | _ -> None
  ) defs in
  (* Multi-pass resolution: each pass may resolve more constants *)
  let changed = ref true in
  let pass = ref 0 in
  while !changed && !pass < 5 do
    changed := false;
    incr pass;
    List.iter (fun (name, exp) ->
      if not (Hashtbl.mem global_constants name) then
        match try_eval_exp_with_ctx global_constants exp with
        | Some v ->
          Printf.printf "  Global constant (pass %d): %s = %d\n%!" !pass name v;
          Hashtbl.replace global_constants name v;
          changed := true
        | None -> ()
    ) let_bindings
  done;
  Printf.printf "Found %d global constants\n%!" (Hashtbl.length global_constants);

  (* Third pass: extract execute clauses (with option to inline helpers) *)
  Printf.printf "Third pass: extracting execute clauses...\n%!";
  let per_instr_graphs = List.concat_map (fun def ->
    match def with
    | DEF_aux (DEF_fundef fdef, _) ->
        GraphBuilder.visit_fundef_per_instruction use_real_fetch helper_graphs_tbl ~global_constants decode_mappings filter_func fdef
    | _ -> []
  ) defs in

  (* Convert helper graphs to output format *)
  let helper_graphs_list = Hashtbl.fold (fun name graph acc ->
    ("_" ^ name, graph) :: acc
  ) helper_graphs_tbl [] in

  (* Combine per-instruction and helper graphs *)
  per_instr_graphs @ helper_graphs_list

(* Extract from typed AST - kept for potential future use *)
let _extract_from_typed_ast ?filter_func (typed_ast : Type_check.typed_ast) =
  extract_from_ast ?filter_func typed_ast.defs

(* Extract from untyped AST - kept for potential future use *)
let _extract_from_untyped_ast ?filter_func (untyped_ast : Ast_util.untyped_ast) =
  Printf.printf "  Untyped AST has %d definitions\n%!" (List.length untyped_ast.defs);
  extract_from_ast ?filter_func untyped_ast.defs

(* Command-line interface *)
let () =
  if Array.length Sys.argv < 3 then begin
    Printf.eprintf "Usage: %s <input.sail|.sail_project> <output.json> [OPTIONS]\n" Sys.argv.(0);
    Printf.eprintf "\n";
    Printf.eprintf "Options:\n";
    Printf.eprintf "  --project-dir <dir>     Base directory for resolving paths in .sail_project\n";
    Printf.eprintf "  --modules <list>        Comma-separated list of modules to load from project\n";
    Printf.eprintf "  --function <name>       Only extract specific function (e.g., 'execute')\n";
    Printf.eprintf "  --per-instruction       Extract each instruction as a separate graph\n";
    Printf.eprintf "  --use-real-fetch        Inline real fetch() function instead of synthetic imem[pc]\n";
    Printf.eprintf "  --deps <files>          Comma-separated list of dependency files to load first\n";
    Printf.eprintf "  --deps-file <file>      File containing list of dependency files (one per line)\n";
    Printf.eprintf "\n";
    Printf.eprintf "Examples:\n";
    Printf.eprintf "  %s file.sail output.json\n" Sys.argv.(0);
    Printf.eprintf "  %s riscv.sail_project output.json --function execute --per-instruction\n" Sys.argv.(0);
    Printf.eprintf "  %s base_insts.sail output.json --deps-file core_files.txt\n" Sys.argv.(0);
    exit 1
  end;

  let input_file = Sys.argv.(1) in
  let output_file = Sys.argv.(2) in

  (* Parse command-line options *)
  let rec parse_args
      (i : int)
      (project_dir : string option)
      (modules : string list option)
      (func_filter : string option)
      (per_instr : bool)
      (use_real_fetch : bool)
      (deps : string list option)
      : (string option * string list option * string option * bool * bool * string list option) =
    if i >= Array.length Sys.argv then (project_dir, modules, func_filter, per_instr, use_real_fetch, deps)
    else match Sys.argv.(i) with
      | "--project-dir" when i + 1 < Array.length Sys.argv ->
          parse_args (i + 2) (Some Sys.argv.(i + 1)) modules func_filter per_instr use_real_fetch deps
      | "--modules" when i + 1 < Array.length Sys.argv ->
          let module_list = String.split_on_char ',' Sys.argv.(i + 1) in
          parse_args (i + 2) project_dir (Some module_list) func_filter per_instr use_real_fetch deps
      | "--function" when i + 1 < Array.length Sys.argv ->
          parse_args (i + 2) project_dir modules (Some Sys.argv.(i + 1)) per_instr use_real_fetch deps
      | "--per-instruction" ->
          parse_args (i + 1) project_dir modules func_filter true use_real_fetch deps
      | "--use-real-fetch" ->
          parse_args (i + 1) project_dir modules func_filter per_instr true deps
      | "--deps" when i + 1 < Array.length Sys.argv ->
          let dep_list = String.split_on_char ',' Sys.argv.(i + 1) in
          parse_args (i + 2) project_dir modules func_filter per_instr use_real_fetch (Some dep_list)
      | "--deps-file" when i + 1 < Array.length Sys.argv ->
          let ic = open_in Sys.argv.(i + 1) in
          let rec read_lines acc =
            try
              let line = input_line ic in
              let trimmed = String.trim line in
              if String.length trimmed > 0 && not (String.starts_with ~prefix:"#" trimmed) then
                read_lines (trimmed :: acc)
              else
                read_lines acc
            with End_of_file -> List.rev acc
          in
          let dep_list = read_lines [] in
          close_in ic;
          parse_args (i + 2) project_dir modules func_filter per_instr use_real_fetch (Some dep_list)
      | _ -> parse_args (i + 1) project_dir modules func_filter per_instr use_real_fetch deps
  in
  let (_project_dir, _modules, func_filter, per_instruction, use_real_fetch, deps) =
    parse_args 3 None None None false false None in

  (* Check if input is a project file or regular SAIL file *)
  let is_project = Filename.check_suffix input_file ".sail_project" in
  Printf.printf "Input file: %s\n" input_file;
  Printf.printf "Is project: %b\n" is_project;

  (* Parse SAIL file or project *)
  let ast_defs =
    if is_project then begin
      Printf.printf "Loading SAIL project: %s\n" input_file;
      Printf.printf "TEST: Using Frontend.load_project (typed AST with descattered execute)...\n";

      let default_sail_dir =
        match Sys.getenv_opt "SAIL_DIR" with
        | Some dir -> dir
        | None -> Filename.concat (Sys.getenv "HOME") ".opam/default/share/sail"
      in

      (* Replicate what SAIL CLI does: parse project, then call load_modules *)
      let root_directory = Filename.dirname input_file in
      let contents =
        let ic = open_in input_file in
        let s = really_input_string ic (in_channel_length ic) in
        close_in ic;
        s
      in
      let project_defs = Project.mk_root root_directory :: Initial_check.parse_project ~filename:input_file ~contents () in
      let variables = ref Util.StringMap.empty in
      let proj = Project.initialize_project_structure ~variables project_defs in
      let mod_ids = Project.all_modules proj in

      Printf.printf "Loading %d modules from project...\n" (List.length mod_ids);

      let env = Type_check.initial_env_with_modules proj in

      (* Enable backtrace *)
      Printexc.record_backtrace true;

      let (_ctx, typed_ast, _env, _effects) =
        try
          Frontend.load_modules default_sail_dir [] env proj mod_ids
        with
        | Reporting.Fatal_error err ->
            Printf.printf "FATAL ERROR from Frontend.load_modules:\n";
            Reporting.print_error err;
            Printexc.print_backtrace stdout;
            exit 1
        | exn ->
            Printf.printf "ERROR from Frontend.load_modules: %s\n" (Printexc.to_string exn);
            Printexc.print_backtrace stdout;
            exit 1
      in

      Printf.printf "Loaded typed AST with %d definitions (execute clauses are descattered/merged!)\n" (List.length typed_ast.defs);

      typed_ast.defs
    end else begin
      Printf.printf "Parsing SAIL file (untyped): %s\n" input_file;

      (* Parse files and process to untyped AST WITHOUT type-checking *)
      let all_files = match deps with
        | None -> [input_file]
        | Some dep_files ->
            Printf.printf "Loading %d dependency files first...\n" (List.length dep_files);
            dep_files @ [input_file]
      in

      Printf.printf "Total files to load: %d\n" (List.length all_files);

      (* Parse all files *)
      let default_sail_dir =
        match Sys.getenv_opt "SAIL_DIR" with
        | Some dir -> dir
        | None ->
            (* Default to opam SAIL lib directory *)
            let opam_dir = Filename.concat (Sys.getenv "HOME") ".opam/default/share/sail/lib" in
            Printf.printf "  SAIL_DIR not set, using: %s\n" opam_dir;
            opam_dir
      in

      let ctx = Initial_check.initial_ctx in
      let (untyped_ast, _final_ctx) = List.fold_left (fun (acc_ast, acc_ctx) file ->
        Printf.printf "  Parsing: %s\n%!" file;
        if not (Sys.file_exists file) then begin
          Printf.eprintf "ERROR: File does not exist: %s\n%!" file;
          exit 1
        end;
        let (_comments, defs) = Initial_check.parse_file file in
        (* Preprocess to resolve $include directives *)
        let defs = Preprocess.preprocess default_sail_dir None [] defs in
        (* Create Parse_ast.defs structure *)
        let parse_defs = Parse_ast.Defs [(Some file, defs)] in
        (* Process to untyped AST *)
        let (file_ast, new_ctx) = Initial_check.process_ast acc_ctx parse_defs in
        (* Accumulate definitions *)
        ({ defs = acc_ast.defs @ file_ast.defs; comments = acc_ast.comments @ file_ast.comments }, new_ctx)
      ) ({ defs = []; comments = [] }, ctx) all_files in

      Printf.printf "Loaded untyped AST with %d definitions\n" (List.length untyped_ast.defs);
      (* Cast untyped defs to polymorphic type - safe because visitor ignores annotations *)
      (Obj.magic untyped_ast.defs : (Type_check.tannot, Type_check.env) Ast.def list)
    end
  in

  (* Extract ResourceGraph *)
  if per_instruction then begin
    (* Per-instruction mode: extract each instruction separately *)
    Printf.printf "Extracting per-instruction ResourceGraphs...\n";
    if Option.is_some func_filter then
      Printf.printf "  Filtering for function: %s\n" (Option.get func_filter);

    let instr_graphs = extract_per_instruction ~use_real_fetch ?filter_func:func_filter ast_defs in
    Printf.printf "Extracted %d instructions\n" (List.length instr_graphs);

    (* Write JSON as object with instruction names as keys *)
    Printf.printf "Writing to: %s\n" output_file;
    (* Apply D extension 64-bit width upgrades to D instruction graphs *)
    let instr_graphs = List.map (fun (name, graph) ->
      let is_d_instr =
        (try let _ = Str.search_forward (Str.regexp_string "_D_") name 0 in true
         with Not_found -> false) ||
        (let len = String.length name in
         len >= 2 && String.sub name (len - 2) 2 = "_D") in
      if is_d_instr then (name, upgrade_d_fp_widths graph)
      else (name, graph)
    ) instr_graphs in
    let open JSON in
    let instr_objs = List.map (fun (name, graph) ->
      field name (graph_to_json graph)
    ) instr_graphs in
    let json_str = obj instr_objs in

    let oc = open_out output_file in
    output_string oc json_str;
    output_string oc "\n";
    close_out oc;

    (* Print statistics *)
    let total_nodes = List.fold_left (fun acc (_, g) -> acc + List.length g.nodes) 0 instr_graphs in
    let total_edges = List.fold_left (fun acc (_, g) -> acc + List.length g.edges) 0 instr_graphs in
    Printf.printf "Success! Extracted %d instructions with %d total nodes and %d total edges\n"
      (List.length instr_graphs) total_nodes total_edges;

    (* Print sample instructions *)
    Printf.printf "Sample instructions: %s\n"
      (String.concat ", " (List.map fst (List.filteri (fun i _ -> i < 10) instr_graphs)))
  end else begin
    (* Merged mode: extract all into one graph *)
    Printf.printf "Extracting ResourceGraph (merged mode)...\n";
    if Option.is_some func_filter then
      Printf.printf "  Filtering for function: %s\n" (Option.get func_filter);
    let graph = extract_from_ast ?filter_func:func_filter ast_defs in

    (* Write JSON *)
    Printf.printf "Writing to: %s\n" output_file;
    let json_str = graph_to_json graph in
    let oc = open_out output_file in
    output_string oc json_str;
    output_string oc "\n";
    close_out oc;

    Printf.printf "Success! Extracted %d nodes and %d edges\n"
      (List.length graph.nodes) (List.length graph.edges)
  end
