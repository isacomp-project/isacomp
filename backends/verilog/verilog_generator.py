from typing import Dict, List, Optional, Set, Tuple
from core.resource_graph import ResourceGraph, Node, Edge
from .verilog_module_generators import (
    MuxGenerator,
    CounterGenerator,
    HazardDetectorGenerator,
    create_module_generator_from_node
)


class VerilogGenerator:
    """Generate single-cycle Verilog implementation from ResourceGraph."""

    def __init__(self, graph: ResourceGraph, module_name: str = "processor"):
        self.graph = graph
        self.module_name = module_name
        self.wire_declarations = []
        self.logic_declarations = []  # For signals assigned in always @* blocks (uses reg type)
        self.reg_declarations = []
        self.memory_declarations = {}
        self.modules = [] # for things like ALU, MUX
        self.combinational_logic = []
        self.initial_blocks = []
        self.always_blocks = []
        self.node_id_to_name = {}  # Map node IDs to generated Verilog names
        self.name_counter = {}  # Counter for generating unique names
        self.declared_names = set()  # Track declared names to avoid duplicates
        self.assigned_signals = set()  # Track signals with assignments to avoid duplicate assigns

        # External inputs/outputs for aspect-oriented programming
        self.external_inputs = []  # List of {name, bit_width} for ext inputs
        self.external_outputs = []  # List of {name, bit_width} for ext push outputs
        self.sensitive_signals = []  # List of {name, bit_width} for sensitive (kill) signals

        # Module generators for complex hardware components
        self.module_generators = {}  # Map node_id -> generator instance
        self.module_definitions = []  # List of module definition strings
        self.module_instantiations = []  # List of module instantiation strings

        # Combinational logic string (accumulated during analysis and generation)
        self.comb_logic = ""

        # Track which FP modules are needed
        self.fp_modules_needed = set()  # e.g., {'fp_add', 'fp_mul'}

        # Memoization cache for bit width inference
        self._bit_width_cache = {}  # node.id -> inferred bit width

        # Renamer signal assignments (generated during module analysis)
        self.renamer_assigns = []

        # Externalized memory tracking for valid-ready handshake protocol
        self.externalized_memories = set()  # Set of memory names marked for externalization
        self.memory_read_ports = []  # List of {mem, port_name, addr_signal, data_width, addr_width}
        self.memory_write_ports = []  # List of {mem, port_name, addr_signal, data_signal, enable_signal, data_width, addr_width}

        # Cache for dynamically discovered instruction prefixes
        self._instruction_prefixes = None

    def _get_instruction_prefixes(self):
        """
        Discover instruction prefixes from the graph structure.

        Collects instruction names from:
        1. node.data['instruction'] - set by graph merger on instruction-specific nodes
        2. node.data['group_members'] - set on grouped/merged nodes
        3. Enable node IDs matching pattern '{instr}_enable'

        Returns a sorted list of '{instr}_' prefix strings.
        """
        if self._instruction_prefixes is not None:
            return self._instruction_prefixes

        instr_names = set()
        for node_id, node in self.graph.nodes.items():
            # Source 1: explicit instruction metadata
            instr = node.data.get('instruction') if node.data else None
            if instr and instr != 'shared':
                instr_names.add(instr)

            # Source 2: group_members lists
            members = node.data.get('group_members') if node.data else None
            if members:
                instr_names.update(members)

            # Source 3: enable nodes with pattern {instr}_enable
            if node_id.endswith('_enable') and node.data:
                ntype = node.data.get('type', '')
                if ntype in ('instruction_enable', 'enable_signal', 'operation', ''):
                    # Strip prefix (p0_, p1_, etc.) and _enable suffix
                    base = node_id
                    for prefix in ('p0_', 'p1_'):
                        if base.startswith(prefix):
                            base = base[len(prefix):]
                            break
                    if base.endswith('_enable'):
                        candidate = base[:-len('_enable')]
                        if candidate:
                            instr_names.add(candidate)

        # Convert to sorted prefix list (with trailing underscore)
        self._instruction_prefixes = sorted(f'{name}_' for name in instr_names)
        return self._instruction_prefixes

    def _get_mem_port_width(self, array_name: str) -> int:
        """
        Get the port_width for a memory declared with 'mem' keyword.

        Returns:
            port_width in bits if this is a 'mem' type memory, 0 otherwise.
            For 'mem' types, returns port_width if set, else bit_width, else 0.
            Word-addressed memories return 0 (no byte-to-word scaling needed).
        """
        mem_node = self.graph.nodes.get(array_name)
        if not mem_node:
            return 0

        # Only 'mem' declarations (type 'isa_state mem') use port_width addressing
        if mem_node.data.get('type') != 'isa_state mem':
            return 0

        # Word-addressed memories: addresses are already word indices
        if mem_node.data.get('word_addressed'):
            return 0

        # Return port_width if set, otherwise bit_width
        port_width = mem_node.data.get('port_width')
        if port_width and port_width >= 8:
            return port_width

        bit_width = mem_node.data.get('bit_width')
        if bit_width and bit_width >= 8:
            return bit_width

        return 0

    def _get_mem_endianness(self, array_name: str) -> str:
        """
        Get the endianness for a memory declared with 'mem' keyword.

        Returns:
            'big' or 'little'. Defaults to 'little' if not specified.
        """
        mem_node = self.graph.nodes.get(array_name)
        if not mem_node:
            return 'little'

        return mem_node.data.get('endianness', 'little')

    def _is_physical_memory(self, array_name: str) -> bool:
        """
        Check if a memory is a physical memory that needs MEM_BASE offset.

        Physical memories (imem, dmem) use 32-bit byte addresses and need MEM_BASE offset.
        Register files (csr, rf) use direct register indices and don't need MEM_BASE.

        Returns:
            True if this is a physical memory needing MEM_BASE offset.
        """
        mem_node = self.graph.nodes.get(array_name)
        if not mem_node:
            return False

        # Only 'mem' declarations (type 'isa_state mem') might be physical memories
        if mem_node.data.get('type') != 'isa_state mem':
            return False

        # Word-addressed memories use direct word indices, no MEM_BASE needed
        if mem_node.data.get('word_addressed'):
            return False

        # Check array_depth (address width) to determine if it's a physical memory
        # Physical memories (imem, dmem) have 15-17 bit addresses (for 32KB-128KB)
        # CSR has 12-bit addresses (4096 registers)
        # Physical memories use byte addressing, so need MEM_BASE offset
        array_depth = mem_node.data.get('array_depth')
        if array_depth is not None and array_depth >= 15:
            # Likely a physical memory with large address space
            return True

        # Fallback: check by name (imem, dmem, umem are physical memories)
        if array_name in ['imem', 'dmem', 'umem']:
            return True

        return False

    def _is_mem_type_read(self, node: Node) -> bool:
        """
        Check if a node reads from a 'mem' type memory (declared with 'mem' keyword).

        Returns True if the node reads from a memory with type 'isa_state mem'.
        """
        # Check array_access type
        if node.data.get('type') == 'array_access':
            # Find the memory being accessed
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'array_base':
                    mem_node = edge.source
                    if mem_node.data.get('type') == 'isa_state mem':
                        return True
            # Also check expression data
            expr = node.data.get('expression', {})
            if expr.get('type') == 'array_access':
                array_expr = expr.get('target', {})
                array_name = array_expr.get('name', '')
                return self._get_mem_port_width(array_name) > 0

        # Check _rd nodes (after architectural state splitting)
        if '_rd' in node.id:
            # Check if any 'mem' type memory name appears in the node ID
            for mem_name, mem_node in sorted(self.graph.nodes.items()):
                if mem_node.data.get('type') == 'isa_state mem':
                    if f'{mem_name}[' in node.id or f'{mem_name}_' in node.id:
                        return True

        return False

    def _get_mem_index_expr(self, addr_name: str, shift_bits: int, is_physical_mem: bool = True) -> str:
        """
        Generate memory index expression with MEM_BASE offset for physical memories.

        For physical memories (imem, dmem), generates an adjusted address wire and returns index.
        For register files (rf, csr), generates: addr (direct index, no shift)

        Note: iverilog doesn't support bit-select on expressions like (a-b)[31:2],
        so we use right-shift instead: ((addr - MEM_BASE) >> shift_bits)

        Args:
            addr_name: Name of the address wire/reg
            shift_bits: Number of bits to shift for word alignment (e.g., 2 for 32-bit memory)
            is_physical_mem: Whether this is a physical memory needing MEM_BASE offset

        Returns:
            Verilog expression for indexing the memory array
        """
        if is_physical_mem:
            # For physical memories, offset by MEM_BASE and shift
            # Use right-shift instead of bit-select for iverilog compatibility
            # MEM_BASE should be defined via -DMEM_BASE=0x... on simulator command line
            return f"(({addr_name} - `MEM_BASE) >> {shift_bits})"
        else:
            # Register files use direct indexing (no MEM_BASE offset, no bit-select)
            return addr_name

    def generate(self) -> str:
        """Generate complete Verilog module."""
        self._propagate_bit_slice_widths()  # Widen sources based on bit slice accesses
        self._mark_fp_nan_boxing()  # Mark zero_extend nodes that need NaN-boxing for FP
        self._mark_signed_fp_conversions()  # Mark signed FP->int conversions for sign-extension
        self._identify_inlined_nodes()  # Identify AND nodes that can be inlined in mux selects
        self._analyze_graph()
        self._generate_extra_modules()
        self._generate_module_header()
        self._generate_declarations()
        self._generate_memory_initialization()
        self._generate_combinational_logic()
        self._fix_narrow_access_declarations()
        self._prescan_memory_write_ports()  # Pre-scan memory write ports for externalized memories
        self._generate_variable_latency_memory_logic()
        self._finalize_externalized_memory_ports()  # Add externalized memory port connections (before seq logic for stall signal)
        self._generate_sequential_logic()
        self._generate_bit_slice_concatenations()

        return self._assemble_module()

    def _analyze_graph(self):
        """Analyze the graph to determine signal types and dependencies."""
        # Analyze ISA state - iterate in sorted order for deterministic output
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            # Skip cast nodes - they're inlined in expressions, not declared
            # Note: replication and concatenation need wires if they're referenced by other nodes
            if node.data.get('type') in ['cast']:
                continue

            if node.is_arch_state:
                # Check if this is a module node (e.g., multiplexer marked as arch state)
                if node.data.get('type') in ['multiplexer', 'uarch_counter', 'serialization_counter', 'memory_port_counter', 'memory_access_counter', 'hazard_detection_unit', 'hazard_detector', 'read_only_cache', 'read_write_cache', 'tlb_cache', 'instruction_buffer', 'btb_storage', 'renamer']:
                    self._process_module_node(node)
                elif node.data.get('type') == 'alu_module':
                    self._process_intermediate_node(node)
                else:
                    self._process_isa_state_node(node)
            elif node.data.get('type', '').startswith('isa_state'):
                # Handle split memory ports (created by split_merge transformation)
                if node.data.get('is_split_port'):
                    self._process_split_memory_port(node)
                else:
                    # All isa_state nodes should be processed as ISA state
                    # This includes external/sensitive state and read-only state
                    self._process_isa_state_node(node)
            elif node.data.get('type') in ['var', 'temp_var']:
                self._process_variable_node(node)
            elif node.data.get('type') in ['operation', 'binary_op', 'fp_operation', 'array_access', 'bit_slice', 'write_data_slice', 'concatenation', 'repetition', 'ternary', 'ternary_op', 'literal', 'sized_literal', 'binary_literal', 'decimal_literal', 'verilog_hex_literal', 'verilog_dec_literal', 'comparison', 'logical_and', 'logical_or', 'logical_not', 'instruction_enable', 'address_offset', 'port_address_offset', 'memory_data_merge', 'port_data_merge', 'zero_extend', 'sign_extend', 'one_hot_mux', 'cache_read_data', 'cache_valid', 'cache_refill_addr', 'cache_refill_data', 'control_signal', 'cache_read_req', 'byte_enable_mux', 'alias', 'tlb_hit', 'tlb_data', 'ibuf_read_data', 'ibuf_valid', 'ibuf_fetch_addr', 'ibuf_fetch_req', 'mux', 'array_read', 'alu_module', 'alu_operand_mux', 'alu_opcode_mux', 'byte_enable_computation']:
                self._process_intermediate_node(node)
            elif node.data.get('type') in ['multiplexer', 'uarch_counter', 'serialization_counter', 'memory_port_counter', 'memory_access_counter', 'hazard_detection_unit', 'hazard_detector', 'read_only_cache', 'read_write_cache', 'tlb_cache', 'instruction_buffer', 'btb_storage', 'renamer']:
                self._process_module_node(node)
            elif node.is_uarch_state or node.data.get('type') in ['pipeline_register', 'pipeline_stall_controller', 'ras_stack', 'ras_ptr_update', 'ras_ptr', 'rename_table', 'free_list']:
                # Handle uarch state nodes (pipeline registers, stall controllers, RAS, renaming tables, etc.)
                if node.data.get('type') == 'ras_stack':
                    self._process_ras_stack_node(node)
                elif node.data.get('type') == 'ras_ptr_update':
                    self._process_ras_ptr_update_node(node)
                elif node.data.get('type') == 'ras_ptr':
                    self._process_ras_ptr_node(node)
                else:
                    self._process_uarch_state_node(node)
            elif node.data.get('type') in ['uarch_index', 'denamer', 'denamer_instance']:
                # Handle renaming-related intermediate nodes
                self._process_renaming_node(node)

        # Second pass: For array_access nodes that need narrow load selection,
        # declare the intermediate _word wires (must be after memory_declarations is populated)
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if node.data.get('type') == 'array_access':
                self._declare_narrow_load_word_wire(node)

    def _propagate_bit_slice_widths(self):
        """Propagate minimum widths from bit_slice uses and assignment targets back to source nodes.

        If a bit_slice accesses bit N (e.g., result[8]), the source node must be
        at least N+1 bits wide. This ensures arithmetic results can capture
        carry/borrow bits for 6502-style flag detection.

        Also propagates declared variable widths backward through assignments,
        so that expressions assigned to 5-bit variables use 5-bit intermediates.

        Follows data edges backward to propagate widths through aliases,
        but excludes register read nodes (ending in _rd) to avoid incorrectly
        widening flags and other narrow architectural state.
        """
        # Collect minimum width requirements from bit slices and variable declarations
        min_widths = {}  # source_node_id -> minimum required width

        # First, seed from variables with explicit bit_width that have incoming arithmetic operations
        # Only propagate to arithmetic operations (like additions) - not memory reads
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            explicit_width = node.data.get('bit_width')
            node_type = node.data.get('type')
            # Include 'var' nodes (from ISA var declarations)
            if explicit_width is not None and node_type in ['var', 'variable']:
                # This node has explicit width - check if source is an arithmetic operation
                for edge in node.incoming_edges:
                    edge_type = edge.data.get('type', '')
                    if edge_type in ['assignment', 'data', 'value']:
                        source = edge.source
                        # Only propagate to arithmetic operations, not memory reads
                        source_type = source.data.get('type', '')
                        source_op = source.data.get('operator', '')
                        if source_type == 'operation' and source_op in ['+', '-', '*']:
                            if source.id not in min_widths or min_widths[source.id] < explicit_width:
                                min_widths[source.id] = explicit_width

        # Seed from bit_slice accesses
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if node.data.get('type') != 'bit_slice':
                continue

            # Get the high bit being accessed
            high_bit = None
            if 'high_bit' in node.data:
                high_bit = node.data['high_bit']
            elif 'high' in node.data:
                high_bit = node.data['high']
            elif 'bitslice' in node.data:
                high_bit = node.data['bitslice'][0]
            else:
                expr = node.data.get('expression', {})
                if expr.get('type') == 'bit_slice' and 'range' in expr:
                    high_bit = expr['range'][0]

            if high_bit is None:
                continue

            # Find the source node
            for edge in node.incoming_edges:
                source = edge.source
                # Calculate minimum width (high_bit + 1 for zero-indexed)
                required_width = high_bit + 1

                # Track max requirement for this source
                if source.id not in min_widths or min_widths[source.id] < required_width:
                    min_widths[source.id] = required_width

        # Propagate widths backward through data/value edges
        # This handles cases like cpy_imm_result = Y_sub_imm where cpy_imm_result
        # needs to be 9 bits - Y_sub_imm should also be 9 bits
        changed = True
        iterations = 0

        while changed and iterations < 10:  # Limit iterations to avoid infinite loops
            changed = False
            iterations += 1
            for node_id, min_width in list(min_widths.items()):
                if node_id not in self.graph.nodes:
                    continue
                node = self.graph.nodes[node_id]

                # Follow incoming data/value edges backward
                for edge in node.incoming_edges:
                    edge_type = edge.data.get('type', '')
                    # Only follow data-like edges (not control edges)
                    if edge_type in ['data', 'value', 'operand', 'alias', 'assignment']:
                        source = edge.source

                        # Skip register read nodes - these are architectural state
                        # with fixed widths that should not be widened
                        if source.id.endswith('_rd'):
                            continue

                        # Propagate width to the source if it needs widening
                        # BUT: don't override nodes that have explicit bit_width from ISA declarations
                        # Those widths are authoritative and should not be changed by downstream usage
                        source_explicit_width = source.data.get('bit_width')
                        if source_explicit_width is not None:
                            # Source has explicit width - don't propagate
                            continue

                        if source.id not in min_widths or min_widths[source.id] < min_width:
                            min_widths[source.id] = min_width
                            changed = True

        # Apply minimum widths to source nodes
        for node_id, min_width in min_widths.items():
            if node_id not in self.graph.nodes:
                continue
            node = self.graph.nodes[node_id]

            # Skip multiplexer nodes - their width is determined by their inputs,
            # not by how bits are sliced from their output. A bit slice like addr[1:0]
            # for byte selection shouldn't constrain the mux to 2 bits.
            if node.data.get('type') == 'multiplexer':
                continue

            # Skip one_hot_mux nodes (address muxes) - their width is determined by
            # their address source inputs, not by how bits are sliced from their output.
            # For example, umem_ea_rd_addr_mux should be 64 bits (full address) even if
            # only [2:0] is used for byte offset selection.
            if node.data.get('type') == 'one_hot_mux':
                continue

            # Skip bit_slice nodes - their width is determined by their range,
            # not by what uses them. A bit slice like instr[15:11] is always 5 bits.
            if node.data.get('type') == 'bit_slice':
                continue

            # Skip array_access nodes (memory reads) - their width is determined by the
            # memory's data width, not by how bits are sliced from the read data.
            # For example, umem[pc]_rd is always 32 bits even if instr[25:0] uses only 26.
            if node.data.get('type') == 'array_access':
                continue

            # Skip _rd nodes (ISA state reads) - these have fixed architectural widths
            # that should not be widened based on downstream bit slice usage.
            if node_id.endswith('_rd'):
                continue

            # Skip pipeline_register nodes that carry data from memory reads or ISA state.
            # Their width should be determined by the source, not by downstream bit slices.
            # For example, PIPE_Decode_umem_pc_rd_PIPE should be 32 bits (full instruction),
            # not narrowed to 26 bits just because instr[25:0] is used for jump targets.
            if node.data.get('type') == 'pipeline_register':
                # Only skip if this is carrying instruction/memory data, not boolean signals
                # Check if pipeline register carries data from a byte-addressed memory (type 'isa_state mem')
                carries_mem_data = False
                for mem_name, mem_node in sorted(self.graph.nodes.items()):
                    if mem_node.data.get('type') == 'isa_state mem':
                        if f'{mem_name}_pc' in node_id or f'{mem_name}[pc]' in node_id:
                            carries_mem_data = True
                            break
                if carries_mem_data:
                    continue

            current_width = node.data.get('bit_width')

            # If node doesn't have explicit width or it's too small, update it
            if current_width is None or current_width < min_width:
                node.data['bit_width'] = min_width
                print(f"Widened {node_id} from {current_width} to {min_width} bits (bit_slice access)")

    def _mark_fp_nan_boxing(self):
        """Mark zero_extend nodes that need NaN-boxing for FP register file writes.

        When D extension (64-bit FP) is present alongside F extension (32-bit FP),
        single-precision values written to the 64-bit FP register file must be
        NaN-boxed: upper 32 bits set to all 1s instead of zero-extended.

        This pass finds the FP register file write mux and traces back to find
        any zero_extend nodes that are extending 32-bit values to 64 bits,
        marking them for NaN-boxing instead of zero-extension.

        IMPORTANT: We must exclude zero_extend nodes that are also used by the
        integer register file (rf_write_data_mux), since values going to integer
        registers (like FCLASS.D results) need zero-extension, not NaN-boxing.
        """
        # Find the FP register file write data mux
        frf_write_mux = None
        frf_width = None

        for node_id, node in self.graph.nodes.items():
            # Look for frf write data mux or frf_wr node
            if 'frf' in node_id.lower() and ('write_data' in node_id.lower() or node_id.endswith('_wr')):
                node_width = node.data.get('bit_width')
                if node_width and node_width == 64:
                    frf_write_mux = node
                    frf_width = 64
                    break
            # Also check for frf_write_data_mux pattern
            if node_id == 'frf_write_data_mux' or node_id == 'frf_write_data':
                frf_write_mux = node
                frf_width = node.data.get('bit_width', 64)
                break

        if not frf_write_mux or frf_width != 64:
            # No 64-bit FP register file found, nothing to do
            return

        # Find the integer register file write mux to exclude nodes used by it
        rf_write_mux = None
        for node_id, node in self.graph.nodes.items():
            if node_id == 'rf_write_data_mux' or node_id == 'rf_write_data':
                rf_write_mux = node
                break
            # Also check for rf write data patterns
            if 'rf' in node_id.lower() and 'frf' not in node_id.lower() and 'write_data' in node_id.lower():
                rf_write_mux = node
                break

        # Find zero_extend nodes that DIRECTLY feed into rf_write_data_mux
        rf_zero_extend_nodes = set()
        if rf_write_mux:
            for edge in rf_write_mux.incoming_edges:
                source = edge.source
                if source.data.get('type') == 'zero_extend':
                    original_width = source.data.get('original_width')
                    target_width = source.data.get('bit_width')
                    if original_width == 32 and target_width == 64:
                        rf_zero_extend_nodes.add(source.id)

        # Find zero_extend nodes that DIRECTLY feed into frf_write_data_mux
        frf_zero_extend_nodes = set()
        for edge in frf_write_mux.incoming_edges:
            source = edge.source
            if source.data.get('type') == 'zero_extend':
                original_width = source.data.get('original_width')
                target_width = source.data.get('bit_width')
                if original_width == 32 and target_width == 64:
                    frf_zero_extend_nodes.add(source.id)

        # Mark nodes based on which muxes they feed
        nan_box_count = 0
        dual_count = 0

        for node_id in frf_zero_extend_nodes:
            node = self.graph.nodes[node_id]
            if node_id in rf_zero_extend_nodes:
                # Node is used by BOTH FP and integer register files
                # Mark as dual - need both zero-extended (for RF) and NaN-boxed (for FRF) versions
                node.data['nan_box_dual'] = True
                dual_count += 1
            else:
                # Only used by FP register file - simple NaN-boxing
                node.data['nan_box'] = True
                nan_box_count += 1

        if nan_box_count > 0:
            print(f"Marked {nan_box_count} zero_extend nodes for NaN-boxing (FP 32->64 bit extension)")
        if dual_count > 0:
            print(f"Marked {dual_count} zero_extend nodes for dual NaN-boxing (shared FP/integer use)")

    def _mark_signed_fp_conversions(self):
        """Mark zero_extend nodes for signed FP->int conversions to use sign-extension.

        RISC-V spec requires FCVT.W.D and FCVT.W.S (signed conversions) to produce
        sign-extended 64-bit results on RV64. This pass finds zero_extend nodes
        that extend signed FP conversion results and marks them for sign-extension.
        """
        # FP-to-W-type (32-bit) integer conversion intrinsics
        # On RV64, W-type results (both signed and unsigned) must be sign-extended to 64-bit
        # This includes FCVT.W.* and FCVT.WU.* - all produce sign-extended results
        w_type_fp_cvt_intrinsics = {'fp_cvt_w_s', 'fp_cvt_w_d', 'fp_cvt_wu_s', 'fp_cvt_wu_d'}

        sign_ext_count = 0

        for node_id, node in self.graph.nodes.items():
            # Look for zero_extend nodes extending 32->64 bits
            if node.data.get('type') == 'zero_extend':
                original_width = node.data.get('original_width')
                target_width = node.data.get('bit_width')

                # Only consider 32->64 extensions that aren't NaN-boxed
                if original_width == 32 and target_width == 64 and not node.data.get('nan_box', False):
                    # Check if the source is a signed FP conversion intrinsic result
                    for edge in node.incoming_edges:
                        source = edge.source
                        fp_intrinsic = source.data.get('fp_intrinsic')
                        # Also check node name patterns for conversion results
                        is_w_type_cvt = fp_intrinsic in w_type_fp_cvt_intrinsics
                        # Check if source node name contains W-type conversion pattern
                        if not is_w_type_cvt:
                            for w_name in ['fcvt_w_d', 'fcvt_w_s', 'fcvt_wu_d', 'fcvt_wu_s']:
                                if w_name in source.id.lower() and 'cvt_result' in source.id.lower():
                                    is_w_type_cvt = True
                                    break
                        if is_w_type_cvt:
                            # Mark for sign-extension instead of zero-extension
                            node.data['sign_extend'] = True
                            sign_ext_count += 1
                            break

        if sign_ext_count > 0:
            print(f"Marked {sign_ext_count} zero_extend nodes for sign-extension (signed FP->int conversion)")

    def _identify_inlined_nodes(self):
        """Identify AND nodes that can be inlined in mux select expressions.

        This prevents generating unnecessary wires for trivial AND operations
        like 'add_enable && (rd != 0)' that are only used as mux selects.
        """
        self.inlined_nodes = set()

        # First pass: collect candidate AND nodes that are used as mux selects
        candidate_inlines = set()
        mux_count = 0
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if node.data.get('type') == 'multiplexer':
                mux_count += 1
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'mux_select':
                        select_source = edge.source
                        # Check if this select is a simple AND operation
                        # Handle both ILA case (type='operation', operator='&&') and
                        # ISA case (type='logical_and', operation='&&')
                        is_and_op = False
                        if (select_source.data.get('type') == 'operation' and
                            select_source.data.get('operator') == '&&'):
                            is_and_op = True
                        elif (select_source.data.get('type') == 'logical_and' and
                              select_source.data.get('operation') == '&&'):
                            is_and_op = True

                        if is_and_op:
                            # Check if it has exactly 2 operands
                            # Handle both edge types: 'operand' (ILA) and 'logic_input' (ISA)
                            operands = [e for e in select_source.incoming_edges
                                       if e.data.get('type') in ['operand', 'logic_input']]
                            if len(operands) == 2:
                                candidate_inlines.add(select_source.id)

        # Second pass: only inline if the node is ONLY used as mux selects (no other outgoing edges)
        for node_id in sorted(candidate_inlines):
            node = self.graph.nodes[node_id]

            # CRITICAL FIX: Never inline instruction_enable nodes
            # These are used in sequential logic (if statements) for memory writes
            # and MUST have wire declarations even if they also serve as mux selects
            # Check both by type and by naming pattern (xxx_enable)
            is_instruction_enable = (
                node.data.get('type') == 'instruction_enable' or
                node_id.endswith('_enable')
            )
            if is_instruction_enable:
                continue

            # Check that all outgoing edges go to multiplexers as mux_select
            # Do NOT inline if any edge is a write_enable (used in sequential logic)
            all_uses_are_mux_selects = True
            for edge in node.outgoing_edges:
                if edge.data.get('type') == 'write_enable':
                    all_uses_are_mux_selects = False
                    break
                if edge.data.get('type') != 'mux_select':
                    all_uses_are_mux_selects = False
                    break

            if all_uses_are_mux_selects:
                self.inlined_nodes.add(node_id)
            # Suppress verbose per-node marking output

        print(f"Found {mux_count} multiplexer nodes, marked {len(self.inlined_nodes)} AND nodes for inlining")

    def _process_isa_state_node(self, node: Node):
        """Process ISA state nodes for Verilog generation."""
        # issue: ISA state nodes will have two kinds, read and write.
        # 1. need to apply read/write disambiguation on original graph
        # 2. need to only generate one declaration per actual ISA state
        # create set of names for declarations to avoid duplicates,

        # For split read/write nodes (like pc_rd, instr_rd), use the node ID
        # Otherwise use the name from data
        # Check for _rd/_wr as SUFFIXES to avoid matching nodes like conditional_mux_pc_wr_mux_...
        if node.id.endswith('_rd') or node.id.endswith('_wr'):
            name = node.id
        else:
            name = node.data.get('name', node.id)

        # Get bit_width, inferring it if not present (for merged graph nodes)
        # For memories, port_width (actual access width) takes precedence over bit_width
        if 'port_width' in node.data:
            bit_width = node.data['port_width']
        elif 'bit_width' in node.data:
            bit_width = node.data['bit_width']
        else:
            bit_width = self._infer_bit_width(node)

        is_memory = node.data.get('is_memory', False)

        if is_memory:
            # Multi-dimensional array -> memory
            # For CAM nodes, array_depth is already the actual entry count (e.g., 64 entries)
            # For regular arrays, array_depth is the address width (e.g., 5 bits for rf[31:0][4:0])
            # We need to convert address width to actual depth (2^addr_width = 32 entries)
            raw_array_depth = node.data['array_depth']

            # Cap memory depth for practical synthesis
            # ILA specs may have 30-bit address spaces (1GB) which is impractical
            # Cap at 64MB (2^26) to support J2 Linux and other large memory requirements
            MAX_MEMORY_DEPTH = 67108864  # 2^26 = 64MB

            # Check if this is a CAM node - for CAMs, array_depth is already entry count
            if node.data.get('is_cam', False):
                # CAM: array_depth is total_entries directly
                array_depth = raw_array_depth
                addr_width = max(1, (raw_array_depth - 1).bit_length())
            else:
                # Regular array: array_depth is address width, convert to entry count
                addr_width = raw_array_depth
                array_depth = min(2 ** addr_width, MAX_MEMORY_DEPTH)

            self.memory_declarations[name] = {
                'bit_width': bit_width,
                'array_depth': array_depth,
                'addr_width': addr_width,
                'mem_file': f"{name}.hex"
            }

            # Store latency specification (set by set_memory_variable_latency)
            # Note: For externalized memory with caches, the cache handles latency,
            # so testbench uses 0 (combinational). The min/max are stored for reference.
            self.memory_declarations[name]['min_latency'] = node.data.get('min_latency', 0)
            self.memory_declarations[name]['max_latency'] = node.data.get('max_latency', 0)

            # Track externalized memories for valid-ready handshake port generation
            if node.data.get('externalized', False):
                self.externalized_memories.add(name)
                # Store additional info for port generation
                self.memory_declarations[name]['externalized'] = True
                self.memory_declarations[name]['externalize_read'] = node.data.get('externalize_read', True)
                self.memory_declarations[name]['externalize_write'] = node.data.get('externalize_write', True)
                self.memory_declarations[name]['use_valid_ready'] = node.data.get('use_valid_ready', True)
        else:
            # Determine if this should be a register or wire
            # Nodes marked as arch_state from merged graphs may have different types
            node_type = node.data.get('type')

            # Sanitize the name for Verilog
            sanitized_name = self._sanitize_identifier(name)

            # Skip if already declared
            if sanitized_name in self.declared_names:
                return

            self.declared_names.add(sanitized_name)
            # Map node ID to the sanitized Verilog name
            self.node_id_to_name[node.id] = sanitized_name

            # Skip port nodes - they're declared in the module header
            if node.data.get('is_port', False):
                return

            # Check for external/sensitive state (aspect-oriented programming)
            is_external = node.data.get('is_external', False)
            is_push = node.data.get('is_push', False)
            is_sensitive = node.data.get('is_sensitive', False)

            # External inputs (ext without push)
            if is_external and not is_push:
                self.external_inputs.append({
                    'name': sanitized_name,
                    'bit_width': bit_width
                })
                return  # Don't declare as register or wire

            # External outputs (ext push)
            if is_external and is_push:
                self.external_outputs.append({
                    'name': sanitized_name,
                    'bit_width': bit_width
                })
                return  # Don't declare as register or wire

            # Sensitive (kill) signals
            if is_sensitive:
                self.sensitive_signals.append({
                    'name': sanitized_name,
                    'bit_width': bit_width
                })
                # Sensitive signals are internal wires
                self.wire_declarations.append({
                    'name': sanitized_name,
                    'bit_width': bit_width
                })
                return

            # Check if this is a split read/write node with conceptual forwarding
            has_state_update_edge = any(edge.data.get('type') == 'state_update'
                                       for edge in node.incoming_edges)

            # These types should always be wires, never registers
            if node_type in ['array_access', 'bit_slice', 'multiplexer', 'memory_write_port', 'one_hot_mux']:
                # Only add if not already in wire_declarations
                if not any(w['name'] == sanitized_name for w in self.wire_declarations):
                    self.wire_declarations.append({
                        'name': sanitized_name,
                        'bit_width': bit_width
                    })
            # _rd nodes with state_update edges should be wires (conceptual forwarding)
            # Check for _rd as SUFFIX to avoid matching nodes like conditional_mux_pc_rd_mux_...
            elif node.id.endswith('_rd') and has_state_update_edge:
                # Only add if not already in wire_declarations
                if not any(w['name'] == sanitized_name for w in self.wire_declarations):
                    self.wire_declarations.append({
                        'name': sanitized_name,
                        'bit_width': bit_width
                    })
                # Also declare the base register (without _rd suffix)
                base_name = sanitized_name.replace('_rd', '')
                if base_name not in self.declared_names:
                    self.declared_names.add(base_name)
                    self.reg_declarations.append({
                        'name': base_name,
                        'bit_width': bit_width,
                        'reset_wire': f"reset_{base_name}"
                    })
            # _wr nodes should be wires
            # Check for _wr as SUFFIX to avoid matching nodes like conditional_mux_pc_wr_mux_...
            elif node.id.endswith('_wr'):
                # For ISA state _wr nodes, constrain width to match the base register
                # This prevents addition carry bits from widening the output
                final_bit_width = bit_width
                base_name = node.id[:-3]  # Remove '_wr'
                base_node = self.graph.nodes.get(base_name)
                if base_node and base_node.data.get('bit_width'):
                    # Use the base register's width, which is the architectural constraint
                    final_bit_width = base_node.data['bit_width']
                # Also check the _rd version
                rd_node = self.graph.nodes.get(f'{base_name}_rd')
                if rd_node and rd_node.data.get('bit_width'):
                    final_bit_width = rd_node.data['bit_width']
                self.wire_declarations.append({
                    'name': sanitized_name,
                    'bit_width': final_bit_width
                })
            # ISA state should be registers
            # Also treat uarch_counter, uarch_state, pipeline_register, and validity_bit nodes as registers
            # EXCEPT x0 which is hardwired to zero in RISC-V
            # EXCEPT instruction-prefixed copies (e.g., add_satp) which should read from the shared _rd register
            elif node_type.startswith('isa_state') or node_type in ['uarch_counter', 'uarch_state', 'pipeline_register', 'validity_bit'] or self._should_be_register(node):
                # Check if this is an instruction-prefixed copy of ISA state
                # These should be wires that read from the shared _rd register, not separate registers
                # Check for 'instruction' key or 'group_id' key (different merging strategies use different names)
                instr_prefix = node.data.get('instruction') or node.data.get('group_id')

                # Also detect by name pattern: {instruction}_{isa_state_name}
                if not instr_prefix and node_type.startswith('isa_state') and not node.is_arch_state:
                    # Try to detect instruction prefix by name pattern
                    # Prefixes are discovered dynamically from graph metadata
                    known_prefixes = self._get_instruction_prefixes()
                    for prefix in known_prefixes:
                        if name.startswith(prefix):
                            instr_prefix = prefix.rstrip('_')
                            break

                if instr_prefix and node_type.startswith('isa_state') and not node.is_arch_state:
                    # This is an instruction-specific copy like 'add_satp'
                    # Find the base name using original_id if available, otherwise try to strip prefix
                    base_name = node.data.get('original_id')
                    if not base_name:
                        # Try to strip instruction prefix from name
                        prefix_str = instr_prefix + '_'
                        if name.startswith(prefix_str):
                            base_name = name[len(prefix_str):]

                    if base_name:
                        shared_rd_name = f"{base_name}_rd"
                        # Check if the shared _rd register exists
                        if shared_rd_name in self.graph.nodes:
                            # DON'T create alias if this node has incoming assignment edges
                            # (meaning its value is computed from elsewhere, not just read from shared register)
                            # This handles cases like gated assignments from aspects:
                            #   mepc when (exception_taken) = pc  -> creates add_mepc with incoming edge from pc
                            has_incoming_assignments = False
                            for edge in node.incoming_edges:
                                edge_type = edge.data.get('type', '')
                                if edge_type in ['assignment', 'mux_output', 'ternary_result', 'operand', 'mux_input']:
                                    has_incoming_assignments = True
                                    break

                            if has_incoming_assignments:
                                # Node has computed value - declare as wire but don't create alias
                                # The assignment will be generated from the incoming edges
                                self.wire_declarations.append({
                                    'name': sanitized_name,
                                    'bit_width': bit_width
                                })
                                return  # Don't process as regular register, assignment comes from edges

                            # No incoming assignments - create alias to read from shared register
                            self.wire_declarations.append({
                                'name': sanitized_name,
                                'bit_width': bit_width
                            })
                            # Track this alias to generate 'assign add_satp = satp_rd;' later
                            if not hasattr(self, 'isa_state_aliases'):
                                self.isa_state_aliases = []
                            self.isa_state_aliases.append({
                                'alias': sanitized_name,
                                'source': shared_rd_name,
                                'bit_width': bit_width
                            })
                            return  # Don't process as regular register
                if name == 'x0':
                    # x0 is hardwired to zero - declare as wire tied to 0
                    self.wire_declarations.append({
                        'name': sanitized_name,
                        'bit_width': bit_width
                    })
                    # Add a constant assignment for x0 = 0
                    # This will be generated in the combinational logic section
                    # by adding a special case in _generate_declarations
                else:
                    # Default bit_width to 32 if None
                    if bit_width is None:
                        bit_width = 32
                    # uarch_state result registers, pipeline registers, and validity bits reset to appropriate values
                    if node_type in ['uarch_state', 'pipeline_register']:
                        # Allow node data to override the default zero reset
                        reset_value = node.data.get('reset_value', f"{bit_width}'d0")
                    elif node_type == 'validity_bit':
                        # Validity bits reset to 1 (valid)
                        reset_value = "1'b1"
                    else:
                        reset_value = f"reset_{sanitized_name}"
                    self.reg_declarations.append({
                        'name': sanitized_name,
                        'bit_width': bit_width,
                        'reset_wire': reset_value
                    })
            else:
                # Default to wire for other types
                self.wire_declarations.append({
                    'name': sanitized_name,
                    'bit_width': bit_width
                })
            """
            if self._should_be_register(node):
                self.reg_declarations.append({
                    'name': name,
                    'bit_width': bit_width,
                    'reset_wire': f"reset_{name}"
                })
            elif self._should_be_module(node):
                self.modules.append(
                    self._get_module_data(node)
                )
            else:
                self.wire_declarations.append({
                    'name': name,
                    'bit_width': bit_width
                })
            """

    def _process_uarch_state_node(self, node: Node):
        """Process microarchitectural state nodes (pipeline registers, stall controllers, etc.)."""
        name = node.data.get('name', node.id)
        node_type = node.data.get('type')

        # Get bit_width, inferring it if not present
        if 'bit_width' in node.data:
            bit_width = node.data['bit_width']
        else:
            bit_width = self._infer_bit_width(node)

        # Default to 32 bits if we can't infer
        if bit_width is None:
            bit_width = 32

        # Sanitize the name for Verilog
        sanitized_name = self._sanitize_identifier(name)

        # Skip if already declared
        if sanitized_name in self.declared_names:
            return

        self.declared_names.add(sanitized_name)
        # Map node ID to the sanitized Verilog name
        self.node_id_to_name[node.id] = sanitized_name

        if node_type == 'pipeline_register':
            # Pipeline registers are sequential elements that reset to 0
            # Allow node data to override the default zero reset (e.g. for PC feedback loops)
            reset_val = node.data.get('reset_value', f"{bit_width}'d0")
            self.reg_declarations.append({
                'name': sanitized_name,
                'bit_width': bit_width,
                'reset_wire': reset_val
            })
        elif node_type == 'pipeline_stall_controller':
            # Stall controllers are combinational logic outputs (wires)
            self.wire_declarations.append({
                'name': sanitized_name,
                'bit_width': 1  # Stall signal is 1 bit
            })
        else:
            # Other uarch_state nodes default to registers
            self.reg_declarations.append({
                'name': sanitized_name,
                'bit_width': bit_width,
                'reset_wire': f"{bit_width}'d0"
            })

    def _process_ras_stack_node(self, node: Node):
        """Process Return Address Stack (RAS) stack array node."""
        name = node.data.get('name', node.id)
        sanitized_name = self._sanitize_identifier(name)

        # Skip if already declared
        if sanitized_name in self.declared_names:
            return

        self.declared_names.add(sanitized_name)
        self.node_id_to_name[node.id] = sanitized_name

        # Get RAS dimensions
        bit_width = node.data.get('bit_width', 32)
        depth = node.data.get('depth', 8)

        # Declare RAS stack as a memory array
        # This will generate: reg [31:0] ras_stack [0:7];
        import math
        addr_width = max(1, int(math.ceil(math.log2(depth))))

        self.memory_declarations[sanitized_name] = {
            'bit_width': bit_width,
            'array_depth': depth,
            'addr_width': addr_width,
            'is_ras': True,
            'mem_file': None  # RAS doesn't need initialization file
        }

    def _process_ras_ptr_update_node(self, node: Node):
        """Process RAS pointer update mux node - generates combinational logic for next pointer value."""
        name = node.data.get('name', node.id)
        sanitized_name = self._sanitize_identifier(name)

        # Skip if already declared
        if sanitized_name in self.declared_names:
            return

        self.declared_names.add(sanitized_name)
        self.node_id_to_name[node.id] = sanitized_name

        # Get bit width from node data
        bit_width = node.data.get('bit_width', 3)

        # Declare as wire - the combinational logic will be generated later
        self.wire_declarations.append({
            'name': sanitized_name,
            'bit_width': bit_width
        })

    def _process_ras_ptr_node(self, node: Node):
        """Process RAS stack pointer node - a microarchitectural register."""
        name = node.data.get('name', node.id)
        sanitized_name = self._sanitize_identifier(name)

        # Skip if already declared
        if sanitized_name in self.declared_names:
            return

        self.declared_names.add(sanitized_name)
        self.node_id_to_name[node.id] = sanitized_name

        # Get bit width from node data
        bit_width = node.data.get('bit_width', 3)

        # Declare as register (sequential element)
        self.reg_declarations.append({
            'name': sanitized_name,
            'bit_width': bit_width,
            'reset_wire': f"{bit_width}'d0"
        })

    def _process_renaming_node(self, node: Node):
        """Process register renaming related nodes (uarch_index, denamer, denamer_instance)."""
        name = node.data.get('name', node.id)
        node_type = node.data.get('type')

        # Sanitize the name for Verilog
        sanitized_name = self._sanitize_identifier(name)

        # Skip if already declared
        if sanitized_name in self.declared_names:
            return

        self.declared_names.add(sanitized_name)
        self.node_id_to_name[node.id] = sanitized_name

        if node_type == 'uarch_index':
            # Microarchitectural index - physical register index
            # This is a wire that carries the physical register number
            # Infer width from connected renamer or default to 6 bits (for 64 physical regs)
            bit_width = node.data.get('bit_width', 6)
            self.wire_declarations.append({
                'name': sanitized_name,
                'bit_width': bit_width
            })

        elif node_type in ['denamer', 'denamer_instance']:
            # Denamer converts physical index back to architectural
            # This is combinational logic, output is a wire
            bit_width = node.data.get('bit_width', 5)  # Default to 5 bits for 32 arch regs
            self.wire_declarations.append({
                'name': sanitized_name,
                'bit_width': bit_width
            })

    def _should_be_module(self, node: Node) -> bool:
        """Determine if an ISA state should be implemented as a module (like ALU)."""
        # For now, only ALU is considered
        if node.data.get('type') in ['ternary_op',
                                     'uarch_counter',
                                     'hazard_detection_unit',
                                     'hazard_detector',
                                     'pipeline_stall_controller',
                                     'alu_module',
                                     'opcode_control',
                                     'opcode_assignment',
                                     'alu_operand_mux',
                                     'serialization_counter',
                                     'narrow_operation_unit',
                                     'memory_port_counter',
                                     'multiplexer',
                                     'operand_mux',
                                     'resource_control',
                                     'renamer']:
            return True
        return False
    
    def _get_module_data(self, node: Node) -> Dict:
        # TODO: create classes for generating modules
        type = node.data.get('type')
        if type == 'multiplexer':
            return {
                'module_name': node.data.get('name'),
                'module_type': 'MUX',
                'num_inputs': node.data.get('num_inputs', 0),
            }
        elif type == 'alu_operand_mux':
            # TODO: need to get num inputs, which isn't a field
            return None

    def _process_variable_node(self, node: Node):
        """Process variable nodes."""
        name = node.data['name']
        # Sanitize the name for Verilog (e.g., c.add -> c_add)
        sanitized_name = self._sanitize_identifier(name)

        # Skip port nodes - they're declared in the module header
        if node.data.get('is_port', False):
            # Still map the node ID to its name for reference resolution
            self.node_id_to_name[node.id] = sanitized_name
            return

        # Skip cache interface signals - these are declared by _process_cache_node
        # Cache signals have patterns like icache_*, tlb_*, rocache_*, dcache_*
        if name in self.declared_names:
            is_cache_signal = any(name.startswith(prefix) for prefix in ['icache_', 'tlb_', 'rocache_', 'dcache_'])
            if is_cache_signal:
                # Still map the node ID to its name for reference resolution
                self.node_id_to_name[node.id] = name
                return

        # Skip BTB output signals - these are declared by _process_btb_node
        if node.data.get('btb_output', False):
            self.node_id_to_name[node.id] = name
            return

        # Special case: if this variable is used as an index to memory and gets updated,
        # it should be a register (like PC)
        should_be_register = self._should_be_register(node)

        bit_width = self._infer_bit_width(node)

        # Map node ID to the Verilog name
        self.node_id_to_name[node.id] = sanitized_name

        # Only add declaration if not already declared (e.g., by cache processing)
        if sanitized_name not in self.declared_names:
            self.declared_names.add(sanitized_name)
            if should_be_register:
                self.reg_declarations.append({
                    'name': sanitized_name,
                    'bit_width': bit_width,
                    'reset_wire': f"reset_{sanitized_name}"
                })
            else:
                self.wire_declarations.append({
                    'name': sanitized_name,
                    'bit_width': bit_width
                })

    def _should_be_register(self, node: Node) -> bool:
        """Determine if a variable should be a register based on usage."""
        # Pipeline registers are always registers
        if node.data.get('type') in ['pipeline_register']:
            return True

        # Check for incoming edges that indicate sequential assignment
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type')
            # state_update edges indicate sequential assignment
            if edge_type == 'state_update':
                return True
            # assignment edges with self-reference need registers
            if edge_type == 'assignment':
                # Check if this node appears in the right-hand side expression
                if self._expression_references_node(edge.data.get('right', {}), node):
                    return True

        return False

    def _generate_ila_array_write(self, target: Node, ternary_source: Node):
        """Generate sequential logic for ILA-style array writes.

        ILA uses: array_next = cond ? array : memory_write(array, addr, data)
        Generate: if (!cond) array_rd[addr] <= data;
        """
        # Extract ternary operands
        cond_edge = None
        true_edge = None
        false_edge = None

        for edge in ternary_source.incoming_edges:
            edge_type = edge.data.get('type')
            if edge_type == 'ternary_condition':
                cond_edge = edge
            elif edge_type == 'ternary_true':
                true_edge = edge
            elif edge_type == 'ternary_false':
                false_edge = edge

        if not (cond_edge and true_edge and false_edge):
            print(f"Warning: Could not extract ternary edges for {ternary_source.id}")
            return

        # Get condition name
        cond_name = self.node_id_to_name.get(cond_edge.source.id,
                                             self._sanitize_identifier(cond_edge.source.id))

        # Identify which branch is the memory_write
        memory_write_node = None
        array_node = None

        if false_edge.source.data.get('type') == 'memory_write':
            memory_write_node = false_edge.source
            array_node = true_edge.source
            # If true branch is array (no write), then write when condition is FALSE
            write_condition = f"!{cond_name}"
        elif true_edge.source.data.get('type') == 'memory_write':
            memory_write_node = true_edge.source
            array_node = false_edge.source
            # If false branch is array (no write), then write when condition is TRUE
            write_condition = cond_name
        else:
            print(f"Warning: No memory_write found in ternary {ternary_source.id}")
            return

        # Extract memory_write operands
        # ILA memory_write nodes have: position 0 = array, position 1 = address, position 2 = data
        data_node = None
        addr_node = None
        array_operand = None

        for edge in memory_write_node.incoming_edges:
            src = edge.source
            position = edge.data.get('position', -1)
            if position == 0:
                array_operand = src  # The array being written
            elif position == 1:
                addr_node = src      # Write address
            elif position == 2:
                data_node = src      # Write data

        if not (data_node and addr_node):
            print(f"Warning: Could not extract write address/data from {memory_write_node.id}")
            return

        # Get target array name (replace _wr with _rd)
        array_name = target.id.replace('_wr', '_rd')
        data_name = self.node_id_to_name.get(data_node.id, self._sanitize_identifier(data_node.id))
        addr_name = self.node_id_to_name.get(addr_node.id, self._sanitize_identifier(addr_node.id))

        # Generate conditional write
        self.seq_logic += f"            if ({write_condition}) begin\n"
        self.seq_logic += f"                {array_name}[{addr_name}] <= {data_name};\n"
        self.seq_logic += f"            end\n"

    def _is_array_ternary(self, node: Node) -> bool:
        """Check if a ternary node operates on array operands (ILA pattern).

        ILA models use ternaries like: rf_next = cond ? rf : memory_write(rf, addr, data)
        This can't be represented as a wire in Verilog and must be handled in sequential logic.
        """
        if node.data.get('type') != 'ternary_op':
            return False

        # Check incoming edges for array operands
        if node.incoming_edges:
            for edge in node.incoming_edges:
                source = edge.source
                # Check if source is an array (memory)
                if source.data.get('is_memory') or \
                   (source.data.get('type') == 'isa_state' and \
                    source.data.get('array_depth') is not None):
                    return True
                # Check if source is a memory_write node
                if source.data.get('type') == 'memory_write':
                    return True

        return False

    def _find_full_register_write_enables(self, parent_name: str) -> list:
        """Find mux select enable signals for a full-register write.

        When a register like 'xer' has both full writes (xer <= xer_wr from mtspr)
        and bit-slice writes (xer[34] <= carry from addic), the bit-slice write's
        mux defaults to the old value when no carry instruction is active. If the
        full-register write (mtspr) is active, the bit-slice default would override
        the new bit value. To prevent this, we find the mux select signals that
        drive the full-register write and gate the bit-slice write with their negation.

        Returns a list of Verilog enable signal names, or empty list if no full write exists.
        """
        wr_node_id = f"{parent_name}_wr"
        wr_node = self.graph.nodes.get(wr_node_id)
        if not wr_node:
            return []

        enables = []
        for edge in wr_node.incoming_edges:
            if edge.data.get('type') == 'assignment':
                source = edge.source
                # Check if source is a mux/merge node
                if source.data.get('type') in ['mux', 'multiplexer', 'port_data_merge', 'memory_data_merge']:
                    for mux_edge in source.incoming_edges:
                        if mux_edge.data.get('type') in ['mux_select', 'port_select']:
                            select_name = self.node_id_to_name.get(
                                mux_edge.source.id,
                                self._sanitize_identifier(mux_edge.source.id))
                            enables.append(select_name)
        return enables

    def _expression_references_node(self, expr: Dict, target_node: Node) -> bool:
        """Check if an expression references a specific node."""
        if expr.get('type') == 'identifier':
            return expr.get('name') == target_node.data.get('name')
        elif expr.get('type') == 'binary_op':
            return (self._expression_references_node(expr.get('left', {}), target_node) or
                    self._expression_references_node(expr.get('right', {}), target_node))
        elif expr.get('type') in ['array_access', 'bit_slice']:
            # Check the base expression
            base_expr = expr.get('target', {})
            return self._expression_references_node(base_expr, target_node)
        return False

    def _process_intermediate_node(self, node: Node):
        """Process intermediate computation nodes."""
        expr_id = node.id

        # Skip inlined nodes (they don't need wire declarations)
        if hasattr(self, 'inlined_nodes') and expr_id in self.inlined_nodes:
            # Still store a name mapping for consistency, but mark as inlined
            verilog_name = self._sanitize_identifier(expr_id)
            self.node_id_to_name[expr_id] = verilog_name
            return

        # Create internal wires for intermediate results
        bit_width = self._infer_bit_width(node)

        # Generate a clean name for complex expression types
        node_type = node.data.get('type')
        if node_type == 'concatenation':
            verilog_name = self._generate_concat_name(node)
        elif node_type == 'repetition':
            verilog_name = self._generate_repetition_name(node)
        elif node_type == 'ternary_op':
            # Check if this ternary operates on arrays (ILA pattern)
            # If so, skip wire declaration - it will be handled in sequential logic
            if self._is_array_ternary(node):
                # Still store the name mapping but don't declare a wire
                verilog_name = self._generate_ternary_name(node)
                self.node_id_to_name[expr_id] = verilog_name
                return
            verilog_name = self._generate_ternary_name(node)
        else:
            # Sanitize the name for other types
            verilog_name = self._sanitize_identifier(expr_id)

        # Store the mapping from node ID to Verilog name
        self.node_id_to_name[expr_id] = verilog_name

        # Skip if already declared
        if verilog_name in self.declared_names:
            return

        self.declared_names.add(verilog_name)
        # Only add if not already in wire_declarations
        if not any(w['name'] == verilog_name for w in self.wire_declarations):
            self.wire_declarations.append({
                'name': verilog_name,
                'bit_width': bit_width,
                'original_id': expr_id
            })

    def _declare_narrow_load_word_wire(self, node: Node):
        """Declare intermediate _word wire for array_access nodes that need narrow load selection."""
        # Check if this is a memory read that will need byte/halfword selection
        expr = node.data.get('expression', {})
        array_name = expr.get('target', {}).get('name')

        if not array_name or array_name not in self.memory_declarations:
            return

        memory_width = self.memory_declarations[array_name]['bit_width']
        access_width = self._infer_bit_width(node)

        # If access is narrower than memory, we'll need word wire
        # Skip if memory_width is None (width not yet inferred)
        if access_width and memory_width and access_width < memory_width and access_width >= 8:
            # Get the Verilog name for this node
            verilog_name = self.node_id_to_name.get(node.id)
            if not verilog_name:
                # Try using sanitized node.id as fallback
                verilog_name = self._sanitize_identifier(node.id)

            if verilog_name:
                word_wire_name = f"{verilog_name}_word"
                if word_wire_name not in self.declared_names:
                    self.wire_declarations.append({
                        'name': word_wire_name,
                        'bit_width': memory_width
                    })
                    self.declared_names.add(word_wire_name)

    def _process_module_node(self, node: Node):
        """Process nodes that represent hardware modules (MUX, ALU, Counter, etc.)."""
        node_type = node.data.get('type')
        node_name = node.data.get('name', node.id)

        # Create module generator from node data
        try:
            generator = create_module_generator_from_node(node.data)
            self.module_generators[node.id] = generator

            # Sanitize the module output name
            sanitized_name = self._sanitize_identifier(node_name)
            self.node_id_to_name[node.id] = sanitized_name

            # Special handling for renamer - declare all renaming signals
            if node_type == 'renamer':
                self._process_renamer_node(node, generator, sanitized_name)
                return

            # Special handling for read_only_cache - declare all cache signals
            if node_type == 'read_only_cache':
                self._process_cache_node(node, generator, sanitized_name)
                return

            # Special handling for read_write_cache - declare all cache signals
            if node_type == 'read_write_cache':
                self._process_rw_cache_node(node, generator, sanitized_name)
                return

            # Special handling for tlb_cache - declare all TLB signals
            if node_type == 'tlb_cache':
                self._process_tlb_cache_node(node, sanitized_name)
                return

            # Special handling for instruction_buffer - declare all buffer signals
            if node_type == 'instruction_buffer':
                self._process_ibuf_node(node, generator, sanitized_name)
                return

            # Special handling for btb_storage - declare all BTB signals
            if node_type == 'btb_storage':
                self._process_btb_node(node, generator, sanitized_name)
                return

            # Determine bit width for module outputs - use explicit data or infer
            bit_width = node.data.get('data_width', node.data.get('output_width', None))
            if bit_width is None:
                bit_width = self._infer_bit_width(node)

            # Declare module output
            # For multiplexers and counters, use reg/logic since they're assigned in always blocks
            if sanitized_name not in self.declared_names:
                if node_type in ['multiplexer', 'uarch_counter', 'serialization_counter', 'memory_access_counter']:
                    self.logic_declarations.append({
                        'name': sanitized_name,
                        'bit_width': bit_width
                    })
                else:
                    self.wire_declarations.append({
                        'name': sanitized_name,
                        'bit_width': bit_width
                    })
                self.declared_names.add(sanitized_name)

            # For multiplexers, handle zero-extension of narrow inputs
            if node_type == 'multiplexer':
                mux_width = bit_width
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'mux_input':
                        source_node = edge.source
                        src_width = source_node.data.get('bit_width')
                        src_type = source_node.data.get('type')

                        # If source is narrower than mux, pre-declare zero-extended wire
                        # But skip literals - they can be inlined
                        if src_width and src_width < mux_width:
                            src_name = self.node_id_to_name.get(source_node.id, self._sanitize_identifier(source_node.data.get('name', source_node.id)))

                            # Check if this is a literal (by type or by name pattern) or a concatenation
                            is_literal_type = src_type in ['literal', 'sized_literal']
                            is_literal_name = "'" in src_name or src_name.isdigit()
                            # Concatenation expressions contain braces and can't be used as identifiers
                            is_concat = '{' in src_name or '}' in src_name

                            if not (is_literal_type or is_literal_name or is_concat):
                                ext_name = f"{src_name}_zext"

                                # Only declare the zero-extension wire if a node with this name doesn't exist
                                # If a node exists, it will be declared through normal node processing
                                ext_node_exists = ext_name in self.graph.nodes

                                if not ext_node_exists and ext_name not in self.declared_names:
                                    self.wire_declarations.append({
                                        'name': ext_name,
                                        'bit_width': mux_width
                                    })
                                    self.declared_names.add(ext_name)

        except (ValueError, KeyError) as e:
            print(f"Warning: Could not create module generator for {node.id}: {e}")
            # Fall back to treating as intermediate node
            self._process_intermediate_node(node)

    def _generate_extra_modules(self):
        """Generate extra modules like ALU, MUX, etc."""
        # Generate module definitions from module generators
        # Skip multiplexers since they now use inline always @* blocks
        for node_id, generator in sorted(self.module_generators.items()):
            node = self.graph.nodes.get(node_id)
            if node and node.data.get('type') == 'multiplexer':
                # Skip - multiplexers are now inlined
                continue
            if node and node.data.get('type') == 'tlb_cache':
                # Skip - TLB caches are handled inline in _process_tlb_cache_node
                continue
            if node and node.data.get('type') == 'alu_module':
                # Skip - ALU modules are handled by _generate_alu_module_logic
                continue
            module_def = generator.generate_module()
            self.module_definitions.append(module_def)

        # Legacy support for old module format
        self.extra_modules = ""
        for module in self.modules:
            if module['module_type'] == 'MUX':
                self.extra_modules += self._generate_MUX_module(module['module_name'], module['num_inputs'])

    def _process_cache_node(self, node, generator, cache_name: str):
        """
        Process a read_only_cache node - declare all cache signals and generate instantiation.

        Cache has multiple I/O:
        - Read ports: read_addr_N, read_req_N (inputs), read_data_N, read_valid_N (outputs)
        - Refill interface: refill_addr, refill_req (outputs), refill_data, refill_valid (inputs)
        - Control signals: start (input), idle, complete (outputs)
        """
        data_width = node.data.get('data_width', 32)
        address_width = node.data.get('address_width', 32)
        num_read_ports = node.data.get('num_read_ports', 1)

        # Track generated signal names for instantiation
        read_addrs = []
        read_reqs = []
        read_datas = []
        read_valids = []

        # Declare read port signals
        for i in range(num_read_ports):
            # Read address input - find from graph edges
            read_addr_name = f"{cache_name}_read_addr_{i}"
            if read_addr_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': read_addr_name,
                    'bit_width': address_width
                })
                self.declared_names.add(read_addr_name)
            read_addrs.append(read_addr_name)

            # Read request input
            read_req_name = f"{cache_name}_read_req_{i}"
            if read_req_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': read_req_name,
                    'bit_width': 1
                })
                self.declared_names.add(read_req_name)
            read_reqs.append(read_req_name)

            # Read data output
            read_data_name = f"{cache_name}_data_{i}"
            if read_data_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': read_data_name,
                    'bit_width': data_width
                })
                self.declared_names.add(read_data_name)
            read_datas.append(read_data_name)
            # Map data output node to this signal
            data_node_id = f"{cache_name}_data_{i}"
            if data_node_id in self.graph.nodes:
                self.node_id_to_name[data_node_id] = read_data_name

            # Read valid output
            read_valid_name = f"{cache_name}_valid_{i}"
            if read_valid_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': read_valid_name,
                    'bit_width': 1
                })
                self.declared_names.add(read_valid_name)
            read_valids.append(read_valid_name)
            # Map valid output node
            valid_node_id = f"{cache_name}_valid_{i}"
            if valid_node_id in self.graph.nodes:
                self.node_id_to_name[valid_node_id] = read_valid_name

        # Declare refill interface signals
        refill_addr_name = f"{cache_name}_refill_addr"
        if refill_addr_name not in self.declared_names:
            self.wire_declarations.append({
                'name': refill_addr_name,
                'bit_width': address_width
            })
            self.declared_names.add(refill_addr_name)
        if refill_addr_name in self.graph.nodes:
            self.node_id_to_name[refill_addr_name] = refill_addr_name

        refill_req_name = f"{cache_name}_refill_req"
        if refill_req_name not in self.declared_names:
            self.wire_declarations.append({
                'name': refill_req_name,
                'bit_width': 1
            })
            self.declared_names.add(refill_req_name)

        refill_data_name = f"{cache_name}_refill_data"
        if refill_data_name not in self.declared_names:
            self.wire_declarations.append({
                'name': refill_data_name,
                'bit_width': data_width
            })
            self.declared_names.add(refill_data_name)
        if refill_data_name in self.graph.nodes:
            self.node_id_to_name[refill_data_name] = refill_data_name

        refill_valid_name = f"{cache_name}_refill_valid"
        if refill_valid_name not in self.declared_names:
            self.wire_declarations.append({
                'name': refill_valid_name,
                'bit_width': 1
            })
            self.declared_names.add(refill_valid_name)

        # Declare control signals (start, idle, complete)
        start_signal_id = node.data.get('start_signal')
        idle_signal_id = node.data.get('idle_signal')
        complete_signal_id = node.data.get('complete_signal')

        if start_signal_id:
            start_name = self._sanitize_identifier(start_signal_id)
            if start_name not in self.declared_names:
                self.wire_declarations.append({'name': start_name, 'bit_width': 1})
                self.declared_names.add(start_name)
            if start_signal_id in self.graph.nodes:
                self.node_id_to_name[start_signal_id] = start_name

        if idle_signal_id:
            idle_name = self._sanitize_identifier(idle_signal_id)
            if idle_name not in self.declared_names:
                self.wire_declarations.append({'name': idle_name, 'bit_width': 1})
                self.declared_names.add(idle_name)
            if idle_signal_id in self.graph.nodes:
                self.node_id_to_name[idle_signal_id] = idle_name

        if complete_signal_id:
            complete_name = self._sanitize_identifier(complete_signal_id)
            if complete_name not in self.declared_names:
                self.wire_declarations.append({'name': complete_name, 'bit_width': 1})
                self.declared_names.add(complete_name)
            if complete_signal_id in self.graph.nodes:
                self.node_id_to_name[complete_signal_id] = complete_name

        # Handle flush signals (from fence.i, sfence.vma, etc.)
        flush_signal_name = None
        flush_signal_ids = node.data.get('flush_signals', [])
        if flush_signal_ids:
            # Find flush signals from incoming edges
            flush_signals = []
            for edge in node.incoming_edges:
                if edge.data and edge.data.get('type') == 'cache_flush':
                    flush_sig_id = edge.source.id
                    flush_sig_name = self._sanitize_identifier(flush_sig_id)
                    # Declare the flush signal wire if not already declared
                    if flush_sig_name not in self.declared_names:
                        self.wire_declarations.append({
                            'name': flush_sig_name,
                            'bit_width': 1
                        })
                        self.declared_names.add(flush_sig_name)
                    if flush_sig_id in self.graph.nodes:
                        self.node_id_to_name[flush_sig_id] = flush_sig_name
                    flush_signals.append(flush_sig_name)

            if flush_signals:
                if len(flush_signals) == 1:
                    # Single flush signal
                    flush_signal_name = flush_signals[0]
                else:
                    # Multiple flush sources - OR them together
                    flush_signal_name = f"{cache_name}_flush_combined"
                    if flush_signal_name not in self.declared_names:
                        self.wire_declarations.append({
                            'name': flush_signal_name,
                            'bit_width': 1
                        })
                        self.declared_names.add(flush_signal_name)
                    # Generate OR of all flush signals
                    or_expr = " || ".join(flush_signals)
                    self.comb_logic += f"    assign {flush_signal_name} = {or_expr};\n"

        # Generate cache module instantiation
        instantiation = generator.get_port_connections(
            read_addrs=read_addrs,
            read_reqs=read_reqs,
            read_datas=read_datas,
            read_valids=read_valids,
            refill_addr=refill_addr_name,
            refill_req=refill_req_name,
            refill_data=refill_data_name,
            refill_valid=refill_valid_name,
            flush_signal=flush_signal_name
        )
        self.module_instantiations.append(instantiation)

    def _process_ibuf_node(self, node, generator, buf_name: str):
        """
        Process an instruction_buffer node - declare all buffer signals and generate instantiation.

        Instruction buffer I/O:
        - Fetch interface: fetch_addr, fetch_req (outputs), fetch_data, fetch_valid (inputs)
        - Output: out_data, out_valid (outputs)
        - Consume: consume_bytes, consume_valid (inputs from decode)
        - Control signals: start (input), idle, complete (outputs)
        """
        data_width = node.data.get('data_width', 32)
        fetch_width = node.data.get('fetch_width', 32)
        address_width = node.data.get('address_width', 32)
        num_read_ports = node.data.get('num_read_ports', 1)
        fetch_bytes = node.data.get('fetch_bytes', fetch_width // 8)
        consume_width = max((fetch_bytes - 1).bit_length(), 1) + 1

        # Declare fetch interface signals
        fetch_addr_name = f"{buf_name}_fetch_addr"
        if fetch_addr_name not in self.declared_names:
            self.wire_declarations.append({
                'name': fetch_addr_name,
                'bit_width': address_width
            })
            self.declared_names.add(fetch_addr_name)
        if fetch_addr_name in self.graph.nodes:
            self.node_id_to_name[fetch_addr_name] = fetch_addr_name

        fetch_req_name = f"{buf_name}_fetch_req"
        if fetch_req_name not in self.declared_names:
            self.wire_declarations.append({
                'name': fetch_req_name,
                'bit_width': 1
            })
            self.declared_names.add(fetch_req_name)

        fetch_data_name = f"{buf_name}_fetch_data"
        if fetch_data_name not in self.declared_names:
            self.wire_declarations.append({
                'name': fetch_data_name,
                'bit_width': fetch_width
            })
            self.declared_names.add(fetch_data_name)
        if fetch_data_name in self.graph.nodes:
            self.node_id_to_name[fetch_data_name] = fetch_data_name

        fetch_valid_name = f"{buf_name}_fetch_valid"
        if fetch_valid_name not in self.declared_names:
            self.wire_declarations.append({
                'name': fetch_valid_name,
                'bit_width': 1
            })
            self.declared_names.add(fetch_valid_name)

        # Declare output data signals (one per read port)
        out_datas = []
        out_valids = []
        for i in range(num_read_ports):
            out_data_name = f"{buf_name}_data_{i}"
            if out_data_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': out_data_name,
                    'bit_width': data_width
                })
                self.declared_names.add(out_data_name)
            if out_data_name in self.graph.nodes:
                self.node_id_to_name[out_data_name] = out_data_name
            out_datas.append(out_data_name)

            out_valid_name = f"{buf_name}_valid_{i}"
            if out_valid_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': out_valid_name,
                    'bit_width': 1
                })
                self.declared_names.add(out_valid_name)
            if out_valid_name in self.graph.nodes:
                self.node_id_to_name[out_valid_name] = out_valid_name
            out_valids.append(out_valid_name)

        # Declare consume interface signals
        consume_bytes_name = f"{buf_name}_consume_bytes"
        if consume_bytes_name not in self.declared_names:
            self.wire_declarations.append({
                'name': consume_bytes_name,
                'bit_width': consume_width
            })
            self.declared_names.add(consume_bytes_name)
        if consume_bytes_name in self.graph.nodes:
            self.node_id_to_name[consume_bytes_name] = consume_bytes_name

        # consume_valid is driven by out_valid (consume when data is valid)
        consume_valid_name = f"{buf_name}_consume_valid"
        if consume_valid_name not in self.declared_names:
            self.wire_declarations.append({
                'name': consume_valid_name,
                'bit_width': 1
            })
            self.declared_names.add(consume_valid_name)
        # consume_valid = out_valid_0 (consume when output is valid)
        # If a consume_stall_signal is set, gate consume_valid so the buffer
        # does NOT advance its read pointer during pipeline stalls.
        consume_stall = node.data.get('consume_stall_signal')
        if out_valids:
            if consume_stall:
                self.comb_logic += f"    assign {consume_valid_name} = {out_valids[0]} && !{consume_stall};\n"
            else:
                self.comb_logic += f"    assign {consume_valid_name} = {out_valids[0]};\n"

        # Declare control signals (start, idle, complete)
        start_signal_id = node.data.get('start_signal')
        idle_signal_id = node.data.get('idle_signal')
        complete_signal_id = node.data.get('complete_signal')

        if start_signal_id:
            start_name = self._sanitize_identifier(start_signal_id)
            if start_name not in self.declared_names:
                self.wire_declarations.append({'name': start_name, 'bit_width': 1})
                self.declared_names.add(start_name)
            if start_signal_id in self.graph.nodes:
                self.node_id_to_name[start_signal_id] = start_name

        if idle_signal_id:
            idle_name = self._sanitize_identifier(idle_signal_id)
            if idle_name not in self.declared_names:
                self.wire_declarations.append({'name': idle_name, 'bit_width': 1})
                self.declared_names.add(idle_name)
            if idle_signal_id in self.graph.nodes:
                self.node_id_to_name[idle_signal_id] = idle_name

        if complete_signal_id:
            complete_name = self._sanitize_identifier(complete_signal_id)
            if complete_name not in self.declared_names:
                self.wire_declarations.append({'name': complete_name, 'bit_width': 1})
                self.declared_names.add(complete_name)
            if complete_signal_id in self.graph.nodes:
                self.node_id_to_name[complete_signal_id] = complete_name

        # Handle flush signals
        flush_signal_name = None
        flush_signal_ids = node.data.get('flush_signals', [])
        if flush_signal_ids:
            flush_signals = []
            for edge in node.incoming_edges:
                if edge.data and edge.data.get('type') == 'ibuf_flush':
                    flush_sig_id = edge.source.id
                    flush_sig_name = self._sanitize_identifier(flush_sig_id)
                    if flush_sig_name not in self.declared_names:
                        self.wire_declarations.append({
                            'name': flush_sig_name,
                            'bit_width': 1
                        })
                        self.declared_names.add(flush_sig_name)
                    if flush_sig_id in self.graph.nodes:
                        self.node_id_to_name[flush_sig_id] = flush_sig_name
                    flush_signals.append(flush_sig_name)

            if flush_signals:
                if len(flush_signals) == 1:
                    flush_signal_name = flush_signals[0]
                else:
                    flush_signal_name = f"{buf_name}_flush_combined"
                    if flush_signal_name not in self.declared_names:
                        self.wire_declarations.append({
                            'name': flush_signal_name,
                            'bit_width': 1
                        })
                        self.declared_names.add(flush_signal_name)
                    or_expr = " || ".join(flush_signals)
                    self.comb_logic += f"    assign {flush_signal_name} = {or_expr};\n"

        # Handle redirect_addr signal
        redirect_addr_name = None
        redirect_addr_signal_id = node.data.get('redirect_addr_signal')
        if redirect_addr_signal_id:
            for edge in node.incoming_edges:
                if edge.data and edge.data.get('type') == 'ibuf_redirect_addr':
                    redirect_sig_id = edge.source.id
                    redirect_addr_name = self._sanitize_identifier(redirect_sig_id)
                    if redirect_addr_name not in self.declared_names:
                        self.wire_declarations.append({
                            'name': redirect_addr_name,
                            'bit_width': address_width
                        })
                        self.declared_names.add(redirect_addr_name)
                    if redirect_sig_id in self.graph.nodes:
                        self.node_id_to_name[redirect_sig_id] = redirect_addr_name
                    break

        # Determine reset address for ibuf (matches CPU's reset PC).
        # The PC node is typically split into pc_rd/pc_wr, with reset port reset_pc_rd.
        reset_addr_name = None
        pc_node_id = node.data.get('pc_node')
        if pc_node_id:
            # Check if the PC was split (pc_rd / pc_wr pattern)
            pc_rd_id = f"{pc_node_id}_rd"
            if pc_rd_id in self.graph.nodes:
                reset_addr_name = f"reset_{pc_rd_id}"
            else:
                reset_addr_name = f"reset_{pc_node_id}"

        # Check for raw opcode->length mapping for consume_bytes.
        # When present, generate a combinational decoder from the raw ibuf
        # data output, bypassing the piped instruction opcode.  This fixes
        # a one-cycle lag that causes wrong consume byte counts when
        # consecutive instructions have different lengths.
        raw_opcode_lengths = node.data.get('raw_opcode_lengths')
        if raw_opcode_lengths and out_datas:
            raw_len_name = f"{buf_name}_raw_instr_length"
            self.wire_declarations.append({
                'name': raw_len_name,
                'bit_width': consume_width
            })
            self.declared_names.add(raw_len_name)

            # Group opcodes by instruction length
            by_length = {}
            for opcode, length in raw_opcode_lengths.items():
                by_length.setdefault(length, []).append(opcode)

            # Use the most common length as the default (saves comparisons)
            default_length = max(by_length.keys(), key=lambda k: len(by_length[k]))

            data_signal = out_datas[0]  # raw ibuf head byte

            # For each non-default length group, emit an OR of comparisons
            terms = []
            for length in sorted(by_length.keys()):
                if length == default_length:
                    continue
                opcodes = sorted(by_length[length])
                comparisons = " || ".join(
                    f"({data_signal} == 8'd{op})" for op in opcodes
                )
                is_name = f"{buf_name}_raw_is_{length}byte"
                self.wire_declarations.append({'name': is_name, 'bit_width': 1})
                self.declared_names.add(is_name)
                self.comb_logic += f"    assign {is_name} = {comparisons};\n"
                terms.append((is_name, length))

            # Build ternary chain with default
            expr = f"{consume_width}'d{default_length}"
            for is_name, length in reversed(terms):
                expr = f"{is_name} ? {consume_width}'d{length} : {expr}"
            self.comb_logic += f"    assign {raw_len_name} = {expr};\n"

            # Override consume_bytes to use the raw decoder
            consume_bytes_name = raw_len_name

        # Generate buffer module instantiation with multi-port outputs
        instantiation = generator.get_port_connections(
            fetch_addr=fetch_addr_name,
            fetch_req=fetch_req_name,
            fetch_data=fetch_data_name,
            fetch_valid=fetch_valid_name,
            out_datas=out_datas,
            out_valids=out_valids,
            consume_bytes=consume_bytes_name,
            consume_valid=consume_valid_name,
            reset_addr=reset_addr_name,
            flush_signal=flush_signal_name,
            redirect_addr=redirect_addr_name
        )
        self.module_instantiations.append(instantiation)

        # Add ibuf stall signal to gate CPU register updates when ibuf is empty.
        # When the ibuf has no valid data (e.g., after reset or flush), the CPU
        # must freeze to avoid executing garbage instructions.
        if out_valids:
            ibuf_stall_name = f"{buf_name}_stall"
            if ibuf_stall_name not in self.declared_names:
                self.wire_declarations.append({'name': ibuf_stall_name, 'bit_width': 1})
                self.declared_names.add(ibuf_stall_name)
            self.comb_logic += f"    assign {ibuf_stall_name} = ~{out_valids[0]};\n"

            # Gate CPU state updates on ibuf valid
            existing_stall = getattr(self, '_mem_ext_stall_signal', None)
            if existing_stall is None:
                self._mem_ext_stall_signal = ibuf_stall_name
            else:
                combined = f"{ibuf_stall_name}_combined"
                if combined not in self.declared_names:
                    self.wire_declarations.append({'name': combined, 'bit_width': 1})
                    self.declared_names.add(combined)
                self.comb_logic += f"    assign {combined} = {existing_stall} || {ibuf_stall_name};\n"
                self._mem_ext_stall_signal = combined

    def _process_rw_cache_node(self, node, generator, cache_name: str):
        """
        Process a read_write_cache node - declare all cache signals and generate instantiation.

        RW Cache has multiple I/O:
        - Read ports: read_addr_N, read_req_N (inputs), read_data_N, read_valid_N (outputs)
        - Write port: write_addr, write_data, write_byte_enable, write_req (inputs), write_complete (output)
        - Refill interface: refill_addr, refill_req (outputs), refill_data, refill_valid (inputs)
        - Write-through interface: write_through_addr, write_through_data, write_through_byte_enable,
                                   write_through_req (outputs), write_through_complete (input)
        - Control signals: idle, complete (outputs)
        """
        data_width = node.data.get('data_width', 32)
        address_width = node.data.get('address_width', 32)
        num_read_ports = node.data.get('num_read_ports', 1)
        byte_enable_width = data_width // 8

        # Track generated signal names for instantiation
        read_addrs = []
        read_reqs = []
        read_datas = []
        read_valids = []

        # Declare read port signals (reuse logic from RO cache)
        for i in range(num_read_ports):
            read_addr_name = f"{cache_name}_read_addr_{i}"
            if read_addr_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': read_addr_name,
                    'bit_width': address_width
                })
                self.declared_names.add(read_addr_name)
            read_addrs.append(read_addr_name)

            read_req_name = f"{cache_name}_read_req_{i}"
            if read_req_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': read_req_name,
                    'bit_width': 1
                })
                self.declared_names.add(read_req_name)
            read_reqs.append(read_req_name)

            read_data_name = f"{cache_name}_data_{i}"
            if read_data_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': read_data_name,
                    'bit_width': data_width
                })
                self.declared_names.add(read_data_name)
            read_datas.append(read_data_name)
            if read_data_name in self.graph.nodes:
                self.node_id_to_name[read_data_name] = read_data_name

            read_valid_name = f"{cache_name}_valid_{i}"
            if read_valid_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': read_valid_name,
                    'bit_width': 1
                })
                self.declared_names.add(read_valid_name)
            read_valids.append(read_valid_name)
            if read_valid_name in self.graph.nodes:
                self.node_id_to_name[read_valid_name] = read_valid_name

        # Declare write port signals
        write_addr_name = f"{cache_name}_write_addr"
        if write_addr_name not in self.declared_names:
            self.wire_declarations.append({'name': write_addr_name, 'bit_width': address_width})
            self.declared_names.add(write_addr_name)

        write_data_name = f"{cache_name}_write_data"
        if write_data_name not in self.declared_names:
            self.wire_declarations.append({'name': write_data_name, 'bit_width': data_width})
            self.declared_names.add(write_data_name)

        write_byte_enable_name = f"{cache_name}_write_byte_enable"
        if write_byte_enable_name not in self.declared_names:
            self.wire_declarations.append({'name': write_byte_enable_name, 'bit_width': byte_enable_width})
            self.declared_names.add(write_byte_enable_name)

        write_req_name = f"{cache_name}_write_req"
        if write_req_name not in self.declared_names:
            self.wire_declarations.append({'name': write_req_name, 'bit_width': 1})
            self.declared_names.add(write_req_name)

        write_complete_name = f"{cache_name}_write_complete"
        if write_complete_name not in self.declared_names:
            self.wire_declarations.append({'name': write_complete_name, 'bit_width': 1})
            self.declared_names.add(write_complete_name)

        # Generate assignments for cache write inputs from the connected write port
        # Find the write port connected to this cache via cache_write_input edge
        write_port_id = node.data.get('write_port')
        cache_write_assigns = []
        if write_port_id:
            write_port = self.graph.nodes.get(write_port_id)
            if write_port:
                # Get the write port's input signals
                for edge in write_port.incoming_edges:
                    edge_type = edge.data.get('type')
                    source = edge.source
                    source_name = self.node_id_to_name.get(source.id, self._sanitize_identifier(source.id))

                    if edge_type == 'write_address':
                        # Generate: cache_write_addr = write_address_source
                        cache_write_assigns.append(f"    assign {write_addr_name} = {source_name};\n")
                    elif edge_type == 'write_data':
                        # The data comes from a mux - get the mux output name
                        # For merged write data, use the positioned data mux
                        data_mux_name = self.node_id_to_name.get(source.id, self._sanitize_identifier(source.id))
                        cache_write_assigns.append(f"    assign {write_data_name} = {data_mux_name};\n")

                # Get write enable from cache node's stored combined_write_enable (ORIGINAL, not modified)
                # Note: The write_port's combined_write_enable may have been modified by pipelining
                # to point to the cache's write_through_req (which is the OUTPUT, not INPUT)
                combined_enable = node.data.get('combined_write_enable')
                if combined_enable:
                    enable_name = self.node_id_to_name.get(combined_enable, self._sanitize_identifier(combined_enable))
                    # Gate cache write_req with Memory stage validity
                    # Flushed stores (PIPE_Memory_valid_PIPE=0) must NOT trigger cache writes
                    # The cache write_through_req output is NOT gated (once cache starts, it must complete)
                    validity_signal = "PIPE_Memory_valid_PIPE"
                    gated_enable_name = f"{enable_name}_valid_gated"
                    # Check if the gated signal node already exists in the graph
                    # (created by add_rwcache_latency_stalls in cache_optimization.py)
                    # If so, don't generate duplicate assignment here
                    gated_node_exists = gated_enable_name in self.graph.nodes or \
                                        any(n.id == gated_enable_name for n in self.graph.nodes.values())
                    if not gated_node_exists:
                        # Declare the gated signal if not already done
                        if gated_enable_name not in self.declared_names:
                            self.wire_declarations.append({'name': gated_enable_name, 'bit_width': 1})
                            self.declared_names.add(gated_enable_name)
                        # Create gated assignment: gated = enable && valid
                        cache_write_assigns.append(f"    assign {gated_enable_name} = {enable_name} && {validity_signal};\n")
                    # Use gated signal for cache write_req
                    cache_write_assigns.append(f"    assign {write_req_name} = {gated_enable_name};\n")

                # Get byte enables from cache node's stored values (may have more than write_port)
                store_byte_enables = node.data.get('store_byte_enables', {})
                writers = node.data.get('writers', [])

                # Collect all byte enable expressions
                be_signals = []

                # Add sub-word store byte enables (sb, sh) - must be gated by their instruction enables
                for instr, be_node_id in store_byte_enables.items():
                    be_name = self.node_id_to_name.get(be_node_id, self._sanitize_identifier(be_node_id))
                    # Find the instruction enable for this sub-word store
                    instr_enable_candidates = [
                        f"PIPE_Memory_PIPE_Execute_{instr}_enable_PIPE_PIPE",
                        f"PIPE_Execute_{instr}_enable_PIPE",
                        f"{instr}_enable"
                    ]
                    instr_enable_name = None
                    for candidate in instr_enable_candidates:
                        if candidate in self.node_id_to_name:
                            instr_enable_name = self.node_id_to_name[candidate]
                            break
                        if candidate in self.graph.nodes:
                            instr_enable_name = self._sanitize_identifier(candidate)
                            break

                    if instr_enable_name:
                        # Gate the byte enable with instruction enable
                        be_signals.append(f"({be_name} & {{4{{{instr_enable_name}}}}})")
                        print(f"    Added sub-word store {instr} byte enable: ({be_name} & {{4{{{instr_enable_name}}}}})")
                    else:
                        # Fallback if no enable found (shouldn't happen in normal operation)
                        be_signals.append(be_name)
                        print(f"    Warning: Added {instr} byte enable without gating: {be_name}")

                # Add full-word store byte enables (sw, sd, etc.) - these need all 1's when enabled
                # Full-word stores don't have byte enable computation because they write all bytes
                for writer in writers:
                    if writer not in store_byte_enables:
                        # This is a full-word store (e.g., sw) - find its enable signal
                        # Look for the pipelined enable signal in Memory stage
                        writer_enable_candidates = [
                            f"PIPE_Memory_PIPE_Execute_{writer}_enable_PIPE_PIPE",
                            f"PIPE_Execute_{writer}_enable_PIPE",
                            f"{writer}_enable"
                        ]
                        writer_enable_name = None
                        for candidate in writer_enable_candidates:
                            if candidate in self.node_id_to_name:
                                writer_enable_name = self.node_id_to_name[candidate]
                                break
                            if candidate in self.graph.nodes:
                                writer_enable_name = self._sanitize_identifier(candidate)
                                break

                        if writer_enable_name:
                            # When this store is enabled, all byte lanes are active
                            # Use {byte_enable_width{enable}} to replicate the enable bit
                            be_signals.append(f"{{4{{{writer_enable_name}}}}}")
                            print(f"    Added full-word store {writer} byte enable: {{4{{{writer_enable_name}}}}}")

                if be_signals:
                    be_expr = ' | '.join(be_signals)
                    cache_write_assigns.append(f"    assign {write_byte_enable_name} = {be_expr};\n")

        # Store for later addition to comb_logic
        if not hasattr(self, '_pending_cache_assigns'):
            self._pending_cache_assigns = []
        self._pending_cache_assigns.extend(cache_write_assigns)

        # Declare refill interface signals
        refill_addr_name = f"{cache_name}_refill_addr"
        if refill_addr_name not in self.declared_names:
            self.wire_declarations.append({'name': refill_addr_name, 'bit_width': address_width})
            self.declared_names.add(refill_addr_name)
        if refill_addr_name in self.graph.nodes:
            self.node_id_to_name[refill_addr_name] = refill_addr_name

        refill_req_name = f"{cache_name}_refill_req"
        if refill_req_name not in self.declared_names:
            self.wire_declarations.append({'name': refill_req_name, 'bit_width': 1})
            self.declared_names.add(refill_req_name)

        refill_data_name = f"{cache_name}_refill_data"
        if refill_data_name not in self.declared_names:
            self.wire_declarations.append({'name': refill_data_name, 'bit_width': data_width})
            self.declared_names.add(refill_data_name)
        if refill_data_name in self.graph.nodes:
            self.node_id_to_name[refill_data_name] = refill_data_name

        refill_valid_name = f"{cache_name}_refill_valid"
        if refill_valid_name not in self.declared_names:
            self.wire_declarations.append({'name': refill_valid_name, 'bit_width': 1})
            self.declared_names.add(refill_valid_name)

        # Declare write-through interface signals
        wt_addr_name = f"{cache_name}_write_through_addr"
        if wt_addr_name not in self.declared_names:
            self.wire_declarations.append({'name': wt_addr_name, 'bit_width': address_width})
            self.declared_names.add(wt_addr_name)

        wt_data_name = f"{cache_name}_write_through_data"
        if wt_data_name not in self.declared_names:
            self.wire_declarations.append({'name': wt_data_name, 'bit_width': data_width})
            self.declared_names.add(wt_data_name)

        wt_byte_enable_name = f"{cache_name}_write_through_byte_enable"
        if wt_byte_enable_name not in self.declared_names:
            self.wire_declarations.append({'name': wt_byte_enable_name, 'bit_width': byte_enable_width})
            self.declared_names.add(wt_byte_enable_name)

        wt_req_name = f"{cache_name}_write_through_req"
        if wt_req_name not in self.declared_names:
            self.wire_declarations.append({'name': wt_req_name, 'bit_width': 1})
            self.declared_names.add(wt_req_name)

        wt_complete_name = f"{cache_name}_write_through_complete"
        if wt_complete_name not in self.declared_names:
            self.wire_declarations.append({'name': wt_complete_name, 'bit_width': 1})
            self.declared_names.add(wt_complete_name)

        # Declare control signals
        idle_signal_id = node.data.get('idle_signal')
        complete_signal_id = node.data.get('complete_signal')

        idle_name = f"{cache_name}_idle"
        if idle_signal_id:
            idle_name = self._sanitize_identifier(idle_signal_id)
        if idle_name not in self.declared_names:
            self.wire_declarations.append({'name': idle_name, 'bit_width': 1})
            self.declared_names.add(idle_name)
        if idle_signal_id and idle_signal_id in self.graph.nodes:
            self.node_id_to_name[idle_signal_id] = idle_name

        complete_name = f"{cache_name}_complete"
        if complete_signal_id:
            complete_name = self._sanitize_identifier(complete_signal_id)
        if complete_name not in self.declared_names:
            self.wire_declarations.append({'name': complete_name, 'bit_width': 1})
            self.declared_names.add(complete_name)
        if complete_signal_id and complete_signal_id in self.graph.nodes:
            self.node_id_to_name[complete_signal_id] = complete_name

        # Generate cache module instantiation
        instantiation = generator.get_port_connections(
            read_addrs=read_addrs,
            read_reqs=read_reqs,
            read_datas=read_datas,
            read_valids=read_valids,
            write_addr=write_addr_name,
            write_data=write_data_name,
            write_byte_enable=write_byte_enable_name,
            write_req=write_req_name,
            write_complete=write_complete_name,
            refill_addr=refill_addr_name,
            refill_req=refill_req_name,
            refill_data=refill_data_name,
            refill_valid=refill_valid_name,
            write_through_addr=wt_addr_name,
            write_through_data=wt_data_name,
            write_through_byte_enable=wt_byte_enable_name,
            write_through_req=wt_req_name,
            write_through_complete=wt_complete_name,
            idle=idle_name,
            complete=complete_name
        )
        self.module_instantiations.append(instantiation)

    def _process_tlb_cache_node(self, node, tlb_name: str):
        """
        Process a tlb_cache node - generate inline TLB with storage and matching.

        TLB has:
        - VPN inputs for each level (for tag matching)
        - Per-depth outputs: hit_depth1, data_depth1, hit_depth2, data_depth2, etc.
        - Control signals: start, idle, complete
        - PTW update interface: from memory read nodes
        - Flush signal from sfence.vma
        """
        pte_width = node.data.get('pte_width', 32)
        num_levels = node.data.get('num_levels', 2)
        vpn_widths = node.data.get('vpn_widths', [10, 10])
        num_entries = node.data.get('num_entries', 64)
        associativity = node.data.get('associativity', 4)
        flush_signal = node.data.get('flush_signal', 'flush_tlb')

        # Derived parameters
        num_sets = num_entries // associativity
        index_width = max(1, (num_sets - 1).bit_length())
        depth_width = max(1, num_levels.bit_length())
        way_bits = max(1, (associativity - 1).bit_length())

        # Map TLB node to name
        self.node_id_to_name[node.id] = tlb_name

        # Declare per-depth hit and data signals as wires (driven by TLB logic)
        for depth in range(1, num_levels + 1):
            hit_name = f"{tlb_name}_hit_depth{depth}"
            data_name = f"{tlb_name}_data_depth{depth}"

            if hit_name not in self.declared_names:
                self.wire_declarations.append({'name': hit_name, 'bit_width': 1})
                self.declared_names.add(hit_name)
            hit_node_id = f"{tlb_name}_hit_depth{depth}"
            if hit_node_id in self.graph.nodes:
                self.node_id_to_name[hit_node_id] = hit_name

            if data_name not in self.declared_names:
                self.wire_declarations.append({'name': data_name, 'bit_width': pte_width})
                self.declared_names.add(data_name)
            data_node_id = f"{tlb_name}_data_depth{depth}"
            if data_node_id in self.graph.nodes:
                self.node_id_to_name[data_node_id] = data_name

            # Miss signals (inverse of hit)
            miss_name = f"{tlb_name}_miss_depth{depth}"
            if miss_name not in self.declared_names:
                self.wire_declarations.append({'name': miss_name, 'bit_width': 1})
                self.declared_names.add(miss_name)
            miss_node_id = f"{tlb_name}_miss_depth{depth}"
            if miss_node_id in self.graph.nodes:
                self.node_id_to_name[miss_node_id] = miss_name

        # Declare VPN input signals
        for i, width in enumerate(vpn_widths):
            vpn_name = f"{tlb_name}_vpn{i}_in"
            if vpn_name not in self.declared_names:
                self.wire_declarations.append({'name': vpn_name, 'bit_width': width})
                self.declared_names.add(vpn_name)
            vpn_node_id = f"{tlb_name}_vpn{i}_in"
            if vpn_node_id in self.graph.nodes:
                self.node_id_to_name[vpn_node_id] = vpn_name

        # Declare control signals
        control_signals = ['start', 'idle', 'complete', 'ptw_active', 'update']
        for signal in control_signals:
            signal_name = f"{tlb_name}_{signal}"
            if signal_name not in self.declared_names:
                self.wire_declarations.append({'name': signal_name, 'bit_width': 1})
                self.declared_names.add(signal_name)
            signal_node_id = f"{tlb_name}_{signal}"
            if signal_node_id in self.graph.nodes:
                self.node_id_to_name[signal_node_id] = signal_name

        # Generate TLB storage and logic
        if not hasattr(self, '_pending_tlb_assigns'):
            self._pending_tlb_assigns = []
        if not hasattr(self, '_pending_tlb_seq'):
            self._pending_tlb_seq = []

        tlb = []
        tlb.append(f"\n    // ============================================================")
        tlb.append(f"    // TLB: {tlb_name} ({num_entries} entries, {associativity}-way, {num_levels} levels)")
        tlb.append(f"    // ============================================================")

        # Storage arrays
        tlb.append(f"    // TLB storage arrays")
        tlb.append(f"    reg {tlb_name}_valid [{num_sets-1}:0][{associativity-1}:0];")
        tlb.append(f"    reg [{depth_width-1}:0] {tlb_name}_depth [{num_sets-1}:0][{associativity-1}:0];")
        for i, width in enumerate(vpn_widths):
            tlb.append(f"    reg [{width-1}:0] {tlb_name}_vpn{i} [{num_sets-1}:0][{associativity-1}:0];")
        tlb.append(f"    reg [{pte_width-1}:0] {tlb_name}_pte [{num_sets-1}:0][{associativity-1}:0];")
        tlb.append(f"    reg [{way_bits-1}:0] {tlb_name}_lru [{num_sets-1}:0];")
        tlb.append(f"    reg [{way_bits-1}:0] {tlb_name}_update_way;")
        tlb.append("")

        # Index extraction (from VPN0 low bits)
        tlb.append(f"    // Index extraction")
        tlb.append(f"    wire [{index_width-1}:0] {tlb_name}_index = {tlb_name}_vpn0_in[{index_width-1}:0];")
        tlb.append("")

        # Per-way, per-depth matching
        tlb.append(f"    // Per-way tag matching")
        for way in range(associativity):
            tlb.append(f"    // Way {way}")
            for lvl in range(num_levels):
                tlb.append(f"    wire {tlb_name}_vpn{lvl}_match_w{way} = ({tlb_name}_vpn{lvl}[{tlb_name}_index][{way}] == {tlb_name}_vpn{lvl}_in);")

            # Per-depth hit: depth D matches VPNs 0 to (depth-1)
            # vpn0 = root level (highest bits), vpn1 = next level, etc.
            # depth=1 (superpage): match vpn0 only
            # depth=2 (4KB page): match vpn0 AND vpn1
            for depth in range(1, num_levels + 1):
                match_terms = [f"{tlb_name}_vpn{lvl}_match_w{way}" for lvl in range(depth)]
                match_expr = " && ".join(match_terms) if match_terms else "1'b1"
                tlb.append(f"    wire {tlb_name}_depth{depth}_match_w{way} = {tlb_name}_valid[{tlb_name}_index][{way}] && ({tlb_name}_depth[{tlb_name}_index][{way}] == {depth_width}'d{depth}) && {match_expr};")
        tlb.append("")

        # Aggregate hits per depth
        tlb.append(f"    // Per-depth hit aggregation")
        for depth in range(1, num_levels + 1):
            hit_terms = [f"{tlb_name}_depth{depth}_match_w{way}" for way in range(associativity)]
            tlb.append(f"    wire {tlb_name}_any_hit_depth{depth} = " + " || ".join(hit_terms) + ";")

        all_hit_terms = [f"{tlb_name}_any_hit_depth{d}" for d in range(1, num_levels + 1)]
        tlb.append(f"    wire {tlb_name}_any_hit = " + " || ".join(all_hit_terms) + ";")
        tlb.append("")

        # Hit way selection per depth
        tlb.append(f"    // Hit way selection")
        for depth in range(1, num_levels + 1):
            tlb.append(f"    reg [{way_bits-1}:0] {tlb_name}_hit_way_depth{depth};")
        tlb.append(f"    always @* begin")
        for depth in range(1, num_levels + 1):
            tlb.append(f"        {tlb_name}_hit_way_depth{depth} = {way_bits}'d0;")
            for way in range(associativity):
                tlb.append(f"        if ({tlb_name}_depth{depth}_match_w{way}) {tlb_name}_hit_way_depth{depth} = {way_bits}'d{way};")
        tlb.append(f"    end")
        tlb.append("")

        # Output hit and data per depth
        tlb.append(f"    // Output hit/data per depth")
        for depth in range(1, num_levels + 1):
            tlb.append(f"    assign {tlb_name}_hit_depth{depth} = {tlb_name}_any_hit_depth{depth};")
            tlb.append(f"    assign {tlb_name}_data_depth{depth} = {tlb_name}_pte[{tlb_name}_index][{tlb_name}_hit_way_depth{depth}];")
        tlb.append("")

        # Miss signals (inverse of hit) - these drive the gated enables for PTW reads
        # The gated enables are already generated elsewhere, these are for reference
        # tlb.append(f"    // Miss signals (inverse of hit)")
        # for depth in range(1, num_levels + 1):
        #     tlb.append(f"    assign {tlb_name}_miss_depth{depth} = ~{tlb_name}_hit_depth{depth};")
        # tlb.append("")

        # Per-level update signals - support superpages by detecting leaf at each level
        # level_info contains: depth, read_node_id, pte_node_id, leaf_indicator
        level_info = node.data.get('level_info', [])

        tlb.append(f"    // Per-level update signals (superpage support)")
        update_terms = []
        for lvl_info in level_info:
            depth = lvl_info['depth']
            read_node_id = lvl_info['read_node_id']
            leaf_indicator = lvl_info.get('leaf_indicator')
            is_last_level = (depth == num_levels)

            # Construct gated enable signal name from read node ID
            read_name = self._sanitize_identifier(read_node_id)
            gated_enable = f"{read_name}_gated_enable"
            update_signal_name = f"{tlb_name}_update_depth{depth}"

            if is_last_level:
                # Last level is always a leaf - update unconditionally on read
                tlb.append(f"    assign {update_signal_name} = {gated_enable};")
            elif leaf_indicator:
                # Intermediate level - update only if leaf indicator is set
                tlb.append(f"    assign {update_signal_name} = {gated_enable} && {leaf_indicator};")
            else:
                # No leaf indicator - this level can never be a leaf (shouldn't happen)
                tlb.append(f"    assign {update_signal_name} = 1'b0;  // No leaf indicator")

            update_terms.append(update_signal_name)

        # Combined update signal - OR of all per-level updates
        if update_terms:
            tlb.append(f"    assign {tlb_name}_update = {' || '.join(update_terms)};")
        else:
            tlb.append(f"    assign {tlb_name}_update = 1'b0;  // No level info")
        tlb.append("")

        self._pending_tlb_assigns.extend([s + "\n" for s in tlb])

        # Sequential logic for TLB update
        seq = []
        seq.append(f"\n    // TLB update logic for {tlb_name}")
        seq.append(f"    integer {tlb_name}_init_i, {tlb_name}_init_j;")
        seq.append(f"    always @(posedge clk) begin")
        seq.append(f"        if (reset || {flush_signal}) begin")
        seq.append(f"            for ({tlb_name}_init_i = 0; {tlb_name}_init_i < {num_sets}; {tlb_name}_init_i = {tlb_name}_init_i + 1) begin")
        seq.append(f"                for ({tlb_name}_init_j = 0; {tlb_name}_init_j < {associativity}; {tlb_name}_init_j = {tlb_name}_init_j + 1) begin")
        seq.append(f"                    {tlb_name}_valid[{tlb_name}_init_i][{tlb_name}_init_j] <= 1'b0;")
        seq.append(f"                end")
        seq.append(f"                {tlb_name}_lru[{tlb_name}_init_i] <= {way_bits}'d0;")
        seq.append(f"            end")
        seq.append(f"            {tlb_name}_update_way <= {way_bits}'d0;")
        seq.append(f"        end else begin")

        # Update LRU on hit
        seq.append(f"            // Update LRU on hit")
        seq.append(f"            if ({tlb_name}_any_hit) begin")
        for depth in range(1, num_levels + 1):
            seq.append(f"                if ({tlb_name}_any_hit_depth{depth}) {tlb_name}_lru[{tlb_name}_index] <= {tlb_name}_hit_way_depth{depth};")
        seq.append(f"            end")

        # Select victim way and fill on PTW update (using the itlb_update signal from graph)
        update_signal = f"{tlb_name}_update"
        seq.append(f"            // Fill TLB on PTW completion")
        seq.append(f"            if ({update_signal}) begin")
        seq.append(f"                // Select victim way (prefer invalid entry)")
        seq.append(f"                {tlb_name}_update_way <= {way_bits}'d0;")
        for way in range(associativity):
            seq.append(f"                if (!{tlb_name}_valid[{tlb_name}_index][{way}]) {tlb_name}_update_way <= {way_bits}'d{way};")
        if associativity > 1:
            seq.append(f"                else {tlb_name}_update_way <= {tlb_name}_lru[{tlb_name}_index] ^ {way_bits}'d1;")
        seq.append(f"            end")
        seq.append(f"        end")
        seq.append(f"    end")

        # Separate always block for actually writing TLB entries
        # This fills with the final PTE data when PTW completes at any level
        # The depth and PTE source depend on which level triggered the update
        seq.append(f"")
        seq.append(f"    // TLB fill logic (write entry on PTW completion)")
        seq.append(f"    // Supports superpages - fill at the level where leaf was found")
        seq.append(f"    always @(posedge clk) begin")
        seq.append(f"        if (!reset && !{flush_signal}) begin")

        # Generate per-level fill logic using if-else chain (priority to earlier levels = superpages)
        level_info = node.data.get('level_info', [])
        first = True
        for lvl_info in level_info:
            depth = lvl_info['depth']
            pte_node_id = lvl_info.get('pte_node_id', '')
            update_signal_name = f"{tlb_name}_update_depth{depth}"

            # Determine PTE source name from pte_node_id
            # The pte_node_id is like 'pte1' or 'addr_pte1', use it directly
            if pte_node_id:
                pte_source = pte_node_id
            else:
                # Fallback based on depth (shouldn't happen if level_info is populated)
                pte_source = f"pte{num_levels - depth}" if tlb_name == "itlb" else f"addr_pte{num_levels - depth}"

            if first:
                seq.append(f"            if ({update_signal_name}) begin")
                first = False
            else:
                seq.append(f"            end else if ({update_signal_name}) begin")

            seq.append(f"                {tlb_name}_valid[{tlb_name}_index][{tlb_name}_update_way] <= 1'b1;")
            seq.append(f"                {tlb_name}_depth[{tlb_name}_index][{tlb_name}_update_way] <= {depth_width}'d{depth};")
            for i in range(num_levels):
                seq.append(f"                {tlb_name}_vpn{i}[{tlb_name}_index][{tlb_name}_update_way] <= {tlb_name}_vpn{i}_in;")
            seq.append(f"                {tlb_name}_pte[{tlb_name}_index][{tlb_name}_update_way] <= {pte_source};")

        if first:
            # No level_info - fallback to old behavior
            pte_source = "pte0" if tlb_name == "itlb" else "addr_pte0"
            seq.append(f"            if ({update_signal}) begin")
            seq.append(f"                {tlb_name}_valid[{tlb_name}_index][{tlb_name}_update_way] <= 1'b1;")
            seq.append(f"                {tlb_name}_depth[{tlb_name}_index][{tlb_name}_update_way] <= {depth_width}'d{num_levels};")
            for i in range(num_levels):
                seq.append(f"                {tlb_name}_vpn{i}[{tlb_name}_index][{tlb_name}_update_way] <= {tlb_name}_vpn{i}_in;")
            seq.append(f"                {tlb_name}_pte[{tlb_name}_index][{tlb_name}_update_way] <= {pte_source};")

        seq.append(f"            end")
        seq.append(f"        end")
        seq.append(f"    end")

        self._pending_tlb_seq.extend([s + "\n" for s in seq])

        print(f"    Processed TLB cache node: {tlb_name} ({num_entries} entries, {associativity}-way)")

    def _process_btb_node(self, node, generator, btb_name: str):
        """
        Process a btb_storage node - declare all BTB signals and generate instantiation.

        BTB has these I/O:
        - Lookup: lookup_pc (input), hit, predicted_target, predicted_taken (outputs)
        - Dual-port (optional): execute_lookup_pc (input), execute_hit, execute_predicted_taken (outputs)
        - Update: update_enable, update_pc, update_target, update_taken (inputs)
        """
        pc_width = node.data.get('pc_width', 32)
        target_width = node.data.get('target_width', 32)
        dual_port = node.data.get('dual_port', False)

        # Get BTB output node IDs from the graph
        # The BTB optimization creates nodes with predictable names
        btb_base = btb_name.replace('_storage', '')

        # Declare BTB output signals
        hit_name = f"{btb_base}_hit"
        if hit_name not in self.declared_names:
            self.wire_declarations.append({
                'name': hit_name,
                'bit_width': 1
            })
            self.declared_names.add(hit_name)
        # Map the hit node to this signal
        if hit_name in self.graph.nodes:
            self.node_id_to_name[hit_name] = hit_name

        predicted_target_name = f"{btb_base}_predicted_target"
        if predicted_target_name not in self.declared_names:
            self.wire_declarations.append({
                'name': predicted_target_name,
                'bit_width': target_width
            })
            self.declared_names.add(predicted_target_name)
        if predicted_target_name in self.graph.nodes:
            self.node_id_to_name[predicted_target_name] = predicted_target_name

        predicted_taken_name = f"{btb_base}_predicted_taken"
        if predicted_taken_name not in self.declared_names:
            self.wire_declarations.append({
                'name': predicted_taken_name,
                'bit_width': 1
            })
            self.declared_names.add(predicted_taken_name)
        if predicted_taken_name in self.graph.nodes:
            self.node_id_to_name[predicted_taken_name] = predicted_taken_name

        # Dual-port signals (for Execute-stage misprediction detection)
        execute_lookup_pc_name = None
        execute_hit_name = None
        execute_predicted_taken_name = None

        if dual_port:
            execute_hit_name = f"{btb_base}_execute_hit"
            if execute_hit_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': execute_hit_name,
                    'bit_width': 1
                })
                self.declared_names.add(execute_hit_name)
            if execute_hit_name in self.graph.nodes:
                self.node_id_to_name[execute_hit_name] = execute_hit_name

            execute_predicted_taken_name = f"{btb_base}_execute_predicted_taken"
            if execute_predicted_taken_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': execute_predicted_taken_name,
                    'bit_width': 1
                })
                self.declared_names.add(execute_predicted_taken_name)
            if execute_predicted_taken_name in self.graph.nodes:
                self.node_id_to_name[execute_predicted_taken_name] = execute_predicted_taken_name

        # Find lookup_pc from incoming edges
        lookup_pc_name = None
        for edge in node.incoming_edges:
            if edge.data.get('type') == 'btb_lookup':
                source_name = self.node_id_to_name.get(edge.source.id)
                if source_name is None:
                    # Use node ID directly - 'name' field may be the original name before splitting
                    source_name = self._sanitize_identifier(edge.source.id)
                lookup_pc_name = source_name
                break

        if lookup_pc_name is None:
            # Fallback: use fetch PC (pc_rd is the read port in pipelined designs)
            lookup_pc_name = "pc_rd"

        # Find update signals from incoming edges
        update_enable_name = None
        update_pc_name = None
        update_target_name = None
        update_taken_name = None

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type')
            source_name = self.node_id_to_name.get(edge.source.id)
            if source_name is None:
                source_name = self._sanitize_identifier(edge.source.data.get('name', edge.source.id))

            if edge_type == 'btb_update_enable':
                update_enable_name = source_name
            elif edge_type == 'btb_update_pc':
                update_pc_name = source_name
            elif edge_type == 'btb_update_target':
                update_target_name = source_name
            elif edge_type == 'btb_update_taken':
                update_taken_name = source_name
            elif edge_type == 'btb_execute_lookup' and dual_port:
                execute_lookup_pc_name = source_name

        # Use defaults if not found
        if update_enable_name is None:
            update_enable_name = f"{btb_base}_update_enable"
        if update_pc_name is None:
            update_pc_name = "pc_execute"
        if update_target_name is None:
            update_target_name = "branch_target"
        if update_taken_name is None:
            update_taken_name = "branch_taken"
        if dual_port and execute_lookup_pc_name is None:
            # Default to using update_pc (which is Execute-stage PC)
            execute_lookup_pc_name = update_pc_name

        # Generate BTB module instantiation
        if dual_port:
            instantiation = generator.get_port_connections(
                lookup_pc=lookup_pc_name,
                hit=hit_name,
                predicted_target=predicted_target_name,
                predicted_taken=predicted_taken_name,
                execute_lookup_pc=execute_lookup_pc_name,
                execute_hit=execute_hit_name,
                execute_predicted_taken=execute_predicted_taken_name,
                update_enable=update_enable_name,
                update_pc=update_pc_name,
                update_target=update_target_name,
                update_taken=update_taken_name
            )
        else:
            instantiation = generator.get_port_connections(
                lookup_pc=lookup_pc_name,
                hit=hit_name,
                predicted_target=predicted_target_name,
                predicted_taken=predicted_taken_name,
                update_enable=update_enable_name,
                update_pc=update_pc_name,
                update_target=update_target_name,
                update_taken=update_taken_name
            )
        self.module_instantiations.append(instantiation)

    def _process_renamer_node(self, node, generator, renamer_name: str):
        """
        Process a renamer node - declare all renaming signals and generate instantiation.

        Decode-stage allocation design:
        - Read ports: read_arch_N, read_valid_N (inputs at Decode), read_phys_N (outputs)
        - Write ports: write_arch_N, write_valid_N (inputs at Decode), write_phys_N, write_old_phys_N (outputs)
        - Commit ports: commit_arch_N, commit_phys_N, commit_valid_N (inputs at Writeback)
        - Free port: free_phys, free_valid (inputs at Writeback)
        - Control: stall (Decode stall), flush (control_hazard_flush)
        - Status: free_list_empty, free_count (outputs)

        Pipeline registers are generated for write_phys (uarch_rd) and write_old_phys
        from Decode through to Writeback, where they are used for RF write and freeing.
        """
        num_read_ports = node.data.get('num_reads', 2)
        num_write_ports = node.data.get('num_writes', 1)
        num_phys_regs = node.data.get('num_physical_regs', 64)
        import math
        phys_reg_width = math.ceil(math.log2(num_phys_regs)) if num_phys_regs > 1 else 1
        arch_reg_width = 5  # RISC-V uses 5 bits for 32 architectural registers

        # Track generated signal names for instantiation
        read_archs = []
        read_valids = []
        read_phys = []
        write_archs = []
        write_valids = []
        write_phys = []
        write_old_phys = []
        commit_archs = []
        commit_phys_names = []
        commit_valids = []

        # Declare read port signals
        for i in range(num_read_ports):
            read_arch_name = f"{renamer_name}_read_arch_{i}"
            if read_arch_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': read_arch_name,
                    'bit_width': arch_reg_width
                })
                self.declared_names.add(read_arch_name)
            read_archs.append(read_arch_name)

            read_valid_name = f"{renamer_name}_read_valid_{i}"
            if read_valid_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': read_valid_name,
                    'bit_width': 1
                })
                self.declared_names.add(read_valid_name)
            read_valids.append(read_valid_name)

            read_phys_name = f"{renamer_name}_read_phys_{i}"
            if read_phys_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': read_phys_name,
                    'bit_width': phys_reg_width
                })
                self.declared_names.add(read_phys_name)
            read_phys.append(read_phys_name)

        # Declare write port signals (Decode-stage allocation)
        for i in range(num_write_ports):
            write_arch_name = f"{renamer_name}_write_arch_{i}"
            if write_arch_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': write_arch_name,
                    'bit_width': arch_reg_width
                })
                self.declared_names.add(write_arch_name)
            write_archs.append(write_arch_name)

            write_valid_name = f"{renamer_name}_write_valid_{i}"
            if write_valid_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': write_valid_name,
                    'bit_width': 1
                })
                self.declared_names.add(write_valid_name)
            write_valids.append(write_valid_name)

            write_phys_name = f"{renamer_name}_write_phys_{i}"
            if write_phys_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': write_phys_name,
                    'bit_width': phys_reg_width
                })
                self.declared_names.add(write_phys_name)
            write_phys.append(write_phys_name)

            write_old_phys_name = f"{renamer_name}_write_old_phys_{i}"
            if write_old_phys_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': write_old_phys_name,
                    'bit_width': phys_reg_width
                })
                self.declared_names.add(write_old_phys_name)
            write_old_phys.append(write_old_phys_name)

        # Declare commit port signals (Writeback-stage)
        for i in range(num_write_ports):
            commit_arch_name = f"{renamer_name}_commit_arch_{i}"
            if commit_arch_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': commit_arch_name,
                    'bit_width': arch_reg_width
                })
                self.declared_names.add(commit_arch_name)
            commit_archs.append(commit_arch_name)

            commit_phys_name = f"{renamer_name}_commit_phys_{i}"
            if commit_phys_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': commit_phys_name,
                    'bit_width': phys_reg_width
                })
                self.declared_names.add(commit_phys_name)
            commit_phys_names.append(commit_phys_name)

            commit_valid_name = f"{renamer_name}_commit_valid_{i}"
            if commit_valid_name not in self.declared_names:
                self.wire_declarations.append({
                    'name': commit_valid_name,
                    'bit_width': 1
                })
                self.declared_names.add(commit_valid_name)
            commit_valids.append(commit_valid_name)

        # Declare free port signals
        free_phys_name = f"{renamer_name}_free_phys"
        if free_phys_name not in self.declared_names:
            self.wire_declarations.append({
                'name': free_phys_name,
                'bit_width': phys_reg_width
            })
            self.declared_names.add(free_phys_name)

        free_valid_name = f"{renamer_name}_free_valid"
        if free_valid_name not in self.declared_names:
            self.wire_declarations.append({
                'name': free_valid_name,
                'bit_width': 1
            })
            self.declared_names.add(free_valid_name)

        # Declare status signals
        free_list_empty_name = f"{renamer_name}_free_list_empty"
        if free_list_empty_name not in self.declared_names:
            self.wire_declarations.append({
                'name': free_list_empty_name,
                'bit_width': 1
            })
            self.declared_names.add(free_list_empty_name)

        free_count_name = f"{renamer_name}_free_count"
        if free_count_name not in self.declared_names:
            self.wire_declarations.append({
                'name': free_count_name,
                'bit_width': phys_reg_width + 1
            })
            self.declared_names.add(free_count_name)

        # Determine pipeline depth by counting how many stages rd is piped through.
        # This tells us how many pipeline registers to generate for write_phys/write_old_phys.
        pipe_depth = self._get_renamer_pipe_depth(node)

        # Declare pipeline registers for write_phys and write_old_phys
        # These pipe the Decode-stage allocation outputs through to Writeback
        piped_write_phys = []
        piped_old_phys = []
        piped_write_valid = []  # pipe write_valid (Decode validity) for commit_valid at WB
        for i in range(num_write_ports):
            wp_chain = [write_phys[i]]
            op_chain = [write_old_phys[i]]
            wv_chain = [write_valids[i]]
            stage_names = ['Execute', 'Memory', 'Writeback', 'WB2']  # generic names
            for d in range(pipe_depth):
                stage = stage_names[d] if d < len(stage_names) else f"S{d}"
                # Pipeline register for write_phys (uarch_rd)
                wp_pipe = f"{renamer_name}_write_phys_{i}_pipe_{stage}"
                if wp_pipe not in self.declared_names:
                    self.reg_declarations.append({
                        'name': wp_pipe,
                        'bit_width': phys_reg_width,
                        'reset_wire': f"{phys_reg_width}'d0"
                    })
                    self.declared_names.add(wp_pipe)
                wp_chain.append(wp_pipe)

                # Pipeline register for write_old_phys (old_phys)
                op_pipe = f"{renamer_name}_write_old_phys_{i}_pipe_{stage}"
                if op_pipe not in self.declared_names:
                    self.reg_declarations.append({
                        'name': op_pipe,
                        'bit_width': phys_reg_width,
                        'reset_wire': f"{phys_reg_width}'d0"
                    })
                    self.declared_names.add(op_pipe)
                op_chain.append(op_pipe)

                # Pipeline register for write_valid (allocation valid at Decode → commit valid at WB)
                wv_pipe = f"{renamer_name}_write_valid_{i}_pipe_{stage}"
                if wv_pipe not in self.declared_names:
                    self.reg_declarations.append({
                        'name': wv_pipe,
                        'bit_width': 1,
                        'reset_wire': "1'b0"
                    })
                    self.declared_names.add(wv_pipe)
                wv_chain.append(wv_pipe)

            piped_write_phys.append(wp_chain)
            piped_old_phys.append(op_chain)
            piped_write_valid.append(wv_chain)

        # Store pipeline register info for deferred sequential logic generation
        # (seq_logic is not available during _analyze_graph; it's created in _generate_sequential_logic)
        if not hasattr(self, '_renamer_pipe_regs'):
            self._renamer_pipe_regs = []
        if pipe_depth > 0:
            self._renamer_pipe_regs.append({
                'num_write_ports': num_write_ports,
                'pipe_depth': pipe_depth,
                'phys_reg_width': phys_reg_width,
                'piped_write_phys': piped_write_phys,
                'piped_old_phys': piped_old_phys,
                'piped_write_valid': piped_write_valid,
            })

        # The deepest piped versions are used for commit and free at Writeback
        wb_write_phys = [chain[-1] for chain in piped_write_phys]
        wb_old_phys = [chain[-1] for chain in piped_old_phys]
        wb_write_valid = [chain[-1] for chain in piped_write_valid]

        # Find stall and flush signals for renamer instantiation
        stall_signal = self._find_decode_stall_signal() or "1'b0"
        flush_signal = self._find_flush_signal() or "1'b0"

        # Generate renamer module instantiation with commit ports
        instantiation = generator.get_port_connections(
            read_archs=read_archs,
            read_valids=read_valids,
            read_phys=read_phys,
            write_archs=write_archs,
            write_valids=write_valids,
            write_phys=write_phys,
            write_old_phys=write_old_phys,
            commit_archs=commit_archs,
            commit_phys=commit_phys_names,
            commit_valids=commit_valids,
            free_phys=free_phys_name,
            free_valid=free_valid_name,
            stall=stall_signal,
            flush=flush_signal
        )
        self.module_instantiations.append(instantiation)

        # Process edges to/from the renamer to generate assign statements
        self._connect_renamer_signals(node, renamer_name,
                                       read_archs, read_valids, read_phys,
                                       write_archs, write_valids, write_phys,
                                       write_old_phys,
                                       commit_archs, commit_phys_names, commit_valids,
                                       free_phys_name, free_valid_name,
                                       wb_write_phys, wb_old_phys, wb_write_valid,
                                       pipe_depth)

        # Store renamer metadata for RF write override
        self._renamer_wb_write_phys = wb_write_phys

    def _get_renamer_pipe_depth(self, renamer_node) -> int:
        """Determine the pipeline depth between Decode and Writeback by counting
        how deep the rd signal is piped through pipeline registers.

        Returns the number of pipeline stages that write_phys/write_old_phys
        need to be piped through (e.g. 3 for a 5-stage pipeline: Exec, Mem, WB).
        """
        # First, identify which rename_input edge corresponds to the write (rd) port
        # by matching input edges to write-role output edges
        write_input_edge = None
        for in_edge in renamer_node.incoming_edges:
            if in_edge.data.get('type') != 'rename_input':
                continue
            source_name = in_edge.source.data.get('name', in_edge.source.id)
            arch_idx = in_edge.data.get('architectural_index')
            # Check if this input matches a write-role output
            for out_edge in renamer_node.outgoing_edges:
                if out_edge.data.get('type') != 'rename_output':
                    continue
                uarch_node = out_edge.target
                if uarch_node.data.get('rename_role') != 'write':
                    continue
                # Match by architectural_index or name pattern
                out_arch_idx = out_edge.data.get('architectural_index')
                uarch_name = uarch_node.data.get('name', uarch_node.id)
                if (arch_idx and out_arch_idx == arch_idx) or \
                   (uarch_name.startswith('uarch_') and source_name == uarch_name[len('uarch_'):]):
                    write_input_edge = in_edge
                    break
            if write_input_edge:
                break

        if write_input_edge:
            source_base = write_input_edge.source.data.get('name', write_input_edge.source.id)
            # Count the deepest piped version of source_base.
            # Match pipeline registers where source_base appears as a delimited segment
            # (not just a substring), e.g., '_rd_' or ending with '_rd_PIPE...'
            deepest_depth = 0
            for nid, node in self.graph.nodes.items():
                if node.data.get('type') != 'pipeline_register':
                    continue
                # Check that source_base appears as a word boundary in the node ID
                # to avoid matching 'rd' inside 'pc_rd' or 'rf_rs1_rd'
                import re
                if re.search(r'(?:^|_)' + re.escape(source_base) + r'(?:_|$)', nid):
                    depth = 0
                    parts = nid.split('_')
                    for p in reversed(parts):
                        if p == 'PIPE':
                            depth += 1
                        else:
                            break
                    if depth > deepest_depth:
                        deepest_depth = depth
            return deepest_depth

        # Fallback: count total pipeline stages from graph
        max_pipe_time = 0
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'pipeline_register':
                pt = node.data.get('pipe_time', 0)
                if pt > max_pipe_time:
                    max_pipe_time = pt
        # Subtract 1 for Fetch stage (rd enters at Decode, not Fetch)
        return max(0, max_pipe_time - 1)

    def _find_decode_stall_signal(self) -> str:
        """Find the Decode-stage stall signal name."""
        # Look for the stall controller node
        for nid, node in self.graph.nodes.items():
            if node.data.get('type') == 'pipeline_stall_controller':
                name = self.node_id_to_name.get(nid, self._sanitize_identifier(nid))
                return name
        # Fallback: check for common name
        if 'PIPE_Decode_stall_ctrl' in self.declared_names:
            return 'PIPE_Decode_stall_ctrl'
        return None

    def _find_flush_signal(self) -> str:
        """Find the control hazard flush signal name."""
        for nid, node in self.graph.nodes.items():
            if 'control_hazard_flush' in nid and node.data.get('type') != 'pipeline_register':
                name = self.node_id_to_name.get(nid, self._sanitize_identifier(nid))
                return name
        if 'control_hazard_flush' in self.declared_names:
            return 'control_hazard_flush'
        return None

    def _connect_renamer_signals(self, renamer_node, renamer_name: str,
                                  read_archs: list, read_valids: list, read_phys: list,
                                  write_archs: list, write_valids: list, write_phys: list,
                                  write_old_phys: list,
                                  commit_archs: list, commit_phys_names: list, commit_valids: list,
                                  free_phys_name: str, free_valid_name: str,
                                  wb_write_phys: list, wb_old_phys: list, wb_write_valid: list,
                                  pipe_depth: int):
        """
        Generate assign statements connecting renamer I/O.

        Decode-stage allocation design:
        - write_arch/write_valid connect to Decode-stage rd (NOT piped)
        - write_phys (uarch_rd) and write_old_phys are piped through to Writeback
        - commit ports connect to piped Writeback-stage signals
        - free ports connect to piped old_phys at Writeback

        Classification uses the rename_output target structure (which survives
        pipelining) rather than edge metadata which may be lost.
        """
        # Collect rename_input edges
        rename_input_edges = []
        for edge in renamer_node.incoming_edges:
            if edge.data.get('type') == 'rename_input':
                rename_input_edges.append(edge)

        # Collect rename_output edges and classify read vs write
        rename_output_edges = []
        uarch_is_write = {}  # uarch_node.id -> bool
        for edge in renamer_node.outgoing_edges:
            if edge.data.get('type') == 'rename_output':
                rename_output_edges.append(edge)
                uarch_node = edge.target
                is_write = uarch_node.data.get('rename_role') == 'write'
                if not is_write:
                    for target_edge in uarch_node.outgoing_edges:
                        if target_edge.data.get('type') == 'write_address':
                            target_node = target_edge.target
                            if target_node.data.get('type') == 'memory_write_port':
                                is_write = True
                                break
                uarch_is_write[uarch_node.id] = is_write

        # Match rename_input edges to rename_output edges
        read_inputs = []
        write_inputs = []
        input_to_uarch = {}

        for in_edge in rename_input_edges:
            source_id = in_edge.source.id
            source_name = in_edge.source.data.get('name', source_id)
            arch_idx = in_edge.data.get('architectural_index')
            matched_uarch = None

            for out_edge in rename_output_edges:
                out_arch_idx = out_edge.data.get('architectural_index')
                uarch_node = out_edge.target
                if arch_idx and out_arch_idx == arch_idx:
                    matched_uarch = uarch_node
                    break
                uarch_name = uarch_node.data.get('name', uarch_node.id)
                if uarch_name.startswith('uarch_'):
                    base = uarch_name[len('uarch_'):]
                    if source_name == base or source_id == base or source_id.endswith(f'_{base}_PIPE') or source_id.endswith(f'_PIPE_{base}_PIPE'):
                        matched_uarch = uarch_node
                        break

            if matched_uarch:
                input_to_uarch[source_id] = matched_uarch
                if uarch_is_write.get(matched_uarch.id, False):
                    write_inputs.append(in_edge)
                else:
                    read_inputs.append(in_edge)
            else:
                read_inputs.append(in_edge)

        # Connect read ports (unchanged - Decode-stage rs1/rs2 lookups)
        for i, edge in enumerate(read_inputs):
            if i >= len(read_archs):
                break
            source_name = self.node_id_to_name.get(edge.source.id)
            if not source_name:
                source_name = self._sanitize_identifier(edge.source.data.get('name', edge.source.id))

            assign_stmt = f"assign {read_archs[i]} = {source_name};"
            if assign_stmt not in self.renamer_assigns:
                self.renamer_assigns.append(assign_stmt)

            enable_stmt = f"assign {read_valids[i]} = 1'b1;"
            if enable_stmt not in self.renamer_assigns:
                self.renamer_assigns.append(enable_stmt)

        # Connect write ports - use Decode-stage rd (NOT the deepest piped version)
        for i, edge in enumerate(write_inputs):
            if i >= len(write_archs):
                break
            source_name = self.node_id_to_name.get(edge.source.id)
            if not source_name:
                source_name = self._sanitize_identifier(edge.source.data.get('name', edge.source.id))

            # write_arch connects to Decode-stage rd directly (NOT piped to Writeback)
            assign_stmt = f"assign {write_archs[i]} = {source_name};"
            if assign_stmt not in self.renamer_assigns:
                self.renamer_assigns.append(assign_stmt)

            # write_valid at Decode: rd != 0 AND instruction has a write destination
            # AND the Decode stage is valid (not a bubble from a flush).
            # Without the valid gating, a wrong-path instruction that enters Decode
            # after a flush would speculatively allocate and corrupt the RAT.
            decode_write_valid = self._find_decode_write_valid(source_name)
            decode_valid = self._find_decode_valid_signal()
            if decode_valid:
                enable_stmt = f"assign {write_valids[i]} = {decode_write_valid} && {decode_valid};"
            else:
                enable_stmt = f"assign {write_valids[i]} = {decode_write_valid};"
            if enable_stmt not in self.renamer_assigns:
                self.renamer_assigns.append(enable_stmt)

        # Connect commit ports (Writeback-stage piped signals)
        for i, edge in enumerate(write_inputs):
            if i >= len(commit_archs):
                break
            # commit_arch = piped rd at Writeback (deepest piped version)
            source_base = edge.source.data.get('name', edge.source.id)
            deepest_name = self.node_id_to_name.get(edge.source.id) or self._sanitize_identifier(source_base)
            deepest_depth = 0
            for nid, node in self.graph.nodes.items():
                if (node.data.get('type') == 'pipeline_register' and
                    source_base in nid):
                    depth = 0
                    parts = nid.split('_')
                    for p in reversed(parts):
                        if p == 'PIPE':
                            depth += 1
                        else:
                            break
                    if depth > deepest_depth:
                        deepest_depth = depth
                        candidate = self.node_id_to_name.get(nid, self._sanitize_identifier(nid))
                        deepest_name = candidate

            assign_stmt = f"assign {commit_archs[i]} = {deepest_name};"
            if assign_stmt not in self.renamer_assigns:
                self.renamer_assigns.append(assign_stmt)

            # commit_phys = piped write_phys at Writeback
            assign_stmt = f"assign {commit_phys_names[i]} = {wb_write_phys[i]};"
            if assign_stmt not in self.renamer_assigns:
                self.renamer_assigns.append(assign_stmt)

            # commit_valid = Writeback-stage write enable (the existing WB write enable)
            # This is the piped write_valid that reached Writeback AND the WB write enable
            write_enable_name = self._find_wb_write_enable(input_to_uarch.get(edge.source.id))
            if write_enable_name:
                assign_stmt = f"assign {commit_valids[i]} = {write_enable_name};"
            else:
                # Fall back to the piped write_valid
                assign_stmt = f"assign {commit_valids[i]} = {wb_write_valid[i]};"
            if assign_stmt not in self.renamer_assigns:
                self.renamer_assigns.append(assign_stmt)

        # Connect rename_output phys ports to uarch_index nodes
        read_uarch_idx = 0
        write_uarch_idx = 0
        for edge in rename_output_edges:
            uarch_node = edge.target
            target_name = self.node_id_to_name.get(uarch_node.id)
            if not target_name:
                target_name = self._sanitize_identifier(uarch_node.data.get('name', uarch_node.id))

            if uarch_is_write.get(uarch_node.id, False):
                if write_uarch_idx < len(write_phys):
                    assign_stmt = f"assign {target_name} = {write_phys[write_uarch_idx]};"
                    if assign_stmt not in self.renamer_assigns:
                        self.renamer_assigns.append(assign_stmt)
                write_uarch_idx += 1
            else:
                if read_uarch_idx < len(read_phys):
                    assign_stmt = f"assign {target_name} = {read_phys[read_uarch_idx]};"
                    if assign_stmt not in self.renamer_assigns:
                        self.renamer_assigns.append(assign_stmt)
                read_uarch_idx += 1

        # Free port: connect piped old_phys and commit_valid at Writeback
        if wb_old_phys and wb_write_valid:
            free_stmt = f"assign {free_phys_name} = {wb_old_phys[0]};"
            if free_stmt not in self.renamer_assigns:
                self.renamer_assigns.append(free_stmt)
            free_en_stmt = f"assign {free_valid_name} = {commit_valids[0]};"
            if free_en_stmt not in self.renamer_assigns:
                self.renamer_assigns.append(free_en_stmt)
        else:
            free_stmt = f"assign {free_valid_name} = 1'b0;"
            if free_stmt not in self.renamer_assigns:
                self.renamer_assigns.append(free_stmt)

    def _find_decode_write_valid(self, rd_signal_name: str) -> str:
        """Find the Decode-stage validity signal for write allocation.

        For RISC-V, this is typically rf_rd_ne_0_guarded_enable which is
        (any_rd_writing_enable && rd != 0). Fall back to (rd != 0) if not found.
        """
        # Look for rf_rd_ne_0_guarded_enable node (common in merged RISC-V graphs)
        for nid, node in self.graph.nodes.items():
            if 'rf_rd_ne_0_guarded_enable' in nid:
                name = self.node_id_to_name.get(nid, self._sanitize_identifier(nid))
                return name

        # Fall back: look for (rd != 0) style node
        for nid, node in self.graph.nodes.items():
            if nid == '(rd != 0)' or nid == 'rf_rd_ne_0':
                name = self.node_id_to_name.get(nid, self._sanitize_identifier(nid))
                return name

        # Last resort: generate (rd != 0) inline
        return f"({rd_signal_name} != 0)"

    def _find_decode_valid_signal(self) -> str:
        """Find the Decode-stage valid pipeline register.

        After a flush, this is 0 for one cycle, preventing the wrong-path
        instruction that enters Decode from allocating in the renamer.
        """
        # Look for PIPE_Decode_valid_PIPE in the graph
        for nid, node in self.graph.nodes.items():
            if node.data.get('type') == 'pipeline_register':
                name = self.node_id_to_name.get(nid, self._sanitize_identifier(nid))
                if name == 'PIPE_Decode_valid_PIPE':
                    return name
        # Fall back to searching declared reg names
        for reg in self.reg_declarations:
            if reg['name'] == 'PIPE_Decode_valid_PIPE':
                return 'PIPE_Decode_valid_PIPE'
        # Search wire declarations too
        for wire in self.wire_declarations:
            if wire['name'] == 'PIPE_Decode_valid_PIPE':
                return 'PIPE_Decode_valid_PIPE'
        return None

    def _find_wb_write_enable(self, uarch_node) -> str:
        """Find the Writeback-stage write enable signal for the commit port."""
        if not uarch_node:
            return None

        # First try: look for write_address edge from uarch_node
        for ue in uarch_node.outgoing_edges:
            if ue.data.get('type') == 'write_address':
                write_port = ue.target
                we_name = write_port.data.get('combined_write_enable')
                if we_name:
                    return self._sanitize_identifier(we_name)
                break

        # Second try: find memory_write_port with renamed_write_index matching this uarch node
        for node in self.graph.nodes.values():
            if (node.data.get('type') == 'memory_write_port' and
                node.data.get('renamed_write_index') == uarch_node.id):
                we_name = node.data.get('combined_write_enable')
                if we_name:
                    return self._sanitize_identifier(we_name)
                break

        return None

    def _generate_MUX_module(self, name, num_inputs, data_width: int = 32) -> str:
        """Generate MUX module based on number of inputs."""
        # Calculate select width
        select_width = (num_inputs - 1).bit_length()

        # Start module definition
        verilog = f"module {name}(\n"

        # Generate input ports for each data input
        for i in range(num_inputs):
            verilog += f"    input wire [{data_width-1}:0] in_{i},\n"

        # Select signal
        verilog += f"    input wire [{select_width-1}:0] sel,\n"

        # Output port
        verilog += f"    output logic [{data_width-1}:0] out\n"
        verilog += ");\n\n"

        # Generate case statement for mux selection
        verilog += "    always_comb begin\n"
        verilog += "        case (sel)\n"

        # Add cases for each input
        for i in range(num_inputs):
            verilog += f"            {select_width}'d{i}: out = in_{i};\n"

        # Default case
        verilog += f"            default: out = {data_width}'d0;\n"
        verilog += "        endcase\n"
        verilog += "    end\n\n"

        verilog += "endmodule\n"

        return verilog

    def _operator_to_verilog(self, operator: str) -> str:
        """Convert operator string to Verilog operator."""
        operator_map = {
            '+': '+',
            '-': '-',
            '|': '|',
            '&': '&',
            '^': '^',
            '<<': '<<',
            '>>': '>>',
            '>>>': '>>>',
            '*': '*',
            '/': '/',
            '%': '%',
            '==': '==',
            '!=': '!=',
            '<': '<',
            '>': '>',
            '<=': '<=',
            '>=': '>=',
            '<s': '<',
            '>s': '>',
            '<=s': '<=',
            '>=s': '>='
        }
        return operator_map.get(operator, operator)

    def _get_zero_extended_expr(self, index_name: str, target_bits: int = 32) -> str:
        """Return a Verilog expression that zero-extends index_name to target_bits if narrower."""
        idx_width = None
        for nid, vname in self.node_id_to_name.items():
            if vname == index_name:
                src = self.graph.nodes.get(nid)
                if src is not None:
                    idx_width = self._infer_bit_width(src)
                break
        if not idx_width:
            idx_width = target_bits
        if idx_width < target_bits:
            pad = target_bits - idx_width
            return f"{{{pad}'b0, {index_name}}}"
        return index_name

    def _infer_bit_width(self, node: Node, _depth: int = 0, _visited: set = None) -> int:
        """Infer bit width for a node based on context (with memoization)."""
        # Check memoization cache first
        if node.id in self._bit_width_cache:
            return self._bit_width_cache[node.id]

        # Cycle detection - avoid infinite recursion when graph has cycles
        if _visited is None:
            _visited = set()
        if node.id in _visited:
            # Cycle detected - return default width (don't cache cycle results)
            return 32
        _visited = _visited | {node.id}  # Create new set to avoid mutation across branches

        # Compute the result
        result = self._infer_bit_width_impl(node, _depth, _visited)

        # Cache the result
        self._bit_width_cache[node.id] = result

        return result

    def _infer_bit_width_impl(self, node: Node, _depth: int, _visited: set) -> int:
        """Implementation of bit width inference logic."""
        # Instruction buffer fetch nodes need their explicit bit_width (fetch_width),
        # not the memory element width, since they read multiple bytes at once
        if node.data.get('type') == 'array_access' and node.data.get('is_buffer_fetch', False):
            if 'bit_width' in node.data and node.data['bit_width'] is not None:
                return node.data['bit_width']

        # For array_access and concatenation nodes, DON'T use explicit bit_width -
        # array_access needs special narrow load handling, concatenation should always
        # compute width from the sum of its input widths
        if node.data.get('type') not in ('array_access', 'concatenation'):
            # Check port_width first (for memories with different access width than element width)
            if 'port_width' in node.data and node.data['port_width'] is not None:
                return node.data['port_width']
            # Check if bit_width is explicitly set in node data first
            if 'bit_width' in node.data and node.data['bit_width'] is not None:
                return node.data['bit_width']

        # Check if this node produces a boolean (1-bit) result
        if self._produces_boolean_result(node):
            return 1

        # For literal nodes, check if width is explicitly specified
        if node.data.get('type') == 'literal' and 'width' in node.data:
            return node.data['width']

        # For bit_slice nodes, calculate width from the range
        if node.data.get('type') == 'bit_slice':
            # Check ILA format first (high_bit, low_bit)
            if 'high_bit' in node.data and 'low_bit' in node.data:
                high = node.data['high_bit']
                low = node.data['low_bit']
                return (high - low + 1)
            # Check for high/low directly in node.data
            elif 'high' in node.data and 'low' in node.data:
                high = node.data['high']
                low = node.data['low']
                return (high - low + 1)
            # Check for bitslice field
            elif 'bitslice' in node.data:
                high, low = node.data['bitslice']
                return (high - low + 1)
            # Check ISA format (expression with range)
            expr = node.data.get('expression', {})
            if expr.get('type') == 'bit_slice' and 'range' in expr:
                high, low = expr['range']
                return (high - low + 1)

        # For sized_literal nodes, use the width field
        if node.data.get('type') == 'sized_literal':
            expr = node.data.get('expression', {})
            if expr.get('type') == 'sized_literal':
                return expr.get('width', 1)
            # Also check node data directly
            return node.data.get('width', 1)

        # For decimal_literal and verilog hex/dec literal nodes, use the width field
        if node.data.get('type') in ['decimal_literal', 'verilog_hex_literal', 'verilog_dec_literal']:
            return node.data.get('width', 32)


        # For repetition nodes, width = count * width of inner expression
        if node.data.get('type') == 'repetition':
            expr = node.data.get('expression', {})
            if expr.get('type') == 'repetition':
                count = expr.get('count', 1)
                # The inner expression is typically 1 bit (like imm[11])
                # but we should try to infer it properly
                if node.incoming_edges:
                    source_edge = sorted(node.incoming_edges, key=lambda e: e.source.id)[0]
                    inner_width = self._infer_bit_width(source_edge.source, _depth + 1, _visited)
                    return count * inner_width
                # Fallback: assume inner is 1 bit
                return count

        # For concatenation nodes, width = sum of all input widths
        if node.data.get('type') == 'concatenation':
            if node.incoming_edges:
                total_width = 0
                for edge in node.incoming_edges:
                    source_width = self._infer_bit_width(edge.source, _depth + 1, _visited)
                    total_width += source_width
                return total_width
            # Fallback: try to calculate from expression data
            expr = node.data.get('expression', {})
            if expr.get('type') == 'concatenation':
                parts = expr.get('parts', [])
                total_width = 0
                for sub_expr in parts:
                    # Estimate width from sub-expression
                    if sub_expr.get('type') == 'identifier':
                        # Look up the identifier in the graph to get its actual width
                        identifier_name = sub_expr.get('name')
                        if identifier_name and identifier_name in self.graph.nodes:
                            id_node = self.graph.nodes[identifier_name]
                            id_width = self._infer_bit_width(id_node, _depth + 1, _visited)
                            total_width += id_width if id_width else 32
                        else:
                            total_width += 32
                    elif sub_expr.get('type') == 'literal':
                        total_width += 32
                    elif sub_expr.get('type') == 'sized_literal':
                        total_width += sub_expr.get('width', 1)
                    elif sub_expr.get('type') == 'bit_slice':
                        if 'range' in sub_expr:
                            high, low = sub_expr['range']
                            total_width += (high - low + 1)
                        else:
                            total_width += 32
                    elif sub_expr.get('type') == 'repetition':
                        count = sub_expr.get('count', 1)
                        total_width += count  # Assume inner is 1 bit
                    else:
                        total_width += 32
                return total_width

        # For multiplexer nodes, infer width from mux inputs (max of all non-32 widths)
        # Start with None so we can detect if we found any actual widths
        if node.data.get('type') == 'multiplexer':
            found_widths = []
            for edge in node.incoming_edges:
                if edge.data.get('type') in ['mux_input', 'mux_default_input']:
                    src_width = self._infer_bit_width(edge.source, _depth + 1, _visited)
                    if src_width is not None:
                        found_widths.append(src_width)
            if found_widths:
                # Return max of actual widths found (not just defaulting to 32)
                return max(found_widths)
            # Also try to infer from outgoing edges (what uses this mux output)
            for edge in node.outgoing_edges:
                target = edge.target
                # Check for _wr nodes which should have width from their base register
                if target.id.endswith('_wr'):
                    base_name = target.id[:-3]  # Remove '_wr' suffix
                    base_node = self.graph.nodes.get(base_name)
                    if base_node and base_node.data.get('bit_width'):
                        return base_node.data['bit_width']
                target_width = target.data.get('bit_width')
                if target_width and target_width != 32:
                    return target_width
            return 32  # Default if nothing else found

        # For ternary/ternary_op nodes, infer width from true/false operands (max of both)
        if node.data.get('type') == 'ternary_op':
            true_width = None
            false_width = None
            for edge in node.incoming_edges:
                edge_type = edge.data.get('type')
                if edge_type == 'ternary_true':
                    true_width = self._infer_bit_width(edge.source, _depth + 1, _visited)
                elif edge_type == 'ternary_false':
                    false_width = self._infer_bit_width(edge.source, _depth + 1, _visited)
            # Return max of operand widths (take maximum of all non-None widths)
            widths = [w for w in [true_width, false_width] if w is not None]
            if widths:
                return max(widths)
            # If edge tracing failed, try to infer from ALL incoming edges (excluding condition)
            # This handles cases where edges aren't labeled as ternary_true/ternary_false
            if true_width is None and false_width is None:
                all_widths = []
                for edge in node.incoming_edges:
                    edge_type = edge.data.get('type')
                    # Skip condition edges (they're 1-bit boolean)
                    if edge_type == 'ternary_condition':
                        continue
                    # Skip operand edges that are likely condition
                    if self._produces_boolean_result(edge.source):
                        continue
                    src_width = self._infer_bit_width(edge.source, _depth + 1, _visited)
                    if src_width is not None and src_width > 1:
                        all_widths.append(src_width)
                if all_widths:
                    return max(all_widths)
            # If both are None, check if either has explicit 64-bit connection
            if true_width is None and false_width is None:
                # Check outgoing edges for targets that expect 64-bit
                for edge in node.outgoing_edges:
                    target_width = edge.target.data.get('bit_width')
                    if target_width is not None and target_width > 32:
                        return target_width

        # For pipeline_register nodes, trace back through incoming edges to find source width
        if node.data.get('type') == 'pipeline_register':
            for edge in node.incoming_edges:
                # Skip control edges (stall, valid_gate) - these are 1-bit signals
                if edge.data.get('type') in ['stall', 'valid_gate']:
                    continue
                source_width = self._infer_bit_width(edge.source, _depth + 1, _visited)
                if source_width is not None:
                    return source_width

        # For var nodes without explicit width, trace back through incoming edges
        # to find the source width (e.g., r1 = rf[rs1] should get rf's element width)
        if node.data.get('type') == 'var' and not node.data.get('width_explicit'):
            for edge in node.incoming_edges:
                # Skip validity_check edges - these are 1-bit control signals, not data
                edge_type = edge.data.get('type')
                if edge_type == 'validity_check':
                    continue
                source = edge.source
                # If source is pipeline_register, trace through it
                if source.data.get('type') == 'pipeline_register':
                    source_width = self._infer_bit_width(source, _depth + 1, _visited)
                    if source_width is not None:
                        return source_width
                # If source is array_access, get the memory element width
                if source.data.get('type') == 'array_access':
                    for src_edge in source.incoming_edges:
                        if src_edge.data.get('type') == 'array_base':
                            mem_source = src_edge.source
                            mem_width = mem_source.data.get('bit_width')
                            if mem_width is not None:
                                return mem_width
                # Recursively infer from source
                source_width = self._infer_bit_width(source, _depth + 1, _visited)
                if source_width is not None and source_width != 32:
                    return source_width

        # For array_access nodes accessing memory, return the MEMORY width (not consumer width)
        # This is needed for narrow load detection: we need to know the access is narrower than memory
        if node.data.get('type') == 'array_access':
            # Check if accessing a memory - look for incoming edge from memory node
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'array_base':
                    # Check the source (memory/array) for bit_width
                    source_width = edge.source.data.get('bit_width')
                    if source_width is not None:
                        return source_width
                    # Also check memory_declarations if available
                    if edge.source.data.get('is_memory'):
                        memory_name = edge.source.data.get('name', edge.source.id)
                        if memory_name in self.memory_declarations:
                            mem_width = self.memory_declarations[memory_name].get('bit_width')
                            if mem_width is not None:
                                return mem_width

            # Non-memory array access: use consumer width
            for edge in node.outgoing_edges:
                target_width = edge.target.data.get('bit_width')
                if target_width is not None:
                    return target_width

        # For _rd nodes that are memory reads (e.g., mainmem[pc]_rd), use memory element width
        # These are split nodes created by architectural state splitting from array_access nodes
        if node.id.endswith('_rd') and '[' in node.id:
            # Extract memory name from pattern like "mainmem[pc]_rd"
            import re
            match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)\[', node.id)
            if match:
                memory_name = match.group(1)
                # Check memory node in graph first (more reliable since memory_declarations
                # may not be populated yet due to alphabetical processing order)
                mem_node = self.graph.nodes.get(memory_name)
                if mem_node and mem_node.data.get('is_memory'):
                    mem_width = mem_node.data.get('bit_width')
                    if mem_width is not None:
                        return mem_width
                # Fallback to memory_declarations if available
                if memory_name in self.memory_declarations:
                    mem_width = self.memory_declarations[memory_name].get('bit_width')
                    if mem_width is not None:
                        return mem_width

        # For binary operations (like shifts, arithmetic), infer from operands
        # Shift operations: result width = left operand width
        # Arithmetic operations: result width = max(left, right) operand width
        if node.data.get('type') == 'operation':
            operator = node.data.get('operator')
            expr = node.data.get('expression', {})
            if expr.get('type') == 'binary_op':
                operator = expr.get('operator', operator)

            # Find left and right operands from edges
            left_width = None
            right_width = None
            for edge in node.incoming_edges:
                pos = edge.data.get('position')
                if pos == 'left' or pos == 0:
                    left_width = self._infer_bit_width(edge.source, _depth + 1, _visited)
                elif pos == 'right' or pos == 1:
                    right_width = self._infer_bit_width(edge.source, _depth + 1, _visited)

            # For shift operations, result width equals left operand width
            if operator in ['<<', '>>', '>>>', 'sll', 'srl', 'sra']:
                if left_width is not None:
                    return left_width
            # For arithmetic operations, use max of operand widths
            # For addition, add 1 bit to handle carry overflow
            elif operator in ['+', '-', '*', '/', '&', '|', '^']:
                operand_widths = [w for w in [left_width, right_width] if w is not None and w != 32]
                if operand_widths:
                    max_width = max(operand_widths)
                    # Addition/subtraction can overflow/underflow by 1 bit
                    # (e.g., 4-bit + 4-bit + carry = 5-bit, or borrow propagation)
                    if operator in ('+', '-'):
                        return max_width + 1
                    return max_width

        # Check if connected to ISA state with known width
        for edge in node.incoming_edges | node.outgoing_edges:
            other_node = edge.source if edge.target == node else edge.target
            if other_node.is_arch_state and 'bit_width' in other_node.data:
                return other_node.data['bit_width']

        # Try to infer from incoming edges (assignment or bit_access edges)
        for edge in node.incoming_edges:
            if edge.data.get('type') in ['assignment', 'bit_access']:
                # Recursively infer from source
                source_width = self._infer_bit_width(edge.source, _depth + 1, _visited)
                if source_width != 32:  # Only use if we got a non-default width
                    return source_width

        # For binary operations, also try operand edges
        for edge in node.incoming_edges:
            if edge.data.get('type') == 'operand':
                source_width = self._infer_bit_width(edge.source, _depth + 1, _visited)
                if source_width != 32:
                    return source_width

        # Default width
        return 32

    def _produces_boolean_result(self, node: Node) -> bool:
        """
        Determine if a node produces a boolean (1-bit) result.

        Boolean results come from:
        - Comparison operations (==, !=, <, >, <=, >=)
        - Logical operations (&&, ||, !)
        - Bitwise AND/OR on boolean inputs (for ILA decode chains)
        - Instruction decode signals
        """
        node_type = node.data.get('type')

        # Type-based checks
        if node_type in ['comparison', 'logical_and', 'logical_or', 'logical_not', 'instruction_enable']:
            return True

        # Check for operations with comparison operators
        if node_type == 'operation':
            operator = node.data.get('operator', '')

            # Comparison operators always produce boolean results
            if operator in ['==', '!=', '<', '>', '<=', '>=', '<s', '>s', '<=s', '>=s']:
                return True

            # Logical NOT always produces boolean result
            if operator == '!':
                return True

            # Logical AND/OR always produce boolean results
            if operator in ['&&', '||']:
                return True

            # Bitwise AND/OR on all 1-bit inputs produces 1-bit result
            # This handles ILA decode chains: (opcode==X) & (funct3==Y) & (funct7==Z)
            if operator in ['&', '|']:
                # Check if all inputs are 1-bit
                all_inputs_1bit = True
                for edge in node.incoming_edges:
                    if not self._produces_boolean_result(edge.source):
                        all_inputs_1bit = False
                        break
                if all_inputs_1bit and len(node.incoming_edges) > 0:
                    return True

            # Legacy expression format
            expr = node.data.get('expression', {})
            if expr.get('type') == 'binary_op':
                operator = expr.get('operator', '')
                # Comparison operators always produce boolean results
                if operator in ['==', '!=', '<', '>', '<=', '>=', '<s', '>s', '<=s', '>=s']:
                    return True
                # Logical AND/OR always produce boolean results
                if operator in ['&&', '||']:
                    return True
            elif expr.get('type') == 'unary_op':
                operator = expr.get('operator', '')
                # Logical NOT always produces boolean result
                if operator == '!':
                    return True

        # Also check if node has explicit width=1 in data
        if node.data.get('width') == 1:
            return True

        return False

    def _trace_fp_operand_to_reg(self, node: 'Node') -> Optional[str]:
        """Trace an FP operand node back to its FP register file read.

        When FP operand nodes are merged with instruction-specific prefixes (like fadd_s_f1),
        we need to trace back to the actual FP register file read signal (frf_rs1_rd or frf_rs2_rd).

        Returns the correct register file read signal name, or None if can't trace.
        """
        # Look for assignment edges that connect this node to an frf read
        for edge in node.incoming_edges:
            if edge.data.get('type') == 'assignment':
                source = edge.source
                source_id = source.id

                # Check if this is an FP register file read (frf[rsX]_rd)
                if source_id.startswith('frf[') and source_id.endswith(']_rd'):
                    # Map to the unified frf_rsX_rd signal
                    if 'rs1' in source_id:
                        return 'frf_rs1_rd'
                    elif 'rs2' in source_id:
                        return 'frf_rs2_rd'
                    elif 'rs3' in source_id:
                        return 'frf_rs3_rd'

                # Check if source node has a declared wire we can use
                source_ref = self.node_id_to_name.get(source_id)
                if source_ref:
                    wire_names = {w['name'] for w in self.wire_declarations}
                    reg_names = {r['name'] for r in self.reg_declarations}
                    if source_ref in wire_names or source_ref in reg_names:
                        return source_ref

                # Recurse to trace further back
                traced = self._trace_fp_operand_to_reg(source)
                if traced:
                    return traced

        return None

    def _sanitize_identifier(self, identifier: str) -> str:
        """Convert expression identifiers to valid Verilog identifiers."""
        # Preserve binary wildcard patterns before general sanitization
        # Convert 0b0** to 0b0xx (using 'x' for wildcard bits)
        import re
        sanitized = re.sub(r'0b([01]*)(\*+)', lambda m: f'0b{m.group(1)}{"x" * len(m.group(2))}', identifier)

        # Replace invalid characters
        sanitized = sanitized.replace('.', '_')  # Handle dots (e.g., c.add -> c_add)
        sanitized = sanitized.replace('@', '_at_')  # Handle CAM lookup syntax (e.g., itlb_vpn@[key])
        sanitized = sanitized.replace('[', '_').replace(']', '_').replace(':', '_')
        sanitized = sanitized.replace('(', '_').replace(')', '_').replace(' ', '_')
        sanitized = sanitized.replace("'", '_').replace('{', '_').replace('}', '_')
        sanitized = sanitized.replace(',', '_').replace('?', '_').replace('$', '_')
        sanitized = sanitized.replace('+', 'add').replace('-', 'sub')
        sanitized = sanitized.replace('*', 'mul').replace('/s', 'divs').replace('/', 'div')
        sanitized = sanitized.replace('%s', 'mods').replace('%', 'mod')
        sanitized = sanitized.replace('&', 'and').replace('|', 'or').replace('^', 'xor')
        sanitized = sanitized.replace('>>>', 'srlgt').replace('<<', 'sll').replace('>>', 'srl')
        sanitized = sanitized.replace('==', 'eq').replace('!=', 'ne')
        sanitized = sanitized.replace('<=', 'le').replace('>=', 'ge')
        sanitized = sanitized.replace('<', 'lt').replace('>', 'gt')
        sanitized = sanitized.replace('=', 'eq')  # Handle standalone = after ==, !=, <=, >=
        sanitized = sanitized.replace('!', 'not').replace('~', 'inv')

        # Remove duplicate underscores and trailing underscores
        while '__' in sanitized:
            sanitized = sanitized.replace('__', '_')
        sanitized = sanitized.strip('_')

        # Ensure it starts with a letter
        if sanitized and sanitized[0].isdigit():
            sanitized = 'w_' + sanitized

        return sanitized

    def _generate_unique_name(self, base_name: str) -> str:
        """Generate a unique name by appending a counter if needed."""
        # Sanitize the base name to ensure it's a valid Verilog identifier
        sanitized_base = self._sanitize_identifier(base_name)

        if sanitized_base not in self.name_counter:
            self.name_counter[sanitized_base] = 0
            return sanitized_base
        else:
            self.name_counter[sanitized_base] += 1
            return f"{sanitized_base}_{self.name_counter[sanitized_base]}"

    def _get_node_verilog_ref(self, node: Node) -> str:
        """Get the Verilog reference for a node, handling casts and replications specially.

        For cast nodes like $signed(x), this returns the inline cast expression.
        For replication nodes like {1{w_20}}, this returns the inline replication expression.
        For regular nodes, returns the node's Verilog name.
        """
        # Handle cast nodes (e.g., $signed(x))
        if node.data.get('type') == 'cast':
            cast_type = node.data.get('cast_type', 'signed')
            # Get the operand node (the thing being cast)
            if node.incoming_edges:
                operand_node = list(node.incoming_edges)[0].source
                operand_ref = self.node_id_to_name.get(operand_node.id, self._sanitize_identifier(operand_node.id))
                return f"${cast_type}({operand_ref})"
            else:
                # Fallback if no incoming edges
                return node.id

        # Handle replication nodes (e.g., {1{w_20}})
        if node.data.get('type') in ['replication', 'repetition']:
            # Try to find repetition_input edge (newer format)
            value_node = None
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'repetition_input':
                    value_node = edge.source
                    break

            # If found repetition_input, get count from expression data
            if value_node:
                expr = node.data.get('expression', {})
                count = expr.get('count', '1')
                value_ref = self._get_node_verilog_ref(value_node)
                return f"{{{count}{{{value_ref}}}}}"

            # Otherwise try old format with repl_count and repl_value edges
            count_node = None
            value_node = None
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'repl_count':
                    count_node = edge.source
                elif edge.data.get('type') in ['repl_value', 'repetition_input']:
                    value_node = edge.source

            if count_node and value_node:
                # Get the count (usually a literal)
                if count_node.data.get('type') == 'literal':
                    count = count_node.data.get('value', '1')
                else:
                    count = self.node_id_to_name.get(count_node.id, self._sanitize_identifier(count_node.id))

                # Get the value - recursively handle if it's also a special node
                value_ref = self._get_node_verilog_ref(value_node)

                return f"{{{count}{{{value_ref}}}}}"
            elif value_node:
                # Only have value node, extract count from expression
                expr = node.data.get('expression', {})
                if expr.get('type') == 'repetition':
                    count = expr.get('count', 1)
                    # Get the value - recursively handle if it's also a special node
                    value_ref = self._get_node_verilog_ref(value_node)
                    return f"{{{count}{{{value_ref}}}}}"
            else:
                # Fallback: use expression data to build repetition with proper name lookups
                expr = node.data.get('expression', {})
                if expr.get('type') == 'repetition':
                    count = expr.get('count', 1)
                    inner_expr = expr.get('expression', {})
                    inner_name = self._get_verilog_name_for_expression(inner_expr)
                    return f"{{{count}{{{inner_name}}}}}"
                # If we can't inline from expression, this repetition should have been declared as a wire
                # Use the wire name if it exists
                if node.id in self.node_id_to_name:
                    return self.node_id_to_name[node.id]
                # Should not reach here - repetitions should always be inlinable
                return "{/* ERROR: cannot inline repetition */}"

        # Handle concatenation nodes (e.g., {w_20, w_21})
        if node.data.get('type') == 'concatenation':
            # Find all concat_input edges (handle both concat_input and concatenation_input)
            # Sort by position to ensure correct MSB-to-LSB order
            concat_parts = []
            sorted_edges = sorted(node.incoming_edges, key=lambda e: e.data.get('position', 0))
            for edge in sorted_edges:
                if edge.data.get('type') in ['concat_input', 'concatenation_input']:
                    part_node = edge.source
                    part_ref = self._get_node_verilog_ref(part_node)
                    concat_parts.append(part_ref)

            if concat_parts:
                return "{" + ", ".join(concat_parts) + "}"
            else:
                # Fallback: use expression data to build concatenation with proper name lookups
                expr = node.data.get('expression', {})
                if expr.get('type') == 'concatenation':
                    parts = []
                    for sub_expr in expr.get('parts', []):
                        part_name = self._get_verilog_name_for_expression(sub_expr)
                        parts.append(part_name)
                    if parts:
                        return "{" + ", ".join(parts) + "}"
                # If we can't inline from expression, this concatenation should have been declared as a wire
                # Use the wire name if it exists
                if node.id in self.node_id_to_name:
                    return self.node_id_to_name[node.id]
                # Should not reach here - concatenations should always be inlinable
                return "{/* ERROR: cannot inline concatenation */}"

        # Handle constant nodes (e.g., constant address for rf[31] in jal)
        if node.data.get('type') == 'constant':
            value = node.data.get('value', 0)
            bit_width = node.data.get('bit_width', 32)
            return f"{bit_width}'d{value}"

        # Handle literal nodes - inline the value with proper width
        if node.data.get('type') == 'literal':
            value = node.data.get('value', 0)
            # Use bit_width from node data, or expression width, or infer it
            bit_width = node.data.get('bit_width')
            if bit_width is None:
                expr = node.data.get('expression', {})
                bit_width = expr.get('width', self._infer_bit_width(node))
            # Safeguard: ensure the width can actually represent the value
            # (prevents truncation bugs like 2'd12 which silently becomes 0)
            if isinstance(value, int) and value > 0:
                min_width = value.bit_length()
                if bit_width < min_width:
                    bit_width = min_width
            return f"{bit_width}'d{value}"

        if node.data.get('type') == 'sized_literal':
            width = node.data.get('width', 1)
            # Determine the best representation based on available data
            if 'bits' in node.data:
                bits = node.data.get('bits', '0')
                return f"{width}'b{bits}"
            elif 'hex_digits' in node.data:
                hex_digits = node.data.get('hex_digits', '0')
                return f"{width}'h{hex_digits}"
            elif 'dec_digits' in node.data:
                dec_digits = node.data.get('dec_digits', '0')
                return f"{width}'d{dec_digits}"
            else:
                value = node.data.get('value', 0)
                return f"{width}'d{value}"

        if node.data.get('type') == 'binary_wildcard':
            # For binary wildcards without wildcards, treat as binary literal
            pattern = node.data.get('pattern', '0')
            width = node.data.get('width', len(pattern))
            if '*' not in pattern:
                return f"{width}'b{pattern}"
            # With wildcards, fall through to wire reference (shouldn't happen in comparisons)

        # Regular nodes: return their mapped Verilog name
        # For architectural states with split read/write (e.g., pc split into pc_rd/pc_wr),
        # prefer the _rd version when reading the value
        node_name = node.data.get('name', node.id)
        # Only add _rd suffix if the name doesn't already end with _rd or _zext
        # (to avoid double-suffix like rf_rm_rd_zext_rd)
        if not node_name.endswith('_rd') and not node_name.endswith('_zext'):
            if f"{node_name}_rd" in self.node_id_to_name:
                return self.node_id_to_name[f"{node_name}_rd"]
        if node.id in self.node_id_to_name:
            return self.node_id_to_name[node.id]
        # Also check if node.id itself ends with a name that has _rd version
        # This handles cases like when node.id is "pc" but the mapping uses "pc_rd"
        # Only add _rd suffix if the id doesn't already end with _rd or _zext
        if not node.id.endswith('_rd') and not node.id.endswith('_zext'):
            if f"{node.id}_rd" in self.node_id_to_name:
                return self.node_id_to_name[f"{node.id}_rd"]
        return self._sanitize_identifier(node.id)

    def _generate_concat_name(self, node: Node) -> str:
        """Generate a descriptive name for concatenation nodes."""
        expr = node.data.get('expression', {})
        if expr.get('type') != 'concatenation':
            return self._sanitize_identifier(node.id)

        # Try to extract meaningful names from the sub-expressions
        parts_list = expr.get('parts', [])
        if not parts_list:
            return self._generate_unique_name('concat')

        # Get the first identifier we can find to use as base name
        parts = []
        for sub_expr in parts_list:
            if sub_expr.get('type') == 'identifier':
                parts.append(sub_expr['name'])
            elif sub_expr.get('type') == 'repetition':
                # Try to get the inner expression
                inner = sub_expr.get('expression', {})
                if inner.get('type') == 'array_access':
                    array_name = inner.get('target', {}).get('name', 'rep')
                    parts.append(f"{array_name}_rep")
                else:
                    parts.append('rep')

        if parts:
            base_name = '_'.join(parts[:2])  # Use first 2 parts to avoid long names
            return self._generate_unique_name(f"concat_{base_name}")
        else:
            return self._generate_unique_name('concat')

    def _generate_repetition_name(self, node: Node) -> str:
        """Generate a descriptive name for repetition nodes."""
        expr = node.data.get('expression', {})
        if expr.get('type') != 'repetition':
            return self._sanitize_identifier(node.id)

        count = expr.get('count', 0)
        inner_expr = expr.get('expression', {})

        # Try to get a meaningful name from the inner expression
        if inner_expr.get('type') == 'identifier':
            base_name = f"rep{count}_{inner_expr['name']}"
        elif inner_expr.get('type') == 'array_access':
            array_name = inner_expr.get('target', {}).get('name', 'val')
            index = inner_expr.get('index', {})
            if index.get('type') == 'literal':
                base_name = f"rep{count}_{array_name}_{index['value']}"
            else:
                base_name = f"rep{count}_{array_name}"
        else:
            base_name = f"rep{count}"

        return self._generate_unique_name(base_name)

    def _generate_ternary_name(self, node: Node) -> str:
        """Generate a descriptive name for ternary operator nodes."""
        expr = node.data.get('expression', {})
        if expr.get('type') != 'ternary_op':
            return self._sanitize_identifier(node.id)

        # Try to extract meaningful names from the condition and branches
        cond_expr = expr.get('condition', {})
        true_expr = expr.get('if_true', {})

        # Get names for condition and values
        parts = []
        if cond_expr.get('type') == 'identifier':
            parts.append(cond_expr['name'])
        elif cond_expr.get('type') == 'binary_op':
            # For binary ops like r1 == r2, try to get variable names
            left = cond_expr.get('left', {})
            if left.get('type') == 'identifier':
                parts.append(left['name'])

        # Add a part from the true value
        if true_expr.get('type') == 'identifier':
            parts.append(true_expr['name'])

        # Build descriptive name
        # Use _ternary suffix to avoid collision with priority mux nodes (which use _mux)
        if parts:
            base_name = '_'.join(parts[:2]) + '_ternary'  # Use first 2 parts
        else:
            base_name = 'ternary'

        return self._generate_unique_name(base_name)

    def _generate_module_header(self):
        """Generate module declaration with ports."""
        self.module_header = f"module {self.module_name}(\n"

        # Collect all input/output ports from the graph
        input_ports = []
        output_ports = []

        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if node.data.get('is_port', False):
                port_name = node.data.get('name', node.id)
                port_direction = node.data.get('port_direction', 'input')
                bit_width = self._infer_bit_width(node)

                if port_direction == 'input':
                    input_ports.append({'name': port_name, 'bit_width': bit_width})
                elif port_direction == 'output':
                    output_ports.append({'name': port_name, 'bit_width': bit_width})

        # Always add clk and reset if they're not already in input_ports
        if not any(p['name'] == 'clk' for p in input_ports):
            input_ports.insert(0, {'name': 'clk', 'bit_width': 1})
        if not any(p['name'] == 'reset' for p in input_ports):
            input_ports.insert(1, {'name': 'reset', 'bit_width': 1})

        # Add input ports
        for port in input_ports:
            name = port['name']
            bit_width = port['bit_width'] if port['bit_width'] else 1
            if bit_width > 1:
                self.module_header += f"    input wire [{bit_width-1}:0] {name},\n"
            else:
                self.module_header += f"    input wire {name},\n"

        # Add output ports
        for port in output_ports:
            name = port['name']
            bit_width = port['bit_width'] if port['bit_width'] else 1
            if bit_width > 1:
                self.module_header += f"    output wire [{bit_width-1}:0] {name},\n"
            else:
                self.module_header += f"    output wire {name},\n"

        # Add reset value inputs for single-dimensional ISA state (skip if already in input_ports)
        for reg_decl in self.reg_declarations:
            name = reg_decl['name']
            reset_port_name = f"reset_{name}"
            # Skip if this reset port is already in input_ports (from parser)
            if any(p['name'] == reset_port_name for p in input_ports):
                continue
            bit_width = reg_decl['bit_width']
            if bit_width > 1:
                self.module_header += f"    input wire [{bit_width-1}:0] {reset_port_name},\n"
            else:
                self.module_header += f"    input wire {reset_port_name},\n"

        # Add external inputs (from ext declarations, skip if already in input_ports)
        for ext_input in self.external_inputs:
            name = ext_input['name']
            # Skip if this port is already in input_ports (from parser)
            if any(p['name'] == name for p in input_ports):
                continue
            bit_width = ext_input['bit_width']
            if bit_width > 1:
                self.module_header += f"    input wire [{bit_width-1}:0] {name},\n"
            else:
                self.module_header += f"    input wire {name},\n"

        # Add external outputs (from ext push declarations, skip if already in output_ports)
        # All ext-push ports are registered (driven by <= in always @(posedge clk)),
        # so they use 'logic'. Ports ending in _wr get an auto _valid companion signal;
        # non-_wr ports have _valid managed separately via ISA state.
        for ext_output in self.external_outputs:
            name = ext_output['name']
            # Skip if this port is already in output_ports (from parser)
            if any(p['name'] == name for p in output_ports):
                continue
            bit_width = ext_output['bit_width']
            if bit_width > 1:
                self.module_header += f"    output logic [{bit_width-1}:0] {name},\n"
            else:
                self.module_header += f"    output logic {name},\n"
            # Only auto-generate _valid port for _wr ports;
            # non-_wr ports have _valid managed by ISA state
            if name.endswith("_wr"):
                self.module_header += f"    output logic {name}_valid,\n"

        # Remove trailing comma and close
        self.module_header = self.module_header.rstrip(',\n') + '\n);\n\n'

    def _generate_declarations(self):
        """Generate logic declarations (using SystemVerilog)."""
        self.declarations = ""

        # module instantiations?

        # Register declarations for ISA state - sorted for determinism
        for reg_decl in sorted(self.reg_declarations, key=lambda x: x['name']):
            name = reg_decl['name']
            bit_width = reg_decl['bit_width']
            # Default to 32 bits if width is None
            if bit_width is None:
                bit_width = 32
            if bit_width > 1:
                self.declarations += f"    reg [{bit_width-1}:0] {name};\n"
            else:
                self.declarations += f"    reg {name};\n"

        # Memory declarations - sorted for determinism
        # Skip externalized memories - they don't have internal arrays
        for name, mem_decl in sorted(self.memory_declarations.items()):
            # Skip externalized memories - their storage is external
            if mem_decl.get('externalized', False):
                continue

            bit_width = mem_decl['bit_width']
            array_depth = mem_decl['array_depth']
            # Default to 32 bits if width is None
            if bit_width is None:
                bit_width = 32
            if bit_width > 1:
                self.declarations += f"    reg [{bit_width-1}:0] {name} [0:{array_depth-1}];\n"
            else:
                self.declarations += f"    reg {name} [0:{array_depth-1}];\n"

        # Reg declarations for signals assigned in always @* blocks (mux outputs) - sorted for determinism
        for logic_decl in sorted(self.logic_declarations, key=lambda x: x['name']):
            name = logic_decl['name']
            bit_width = logic_decl['bit_width']
            # Default to 32 bits if width is None
            if bit_width is None:
                bit_width = 32
            if bit_width > 1:
                self.declarations += f"    reg [{bit_width-1}:0] {name};\n"
            else:
                self.declarations += f"    reg {name};\n"

        # Loop variable for memory initialization (Verilog-2001 compatibility)
        self.declarations += "    integer i;\n\n"

        # Wire declarations - sorted for determinism
        for wire_decl in sorted(self.wire_declarations, key=lambda x: x['name']):
            name = wire_decl['name']
            bit_width = wire_decl['bit_width']
            # Default to 32 bits if width is None
            if bit_width is None:
                bit_width = 32
            # Fix width for architectural state write wires that should match register width
            # (fcsr_wr, pc_wr, etc. should be 32 bits, not 1 bit)
            if name.endswith('_wr') and bit_width == 1:
                # Check if there's a corresponding _rd register that's wider
                rd_name = name[:-3] + '_rd'
                for reg in self.reg_declarations:
                    if reg['name'] == rd_name and reg['bit_width'] and reg['bit_width'] > 1:
                        bit_width = reg['bit_width']
                        break
            if bit_width > 1:
                self.declarations += f"    wire [{bit_width-1}:0] {name};\n"
            else:
                self.declarations += f"    wire {name};\n"

        self.declarations += "\n"

    def _generate_memory_initialization(self):
        """Generate initial blocks for memory initialization."""
        self.memory_init = ""

        # Filter out externalized memories - they don't need internal array initialization
        internal_memories = {
            name: mem_decl for name, mem_decl in self.memory_declarations.items()
            if not mem_decl.get('externalized', False)
        }

        if internal_memories:
            self.memory_init += "    initial begin\n"
            # Note: PC/IP initialization is handled by reset ports (reset_pc, reset_ip)
            # so we don't need explicit initialization in the initial block

            # First, initialize small memories (register files) to zero.
            # Large memories (array_depth > 1024) are NOT zeroed here because
            # testbench initial blocks load them via hierarchical references.
            # Zeroing large memories would overwrite testbench-loaded contents
            # due to non-deterministic initial-block ordering in simulation.
            small_memories = {n: d for n, d in sorted(internal_memories.items())
                              if d['array_depth'] <= 1024}
            large_memories = {n: d for n, d in sorted(internal_memories.items())
                              if d['array_depth'] > 1024}
            if small_memories:
                self.memory_init += "        // Initialize small memories (register files) to zero\n"
                for name, mem_decl in sorted(small_memories.items()):
                    array_depth = mem_decl['array_depth']
                    self.memory_init += f"        for (i = 0; i < {array_depth}; i = i + 1) begin\n"
                    self.memory_init += f"            {name}[i] = 0;\n"
                    self.memory_init += f"        end\n"
            if large_memories:
                self.memory_init += "        // Initialize large memories to zero to avoid x-propagation\n"
                self.memory_init += "        // (sparse hex files may not cover all addresses)\n"
                for name, mem_decl in sorted(large_memories.items()):
                    array_depth = mem_decl['array_depth']
                    self.memory_init += f"        for (i = 0; i < {array_depth}; i = i + 1) begin\n"
                    self.memory_init += f"            {name}[i] = 0;\n"
                    self.memory_init += f"        end\n"

            # Then load from memory files (which may be sparse)
            self.memory_init += "        // Load memory contents from files (can be sparse)\n"
            for name, mem_decl in sorted(internal_memories.items()):
                mem_file = mem_decl.get('mem_file')
                if mem_file:  # Skip if None (e.g., RAS doesn't need initialization file)
                    self.memory_init += f"        $readmemh(\"{mem_file}\", {name});\n"
            self.memory_init += "    end\n\n"

        # Print info about externalized memories
        if self.externalized_memories:
            self.memory_init += f"    // Note: {', '.join(sorted(self.externalized_memories))} externalized (no internal array)\n\n"

    def _prescan_ternary_assignments(self):
        """Pre-scan graph for ternary expressions and add their names to assigned_signals.

        This prevents duplicate MUX blocks from being generated for signals that already
        have ternary assign statements. We only mark the ternary expression NODE itself,
        NOT its assignment targets (those still need assignment edges generated).
        """
        for node_id, node in sorted(self.graph.nodes.items()):
            # Look for ternary operations
            if node.data.get('type') == 'ternary_op' or node.data.get('operator') == '?:':
                # Mark this ternary node itself as assigned (to prevent duplicate MUX blocks)
                node_name = self.node_id_to_name.get(node.id,
                            self._sanitize_identifier(node.data.get('name', node.id)))
                self.assigned_signals.add(node_name)

    def _prescan_memory_write_ports(self):
        """Pre-scan for memory write ports to populate self.memory_write_ports.

        This must be called after _generate_combinational_logic (which populates node_id_to_name)
        but before _finalize_externalized_memory_ports (which uses memory_write_ports).

        The same logic runs again in _generate_sequential_logic for internal memory writes,
        but this pass is only for externalized memories to enable port generation.
        """
        if not self.externalized_memories:
            return

        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if node.data.get('type') == 'memory_write_port':
                # Find write_data and write_address edges
                write_data_edge = None
                write_addr_edge = None
                memory_edge = None

                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'write_data':
                        write_data_edge = edge
                    elif edge.data.get('type') == 'write_address':
                        write_addr_edge = edge

                for edge in node.outgoing_edges:
                    if edge.data.get('type') == 'memory_write':
                        memory_edge = edge

                if write_data_edge and write_addr_edge and memory_edge:
                    memory_name = memory_edge.target.data.get('name', memory_edge.target.id)

                    # Only process externalized memories
                    if memory_name not in self.externalized_memories:
                        continue

                    # Collect write enable signals from the data mux
                    write_enables = []
                    data_mux_node = write_data_edge.source

                    if data_mux_node.data.get('type') in ['multiplexer', 'mux', 'port_data_merge', 'memory_data_merge']:
                        for edge in sorted(data_mux_node.incoming_edges, key=lambda e: (e.source.id, e.target.id)):
                            edge_type = edge.data.get('type')
                            if edge_type in ['mux_select', 'port_select']:
                                select_node = edge.source
                                if ('_write_enable' in select_node.id or
                                    'write_enable' in select_node.data.get('name', '') or
                                    '_enable_and' in select_node.id or
                                    '_enable' in select_node.id):
                                    write_enables.append(select_node)

                    # Get signal names for the port
                    mem_info = self.memory_declarations.get(memory_name, {})
                    data_source_node = write_data_edge.source
                    data_name = self.node_id_to_name.get(data_source_node.id,
                                                         self._sanitize_identifier(data_source_node.id))

                    addr_name = self.node_id_to_name.get(write_addr_edge.source.id,
                                                         self._sanitize_identifier(write_addr_edge.source.id))

                    # Get enable signal - use combined enable or create OR
                    enable_name = node.data.get('combined_write_enable', '')
                    if enable_name:
                        enable_name = self.node_id_to_name.get(enable_name,
                                                                self._sanitize_identifier(enable_name))
                    if not enable_name and write_enables:
                        enable_name = self.node_id_to_name.get(write_enables[0].id,
                                                                self._sanitize_identifier(write_enables[0].id))

                    # Get combined byte enable signal if one was created during externalization
                    combined_byte_enable = node.data.get('combined_byte_enable', '')
                    if combined_byte_enable:
                        combined_byte_enable = self.node_id_to_name.get(
                            combined_byte_enable, self._sanitize_identifier(combined_byte_enable))

                    self.memory_write_ports.append({
                        'mem': memory_name,
                        'port_name': node.id,
                        'addr_signal': addr_name,
                        'data_signal': data_name,
                        'enable_signal': enable_name,
                        'data_width': mem_info.get('bit_width', 32),
                        'addr_width': mem_info.get('addr_width', 32),
                        'combined_byte_enable': combined_byte_enable
                    })

    def _generate_combinational_logic(self):
        """Generate combinational logic for operations and assignments."""
        # Preserve any comb_logic added during _analyze_graph (e.g., ibuf/cache assigns)
        early_comb_logic = self.comb_logic
        self.comb_logic = early_comb_logic
        # Pre-initialize seq_logic in case FP operations need to add sequential logic
        if not hasattr(self, 'seq_logic'):
            self.seq_logic = ""

        # Pre-scan: identify signals that will be assigned via ternary expressions
        # This prevents mux blocks from being generated for signals that already have assign statements
        # DISABLED: This was causing issues with RV64 tests
        # self._prescan_ternary_assignments()

        # RISC-V: x0 is hardwired to zero
        if 'x0' in self.graph.nodes:
            self.comb_logic += "    // RISC-V x0 hardwired to zero\n"
            self.comb_logic += "    assign x0 = 32'h0;\n\n"

        # Generate alias assignments for instruction-prefixed ISA state copies
        # These read from the shared _rd register (e.g., add_satp = satp_rd)
        if hasattr(self, 'isa_state_aliases') and self.isa_state_aliases:
            self.comb_logic += "    // ISA state aliases (instruction-prefixed copies read from shared register)\n"
            for alias in self.isa_state_aliases:
                self.comb_logic += f"    assign {alias['alias']} = {alias['source']};\n"
            self.comb_logic += "\n"

        # Generate renamer signal assignments (connects arch indices to renamer and renamer outputs to uarch indices)
        if hasattr(self, 'renamer_assigns') and self.renamer_assigns:
            self.comb_logic += "    // Renamer signal connections\n"
            for assign_stmt in self.renamer_assigns:
                self.comb_logic += f"    {assign_stmt}\n"
            self.comb_logic += "\n"

        # Generate assign statements for each wire
        processed_nodes = set()

        # Process nodes in dependency order
        for node in self._get_dependency_order():
            if node.id in processed_nodes:
                continue

            # Skip nodes that are inlined (cast only)
            # Note: replication and concatenation need their own assign statements
            if node.data.get('type') in ['cast']:
                processed_nodes.add(node.id)
                continue

            if node.data.get('type') in ['alu_operand_mux', 'alu_opcode_mux']:
                self._generate_alu_mux_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'alu_module':
                self._generate_alu_module_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') in ['operation', 'binary_op']:
                self._generate_operation_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'fp_operation':
                self._generate_fp_operation_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'array_access':
                self._generate_array_access_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') in ['address_offset', 'port_address_offset']:
                self._generate_address_offset_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') in ['memory_data_merge', 'port_data_merge']:
                self._generate_memory_data_merge_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'bit_slice' or node.data.get('expression', {}).get('type') == 'bit_slice':
                self._generate_bit_slice_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'zero_extend':
                self._generate_zero_extend_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'sign_extend':
                self._generate_sign_extend_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'write_data_slice':
                self._generate_write_data_slice_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'literal':
                self._generate_literal_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'sized_literal':
                self._generate_sized_literal_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'concatenation':
                self._generate_concatenation_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'repetition':
                self._generate_repetition_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'ternary_op':
                self._generate_ternary_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'comparison':
                self._generate_comparison_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') in ['logical_and', 'logical_or', 'logical_not']:
                self._generate_logical_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'instruction_enable':
                self._generate_instruction_enable_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'byte_enable_mux':
                self._generate_byte_enable_mux_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'one_hot_mux' and (node.data.get('is_address_mux') or node.data.get('is_shared_read_addr_mux')):
                self._generate_address_mux_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'pipeline_stall_controller':
                # Generate stall controller logic (OR of all hazard signals)
                self._generate_stall_controller_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'array_read' and node.data.get('ras_component'):
                # Generate RAS read logic (top of stack prediction)
                self._generate_ras_read_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'mux' and node.data.get('ras_component'):
                # Generate RAS prediction mux logic
                self._generate_ras_predict_mux_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') in ['multiplexer', 'alu_module', 'uarch_counter', 'memory_access_counter', 'hazard_detection_unit', 'hazard_detector']:
                # Generate module instantiation
                self._generate_module_instantiation(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'cam_lookup':
                self._generate_cam_lookup_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'builtin_call':
                self._generate_builtin_call_logic(node)
                processed_nodes.add(node.id)

        # Generate assignments for variables driven by expressions
        self._generate_variable_assignments()

        # Generate conceptual forwarding for split _rd nodes
        self._generate_conceptual_forwarding()

        # Add pending cache write input assignments
        if hasattr(self, '_pending_cache_assigns') and self._pending_cache_assigns:
            self.comb_logic += "\n    // Cache write input assignments\n"
            for assign in self._pending_cache_assigns:
                self.comb_logic += assign

        # Add TLB logic (storage, matching, outputs)
        if hasattr(self, '_pending_tlb_assigns') and self._pending_tlb_assigns:
            for assign in self._pending_tlb_assigns:
                self.comb_logic += assign

        # Add TLB sequential logic (update, flush)
        if hasattr(self, '_pending_tlb_seq') and self._pending_tlb_seq:
            for seq in self._pending_tlb_seq:
                self.comb_logic += seq

    def _get_dependency_order(self) -> List[Node]:
        """Get nodes in dependency order (topological sort).

        Uses Kahn's algorithm for O(n+e) complexity instead of O(n²).
        """
        from collections import deque

        # Dependency edge types that establish ordering
        dep_types = {'operand', 'array_index', 'bit_access'}

        # Build in-degree map and adjacency list
        in_degree = {}  # node_id -> count of unprocessed dependencies
        dependents = {}  # node_id -> list of node_ids that depend on it
        all_nodes = {}  # node_id -> node

        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            all_nodes[node.id] = node
            in_degree[node.id] = 0
            dependents[node.id] = []

        # Count dependencies and build reverse adjacency
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            for edge in node.incoming_edges:
                if edge.data.get('type') in dep_types and edge.source.id in all_nodes:
                    in_degree[node.id] += 1
                    dependents[edge.source.id].append(node.id)

        # Start with nodes that have no dependencies - sorted for determinism
        queue = deque()
        for node_id, degree in sorted(in_degree.items()):
            if degree == 0:
                queue.append(node_id)

        ordered = []
        while queue:
            node_id = queue.popleft()
            ordered.append(all_nodes[node_id])

            # Decrement in-degree of dependents - sorted for determinism
            for dep_id in sorted(dependents[node_id]):
                in_degree[dep_id] -= 1
                if in_degree[dep_id] == 0:
                    queue.append(dep_id)

        # Handle cycles - add any remaining nodes - sorted for determinism
        for node_id, node in sorted(all_nodes.items()):
            if node not in ordered:
                ordered.append(node)

        return ordered

    def _resolve_ref_with_prefix(self, name: str, calling_node_id: str) -> str:
        """Resolve a bare identifier to its instruction-prefixed Verilog name.

        After graph merging, instruction-local variables (e.g., 'taken', 'invtaken')
        become prefixed (e.g., 'cmpib_eq_taken', 'cmpib_eq_invtaken'). Edge-based
        name resolution via _get_node_verilog_ref may return bare names for nodes
        that were not added to node_id_to_name under their un-prefixed ID.

        This method uses the calling node's ID as context to recover the prefix.
        For example, given name='invtaken' and calling_node_id='cmpib_eq_invtaken_and_expr_8096',
        it finds '_invtaken' at index 8, extracts 'cmpib_eq_invtaken', and returns
        the mapped Verilog name for that node.
        """
        if not calling_node_id:
            return name
        suffix = f"_{name}"
        idx = calling_node_id.find(suffix)
        if idx != -1:
            prefixed_name = calling_node_id[:idx + len(suffix)]
            # Guard: don't resolve to the calling node itself (would create
            # a self-referencing assignment like x = !x)
            if prefixed_name != calling_node_id:
                if prefixed_name in self.node_id_to_name:
                    return self.node_id_to_name[prefixed_name]
                if prefixed_name in self.graph.nodes:
                    return self._get_node_verilog_ref(self.graph.nodes[prefixed_name])
        return name

    def _generate_alu_mux_logic(self, node: Node):
        """Emit a priority-encoded assign for an ``alu_operand_mux`` or
        ``alu_opcode_mux`` node.

        Each entry in ``node.data['mux_entries']`` is a dict with:
        - ``enable``    – instruction enable signal name
        - ``source_id`` – (operand mux only) graph node id for the operand
        - ``opcode``    – (opcode mux only) integer opcode value
        """
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))
        if verilog_name in self.assigned_signals:
            return
        self.assigned_signals.add(verilog_name)

        entries = node.data.get('mux_entries', [])
        width = node.data.get('bit_width', 32)
        is_opcode = node.data.get('type') == 'alu_opcode_mux'

        expr = f"{width}'d0"
        for entry in reversed(entries):
            enable = entry['enable']
            # Compound enables (containing ||) need parentheses for
            # correct Verilog ternary precedence.
            if '||' in enable:
                enable = f"({enable})"
            if is_opcode:
                opw = width
                val = f"{opw}'d{entry['opcode']}"
            else:
                src_id = entry.get('source_id')
                if src_id and src_id in self.node_id_to_name:
                    val = self.node_id_to_name[src_id]
                else:
                    val = f"{width}'d0"
            expr = f"{enable} ? {val} : {expr}"

        self.comb_logic += f"    assign {verilog_name} = {expr};\n"

    def _generate_alu_module_logic(self, node: Node):
        """Emit the ALU module definition and its instantiation.

        Reads incoming edges to find operand and opcode mux nodes,
        and outgoing assignment edges to route the result.
        """
        alu_spec = node.data.get('alu_spec')
        if not alu_spec:
            return

        safe_name = self._sanitize_identifier(alu_spec.name)
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))
        data_width = alu_spec.input_width
        output_width = alu_spec.output_width
        opcode_width = alu_spec.opcode_width

        # --- 1. Module definition (deduplicated by safe_name) -----------
        if not hasattr(self, '_emitted_alu_modules'):
            self._emitted_alu_modules = set()

        if safe_name not in self._emitted_alu_modules:
            self._emitted_alu_modules.add(safe_name)
            mod = f"module {safe_name}(\n"
            mod += f"    input wire [{data_width-1}:0] operand_a,\n"
            mod += f"    input wire [{data_width-1}:0] operand_b,\n"
            mod += f"    input wire [{opcode_width-1}:0] opcode,\n"
            mod += f"    output reg [{output_width-1}:0] result\n"
            mod += ");\n\nalways_comb begin\n    case (opcode)\n"
            for operator, op_info in alu_spec.operations.items():
                opc = op_info['opcode']
                desc = op_info['description']
                verilog_op = self._operator_to_verilog(operator)
                if operator in ('<s', '>s', '<=s', '>=s'):
                    mod += f"        {opcode_width}'d{opc}: result = $signed(operand_a) {verilog_op} $signed(operand_b); // {desc}\n"
                elif operator == '>>>':
                    mod += f"        {opcode_width}'d{opc}: result = $signed(operand_a) >>> operand_b; // {desc}\n"
                else:
                    mod += f"        {opcode_width}'d{opc}: result = operand_a {verilog_op} operand_b; // {desc}\n"
            mod += f"        default: result = {output_width}'d0;\n"
            mod += "    endcase\nend\n\nendmodule\n"
            self.extra_modules += mod + "\n"

        # --- 2. Find connected mux signals from incoming edges ----------
        op_a_signal = f"{data_width}'d0"
        op_b_signal = f"{data_width}'d0"
        opc_signal = f"{opcode_width}'d0"

        for edge in node.incoming_edges:
            src_name = self.node_id_to_name.get(edge.source.id,
                                                 self._sanitize_identifier(edge.source.id))
            sig = edge.data.get('signal_name', '')
            if sig == 'operand_a':
                op_a_signal = src_name
            elif sig == 'operand_b':
                op_b_signal = src_name
            elif sig == 'opcode':
                opc_signal = src_name

        # --- 3. Instantiation (unique instance name per node) -----------
        inst_name = self._sanitize_identifier(f"{node.id}_inst")
        self.comb_logic += f"\n    // {safe_name} instantiation\n"
        self.comb_logic += f"    {safe_name} {inst_name}(\n"
        self.comb_logic += f"        .operand_a({op_a_signal}),\n"
        self.comb_logic += f"        .operand_b({op_b_signal}),\n"
        self.comb_logic += f"        .opcode({opc_signal}),\n"
        self.comb_logic += f"        .result({verilog_name})\n"
        self.comb_logic += "    );\n"
        self.assigned_signals.add(verilog_name)

        # --- 4. Route result to original targets -----------------------
        for edge in node.outgoing_edges:
            if edge.data.get('type') == 'assignment':
                target_name = self.node_id_to_name.get(edge.target.id,
                                                        self._sanitize_identifier(edge.target.id))
                if target_name not in self.assigned_signals:
                    self.comb_logic += f"    assign {target_name} = {verilog_name};\n"
                    self.assigned_signals.add(target_name)

    def _generate_operation_logic(self, node: Node):
        """Generate logic for operation nodes."""
        # Skip inlined nodes (their expressions are inlined at point of use)
        if hasattr(self, 'inlined_nodes') and node.id in self.inlined_nodes:
            return

        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Skip if this signal name has already been assigned (prevents duplicate assignments)
        if verilog_name in self.assigned_signals:
            return

        self.assigned_signals.add(verilog_name)

        # Check for unary operations (identity, negation, etc.)
        operator = node.data.get('operator')
        if operator == 'identity' and len(node.incoming_edges) == 1:
            # Simple pass-through: output = input
            input_edge = list(node.incoming_edges)[0]
            input_name = self._get_node_verilog_ref(input_edge.source)
            input_name = self._resolve_ref_with_prefix(input_name, node.id)
            self.comb_logic += f"    assign {verilog_name} = {input_name};\n"
            return

        # Use incoming edges to get operands
        if node.incoming_edges and len(node.incoming_edges) >= 2:
            # Handle n-ary OR/AND operations (e.g., merged enable conditions with 29 inputs)
            # Check both 'operator' and 'operation' fields (latter used by logical_and/logical_or)
            operator = node.data.get('operator') or node.data.get('operation')
            if operator in ['||', '&&', '|', '&'] and len(node.incoming_edges) > 2:
                # Sort edges by operand_index if available, then by source id for determinism
                # Note: We preserve operand_index ordering (don't re-sort operand_names) to maintain
                # semantic meaning even though AND/OR are commutative
                edges = sorted(node.incoming_edges, key=lambda e: (e.data.get('operand_index', 0), e.source.id))
                operand_names = [self._resolve_ref_with_prefix(self._get_node_verilog_ref(e.source), node.id) for e in edges]
                verilog_op = ' || ' if operator == '||' else ' && ' if operator == '&&' else ' | ' if operator == '|' else ' & '
                expr = verilog_op.join(operand_names)
                self.comb_logic += f"    assign {verilog_name} = {expr};\n"
                return

            # Find left and right operands from edges
            left_edge = None
            right_edge = None
            for edge in node.incoming_edges:
                pos = edge.data.get('position')
                if pos == 'left' or edge.data.get('operand') == 'left' or edge.data.get('type') == 'left_operand':
                    left_edge = edge
                elif pos == 'right' or edge.data.get('operand') == 'right' or edge.data.get('type') == 'right_operand':
                    right_edge = edge

            # If no labeled edges, sort by position and use first two
            if not left_edge or not right_edge:
                edges = list(node.incoming_edges)
                # Sort edges by position field (0 should be left, 1 should be right)
                # Handle both int and string positions, use source.id as secondary key for determinism
                def get_position(e):
                    pos = e.data.get('position', 999)
                    if isinstance(pos, str):
                        try:
                            return int(pos)
                        except ValueError:
                            return 999
                    return pos if isinstance(pos, int) else 999
                edges.sort(key=lambda e: (get_position(e), e.source.id))
                left_edge = edges[0] if len(edges) > 0 else None
                right_edge = edges[1] if len(edges) > 1 else None

            if left_edge and right_edge:
                # Use _get_node_verilog_ref to handle cast nodes properly
                left_name = self._resolve_ref_with_prefix(self._get_node_verilog_ref(left_edge.source), node.id)
                right_name = self._resolve_ref_with_prefix(self._get_node_verilog_ref(right_edge.source), node.id)

                # Get operator from node.data directly, or from expression
                expr = node.data.get('expression', {})
                # Check for operator directly in node.data first (e.g., from hazard resolution),
                # Also check 'operation' field (used by logical_and/logical_or from mux_deduplication)
                # then fall back to expression dict
                operator = node.data.get('operator') or node.data.get('operation') or (expr.get('operator', '+') if expr.get('type') == 'binary_op' else '+')
                # Note: '!' and '~' are unary operators - treat as XOR if used in binary context
                if operator in ['!', '~']:
                    verilog_op = '^'
                else:
                    verilog_op = {'+': '+', '-': '-', '*': '*', '/': '/', '%': '%',
                                 '&': '&', '|': '|', '^': '^',
                                 '<<': '<<', '>>': '>>', '>>>': '>>>',  '==': '==', '!=': '!=', '<': '<', '>': '>',
                                 '<=': '<=', '>=': '>=', '&&': '&&', '||': '||',
                                 '<s': '<', '>s': '>', '<=s': '<=', '>=s': '>='}.get(operator, '+')

                # For arithmetic right shift, if left operand is not already a cast, wrap it
                if operator == '>>>':
                    if not left_name.startswith('$signed('):
                        left_name = f"$signed({left_name})"
                    self.comb_logic += f"    assign {verilog_name} = {left_name} {verilog_op} {right_name};\n"
                # For signed division and modulo, wrap both operands in $signed()
                elif operator == '/s':
                    self.comb_logic += f"    assign {verilog_name} = $signed({left_name}) / $signed({right_name});\n"
                elif operator == '%s':
                    self.comb_logic += f"    assign {verilog_name} = $signed({left_name}) % $signed({right_name});\n"
                # For signed comparisons, wrap both operands in $signed() if they're not already cast
                # Use the operand bit widths to determine proper slicing
                elif operator in ['<s', '>s', '<=s', '>=s']:
                    # Get the bit widths of the operands from the source nodes
                    left_width = left_edge.source.data.get('bit_width', 64) if left_edge else 64
                    right_width = right_edge.source.data.get('bit_width', 64) if right_edge else 64
                    comp_width = min(left_width, right_width)

                    # Helper to check if a name is a Verilog literal constant (e.g., 32'b0, 8'hFF)
                    import re
                    def is_verilog_literal(name):
                        return bool(re.match(r"^\d+'[bhd]", name))

                    # Apply proper slicing based on comparison width
                    # Don't add bit slices to Verilog literal constants - they already have width
                    if not left_name.startswith('$signed('):
                        if left_width > comp_width and not is_verilog_literal(left_name):
                            left_name = f"$signed({left_name}[{comp_width-1}:0])"
                        else:
                            left_name = f"$signed({left_name})"
                    if not right_name.startswith('$signed('):
                        if right_width > comp_width and not is_verilog_literal(right_name):
                            right_name = f"$signed({right_name}[{comp_width-1}:0])"
                        else:
                            right_name = f"$signed({right_name})"
                    self.comb_logic += f"    assign {verilog_name} = {left_name} {verilog_op} {right_name};\n"
                else:
                    self.comb_logic += f"    assign {verilog_name} = {left_name} {verilog_op} {right_name};\n"
                return

        # Handle unary operations (single operand)
        if node.incoming_edges and len(node.incoming_edges) == 1:
            operand_edge = list(node.incoming_edges)[0]
            operand_name = self._resolve_ref_with_prefix(self._get_node_verilog_ref(operand_edge.source), node.id)

            expr = node.data.get('expression', {})
            if expr.get('type') == 'unary_op':
                operator = expr.get('operator', '!')
                verilog_op = {'!': '!', '~': '~', '-': '-'}.get(operator, '!')
                self.comb_logic += f"    assign {verilog_name} = {verilog_op}{operand_name};\n"
                return
            if expr.get('type') == 'reduction_op':
                operator = expr.get('operator', '|')
                verilog_op = {'|': '|', '&': '&', '^': '^'}.get(operator, '|')
                self.comb_logic += f"    assign {verilog_name} = {verilog_op}{operand_name};\n"
                return
            # Also check direct operator field for unary ops
            operator = node.data.get('operator')
            if operator in ['!', '~', '-']:
                verilog_op = {'!': '!', '~': '~', '-': '-'}.get(operator, '!')
                self.comb_logic += f"    assign {verilog_name} = {verilog_op}{operand_name};\n"
                return
            # Check for reduction operators
            if operator in ['reduce_|', 'reduce_&', 'reduce_^']:
                verilog_op = operator.replace('reduce_', '')
                self.comb_logic += f"    assign {verilog_name} = {verilog_op}{operand_name};\n"
                return
            # Handle logical_not nodes from mux_deduplication (use 'operation' field)
            if node.data.get('type') == 'logical_not':
                operator = node.data.get('operation', '!')
                verilog_op = {'!': '!', '~': '~', '-': '-'}.get(operator, '!')
                self.comb_logic += f"    assign {verilog_name} = {verilog_op}{operand_name};\n"
                return

        # Handle NOT nodes with no incoming edges
        # These can come from graph_merger (operator='!', id='notXXX') or
        # mux_deduplication (type='logical_not', id='!XXX' which sanitizes to 'notXXX')
        node_type = node.data.get('type')
        node_op = node.data.get('operator') or node.data.get('operation')

        if node_type == 'logical_not' or (node_op == '!' and verilog_name.startswith('not')):
            # Extract the original signal name from the node ID
            # Node ID might be '!bne_res' (sanitizes to 'notbne_res') or 'notbne_res' directly
            if node.id.startswith('!'):
                original_name = node.id[1:]  # Remove '!' prefix
            elif node.id.startswith('not'):
                original_name = node.id[3:]  # Remove 'not' prefix
            else:
                original_name = None

            if original_name:
                if original_name in self.node_id_to_name:
                    original_ref = self.node_id_to_name[original_name]
                    self.comb_logic += f"    assign {verilog_name} = !{original_ref};\n"
                    return
                elif original_name in self.graph.nodes:
                    original_ref = self._get_node_verilog_ref(self.graph.nodes[original_name])
                    self.comb_logic += f"    assign {verilog_name} = !{original_ref};\n"
                    return

        # Fallback to expression-based generation
        expr = node.data.get('expression', {})
        if expr.get('type') == 'binary_op':
            operator = expr['operator']
            left_name = self._get_verilog_name_for_expression(expr['left'], calling_node_id=node.id)
            right_name = self._get_verilog_name_for_expression(expr['right'], calling_node_id=node.id)

            # Handle signed division and modulo specially
            if operator == '/s':
                self.comb_logic += f"    assign {verilog_name} = $signed({left_name}) / $signed({right_name});\n"
            elif operator == '%s':
                self.comb_logic += f"    assign {verilog_name} = $signed({left_name}) % $signed({right_name});\n"
            else:
                # Note: '!' and '~' are unary operators and should not appear here
                # If they do, it's likely an XOR that should use '^'
                if operator in ['!', '~']:
                    verilog_op = '^'
                else:
                    verilog_op = {'+': '+', '-': '-', '*': '*', '/': '/', '%': '%',
                                 '&': '&', '|': '|', '^': '^',
                                 '<<': '<<', '>>': '>>', '>>>': '>>>',  '==': '==', '!=': '!=', '<': '<', '>': '>',
                                 '<=': '<=', '>=': '>=', '&&': '&&', '||': '||'}.get(operator, '+')
                self.comb_logic += f"    assign {verilog_name} = {left_name} {verilog_op} {right_name};\n"
        elif expr.get('type') == 'unary_op':
            operator = expr.get('operator', '!')
            operand_name = self._get_verilog_name_for_expression(expr['operand'], calling_node_id=node.id)
            verilog_op = {'!': '!', '~': '~', '-': '-'}.get(operator, '!')
            self.comb_logic += f"    assign {verilog_name} = {verilog_op}{operand_name};\n"
        elif expr.get('type') == 'reduction_op':
            # Reduction operations: |, &, ^ - reduce all bits to single bit
            operator = expr.get('operator', '|')
            operand_name = self._get_verilog_name_for_expression(expr['operand'], calling_node_id=node.id)
            # In Verilog, reduction operators are the same symbol as binary: |x, &x, ^x
            verilog_op = {'|': '|', '&': '&', '^': '^'}.get(operator, '|')
            self.comb_logic += f"    assign {verilog_name} = {verilog_op}{operand_name};\n"

    def _generate_fp_operation_logic(self, node: Node):
        """Generate logic for FP operation nodes.

        FP operations are implemented as module instantiations. For simple combinational
        operations (sign inject, classify), we generate assign statements. For complex
        operations (add, mul, div), we instantiate pipelined modules.
        """
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Skip if already assigned
        if verilog_name in self.assigned_signals:
            return
        self.assigned_signals.add(verilog_name)

        fp_intrinsic = node.data.get('fp_intrinsic', '')

        # Get operand names and rounding mode from incoming edges
        # For FP operands, trace back to the actual FP register file reads if needed
        operand_names = []
        rounding_mode_ref = None
        for edge in sorted(node.incoming_edges, key=lambda e: e.data.get('position', 'z')):
            if edge.data.get('type') == 'fp_operand':
                source = edge.source
                operand_ref = self._get_node_verilog_ref(source)

                # If the operand reference doesn't exist as a declared wire,
                # trace back to the FP register file read
                wire_names = {w['name'] for w in self.wire_declarations}
                reg_names = {r['name'] for r in self.reg_declarations}
                if operand_ref not in wire_names and operand_ref not in reg_names:
                    # Check if this operand traces back to an frf read
                    traced_ref = self._trace_fp_operand_to_reg(source)
                    if traced_ref:
                        operand_ref = traced_ref

                operand_names.append(operand_ref)
            elif edge.data.get('type') == 'rounding_mode':
                # Extract rounding mode from the graph (passed explicitly from ISA file)
                source = edge.source
                rounding_mode_ref = self._get_node_verilog_ref(source)

        # Handle different FP operations
        if fp_intrinsic in ['fp_sgnj', 'fp_sgnjn', 'fp_sgnjx']:
            # Sign injection - combinational (FP32)
            # When reading from 64-bit FRF for 32-bit FP ops, need NaN-unboxing
            if len(operand_names) >= 2:
                a, b = operand_names[0], operand_names[1]

                # Check if operands come from 64-bit FP register file and need NaN-unboxing
                fp_operand_edges = [e for e in sorted(node.incoming_edges, key=lambda e: e.data.get('position', 'z'))
                                    if e.data.get('type') == 'fp_operand']

                # Generate NaN-unboxed operand references
                a_unboxed = a
                b_unboxed = b
                for i, edge in enumerate(fp_operand_edges):
                    source_width = edge.source.data.get('bit_width', 32)
                    if source_width == 64:
                        # Need NaN-unboxing: if upper 32 bits are all 1s, use lower 32, else canonical NaN
                        operand = operand_names[i] if i < len(operand_names) else None
                        if operand and i == 0:
                            unboxed_name = f"{verilog_name}_a_unboxed"
                            if unboxed_name not in self.assigned_signals:
                                # Add wire declaration and assignment together in comb_logic
                                self.comb_logic += f"    wire [31:0] {unboxed_name};\n"
                                self.comb_logic += f"    assign {unboxed_name} = ({operand}[63:32] == 32'hFFFFFFFF) ? {operand}[31:0] : 32'h7FC00000;\n"
                                self.assigned_signals.add(unboxed_name)
                            a_unboxed = unboxed_name
                        elif operand and i == 1:
                            unboxed_name = f"{verilog_name}_b_unboxed"
                            if unboxed_name not in self.assigned_signals:
                                # Add wire declaration and assignment together in comb_logic
                                self.comb_logic += f"    wire [31:0] {unboxed_name};\n"
                                self.comb_logic += f"    assign {unboxed_name} = ({operand}[63:32] == 32'hFFFFFFFF) ? {operand}[31:0] : 32'h7FC00000;\n"
                                self.assigned_signals.add(unboxed_name)
                            b_unboxed = unboxed_name

                if fp_intrinsic == 'fp_sgnj':
                    # Copy sign from b to a
                    self.comb_logic += f"    assign {verilog_name} = {{{b_unboxed}[31], {a_unboxed}[30:0]}};\n"
                elif fp_intrinsic == 'fp_sgnjn':
                    # Negate sign of b, apply to a
                    self.comb_logic += f"    assign {verilog_name} = {{~{b_unboxed}[31], {a_unboxed}[30:0]}};\n"
                elif fp_intrinsic == 'fp_sgnjx':
                    # XOR signs
                    self.comb_logic += f"    assign {verilog_name} = {{{a_unboxed}[31] ^ {b_unboxed}[31], {a_unboxed}[30:0]}};\n"

        elif fp_intrinsic in ['fp_sgnj_d', 'fp_sgnjn_d', 'fp_sgnjx_d']:
            # Sign injection - combinational (FP64 / D extension)
            if len(operand_names) >= 2:
                a, b = operand_names[0], operand_names[1]
                if fp_intrinsic == 'fp_sgnj_d':
                    # Copy sign from b to a
                    self.comb_logic += f"    assign {verilog_name} = {{{b}[63], {a}[62:0]}};\n"
                elif fp_intrinsic == 'fp_sgnjn_d':
                    # Negate sign of b, apply to a
                    self.comb_logic += f"    assign {verilog_name} = {{~{b}[63], {a}[62:0]}};\n"
                elif fp_intrinsic == 'fp_sgnjx_d':
                    # XOR signs
                    self.comb_logic += f"    assign {verilog_name} = {{{a}[63] ^ {b}[63], {a}[62:0]}};\n"

        elif fp_intrinsic == 'fp_class':
            # Classification - combinational (FP32)
            # When reading from 64-bit FRF for 32-bit FP ops, need NaN-unboxing
            if len(operand_names) >= 1:
                a = operand_names[0]

                # Check if operand comes from 64-bit FP register file and needs NaN-unboxing
                fp_operand_edges = [e for e in sorted(node.incoming_edges, key=lambda e: e.data.get('position', 'z'))
                                    if e.data.get('type') == 'fp_operand']
                a_ref = a
                if fp_operand_edges and fp_operand_edges[0].source.data.get('bit_width', 32) == 64:
                    # Need NaN-unboxing: if upper 32 bits are all 1s, use lower 32, else canonical NaN
                    unboxed_name = f"{verilog_name}_a_unboxed"
                    if unboxed_name not in self.assigned_signals:
                        # Add wire declaration and assignment together in comb_logic
                        self.comb_logic += f"    wire [31:0] {unboxed_name};\n"
                        self.comb_logic += f"    assign {unboxed_name} = ({a}[63:32] == 32'hFFFFFFFF) ? {a}[31:0] : 32'h7FC00000;\n"
                        self.assigned_signals.add(unboxed_name)
                    a_ref = unboxed_name

                self.comb_logic += f"    // FP classification for {a_ref}\n"
                self.comb_logic += f"    wire {verilog_name}_is_neg = {a_ref}[31];\n"
                self.comb_logic += f"    wire [7:0] {verilog_name}_exp = {a_ref}[30:23];\n"
                self.comb_logic += f"    wire [22:0] {verilog_name}_mant = {a_ref}[22:0];\n"
                self.comb_logic += f"    wire {verilog_name}_is_zero = ({verilog_name}_exp == 8'b0) && ({verilog_name}_mant == 23'b0);\n"
                self.comb_logic += f"    wire {verilog_name}_is_subnormal = ({verilog_name}_exp == 8'b0) && ({verilog_name}_mant != 23'b0);\n"
                self.comb_logic += f"    wire {verilog_name}_is_normal = ({verilog_name}_exp != 8'b0) && ({verilog_name}_exp != 8'hFF);\n"
                self.comb_logic += f"    wire {verilog_name}_is_inf = ({verilog_name}_exp == 8'hFF) && ({verilog_name}_mant == 23'b0);\n"
                self.comb_logic += f"    wire {verilog_name}_is_nan = ({verilog_name}_exp == 8'hFF) && ({verilog_name}_mant != 23'b0);\n"
                self.comb_logic += f"    wire {verilog_name}_is_qnan = {verilog_name}_is_nan && {verilog_name}_mant[22];\n"
                self.comb_logic += f"    wire {verilog_name}_is_snan = {verilog_name}_is_nan && !{verilog_name}_mant[22];\n"
                self.comb_logic += f"    assign {verilog_name} = {{\n"
                self.comb_logic += f"        22'b0,\n"
                self.comb_logic += f"        {verilog_name}_is_qnan,\n"
                self.comb_logic += f"        {verilog_name}_is_snan,\n"
                self.comb_logic += f"        !{verilog_name}_is_neg && {verilog_name}_is_inf,\n"
                self.comb_logic += f"        !{verilog_name}_is_neg && {verilog_name}_is_normal,\n"
                self.comb_logic += f"        !{verilog_name}_is_neg && {verilog_name}_is_subnormal,\n"
                self.comb_logic += f"        !{verilog_name}_is_neg && {verilog_name}_is_zero,\n"
                self.comb_logic += f"        {verilog_name}_is_neg && {verilog_name}_is_zero,\n"
                self.comb_logic += f"        {verilog_name}_is_neg && {verilog_name}_is_subnormal,\n"
                self.comb_logic += f"        {verilog_name}_is_neg && {verilog_name}_is_normal,\n"
                self.comb_logic += f"        {verilog_name}_is_neg && {verilog_name}_is_inf\n"
                self.comb_logic += f"    }};\n"

        elif fp_intrinsic == 'fp_class_d':
            # Classification - combinational (FP64 / D extension)
            if len(operand_names) >= 1:
                a = operand_names[0]
                self.comb_logic += f"    // FP64 classification for {a}\n"
                self.comb_logic += f"    wire {verilog_name}_is_neg = {a}[63];\n"
                self.comb_logic += f"    wire [10:0] {verilog_name}_exp = {a}[62:52];\n"
                self.comb_logic += f"    wire [51:0] {verilog_name}_mant = {a}[51:0];\n"
                self.comb_logic += f"    wire {verilog_name}_is_zero = ({verilog_name}_exp == 11'b0) && ({verilog_name}_mant == 52'b0);\n"
                self.comb_logic += f"    wire {verilog_name}_is_subnormal = ({verilog_name}_exp == 11'b0) && ({verilog_name}_mant != 52'b0);\n"
                self.comb_logic += f"    wire {verilog_name}_is_normal = ({verilog_name}_exp != 11'b0) && ({verilog_name}_exp != 11'h7FF);\n"
                self.comb_logic += f"    wire {verilog_name}_is_inf = ({verilog_name}_exp == 11'h7FF) && ({verilog_name}_mant == 52'b0);\n"
                self.comb_logic += f"    wire {verilog_name}_is_nan = ({verilog_name}_exp == 11'h7FF) && ({verilog_name}_mant != 52'b0);\n"
                self.comb_logic += f"    wire {verilog_name}_is_qnan = {verilog_name}_is_nan && {verilog_name}_mant[51];\n"
                self.comb_logic += f"    wire {verilog_name}_is_snan = {verilog_name}_is_nan && !{verilog_name}_mant[51];\n"
                self.comb_logic += f"    assign {verilog_name} = {{\n"
                self.comb_logic += f"        22'b0,\n"
                self.comb_logic += f"        {verilog_name}_is_qnan,\n"
                self.comb_logic += f"        {verilog_name}_is_snan,\n"
                self.comb_logic += f"        !{verilog_name}_is_neg && {verilog_name}_is_inf,\n"
                self.comb_logic += f"        !{verilog_name}_is_neg && {verilog_name}_is_normal,\n"
                self.comb_logic += f"        !{verilog_name}_is_neg && {verilog_name}_is_subnormal,\n"
                self.comb_logic += f"        !{verilog_name}_is_neg && {verilog_name}_is_zero,\n"
                self.comb_logic += f"        {verilog_name}_is_neg && {verilog_name}_is_zero,\n"
                self.comb_logic += f"        {verilog_name}_is_neg && {verilog_name}_is_subnormal,\n"
                self.comb_logic += f"        {verilog_name}_is_neg && {verilog_name}_is_normal,\n"
                self.comb_logic += f"        {verilog_name}_is_neg && {verilog_name}_is_inf\n"
                self.comb_logic += f"    }};\n"

        elif fp_intrinsic in ['fp_eq', 'fp_lt', 'fp_le', 'fp_min', 'fp_max',
                               'fp_add', 'fp_sub', 'fp_mul', 'fp_div', 'fp_sqrt',
                               'fp_fmadd', 'fp_fmsub', 'fp_fnmadd', 'fp_fnmsub',
                               'fp_cvt_w_s', 'fp_cvt_wu_s', 'fp_cvt_s_w', 'fp_cvt_s_wu',
                               'fp_cvt_l_s', 'fp_cvt_lu_s', 'fp_cvt_s_l', 'fp_cvt_s_lu',
                               # D extension (double precision)
                               'fp_eq_d', 'fp_lt_d', 'fp_le_d', 'fp_min_d', 'fp_max_d',
                               'fp_add_d', 'fp_sub_d', 'fp_mul_d', 'fp_div_d', 'fp_sqrt_d',
                               'fp_fmadd_d', 'fp_fmsub_d', 'fp_fnmadd_d', 'fp_fnmsub_d',
                               'fp_cvt_w_d', 'fp_cvt_wu_d', 'fp_cvt_d_w', 'fp_cvt_d_wu',
                               'fp_cvt_l_d', 'fp_cvt_lu_d', 'fp_cvt_d_l', 'fp_cvt_d_lu',
                               'fp_cvt_s_d', 'fp_cvt_d_s']:
            # Use cvfpu_simple for FP operations (both F and D extensions)
            # Operation mapping: 0=ADD, 1=SUB, 2=MUL, 3=DIV, 4=SQRT
            #                   5=FMADD, 6=FMSUB, 7=FNMADD, 8=FNMSUB
            #                   12=MIN, 13=MAX, 14=EQ, 15=LT, 16=LE
            #                   18=CVT_W, 19=CVT_WU, 20=CVT_x_W, 21=CVT_x_WU
            #                   22=CVT_L, 23=CVT_LU, 24=CVT_x_L, 25=CVT_x_LU
            #                   26=CVT_S_D (double->single), 27=CVT_D_S (single->double)
            op_map = {
                # F extension (single precision)
                'fp_add': 0, 'fp_sub': 1, 'fp_mul': 2, 'fp_div': 3, 'fp_sqrt': 4,
                'fp_fmadd': 5, 'fp_fmsub': 6, 'fp_fnmadd': 7, 'fp_fnmsub': 8,
                'fp_min': 12, 'fp_max': 13, 'fp_eq': 14, 'fp_lt': 15, 'fp_le': 16,
                'fp_cvt_w_s': 18, 'fp_cvt_wu_s': 19, 'fp_cvt_s_w': 20, 'fp_cvt_s_wu': 21,
                'fp_cvt_l_s': 22, 'fp_cvt_lu_s': 23, 'fp_cvt_s_l': 24, 'fp_cvt_s_lu': 25,
                # D extension (double precision) - same op codes, different format
                'fp_add_d': 0, 'fp_sub_d': 1, 'fp_mul_d': 2, 'fp_div_d': 3, 'fp_sqrt_d': 4,
                'fp_fmadd_d': 5, 'fp_fmsub_d': 6, 'fp_fnmadd_d': 7, 'fp_fnmsub_d': 8,
                'fp_min_d': 12, 'fp_max_d': 13, 'fp_eq_d': 14, 'fp_lt_d': 15, 'fp_le_d': 16,
                'fp_cvt_w_d': 18, 'fp_cvt_wu_d': 19, 'fp_cvt_d_w': 20, 'fp_cvt_d_wu': 21,
                'fp_cvt_l_d': 22, 'fp_cvt_lu_d': 23, 'fp_cvt_d_l': 24, 'fp_cvt_d_lu': 25,
                'fp_cvt_s_d': 26, 'fp_cvt_d_s': 27
            }
            op_select = op_map.get(fp_intrinsic, 0)
            self.fp_modules_needed.add('cvfpu')

            # Determine if this is a D extension (double precision) operation
            is_double_op = fp_intrinsic.endswith('_d') or fp_intrinsic in ['fp_cvt_d_w', 'fp_cvt_d_wu', 'fp_cvt_d_l', 'fp_cvt_d_lu', 'fp_cvt_d_s']
            # Determine FPU width: 64 for D extension or 64-bit int conversions, 32 otherwise
            is_64bit_op = fp_intrinsic in ['fp_cvt_l_s', 'fp_cvt_lu_s', 'fp_cvt_s_l', 'fp_cvt_s_lu'] or is_double_op
            fpu_width = 64 if is_64bit_op else 32
            # Track if we need D extension format
            fp_format = 1 if is_double_op else 0  # 0=FP32, 1=FP64
            # For F2F conversions, track source format separately
            # fp_cvt_s_d: FP64->FP32, src=1, dst=0
            # fp_cvt_d_s: FP32->FP64, src=0, dst=1
            src_fp_format = None  # None means same as fp_format
            if fp_intrinsic == 'fp_cvt_s_d':
                src_fp_format = 1  # Source is FP64
                fp_format = 0      # Destination is FP32
                fpu_width = 64     # Need 64-bit width for FP64 input
            elif fp_intrinsic == 'fp_cvt_d_s':
                src_fp_format = 0  # Source is FP32
                fp_format = 1      # Destination is FP64

            a = operand_names[0] if len(operand_names) >= 1 else f"{fpu_width}'b0"
            b = operand_names[1] if len(operand_names) >= 2 else f"{fpu_width}'b0"
            c = operand_names[2] if len(operand_names) >= 3 else f"{fpu_width}'b0"

            # For single-precision operations (fpu_width=32) with 64-bit FP register file,
            # we need to apply NaN-unboxing: if upper 32 bits != 0xFFFFFFFF, use canonical NaN
            if fpu_width == 32 and not is_double_op:
                # Check if operands come from 64-bit FP register file
                fp_operand_edges = [e for e in sorted(node.incoming_edges, key=lambda e: e.data.get('position', 'z'))
                                    if e.data.get('type') == 'fp_operand']
                for i, edge in enumerate(fp_operand_edges):
                    source_width = edge.source.data.get('bit_width', 32)
                    if source_width == 64:
                        # Apply NaN-unboxing for single-precision FPU operations
                        if i == 0 and len(operand_names) >= 1:
                            unboxed_name = f"{verilog_name}_a_unboxed"
                            if unboxed_name not in self.assigned_signals:
                                self.comb_logic += f"    wire [31:0] {unboxed_name};\n"
                                self.comb_logic += f"    assign {unboxed_name} = ({operand_names[0]}[63:32] == 32'hFFFFFFFF) ? {operand_names[0]}[31:0] : 32'h7FC00000;\n"
                                self.assigned_signals.add(unboxed_name)
                            a = unboxed_name
                        elif i == 1 and len(operand_names) >= 2:
                            unboxed_name = f"{verilog_name}_b_unboxed"
                            if unboxed_name not in self.assigned_signals:
                                self.comb_logic += f"    wire [31:0] {unboxed_name};\n"
                                self.comb_logic += f"    assign {unboxed_name} = ({operand_names[1]}[63:32] == 32'hFFFFFFFF) ? {operand_names[1]}[31:0] : 32'h7FC00000;\n"
                                self.assigned_signals.add(unboxed_name)
                            b = unboxed_name
                        elif i == 2 and len(operand_names) >= 3:
                            unboxed_name = f"{verilog_name}_c_unboxed"
                            if unboxed_name not in self.assigned_signals:
                                self.comb_logic += f"    wire [31:0] {unboxed_name};\n"
                                self.comb_logic += f"    assign {unboxed_name} = ({operand_names[2]}[63:32] == 32'hFFFFFFFF) ? {operand_names[2]}[31:0] : 32'h7FC00000;\n"
                                self.assigned_signals.add(unboxed_name)
                            c = unboxed_name

            # For fp_cvt_l_s, fp_cvt_lu_s, and fp_cvt_d_s, the input is a 32-bit float
            # that needs to be NaN-boxed for the 64-bit FPU (upper 32 bits = all 1s)
            if fp_intrinsic in ['fp_cvt_l_s', 'fp_cvt_lu_s', 'fp_cvt_d_s']:
                a = f"{{32'hffffffff, {a}}}"
                b = "64'b0"
                c = "64'b0"

            instance_name = f"{verilog_name}_cvfpu"
            value_wire = f"{verilog_name}_value"
            status_wire = f"{verilog_name}_status"

            # Determine value width based on operation type
            has_flags = node.data.get('has_flags', True)
            value_bits = node.data.get('value_bits', 32)

            # Check if this is a multi-cycle operation (div/sqrt)
            is_multi_cycle = node.data.get('multi_cycle', False)
            latency_cycles = node.data.get('latency_cycles', 1)

            # Get the instruction enable signal from the node's instruction field
            # This is set by graph_merger for instruction-specific nodes
            instr_name = node.data.get('instruction')
            if instr_name:
                instr_enable_for_status = f"{instr_name}_enable"
            else:
                instr_enable_for_status = None

            # Track this cvfpu instance for exception flag handling
            # Store (status_wire, verilog_name, instruction_enable)
            if not hasattr(self, 'cvfpu_status_wires'):
                self.cvfpu_status_wires = []
            self.cvfpu_status_wires.append((status_wire, verilog_name, instr_enable_for_status))

            # Declare value wire for cvfpu output
            if value_wire not in self.declared_names:
                self.declarations += f"    wire [{value_bits - 1}:0] {value_wire};\n"
                self.declared_names.add(value_wire)

            # Declare status wire
            if status_wire not in self.declared_names:
                self.declarations += f"    wire [4:0] {status_wire};\n"
                self.declared_names.add(status_wire)

            if is_multi_cycle:
                # Multi-cycle FP operation (div/sqrt) - needs handshaking
                self.comb_logic += f"    // FP {fp_intrinsic} using cvfpu (multi-cycle, {latency_cycles} cycles)\n"

                # Get the instruction enable signal from the node's instruction field
                # This is set by graph_merger for instruction-specific nodes
                # The instruction enable signal is always generated by the decoder
                instr_name = node.data.get('instruction')
                if instr_name:
                    # Sanitize instruction name (e.g., fp/fdivs -> fp_fdivs)
                    sanitized_instr = self._sanitize_identifier(instr_name)
                    instr_enable = f"{sanitized_instr}_enable"
                else:
                    # No instruction info - this shouldn't happen for properly built graphs
                    # but we need a fallback for edge cases
                    instr_enable = "1'b1"

                # Declare ready and valid signals for handshaking
                ready_wire = f"{verilog_name}_ready"
                valid_wire = f"{verilog_name}_valid"

                if ready_wire not in self.declared_names:
                    self.declarations += f"    wire {ready_wire};\n"
                    self.declared_names.add(ready_wire)
                if valid_wire not in self.declared_names:
                    self.declarations += f"    wire {valid_wire};\n"
                    self.declared_names.add(valid_wire)

                # Declare latched result register for multi-cycle ops
                value_reg = f"{verilog_name}_value_reg"
                status_reg = f"{verilog_name}_status_reg"
                if value_reg not in self.declared_names:
                    self.declarations += f"    reg [{value_bits - 1}:0] {value_reg};\n"
                    self.declared_names.add(value_reg)
                if status_reg not in self.declared_names:
                    self.declarations += f"    reg [4:0] {status_reg};\n"
                    self.declared_names.add(status_reg)

                # Declare operation in-flight register
                in_flight_reg = f"{verilog_name}_in_flight"
                if in_flight_reg not in self.declared_names:
                    self.declarations += f"    reg {in_flight_reg};\n"
                    self.declared_names.add(in_flight_reg)

                # Generate request signal: we want to start when instruction matches, not in-flight, not just completed
                # The !valid condition prevents restarting on the completion cycle
                request_wire = f"{verilog_name}_request"
                if request_wire not in self.declared_names:
                    self.declarations += f"    wire {request_wire};\n"
                    self.declared_names.add(request_wire)
                self.comb_logic += f"    assign {request_wire} = {instr_enable} && !{in_flight_reg} && !{valid_wire};\n"

                # Start signal: handshake completes when both request and ready are high
                # This is used to latch in_flight on the next clock edge
                start_wire = f"{verilog_name}_start"
                if start_wire not in self.declared_names:
                    self.declarations += f"    wire {start_wire};\n"
                    self.declared_names.add(start_wire)
                self.comb_logic += f"    assign {start_wire} = {request_wire} && {ready_wire};\n"

                # Pack result - use fresh CVFPU outputs when valid fires, latched registers otherwise
                # This is critical: on the completion cycle, the latched regs haven't updated yet
                if has_flags:
                    self.comb_logic += f"    // Packed result: fresh when valid, latched otherwise\n"
                    self.comb_logic += f"    assign {verilog_name} = {valid_wire} ? {{{status_wire}, {value_wire}}} : {{{status_reg}, {value_reg}}};\n"
                else:
                    self.comb_logic += f"    assign {verilog_name} = {valid_wire} ? {value_wire} : {value_reg};\n"

                # Generate stall signal for processor
                # Stall when we have a pending request or operation is in flight, BUT NOT when valid
                stall_wire = f"{verilog_name}_stall"
                if stall_wire not in self.declared_names:
                    self.declarations += f"    wire {stall_wire};\n"
                    self.declared_names.add(stall_wire)
                # Stall when:
                # - We have a request pending (waiting for CVFPU handshake or handshake just completed)
                # - Operation is in flight (waiting for completion)
                # - BUT NOT when valid fires - we want PC to advance on completion cycle
                self.comb_logic += f"    assign {stall_wire} = ({request_wire} || {in_flight_reg}) && !{valid_wire};\n"

                # Track multi-cycle FP stall signals for global stall
                if not hasattr(self, 'fp_multicycle_stall_wires'):
                    self.fp_multicycle_stall_wires = []
                self.fp_multicycle_stall_wires.append(stall_wire)

                # Track info for modifying frf_write_enable
                if not hasattr(self, 'fp_multicycle_info'):
                    self.fp_multicycle_info = []
                self.fp_multicycle_info.append({
                    'instr_enable': instr_enable,
                    'valid_wire': valid_wire,
                    'in_flight_reg': in_flight_reg,
                    'stall_wire': stall_wire
                })

                # Sequential logic to latch result and track in-flight
                self.seq_logic += f"\n    // Multi-cycle FP {fp_intrinsic} result latching\n"
                self.seq_logic += f"    always @(posedge clk) begin\n"
                self.seq_logic += f"        if (reset) begin\n"
                self.seq_logic += f"            {in_flight_reg} <= 1'b0;\n"
                self.seq_logic += f"            {value_reg} <= {value_bits}'b0;\n"
                self.seq_logic += f"            {status_reg} <= 5'b0;\n"
                self.seq_logic += f"        end else begin\n"
                self.seq_logic += f"            if ({start_wire}) begin\n"
                self.seq_logic += f"                {in_flight_reg} <= 1'b1;\n"
                self.seq_logic += f"            end else if ({valid_wire} && {in_flight_reg}) begin\n"
                self.seq_logic += f"                {in_flight_reg} <= 1'b0;\n"
                self.seq_logic += f"                {value_reg} <= {value_wire};\n"
                self.seq_logic += f"                {status_reg} <= {status_wire};\n"
                self.seq_logic += f"            end\n"
                self.seq_logic += f"        end\n"
                self.seq_logic += f"    end\n"

                # Rounding mode: use explicitly passed value from ISA file
                # Note: valid_i is connected to request_wire (not start_wire) because CVFPU's
                # ready_o only goes high when valid_i is asserted. The handshake completes
                # when both valid_i and ready_o are high (which is our start_wire).
                # Rounding mode must be in canonical IEEE 754 encoding (000=RNE, 001=RTZ, 010=RDN, 011=RUP, 100=RMM)
                if rounding_mode_ref is not None:
                    # Use explicitly passed rounding mode from ISA file
                    rnd_mode = rounding_mode_ref
                else:
                    # Fallback for operations without rounding mode (comparisons, etc.)
                    rnd_mode = "3'b000"

                params = f".WIDTH({fpu_width}), .FP_FORMAT({fp_format})"
                if src_fp_format is not None:
                    params += f", .SRC_FP_FORMAT({src_fp_format})"
                inst_str = f"""cvfpu_simple #({params}) {instance_name} (
        .clk_i(clk),
        .rst_ni(~reset),
        .a_i({a}),
        .b_i({b}),
        .c_i({c}),
        .op_select_i(5'd{op_select}),
        .rnd_mode_i({rnd_mode}),
        .valid_i({request_wire}),
        .ready_o({ready_wire}),
        .result_o({value_wire}),
        .status_o({status_wire}),
        .valid_o({valid_wire})
    );"""
            else:
                # Combinational FP operation - single cycle
                self.comb_logic += f"    // FP {fp_intrinsic} using cvfpu (combinational)\n"

                # Pack {flags, value} into the result wire if operation has flags
                if has_flags:
                    self.comb_logic += f"    // Packed result: {{flags[4:0], value[{value_bits - 1}:0]}}\n"
                    self.comb_logic += f"    assign {verilog_name} = {{{status_wire}, {value_wire}}};\n"
                else:
                    # No flags - result is just the value
                    self.comb_logic += f"    assign {verilog_name} = {value_wire};\n"

                # Rounding mode: use explicitly passed value from ISA file
                # Must be in canonical IEEE 754 encoding (000=RNE, 001=RTZ, 010=RDN, 011=RUP, 100=RMM)
                if rounding_mode_ref is not None:
                    rnd_mode = rounding_mode_ref
                else:
                    # Fallback for operations without rounding mode
                    rnd_mode = "3'b000"

                params = f".WIDTH({fpu_width}), .FP_FORMAT({fp_format})"
                if src_fp_format is not None:
                    params += f", .SRC_FP_FORMAT({src_fp_format})"
                inst_str = f"""cvfpu_simple #({params}) {instance_name} (
        .clk_i(clk),
        .rst_ni(~reset),
        .a_i({a}),
        .b_i({b}),
        .c_i({c}),
        .op_select_i(5'd{op_select}),
        .rnd_mode_i({rnd_mode}),
        .valid_i(1'b1),
        .ready_o(),
        .result_o({value_wire}),
        .status_o({status_wire}),
        .valid_o()
    );"""
            self.module_instantiations.append(inst_str)

        else:
            # Unknown FP operation - generate placeholder
            self.comb_logic += f"    // Unknown FP operation: {fp_intrinsic}\n"
            self.comb_logic += f"    assign {verilog_name} = 32'h7FC00000;  // qNaN placeholder\n"

    def _generate_array_access_logic(self, node: Node):
        """Generate logic for array access nodes."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Skip write nodes - they're handled in sequential logic, not combinational
        if node.data.get('access_mode') == 'write':
            return

        # Handle superseded nodes (read ports that have been shared with other reads)
        # These should be assigned from the shared read port instead of accessing memory directly
        superseded_by = node.data.get('superseded_by')
        if superseded_by:
            # This read port has been shared with others via address muxing
            # Generate an assignment from the shared port
            shared_port_name = self._sanitize_identifier(superseded_by)

            # Check if the shared port has been declared
            if shared_port_name not in self.declared_names:
                # Declare the shared port wire
                bit_width = node.data.get('bit_width', 32)
                if bit_width > 1:
                    self.wire_declarations.append({
                        'name': shared_port_name,
                        'bit_width': bit_width
                    })
                else:
                    self.wire_declarations.append({
                        'name': shared_port_name,
                        'bit_width': 1
                    })
                self.declared_names.add(shared_port_name)

            # Generate assignment: superseded_rd = shared_port
            # Note: All shared reads get the same value since they're muxed by address
            self.comb_logic += f"    // Read port shared via {superseded_by}\n"
            self.comb_logic += f"    assign {verilog_name} = {shared_port_name};\n"
            return

        # Skip array_access nodes that are memory write targets (not read sources)
        # Memory write targets like dmem[addr]_wr should NOT generate array read logic
        # We can identify these because they access a memory but use a non-address as index
        # (e.g., dmem[sw_r2] where sw_r2 is data, not an address)
        # The proper way to detect this: check if this node's sanitized name appears
        # in a memory write statement in sequential logic, but that's complex.
        # Simpler heuristic: if node.id contains [xxx]_wr and xxx is not 'addr', skip it
        if '_wr' in node.id and node.data.get('type') == 'array_access':
            # Check if the array being accessed is a memory
            for edge in node.incoming_edges:
                source_node = edge.source
                if source_node.data.get('is_memory', False):
                    # This is accessing a memory with _wr suffix - likely a write target
                    # But we need to distinguish dmem[addr]_wr (invalid read) from dmem_addr_wr (valid wire)
                    # The key is that dmem[addr]_wr would be an array_access node
                    # while dmem_addr_wr would be a regular wire
                    # Since this IS an array_access node with _wr accessing memory, skip it
                    return

        # Use incoming edges to get array and index - edges are more reliable than expression data
        # because optimizations like wire alias propagation update edges but not expression metadata
        if node.incoming_edges and len(node.incoming_edges) >= 2:
            array_edge = None
            index_edge = None

            # Use edge position information to identify array (position=0) and index (position=1)
            edges_by_position = {}
            for edge in node.incoming_edges:
                pos = edge.data.get('position')
                if pos is not None:
                    edges_by_position[pos] = edge

            # Check for explicit type='array_base' edge (most reliable for pipelined graphs)
            # This handles cases where the array base has been replaced by a pipeline register
            # Sort edges for deterministic iteration (incoming_edges is a set)
            for edge in sorted(node.incoming_edges, key=lambda e: e.source.id):
                if edge.data.get('type') == 'array_base':
                    array_edge = edge
                    break

            # Position-based assignment (if not already found via type='array_base')
            if not array_edge and 0 in edges_by_position:
                # For position=0 (array), prefer base memory over instruction-specific variants
                candidates = [e for e in node.incoming_edges if e.data.get('position') == 0]
                # Prefer non-instruction-prefixed memories (e.g., 'mem' over 'SH_mem_rd')
                base_mem = None
                for e in candidates:
                    src_id = e.source.id
                    if not any(prefix in src_id for prefix in ['ADD_', 'ADDI_', 'AND_', 'ANDI_', 'AUIPC_',
                                                                 'BEQ_', 'BGE_', 'BGEU_', 'BLT_', 'BLTU_', 'BNE_',
                                                                 'JAL_', 'JALR_', 'LB_', 'LBU_', 'LH_', 'LHU_',
                                                                 'LUI_', 'LW_', 'OR_', 'ORI_', 'SB_', 'SH_',
                                                                 'SLL_', 'SLLI_', 'SLT_', 'SLTI_', 'SLTIU_', 'SLTU_',
                                                                 'SRA_', 'SRAI_', 'SRL_', 'SRLI_', 'SUB_', 'SW_',
                                                                 'XOR_', 'XORI_']):
                        base_mem = e
                        break
                array_edge = base_mem if base_mem else candidates[0]

            # Collect ALL index edges - there may be multiple from different instructions
            # Look for edges with type='array_index' OR position=1
            # Typically there's one after upstream muxing, but collision splits can leave multiple
            index_edges = [e for e in node.incoming_edges
                          if e.data.get('type') == 'array_index' or e.data.get('position') == 1]
            if index_edges:
                if len(index_edges) == 1:
                    index_edge = index_edges[0]
                else:
                    # Multiple index edges from collision-split groups.
                    # Each group outputs the correct address when active, 0 otherwise.
                    # OR-combine them (non-overlapping enables). Sort for determinism.
                    sorted_edges = sorted(index_edges, key=lambda e: e.source.id)
                    index_edge = sorted_edges[0]
                    or_parts = []
                    for e in sorted_edges:
                        part_name = self.node_id_to_name.get(
                            e.source.id, self._sanitize_identifier(e.source.id))
                        or_parts.append(part_name)
                    node.data['_combined_index_name'] = ' | '.join(or_parts)

            # Fallback to old heuristic-based approach if position info not available
            if not array_edge or not index_edge:
                # Identify which edge is the array and which is the index
                # Priority order for array: is_memory > isa_state > bit_slice/var/array_access
                # Priority order for index: literal > everything else
                for edge in node.incoming_edges:
                    source_type = edge.source.data.get('type')
                    is_memory = edge.source.data.get('is_memory', False)

                    # Identify array edge (highest priority: is_memory)
                    if not array_edge and is_memory:
                        array_edge = edge
                    # Identify index edge
                    elif not index_edge and source_type == 'literal':
                        index_edge = edge

                # Second pass for isa_state/mem (lower priority than is_memory)
                for edge in node.incoming_edges:
                    source_type = edge.source.data.get('type')

                    if edge == array_edge or edge == index_edge:
                        continue

                    if not array_edge and source_type.startswith('isa_state'):
                        array_edge = edge

                # Third pass: assign remaining edges
                for edge in node.incoming_edges:
                    source_type = edge.source.data.get('type')

                    if edge == array_edge or edge == index_edge:
                        continue  # Already assigned

                    # If no array found yet, try other types
                    if not array_edge and source_type in ['bit_slice', 'var', 'array_access', 'concatenation']:
                        array_edge = edge
                    # Assign remaining edge to index if not yet assigned
                    elif not index_edge:
                        index_edge = edge

            # If we found both, use them
            if array_edge and index_edge:
                array_name = self.node_id_to_name.get(array_edge.source.id, self._sanitize_identifier(array_edge.source.id))
                index_source = index_edge.source

                # Instruction buffer wide fetch: concatenate consecutive bytes from byte memory
                if node.data.get('is_buffer_fetch', False):
                    index_name = self.node_id_to_name.get(index_source.id, self._sanitize_identifier(index_source.id))
                    fetch_width = node.data.get('bit_width', 8)
                    mem_elem_width = array_edge.source.data.get('bit_width', 8)
                    if fetch_width > mem_elem_width:
                        n_bytes = fetch_width // mem_elem_width
                        byte_reads = [f"{array_name}[{index_name} + {i}]" for i in range(n_bytes)]
                        concat = ", ".join(reversed(byte_reads))
                        self.comb_logic += f"    assign {verilog_name} = {{{concat}}};\n"
                    else:
                        self.comb_logic += f"    assign {verilog_name} = {array_name}[{index_name}];\n"
                    return

                # Check if this is actually a bit-select (not array access)
                # If the array is not a memory and index is a literal, use direct bit index
                is_array_memory = array_edge.source.data.get('is_memory', False)
                is_index_literal = index_edge.source.data.get('type') == 'literal'

                if not is_array_memory and is_index_literal:
                    # Bit-select: use literal value directly
                    index_value = index_source.data.get('value', index_source.id)
                    self.comb_logic += f"    assign {verilog_name} = {array_name}[{index_value}];\n"
                else:
                    # Array access: use signal name for index
                    # Check for OR-combined index from multiple collision-split groups
                    combined = node.data.get('_combined_index_name')
                    if combined:
                        index_name = combined
                    else:
                        index_name = self.node_id_to_name.get(index_source.id, self._sanitize_identifier(index_source.id))

                    # Check if the index source needs a wire declaration (for aspect variables)
                    if index_source.id not in self.node_id_to_name:
                        # Check if this is a var node from an aspect that wasn't processed
                        if index_source.data.get('type') == 'var':
                            # Check if there's an incoming edge that gives us the actual value
                            for edge in index_source.incoming_edges:
                                if edge.data.get('type') == 'assignment':
                                    source_name = self._get_node_verilog_ref(edge.source)
                                    index_name = source_name
                                    self.node_id_to_name[index_source.id] = source_name
                                    break
                            else:
                                # No assignment edge found, declare the wire
                                if index_name not in self.declared_names:
                                    bit_width = index_source.data.get('bit_width', 32)
                                    self.wire_declarations.append({
                                        'name': index_name,
                                        'bit_width': bit_width
                                    })
                                    self.declared_names.add(index_name)
                                    self.node_id_to_name[index_source.id] = index_name

                    # For memory arrays, scale the index based on element size
                    # (e.g., if memory stores 32-bit words and index is byte address, divide by 4)
                    # BUT: only scale for memories with byte addressing (like imem/dmem),
                    # NOT for register files which use register indices
                    # Note: Check memory_declarations even if is_array_memory is False,
                    # because the flag may not be set on nodes from merged graphs
                    is_known_memory = array_name in self.memory_declarations

                    # Track externalized memory reads for external port connections
                    if array_name in self.externalized_memories:
                        mem_info = self.memory_declarations[array_name]
                        # Extract port-specific name for multi-port support
                        # Use node.id (like umem[pc]_rd) to get port name like umem_pc
                        ext_port_name = self._extract_memory_port_name(node.id, array_name)
                        self.memory_read_ports.append({
                            'mem': array_name,
                            'port_name': node.id,  # Original node ID for port extraction
                            'ext_port_name': ext_port_name,  # Computed external port name
                            'addr_signal': index_name,
                            'data_width': mem_info['bit_width'],
                            'addr_width': mem_info['addr_width']
                        })
                        # For externalized memories, read from port-specific external response
                        self.comb_logic += f"    assign {verilog_name} = {ext_port_name}_read_resp_data;\n"
                        return  # Skip normal array access generation

                    if is_known_memory:
                        mem_info = self.memory_declarations[array_name]
                        element_bits = mem_info['bit_width']

                        # Skip if width not yet inferred
                        if element_bits is not None:
                            bytes_per_element = element_bits // 8
                        else:
                            # Width not inferred yet, skip memory-specific logic
                            bytes_per_element = 1

                        # Only scale if this is a 'mem' type memory (type 'isa_state mem')
                        # Register files (rf) use register indices, not scaled addresses
                        mem_port_width = self._get_mem_port_width(array_name)

                        # Infer access width for 'mem' type memories
                        if mem_port_width > 0:
                            # Try to infer access width from outgoing edges (what uses this data)
                            # Collect ALL widths and take maximum (shared nodes may have multiple users)
                            # Skip concatenation_input edges: those represent this read being
                            # ONE PART of a wider concat — the concat's width is the sum of
                            # all parts, not the width of this individual port read.
                            target_widths = []
                            for out_edge in node.outgoing_edges:
                                if out_edge.data.get('type') == 'concatenation_input':
                                    continue
                                target_width = out_edge.target.data.get('bit_width')
                                if target_width is not None and target_width > 0:
                                    target_widths.append(target_width)

                            access_width = None
                            if target_widths:
                                access_width = max(target_widths)

                            # Fallback to node's own bit_width if no outgoing edge found
                            if access_width is None:
                                access_width = node.data.get('bit_width')

                            # Clamp access_width to ISA model's port width.
                            # Individual memory reads should not exceed port_width;
                            # wider values are assembled via concatenation of
                            # multiple port_width-sized reads.
                            if mem_port_width > 0:
                                if access_width is not None:
                                    access_width = min(access_width, mem_port_width)
                                else:
                                    access_width = mem_port_width

                            memory_width = element_bits

                        if bytes_per_element > 1 and mem_port_width > 0 and self._is_physical_memory(array_name):
                            # Need to scale index: divide byte address by bytes_per_element
                            # Only for physical memories (imem, dmem, umem) that use byte addressing
                            # Register files like CSR use direct register indexing
                            import math
                            shift_bits = int(math.log2(bytes_per_element))

                            # Generate selection logic if access differs from memory width
                            # This includes:
                            # 1. Narrow accesses (access_width < memory_width): byte/halfword from word
                            # 2. Wide accesses (access_width > memory_width): multi-cycle dual-word access
                            has_special_access = (access_width is not None and
                                                access_width != memory_width and
                                                access_width >= 8)



                            if has_special_access:
                                # Special access handling:
                                # - Narrow: byte/halfword selection from full word
                                # - Wide: multi-cycle dual-word read and merge

                                if access_width < memory_width:
                                    # NARROW ACCESS: Read full word and select portion
                                    word_wire_name = f"{verilog_name}_word"

                                    # Declare the word wire if not already declared
                                    # NOTE: We add directly to declarations string since this happens during comb logic generation
                                    # which is after _generate_declarations() has already processed wire_declarations list
                                    if word_wire_name not in self.declared_names:
                                        if memory_width > 1:
                                            self.declarations += f"    wire [{memory_width-1}:0] {word_wire_name};\n"
                                        else:
                                            self.declarations += f"    wire {word_wire_name};\n"
                                        self.declared_names.add(word_wire_name)

                                    # Read full word from memory
                                    # If index contains operators (mux), create intermediate wire
                                    # (iverilog doesn't support bit-select on expressions)
                                    actual_idx = index_name
                                    if '|' in index_name or '?' in index_name:
                                        idx_wire = f"{verilog_name}_idx"
                                        if idx_wire not in self.declared_names:
                                            self.declarations += f"    wire [31:0] {idx_wire};\n"
                                            self.declared_names.add(idx_wire)
                                        self.comb_logic += f"    assign {idx_wire} = {index_name};\n"
                                        actual_idx = idx_wire
                                    # Use MEM_BASE offset for physical memory addressing (imem, dmem)
                                    # but not for register files like CSR
                                    # Note: iverilog doesn't support bit-select on expressions, so create intermediate wire
                                    if self._is_physical_memory(array_name):
                                        adj_wire = f"{actual_idx}_adj"
                                        if adj_wire not in self.declared_names:
                                            self.declarations += f"    wire [31:0] {adj_wire};\n"
                                            self.declared_names.add(adj_wire)
                                        expr = self._get_zero_extended_expr(actual_idx)
                                        self.comb_logic += f"    assign {adj_wire} = {expr} - `MEM_BASE;\n"
                                        mem_idx = f"{adj_wire}[31:{shift_bits}]"
                                    else:
                                        mem_idx = f"{actual_idx}[31:{shift_bits}]"
                                    self.comb_logic += f"    assign {word_wire_name} = {array_name}[{mem_idx}];\n"

                                    # Generate selection logic based on access width
                                    # Check endianness for byte/halfword/word selection
                                    endianness = self._get_mem_endianness(array_name)
                                    import math
                                    byte_offset_bits = int(math.log2(memory_width // 8))  # 2 for 32-bit mem, 3 for 64-bit
                                    if access_width == 8:
                                        # Byte access - select byte within memory word
                                        hi_bit = byte_offset_bits - 1
                                        self.comb_logic += f"    assign {verilog_name} = "
                                        if endianness == 'big':
                                            max_val = (memory_width // 8) - 1
                                            max_bits = byte_offset_bits
                                            self.comb_logic += f"{word_wire_name}[({max_bits}'d{max_val} - {actual_idx}[{hi_bit}:0]) * 8 +: 8];\n"
                                        else:
                                            self.comb_logic += f"{word_wire_name}[{actual_idx}[{hi_bit}:0] * 8 +: 8];\n"
                                    elif access_width == 16:
                                        # Halfword from memory word
                                        hi_bit = byte_offset_bits - 1
                                        self.comb_logic += f"    assign {verilog_name} = "
                                        if endianness == 'big':
                                            max_val = (memory_width // 16) - 1
                                            max_bits = byte_offset_bits - 1
                                            self.comb_logic += f"{word_wire_name}[({max_bits}'d{max_val} - {actual_idx}[{hi_bit}:1]) * 16 +: 16];\n"
                                        else:
                                            self.comb_logic += f"{word_wire_name}[{actual_idx}[{hi_bit}:1] * 16 +: 16];\n"
                                    elif access_width == 32 and memory_width > 32:
                                        # 32-bit word from memory wider than 32 bits
                                        hi_bit = byte_offset_bits - 1
                                        self.comb_logic += f"    assign {verilog_name} = "
                                        if endianness == 'big':
                                            max_val = (memory_width // 32) - 1
                                            max_bits = byte_offset_bits - 2
                                            self.comb_logic += f"{word_wire_name}[({max_bits}'d{max_val} - {actual_idx}[{hi_bit}:2]) * 32 +: 32];\n"
                                        else:
                                            self.comb_logic += f"{word_wire_name}[{actual_idx}[{hi_bit}:2] * 32 +: 32];\n"
                                    else:
                                        # General narrow access: extract lower bits from full word
                                        # This handles PTE reads (54-bit from 64-bit memory) and similar
                                        self.comb_logic += f"    assign {verilog_name} = {word_wire_name}[{access_width-1}:0];\n"

                                    # Update node's bit_width to reflect actual narrow access
                                    # This ensures downstream nodes see the correct width
                                    node.data['bit_width'] = access_width

                                    # The wire was already declared with memory_width (32-bit)
                                    # We need to track that it's actually access_width bits
                                    # Store this info so we can fix the declaration
                                    if not hasattr(self, 'narrow_access_wires'):
                                        self.narrow_access_wires = {}
                                    self.narrow_access_wires[verilog_name] = access_width

                                else:
                                    # WIDE ACCESS or POTENTIALLY UNALIGNED:
                                    # access_width > memory_width: always needs dual-word
                                    # access_width == 16/32 with equal memory: may need dual-word if unaligned
                                    #
                                    # Generate dual-word read with merge logic
                                    # WARNING: This requires 2 read ports in the same cycle!
                                    if access_width > memory_width:
                                        print(f"  [MULTI-CYCLE] {verilog_name}: {access_width}-bit access from {memory_width}-bit memory")
                                        print(f"                 Requires dual-{memory_width}-bit reads (2 ports or 2 cycles)")
                                    else:
                                        print(f"  [PORT WARNING] {verilog_name}: {access_width}-bit access may require 2 simultaneous reads from {array_name}")
                                        print(f"                 If memory is constrained to 1 read port, unaligned accesses will fail")

                                    word0_wire = f"{verilog_name}_word0"
                                    word1_wire = f"{verilog_name}_word1"

                                    # Declare intermediate wires for two consecutive words
                                    if word0_wire not in self.declared_names:
                                        self.wire_declarations.append({
                                            'name': word0_wire,
                                            'bit_width': memory_width
                                        })
                                        self.declared_names.add(word0_wire)

                                    if word1_wire not in self.declared_names:
                                        self.wire_declarations.append({
                                            'name': word1_wire,
                                            'bit_width': memory_width
                                        })
                                        self.declared_names.add(word1_wire)

                                    # Read two consecutive memory locations
                                    # If index contains operators (mux), create intermediate wire
                                    wide_actual_idx = index_name
                                    if '|' in index_name or '?' in index_name:
                                        wide_idx_wire = f"{verilog_name}_idx"
                                        if wide_idx_wire not in self.declared_names:
                                            self.declarations += f"    wire [31:0] {wide_idx_wire};\n"
                                            self.declared_names.add(wide_idx_wire)
                                        self.comb_logic += f"    assign {wide_idx_wire} = {index_name};\n"
                                        wide_actual_idx = wide_idx_wire
                                    # Use MEM_BASE offset for physical memory addressing (imem, dmem)
                                    # Note: iverilog doesn't support bit-select on expressions, so create intermediate wire
                                    if self._is_physical_memory(array_name):
                                        adj_wire = f"{wide_actual_idx}_adj"
                                        if adj_wire not in self.declared_names:
                                            self.declarations += f"    wire [31:0] {adj_wire};\n"
                                            self.declared_names.add(adj_wire)
                                        expr = self._get_zero_extended_expr(wide_actual_idx)
                                        self.comb_logic += f"    assign {adj_wire} = {expr} - `MEM_BASE;\n"
                                        mem_idx = f"{adj_wire}[31:{shift_bits}]"
                                    else:
                                        mem_idx = f"{wide_actual_idx}[31:{shift_bits}]"
                                    self.comb_logic += f"    assign {word0_wire} = {array_name}[{mem_idx}];\n"
                                    self.comb_logic += f"    assign {word1_wire} = {array_name}[{mem_idx} + 1];\n"

                                    # Generate merge logic based on byte offset
                                    merged_wire = f"{verilog_name}_merged"
                                    if merged_wire not in self.declared_names:
                                        self.wire_declarations.append({
                                            'name': merged_wire,
                                            'bit_width': 64  # Two 32-bit words concatenated
                                        })
                                        self.declared_names.add(merged_wire)

                                    # Concatenate word1:word0 to create merged value
                                    self.comb_logic += f"    assign {merged_wire} = {{{word1_wire}, {word0_wire}}};\n"
                                    # Extract access_width bits starting at byte offset * 8
                                    import math
                                    wide_byte_hi = int(math.log2(memory_width // 8)) - 1 if memory_width >= 16 else 0
                                    self.comb_logic += f"    assign {verilog_name} = {merged_wire}[{wide_actual_idx}[{wide_byte_hi}:0] * 8 +: {access_width}];\n"
                            else:
                                # Full-width access or width unknown - direct assignment
                                # If index contains operators (mux), create intermediate wire
                                # (iverilog doesn't support bit-select on expressions)
                                if '|' in index_name or '?' in index_name:
                                    # Create intermediate wire for the mux result
                                    # Add directly to declarations string (since _generate_declarations() already ran)
                                    idx_wire = f"{verilog_name}_idx"
                                    if idx_wire not in self.declared_names:
                                        self.declarations += f"    wire [31:0] {idx_wire};\n"
                                        self.declared_names.add(idx_wire)
                                    self.comb_logic += f"    assign {idx_wire} = {index_name};\n"
                                    # Use MEM_BASE offset for physical memory addressing (imem, dmem)
                                    # Note: iverilog doesn't support bit-select on expressions, so create intermediate wire
                                    if self._is_physical_memory(array_name):
                                        adj_wire = f"{idx_wire}_adj"
                                        if adj_wire not in self.declared_names:
                                            self.declarations += f"    wire [31:0] {adj_wire};\n"
                                            self.declared_names.add(adj_wire)
                                        expr = self._get_zero_extended_expr(idx_wire)
                                        self.comb_logic += f"    assign {adj_wire} = {expr} - `MEM_BASE;\n"
                                        mem_idx = f"{adj_wire}[31:{shift_bits}]"
                                    else:
                                        mem_idx = f"{idx_wire}[31:{shift_bits}]"
                                    self.comb_logic += f"    assign {verilog_name} = {array_name}[{mem_idx}];\n"
                                else:
                                    # Use MEM_BASE offset for physical memory addressing (imem, dmem)
                                    # Note: iverilog doesn't support bit-select on expressions, so create intermediate wire
                                    if self._is_physical_memory(array_name):
                                        adj_wire = f"{index_name}_adj"
                                        if adj_wire not in self.declared_names:
                                            self.declarations += f"    wire [31:0] {adj_wire};\n"
                                            self.declared_names.add(adj_wire)
                                        expr = self._get_zero_extended_expr(index_name)
                                        self.comb_logic += f"    assign {adj_wire} = {expr} - `MEM_BASE;\n"
                                        mem_idx = f"{adj_wire}[31:{shift_bits}]"
                                    else:
                                        mem_idx = f"{index_name}[31:{shift_bits}]"
                                    self.comb_logic += f"    assign {verilog_name} = {array_name}[{mem_idx}];\n"

                                # Also assign _word wire if it was declared (for downstream slice operations)
                                # The _word wire may have been declared by _declare_narrow_load_word_wire()
                                # using a different width inference path, so we need to connect it here
                                word_wire_name = f"{verilog_name}_word"
                                if word_wire_name in self.declared_names:
                                    self.comb_logic += f"    assign {word_wire_name} = {verilog_name};\n"
                        elif mem_port_width > 0 and bytes_per_element == 1:
                            # 8-bit memory (bytes_per_element == 1)
                            # Check if access is wider than memory
                            if access_width is not None and memory_width is not None and access_width > memory_width:
                                # Wide access from narrow memory
                                if node.data.get('is_buffer_fetch', False):
                                    # Instruction buffer fetch: concatenate consecutive bytes
                                    # into a wide fetch word (e.g., 4 bytes for 32-bit fetch)
                                    n_bytes = access_width // memory_width
                                    byte_reads = []
                                    for i in range(n_bytes):
                                        byte_reads.append(f"{array_name}[{index_name} + {i}]")
                                    # Little-endian: byte 0 in LSB
                                    concat = ", ".join(reversed(byte_reads))
                                    self.comb_logic += f"    assign {verilog_name} = {{{concat}}};\n"
                                else:
                                    # General wide access - needs multi-cycle handling
                                    print(f"  [MULTI-CYCLE] {verilog_name}: {access_width}-bit access from {memory_width}-bit memory")
                                    print(f"                 Requires multiple {memory_width}-bit reads (2-4 ports or 2-4 cycles)")
                                    self.comb_logic += f"    assign {verilog_name} = {array_name}[{index_name}];  // WARNING: Multi-cycle access needed\n"
                            else:
                                # Normal 8-bit access
                                self.comb_logic += f"    assign {verilog_name} = {array_name}[{index_name}];\n"
                        else:
                            # Check for RF bypass first, otherwise normal access
                            if not self._generate_rf_access_with_bypass(verilog_name, array_name, index_name):
                                self.comb_logic += f"    assign {verilog_name} = {array_name}[{index_name}];\n"
                    else:
                        # Check for RF bypass first, otherwise normal access
                        if not self._generate_rf_access_with_bypass(verilog_name, array_name, index_name):
                            self.comb_logic += f"    assign {verilog_name} = {array_name}[{index_name}];\n"
                return

        # Fallback: use expression data (for cases where edges aren't available)
        expr = node.data.get('expression', {})
        if expr.get('type') == 'array_access':
            array_name = self._get_verilog_name_for_expression(expr.get('target', {}))
            index_name = self._get_verilog_name_for_expression(expr.get('index', {}))
            # Check for RF bypass first, otherwise normal access
            if not self._generate_rf_access_with_bypass(verilog_name, array_name, index_name):
                # Apply byte-to-word address conversion only for physical memories (imem, dmem, umem)
                # Register files like CSR use direct register indexing, not byte addressing
                mem_port_width = self._get_mem_port_width(array_name)
                is_physical = self._is_physical_memory(array_name)
                if mem_port_width >= 8 and is_physical:
                    bytes_per_word = mem_port_width // 8
                    if bytes_per_word > 1:
                        import math
                        shift_bits = int(math.log2(bytes_per_word))
                        # Use MEM_BASE offset for physical memory addressing (imem, dmem)
                        # Note: iverilog doesn't support bit-select on expressions, so create intermediate wire
                        adj_wire = f"{index_name}_adj"
                        if adj_wire not in self.declared_names:
                            self.declarations += f"    wire [31:0] {adj_wire};\n"
                            self.declared_names.add(adj_wire)
                        expr = self._get_zero_extended_expr(index_name)
                        self.comb_logic += f"    assign {adj_wire} = {expr} - `MEM_BASE;\n"
                        mem_idx = f"{adj_wire}[31:{shift_bits}]"
                        self.comb_logic += f"    assign {verilog_name} = {array_name}[{mem_idx}];\n"
                    else:
                        # 8-bit physical memory - apply MEM_BASE offset
                        adj_wire = f"{index_name}_adj"
                        if adj_wire not in self.declared_names:
                            self.declarations += f"    wire [31:0] {adj_wire};\n"
                            self.declared_names.add(adj_wire)
                        expr = self._get_zero_extended_expr(index_name)
                        self.comb_logic += f"    assign {adj_wire} = {expr} - `MEM_BASE;\n"
                        self.comb_logic += f"    assign {verilog_name} = {array_name}[{adj_wire}];\n"
                else:
                    # Non-physical memories (CSR, etc.) use direct indexing
                    self.comb_logic += f"    assign {verilog_name} = {array_name}[{index_name}];\n"

    def _get_memory_write_signals(self, memory_name: str):
        """
        Find signals needed for memory write-to-read forwarding structurally.

        Uses the shared write port's structure to find write enable, address, and data.

        Args:
            memory_name: Name of the memory (e.g., 'rf', 'dmem')

        Returns:
            Tuple of (write_enable_name, write_addr_name, write_data_name) or None if not found.
        """
        # Find the shared write port for this memory
        shared_wr = self.graph.nodes.get(f'{memory_name}_shared_wr')
        if not shared_wr or shared_wr.data.get('type') != 'memory_write_port':
            return None

        # Get write enable from the combined_write_enable field
        # Look for the valid-gated version first
        enable_name = shared_wr.data.get('combined_write_enable')
        write_enable = None
        if enable_name:
            gated_enable = self.graph.nodes.get(f'{enable_name}_valid_gated')
            if gated_enable:
                write_enable = self.node_id_to_name.get(gated_enable.id, self._sanitize_identifier(gated_enable.id))
            else:
                enable_node = self.graph.nodes.get(enable_name)
                if enable_node:
                    write_enable = self.node_id_to_name.get(enable_node.id, self._sanitize_identifier(enable_node.id))

        if not write_enable:
            return None

        # Get write address and data from incoming edges
        write_addr = None
        write_data = None
        for edge in shared_wr.incoming_edges:
            edge_type = edge.data.get('type')
            source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
            if edge_type == 'write_address':
                write_addr = source_name
            elif edge_type == 'write_data':
                write_data = source_name

        if not write_addr or not write_data:
            return None

        return (write_enable, write_addr, write_data)

    def _generate_rf_access_with_bypass(self, verilog_name: str, array_name: str, index_name: str) -> bool:
        """
        Generate memory read with write-to-read forwarding if applicable.

        When a memory has write_read_fwd enabled, we need to forward the write data
        if the address being read is being written in the same cycle (write-first semantics).

        Returns:
            True if forwarding logic was generated, False otherwise (caller should generate normal access).
        """
        # Check if this memory has write_read_fwd enabled
        memory_node = self.graph.nodes.get(array_name)
        if not memory_node or not memory_node.data.get('write_read_fwd', False):
            return False

        # Get the write signals structurally from the shared write port
        write_signals = self._get_memory_write_signals(array_name)
        if not write_signals:
            return False

        write_enable, write_addr, write_data = write_signals

        # Generate forwarding logic:
        # assign mem_rd = (write_enable && write_addr == index) ? write_data : mem[index];
        # Note: The write_enable should already be gated for special cases (e.g., x0 in RISC-V)
        self.comb_logic += f"    // Write-to-read forwarding: forward write data if reading same address being written\n"
        self.comb_logic += f"    assign {verilog_name} = ({write_enable} && {write_addr} == {index_name}) ? {write_data} : {array_name}[{index_name}];\n"

        return True

    def _generate_bit_slice_concatenations(self):
        """Generate concatenation assignments for variables that were split into bit-slice sub-wires.

        When ISA code writes to bit slices of a variable:
            var[31:16] = high_part;
            var[15:0] = low_part;
        The generator creates separate wires var_31_16 and var_15_0 with assign statements,
        but the original 'var' wire is never assigned. This method detects such cases and
        generates: assign var = {var_31_16, var_15_0};
        """
        import re

        # Build a set of all declared wire/reg names and their widths
        declared_wires = {}
        for decl in self.wire_declarations + self.reg_declarations:
            name = decl.get('name')
            if name:
                declared_wires[name] = decl.get('bit_width', decl.get('width', 1))

        # Find wires matching the pattern NAME_H_L (bit-slice sub-wires)
        slice_pattern = re.compile(r'^(.+)_(\d+)_(\d+)$')
        # Group slices by base name
        slice_groups = {}  # base_name -> list of (high, low, full_name)

        for name in declared_wires:
            m = slice_pattern.match(name)
            if m:
                base_name = m.group(1)
                high = int(m.group(2))
                low = int(m.group(3))
                if high > low:  # Valid bit range
                    if base_name not in slice_groups:
                        slice_groups[base_name] = []
                    slice_groups[base_name].append((high, low, name))

        # For each base name that is also a declared wire, check if it's unassigned
        for base_name, slices in sorted(slice_groups.items()):
            if base_name not in declared_wires:
                continue

            # Check if base_name is already assigned in combinational or sequential logic
            # Look for "assign base_name =" or "base_name <=" patterns
            assign_pattern = f"assign {base_name} ="
            nba_pattern = f"{base_name} <="
            if assign_pattern in self.comb_logic or nba_pattern in self.seq_logic:
                continue

            # Sort slices by high bit descending to build concatenation in correct order
            slices.sort(key=lambda s: s[0], reverse=True)

            # Verify slices cover the full width contiguously
            expected_width = declared_wires[base_name]
            total_width = sum(h - l + 1 for h, l, _ in slices)
            if total_width != expected_width:
                continue

            # Verify contiguous coverage (no gaps or overlaps)
            # After sorting by high bit descending: [31:16], [15:0]
            contiguous = True
            for i in range(len(slices) - 1):
                if slices[i][1] != slices[i + 1][0] + 1:
                    contiguous = False
                    break
            # Also check that the lowest slice starts at 0 and highest ends at expected_width-1
            if slices[-1][1] != 0 or slices[0][0] != expected_width - 1:
                contiguous = False

            if not contiguous:
                continue

            # Generate concatenation: assign base = {slice_31_16, slice_15_0};
            slice_names = [s[2] for s in slices]
            concat = ', '.join(slice_names)
            self.comb_logic += f"    assign {base_name} = {{{concat}}};\n"

    def _generate_bit_slice_assign(self, dest_name, source_name, high, low, source_width):
        """Generate a bit-slice assignment, handling the case where the bit indices
        refer to the DESTINATION position but the source is narrower.

        For example, ISA says: var[31:16] = dmem[addr]
        The [31:16] is the destination slice. If dmem reads are 16-bit,
        we should assign the full 16-bit source, not try source[31:16] which is always 0.
        """
        slice_width = high - low + 1
        if high == low:
            # Single bit access
            if high == 0 and source_width == 1:
                return f"    assign {dest_name} = {source_name};\n"
            elif high >= source_width:
                # Bit index beyond source width - this is a destination index
                # Assign full source (should be 1-bit)
                return f"    assign {dest_name} = {source_name};\n"
            else:
                return f"    assign {dest_name} = {source_name}[{high}];\n"
        else:
            # Range access
            if high >= source_width:
                # Destination slice indices exceed source width
                # The slice width should match the source width
                if slice_width == source_width:
                    # Perfect match - just assign full source
                    return f"    assign {dest_name} = {source_name};\n"
                elif slice_width < source_width:
                    # Need to take lower bits of source
                    return f"    assign {dest_name} = {source_name}[{slice_width-1}:0];\n"
                else:
                    # Slice wider than source - zero-extend
                    pad = slice_width - source_width
                    return f"    assign {dest_name} = {{{{{pad}{{1'b0}}}}, {source_name}}};\n"
            else:
                # Normal case - indices within source width
                return f"    assign {dest_name} = {source_name}[{high}:{low}];\n"

    def _generate_bit_slice_logic(self, node: Node):
        """Generate logic for bit slice nodes."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Mark as assigned to prevent duplicate assignment from _generate_variable_assignments
        self.assigned_signals.add(verilog_name)

        # Handle ILA-style bit_slice nodes (type directly in data, not in expression)
        if node.data.get('type') == 'bit_slice':
            target_name = None
            source_node = None

            # Check if this bit_slice references a memory read (for byte offset selection)
            # In that case, use the memory read's address index signal from the expression
            memory_read_id = node.data.get('memory_read_node')
            if memory_read_id:
                # The expression operand contains the index signal name (e.g., "dmem_ea_rd_idx")
                expr = node.data.get('expression', {})
                if expr.get('type') == 'bit_slice':
                    operand = expr.get('operand', {})
                    if operand.get('type') == 'identifier':
                        operand_name = operand.get('name')
                        target_name = self.node_id_to_name.get(operand_name, self._sanitize_identifier(operand_name))

            # Fall back to getting target from incoming edge
            if not target_name and node.incoming_edges:
                # Sort incoming edges for deterministic selection
                first_edge = sorted(node.incoming_edges, key=lambda e: e.source.id)[0]
                source_node = first_edge.source
                target_name = self.node_id_to_name.get(first_edge.source.id, self._sanitize_identifier(first_edge.source.id))

            if not target_name:
                print(f"Warning: bit_slice node {node.id} has no incoming edges")
                return

            # Check if target is an instruction-prefixed ISA state that needs to be redirected
            # to the shared _rd value (e.g., mret_satp -> satp_rd)
            if source_node:
                # Check if this looks like an instruction-prefixed ISA state
                known_prefixes = self._get_instruction_prefixes()
                for prefix in known_prefixes:
                    if target_name.startswith(prefix):
                        base_name = target_name[len(prefix):]
                        # Check if this is an ISA state that has a shared _rd register
                        shared_rd_name = f"{base_name}_rd"
                        if shared_rd_name in self.node_id_to_name or shared_rd_name in self.graph.nodes:
                            # Redirect to shared _rd value
                            target_name = self.node_id_to_name.get(shared_rd_name, shared_rd_name)
                        break

            # Get source width to handle 1-bit signals specially
            # For 1-bit signals, [0] subscript is illegal in Verilog
            source_width = 1
            if source_node:
                source_width = source_node.data.get('bit_width', 1)
            # Also check wire/reg declarations
            # Declarations may use 'width' or 'bit_width' key
            for decl in self.wire_declarations + self.reg_declarations:
                if decl.get('name') == target_name:
                    decl_width = decl.get('width') or decl.get('bit_width')
                    if decl_width is not None:
                        source_width = decl_width
                    break

            # Get bit range from node data (support multiple field name variations)
            # IMPORTANT: check value is not None, not just key existence, since
            # memory_access_transform may set keys with None values
            if node.data.get('high_bit') is not None and node.data.get('low_bit') is not None:
                high, low = node.data['high_bit'], node.data['low_bit']
                if source_width == 1:
                    # 1-bit signal - cannot index regardless of requested bit position
                    self.comb_logic += f"    assign {verilog_name} = {target_name};\n"
                elif high == low:
                    self.comb_logic += f"    assign {verilog_name} = {target_name}[{high}];\n"
                else:
                    self.comb_logic += f"    assign {verilog_name} = {target_name}[{high}:{low}];\n"
                return
            elif node.data.get('high') is not None and node.data.get('low') is not None:
                high, low = node.data['high'], node.data['low']
                if source_width == 1:
                    self.comb_logic += f"    assign {verilog_name} = {target_name};\n"
                elif high == low:
                    self.comb_logic += f"    assign {verilog_name} = {target_name}[{high}];\n"
                else:
                    self.comb_logic += f"    assign {verilog_name} = {target_name}[{high}:{low}];\n"
                return
            elif 'bitslice' in node.data:
                high, low = node.data['bitslice']
                if source_width == 1:
                    self.comb_logic += f"    assign {verilog_name} = {target_name};\n"
                elif high == low:
                    self.comb_logic += f"    assign {verilog_name} = {target_name}[{high}];\n"
                else:
                    self.comb_logic += f"    assign {verilog_name} = {target_name}[{high}:{low}];\n"
                return
            # If no bit range in node.data, fall through to check expression

        # Handle expression-style bit_slice nodes (legacy format)
        expr = node.data.get('expression', {})
        if expr.get('type') == 'bit_slice':
            target_name = None

            # Check if this bit_slice references a memory read (for byte offset selection)
            # In that case, use the expression operand (memory read's index signal)
            memory_read_id = node.data.get('memory_read_node')
            if memory_read_id:
                operand = expr.get('operand', {})
                if operand.get('type') == 'identifier':
                    operand_name = operand.get('name')
                    target_name = self.node_id_to_name.get(operand_name, self._sanitize_identifier(operand_name))

            # Fall back to incoming edge to get the actual target (more reliable after merging)
            if not target_name and node.incoming_edges:
                # Find the edge with type 'bit_access' (from ISA parser)
                for edge in sorted(node.incoming_edges, key=lambda e: e.source.id):
                    if edge.data.get('type') == 'bit_access':
                        target_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                        break
                # If no bit_access edge found, use first incoming edge (sorted for determinism)
                if not target_name and node.incoming_edges:
                    first_edge = sorted(node.incoming_edges, key=lambda e: e.source.id)[0]
                    target_name = self.node_id_to_name.get(first_edge.source.id, self._sanitize_identifier(first_edge.source.id))

            # Fallback to expression if no edges available
            if not target_name:
                target_name = self._get_verilog_name_for_expression(expr['target'])

            # Check if target is an instruction-prefixed ISA state that needs to be redirected
            # to the shared _rd value (e.g., mret_satp -> satp_rd)
            known_prefixes = self._get_instruction_prefixes()
            for prefix in known_prefixes:
                if target_name.startswith(prefix):
                    base_name = target_name[len(prefix):]
                    shared_rd_name = f"{base_name}_rd"
                    if shared_rd_name in self.node_id_to_name or shared_rd_name in self.graph.nodes:
                        target_name = self.node_id_to_name.get(shared_rd_name, shared_rd_name)
                    break

            high, low = expr['range']

            # Check if slicing from a memory read that has a wider _word version
            # This happens when instruction fetch (32-bit) uses 64-bit memory
            # In this case, the base signal is never assigned - use _word instead
            # IMPORTANT: Only apply this for memory reads (nodes ending in _rd), not regular variables
            word_target = f"{target_name}_word"
            if word_target in self.declared_names and target_name.endswith('_rd'):
                # Use the _word version for accessing the actual memory data
                target_name = word_target

            # Get source width to handle 1-bit signals specially
            source_width = None  # None means "unknown"
            # Check source node first (more reliable for externalized memory reads)
            if node.incoming_edges:
                first_edge = sorted(node.incoming_edges, key=lambda e: e.source.id)[0]
                source_node = first_edge.source
                if source_node and source_node.data.get('bit_width') is not None:
                    source_width = source_node.data.get('bit_width')
            # Also check wire/reg declarations (overrides if declared width is available)
            # Declarations may use 'width' or 'bit_width' key
            for decl in self.wire_declarations + self.reg_declarations:
                if decl.get('name') == target_name:
                    decl_width = decl.get('width') or decl.get('bit_width')
                    if decl_width is not None:
                        source_width = decl_width
                    break

            if source_width is not None and source_width == 1:
                # Reliably detected as 1-bit - cannot index, just assign directly
                self.comb_logic += f"    assign {verilog_name} = {target_name};\n"
            elif high == low:
                self.comb_logic += f"    assign {verilog_name} = {target_name}[{high}];\n"
            else:
                self.comb_logic += f"    assign {verilog_name} = {target_name}[{high}:{low}];\n"
            return  # Expression-style bit_slice handled

    def _generate_zero_extend_logic(self, node: Node):
        """Generate logic for zero extend nodes."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))
        # Check bit_width first (set by memory_access_transform), then target_width
        target_width = node.data.get('bit_width', node.data.get('target_width', 32))

        # Get input from incoming edge (sorted for determinism)
        input_name = None
        input_width = None
        if node.incoming_edges:
            first_edge = sorted(node.incoming_edges, key=lambda e: e.source.id)[0]
            input_name = self.node_id_to_name.get(first_edge.source.id, self._sanitize_identifier(first_edge.source.id))
            input_width = self._infer_bit_width(first_edge.source)

        if input_name:
            # Generate: assign output = {{(target_width - input_width){1'b0}}, input};
            if input_width and input_width < target_width:
                pad_width = target_width - input_width

                # Check if this node is marked for NaN-boxing (set during graph construction
                # for FP values being extended to wider FP registers)
                use_nan_boxing = node.data.get('nan_box', False)
                # Check if this node needs dual versions (used by both FP and integer registers)
                use_nan_box_dual = node.data.get('nan_box_dual', False)
                # Check if this node is marked for sign-extension (signed FP->int conversions)
                use_sign_extend = node.data.get('sign_extend', False)

                if use_nan_boxing:
                    # NaN-boxing: upper bits are all 1s
                    self.comb_logic += f"    assign {verilog_name} = {{{{{pad_width}{{1'b1}}}}, {input_name}}};\n"
                elif use_nan_box_dual:
                    # Dual mode: generate zero-extended version (for integer RF)
                    self.comb_logic += f"    assign {verilog_name} = {{{{{pad_width}{{1'b0}}}}, {input_name}}};\n"
                    # Also generate NaN-boxed version (for FP FRF)
                    nan_boxed_name = f"{verilog_name}_nan_boxed"
                    # Add wire declaration for NaN-boxed version if not already declared
                    # Note: Add directly to declarations string since _generate_declarations() has already run
                    if nan_boxed_name not in self.declared_names:
                        self.declarations += f"    wire [{target_width-1}:0] {nan_boxed_name};\n"
                        self.declared_names.add(nan_boxed_name)
                    self.comb_logic += f"    assign {nan_boxed_name} = {{{{{pad_width}{{1'b1}}}}, {input_name}}};\n"
                elif use_sign_extend:
                    # Sign-extension: replicate sign bit
                    sign_bit = f"{input_name}[{input_width - 1}]"
                    self.comb_logic += f"    assign {verilog_name} = {{{{{pad_width}{{{sign_bit}}}}}, {input_name}}};\n"
                else:
                    # Standard zero-extension
                    self.comb_logic += f"    assign {verilog_name} = {{{{{pad_width}{{1'b0}}}}, {input_name}}};\n"
            else:
                # No extension needed
                self.comb_logic += f"    assign {verilog_name} = {input_name};\n"

    def _generate_sign_extend_logic(self, node: Node):
        """Generate logic for sign extend nodes."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))
        # Check bit_width first (set by memory_access_transform), then target_width
        target_width = node.data.get('bit_width', node.data.get('target_width', 32))

        # Get input from incoming edge (sorted for determinism)
        input_name = None
        input_width = None
        if node.incoming_edges:
            first_edge = sorted(node.incoming_edges, key=lambda e: e.source.id)[0]
            input_name = self.node_id_to_name.get(first_edge.source.id, self._sanitize_identifier(first_edge.source.id))
            input_width = self._infer_bit_width(first_edge.source)

        if input_name:
            # Generate: assign output = {{(target_width - input_width){input[input_width-1]}}, input};
            if input_width and input_width < target_width:
                pad_width = target_width - input_width
                sign_bit = f"{input_name}[{input_width-1}]"
                self.comb_logic += f"    assign {verilog_name} = {{{{{pad_width}{{{sign_bit}}}}}, {input_name}}};\n"
            else:
                # No extension needed
                self.comb_logic += f"    assign {verilog_name} = {input_name};\n"

    def _generate_literal_logic(self, node: Node):
        """Generate logic for literal nodes."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))
        value = node.data.get('value', 0)
        bit_width = self._infer_bit_width(node)
        # Safeguard: ensure the width can actually represent the value
        if isinstance(value, int) and value > 0:
            min_width = value.bit_length()
            if bit_width < min_width:
                bit_width = min_width

        # Ensure the literal wire is declared (combinational logic generation runs after declarations)
        if verilog_name not in self.declared_names:
            bw = bit_width or 32
            self.declarations += f"    wire [{bw-1}:0] {verilog_name};\n"
            self.declared_names.add(verilog_name)

        self.comb_logic += f"    assign {verilog_name} = {bit_width}'d{value};\n"

    def _generate_sized_literal_logic(self, node: Node):
        """Generate logic for sized literal nodes."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))
        width = node.data.get('width', 1)

        # Ensure declaration exists
        if verilog_name not in self.declared_names:
            self.declarations += f"    wire [{width-1}:0] {verilog_name};\n"
            self.declared_names.add(verilog_name)
        if 'bits' in node.data:
            bits = node.data.get('bits', '0')
            self.comb_logic += f"    assign {verilog_name} = {width}'b{bits};\n"
        elif 'hex_digits' in node.data:
            hex_digits = node.data.get('hex_digits', '0')
            self.comb_logic += f"    assign {verilog_name} = {width}'h{hex_digits};\n"
        elif 'dec_digits' in node.data:
            dec_digits = node.data.get('dec_digits', '0')
            self.comb_logic += f"    assign {verilog_name} = {width}'d{dec_digits};\n"
        else:
            value = node.data.get('value', 0)
            self.comb_logic += f"    assign {verilog_name} = {width}'d{value};\n"

    def _generate_concatenation_logic(self, node: Node):
        """Generate logic for concatenation nodes."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Use incoming edges to get the actual source nodes
        # This handles cases where wire aliases have been removed
        if node.incoming_edges:
            # Deduplicate edges by position - when merging graphs, duplicate edges
            # at the same position can be created (e.g., mtime_hi and mtime_hi_rd both at pos 0)
            # Keep only one edge per position, preferring _rd suffixed nodes (post-split state)
            position_to_edge = {}
            for edge in sorted(node.incoming_edges, key=lambda e: (e.data.get('position', 0), e.source.id)):
                pos = edge.data.get('position', 0)
                if pos not in position_to_edge:
                    position_to_edge[pos] = edge
                else:
                    # Prefer _rd suffixed nodes (they're the properly split architectural state)
                    existing_edge = position_to_edge[pos]
                    if edge.source.id.endswith('_rd') and not existing_edge.source.id.endswith('_rd'):
                        position_to_edge[pos] = edge

            parts = []
            for pos in sorted(position_to_edge.keys()):
                edge = position_to_edge[pos]
                source_node = edge.source
                source_type = source_node.data.get('type')

                # For sized literals and regular literals, generate inline values
                if source_type == 'sized_literal':
                    width = source_node.data.get('width', 1)
                    if 'bits' in source_node.data:
                        bits = source_node.data.get('bits', '0')
                        source_name = f"{width}'b{bits}"
                    elif 'hex_digits' in source_node.data:
                        hex_digits = source_node.data.get('hex_digits', '0')
                        source_name = f"{width}'h{hex_digits}"
                    elif 'dec_digits' in source_node.data:
                        dec_digits = source_node.data.get('dec_digits', '0')
                        source_name = f"{width}'d{dec_digits}"
                    else:
                        value = source_node.data.get('value', 0)
                        source_name = f"{width}'d{value}"
                elif source_type == 'literal':
                    value = source_node.data.get('value', 0)
                    # Infer bit width from node if available, otherwise default to 32
                    bit_width = self._infer_bit_width(source_node)
                    # Safeguard: ensure the width can represent the value
                    if isinstance(value, int) and value > 0:
                        min_width = value.bit_length()
                        if bit_width < min_width:
                            bit_width = min_width
                    source_name = f"{bit_width}'d{value}"
                else:
                    # For other nodes, use the node_id_to_name mapping
                    source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))

                parts.append(source_name)
            concat_expr = ', '.join(parts)
            self.comb_logic += f"    assign {verilog_name} = {{{concat_expr}}};\n"
        else:
            # Fallback to expression-based generation
            expr = node.data.get('expression', {})
            if expr.get('type') == 'concatenation':
                expr_parts = expr.get('parts', [])
                parts = []
                for sub_expr in expr_parts:
                    part_name = self._get_verilog_name_for_expression(sub_expr)
                    parts.append(part_name)

                concat_expr = ', '.join(parts)
                self.comb_logic += f"    assign {verilog_name} = {{{concat_expr}}};\n"

    def _generate_repetition_logic(self, node: Node):
        """Generate logic for repetition nodes."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Use incoming edge to get the actual source node
        if node.incoming_edges:
            source_edge = sorted(node.incoming_edges, key=lambda e: e.source.id)[0]  # Repetition has one source
            source_name = self.node_id_to_name.get(source_edge.source.id, self._sanitize_identifier(source_edge.source.id))
            expr = node.data.get('expression', {})
            count = expr.get('count', 1) if expr.get('type') == 'repetition' else 1
            self.comb_logic += f"    assign {verilog_name} = {{{count}{{{source_name}}}}};\n"
        else:
            # Fallback to expression-based generation
            expr = node.data.get('expression', {})
            if expr.get('type') == 'repetition':
                count = expr.get('count', 1)
                inner_expr = expr.get('expression', {})
                inner_name = self._get_verilog_name_for_expression(inner_expr)
                self.comb_logic += f"    assign {verilog_name} = {{{count}{{{inner_name}}}}};\n"

    def _generate_ternary_logic(self, node: Node):
        """Generate logic for ternary conditional nodes."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Skip array ternaries - they're handled in sequential logic
        if self._is_array_ternary(node):
            return

        # Check if this is a unified node with a collision mux assignment
        # Unified nodes from collision resolution should just be assigned from the mux output
        assignment_edge = None
        for edge in node.incoming_edges:
            if edge.data.get('type') == 'assignment' and '_collision_mux' in edge.source.id:
                assignment_edge = edge
                break

        if assignment_edge:
            # This is a unified collision node - just assign from the collision mux
            source_name = self.node_id_to_name.get(assignment_edge.source.id,
                                                   self._sanitize_identifier(assignment_edge.source.id))
            self.comb_logic += f"    assign {verilog_name} = {source_name};\n"
            return

        # Use incoming edges if available (more reliable after wire alias propagation)
        if node.incoming_edges and len(node.incoming_edges) == 3:
            # Find condition, true_value, false_value from edges
            # The condition edge typically comes from a comparison or variable
            # The true/false edges come from other expressions
            cond_edge = None
            true_edge = None
            false_edge = None

            # Try to identify edges based on their source types or edge types
            for edge in node.incoming_edges:
                source_type = edge.source.data.get('type')
                edge_type = edge.data.get('type')

                # Use edge type if available (more reliable)
                if edge_type == 'ternary_condition':
                    cond_edge = edge
                elif edge_type == 'ternary_true':
                    true_edge = edge
                elif edge_type == 'ternary_false':
                    false_edge = edge
                # Fallback to source type matching
                elif source_type in ['var', 'comparison', 'logical_and', 'logical_or'] and not cond_edge:
                    cond_edge = edge
                # The other two are true and false branches
                elif not true_edge:
                    true_edge = edge
                elif not false_edge:
                    false_edge = edge

            if cond_edge and true_edge and false_edge:
                # Use the condition source from the edge (handles both group-specific and instruction-specific)
                cond_source_id = cond_edge.source.id
                cond_name = self.node_id_to_name.get(cond_source_id, self._sanitize_identifier(cond_source_id))

                # Check if condition is an instruction enable that should be expanded
                # to include all group members. Use group_members metadata from true/false branches.
                cond_id_lower = cond_source_id.lower()
                if cond_id_lower.endswith('_enable'):
                    # Extract instruction name from enable (e.g., "lb_enable" -> "lb")
                    cond_instr = cond_id_lower[:-7]  # Remove "_enable"

                    # Check if true or false branch has group_members that includes this instruction
                    for branch_edge in [true_edge, false_edge]:
                        group_members = branch_edge.source.data.get('group_members', [])
                        if cond_instr in group_members and len(group_members) > 1:
                            # Expand to all group member enables
                            enable_parts = []
                            for member in group_members:
                                en = f"{member}_enable"
                                if en in self.node_id_to_name:
                                    enable_parts.append(self.node_id_to_name[en])
                                else:
                                    enable_parts.append(en)
                            if len(enable_parts) > 1:
                                cond_name = '(' + ' || '.join(sorted(enable_parts)) + ')'
                            break

                true_name = self.node_id_to_name.get(true_edge.source.id, self._sanitize_identifier(true_edge.source.id))
                false_name = self.node_id_to_name.get(false_edge.source.id, self._sanitize_identifier(false_edge.source.id))

                self.comb_logic += f"    assign {verilog_name} = {cond_name} ? {true_name} : {false_name};\n"
                return

        # Handle incomplete ternaries (ILA pattern: missing true branch)
        # Many ILA ternaries only have condition + false branch
        if node.incoming_edges and len(node.incoming_edges) == 2:
            cond_edge = None
            false_edge = None

            for edge in node.incoming_edges:
                edge_type = edge.data.get('type')
                if edge_type == 'ternary_condition':
                    cond_edge = edge
                elif edge_type == 'ternary_false':
                    false_edge = edge

            if cond_edge and false_edge:
                # Use 0 as default for missing true branch
                node_width = node.data.get('bit_width', 32)
                cond_name = self.node_id_to_name.get(cond_edge.source.id, self._sanitize_identifier(cond_edge.source.id))
                false_name = self.node_id_to_name.get(false_edge.source.id, self._sanitize_identifier(false_edge.source.id))
                self.comb_logic += f"    assign {verilog_name} = {cond_name} ? {node_width}'d0 : {false_name};\n"
                return

        # Fallback to expression-based generation
        expr = node.data.get('expression', {})
        if expr.get('type') == 'ternary_op':
            cond = expr.get('condition', {})
            true_expr = expr.get('if_true', {})
            false_expr = expr.get('if_false', {})

            cond_name = self._get_verilog_name_for_expression(cond)
            true_name = self._get_verilog_name_for_expression(true_expr)
            false_name = self._get_verilog_name_for_expression(false_expr)

            self.comb_logic += f"    assign {verilog_name} = {cond_name} ? {true_name} : {false_name};\n"

    def _generate_comparison_logic(self, node: Node):
        """Generate logic for comparison nodes (from instruction decode)."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # For comparison nodes, we want to overwrite any existing assignment
        # (comparisons take priority over arithmetic operations for signals like xxx_ne_0)
        if verilog_name in self.assigned_signals:
            # Remove the old assignment from comb_logic and regenerate
            # Find and remove the line containing this assignment
            lines = self.comb_logic.split('\n')
            filtered_lines = [line for line in lines if not (f"assign {verilog_name} =" in line)]
            self.comb_logic = '\n'.join(filtered_lines)

        self.assigned_signals.add(verilog_name)

        # Get the comparison operation from node data
        operation = node.data.get('operation', '==')

        # Use incoming edges to get operands
        operands = []
        for edge in node.incoming_edges:
            if edge.data.get('type') in ['decode_input', 'operand', 'left_operand', 'right_operand']:
                # Use _get_node_verilog_ref to properly inline literal values
                source_name = self._get_node_verilog_ref(edge.source)
                operands.append(source_name)

        if len(operands) == 2:
            self.comb_logic += f"    assign {verilog_name} = {operands[0]} {operation} {operands[1]};\n"
            return
        elif len(operands) == 1:
            # Single operand comparison (e.g., field == value)
            # The value should be in the expression data
            expr = node.data.get('expression', {})
            if expr.get('type') in ['binary_op', 'comparison']:
                left_expr = expr.get('left', {})
                right_expr = expr.get('right', {})

                # One operand is the incoming edge, the other is from expression
                if right_expr.get('type') == 'literal':
                    value = right_expr.get('value')
                    # Infer bit width from the LEFT operand (the incoming edge source)
                    source_node = node.incoming_edges.__iter__().__next__().source

                    # Check if left expression is a bit_slice
                    if left_expr.get('type') == 'bit_slice':
                        # Check if the incoming operand is already a bit_slice node
                        source_node = node.incoming_edges.__iter__().__next__().source
                        if source_node.data.get('type') == 'bit_slice' or source_node.data.get('expression', {}).get('type') == 'bit_slice':
                            # The operand is already the bit slice we need, use it directly
                            bit_width = self._infer_bit_width(source_node)
                            formatted_value = self._format_literal_value(value, bit_width)
                            self.comb_logic += f"    assign {verilog_name} = {operands[0]} {operation} {formatted_value};\n"
                            return

                        # Get the bit range
                        if 'range' in left_expr:
                            high, low = left_expr['range']
                        else:
                            high = left_expr.get('high', {}).get('value', 0) if isinstance(left_expr.get('high'), dict) else left_expr.get('high', 0)
                            low = left_expr.get('low', {}).get('value', 0) if isinstance(left_expr.get('low'), dict) else left_expr.get('low', 0)

                        # Use the incoming operand (which is the actual signal) and slice it
                        if high == low:
                            bit_slice_str = f"{operands[0]}[{high}]"
                        else:
                            bit_slice_str = f"{operands[0]}[{high}:{low}]"

                        # Infer bit width for the literal
                        bit_width = (high - low + 1) if high >= low else 1
                        formatted_value = self._format_literal_value(value, bit_width)
                        self.comb_logic += f"    assign {verilog_name} = {bit_slice_str} {operation} {formatted_value};\n"
                        return
                    else:
                        # Not a bit slice, use full operand
                        bit_width = self._infer_bit_width(source_node)
                        formatted_value = self._format_literal_value(value, bit_width)
                        self.comb_logic += f"    assign {verilog_name} = {operands[0]} {operation} {formatted_value};\n"
                        return

        # Fallback to expression-based generation
        expr = node.data.get('expression', {})
        if expr.get('type') == 'binary_op':
            left_expr = expr.get('left', {})
            right_expr = expr.get('right', {})

            # SPECIAL CASE: If left is a bit_slice and we have an incoming edge,
            # use the incoming edge's source instead of the expression's identifier
            # This handles ILA graphs where decode comparisons reference non-existent 'instr' nodes
            if left_expr.get('type') == 'bit_slice' and right_expr.get('type') == 'literal':
                if node.incoming_edges and len(list(node.incoming_edges)) > 0:
                    # Get the first incoming edge (should be the instruction word, sorted for determinism)
                    edge = sorted(node.incoming_edges, key=lambda e: e.source.id)[0]
                    if edge.data.get('type') in ['decode_input', 'operand', 'left_operand', 'right_operand']:
                        operand_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))

                        # Check if the incoming operand is already a bit_slice node
                        if edge.source.data.get('type') == 'bit_slice' or edge.source.data.get('expression', {}).get('type') == 'bit_slice':
                            # The operand is already the bit slice we need, use it directly
                            bit_width = self._infer_bit_width(edge.source)
                            value = right_expr.get('value')
                            formatted_value = self._format_literal_value(value, bit_width)
                            self.comb_logic += f"    assign {verilog_name} = {operand_name} {operation} {formatted_value};\n"
                            return

                        # Get bit range
                        if 'range' in left_expr:
                            high, low = left_expr['range']
                        else:
                            high = left_expr.get('high', {}).get('value', 0) if isinstance(left_expr.get('high'), dict) else left_expr.get('high', 0)
                            low = left_expr.get('low', {}).get('value', 0) if isinstance(left_expr.get('low'), dict) else left_expr.get('low', 0)

                        # Generate bit slice on the operand
                        if high == low:
                            bit_slice_str = f"{operand_name}[{high}]"
                        else:
                            bit_slice_str = f"{operand_name}[{high}:{low}]"

                        # Get value and bit width
                        value = right_expr.get('value')
                        bit_width = (high - low + 1) if high >= low else 1
                        formatted_value = self._format_literal_value(value, bit_width)

                        self.comb_logic += f"    assign {verilog_name} = {bit_slice_str} {operation} {formatted_value};\n"
                        return

            # If the left bit_slice target has no 'type' (e.g., after memory externalization
            # removed the instr node), fall back to incoming edges for the source signal
            if (left_expr.get('type') == 'bit_slice' and right_expr.get('type') == 'literal' and
                    'type' not in left_expr.get('target', {})):
                # Find source signal via incoming edges
                for edge in node.incoming_edges:
                    source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                    # Get bit range from left expression
                    if 'range' in left_expr:
                        high, low = left_expr['range']
                    else:
                        high = left_expr.get('high', {}).get('value', 0) if isinstance(left_expr.get('high'), dict) else left_expr.get('high', 0)
                        low = left_expr.get('low', {}).get('value', 0) if isinstance(left_expr.get('low'), dict) else left_expr.get('low', 0)
                    if high == low:
                        bit_slice_str = f"{source_name}[{high}]"
                    else:
                        bit_slice_str = f"{source_name}[{high}:{low}]"
                    bit_width = (high - low + 1) if high >= low else 1
                    value = right_expr.get('value')
                    formatted_value = self._format_literal_value(value, bit_width)
                    self.comb_logic += f"    assign {verilog_name} = {bit_slice_str} {operation} {formatted_value};\n"
                    return

            left_name = self._get_verilog_name_for_expression(left_expr)
            right_name = self._get_verilog_name_for_expression(right_expr)
            # Check if right is a literal, and if so, try to infer the correct bit width
            if right_expr.get('type') == 'literal' and left_expr.get('type') == 'identifier':
                # Try to find the node for left operand to infer its bit width
                left_id = left_expr['name']
                if left_id in self.graph.nodes:
                    left_node = self.graph.nodes[left_id]
                    bit_width = self._infer_bit_width(left_node)
                    value = right_expr.get('value')
                    formatted_value = self._format_literal_value(value, bit_width)
                    self.comb_logic += f"    assign {verilog_name} = {left_name} {operation} {formatted_value};\n"
                    return
            self.comb_logic += f"    assign {verilog_name} = {left_name} {operation} {right_name};\n"

    def _generate_logical_logic(self, node: Node):
        """Generate logic for logical AND/OR/NOT nodes (from instruction decode)."""
        # Skip inlined nodes (their expressions are inlined at point of use)
        if hasattr(self, 'inlined_nodes') and node.id in self.inlined_nodes:
            return

        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Determine operation type
        node_type = node.data.get('type')

        # Handle NOT (unary) operation
        if node_type == 'logical_not':
            # NOT has a single operand
            if node.incoming_edges:
                for edge in node.incoming_edges:
                    if edge.data.get('type') in ['logic_input', 'operand']:
                        source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                        self.comb_logic += f"    assign {verilog_name} = !{source_name};\n"
                        return
            print(f"Warning: Could not generate logic for logical_not node {node.id} - no operand edge found")
            return

        # Handle AND/OR (binary) operations
        operation = '&&' if node_type == 'logical_and' else '||'

        # Use incoming edges to get operands
        if node.incoming_edges:
            operands = []
            # Sort edges by operand_index then source.id for determinism while preserving semantic order
            for edge in sorted(node.incoming_edges, key=lambda e: (e.data.get('operand_index', 0), e.source.id)):
                if edge.data.get('type') in ['logic_input', 'operand']:
                    source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                    operands.append(source_name)

            if len(operands) >= 2:
                # Join all operands with the operation (order preserved from sorted edges above)
                expr_str = f" {operation} ".join(operands)
                self.comb_logic += f"    assign {verilog_name} = {expr_str};\n"
                return
            elif len(operands) == 1:
                # Single operand - just pass through
                self.comb_logic += f"    assign {verilog_name} = {operands[0]};\n"
                return

        # Fallback: generate based on node data
        print(f"Warning: Could not generate logic for {node_type} node {node.id} - insufficient edge information")

    def _generate_cam_lookup_logic(self, node: Node):
        """Generate logic for CAM (Content-Addressable Memory) lookup nodes.

        CAM lookup generates parallel comparators for each way, producing a
        bitmask of matching entries.

        For a fully associative CAM with N entries:
            match[i] = (cam[i] == key) for each i in 0..N-1
            result = {match[N-1], ..., match[1], match[0]}
        """
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Skip if already assigned
        if verilog_name in self.assigned_signals:
            return
        self.assigned_signals.add(verilog_name)

        cam_info = node.data.get('cam_info', {})
        num_ways = cam_info.get('num_ways', 1)
        num_sets = cam_info.get('num_sets', 1)

        # Get key expression from incoming edge
        key_name = None
        cam_array_name = None
        set_idx_name = None

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type')
            if edge_type == 'cam_key':
                key_name = self._get_node_verilog_ref(edge.source)
            elif edge_type == 'cam_array':
                cam_array_name = self._get_node_verilog_ref(edge.source)
            elif edge_type == 'cam_set_index':
                set_idx_name = self._get_node_verilog_ref(edge.source)

        if not key_name or not cam_array_name:
            print(f"Warning: CAM lookup {node.id} missing key or cam array")
            return

        # Generate comment
        self.comb_logic += f"\n    // CAM lookup: {cam_array_name}@[{key_name}]\n"

        if num_ways == 1:
            # Direct-mapped: single comparison
            if set_idx_name:
                self.comb_logic += f"    assign {verilog_name} = ({cam_array_name}[{set_idx_name}] == {key_name}) ? 1'b1 : 1'b0;\n"
            else:
                self.comb_logic += f"    assign {verilog_name} = ({cam_array_name} == {key_name}) ? 1'b1 : 1'b0;\n"
        else:
            # Fully associative or set-associative: parallel comparators
            # Declare the output wire for the CAM lookup result
            self.comb_logic += f"    wire [{num_ways-1}:0] {verilog_name};\n"

            # Generate match wire for each way
            match_wires = []
            for i in range(num_ways):
                match_wire = f"{verilog_name}_match_{i}"
                match_wires.append(match_wire)
                # Declare the match wire
                self.comb_logic += f"    wire {match_wire};\n"

            # Generate comparators
            for i in range(num_ways):
                if num_sets > 1 and set_idx_name:
                    # Set-associative: cam_array is 2D, index by [set][way]
                    self.comb_logic += f"    assign {match_wires[i]} = ({cam_array_name}[{set_idx_name}][{i}] == {key_name});\n"
                else:
                    # Fully associative: cam_array is 1D, index by [way]
                    # Use _rd suffix for reading from register array
                    cam_rd_name = f"{cam_array_name}_rd" if f"{cam_array_name}_rd" in self.node_id_to_name else cam_array_name
                    self.comb_logic += f"    assign {match_wires[i]} = ({cam_rd_name}[{i}] == {key_name});\n"

            # Concatenate match bits into result bitmask
            # {match[N-1], ..., match[1], match[0]}
            match_concat = ", ".join(reversed(match_wires))
            self.comb_logic += f"    assign {verilog_name} = {{{match_concat}}};\n"

    def _generate_builtin_call_logic(self, node: Node):
        """Generate logic for builtin function calls (ctz, clz).

        ctz (count trailing zeros): Returns index of lowest set bit, or width if all zeros.
        clz (count leading zeros): Returns count of leading zeros from MSB.

        For ctz, we generate a priority encoder:
            ctz(8'b00101000) = 3 (bit 3 is lowest set bit)
            ctz(8'b00000000) = 8 (no bits set, returns width)
        """
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Skip if already assigned
        if verilog_name in self.assigned_signals:
            return
        self.assigned_signals.add(verilog_name)

        builtin = node.data.get('builtin', 'ctz')
        operand_width = node.data.get('operand_width', 32)
        result_width = node.data.get('bit_width', 6)

        # Get operand from incoming edge
        operand_name = None
        for edge in node.incoming_edges:
            if edge.data.get('type') == 'builtin_operand':
                operand_name = self._get_node_verilog_ref(edge.source)
                break

        if not operand_name:
            print(f"Warning: Builtin {builtin} node {node.id} missing operand")
            return

        self.comb_logic += f"\n    // {builtin}({operand_name})\n"

        # Declare output wire for the builtin result
        self.comb_logic += f"    wire [{result_width-1}:0] {verilog_name};\n"

        if builtin == 'ctz':
            # Generate priority encoder for ctz
            # Build cascaded ternary: op[0] ? 0 : op[1] ? 1 : ... : op[N-1] ? N-1 : N
            terms = []
            for i in range(operand_width):
                terms.append(f"{operand_name}[{i}] ? {result_width}'d{i}")
            terms.append(f"{result_width}'d{operand_width}")  # All zeros case

            # Build nested ternary (right-associative)
            expr = terms[-1]
            for i in range(len(terms) - 2, -1, -1):
                expr = f"({terms[i]} : {expr})"

            self.comb_logic += f"    assign {verilog_name} = {expr};\n"

        elif builtin == 'clz':
            # Generate priority encoder for clz (count leading zeros)
            # Check from MSB to LSB
            terms = []
            for i in range(operand_width - 1, -1, -1):
                leading_zeros = operand_width - 1 - i
                terms.append(f"{operand_name}[{i}] ? {result_width}'d{leading_zeros}")
            terms.append(f"{result_width}'d{operand_width}")  # All zeros case

            # Build nested ternary
            expr = terms[-1]
            for i in range(len(terms) - 2, -1, -1):
                expr = f"({terms[i]} : {expr})"

            self.comb_logic += f"    assign {verilog_name} = {expr};\n"

        else:
            print(f"Warning: Unknown builtin function {builtin}")

    def _generate_instruction_enable_logic(self, node: Node):
        """Generate logic for instruction enable nodes (from instruction decode)."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Instruction enable is typically driven by a single decode_enable edge,
        # optionally with decode_exclude edges for fusion mutual exclusion.
        if node.incoming_edges:
            enable_source = None
            exclude_sources = []
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'decode_enable':
                    enable_source = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                elif edge.data.get('type') == 'decode_exclude':
                    exclude_sources.append(self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id)))
            if enable_source:
                if exclude_sources:
                    excludes = ' && '.join(f"!{s}" for s in sorted(exclude_sources))
                    self.comb_logic += f"    assign {verilog_name} = {enable_source} && {excludes};\n"
                else:
                    self.comb_logic += f"    assign {verilog_name} = {enable_source};\n"
                return

        # Fallback: if no explicit edges, check node data
        print(f"Warning: Could not generate logic for instruction_enable node {node.id} - no decode_enable edge found")

    def _generate_byte_enable_mux_logic(self, node: Node):
        """Generate logic for combined byte enable mux nodes.

        These are created by memory_externalization when a memory has per-instruction
        byte enables (e.g., sb_byte_enable, sh_byte_enable for RISC-V).

        The mux selects the appropriate byte enable based on which store instruction
        is active, with full word write (all 1s) as the default.

        IMPORTANT: For pipelined designs, store byte enables must use Memory-stage
        enable signals, not Decode-stage signals. Memory writes occur in the Memory
        stage, so the byte enable selection must be synchronized with that stage.

        This method uses structural graph traversal to find the correct enable signals
        by looking at the memory write port's data mux select signals.
        """
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))
        bit_width = node.data.get('bit_width', 4)
        mux_inputs = node.data.get('mux_inputs', [])  # List of (enable_node_id, byte_enable_node_id)
        default_value = node.data.get('default_value', (1 << bit_width) - 1)

        if not mux_inputs:
            # No per-instruction byte enables, just output default (all 1s)
            self.comb_logic += f"    assign {verilog_name} = {bit_width}'h{default_value:x};\n"
            return

        # Find the write port that uses this byte_enable_mux
        # The write port node should have 'combined_byte_enable' pointing to this node
        data_mux_node = None
        for port_node in self.graph.nodes.values():
            if port_node.data.get('combined_byte_enable') == node.id:
                # Find the data mux that feeds this write port
                for edge in port_node.incoming_edges:
                    if edge.data.get('type') == 'write_data':
                        data_mux_node = edge.source
                        break
                break

        # Build a map from instruction name to pipelined enable signal
        # by looking at the data mux's mux_select edges
        instr_to_pipelined_enable = {}
        if data_mux_node:
            for edge in data_mux_node.incoming_edges:
                if edge.data.get('type') == 'mux_select':
                    source_node = edge.source
                    # The mux_input edges have source_instruction field
                    # Find corresponding mux_input with same select_index to get instruction name
                    select_index = edge.data.get('select_index')
                    if select_index is not None:
                        for input_edge in data_mux_node.incoming_edges:
                            if (input_edge.data.get('type') == 'mux_input' and
                                input_edge.data.get('input_index') == select_index):
                                instr_name = input_edge.data.get('source_instruction')
                                if instr_name:
                                    enable_name = self.node_id_to_name.get(
                                        source_node.id, self._sanitize_identifier(source_node.id))
                                    instr_to_pipelined_enable[instr_name] = enable_name
                                break

        # Build nested ternary: en0 ? be0 : en1 ? be1 : ... : default
        default_str = f"{bit_width}'h{default_value:x}"
        expr = default_str

        for enable_node_id, be_node_id in reversed(mux_inputs):
            # Extract instruction name from enable signal (e.g., 'sb_enable' -> 'sb')
            instr_name = None
            if enable_node_id.endswith('_enable'):
                instr_name = enable_node_id[:-7]  # Remove '_enable' suffix
            elif enable_node_id.endswith('_enable_and'):
                instr_name = enable_node_id[:-11]  # Remove '_enable_and' suffix

            # Use the pipelined enable from the data mux if available
            enable_name = None
            if instr_name and instr_name in instr_to_pipelined_enable:
                enable_name = instr_to_pipelined_enable[instr_name]

            # Fall back to original enable signal if no pipelined version found
            if not enable_name:
                enable_name = self.node_id_to_name.get(enable_node_id, self._sanitize_identifier(enable_node_id))

            be_name = self.node_id_to_name.get(be_node_id, self._sanitize_identifier(be_node_id))
            expr = f"{enable_name} ? {be_name} : {expr}"

        self.comb_logic += f"    assign {verilog_name} = {expr};\n"

    def _generate_address_mux_logic(self, node: Node):
        """Generate logic for address mux nodes (one-hot mux for memory read addresses).

        These are created by memory_access_transform when multiple instructions
        share a memory read but have different effective address computations.

        The mux selects between different EA sources based on their collision mux
        enable signals (e.g., lbz_ea_mux_enable_or_0).
        """
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))
        bit_width = node.data.get('bit_width', 64)
        mux_inputs = node.data.get('mux_inputs', [])

        if not mux_inputs:
            print(f"Warning: Address mux {node.id} has no inputs")
            return

        # For shared read address muxes, we need to ensure enable signals are declared
        # and their logic is generated before we use them
        if node.data.get('is_shared_read_addr_mux'):
            for mux_input in mux_inputs:
                enable_node_id = mux_input.get('enable_node')
                if enable_node_id:
                    enable_name = self._sanitize_identifier(enable_node_id)
                    if enable_name not in self.declared_names:
                        # Declare the enable signal directly (declarations already generated)
                        self.declarations += f"    wire {enable_name};\n"
                        self.declared_names.add(enable_name)

                    # Generate the enable signal logic if not already assigned
                    if enable_name not in self.assigned_signals:
                        enable_node = self.graph.nodes.get(enable_node_id)
                        if enable_node:
                            self._generate_read_enable_logic(enable_node, enable_name)
                            self.assigned_signals.add(enable_name)

        # Classify addresses by pattern to identify the best default
        # For Z80-style ISAs: *_hl_mem_addr is the most common pattern (used by many instructions)
        # so it should be the default
        hl_addr = None
        specific_addrs = []  # (enable, addr) pairs for non-HL addresses

        for mux_input in mux_inputs:
            source_node_id = mux_input.get('source_node')
            enable_node_id = mux_input.get('enable_node')
            source_name = self.node_id_to_name.get(source_node_id, self._sanitize_identifier(source_node_id))

            # Identify HL-pattern address (common default for Z80)
            if 'hl_mem_addr' in source_node_id.lower() and 'nn' not in source_node_id.lower():
                hl_addr = source_name
            elif enable_node_id:
                # This is a specific address with its own enable
                if isinstance(enable_node_id, list):
                    enable_names = [self.node_id_to_name.get(eid, self._sanitize_identifier(eid)) for eid in enable_node_id]
                    enable_name = ' || '.join(enable_names)
                else:
                    enable_name = self.node_id_to_name.get(enable_node_id, self._sanitize_identifier(enable_node_id))
                specific_addrs.append((enable_name, source_name))
            elif not hl_addr:
                # No enable and not HL - could be default
                hl_addr = source_name

        # Build the mux: specific addresses first, then HL address as default
        mux_parts = []
        default_addr = hl_addr

        for enable, addr in specific_addrs:
            # Skip if this is the same as the default (HL) address
            if addr == default_addr:
                continue
            mux_parts.append((enable, addr))

        # Generate the mux expression
        if not mux_parts:
            if default_addr:
                expr = default_addr
            else:
                expr = f"{bit_width}'d0"
        elif len(mux_parts) == 1 and default_addr:
            enable, addr = mux_parts[0]
            expr = f"({enable}) ? {addr} : {default_addr}"
        else:
            expr_parts = []
            for enable, addr in mux_parts:
                expr_parts.append(f"({enable} ? {addr} : ")

            if default_addr:
                expr = ''.join(expr_parts) + default_addr + ')' * len(expr_parts)
            else:
                last_addr = mux_parts[-1][1]
                expr_parts = expr_parts[:-1]
                if expr_parts:
                    expr = ''.join(expr_parts) + last_addr + ')' * len(expr_parts)
                else:
                    expr = last_addr

        self.comb_logic += f"    assign {verilog_name} = {expr};\n"

    def _generate_read_enable_logic(self, node: Node, verilog_name: str):
        """Generate logic for read enable signals used in shared read muxes.

        Read enables can be:
        1. Simple instruction enables (e.g., movl_enable)
        2. OR of multiple instruction enables (e.g., movb_enable || movl_enable)
        3. Literals (e.g., 1'b1 for always-enabled reads like PC fetch)
        """
        node_type = node.data.get('type', '')

        if node_type == 'literal':
            value = node.data.get('value', 0)
            self.comb_logic += f"    assign {verilog_name} = 1'd{value};\n"

        elif node_type == 'logical_or':
            # OR of multiple enables
            or_parts = []
            for edge in node.incoming_edges:
                source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                or_parts.append(source_name)
            if or_parts:
                expr = ' || '.join(sorted(or_parts))
                self.comb_logic += f"    assign {verilog_name} = {expr};\n"
            else:
                self.comb_logic += f"    assign {verilog_name} = 1'b0;\n"

        elif node_type == 'logical_and':
            # AND of condition and instruction enable (e.g., add_rn_bk && add_enable)
            and_parts = []
            for edge in node.incoming_edges:
                source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                and_parts.append(source_name)
            if and_parts:
                expr = ' && '.join(sorted(and_parts))
                self.comb_logic += f"    assign {verilog_name} = {expr};\n"
            else:
                self.comb_logic += f"    assign {verilog_name} = 1'b0;\n"

        elif node_type == 'alias':
            # Alias to another signal
            for edge in node.incoming_edges:
                source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                self.comb_logic += f"    assign {verilog_name} = {source_name};\n"
                break

        elif verilog_name.endswith('_enable'):
            # Single instruction enable - look for incoming edges
            for edge in node.incoming_edges:
                source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                self.comb_logic += f"    assign {verilog_name} = {source_name};\n"
                break
            else:
                # No incoming edges - might be a direct instruction enable
                # Try to find the instruction name and use its enable directly
                instr_name = verilog_name.replace('_enable', '').replace('_rd', '').rsplit('_', 1)[-1]
                if instr_name + '_enable' in self.declared_names:
                    self.comb_logic += f"    assign {verilog_name} = {instr_name}_enable;\n"
                else:
                    self.comb_logic += f"    assign {verilog_name} = 1'b0; // TODO: check enable source\n"

        else:
            self.comb_logic += f"    assign {verilog_name} = 1'b0; // Unknown enable type: {node_type}\n"

    def _generate_hardcoded_store_logic(
        self,
        full_enable: str,
        index_name: str,
        array_name: str,
        word_index_name: str,
        source_name: str,
        data_width: int,
        element_bits: int
    ):
        """Generate hardcoded byte-lane selection case statement for stores.

        This is the fallback when graph-based store nodes are not available.
        Used for backward compatibility with non-transformed graphs.
        """
        import math
        if full_enable:
            self.seq_logic += f"            if ({full_enable}) begin\n"
            indent = "                "
        else:
            indent = "            "

        endianness = self._get_mem_endianness(array_name)
        is_big_endian = endianness == 'big'

        # Compute offset bits based on memory element width
        import math
        addr_shift = int(math.log2(element_bits // 8)) if element_bits >= 8 else 2
        offset_bits = addr_shift
        num_cases = 1 << offset_bits

        # Generate case statement for byte-lane selection
        if data_width == 8:
            # Byte store - always fits within a single word
            self.seq_logic += f"{indent}case ({index_name}[{offset_bits-1}:0])\n"
            if is_big_endian:
                for i in range(num_cases):
                    high = element_bits - 1 - i * 8
                    low = high - 7
                    self.seq_logic += f"{indent}    {offset_bits}'d{i}: {array_name}[{word_index_name}][{high}:{low}] <= {source_name}[7:0];\n"
            else:
                for i in range(num_cases):
                    low = i * 8
                    high = low + 7
                    self.seq_logic += f"{indent}    {offset_bits}'d{i}: {array_name}[{word_index_name}][{high}:{low}] <= {source_name}[7:0];\n"
            self.seq_logic += f"{indent}endcase\n"
        elif data_width == 16:
            # Halfword store
            self.seq_logic += f"{indent}case ({index_name}[{offset_bits-1}:0])\n"
            for i in range(num_cases):
                if is_big_endian:
                    high = element_bits - 1 - i * 8
                    low = high - 15
                else:
                    low = i * 8
                    high = low + 15
                if low >= 0 and high < element_bits:
                    self.seq_logic += f"{indent}    {offset_bits}'d{i}: {array_name}[{word_index_name}][{high}:{low}] <= {source_name}[15:0];\n"
                else:
                    if is_big_endian:
                        bits_in_current = max(0, high + 1)
                        bits_in_next = 16 - bits_in_current
                    else:
                        bits_in_current = element_bits - low
                        bits_in_next = 16 - bits_in_current
                    self.seq_logic += f"{indent}    {offset_bits}'d{i}: begin\n"
                    if is_big_endian:
                        self.seq_logic += f"{indent}        {array_name}[{word_index_name}][{max(0, high)}:0] <= {source_name}[15:{16-bits_in_current}];\n"
                        self.seq_logic += f"{indent}        {array_name}[{word_index_name} + 1][{element_bits-1}:{element_bits-bits_in_next}] <= {source_name}[{bits_in_next-1}:0];\n"
                    else:
                        self.seq_logic += f"{indent}        {array_name}[{word_index_name}][{element_bits-1}:{low}] <= {source_name}[{bits_in_current-1}:0];\n"
                        self.seq_logic += f"{indent}        {array_name}[{word_index_name} + 1][{bits_in_next-1}:0] <= {source_name}[15:{bits_in_current}];\n"
                    self.seq_logic += f"{indent}    end\n"
            self.seq_logic += f"{indent}endcase\n"
        elif data_width == 32:
            # Word store
            self.seq_logic += f"{indent}case ({index_name}[{offset_bits-1}:0])\n"
            for i in range(num_cases):
                if is_big_endian:
                    high = element_bits - 1 - i * 8
                    low = high - 31
                else:
                    low = i * 8
                    high = low + 31
                if low >= 0 and high < element_bits:
                    if low == 0 and high == element_bits - 1:
                        self.seq_logic += f"{indent}    {offset_bits}'d{i}: {array_name}[{word_index_name}] <= {source_name};\n"
                    else:
                        self.seq_logic += f"{indent}    {offset_bits}'d{i}: {array_name}[{word_index_name}][{high}:{low}] <= {source_name}[31:0];\n"
                else:
                    if is_big_endian:
                        bits_in_current = max(0, high + 1)
                        bits_in_next = 32 - bits_in_current
                    else:
                        bits_in_current = element_bits - low
                        bits_in_next = 32 - bits_in_current
                    self.seq_logic += f"{indent}    {offset_bits}'d{i}: begin\n"
                    if is_big_endian:
                        self.seq_logic += f"{indent}        {array_name}[{word_index_name}][{bits_in_current-1}:0] <= {source_name}[31:{bits_in_next}];\n"
                        self.seq_logic += f"{indent}        {array_name}[{word_index_name} + 1][{element_bits-1}:{element_bits-bits_in_next}] <= {source_name}[{bits_in_next-1}:0];\n"
                    else:
                        self.seq_logic += f"{indent}        {array_name}[{word_index_name}][{element_bits-1}:{low}] <= {source_name}[{bits_in_current-1}:0];\n"
                        self.seq_logic += f"{indent}        {array_name}[{word_index_name} + 1][{bits_in_next-1}:0] <= {source_name}[31:{bits_in_current}];\n"
                    self.seq_logic += f"{indent}    end\n"
            self.seq_logic += f"{indent}endcase\n"

        if full_enable:
            self.seq_logic += f"            end\n"

    def _generate_stall_controller_logic(self, node: Node):
        """Generate logic for pipeline stall controller nodes (OR of hazard signals)."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Collect all hazard signals from incoming control edges
        hazard_signals = []
        for edge in node.incoming_edges:
            if edge.data.get('type') == 'control':
                source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                hazard_signals.append(source_name)

        if hazard_signals:
            # Stall if ANY hazard is detected (OR of all hazards) - sorted for determinism
            stall_expr = ' || '.join(sorted(hazard_signals))
            self.comb_logic += f"    assign {verilog_name} = {stall_expr};\n"

            # Also generate the enable signal (inverse of stall)
            enable_name = f"{verilog_name}_enable"
            self.comb_logic += f"    assign {enable_name} = !({verilog_name});\n"

            # Declare the enable wire - add directly to declarations string
            # since _generate_declarations() has already run
            if enable_name not in self.declared_names:
                self.declarations += f"    wire {enable_name};\n"
                self.declared_names.add(enable_name)
        else:
            # No hazards for this stage - always enabled
            self.comb_logic += f"    assign {verilog_name} = 1'b0;\n"
            enable_name = f"{verilog_name}_enable"
            self.comb_logic += f"    assign {enable_name} = 1'b1;\n"

            # Declare the enable wire - add directly to declarations string
            # since _generate_declarations() has already run
            if enable_name not in self.declared_names:
                self.declarations += f"    wire {enable_name};\n"
                self.declared_names.add(enable_name)

    def _generate_ras_read_logic(self, node: Node):
        """Generate logic for RAS read (top of stack prediction)."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Find the RAS stack and index from incoming edges
        ras_stack_name = None
        index_name = None

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type == 'array_base':
                ras_stack_name = self.node_id_to_name.get(
                    edge.source.id, self._sanitize_identifier(edge.source.id))
            elif edge_type == 'array_index':
                index_name = self._get_node_verilog_ref(edge.source)

        if ras_stack_name and index_name:
            # Generate: assign ras_stack_read = ras_stack[ras_ptr - 1];
            self.comb_logic += f"    // RAS top-of-stack read (predicted return address)\n"
            self.comb_logic += f"    assign {verilog_name} = {ras_stack_name}[{index_name}];\n"
        else:
            # Fallback: try to infer from node data
            array_name = node.data.get('array', 'ras_stack')
            self.comb_logic += f"    // RAS read (array/index not found, using fallback)\n"
            self.comb_logic += f"    assign {verilog_name} = {array_name}[ras_ptr - 1];\n"

    def _generate_ras_predict_mux_logic(self, node: Node):
        """Generate logic for RAS prediction mux (ras_pop ? ras_top : pc_add_4)."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Get input names from node data (stored during graph construction)
        select_name = node.data.get('mux_select', 'ras_pop')
        true_name = node.data.get('mux_true', 'ras_top')
        false_name = node.data.get('mux_false', 'pc_add_4')

        # Try to resolve the names from the graph
        select_node_name = self.node_id_to_name.get(select_name, select_name)
        true_node_name = self.node_id_to_name.get(true_name, true_name)
        false_node_name = self.node_id_to_name.get(false_name, false_name)

        # Also check incoming edges for direct connections
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            edge_cond = edge.data.get('condition', '')
            if edge_type == 'mux_select':
                select_node_name = self._get_node_verilog_ref(edge.source)
            elif edge_type == 'mux_input' and edge_cond == 'true':
                true_node_name = self._get_node_verilog_ref(edge.source)
            elif edge_type == 'mux_input' and edge_cond == 'false':
                false_node_name = self._get_node_verilog_ref(edge.source)

        # Generate: assign ras_predict_mux = ras_pop ? ras_top : pc_add_4;
        self.comb_logic += f"    // RAS prediction mux: use RAS top when return detected, otherwise PC+4\n"
        self.comb_logic += f"    assign {verilog_name} = {select_node_name} ? {true_node_name} : {false_node_name};\n"

    def _generate_narrow_memory_access_logic(self, node: Node):
        """Generate logic for narrow memory access nodes (from memory serialization)."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Get memory name and access information from node data
        memory = node.data.get('memory')
        access_mode = node.data.get('access_mode', 'read')  # 'read' or 'write'
        word_width = node.data.get('word_width')

        # Find address input (from address_offset node)
        address_name = None
        for edge in node.incoming_edges:
            if edge.data.get('type') in ['address', 'memory_address']:
                address_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                break

        if not address_name:
            print(f"Warning: No address input found for narrow memory access {node.id}")
            return

        # For reads, generate memory access logic
        if access_mode == 'read':
            # Memory read is handled in sequential logic, but we need to declare the wire
            # The actual read will be generated as part of memory operations
            # For now, just add a comment
            self.comb_logic += f"    // Narrow memory read: {verilog_name} = {memory}[{address_name}] ({word_width} bits)\n"

    def _generate_address_offset_logic(self, node: Node):
        """Generate logic for address offset nodes (address + byte offset)."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Get base address and byte offset from node data
        byte_offset = node.data.get('byte_offset', 0)

        # Find base address input
        base_address_name = None
        for edge in node.incoming_edges:
            if edge.data.get('type') in ['address', 'base_address']:
                base_address_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                break

        if not base_address_name:
            # If no edge, try to get from first incoming edge (sorted for determinism)
            if node.incoming_edges:
                first_edge = sorted(node.incoming_edges, key=lambda e: e.source.id)[0]
                base_address_name = self.node_id_to_name.get(first_edge.source.id, self._sanitize_identifier(first_edge.source.id))

        if not base_address_name:
            print(f"Warning: No base address found for address_offset node {node.id}")
            return

        # Generate address arithmetic
        if byte_offset == 0:
            self.comb_logic += f"    assign {verilog_name} = {base_address_name};\n"
        else:
            self.comb_logic += f"    assign {verilog_name} = {base_address_name} + {byte_offset};\n"

    def _generate_memory_data_merge_logic(self, node: Node):
        """Generate logic for memory data merge nodes (concatenate narrow reads)."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Get merge configuration from node data
        num_words = node.data.get('num_words', 2)
        word_width = node.data.get('word_width')

        # Find all word inputs (from narrow memory accesses or ports)
        word_inputs = []
        for i in range(num_words):
            word_name = None
            # Look for incoming edges with word index
            for edge in node.incoming_edges:
                if edge.data.get('word_index') == i or edge.source.id.endswith(f'_word{i}') or edge.source.id.endswith(f'_port{i}'):
                    word_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                    break
            if word_name:
                word_inputs.append(word_name)

        if not word_inputs:
            # No word inputs found via standard lookup - try fallback for mux_input edges
            # This handles cache write-through where the data comes from cache output
            if node.incoming_edges:
                # Look for mux_input type edges (data inputs, not select signals)
                for edge in node.incoming_edges:
                    edge_type = edge.data.get('type', '')
                    if edge_type == 'mux_input':
                        source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                        if source_name:
                            self.comb_logic += f"    assign {verilog_name} = {source_name};  // Pass-through from mux_input\n"
                            return
            print(f"Warning: No inputs found for memory_data_merge node {node.id}")
            return

        # Generate concatenation (MSB first for big-endian)
        # Word order: word1, word0 -> {word1, word0}
        word_inputs.reverse()  # Reverse to put MSB first
        concatenated = "{" + ", ".join(word_inputs) + "}"
        self.comb_logic += f"    assign {verilog_name} = {concatenated};\n"

    def _generate_write_data_slice_logic(self, node: Node):
        """Generate logic for write data slice nodes (extract bits for narrow writes)."""
        verilog_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Get slice information from node data
        high = node.data.get('high_bit')
        low = node.data.get('low_bit')

        # Find write data input
        data_name = None
        for edge in node.incoming_edges:
            if edge.data.get('type') in ['data', 'write_data']:
                data_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                break

        if not data_name and node.incoming_edges:
            # Use first incoming edge as fallback (sorted for determinism)
            first_edge = sorted(node.incoming_edges, key=lambda e: e.source.id)[0]
            data_name = self.node_id_to_name.get(first_edge.source.id, self._sanitize_identifier(first_edge.source.id))

        if not data_name:
            print(f"Warning: No data input found for write_data_slice node {node.id}")
            return

        # Generate bit slice
        if high is not None and low is not None:
            if high == low:
                self.comb_logic += f"    assign {verilog_name} = {data_name}[{high}];\n"
            else:
                self.comb_logic += f"    assign {verilog_name} = {data_name}[{high}:{low}];\n"
        else:
            print(f"Warning: Missing bit range for write_data_slice node {node.id}")

    def _process_split_memory_port(self, node: Node):
        """Process split memory port nodes (created by split_merge transformation)."""
        port_name = node.id
        bit_width = node.data.get('bit_width')
        array_depth = node.data.get('array_depth', 1024)

        # Treat as a separate memory
        sanitized_name = self._sanitize_identifier(port_name)

        if sanitized_name not in self.memory_declarations:
            # Calculate address width from array depth
            import math
            addr_width = math.ceil(math.log2(array_depth)) if array_depth > 0 else 10

            self.memory_declarations[sanitized_name] = {
                'bit_width': bit_width,
                'array_depth': array_depth,
                'addr_width': addr_width,
                'mem_file': f"{sanitized_name}.hex",
                'is_split_port': True
            }

        self.node_id_to_name[node.id] = sanitized_name

    def _generate_variable_assignments(self):
        """Generate assignments for variables driven by combinational logic."""
        # Pre-scan: collect bit_slice WRITE assignments grouped by target variable.
        # These represent bit-level modifications like: new_sr[0] = 1; new_sr[5] = 0;
        # that need to be folded into the base variable assignment.
        bit_slice_writes = {}  # var_name -> [(high, low, source_verilog_ref)]
        for edge in sorted(self.graph.edges.values(), key=lambda e: (e.source.id, e.target.id)):
            if edge.data.get('type') == 'assignment':
                target = edge.target
                if (target.data.get('type') == 'bit_slice' and
                    target.data.get('access_mode') == 'write'):
                    expr = target.data.get('expression', {})
                    if expr.get('type') == 'bit_slice':
                        target_expr = expr.get('target', {})
                        var_name = target_expr.get('name', '')
                        high_bit, low_bit = expr.get('range', (0, 0))
                        source_ref = self._get_node_verilog_ref(edge.source)
                        if var_name:
                            if var_name not in bit_slice_writes:
                                bit_slice_writes[var_name] = []
                            bit_slice_writes[var_name].append((high_bit, low_bit, source_ref))

        # Find assignment edges to variables and ISA state that are wires
        # Sort for deterministic output
        for edge in sorted(self.graph.edges.values(), key=lambda e: (e.source.id, e.target.id)):
            if edge.data.get('type') == 'assignment':
                target = edge.target

                # Skip bit_slice nodes - handled by bit_slice_writes pre-scan above
                if (target.data.get('type') == 'bit_slice' or
                    target.data.get('expression', {}).get('type') == 'bit_slice'):
                    continue

                # Skip ext push states entirely - handled by dedicated ext push sequential block
                # Check both the node's data flags (regardless of is_arch_state)
                if target.data.get('is_external') and target.data.get('is_push'):
                    continue

                # Include: variables that are not registers, and ISA state that are not registers
                should_assign = False
                if not target.is_arch_state:
                    # Regular variables that are not registers
                    # Include cache_read_req nodes that are driven by combinational logic
                    if (target.data.get('type') in ['var', 'temp_var', 'isa_state', 'cache_read_req', 'control_signal'] and
                        not self._should_be_register(target)):
                        should_assign = True
                else:
                    # ISA state that are not registers and not memory
                    # Special case: _wr nodes are wires that need combinational assignments
                    # EXCEPT: array _wr nodes with ternary sources (handled in sequential logic)
                    if '_wr' in target.id:
                        # Check if this is an array _wr driven by array ternary
                        if self._is_array_ternary(edge.source):
                            should_assign = False  # Handled in sequential logic
                        else:
                            should_assign = True
                    elif (not target.data.get('is_memory', False) and
                          not self._should_be_register(target) and
                          target.data.get('type') != 'isa_state'):
                        # Don't create combinational assigns for isa_state nodes
                        # (like 8086 flags) - they should be registers in sequential logic
                        should_assign = True

                if should_assign:
                    # Skip assignments to x0 (RISC-V hardwired zero register)
                    # x0 must always be zero and cannot be written
                    target_name_check = target.data.get('name', target.id)
                    if target_name_check == 'x0':
                        continue

                    # Skip if source is a conditional write array_access (from ILA transformation)
                    # These are handled in sequential logic, not combinational
                    source = edge.source
                    if source.data.get('type') == 'array_access' and source.data.get('is_write'):
                        continue

                    # Skip assignments to memory arrays (2D arrays, not 1D bit vectors)
                    if target.data.get('is_memory', False) or target.data.get('dimension_count', 0) > 1:
                        continue

                    # Use node_id_to_name mapping for target (handles split nodes like pc_wr)
                    # Prefer display_name over name for split nodes
                    if target.id in self.node_id_to_name:
                        target_name = self.node_id_to_name[target.id]
                    elif 'display_name' in target.data:
                        target_name = target.data['display_name']
                    else:
                        target_name = target.data.get('name', target.id)

                    # Skip if this target already has an assignment (prevents duplicate assignments)
                    if target_name in self.assigned_signals:
                        continue
                    self.assigned_signals.add(target_name)

                    # Special handling for flush signals: gate with instruction enable
                    # The flush should only be active when its instruction is executing
                    if target.data.get('is_flush_trigger'):
                        instruction = target.data.get('instruction')
                        if instruction:
                            enable_signal = f"{instruction}_enable"
                            self.comb_logic += f"    assign {target_name} = {enable_signal};\n"
                            continue  # Skip normal assignment generation

                    # Use _get_node_verilog_ref to handle special nodes (casts, replications, concatenations)
                    # This ensures we inline expressions properly (e.g., {1{w_20}} instead of w_1_w_20)
                    source_name = self._get_node_verilog_ref(source)

                    # Fold bit_slice writes into the variable assignment.
                    # If this variable has bit-level modifications (e.g., new_sr[0] = 1; new_sr[5] = 0;),
                    # generate a bit-concatenation expression instead of a plain assignment.
                    # IMPORTANT: Only fold for local variables (var/temp_var), NOT for isa_state
                    # or _wr nodes. isa_state bit_slice writes (e.g., xer[34] = carry in OpenPower)
                    # are handled separately in sequential logic as scalar_bit_slice_writes.
                    var_orig_name = target.data.get('name', target.id)
                    if (var_orig_name in bit_slice_writes and
                        not target.is_arch_state and
                        target.data.get('type') in ('var', 'temp_var')):
                        modifications = bit_slice_writes[var_orig_name]
                        var_width = target.data.get('bit_width', 32)
                        combined = self._build_bit_modified_expression(
                            source_name, var_width, modifications)
                        if combined is not None:
                            self.comb_logic += f"    assign {target_name} = {combined};\n"
                            continue

                    # Handle narrow loads from memory: if source is a memory read and target is narrower,
                    # generate selection logic based on address low bits
                    target_width = target.data.get('bit_width')
                    # Use _infer_bit_width to get actual width for memory read nodes
                    # This correctly handles 8-bit memories instead of defaulting to 32
                    source_width = source.data.get('bit_width')
                    if source_width is None:
                        source_width = self._infer_bit_width(source)
                        if source_width is None:
                            source_width = 32  # Last resort default

                    # Skip selection logic for concatenation nodes - they combine multiple narrow reads
                    # and don't need further extraction. Their bit_width should be computed from parts.
                    if source.data.get('type') == 'concatenation':
                        # Compute actual width from concatenation parts if not set
                        if source.data.get('bit_width') is None:
                            total_width = 0
                            for edge in source.incoming_edges:
                                if edge.data.get('type') in ['concat_input', 'concatenation_input']:
                                    part_width = edge.source.data.get('bit_width', 8)
                                    total_width += part_width
                            source_width = total_width if total_width > 0 else target_width
                        # Skip narrow load handling - concatenations are the final result
                        self.comb_logic += f"    assign {target_name} = {source_name};\n"
                        continue

                    # Check if source is a memory read from a 'mem' type memory (type 'isa_state mem')
                    is_memory_read = self._is_mem_type_read(source)

                    # For memory reads, get the actual memory width from memory_declarations
                    # instead of defaulting to 32 (which incorrectly triggers selection logic for 16-bit memories)
                    # Also track the memory name for endianness lookup
                    source_mem_name = None
                    if is_memory_read and source_width is None:
                        # Try to get memory width from the source node's memory reference
                        for s_edge in source.incoming_edges:
                            if s_edge.source.data.get('is_memory') or s_edge.source.data.get('type') == 'memory':
                                source_mem_name = s_edge.source.data.get('name', s_edge.source.id)
                                if source_mem_name in self.memory_declarations:
                                    source_width = self.memory_declarations[source_mem_name].get('bit_width')
                                    break
                        # Fallback to 32 only if memory width not found
                        if source_width is None:
                            source_width = 32
                    # Also try to get memory name from source node ID (e.g., "umem[addr]_rd" -> "umem")
                    if source_mem_name is None and '[' in source.id:
                        source_mem_name = source.id[:source.id.index('[')]

                    # Default to 32 for non-memory reads if not set
                    if source_width is None:
                        source_width = 32

                    # Only apply selection if source is wider than target
                    # If source has already been narrowed (e.g., by mem primitive), skip
                    if (is_memory_read and target_width and target_width < source_width and source_width > target_width):
                        # Narrow load: need to select portion based on address
                        # Find the address/index node by searching incoming edges
                        index_name = None

                        # For _rd nodes, look for array_index edges
                        # Skip the base array edge (e.g., dmem -> dmem[addr]_rd)
                        for s_edge in source.incoming_edges:
                            if s_edge.data.get('type') in ['array_index', 'operand']:
                                index_node = s_edge.source
                                # Skip if this is the base array (memory) node
                                if index_node.data.get('is_memory') or index_node.data.get('type') == 'memory':
                                    continue
                                # Check if this node is mapped, or if it has an assignment edge
                                if index_node.id in self.node_id_to_name:
                                    index_name = self.node_id_to_name[index_node.id]
                                else:
                                    # Check for assignment edge to get the computed value
                                    for a_edge in index_node.incoming_edges:
                                        if a_edge.data.get('type') == 'assignment':
                                            index_name = self._get_node_verilog_ref(a_edge.source)
                                            self.node_id_to_name[index_node.id] = index_name
                                            break
                                    else:
                                        index_name = self._sanitize_identifier(index_node.id)
                                break

                        # If not found, try to extract from the node ID (e.g., "dmem[addr]_rd" -> "addr")
                        if not index_name and '[' in source.id and ']' in source.id:
                            # Extract index from ID like "dmem[addr]_rd"
                            start = source.id.index('[') + 1
                            end = source.id.index(']')
                            index_id = source.id[start:end]
                            # Try to find the node for this index (exact match or prefixed version)
                            found_node = None
                            for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
                                if node.id == index_id or node.data.get('name') == index_id:
                                    found_node = node
                                    break
                                # Also check for prefixed versions (e.g., "addr_pa" -> "lb_addr_pa")
                                if node.data.get('type') in ['var', 'temp_var'] and node.id.endswith(f"_{index_id}"):
                                    found_node = node
                                    break

                            if found_node:
                                # Check if this node is already mapped, or if it has an assignment edge
                                if found_node.id in self.node_id_to_name:
                                    index_name = self.node_id_to_name[found_node.id]
                                else:
                                    # Check for assignment edge to get the computed value
                                    for edge in found_node.incoming_edges:
                                        if edge.data.get('type') == 'assignment':
                                            index_name = self._get_node_verilog_ref(edge.source)
                                            self.node_id_to_name[found_node.id] = index_name
                                            break
                                    else:
                                        index_name = self._sanitize_identifier(found_node.id)

                            if not index_name:
                                # Use the extracted ID directly
                                index_name = self._sanitize_identifier(index_id)

                        if index_name:
                            # Skip self-assignments
                            if target_name == source_name:
                                continue
                            # Check endianness for byte/halfword/word selection
                            mem_endianness = self._get_mem_endianness(source_mem_name) if source_mem_name else 'little'
                            # Compute address bit ranges based on source (memory) width
                            import math
                            byte_offset_bits = int(math.log2(source_width // 8))  # 2 for 32-bit, 3 for 64-bit
                            if target_width == 8:
                                # Byte selection from memory word
                                hi_bit = byte_offset_bits - 1
                                if mem_endianness == 'big':
                                    max_val = (source_width // 8) - 1
                                    max_bits = byte_offset_bits
                                    self.comb_logic += f"    assign {target_name} = {source_name}[({max_bits}'d{max_val} - {index_name}[{hi_bit}:0]) * 8 +: 8];\n"
                                else:
                                    self.comb_logic += f"    assign {target_name} = {source_name}[{index_name}[{hi_bit}:0] * 8 +: 8];\n"
                            elif target_width == 16:
                                # Halfword selection from memory word
                                hi_bit = byte_offset_bits - 1
                                if mem_endianness == 'big':
                                    max_val = (source_width // 16) - 1
                                    max_bits = byte_offset_bits - 1
                                    self.comb_logic += f"    assign {target_name} = {source_name}[({max_bits}'d{max_val} - {index_name}[{hi_bit}:1]) * 16 +: 16];\n"
                                else:
                                    self.comb_logic += f"    assign {target_name} = {source_name}[{index_name}[{hi_bit}:1] * 16 +: 16];\n"
                            elif target_width == 32 and source_width > 32:
                                # 32-bit word selection from memory wider than 32 bits
                                hi_bit = byte_offset_bits - 1
                                if mem_endianness == 'big':
                                    max_val = (source_width // 32) - 1
                                    max_bits = byte_offset_bits - 2
                                    self.comb_logic += f"    assign {target_name} = {source_name}[({max_bits}'d{max_val} - {index_name}[{hi_bit}:2]) * 32 +: 32];\n"
                                else:
                                    self.comb_logic += f"    assign {target_name} = {source_name}[{index_name}[{hi_bit}:2] * 32 +: 32];\n"
                            else:
                                # Unexpected narrow width, fall back to direct assignment
                                self.comb_logic += f"    assign {target_name} = {source_name};\n"
                        else:
                            # No index found, direct assignment
                            # Skip self-assignments
                            if target_name != source_name:
                                self.comb_logic += f"    assign {target_name} = {source_name};\n"
                    else:
                        # Skip self-assignments
                        if target_name != source_name:
                            self.comb_logic += f"    assign {target_name} = {source_name};\n"

    def _build_bit_modified_expression(self, base_expr, width, modifications):
        """Build a Verilog bit-concatenation expression that applies bit-level modifications.

        Given a base expression and a list of (high_bit, low_bit, value_expr) modifications,
        generates a concatenation like:
            {base[31:7], 1'b0, 1'b0, base[4:3], 1'b0, 1'b0, 1'b1}

        Args:
            base_expr: Verilog expression for the base value (e.g., "sr_rd")
            width: Total bit width of the variable
            modifications: List of (high_bit, low_bit, value_expr) tuples

        Returns:
            Verilog expression string, or None if no modifications
        """
        if not modifications:
            return None

        # Build a map of which bits are overridden
        # Each entry: bit_position -> value_expression
        overrides = {}
        for high, low, value_expr in modifications:
            slice_width = high - low + 1
            for bit in range(low, high + 1):
                bit_offset = bit - low
                if slice_width == 1:
                    # Single-bit modification: ensure 1-bit width
                    # Detect literal constants and generate clean 1-bit values
                    import re
                    literal_match = re.match(r"(\d+)'d(\d+)", value_expr)
                    if literal_match:
                        val = int(literal_match.group(2))
                        overrides[bit] = f"1'b{val & 1}"
                    else:
                        overrides[bit] = f"{value_expr}[0]"
                else:
                    overrides[bit] = f"{value_expr}[{bit_offset}]"

        # Build concatenation segments from MSB to LSB
        segments = []
        bit = width - 1
        while bit >= 0:
            if bit in overrides:
                # Find contiguous run of overridden bits
                run_start = bit
                while bit > 0 and (bit - 1) in overrides:
                    bit -= 1
                run_end = bit
                # Add each overridden bit value
                for b in range(run_start, run_end - 1, -1):
                    segments.append(overrides[b])
                bit = run_end - 1
            else:
                # Find contiguous run of unmodified bits
                run_start = bit
                while bit > 0 and (bit - 1) not in overrides:
                    bit -= 1
                run_end = bit
                # Add base expression slice
                if run_start == run_end:
                    if width == 1:
                        segments.append(base_expr)
                    else:
                        segments.append(f"{base_expr}[{run_start}]")
                else:
                    segments.append(f"{base_expr}[{run_start}:{run_end}]")
                bit = run_end - 1

        # If only one segment covers the full width, return as-is
        if len(segments) == 1:
            return segments[0]

        return "{" + ", ".join(segments) + "}"

    def _generate_conceptual_forwarding(self):
        """Generate conceptual forwarding assignments for split _rd nodes."""
        # For each _rd node with a state_update edge, generate: assign pc_rd = pc;
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if '_rd' in node.id and node.is_arch_state:
                # Skip memory arrays - they're accessed via indexing, not bulk assignment
                if node.data.get('array_depth') or node.data.get('is_memory'):
                    continue

                # Skip external inputs - they don't need forwarding, they're direct ports
                if node.data.get('is_external') and not node.data.get('is_push'):
                    continue

                # Check if this node has a state_update incoming edge
                has_state_update = any(edge.data.get('type') == 'state_update'
                                      for edge in node.incoming_edges)
                if has_state_update:
                    # Generate forwarding assignment
                    rd_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))
                    base_name = rd_name.replace('_rd', '')
                    self.comb_logic += f"    assign {rd_name} = {base_name};\n"

    def _build_enable_expression(self, expr: dict) -> str:
        """Build a Verilog expression from an enable condition AST.

        Recursively resolves identifiers to existing Verilog signal names.
        Used for ext push write-enable conditions that may reference signals
        not generated as separate wires.
        """
        if not expr or 'type' not in expr:
            return "1'b0"

        if expr['type'] == 'identifier':
            name = expr['name']
            # Try _rd variant first (for arch state reads)
            if f"{name}_rd" in self.node_id_to_name:
                return self.node_id_to_name[f"{name}_rd"]
            if name in self.node_id_to_name:
                return self.node_id_to_name[name]
            return self._sanitize_identifier(name)

        if expr['type'] == 'literal':
            value = expr.get('value', 0)
            width = expr.get('width', 32)
            return f"{width}'d{value}"

        if expr['type'] == 'binary_op':
            left = self._build_enable_expression(expr.get('left', {}))
            right = self._build_enable_expression(expr.get('right', {}))
            op = expr.get('operator', '&')
            verilog_op = {'&': '&', '|': '|', '==': '==', '!=': '!=',
                          '<': '<', '>': '>', '<=': '<=', '>=': '>='}.get(op, op)
            return f"({left} {verilog_op} {right})"

        if expr['type'] == 'unary_op':
            operand = self._build_enable_expression(expr.get('operand', {}))
            op = expr.get('operator', '~')
            return f"({op}{operand})"

        # Fallback: use _get_verilog_name_for_expression
        return self._get_verilog_name_for_expression(expr)

    def _get_or_create_merged_enable(self, enable_name: str) -> str:
        """Get or create a merged enable signal for conditional writes.

        When an enable signal from an aspect gets instruction-prefixed during merging,
        we need to create a unified enable that ORs together all instruction-specific versions.

        Args:
            enable_name: The base enable signal name (e.g., 'itlb_miss_or_itlb_prot_viol')

        Returns:
            Either the original name if it exists, or the name of a merged enable signal
        """
        # Check if the signal already exists in declared wires or the graph
        wire_names = {w['name'] for w in self.wire_declarations}
        if enable_name in wire_names or enable_name in self.graph.nodes:
            return enable_name

        # Also check if it's in node_id_to_name values
        if enable_name in self.node_id_to_name.values():
            return enable_name

        # Look for instruction-prefixed versions (e.g., 'add_itlb_miss_or_itlb_prot_viol')
        prefixed_versions = []
        for wire in self.wire_declarations:
            wire_name = wire['name']
            if wire_name.endswith(f"_{enable_name}"):
                prefixed_versions.append(wire_name)

        if not prefixed_versions:
            # No prefixed versions found, return original name (will fail at compile time)
            return enable_name

        # Create a merged enable signal
        merged_name = f"merged_{enable_name}"
        if merged_name not in self.declared_names:
            self.wire_declarations.append({'name': merged_name, 'bit_width': 1})
            self.declared_names.add(merged_name)

            # Generate the OR of all instruction-specific versions
            or_expr = " || ".join(sorted(prefixed_versions))
            # Emit wire declaration inline since _generate_declarations() may have
            # already run (self.declarations is a snapshot, not a live reference).
            self.comb_logic += f"\n    // Merged enable from instruction-specific versions\n"
            self.comb_logic += f"    wire {merged_name};\n"
            self.comb_logic += f"    assign {merged_name} = {or_expr};\n"

        return merged_name

    def _format_literal_value(self, value, bit_width: int) -> str:
        """Format a literal value for Verilog with proper base notation.

        Args:
            value: The value (can be int, or string like '0b0110011', '0x7', etc.)
            bit_width: The bit width to use

        Returns:
            Properly formatted Verilog literal (e.g., "7'b0110011", "3'h7", "32'd42")
        """
        if isinstance(value, str):
            # Check if already in Verilog literal format (e.g., "12'h302", "7'b0110011")
            import re
            if re.match(r"^\d+'[bhdBHD]\w+$", value):
                # Already a valid Verilog literal, return as-is
                return value
            elif value.startswith('0b'):
                # Binary literal - strip '0b' prefix
                bits = value[2:]
                return f"{bit_width}'b{bits}"
            elif value.startswith('0x'):
                # Hex literal - strip '0x' prefix
                hex_val = value[2:]
                return f"{bit_width}'h{hex_val}"
            else:
                # Decimal string - convert to int
                try:
                    int_val = int(value, 0)  # Auto-detect base
                    return f"{bit_width}'d{int_val}"
                except ValueError:
                    # Fallback to direct decimal
                    return f"{bit_width}'d{value}"
        else:
            # Numeric value
            return f"{bit_width}'d{value}"

    def _get_verilog_name_for_expression(self, expr: Dict, calling_node_id: str = '') -> str:
        """Get the Verilog signal name for an expression.

        Args:
            expr: The expression dict to resolve.
            calling_node_id: The ID of the node being generated (used to infer
                instruction prefix for locally-scoped variable names like
                'invtaken' that become 'cmpb_eq_invtaken' after graph merging).
        """
        if not expr or 'type' not in expr:
            # Handle empty or malformed expressions gracefully
            if expr and 'name' in expr:
                name = expr['name']
                for candidate in [name, f"{name}_rd"]:
                    if candidate in self.node_id_to_name:
                        return self.node_id_to_name[candidate]
            return "1'b0"
        if expr['type'] == 'identifier':
            name = expr['name']
            # For architectural states with split read/write, prefer the _rd version
            # This ensures we read the registered value, not the write target
            # But don't add _rd suffix if name already ends with _rd or _zext
            # (to avoid double-suffix like rf_rm_rd_zext_rd)
            if not name.endswith('_rd') and not name.endswith('_zext'):
                if f"{name}_rd" in self.node_id_to_name:
                    return self.node_id_to_name[f"{name}_rd"]
            # Check if there's a node with this name and use its mapped Verilog name
            if name in self.node_id_to_name:
                return self.node_id_to_name[name]
            # Check for _wr variant (less common for reads)
            if f"{name}_wr" in self.node_id_to_name:
                return self.node_id_to_name[f"{name}_wr"]
            # Check if there's a var node with this name that has an assignment edge
            # This handles aspect variables like addr_pa that are assigned from computed values
            var_node = self.graph.nodes.get(name)

            # If no exact match, search for prefixed versions (e.g., "addr_pa" -> "lb_addr_pa")
            # This handles cases where variables from aspects get instruction-prefixed
            if not var_node:
                for node_id, node in sorted(self.graph.nodes.items()):
                    if node.data.get('type') in ['var', 'temp_var']:
                        # Check if this node ends with the name we're looking for
                        if node_id.endswith(f"_{name}") or node_id == name:
                            var_node = node
                            break

            if var_node and var_node.data.get('type') in ['var', 'temp_var']:
                for edge in var_node.incoming_edges:
                    if edge.data.get('type') == 'assignment':
                        source_id = edge.source.id
                        if source_id in self.node_id_to_name:
                            # Cache this mapping for future lookups
                            self.node_id_to_name[name] = self.node_id_to_name[source_id]
                            return self.node_id_to_name[source_id]

            # Last resort: if calling_node_id is provided, try to extract the instruction
            # prefix from it. For example, if calling_node_id='cmpb_eq_invtaken_and_expr_6337'
            # and name='invtaken', we look for '_invtaken' in the calling node ID to recover
            # the fully-qualified name 'cmpb_eq_invtaken'.
            if calling_node_id:
                suffix = f"_{name}"
                idx = calling_node_id.find(suffix)
                if idx != -1:
                    prefixed_name = calling_node_id[:idx + len(suffix)]
                    # Guard: don't use the calling node's own name as its operand
                    # (would create a self-referencing assignment like x = !x)
                    if prefixed_name != calling_node_id:
                        if prefixed_name in self.node_id_to_name:
                            return self.node_id_to_name[prefixed_name]
                        if prefixed_name in self.graph.nodes:
                            ref = self._get_node_verilog_ref(self.graph.nodes[prefixed_name])
                            self.node_id_to_name[name] = ref
                            return ref

            return name
        elif expr['type'] == 'sized_literal':
            # Use format + original_digits when available (canonical form)
            width = expr.get('width', 1)
            fmt = expr.get('format')
            original_digits = expr.get('original_digits')
            if fmt and original_digits is not None:
                fmt_char = {'bin': 'b', 'hex': 'h', 'dec': 'd'}.get(fmt, 'b')
                return f"{width}'{fmt_char}{original_digits}"
            # Fallback to legacy compat keys
            elif 'bits' in expr:
                return f"{width}'b{expr.get('bits', '0')}"
            elif 'hex_digits' in expr:
                return f"{width}'h{expr.get('hex_digits', '0')}"
            elif 'dec_digits' in expr:
                return f"{width}'d{expr.get('dec_digits', '0')}"
            else:
                return f"{width}'d{expr.get('value', 0)}"
        elif expr['type'] == 'literal':
            # Generate inline literal - use helper function
            value = expr.get('value')
            width = expr.get('width', 32)  # Use expression width if available
            return self._format_literal_value(value, width)
        elif expr['type'] == 'array_access':
            # First check if there's a node representing this array_access
            expr_id = self._expression_to_id(expr)
            if expr_id in self.node_id_to_name:
                return self.node_id_to_name[expr_id]
            # Otherwise generate inline array access
            array_expr = expr.get('target', {})
            index_expr = expr.get('index', {})
            array_name = self._get_verilog_name_for_expression(array_expr)
            # For array indices, just use the literal value without width formatting
            if index_expr.get('type') == 'literal':
                index_name = str(index_expr.get('value'))
            else:
                index_name = self._get_verilog_name_for_expression(index_expr)
            return f"{array_name}[{index_name}]"
        elif expr['type'] == 'repetition':
            # First check if there's a node representing this repetition
            expr_id = self._expression_to_id(expr)
            if expr_id in self.node_id_to_name:
                return self.node_id_to_name[expr_id]
            # Otherwise generate inline repetition
            count = expr.get('count', 1)
            inner_expr = expr.get('expression', {})
            inner_name = self._get_verilog_name_for_expression(inner_expr)
            return f"{{{count}{{{inner_name}}}}}"
        elif expr['type'] == 'bit_slice':
            # First check if there's a node representing this bit_slice expression
            # and use its mapped Verilog name (which will be sanitized)
            expr_id = self._expression_to_id(expr)
            if expr_id in self.node_id_to_name:
                return self.node_id_to_name[expr_id]

            # Otherwise generate inline bit slice
            # _parse_field_expression uses 'array' key; parser uses 'target' key — handle both
            target_expr = expr.get('target') or expr.get('array', {})
            target_name = self._get_verilog_name_for_expression(target_expr)

            # Handle both 'range' tuple and separate 'high'/'low' fields
            if 'range' in expr:
                high, low = expr['range']
            else:
                high = expr.get('high', {}).get('value', 0) if isinstance(expr.get('high'), dict) else expr.get('high', 0)
                low = expr.get('low', {}).get('value', 0) if isinstance(expr.get('low'), dict) else expr.get('low', 0)

            if high == low:
                return f"{target_name}[{high}]"
            else:
                return f"{target_name}[{high}:{low}]"
        elif expr['type'] == 'cam_lookup':
            # CAM associative lookup - generates parallel comparators
            expr_id = self._expression_to_id(expr)
            if expr_id in self.node_id_to_name:
                return self.node_id_to_name[expr_id]
            # Generate inline CAM lookup (will be expanded by _generate_cam_lookup)
            return self._sanitize_identifier(expr_id)
        elif expr['type'] == 'builtin_call':
            # Builtin functions (ctz, clz)
            expr_id = self._expression_to_id(expr)
            if expr_id in self.node_id_to_name:
                return self.node_id_to_name[expr_id]
            # Generate inline builtin (will be expanded)
            return self._sanitize_identifier(expr_id)
        elif expr['type'] == 'binary_op':
            # First check if there's a node representing this binary op
            expr_id = self._expression_to_id(expr)
            if expr_id in self.node_id_to_name:
                return self.node_id_to_name[expr_id]
            # Also check sanitized form (graph merger may use sanitized node IDs)
            sanitized = self._sanitize_identifier(expr_id)
            if sanitized in self.node_id_to_name:
                return self.node_id_to_name[sanitized]
            # No node exists - generate inline Verilog expression
            left_name = self._get_verilog_name_for_expression(expr['left'])
            right_name = self._get_verilog_name_for_expression(expr['right'])
            op = expr['operator']
            verilog_op = self._operator_to_verilog(op)
            if op in ('<s', '>s', '<=s', '>=s'):
                return f"($signed({left_name}) {verilog_op} $signed({right_name}))"
            return f"({left_name} {verilog_op} {right_name})"
        elif expr['type'] == 'unary_op':
            expr_id = self._expression_to_id(expr)
            if expr_id in self.node_id_to_name:
                return self.node_id_to_name[expr_id]
            operand_name = self._get_verilog_name_for_expression(expr.get('operand', {}))
            operator = expr.get('operator', '~')
            return f"({operator}{operand_name})"
        elif expr['type'] == 'ternary_op':
            expr_id = self._expression_to_id(expr)
            if expr_id in self.node_id_to_name:
                return self.node_id_to_name[expr_id]
            cond_name = self._get_verilog_name_for_expression(expr.get('condition', {}))
            true_name = self._get_verilog_name_for_expression(expr.get('if_true', {}))
            false_name = self._get_verilog_name_for_expression(expr.get('if_false', {}))
            return f"({cond_name} ? {true_name} : {false_name})"
        elif expr['type'] == 'reduction_op':
            expr_id = self._expression_to_id(expr)
            if expr_id in self.node_id_to_name:
                return self.node_id_to_name[expr_id]
            operand_name = self._get_verilog_name_for_expression(expr.get('operand', {}))
            operator = expr.get('operator', '|')
            return f"({operator}{operand_name})"
        else:
            # For complex expressions, use the node ID mapping if available
            expr_id = self._expression_to_id(expr)
            # Check if we have a generated name for this expression
            if expr_id in self.node_id_to_name:
                return self.node_id_to_name[expr_id]
            else:
                # Compute sanitized ID (e.g., "(~taken)" -> "invtaken")
                sanitized = self._sanitize_identifier(expr_id)
                # Before returning the bare sanitized name, try prefix recovery using
                # calling_node_id context. The calling node ID may be raw (e.g.
                # "cmpb_eq_(~taken & expr_4013)") or already sanitized. Sanitize it
                # to find the prefix (e.g. "cmpb_eq_invtaken").
                if calling_node_id and sanitized:
                    # Try multiple forms of the calling node name for the suffix search
                    calling_sanitized = self._sanitize_identifier(calling_node_id)
                    calling_verilog = self.node_id_to_name.get(calling_node_id, calling_sanitized)
                    suffix = "_" + sanitized
                    for calling_name in set([calling_node_id, calling_sanitized, calling_verilog]):
                        idx2 = calling_name.find(suffix)
                        if idx2 > -1:
                            prefixed_name = calling_name[:idx2 + len(suffix)]
                            # Search node_id_to_name values for this Verilog name
                            # (node IDs use raw syntax like "cmpb_eq_~taken")
                            for _nid, _vname in self.node_id_to_name.items():
                                if _vname == prefixed_name:
                                    return _vname
                            if prefixed_name in self.graph.nodes:
                                return self._get_node_verilog_ref(
                                    self.graph.nodes[prefixed_name])
                return sanitized

    def _expression_to_id(self, expr: Dict) -> str:
        """Convert expression to ID (same logic as in parser)."""
        if 'type' not in expr:
            return f"unknown_{id(expr)}"
        if expr['type'] == 'identifier':
            return expr['name']
        elif expr['type'] == 'array_access':
            array_id = self._expression_to_id(expr['target'])
            index_id = self._expression_to_id(expr['index'])
            base_id = f"{array_id}[{index_id}]"
            # Check if there's a _rd or _wr variant in the graph
            if f"{base_id}_rd" in self.graph.nodes:
                return f"{base_id}_rd"
            elif f"{base_id}_wr" in self.graph.nodes:
                return f"{base_id}_wr"
            else:
                return base_id
        elif expr['type'] == 'bit_slice':
            target_expr = expr.get('target') or expr.get('array', {})
            target_id = self._expression_to_id(target_expr)
            # Handle both 'range' tuple and separate 'high'/'low' fields
            if 'range' in expr:
                high, low = expr['range']
            else:
                high = expr.get('high', {}).get('value', 0) if isinstance(expr.get('high'), dict) else expr.get('high', 0)
                low = expr.get('low', {}).get('value', 0) if isinstance(expr.get('low'), dict) else expr.get('low', 0)
            base_id = f"{target_id}[{high}:{low}]"
            # Check for _rd/_wr variants
            if f"{base_id}_rd" in self.graph.nodes:
                return f"{base_id}_rd"
            elif f"{base_id}_wr" in self.graph.nodes:
                return f"{base_id}_wr"
            else:
                return base_id
        elif expr['type'] == 'binary_op':
            left_id = self._expression_to_id(expr['left'])
            right_id = self._expression_to_id(expr['right'])
            return f"({left_id} {expr['operator']} {right_id})"
        elif expr['type'] == 'literal':
            return str(expr['value'])
        elif expr['type'] == 'sized_literal':
            # Use format + original_digits when available (canonical form)
            width = expr.get('width', 1)
            fmt = expr.get('format')
            original_digits = expr.get('original_digits')
            if fmt and original_digits is not None:
                fmt_char = {'bin': 'b', 'hex': 'h', 'dec': 'd'}.get(fmt, 'b')
                return f"{width}'{fmt_char}{original_digits}"
            # Fallback to legacy compat keys
            elif 'bits' in expr:
                return f"{width}'b{expr.get('bits', '0')}"
            elif 'hex_digits' in expr:
                return f"{width}'h{expr.get('hex_digits', '0')}"
            elif 'dec_digits' in expr:
                return f"{width}'d{expr.get('dec_digits', '0')}"
            else:
                return f"{width}'d{expr.get('value', 0)}"
        elif expr['type'] == 'repetition':
            # For repetition, try to find the node
            count = expr.get('count', 1)
            inner_id = self._expression_to_id(expr.get('expression', {}))
            base_id = f"{{{count}{{{inner_id}}}}}"
            if base_id in self.graph.nodes:
                return base_id
            else:
                return base_id
        elif expr['type'] == 'concatenation':
            # For concatenation, recursively get Verilog names for sub-expressions
            # This ensures literals get proper width formatting
            parts = []
            for sub_expr in expr.get('parts', []):
                parts.append(self._get_verilog_name_for_expression(sub_expr))
            return "{" + ", ".join(parts) + "}"
        elif expr['type'] == 'ternary_op':
            # Handle ternary expression: condition ? true_val : false_val
            # Support both key naming conventions
            cond_id = self._expression_to_id(expr.get('condition', {}))
            true_id = self._expression_to_id(expr.get('if_true', {}))
            false_id = self._expression_to_id(expr.get('if_false', {}))
            return f"({cond_id} ? {true_id} : {false_id})"
        elif expr['type'] == 'unary_op':
            # Handle unary operations like ~, !, -
            operand_id = self._expression_to_id(expr.get('operand', {}))
            operator = expr.get('operator', '~')
            return f"({operator}{operand_id})"
        elif expr['type'] == 'reduction_op':
            # Handle reduction operations: |, &, ^ - reduce all bits to single bit
            operand_id = self._expression_to_id(expr.get('operand', {}))
            operator = expr.get('operator', '|')
            return f"({operator}{operand_id})"
        elif expr['type'] == 'cam_lookup':
            # CAM associative lookup: cam@[key] or cam@[key][set_idx]
            cam_id = self._expression_to_id(expr.get('cam', {}))
            key_id = self._expression_to_id(expr.get('key', {}))
            set_index = expr.get('set_index')
            if set_index:
                set_id = self._expression_to_id(set_index)
                return f"{cam_id}@[{key_id}][{set_id}]"
            else:
                return f"{cam_id}@[{key_id}]"
        elif expr['type'] == 'builtin_call':
            # Builtin function call like ctz(), clz()
            builtin = expr.get('builtin', 'ctz')
            operand_id = self._expression_to_id(expr.get('operand', {}))
            return f"{builtin}({operand_id})"
        else:
            return f"unknown_{hash(str(expr))}"

    def _fix_narrow_access_declarations(self):
        """Fix wire declarations for narrow memory accesses.

        During _generate_combinational_logic(), we discover which memory reads
        have narrow access (e.g., 8-bit byte load from 32-bit word). The wire
        declarations were generated earlier with the wrong width (32-bit),
        so we need to fix them here.
        """
        if not hasattr(self, 'narrow_access_wires') or not self.narrow_access_wires:
            return

        import re
        for wire_name, access_width in sorted(self.narrow_access_wires.items()):
            # Find and replace the declaration in self.declarations
            # Pattern: wire [31:0] wire_name;  ->  wire [access_width-1:0] wire_name;
            old_pattern = rf'(\s+wire\s+)\[\d+:0\]\s+{re.escape(wire_name)};'
            if access_width > 1:
                new_decl = rf'\1[{access_width-1}:0] {wire_name};'
            else:
                new_decl = rf'\1 {wire_name};'

            self.declarations = re.sub(old_pattern, new_decl, self.declarations)

    def _generate_sequential_logic(self):
        """Generate sequential logic for state updates."""
        # Preserve any seq_logic already added (e.g., from multi-cycle FP operations)
        if not hasattr(self, 'seq_logic'):
            self.seq_logic = ""

        # Generate global FP multi-cycle stall signal if we have multi-cycle FP operations
        self.fp_stall_signal = None
        if hasattr(self, 'fp_multicycle_stall_wires') and self.fp_multicycle_stall_wires:
            self.fp_stall_signal = 'fp_multicycle_stall'
            if self.fp_stall_signal not in self.declared_names:
                self.declarations += f"    wire {self.fp_stall_signal};\n"
                self.declared_names.add(self.fp_stall_signal)
            # Generate the OR of all FP stall signals
            stall_expr = ' || '.join(self.fp_multicycle_stall_wires)
            self.comb_logic += f"\n    // Global FP multi-cycle stall (stall PC and writes during div/sqrt)\n"
            self.comb_logic += f"    assign {self.fp_stall_signal} = {stall_expr};\n"

        # Find assignment edges to registers (only self-referential variables and true state)
        register_assignments = []
        # Also track bit_slice writes to array elements (e.g., xregs[idx][7:0] = value)
        array_bit_slice_writes = []
        # Track scalar bit_slice writes (e.g., xer[34] = carry) - writes to bit ranges of scalar registers
        scalar_bit_slice_writes = []

        # Sort for deterministic output
        for edge in sorted(self.graph.edges.values(), key=lambda e: (e.source.id, e.target.id)):
            if edge.data.get('type') == 'assignment':
                target = edge.target
                # Include:
                # 1. Non-arch-state variables that should be registers (self-referential)
                # 2. Arch-state that should be registers (not memory)
                # 3. _wr nodes for split ISA state (like pc_wr), but not memory writes (like rf[rd]_wr)
                # 4. Bit slice writes to array elements (like xregs[idx][7:0])
                # 5. Non-split isa_state (like 8086 flags) that are assigned but not self-referential
                # Check for _wr as SUFFIX to avoid matching nodes like conditional_mux_pc_wr_mux_...
                # Exclude array access _wr nodes like rf[rd]_wr and dmem[addr]_wr - these are handled by arch state mux
                # But NOT bit-range writes like xer[34:34]_wr (distinguished by ':' in the brackets)
                is_array_access_wr = (target.id.endswith('_wr') and '[' in target.id and ']' in target.id
                                      and ':' not in target.id)
                # Detect bit-range _wr nodes like xer[34:34]_wr - writes to specific bits of a scalar register
                is_bit_range_wr = (target.id.endswith('_wr') and '[' in target.id and ']' in target.id
                                   and ':' in target.id)
                is_split_isa_state = (target.id.endswith('_wr') and target.data.get('name') is not None
                                      and not is_array_access_wr and not is_bit_range_wr)
                # Check for bit_slice write to array element
                is_array_bit_slice_write = (target.data.get('type') == 'bit_slice' and
                                            target.data.get('access_mode') == 'write' and
                                            '_wr[' in target.id)  # Contains _wr[ indicating array write
                # Check for non-split isa_state (like flags) that need sequential assignment
                is_non_split_isa_state = (target.data.get('type') == 'isa_state' and
                                          target.is_arch_state and
                                          '_wr' not in target.id and
                                          not target.data.get('is_memory', False))

                if is_array_bit_slice_write:
                    # Check if this bit_slice write is handled by a memory_write_port
                    # If so, skip it (the memory_write_port will generate the write with proper enable)
                    expr = target.data.get('expression', {})
                    inner_target = expr.get('target', {})
                    bit_range = expr.get('range')
                    array_name = None
                    if inner_target.get('type') == 'array_access':
                        array_expr = inner_target.get('target', {})
                        if array_expr.get('type') == 'identifier':
                            array_name = array_expr.get('name')

                    # Check if there's a memory_write_port with matching (base_memory, bit_range)
                    has_write_port = False
                    if array_name and bit_range:
                        # Look for memory_write_port nodes with matching bit_range
                        for node in self.graph.nodes.values():
                            if (node.data.get('type') == 'memory_write_port' and
                                node.data.get('base_memory') == array_name and
                                node.data.get('bit_range') == bit_range):
                                has_write_port = True
                                break

                    if not has_write_port:
                        array_bit_slice_writes.append(edge)
                elif is_bit_range_wr:
                    scalar_bit_slice_writes.append(edge)
                elif ((self._should_be_register(target) and not target.data.get('is_memory', False)) or
                      is_split_isa_state or is_non_split_isa_state):
                    # Skip ext push states - handled by dedicated ext push sequential block
                    if target.data.get('is_external') and target.data.get('is_push'):
                        continue
                    register_assignments.append(edge)

        # Find pipeline_input edges to pipeline registers (uarch_state)
        pipeline_register_assignments = []
        # Sort for deterministic output
        for edge in sorted(self.graph.edges.values(), key=lambda e: (e.source.id, e.target.id)):
            if edge.data.get('type') == 'pipeline_input':
                target = edge.target
                # Pipeline registers are uarch_state or have type 'pipeline_register'
                if target.is_uarch_state or target.data.get('type') == 'pipeline_register':
                    pipeline_register_assignments.append(edge)

        if register_assignments or pipeline_register_assignments or array_bit_slice_writes or scalar_bit_slice_writes:
            self.seq_logic += "    always @(posedge clk) begin\n"
            self.seq_logic += "        if (reset) begin\n"

            # Reset assignments
            for reg_decl in self.reg_declarations:
                name = reg_decl['name']
                reset_wire = reg_decl['reset_wire']
                self.seq_logic += f"            {name} <= {reset_wire};\n"

            # Check if we have external memory stall signal to gate state updates
            mem_stall_signal = getattr(self, '_mem_ext_stall_signal', None)
            if mem_stall_signal:
                # Get the memory stage stall control signal if available
                # This allows Writeback registers to update when dcache completes even if icache is busy
                mem_stage_stall = getattr(self, '_memory_stage_stall_ctrl', None)
                if mem_stage_stall:
                    # Use OR: update when no ext stall OR when memory stage stall releases
                    self.seq_logic += f"        end else if (!{mem_stall_signal} || !{mem_stage_stall}) begin\n"
                    self.seq_logic += f"            // State updates: run when no external stall OR when dcache completes (for Writeback)\n"
                else:
                    self.seq_logic += f"        end else if (!{mem_stall_signal}) begin\n"
                    self.seq_logic += f"            // State updates gated by external memory stall\n"
            else:
                self.seq_logic += "        end else begin\n"

            # Generate kill signal warning if there are sensitive signals
            # TODO: Full sensitive (kill) signal implementation requires wrapping
            # all state updates in kill signal checks. For now, we just note their presence.
            if self.sensitive_signals:
                kill_signals = ", ".join([sig['name'] for sig in self.sensitive_signals])
                self.seq_logic += f"            // WARNING: Sensitive signals detected ({kill_signals})\n"
                self.seq_logic += f"            // TODO: Implement full kill logic to suppress updates when sensitive signals are active\n"

            # Deduplicate register assignments by target name to avoid duplicate updates
            seen_targets = set()
            deduplicated_assignments = []
            for edge in register_assignments:
                target = edge.target
                # For _wr nodes, the actual target is the corresponding register
                if target.id.endswith('_wr'):
                    target_key = target.id.replace('_wr', '')
                else:
                    target_key = target.data.get('name', target.id)
                if target_key not in seen_targets:
                    seen_targets.add(target_key)
                    deduplicated_assignments.append(edge)

            # Register update assignments
            for edge in deduplicated_assignments:
                # Handle split nodes: if target is _wr node, update _rd register
                target = edge.target
                # Check for _wr as SUFFIX to avoid matching nodes like conditional_mux_pc_wr_mux_...
                if target.id.endswith('_wr'):
                    # This is a write node
                    # Check if this is an array being updated by a ternary with memory_write
                    source = edge.source
                    if self._is_array_ternary(source):
                        # Special case: ILA-style array update via ternary
                        self._generate_ila_array_write(target, source)
                        continue

                    # Normal scalar _wr node - update the register from the _wr wire
                    # Check if this is an array access (contains [...])
                    if '[' in target.id and ']' in target.id:
                        # For array accesses like rf[rd]_wr or dmem[addr]_wr,
                        # strip just the _wr suffix to get rf[rd] or dmem[addr]
                        target_name = target.id.replace('_wr', '')
                    else:
                        # For scalars, check if the _rd node was declared as a wire
                        # (has state_update edge) or as a reg (no state_update edge)
                        rd_node_id = target.id.replace('_wr', '_rd')
                        rd_node = self.graph.nodes.get(rd_node_id)
                        if rd_node:
                            # Check if _rd has state_update edge (means it was declared as wire)
                            has_state_update = any(e.data.get('type') == 'state_update'
                                                   for e in rd_node.incoming_edges)
                            if has_state_update:
                                # _rd is a wire, use base name (without _rd suffix) as target
                                base_name = target.id.replace('_wr', '')
                            else:
                                # _rd is a reg, use _rd as target (like pc_rd)
                                base_name = rd_node_id
                        else:
                            # Fallback: use base name without _wr
                            base_name = target.id.replace('_wr', '')
                        target_name = base_name

                    # For memory arrays, _rd should read from base array
                    if target.data.get('is_memory', False):
                        source_name = target.data.get('name', target.id.replace('_wr', ''))
                    else:
                        # Use the _wr wire as the source
                        wr_name = self.node_id_to_name.get(target.id, self._sanitize_identifier(target.id))
                        source_name = wr_name

                    # Check if this is an array (has array_depth)
                    if target.data.get('array_depth'):
                        array_depth = target.data['array_depth']
                        if array_depth <= 32:
                            actual_depth = 2 ** array_depth
                        else:
                            actual_depth = array_depth
                        actual_depth = min(actual_depth, 1024)
                        self.seq_logic += f"            // Copy array {base_name}\n"
                        self.seq_logic += f"            for (i = 0; i < {actual_depth}; i = i + 1) begin\n"
                        self.seq_logic += f"                {target_name}[i] = {source_name}[i];\n"
                        self.seq_logic += f"            end\n"
                        continue
                else:
                    target_name = edge.target.data['name']
                    source = edge.source
                    if source.data.get('type') == 'identifier' or source.data.get('name'):
                        source_name = source.data.get('name', self.node_id_to_name.get(source.id, self._sanitize_identifier(source.id)))
                    else:
                        source_name = self.node_id_to_name.get(source.id, self._sanitize_identifier(source.id))

                # Check if there's a stall signal connected to this register (same as pipeline registers)
                # For split _rd/_wr nodes, check the _rd node for stall edges
                stall_signal = None
                check_node = target
                if target.id.endswith('_wr'):
                    # Check the corresponding _rd node for stall edges
                    rd_node_id = target.id.replace('_wr', '_rd')
                    rd_node = self.graph.nodes.get(rd_node_id)
                    if rd_node:
                        check_node = rd_node

                for incoming_edge in sorted(check_node.incoming_edges, key=lambda e: (e.source.id, e.target.id)):
                    if incoming_edge.data.get('type') == 'stall':
                        stall_node = incoming_edge.source
                        stall_signal_name = self.node_id_to_name.get(stall_node.id, self._sanitize_identifier(stall_node.id))
                        # In dual-issue: don't gate p1 registers by p0 stall controllers
                        # This prevents deadlock when p0 stalls due to p1 hazard
                        is_p1_target = target.id.startswith('p1_')
                        is_p0_stall = stall_node.id.startswith('p0_')
                        if is_p1_target and is_p0_stall:
                            continue  # Skip this stall - p1 should not be gated by p0 stalls
                        stall_signal = stall_signal_name
                        break

                # Also check for write_stall_signals in node data (used by memory latency stall)
                stall_signals = []
                if stall_signal:
                    stall_signals.append(stall_signal)
                write_stalls = check_node.data.get('write_stall_signals', [])
                for stall_id in write_stalls:
                    stall_node = self.graph.nodes.get(stall_id)
                    if stall_node:
                        stall_name = self.node_id_to_name.get(stall_id, self._sanitize_identifier(stall_id))
                        if stall_name not in stall_signals:
                            stall_signals.append(stall_name)

                # Add FP multi-cycle stall if we have multi-cycle FP operations
                if self.fp_stall_signal and self.fp_stall_signal not in stall_signals:
                    stall_signals.append(self.fp_stall_signal)

                # Check for enable condition from edge (e.g., from 'when' clause in ISA)
                # This handles conditional writes like: cpsr when (cond_pass & s_bit) = new_cpsr
                enable_expr = edge.data.get('enable')
                enable_cond = None
                if enable_expr:
                    # First, try to find the enable via write_enable edge on the target node
                    # This resolves the actual enable wire (e.g., fp_sqrt_d_f1_enable)
                    # instead of sanitizing the expression (which may produce a different name)
                    for we_edge in target.incoming_edges:
                        if we_edge.data.get('type') == 'write_enable':
                            en_node = we_edge.source
                            enable_cond = self.node_id_to_name.get(en_node.id, self._sanitize_identifier(en_node.id))
                            break
                    if not enable_cond:
                        enable_cond = self._get_verilog_name_for_expression(enable_expr)
                        # Check if this enable signal exists or if we need to merge instruction-specific versions
                        enable_cond = self._get_or_create_merged_enable(enable_cond)

                # For ISA state gated by a Decode stall: use stall_and_not_flush
                # so that control hazard flushes (taken branches/jumps) override
                # the Decode stall and allow the PC to update to the branch target.
                # Only Decode-stage stalls are overridden; structural stalls (f-stage,
                # Memory-stage) must NOT be overridden by flushes.
                # This matches the Rust verilog_generator's stall_and_not_flush
                # mechanism (rust_core/src/verilog_generator.rs:3950-3961).
                if stall_signals and check_node.data.get('type') == 'isa_state':
                    # Find the control hazard flush signal for this pipe
                    pipe_prefix = ''
                    for sn in stall_signals:
                        if sn.startswith('p0_') or sn.startswith('p1_'):
                            pipe_prefix = sn[:3]
                            break
                    flush_name = f"{pipe_prefix}control_hazard_flush" if pipe_prefix else "control_hazard_flush"
                    flush_node = self.graph.nodes.get(flush_name)
                    if flush_node:
                        # Split stalls: Decode stalls get && !flush, others stay raw
                        decode_stalls = [s for s in stall_signals if '_Decode_stall_ctrl' in s]
                        other_stalls = [s for s in stall_signals if '_Decode_stall_ctrl' not in s]
                        parts = []
                        for ds in decode_stalls:
                            parts.append(f"({ds} && !{flush_name})")
                        parts.extend(other_stalls)
                        stall_cond = ' || '.join(parts)
                        self.seq_logic += f"            if (!({stall_cond})) {target_name} <= {source_name};\n"
                    else:
                        stall_cond = ' || '.join(stall_signals)
                        self.seq_logic += f"            if (!({stall_cond})) {target_name} <= {source_name};\n"
                elif stall_signals and enable_cond:
                    stall_cond = ' || '.join(stall_signals)
                    # Use OR: update when not stalled OR when multicycle enable fires
                    # (enable fires at final cycle of multicycle op while stall is still active)
                    self.seq_logic += f"            if (!({stall_cond}) || ({enable_cond})) {target_name} <= {source_name};\n"
                elif stall_signals:
                    stall_cond = ' || '.join(stall_signals)
                    self.seq_logic += f"            if (!({stall_cond})) {target_name} <= {source_name};\n"
                elif enable_cond:
                    self.seq_logic += f"            if ({enable_cond}) {target_name} <= {source_name};\n"
                else:
                    self.seq_logic += f"            {target_name} <= {source_name};\n"

            # Generate pipeline register updates
            for edge in pipeline_register_assignments:
                target = edge.target
                source = edge.source
                target_name = self.node_id_to_name.get(target.id, self._sanitize_identifier(target.id))
                # Use _get_node_verilog_ref to properly inline concatenations/repetitions
                source_name = self._get_node_verilog_ref(source)

                # Dual-issue P1 valid: When cross-coupled stall controllers exist
                # (both pipes stall together), P1's valid should use the standard
                # stall-gated pattern (hold during stall) rather than bubble injection.
                # The bubble injection pattern (!stall && !flush) was designed for
                # single-pipe stalls but incorrectly kills P1's instruction during
                # cross-coupled stalls by setting valid=0 instead of holding it.
                # With cross-coupling, bubble injection into XMW is handled by
                # valid_and_not_stall, so P1's Decode valid should just be held.
                p0_stall_for_p1_valid = None  # Disabled: use standard stall-gated path

                # Check if there's a stall signal connected to this pipeline register
                stall_signal = None
                for incoming_edge in sorted(target.incoming_edges, key=lambda e: (e.source.id, e.target.id)):
                    if incoming_edge.data.get('type') == 'stall':
                        stall_node = incoming_edge.source
                        stall_signal = self.node_id_to_name.get(stall_node.id, self._sanitize_identifier(stall_node.id))
                        break

                # Also check for stall_gated attribute (for operand registers in bypass)
                if not stall_signal and target.data.get('stall_gated'):
                    # Use the global Decode stall controller
                    stall_signal = 'PIPE_Decode_stall_ctrl'

                # Check if there's a valid_gate signal (for result registers in bypass mode)
                # This prevents garbage from bubbles overwriting valid results
                valid_gate_signal = None
                for incoming_edge in target.incoming_edges:
                    if incoming_edge.data.get('type') == 'valid_gate':
                        valid_gate_node = incoming_edge.source
                        valid_gate_signal = self.node_id_to_name.get(valid_gate_node.id, self._sanitize_identifier(valid_gate_node.id))
                        break

                # Check if there's a flush signal connected to this pipeline register
                # (used by dual-issue control hazard handling)
                flush_signal = None
                for incoming_edge in sorted(target.incoming_edges, key=lambda e: (e.source.id, e.target.id)):
                    if incoming_edge.data.get('type') == 'flush':
                        flush_node = incoming_edge.source
                        flush_signal = self.node_id_to_name.get(flush_node.id, self._sanitize_identifier(flush_node.id))
                        break

                # Generate the conditional assignment based on stall and/or valid_gate signals
                # Special case: P1 valid signal with bubble injection
                if p0_stall_for_p1_valid and flush_signal:
                    # P1's valid = !stall && !flush && [valid_gate] (bubble when stall OR flush OR blocked)
                    cond = f"!{p0_stall_for_p1_valid} && !{flush_signal}"
                    if valid_gate_signal:
                        cond += f" && {valid_gate_signal}"
                    self.seq_logic += f"            {target_name} <= {cond};\n"
                elif p0_stall_for_p1_valid:
                    # P1's valid becomes !p0_stall_ctrl [&& valid_gate] (0 when P0 stalls = bubble)
                    # This allows P1 to complete and then clear the hazard condition
                    cond = f"!{p0_stall_for_p1_valid}"
                    if valid_gate_signal:
                        cond += f" && {valid_gate_signal}"
                    self.seq_logic += f"            {target_name} <= {cond};\n"
                elif flush_signal and '_valid_PIPE' in target.id:
                    # Valid signal with flush: when flush, force 0; otherwise propagate source (when stall, hold)
                    # Use stall_and_not_flush: a flush must override the stall so
                    # the Decode valid can be killed (preventing the stalled
                    # instruction from executing after the branch redirect).
                    # Only override Decode-stage stalls, not structural stalls.
                    if stall_signal and '_Decode_stall_ctrl' in stall_signal:
                        self.seq_logic += f"            if (!{stall_signal} || {flush_signal}) {target_name} <= ({flush_signal}) ? 1'b0 : {source_name};\n"
                    elif stall_signal:
                        self.seq_logic += f"            if (!{stall_signal}) {target_name} <= ({flush_signal}) ? 1'b0 : {source_name};\n"
                    else:
                        self.seq_logic += f"            {target_name} <= ({flush_signal}) ? 1'b0 : {source_name};\n"
                elif stall_signal and valid_gate_signal:
                    self.seq_logic += f"            if (!{stall_signal} && {valid_gate_signal}) {target_name} <= {source_name};\n"
                elif stall_signal:
                    self.seq_logic += f"            if (!{stall_signal}) {target_name} <= {source_name};\n"
                elif valid_gate_signal:
                    self.seq_logic += f"            if ({valid_gate_signal}) {target_name} <= {source_name};\n"
                else:
                    self.seq_logic += f"            {target_name} <= {source_name};\n"

            # Generate renamer pipeline registers (uarch_rd, old_phys, write_valid: Decode → Writeback)
            #
            # D→E stage: flush zeros these registers (prevents flushed Decode instruction
            #   from propagating a stale allocation through the pipeline). Also gated by
            #   Decode stall so stalled instructions don't re-enter Execute.
            # Later stages (E→M, M→WB): always update, NO flush zeroing — valid in-flight
            #   instructions at Memory/Writeback must not be killed.
            if hasattr(self, '_renamer_pipe_regs') and self._renamer_pipe_regs:
                self.seq_logic += "\n            // Renamer pipeline registers (Decode -> Writeback)\n"
                stall_signal = self._find_decode_stall_signal()
                flush_signal = self._find_flush_signal()

                for pipe_info in self._renamer_pipe_regs:
                    num_wp = pipe_info['num_write_ports']
                    pd = pipe_info['pipe_depth']
                    prw = pipe_info['phys_reg_width']
                    for i in range(num_wp):
                        for d in range(pd):
                            src_wp = pipe_info['piped_write_phys'][i][d]
                            dst_wp = pipe_info['piped_write_phys'][i][d + 1]
                            src_op = pipe_info['piped_old_phys'][i][d]
                            dst_op = pipe_info['piped_old_phys'][i][d + 1]
                            src_wv = pipe_info['piped_write_valid'][i][d]
                            dst_wv = pipe_info['piped_write_valid'][i][d + 1]

                            if d == 0:
                                # D→E: flush zeros + stall gating
                                if flush_signal:
                                    self.seq_logic += f"            if ({flush_signal}) begin\n"
                                    self.seq_logic += f"                {dst_wp} <= {prw}'d0;\n"
                                    self.seq_logic += f"                {dst_op} <= {prw}'d0;\n"
                                    self.seq_logic += f"                {dst_wv} <= 1'b0;\n"
                                    if stall_signal:
                                        self.seq_logic += f"            end else if (!{stall_signal}) begin\n"
                                    else:
                                        self.seq_logic += f"            end else begin\n"
                                elif stall_signal:
                                    self.seq_logic += f"            if (!{stall_signal}) begin\n"
                                else:
                                    self.seq_logic += f"            begin\n"
                                self.seq_logic += f"                {dst_wp} <= {src_wp};\n"
                                self.seq_logic += f"                {dst_op} <= {src_op};\n"
                                self.seq_logic += f"                {dst_wv} <= {src_wv};\n"
                                self.seq_logic += f"            end\n"
                            else:
                                # E→M, M→WB: always update, no flush zeroing
                                self.seq_logic += f"            {dst_wp} <= {src_wp};\n"
                                self.seq_logic += f"            {dst_op} <= {src_op};\n"
                                self.seq_logic += f"            {dst_wv} <= {src_wv};\n"

            # Generate array bit slice writes (e.g., xregs[idx][7:0] <= value)
            # Group writes by target to handle case statement conditional writes
            target_writes = {}  # key: (array_name, index_expr_str, high, low) -> list of (enable_expr, source_name)
            for edge in array_bit_slice_writes:
                target = edge.target
                source = edge.source
                # Extract array name, index, and bit range from the expression
                expr = target.data.get('expression', {})
                if expr.get('type') == 'bit_slice':
                    inner_target = expr.get('target', {})
                    bit_range = expr.get('range', (7, 0))
                    high, low = bit_range

                    if inner_target.get('type') == 'array_access':
                        # Get array base name
                        array_expr = inner_target.get('target', {})
                        if array_expr.get('type') == 'identifier':
                            array_name = array_expr.get('name', 'unknown')
                        else:
                            array_name = self._sanitize_identifier(str(array_expr))

                        # Get index expression - need to convert to Verilog name
                        index_expr = inner_target.get('index', {})
                        index_name = self._get_verilog_name_for_expression(index_expr)

                        # Get source value
                        source_name = self.node_id_to_name.get(source.id, self._sanitize_identifier(source.id))

                        # Check for enable condition from edge data (case statement arms)
                        enable_expr = edge.data.get('enable')
                        enable_name = None
                        if enable_expr:
                            enable_name = self._get_verilog_name_for_expression(enable_expr)

                        # Group by target
                        key = (array_name, index_name, high, low)
                        if key not in target_writes:
                            target_writes[key] = []
                        target_writes[key].append((enable_name, source_name))

            # Generate assignments, merging conditional writes to same target
            for (array_name, index_name, high, low), writes in sorted(target_writes.items()):
                if len(writes) == 1 and writes[0][0] is None:
                    # Single unconditional write
                    source_name = writes[0][1]
                    if high == low:
                        self.seq_logic += f"            {array_name}[{index_name}][{high}] <= {source_name};\n"
                    else:
                        self.seq_logic += f"            {array_name}[{index_name}][{high}:{low}] <= {source_name};\n"
                else:
                    # Multiple writes or conditional writes - generate if-else chain
                    # Filter out no-op writes (where source reads from same location as target)
                    actual_writes = []
                    for enable_name, source_name in writes:
                        # Check if this is a no-op (writing same value back)
                        # A no-op looks like: xregs[idx][15:8] <= xregs[idx][15:8]
                        # The source_name would reference the same array/index/bits
                        is_noop = source_name.startswith(f'{array_name}_') and f'_{high}_{low}' in source_name
                        if not is_noop:
                            actual_writes.append((enable_name, source_name))

                    if len(actual_writes) == 0:
                        # All writes were no-ops, skip
                        continue
                    elif len(actual_writes) == 1 and actual_writes[0][0] is not None:
                        # Single conditional write
                        enable_name, source_name = actual_writes[0]
                        if high == low:
                            self.seq_logic += f"            if ({enable_name}) {array_name}[{index_name}][{high}] <= {source_name};\n"
                        else:
                            self.seq_logic += f"            if ({enable_name}) {array_name}[{index_name}][{high}:{low}] <= {source_name};\n"
                    else:
                        # Multiple conditional writes - generate if-else chain
                        first = True
                        for enable_name, source_name in actual_writes:
                            if enable_name:
                                keyword = "if" if first else "else if"
                                if high == low:
                                    self.seq_logic += f"            {keyword} ({enable_name}) {array_name}[{index_name}][{high}] <= {source_name};\n"
                                else:
                                    self.seq_logic += f"            {keyword} ({enable_name}) {array_name}[{index_name}][{high}:{low}] <= {source_name};\n"
                                first = False
                            else:
                                # Unconditional write as else clause
                                if high == low:
                                    self.seq_logic += f"            else {array_name}[{index_name}][{high}] <= {source_name};\n"
                                else:
                                    self.seq_logic += f"            else {array_name}[{index_name}][{high}:{low}] <= {source_name};\n"

            # Generate scalar bit-range writes (e.g., xer[34:34] <= xer_34_34_wr)
            # These must come AFTER full register writes so that Verilog last-assignment-wins
            # semantics allow the bit-range to override the specific bits.
            # Group by parent register for clean output.
            if scalar_bit_slice_writes:
                import re
                # Group by parent register name
                parent_groups = {}  # parent_name -> list of (high, low, wr_signal_name)
                for edge in scalar_bit_slice_writes:
                    target = edge.target
                    # Extract parent name and bit range from node ID: "name[high:low]_wr"
                    m = re.match(r'^(.+)\[(\d+):(\d+)\]_wr$', target.id)
                    if m:
                        parent_name = m.group(1)
                        high = int(m.group(2))
                        low = int(m.group(3))
                        wr_name = self.node_id_to_name.get(target.id, self._sanitize_identifier(target.id))
                        if parent_name not in parent_groups:
                            parent_groups[parent_name] = []
                        parent_groups[parent_name].append((high, low, wr_name))

                for parent_name in sorted(parent_groups.keys()):
                    writes = sorted(parent_groups[parent_name])
                    # Find enables for full-register write to this parent
                    # When a register has both full writes (e.g., xer <= xer_wr from mtspr)
                    # and bit-slice writes (e.g., xer[34] from addic), the bit-slice write
                    # must be gated to prevent its default value overriding the full write.
                    full_write_enables = self._find_full_register_write_enables(parent_name)
                    if full_write_enables:
                        enable_cond = ' || '.join(sorted(full_write_enables))
                        self.seq_logic += f"            if (!({enable_cond})) begin\n"
                        for high, low, wr_name in writes:
                            if high == low:
                                self.seq_logic += f"                {parent_name}[{high}] <= {wr_name};\n"
                            else:
                                self.seq_logic += f"                {parent_name}[{high}:{low}] <= {wr_name};\n"
                        self.seq_logic += f"            end\n"
                    else:
                        for high, low, wr_name in writes:
                            if high == low:
                                self.seq_logic += f"            {parent_name}[{high}] <= {wr_name};\n"
                            else:
                                self.seq_logic += f"            {parent_name}[{high}:{low}] <= {wr_name};\n"

            self.seq_logic += "        end\n"
            self.seq_logic += "    end\n\n"

        # Handle external outputs (ext push) - these need data and valid signal assignments
        external_output_assignments = []
        # Sort for deterministic output
        for edge in sorted(self.graph.edges.values(), key=lambda e: (e.source.id, e.target.id)):
            if edge.data.get('type') == 'assignment':
                target = edge.target
                # Check if target is an external output
                if target.data and target.data.get('is_external') and target.data.get('is_push'):
                    external_output_assignments.append(edge)

        if external_output_assignments:
            self.seq_logic += "    // External output assignments (ext push)\n"
            self.seq_logic += "    always @(posedge clk) begin\n"
            self.seq_logic += "        if (reset) begin\n"
            # Reset all external outputs (and auto _valid signals for _wr ports)
            for ext_output in self.external_outputs:
                name = ext_output['name']
                bit_width = ext_output['bit_width']
                if bit_width > 1:
                    self.seq_logic += f"            {name} <= {bit_width}'d0;\n"
                else:
                    self.seq_logic += f"            {name} <= 1'b0;\n"
                # Only auto-generate _valid reset for _wr ports;
                # non-_wr ports have _valid managed by ISA state logic
                if name.endswith("_wr"):
                    self.seq_logic += f"            {name}_valid <= 1'b0;\n"
            self.seq_logic += "        end else begin\n"
            # Generate assignments for each external output with write-enable-gated valid
            for edge in external_output_assignments:
                target_name = self.node_id_to_name.get(edge.target.id, self._sanitize_identifier(edge.target.id))
                source = edge.source
                source_name = self.node_id_to_name.get(source.id, self._sanitize_identifier(source.id))

                # Find write-enable condition for this push state
                # Look for write_enable edge on the target node, or enable in edge data
                enable_cond = None
                target_node = edge.target
                for we_edge in target_node.incoming_edges:
                    if we_edge.data.get('type') == 'write_enable':
                        en_node = we_edge.source
                        if en_node.id in self.node_id_to_name:
                            enable_cond = self.node_id_to_name[en_node.id]
                        break
                if not enable_cond:
                    # Build enable expression from edge data (the 'enable' AST)
                    enable_expr = edge.data.get('enable')
                    if enable_expr:
                        enable_cond = self._build_enable_expression(enable_expr)

                # Gate with instruction enable (like regular sequential writes)
                # Extract instruction prefix from source node ID
                instr_enable = None
                known_prefixes = self._get_instruction_prefixes()
                for prefix in known_prefixes:
                    if source.id.startswith(prefix):
                        instr_name = prefix.rstrip('_')
                        candidate = f"{instr_name}_enable"
                        if candidate in self.node_id_to_name:
                            instr_enable = self.node_id_to_name[candidate]
                        elif candidate in self.graph.nodes:
                            instr_enable = candidate
                        break
                if instr_enable and enable_cond:
                    enable_cond = f"({enable_cond} & {instr_enable})"
                elif instr_enable:
                    enable_cond = instr_enable

                # Only auto-drive _valid for _wr ports; non-_wr ports have
                # _valid managed by ISA state logic to avoid double-drivers
                auto_valid = target_name.endswith("_wr")
                if enable_cond:
                    # Conditional push: valid pulses only when write-enable is active
                    if auto_valid:
                        self.seq_logic += f"            {target_name}_valid <= {enable_cond};\n"
                    self.seq_logic += f"            if ({enable_cond}) {target_name} <= {source_name};\n"
                else:
                    # Unconditional push: valid is always high
                    self.seq_logic += f"            {target_name} <= {source_name};\n"
                    if auto_valid:
                        self.seq_logic += f"            {target_name}_valid <= 1'b1;\n"
            self.seq_logic += "        end\n"
            self.seq_logic += "    end\n\n"

        # Handle RAS (Return Address Stack) sequential logic
        self._generate_ras_sequential_logic()

        # Handle memory writes (both direct and through memory_write_port nodes)
        memory_writes = []

        # Direct memory writes (from single-instruction processors)
        # Sort for deterministic output
        for edge in sorted(self.graph.edges.values(), key=lambda e: (e.source.id, e.target.id)):
            if (edge.data.get('type') == 'assignment' and
                edge.target.data.get('type') == 'array_access'):
                # Check if the array being accessed is a memory
                target_expr = edge.data.get('left', {})
                if target_expr.get('type') == 'array_access':
                    array_expr = target_expr.get('target', {})
                    if array_expr.get('type') == 'identifier':
                        array_name = array_expr['name']
                        if array_name in self.graph.nodes:
                            array_node = self.graph.nodes[array_name]
                            if array_node.data.get('is_memory', False):
                                memory_writes.append(edge)

        # Memory write ports (from merged processors)
        memory_write_ports = []
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if node.data.get('type') == 'memory_write_port':
                # Find write_data and write_address edges
                write_data_edge = None
                write_addr_edge = None
                memory_edge = None

                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'write_data':
                        write_data_edge = edge
                    elif edge.data.get('type') == 'write_address':
                        write_addr_edge = edge

                for edge in node.outgoing_edges:
                    if edge.data.get('type') == 'memory_write':
                        memory_edge = edge

                if write_data_edge and write_addr_edge and memory_edge:
                    # Collect write enable signals from the data mux
                    write_enables = []
                    data_mux_node = write_data_edge.source

                    # Check for both 'multiplexer' type and 'mux' type (merged graphs may use 'mux')
                    if data_mux_node.data.get('type') in ['multiplexer', 'mux', 'port_data_merge', 'memory_data_merge']:
                        # Look for select signals that are write enables - sorted for determinism
                        for edge in sorted(data_mux_node.incoming_edges, key=lambda e: (e.source.id, e.target.id)):
                            edge_type = edge.data.get('type')
                            if edge_type in ['mux_select', 'port_select']:
                                select_node = edge.source
                                # Check if this is an enable signal
                                # (either "_write_enable" for rf or "_enable_and" for memory or "_enable" for stores)
                                if ('_write_enable' in select_node.id or
                                    'write_enable' in select_node.data.get('name', '') or
                                    '_enable_and' in select_node.id or
                                    '_enable' in select_node.id):
                                    write_enables.append(select_node)
                    else:
                        pass  # Mux node is not of recognized type

                    # Check for validity_check edges on the memory_write_port node
                    validity_signal = None
                    for edge in sorted(node.incoming_edges, key=lambda e: (e.source.id, e.target.id)):
                        if edge.data.get('type') == 'validity_check':
                            validity_signal = edge.source
                            break

                    memory_name = memory_edge.target.data.get('name', memory_edge.target.id)

                    # Skip externalized memories - writes go to external port, not internal array
                    if memory_name in self.externalized_memories:
                        # Check if already added during _prescan_memory_write_ports
                        already_added = any(p['port_name'] == node.id for p in self.memory_write_ports)
                        if not already_added:
                            # Track the write port info for external port connections
                            mem_info = self.memory_declarations.get(memory_name, {})
                            data_source_node = write_data_edge.source
                            data_name = self.node_id_to_name.get(data_source_node.id,
                                                                 self._sanitize_identifier(data_source_node.id))

                            addr_name = self.node_id_to_name.get(write_addr_edge.source.id,
                                                                 self._sanitize_identifier(write_addr_edge.source.id))
                            # Get enable signal - use combined enable or create OR
                            enable_name = node.data.get('combined_write_enable', '')
                            if not enable_name and write_enables:
                                enable_name = self.node_id_to_name.get(write_enables[0].id,
                                                                        self._sanitize_identifier(write_enables[0].id))
                            # Get combined byte enable signal if one was created during externalization
                            combined_byte_enable = node.data.get('combined_byte_enable', '')
                            if combined_byte_enable:
                                combined_byte_enable = self.node_id_to_name.get(
                                    combined_byte_enable, self._sanitize_identifier(combined_byte_enable))

                            self.memory_write_ports.append({
                                'mem': memory_name,
                                'port_name': node.id,
                                'addr_signal': addr_name,
                                'data_signal': data_name,
                                'enable_signal': enable_name,
                                'data_width': mem_info.get('bit_width', 32),
                                'addr_width': mem_info.get('addr_width', 32),
                                'combined_byte_enable': combined_byte_enable
                            })
                        continue  # Skip internal array write

                    memory_write_ports.append({
                        'memory': memory_name,
                        'data': write_data_edge.source,
                        'address': write_addr_edge.source,
                        'write_enables': write_enables,
                        'validity_signal': validity_signal,
                        'port_node': node  # Store the write port node for later reference
                    })

        # Conditional array writes (from ILA transformation)
        conditional_writes = []
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if node.data.get('type') == 'array_access' and node.data.get('is_write'):
                # This is a conditional write from ILA transformation
                # Extract write_enable, write_data, array, and address
                write_enable = None
                write_data = None
                base_array = None
                address = None

                for edge in node.incoming_edges:
                    edge_type = edge.data.get('type')
                    position = edge.data.get('position')

                    if edge_type == 'write_enable':
                        write_enable = edge.source
                    elif edge_type == 'write_data':
                        write_data = edge.source
                    elif edge_type == 'operand':
                        if position == 0:
                            base_array = edge.source
                        elif position == 1:
                            address = edge.source

                if write_enable and write_data and base_array and address:
                    # Find the target (should be _wr node) - optional for ILA writes
                    target = None
                    for edge in node.outgoing_edges:
                        if edge.data.get('type') == 'assignment':
                            target = edge.target
                            break

                    # Add to conditional writes even if no target (ILA register file writes)
                    conditional_writes.append({
                        'node': node,
                        'enable': write_enable,
                        'data': write_data,
                        'array': base_array,
                        'address': address,
                        'target': target  # May be None for ILA writes
                    })

        if memory_writes or memory_write_ports or conditional_writes:
            self.seq_logic += "    always @(posedge clk) begin\n"
            # Gate memory writes with external memory stall signal if present
            mem_stall_signal = getattr(self, '_mem_ext_stall_signal', None)
            if mem_stall_signal:
                self.seq_logic += f"        if (!reset && !{mem_stall_signal}) begin\n"
            else:
                self.seq_logic += "        if (!reset) begin\n"

            # Direct memory writes
            for edge in memory_writes:
                target_expr = edge.data['left']
                array_name = target_expr['target']['name']

                # Use edge.source for the data to write
                source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))

                # Find instruction-specific write enable signal and address
                write_enable = None
                instr_prefix = None
                source_id = edge.source.id

                # Check if source has instruction prefix (e.g., "sw_r2")
                for instr_name in self.graph.nodes.keys():
                    if instr_name.endswith('_enable_and'):
                        potential_prefix = instr_name.replace('_enable_and', '')
                        if source_id.startswith(potential_prefix + '_'):
                            instr_prefix = potential_prefix
                            break

                # Find the address node by examining the actual array_access write node's edges
                # This is more robust than using metadata, which may have stale node names after merging
                index_name = None
                array_node = None

                # edge.target is the array_access write node
                write_node = edge.target

                # Find the actual address and array nodes from incoming edges
                for in_edge in write_node.incoming_edges:
                    if in_edge.data.get('type') == 'array_index':
                        position = in_edge.data.get('position')
                        if position == 0:
                            array_node = in_edge.source
                        elif position == 1:
                            # This is the address node - use its actual ID
                            index_name = self.node_id_to_name.get(in_edge.source.id,
                                                                 self._sanitize_identifier(in_edge.source.id))

                # Try to find instruction enable signal
                # Extract instruction prefix from write node or address node
                if instr_prefix:
                    # Also look for enable signal
                    enable_node_id = f"{instr_prefix}_enable_and"
                    if enable_node_id in self.graph.nodes:
                        write_enable = self.node_id_to_name.get(enable_node_id, enable_node_id)

                # Fallback: try to infer from node prefixes
                if not write_enable and index_name:
                    # Try to extract instruction prefix from address node name
                    for potential_instr in ['SB', 'SH', 'SW', 'LB', 'LH', 'LW', 'LBU', 'LHU']:
                        if index_name.startswith(potential_instr + '_'):
                            enable_node_id = f"{potential_instr}_enable"
                            if enable_node_id in self.node_id_to_name:
                                write_enable = self.node_id_to_name[enable_node_id]
                                break

                # Second fallback: if source is a mux output, use mux selects as write enable
                # This handles merged memory writes where multiple instructions share a write path
                if not write_enable:
                    source_node = edge.source
                    if source_node.data.get('type') in ['mux', 'port_data_merge', 'memory_data_merge']:
                        # Find mux select signals by looking at incoming edges
                        mux_selects = []
                        for mux_edge in source_node.incoming_edges:
                            if mux_edge.data.get('type') in ['mux_select', 'port_select']:
                                select_name = self.node_id_to_name.get(mux_edge.source.id,
                                                                       self._sanitize_identifier(mux_edge.source.id))
                                mux_selects.append(select_name)
                        if mux_selects:
                            # Use OR of all select signals as write enable - sorted for determinism
                            write_enable = ' || '.join(sorted(mux_selects))

                # Third fallback: for 'mem' type memory arrays (type 'isa_state mem'), look for store enables
                if not write_enable and array_node and array_node.data.get('is_memory'):
                    memory_name = array_node.data.get('name', array_node.id)
                    mem_port_width = self._get_mem_port_width(memory_name)
                    if mem_port_width > 0:
                        # Look for store enable signals (sb_enable, sh_enable, sw_enable, sd_enable)
                        store_enables = []
                        for store_instr in ['sb', 'sh', 'sw', 'sd']:
                            enable_id = f"{store_instr}_enable"
                            if enable_id in self.node_id_to_name:
                                store_enables.append(self.node_id_to_name[enable_id])
                        if store_enables:
                            # Sorted for determinism
                            write_enable = ' || '.join(sorted(store_enables))

                # Final fallback to expression-based index (shouldn't be needed after fix)
                if not index_name:
                    index_name = self._get_verilog_name_for_expression(target_expr['index'])

                # Apply address scaling for byte-addressed memories (dmem, imem, umem)
                # Word-addressed memories (rf) don't need scaling
                # Also detect narrow stores that need byte-lane selection
                word_index_name = index_name
                byte_offset_bits = None
                needs_byte_lane_select = False
                data_width = None

                if array_name in self.memory_declarations:
                    mem_info = self.memory_declarations[array_name]
                    element_bits = mem_info['bit_width']
                    bytes_per_element = element_bits // 8

                    # Only scale if this is a 'mem' type memory (type 'isa_state mem')
                    # Register files (rf) use register indices, not scaled addresses
                    mem_port_width = self._get_mem_port_width(array_name)

                    if bytes_per_element > 1 and mem_port_width > 0:
                        # Get data width from source node
                        source_node = edge.source
                        data_width = source_node.data.get('bit_width')

                        # Scale byte address to word index by right-shifting
                        # Use MEM_BASE offset for physical memory addressing (imem, dmem)
                        # Note: Use >> instead of [31:shift] for iverilog compatibility in seq logic
                        import math
                        shift_bits = int(math.log2(bytes_per_element))
                        if self._is_physical_memory(array_name):
                            word_index_name = f"(({index_name} - `MEM_BASE) >> {shift_bits})"
                        else:
                            word_index_name = f"({index_name} >> {shift_bits})"
                        byte_offset_bits = shift_bits  # e.g., 2 for word addressing

                        # Check if this is a narrow store
                        if data_width is not None and data_width < element_bits and data_width >= 8:
                            needs_byte_lane_select = True

                # Check for enable condition from edge data (for guarded writes like rf[rd] when (rd != 0))
                enable_expr = edge.data.get('enable')

                # Build complete enable condition
                enable_conditions = []
                if write_enable:
                    enable_conditions.append(write_enable)
                if enable_expr:
                    enable_cond = self._get_verilog_name_for_expression(enable_expr)
                    enable_conditions.append(enable_cond)

                # Check if this is a narrow access from memory transformation
                # If so, add counter-based enable
                target_node = edge.target
                if target_node.data.get('is_narrow_access'):
                    word_index = target_node.data.get('word_index')
                    memory = target_node.data.get('memory')
                    if word_index is not None and memory:
                        # Find the counter for this memory
                        counter_name = f"{memory}_access_counter"
                        if counter_name in self.graph.nodes:
                            counter_verilog_name = self.node_id_to_name.get(counter_name, self._sanitize_identifier(counter_name))
                            enable_conditions.append(f"{counter_verilog_name} == {word_index}")

                full_enable = ' && '.join(enable_conditions) if enable_conditions else None

                # Generate the store logic
                if needs_byte_lane_select:
                    # Check if graph-based store nodes are available
                    target_node = edge.target
                    has_graph_store_nodes = (
                        target_node.data.get('store_byte_enable_node') and
                        target_node.data.get('store_data_node')
                    )

                    if has_graph_store_nodes:
                        # Use graph-based store logic (byte enables + positioned data)
                        be_node_id = target_node.data.get('store_byte_enable_node')
                        pd_node_id = target_node.data.get('store_data_node')
                        byte_sel_nodes = target_node.data.get('store_byte_sel_nodes', [])

                        be_name = self.node_id_to_name.get(be_node_id, self._sanitize_identifier(be_node_id))
                        pd_name = self.node_id_to_name.get(pd_node_id, self._sanitize_identifier(pd_node_id))

                        # Get byte-enable parameters from the node
                        be_node = self.graph.nodes.get(be_node_id)
                        if be_node:
                            num_byte_lanes = be_node.data.get('bit_width', 4)
                            bytes_per_access = be_node.data.get('bytes_per_access', 1)

                            if full_enable:
                                self.seq_logic += f"            if ({full_enable}) begin\n"
                                indent = "                "
                            else:
                                indent = "            "

                            # Generate byte-lane writes using graph-based byte-enable
                            # For each byte lane, write if the corresponding bit is set
                            for lane in range(num_byte_lanes):
                                low_bit = lane * 8
                                high_bit = low_bit + 7
                                self.seq_logic += f"{indent}if ({be_name}[{lane}]) {array_name}[{word_index_name}][{high_bit}:{low_bit}] <= {pd_name}[{high_bit}:{low_bit}];\n"

                            if full_enable:
                                self.seq_logic += f"            end\n"
                        else:
                            # Fallback to hardcoded if node not found
                            print(f"Warning: store_byte_enable node {be_node_id} not found, using fallback")
                            self._generate_hardcoded_store_logic(
                                full_enable, index_name, array_name, word_index_name,
                                source_name, data_width, element_bits
                            )
                    else:
                        # Fallback: Use hardcoded byte-lane selection case statement
                        self._generate_hardcoded_store_logic(
                            full_enable, index_name, array_name, word_index_name,
                            source_name, data_width, element_bits
                        )
                else:
                    # Full-width store: direct assignment
                    if full_enable:
                        self.seq_logic += f"            if ({full_enable}) begin\n"
                        self.seq_logic += f"                {array_name}[{word_index_name}] <= {source_name};\n"
                        self.seq_logic += f"            end\n"
                    else:
                        self.seq_logic += f"            {array_name}[{word_index_name}] <= {source_name};\n"

            # Memory write ports
            for port in memory_write_ports:
                memory_name = port['memory']
                data_name = self.node_id_to_name.get(port['data'].id, self._sanitize_identifier(port['data'].id))
                addr_name = self.node_id_to_name.get(port['address'].id, self._sanitize_identifier(port['address'].id))

                # Override write address with physical index from renamer if applicable
                # When register renaming is enabled, the write_address edge still uses the
                # architectural index (rd) for pipelining and hazard detection, but the actual
                # RF write must use the physical index allocated by the renamer.
                # With Decode-stage allocation, use the piped write_phys at Writeback.
                write_port_node = port.get('port_node')
                if write_port_node and write_port_node.data.get('renamed_write_index'):
                    # Use the Writeback-piped write_phys signal instead of Decode-stage uarch_rd
                    if hasattr(self, '_renamer_wb_write_phys') and self._renamer_wb_write_phys:
                        addr_name = self._renamer_wb_write_phys[0]
                    else:
                        renamed_idx = write_port_node.data['renamed_write_index']
                        addr_name = self.node_id_to_name.get(renamed_idx, self._sanitize_identifier(renamed_idx))

                # Check if this is a mixed-width write port that needs byte-lane selection
                write_enables = port.get('write_enables', [])

                # Get memory width
                mem_width = None
                if memory_name in self.memory_declarations:
                    mem_width = self.memory_declarations[memory_name]['bit_width']

                # Calculate address shift for memory indexing
                # For 32-bit memory (4 bytes): shift=2, addr[31:2]
                # For 64-bit memory (8 bytes): shift=3, addr[31:3]
                import math
                addr_shift = int(math.log2(mem_width // 8)) if mem_width and mem_width >= 8 else 2

                # Get writer information from write port metadata (added by graph_merger)
                # Use the port_node stored earlier instead of searching by memory name
                # (important for multi-port memories where each port has different metadata)
                write_port_node = port.get('port_node')

                writers = []
                writer_widths = {}
                needs_byte_lane_logic = False

                if write_port_node:
                    writers = write_port_node.data.get('writers', [])
                    writer_widths = write_port_node.data.get('writer_widths', {})
                    # Check if any writer has a different width than memory
                    # This includes:
                    # - Narrow writes (width < mem_width): needs byte-lane selection
                    # - Wide writes (width > mem_width): needs multi-cycle dual-word writes
                    if mem_width:
                        for writer, width in writer_widths.items():
                            if width != mem_width:
                                needs_byte_lane_logic = True
                                break

                # Check for combined write enable (e.g., rf_write_enable = any_instr_enable && rd != 0)
                combined_write_enable_id = None
                combined_write_enable_name = None
                if write_port_node:
                    combined_write_enable_id = write_port_node.data.get('combined_write_enable')
                    if combined_write_enable_id:
                        combined_write_enable_name = self.node_id_to_name.get(
                            combined_write_enable_id,
                            self._sanitize_identifier(combined_write_enable_id)
                        )

                # Find stall signals that should gate writes for this pipe instance.
                # Only for dual-issue pipelines: when a pipeline stage is stalled,
                # writes (RF, memory) must be suppressed to prevent repeated execution
                # from corrupting state (e.g., when an instruction reads and writes
                # the same register during a stall cycle).
                # For single-issue stall pipelines, writes must NOT be gated because
                # the write needs to complete to resolve the data hazard that caused
                # the stall in the first place.
                write_stall_cond = None
                check_name = combined_write_enable_name or ""
                if not check_name and write_enables:
                    check_name = self.node_id_to_name.get(write_enables[0].id, "")

                pipe_prefix = ""
                for prefix in ['p0_', 'p1_', 'p2_', 'p3_']:
                    if check_name.startswith(prefix):
                        pipe_prefix = prefix
                        break

                # Only gate writes with stall signals in dual-issue pipelines.
                # Use stall controllers that are actually connected to this
                # memory node via the resource graph (stall edges), rather than
                # auto-discovering all stall controllers by name.
                if pipe_prefix:
                    mem_node = self.graph.nodes.get(memory_name)
                    stall_names = []
                    if mem_node:
                        for edge in mem_node.incoming_edges:
                            if edge.data.get('type') == 'stall' and edge.source.id.endswith('_stall_ctrl'):
                                sname = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                                if sname not in stall_names:
                                    stall_names.append(sname)

                    if stall_names:
                        if len(stall_names) == 1:
                            write_stall_cond = stall_names[0]
                        else:
                            write_stall_cond = '(' + ' || '.join(stall_names) + ')'

                if needs_byte_lane_logic and write_enables:
                    # Determine if this memory uses port_width-based addressing (type 'isa_state mem')
                    # Register files use direct indexing, 'mem' type memories use port_width addressing
                    mem_port_width = self._get_mem_port_width(memory_name)
                    is_mem_type = mem_port_width > 0

                    # Get validity signal if present (from branch prediction)
                    validity_signal = port.get('validity_signal')
                    validity_name = None
                    if validity_signal:
                        validity_name = self.node_id_to_name.get(validity_signal.id, self._sanitize_identifier(validity_signal.id))

                    # If there's a combined write enable, use it as the outer condition
                    # This handles shared enable conditions like (rd != 0) for register file writes
                    if combined_write_enable_name:
                        # Add FP stall condition if present
                        outer_cond = combined_write_enable_name
                        if self.fp_stall_signal:
                            outer_cond = f"({outer_cond} && !{self.fp_stall_signal})"
                        if write_stall_cond:
                            outer_cond = f"({outer_cond} && !{write_stall_cond})"
                        self.seq_logic += f"            if ({outer_cond}) begin\n"
                        inner_indent = "                "
                    elif self.fp_stall_signal or write_stall_cond:
                        # No combined write enable but we still need to gate on FP stall / pipeline stall
                        gate_parts = []
                        if self.fp_stall_signal:
                            gate_parts.append(f"!{self.fp_stall_signal}")
                        if write_stall_cond:
                            gate_parts.append(f"!{write_stall_cond}")
                        gate_cond = ' && '.join(gate_parts)
                        self.seq_logic += f"            if ({gate_cond}) begin\n"
                        inner_indent = "                "
                    else:
                        inner_indent = "            "

                    # Check for graph-based byte enable mappings from set_port_width transform
                    store_byte_enables = write_port_node.data.get('store_byte_enables', {}) if write_port_node else {}
                    store_positioned_data = write_port_node.data.get('store_positioned_data', {}) if write_port_node else {}
                    store_raw_data = write_port_node.data.get('store_raw_data', {}) if write_port_node else {}

                    # Generate conditional byte-lane logic for each writer
                    # Match enable signals to writers by extracting instruction name from enable
                    body_indent = inner_indent + "    "  # Additional indent for inside the if block
                    for i, enable_node in enumerate(write_enables):
                        enable_name = self.node_id_to_name.get(enable_node.id, self._sanitize_identifier(enable_node.id))

                        # Extract writer name from enable signal (e.g., "sb_enable_and" -> "sb")
                        # Also handle pipelined names like "PIPE_Execute_sb_enable_PIPE"
                        writer = None
                        enable_id = enable_node.id
                        if '_enable_and' in enable_id:
                            writer = enable_id.replace('_enable_and', '')
                        elif '_write_enable' in enable_id:
                            writer = enable_id.replace('_write_enable', '')
                        elif '_enable' in enable_id:
                            # Handle pipelined enable names like PIPE_Execute_sb_enable_PIPE
                            # Also handle dual-issue names like p0_PIPE_ExecuteMemoryWriteback_sb_enable_PIPE
                            # Also handle compressed instruction names with dots like c.swsp_enable
                            # Extract just the instruction name
                            import re
                            match = re.search(r'(?:p\d+_)?(?:PIPE_\w+_)?([\w.]+)_enable(?:_PIPE)?', enable_id)
                            if match:
                                writer = match.group(1)
                            else:
                                writer = enable_id.replace('_enable', '')

                        # Get writer width - try both underscore and dot versions
                        # (enable signals use underscores like c_swsp_enable, but instruction names use dots like c.swsp)
                        writer_width = writer_widths.get(writer) if writer else None
                        writer_dot = writer.replace('_', '.') if writer else None
                        if not writer_width and writer_dot:
                            writer_width = writer_widths.get(writer_dot)
                        # For dual-issue pipelines, strip pipe prefix (p0_, p1_, etc.)
                        # Enable IDs like p0_sb_enable produce writer="p0_sb" but
                        # writer_widths keys are unprefixed like "sb"
                        if not writer_width and writer:
                            import re
                            stripped = re.sub(r'^p\d+_', '', writer)
                            if stripped != writer:
                                writer_width = writer_widths.get(stripped)
                                if not writer_width:
                                    stripped_dot = stripped.replace('_', '.')
                                    writer_width = writer_widths.get(stripped_dot)

                        # Add validity check to enable condition
                        if validity_name:
                            enable_cond = f"({enable_name} && {validity_name})"
                        else:
                            enable_cond = enable_name

                        if i == 0:
                            self.seq_logic += f"{inner_indent}if ({enable_cond}) begin\n"
                        else:
                            self.seq_logic += f"{inner_indent}end else if ({enable_cond}) begin\n"

                        # Check if we have graph-based byte enable for this writer
                        # Try both underscore and dot versions of the writer name
                        be_node_id = store_byte_enables.get(writer) or store_byte_enables.get(writer_dot)
                        pd_node_id = store_positioned_data.get(writer) or store_positioned_data.get(writer_dot)

                        if be_node_id and pd_node_id and writer_width and writer_width < mem_width:
                            # Use graph-based byte-enable logic
                            be_name = self.node_id_to_name.get(be_node_id, self._sanitize_identifier(be_node_id))
                            pd_name = self.node_id_to_name.get(pd_node_id, self._sanitize_identifier(pd_node_id))
                            num_byte_lanes = mem_width // 8

                            # Use MEM_BASE offset for physical memory addressing (imem, dmem)
                            # Use >> instead of [31:x] for iverilog compatibility
                            # Non-physical 'mem' types (like CSR) use direct indexing
                            if self._is_physical_memory(memory_name):
                                mem_idx = f"(({addr_name} - `MEM_BASE) >> {addr_shift})"
                            else:
                                mem_idx = addr_name

                            # Check if spanning writes are possible (sub-word access that can
                            # cross word boundary). If so, the byte_enable + positioned_data
                            # logic is WRONG for the spanning offset because the inverted selector
                            # wraps around, corrupting byte positions.
                            # Try store_raw_data first, then trace graph as fallback
                            raw_data_id = store_raw_data.get(writer) or store_raw_data.get(writer_dot)
                            if not raw_data_id:
                                # Trace positioned_data node's left_operand (zero-extended data)
                                # to find the raw data source for spanning fixup
                                pd_node = self.graph.nodes.get(pd_node_id) if pd_node_id else None
                                if pd_node:
                                    for pd_edge in pd_node.incoming_edges:
                                        if pd_edge.data.get('type') == 'left_operand':
                                            # This is the zero-extended data node
                                            data_zext_node = pd_edge.source
                                            # The raw data is the zext node's operand source
                                            for zext_edge in data_zext_node.incoming_edges:
                                                if zext_edge.data.get('type') == 'operand':
                                                    raw_data_id = zext_edge.source.id
                                                    break
                                            if not raw_data_id:
                                                # Use the zext node itself as raw data
                                                raw_data_id = data_zext_node.id
                                            break
                            bytes_per_access = writer_width // 8
                            has_spanning = (raw_data_id is not None and
                                           bytes_per_access > 1 and
                                           num_byte_lanes > bytes_per_access)
                            if has_spanning:
                                span_offset = num_byte_lanes - 1  # last byte offset where spanning occurs
                                bits_in_current = num_byte_lanes - span_offset  # bytes fitting in current word
                                bits_in_next = bytes_per_access - bits_in_current  # bytes overflowing to next word
                                mem_endian = self._get_mem_endianness(memory_name)
                            else:
                                span_offset = -1  # never matches
                                mem_endian = None

                            self.seq_logic += f"{body_indent}// Graph-based byte-enable store\n"
                            for lane in range(num_byte_lanes):
                                low_bit = lane * 8
                                high_bit = low_bit + 7
                                if has_spanning and mem_endian == 'big':
                                    # Guard byte_enable writes against spanning offset to prevent
                                    # corruption: at the spanning offset, the inverted selector wraps
                                    # causing byte_enable to enable wrong lanes with wrong data
                                    self.seq_logic += f"{body_indent}if ({be_name}[{lane}] && {addr_name}[{addr_shift-1}:0] != {addr_shift}'d{span_offset}) {memory_name}[{mem_idx}][{high_bit}:{low_bit}] <= {pd_name}[{high_bit}:{low_bit}];\n"
                                else:
                                    self.seq_logic += f"{body_indent}if ({be_name}[{lane}]) {memory_name}[{mem_idx}][{high_bit}:{low_bit}] <= {pd_name}[{high_bit}:{low_bit}];\n"

                            # Spanning write fixup: when a sub-word write crosses a word boundary,
                            # emit direct writes for both the current word and next word portions.
                            if has_spanning:
                                raw_data_name = self.node_id_to_name.get(raw_data_id, self._sanitize_identifier(raw_data_id))
                                if self._is_physical_memory(memory_name):
                                    next_idx = f"({mem_idx} + 1)"
                                else:
                                    next_idx = f"({mem_idx} + 1)"
                                if mem_endian == 'big':
                                    # Big-endian spanning at byte offset {span_offset}:
                                    # - Current word: high byte(s) of data go to low bit positions
                                    # - Next word: low byte(s) of data go to high bit positions
                                    self.seq_logic += f"{body_indent}// Spanning write fixup for byte offset {span_offset}\n"
                                    # Current word: write the portion that fits
                                    self.seq_logic += f"{body_indent}if ({addr_name}[{addr_shift-1}:0] == {addr_shift}'d{span_offset}) "
                                    self.seq_logic += f"{memory_name}[{mem_idx}][{bits_in_current*8 - 1}:0] <= {raw_data_name}[{writer_width-1}:{writer_width - bits_in_current*8}];\n"
                                    # Next word: write the overflow portion
                                    self.seq_logic += f"{body_indent}if ({addr_name}[{addr_shift-1}:0] == {addr_shift}'d{span_offset}) "
                                    self.seq_logic += f"{memory_name}[{next_idx}][{mem_width-1}:{mem_width - bits_in_next*8}] <= {raw_data_name}[{bits_in_next*8-1}:0];\n"
                                else:
                                    # Little-endian: byte_enable writes are correct for current word
                                    # at spanning offset; only need next word fixup
                                    self.seq_logic += f"{body_indent}// Spanning write fixup for byte offset {span_offset}\n"
                                    self.seq_logic += f"{body_indent}if ({addr_name}[{addr_shift-1}:0] == {addr_shift}'d{span_offset}) "
                                    self.seq_logic += f"{memory_name}[{next_idx}][{bits_in_next*8-1}:0] <= {raw_data_name}[{writer_width-1}:{writer_width - bits_in_next*8}];\n"
                        elif writer_width == 8:
                            # Byte store
                            # Check for bit_range on write port (for partial writes using 'of' keyword)
                            port_bit_range = write_port_node.data.get('bit_range') if write_port_node else None
                            if port_bit_range:
                                # Register file partial write - use bit range from write port
                                bit_high, bit_low = port_bit_range
                                self.seq_logic += f"{body_indent}{memory_name}[{addr_name}][{bit_high}:{bit_low}] <= {data_name}[7:0];\n"
                            elif mem_width == 8:
                                # 8-bit memory: direct byte addressing, no word/byte selection needed
                                self.seq_logic += f"{body_indent}{memory_name}[{addr_name}] <= {data_name}[7:0];\n"
                            elif is_mem_type:
                                # Byte-lane selection for mem-type memory with endianness support
                                if self._is_physical_memory(memory_name):
                                    mem_idx = f"(({addr_name} - `MEM_BASE) >> {addr_shift})"
                                else:
                                    mem_idx = f"({addr_name} >> {addr_shift})"
                                mem_endian = self._get_mem_endianness(memory_name)
                                offset_bits = addr_shift
                                num_cases = 1 << offset_bits
                                self.seq_logic += f"{body_indent}case ({addr_name}[{offset_bits-1}:0])\n"
                                for case_idx in range(num_cases):
                                    if mem_endian == 'big':
                                        high = mem_width - 1 - case_idx * 8
                                        low = high - 7
                                    else:
                                        low = case_idx * 8
                                        high = low + 7
                                    self.seq_logic += f"{body_indent}    {offset_bits}'d{case_idx}: {memory_name}[{mem_idx}][{high}:{low}] <= {data_name}[7:0];\n"
                                self.seq_logic += f"{body_indent}endcase\n"
                            else:
                                # Not 'mem' type: shouldn't happen for 8-bit writes
                                self.seq_logic += f"{body_indent}{memory_name}[{addr_name}] <= {{{{24'b0, {data_name}[7:0]}}}};\n"
                        elif writer_width == 16:
                            # Check for bit_range on write port (for partial writes using 'of' keyword)
                            port_bit_range_16 = write_port_node.data.get('bit_range') if write_port_node else None
                            if port_bit_range_16 and not is_mem_type:
                                # Register file partial write - use bit range from write port
                                bit_high_16, bit_low_16 = port_bit_range_16
                                self.seq_logic += f"{body_indent}{memory_name}[{addr_name}][{bit_high_16}:{bit_low_16}] <= {data_name}[15:0];\n"
                            elif writer_width > mem_width:
                                print(f"  [MULTI-CYCLE] {writer}: {writer_width}-bit store to {mem_width}-bit memory")
                                print(f"                 Requires dual-{mem_width}-bit writes (2 ports or 2 cycles)")
                            elif is_mem_type:
                                print(f"  [PORT WARNING] {writer}: 16-bit store may require 2 simultaneous writes if unaligned")

                            if port_bit_range_16 and not is_mem_type:
                                pass  # Already handled above
                            elif is_mem_type:
                                # Halfword store with byte-lane selection and endianness support
                                if self._is_physical_memory(memory_name):
                                    mem_idx = f"(({addr_name} - `MEM_BASE) >> {addr_shift})"
                                else:
                                    mem_idx = f"({addr_name} >> {addr_shift})"
                                mem_endian = self._get_mem_endianness(memory_name)
                                if mem_width == 16:
                                    # 16-bit memory: writer matches mem width, direct write
                                    self.seq_logic += f"{body_indent}{memory_name}[{mem_idx}] <= {data_name}[15:0];\n"
                                else:
                                    offset_bits = addr_shift
                                    num_cases = 1 << offset_bits
                                    self.seq_logic += f"{body_indent}case ({addr_name}[{offset_bits-1}:0])\n"
                                    for offset_idx in range(num_cases):
                                        if mem_endian == 'big':
                                            high = mem_width - 1 - offset_idx * 8
                                            low = high - 15
                                        else:
                                            low = offset_idx * 8
                                            high = low + 15
                                        if low >= 0 and high < mem_width:
                                            self.seq_logic += f"{body_indent}    {offset_bits}'d{offset_idx}: {memory_name}[{mem_idx}][{high}:{low}] <= {data_name}[15:0];\n"
                                        else:
                                            if mem_endian == 'big':
                                                bits_in_current = max(0, high + 1)
                                                bits_in_next = 16 - bits_in_current
                                            else:
                                                bits_in_current = mem_width - low
                                                bits_in_next = 16 - bits_in_current
                                            self.seq_logic += f"{body_indent}    {offset_bits}'d{offset_idx}: begin\n"
                                            if mem_endian == 'big':
                                                self.seq_logic += f"{body_indent}        {memory_name}[{mem_idx}][{max(0, high)}:0] <= {data_name}[15:{16-bits_in_current}];\n"
                                                self.seq_logic += f"{body_indent}        {memory_name}[{mem_idx} + 1][{mem_width-1}:{mem_width-bits_in_next}] <= {data_name}[{bits_in_next-1}:0];\n"
                                            else:
                                                self.seq_logic += f"{body_indent}        {memory_name}[{mem_idx}][{mem_width-1}:{low}] <= {data_name}[{bits_in_current-1}:0];\n"
                                                self.seq_logic += f"{body_indent}        {memory_name}[{mem_idx} + 1][{bits_in_next-1}:0] <= {data_name}[15:{bits_in_current}];\n"
                                            self.seq_logic += f"{body_indent}    end\n"
                                    self.seq_logic += f"{body_indent}endcase\n"
                            else:
                                # Not 'mem' type: shouldn't happen for 16-bit writes
                                self.seq_logic += f"{body_indent}{memory_name}[{addr_name}] <= {{{{16'b0, {data_name}[15:0]}}}};\n"
                        elif writer_width == 32:
                            # Word store - may span word boundaries if unaligned OR if memory is narrower
                            if writer_width > mem_width:
                                print(f"  [MULTI-CYCLE] {writer}: {writer_width}-bit store to {mem_width}-bit memory")
                                print(f"                 Requires dual-{mem_width}-bit writes (2 ports or 2 cycles)")
                            elif is_mem_type:
                                print(f"  [PORT WARNING] {writer}: 32-bit store may require 2 simultaneous writes if unaligned")

                            # For register files (not 'mem' type), use simple direct indexing
                            if not is_mem_type:
                                self.seq_logic += f"{body_indent}{memory_name}[{addr_name}] <= {data_name};\n"
                            else:
                                # Word store with byte-lane selection and endianness support
                                if self._is_physical_memory(memory_name):
                                    mem_idx = f"(({addr_name} - `MEM_BASE) >> {addr_shift})"
                                else:
                                    mem_idx = f"({addr_name} >> {addr_shift})"
                                if mem_width == 16:
                                    # 32-bit write to 16-bit memory: two consecutive halfword writes
                                    mem_endian = self._get_mem_endianness(memory_name)
                                    if mem_endian == 'big':
                                        self.seq_logic += f"{body_indent}{memory_name}[{mem_idx}] <= {data_name}[31:16];\n"
                                        self.seq_logic += f"{body_indent}{memory_name}[{mem_idx} + 1] <= {data_name}[15:0];\n"
                                    else:
                                        self.seq_logic += f"{body_indent}{memory_name}[{mem_idx}] <= {data_name}[15:0];\n"
                                        self.seq_logic += f"{body_indent}{memory_name}[{mem_idx} + 1] <= {data_name}[31:16];\n"
                                else:
                                    mem_endian = self._get_mem_endianness(memory_name)
                                    offset_bits = addr_shift
                                    num_cases = 1 << offset_bits
                                    self.seq_logic += f"{body_indent}case ({addr_name}[{offset_bits-1}:0])\n"
                                    for offset_index in range(num_cases):
                                        if mem_endian == 'big':
                                            high = mem_width - 1 - offset_index * 8
                                            low = high - 31
                                        else:
                                            low = offset_index * 8
                                            high = low + 31
                                        if low >= 0 and high < mem_width:
                                            if low == 0 and high == mem_width - 1:
                                                self.seq_logic += f"{body_indent}    {offset_bits}'d{offset_index}: {memory_name}[{mem_idx}] <= {data_name};\n"
                                            else:
                                                self.seq_logic += f"{body_indent}    {offset_bits}'d{offset_index}: {memory_name}[{mem_idx}][{high}:{low}] <= {data_name}[31:0];\n"
                                        else:
                                            if mem_endian == 'big':
                                                bits_in_current = max(0, high + 1)
                                                bits_in_next = 32 - bits_in_current
                                            else:
                                                bits_in_current = mem_width - low
                                                bits_in_next = 32 - bits_in_current
                                            self.seq_logic += f"{body_indent}    {offset_bits}'d{offset_index}: begin\n"
                                            if mem_endian == 'big':
                                                self.seq_logic += f"{body_indent}        {memory_name}[{mem_idx}][{bits_in_current-1}:0] <= {data_name}[31:{bits_in_next}];\n"
                                                self.seq_logic += f"{body_indent}        {memory_name}[{mem_idx} + 1][{mem_width-1}:{mem_width-bits_in_next}] <= {data_name}[{bits_in_next-1}:0];\n"
                                            else:
                                                self.seq_logic += f"{body_indent}        {memory_name}[{mem_idx}][{mem_width-1}:{low}] <= {data_name}[{bits_in_current-1}:0];\n"
                                                self.seq_logic += f"{body_indent}        {memory_name}[{mem_idx} + 1][{bits_in_next-1}:0] <= {data_name}[31:{bits_in_current}];\n"
                                            self.seq_logic += f"{body_indent}    end\n"
                                    self.seq_logic += f"{body_indent}endcase\n"
                        else:
                            # Full-width or unhandled - use appropriate addressing
                            if not is_mem_type:
                                self.seq_logic += f"{body_indent}{memory_name}[{addr_name}] <= {data_name};\n"
                            else:
                                # Use >> instead of [31:x] for iverilog compatibility
                                # Non-physical 'mem' types (like CSR) use direct indexing
                                if self._is_physical_memory(memory_name):
                                    mem_idx = f"(({addr_name} - `MEM_BASE) >> {addr_shift})"
                                else:
                                    mem_idx = addr_name
                                self.seq_logic += f"{body_indent}{memory_name}[{mem_idx}] <= {data_name};\n"

                    self.seq_logic += f"{inner_indent}end\n"

                    # Close the combined write enable block if we opened one
                    if combined_write_enable_name or self.fp_stall_signal or write_stall_cond:
                        self.seq_logic += f"            end\n"

                elif write_enables or combined_write_enable_name:
                    # No byte-lane selection needed - simple conditional write
                    # Use combined write enable if available (includes shared conditions like rd != 0)
                    # Also handles case where no data mux exists (single writer) but enable is still needed
                    if combined_write_enable_name:
                        enable_cond = combined_write_enable_name
                    elif write_enables:
                        enable_names = [self.node_id_to_name.get(en.id, self._sanitize_identifier(en.id)) for en in write_enables]
                        # Sorted for determinism
                        enable_cond = ' || '.join(sorted(enable_names))

                    # Add validity signal if present (from branch prediction)
                    validity_signal = port.get('validity_signal')
                    if validity_signal:
                        validity_name = self.node_id_to_name.get(validity_signal.id, self._sanitize_identifier(validity_signal.id))
                        enable_cond = f"({enable_cond} && {validity_name})"
                    # Add FP multi-cycle stall if present (stall writes during div/sqrt)
                    if self.fp_stall_signal:
                        enable_cond = f"({enable_cond} && !{self.fp_stall_signal})"
                    # Gate writes by pipeline stall to prevent repeated execution during stalls
                    if write_stall_cond:
                        enable_cond = f"({enable_cond} && !{write_stall_cond})"
                    self.seq_logic += f"            if ({enable_cond}) begin\n"

                    # Check if this is a 'mem' type memory (type 'isa_state mem')
                    # Register files use direct indexing, 'mem' type uses port_width-based addressing
                    is_mem_type = self._get_mem_port_width(memory_name) > 0

                    if is_mem_type:
                        # Use >> instead of [31:x] for iverilog compatibility
                        # Non-physical 'mem' types (like CSR) use direct indexing
                        if self._is_physical_memory(memory_name):
                            mem_idx = f"(({addr_name} - `MEM_BASE) >> {addr_shift})"
                        else:
                            mem_idx = addr_name
                        self.seq_logic += f"                {memory_name}[{mem_idx}] <= {data_name};\n"
                    else:
                        # Check for bit_range on write port (partial register writes via 'of' keyword)
                        port_bit_range = write_port_node.data.get('bit_range') if write_port_node else None
                        if port_bit_range:
                            # Partial register write: only update the targeted bit range
                            # Use bit-select on LHS to preserve other bits
                            bit_high, bit_low = port_bit_range
                            data_width = bit_high - bit_low + 1
                            self.seq_logic += f"                {memory_name}[{addr_name}][{bit_high}:{bit_low}] <= {data_name}[{data_width-1}:0];\n"
                        else:
                            self.seq_logic += f"                {memory_name}[{addr_name}] <= {data_name};\n"
                    self.seq_logic += f"            end\n"
                else:
                    # No write enables found from mux selects
                    # But we should still gate the write with writer enables if available
                    # Check if this is a 'mem' type memory (type 'isa_state mem')
                    is_mem_type = self._get_mem_port_width(memory_name) > 0

                    # Use combined write enable if available (includes guarded conditions like exc_taken)
                    # This is the preferred approach as it preserves conditional write semantics
                    writer_enable_cond = None
                    if combined_write_enable_name:
                        writer_enable_cond = combined_write_enable_name
                    elif writers:
                        # Fallback: Construct enable from writer instruction enables
                        # Note: This loses conditional write semantics (like when exc_taken)
                        writer_enables = []
                        for writer in writers:
                            writer_enable = f"{writer}_enable"
                            if writer_enable in self.node_id_to_name.values():
                                writer_enables.append(writer_enable)
                            elif writer_enable in [n.id for n in self.graph.nodes.values()]:
                                writer_enables.append(writer_enable)
                        if writer_enables:
                            writer_enable_cond = ' || '.join(sorted(writer_enables))

                    if writer_enable_cond:
                        # Gate write with writer enable
                        # Add FP stall condition if present
                        full_cond = writer_enable_cond
                        if self.fp_stall_signal:
                            full_cond = f"({full_cond} && !{self.fp_stall_signal})"
                        if write_stall_cond:
                            full_cond = f"({full_cond} && !{write_stall_cond})"
                        self.seq_logic += f"            if ({full_cond}) begin\n"
                        if is_mem_type:
                            self.seq_logic += f"                {memory_name}[{addr_name}[31:{addr_shift}]] <= {data_name};\n"
                        else:
                            # Check for bit_range on write port (partial register writes via 'of' keyword)
                            port_bit_range = write_port_node.data.get('bit_range') if write_port_node else None
                            if port_bit_range:
                                bit_high, bit_low = port_bit_range
                                data_width = bit_high - bit_low + 1
                                self.seq_logic += f"                {memory_name}[{addr_name}][{bit_high}:{bit_low}] <= {data_name}[{data_width-1}:0];\n"
                            else:
                                self.seq_logic += f"                {memory_name}[{addr_name}] <= {data_name};\n"
                        self.seq_logic += f"            end\n"
                    elif self.fp_stall_signal:
                        # No writer enable but we still need to gate on FP stall
                        self.seq_logic += f"            if (!{self.fp_stall_signal}) begin\n"
                        if is_mem_type:
                            # Use MEM_BASE offset for physical memory addressing (imem, dmem, umem)
                            # Non-physical 'mem' types (like CSR) use direct indexing
                            if self._is_physical_memory(memory_name):
                                mem_idx = f"(({addr_name} - `MEM_BASE) >> {addr_shift})"
                            else:
                                mem_idx = addr_name
                            self.seq_logic += f"                {memory_name}[{mem_idx}] <= {data_name};\n"
                        else:
                            # Check for bit_range on write port (partial register writes via 'of' keyword)
                            port_bit_range = write_port_node.data.get('bit_range') if write_port_node else None
                            if port_bit_range:
                                bit_high, bit_low = port_bit_range
                                data_width = bit_high - bit_low + 1
                                self.seq_logic += f"                {memory_name}[{addr_name}][{bit_high}:{bit_low}] <= {data_name}[{data_width-1}:0];\n"
                            else:
                                self.seq_logic += f"                {memory_name}[{addr_name}] <= {data_name};\n"
                        self.seq_logic += f"            end\n"
                    else:
                        # Truly unconditional write (no writers metadata)
                        if is_mem_type:
                            # Use MEM_BASE offset for physical memory addressing (imem, dmem, umem)
                            # Non-physical 'mem' types (like CSR) use direct indexing
                            if self._is_physical_memory(memory_name):
                                mem_idx = f"(({addr_name} - `MEM_BASE) >> {addr_shift})"
                            else:
                                mem_idx = addr_name
                            self.seq_logic += f"            {memory_name}[{mem_idx}] <= {data_name};\n"
                        else:
                            # Check for bit_range on write port (partial register writes via 'of' keyword)
                            port_bit_range = write_port_node.data.get('bit_range') if write_port_node else None
                            if port_bit_range:
                                bit_high, bit_low = port_bit_range
                                data_width = bit_high - bit_low + 1
                                self.seq_logic += f"            {memory_name}[{addr_name}][{bit_high}:{bit_low}] <= {data_name}[{data_width-1}:0];\n"
                            else:
                                self.seq_logic += f"            {memory_name}[{addr_name}] <= {data_name};\n"

            # Conditional array writes (from ILA transformation)
            for write_info in conditional_writes:
                enable_name = self.node_id_to_name.get(write_info['enable'].id,
                                                       self._sanitize_identifier(write_info['enable'].id))
                data_name = self.node_id_to_name.get(write_info['data'].id,
                                                     self._sanitize_identifier(write_info['data'].id))
                addr_name = self.node_id_to_name.get(write_info['address'].id,
                                                     self._sanitize_identifier(write_info['address'].id))

                # Get the base array name (strip _rd suffix if present)
                base_name = write_info['array'].data.get('name', write_info['array'].id)
                if base_name.endswith('_rd'):
                    base_name = base_name[:-3]

                # Generate conditional write directly to the array
                # Add FP stall condition if present
                full_cond = enable_name
                if self.fp_stall_signal:
                    full_cond = f"({full_cond} && !{self.fp_stall_signal})"
                self.seq_logic += f"            if ({full_cond}) begin\n"
                self.seq_logic += f"                {base_name}[{addr_name}] <= {data_name};\n"
                self.seq_logic += f"            end\n"

            self.seq_logic += "        end\n"
            self.seq_logic += "    end\n\n"

    def _generate_ras_sequential_logic(self):
        """Generate sequential logic for Return Address Stack (RAS) operations."""
        import math

        # Find RAS-related nodes
        ras_stack_node = None
        ras_ptr_node = None
        ras_push_node = None
        ras_pop_node = None
        ras_push_valid_node = None
        ras_pop_valid_node = None
        ras_stack_write_node = None
        ras_ptr_next_node = None

        for node in self.graph.nodes.values():
            node_type = node.data.get('type', '')
            node_name = node.data.get('name', node.id)

            if node_type == 'ras_stack':
                ras_stack_node = node
            elif node_name == 'ras_ptr' and node.is_uarch_state:
                ras_ptr_node = node
            elif node_name == 'ras_push':
                ras_push_node = node
            elif node_name == 'ras_pop':
                ras_pop_node = node
            elif node_name == 'ras_push_valid':
                ras_push_valid_node = node
            elif node_name == 'ras_pop_valid':
                ras_pop_valid_node = node
            elif node_type == 'array_write' and node.data.get('ras_component'):
                ras_stack_write_node = node
            elif node_type == 'ras_ptr_update':
                ras_ptr_next_node = node

        # If no RAS components found, return
        if not ras_stack_node or not ras_ptr_node:
            return

        # Get names
        stack_name = self.node_id_to_name.get(ras_stack_node.id, 'ras_stack')
        ptr_name = self.node_id_to_name.get(ras_ptr_node.id, 'ras_ptr')

        # Get push/pop signal names - prefer flush-gated versions if available
        # The flush-gated versions (ras_push_valid, ras_pop_valid) prevent
        # corrupting the RAS when instructions are flushed
        push_name = 'ras_push'
        pop_name = 'ras_pop'
        if ras_push_valid_node:
            push_name = self.node_id_to_name.get(ras_push_valid_node.id, 'ras_push_valid')
        elif ras_push_node:
            push_name = self.node_id_to_name.get(ras_push_node.id, 'ras_push')
        if ras_pop_valid_node:
            pop_name = self.node_id_to_name.get(ras_pop_valid_node.id, 'ras_pop_valid')
        elif ras_pop_node:
            pop_name = self.node_id_to_name.get(ras_pop_node.id, 'ras_pop')

        # Get return address source (from stack write node's incoming edges)
        return_addr_name = 'ret_addr'
        if ras_stack_write_node:
            for edge in ras_stack_write_node.incoming_edges:
                if edge.data.get('type') == 'write_data':
                    return_addr_name = self.node_id_to_name.get(
                        edge.source.id, self._sanitize_identifier(edge.source.id))
                    break

        # Get pointer width
        ptr_width = ras_ptr_node.data.get('bit_width', 3)
        depth = ras_stack_node.data.get('depth', 8)

        self.seq_logic += "    // Return Address Stack (RAS) sequential logic\n"
        self.seq_logic += "    always @(posedge clk) begin\n"
        self.seq_logic += "        if (reset) begin\n"
        self.seq_logic += f"            {ptr_name} <= {ptr_width}'d0;\n"
        self.seq_logic += "        end else begin\n"
        self.seq_logic += f"            if ({push_name}) begin\n"
        self.seq_logic += f"                {stack_name}[{ptr_name}] <= {return_addr_name};\n"
        self.seq_logic += f"                {ptr_name} <= {ptr_name} + 1;\n"
        self.seq_logic += f"            end else if ({pop_name}) begin\n"
        self.seq_logic += f"                {ptr_name} <= {ptr_name} - 1;\n"
        self.seq_logic += "            end\n"
        self.seq_logic += "        end\n"
        self.seq_logic += "    end\n\n"

    def _generate_module_instantiation(self, node: Node):
        """Generate instantiation for a hardware module (MUX, ALU, etc.)."""
        node_type = node.data.get('type')

        if node.id not in self.module_generators:
            print(f"Warning: No generator found for module node {node.id}")
            return

        generator = self.module_generators[node.id]

        # Generate instantiation based on module type
        if node_type == 'multiplexer':
            self._generate_mux_instantiation(node, generator)
        elif node_type == 'alu_module':
            # ALU instantiation is handled by _generate_alu_module_logic
            pass
        elif node_type in ['uarch_counter', 'serialization_counter', 'memory_port_counter', 'memory_access_counter']:
            self._generate_counter_instantiation(node, generator)

    def _generate_inline_mux_logic(self, node: Node, generator, input_signals: list,
                                   select_signal, output_signal: str, default_signal: str = None,
                                   input_indices: list = None) -> str:
        """
        Generate inline mux logic as always @* blocks instead of module instantiations.
        This significantly reduces the number of modules generated.
        """
        logic = ""
        select_type = generator.select_type if hasattr(generator, 'select_type') else 'binary'
        data_width = generator.data_width if hasattr(generator, 'data_width') else 32

        # Add comment identifying the mux
        logic += f"    // Inline mux logic for {node.id}\n"

        if select_type == 'priority':
            # Generate priority mux with if-else chain
            logic += f"    always @* begin\n"

            if len(input_signals) == 0:
                # No inputs - just assign default
                if default_signal:
                    logic += f"        {output_signal} = {default_signal};\n"
                else:
                    logic += f"        {output_signal} = {data_width}'d0;\n"
            else:
                # Generate if-else chain for priority selection
                select_list = select_signal if isinstance(select_signal, list) else [select_signal]

                for i, (inp_sig, sel_sig) in enumerate(zip(input_signals, select_list)):
                    if i == 0:
                        logic += f"        if ({sel_sig}) begin\n"
                    else:
                        logic += f"        end else if ({sel_sig}) begin\n"
                    logic += f"            {output_signal} = {inp_sig};\n"

                # Default case
                logic += "        end else begin\n"
                if default_signal:
                    # Note: byte/halfword extraction is handled by standard priority muxes
                    # created by memory_access_transform's set_port_width strategy
                    logic += f"            {output_signal} = {default_signal};\n"
                else:
                    logic += f"            {output_signal} = {data_width}'d0;\n"
                logic += "        end\n"

            logic += "    end\n\n"

        elif select_type == 'one_hot':
            # Generate one-hot mux with OR-based logic
            logic += f"    always @* begin\n"
            logic += f"        {output_signal} = "

            select_list = select_signal if isinstance(select_signal, list) else [select_signal]
            terms = []
            for inp_sig, sel_sig in zip(input_signals, select_list):
                terms.append(f"({sel_sig} ? {inp_sig} : {data_width}'d0)")

            if default_signal and select_list:
                # Add default term: when no select is active, output default
                no_sel = " | ".join(select_list)
                terms.append(f"(!({no_sel}) ? {default_signal} : {data_width}'d0)")

            logic += " | ".join(terms) + ";\n"
            logic += "    end\n\n"

        else:  # binary
            # Generate binary mux with case statement
            # Use original input_indices if provided, otherwise fall back to enumerate
            if input_indices is None:
                input_indices = list(range(len(input_signals)))

            # Calculate select width based on max index value
            max_idx = max(input_indices) if input_indices else 0
            select_width = max_idx.bit_length() if max_idx > 0 else 1

            logic += f"    always @* begin\n"
            logic += f"        case ({select_signal})\n"

            for idx, inp_sig in zip(input_indices, input_signals):
                logic += f"            {select_width}'d{idx}: {output_signal} = {inp_sig};\n"

            logic += f"            default: {output_signal} = "
            if default_signal:
                logic += f"{default_signal};\n"
            else:
                logic += f"{data_width}'d0;\n"
            logic += "        endcase\n"
            logic += "    end\n\n"

        return logic

    def _generate_mux_instantiation(self, node: Node, generator):
        """Generate instantiation for a multiplexer."""
        # Collect input signals, select signals, and default input from incoming edges
        mux_inputs = []
        mux_selects = []
        default_signal = None

        # Check if this is an orthogon data-select mux (has an orthogon_selector edge)
        orthogon_selector_signal = None
        for edge in node.incoming_edges:
            if (edge.data.get('type') == 'mux_select'
                    and edge.data.get('orthogon_selector')):
                orthogon_selector_signal = self._get_node_verilog_ref(edge.source)
                break

        # Process all incoming edges
        for edge in node.incoming_edges:
            if edge.data.get('type') == 'mux_input':
                input_index = edge.data.get('input_index', edge.data.get('mux_select', 0))
                # Use _get_node_verilog_ref to properly inline concatenations/repetitions
                source_name = self._get_node_verilog_ref(edge.source)
                mux_inputs.append((input_index, source_name))
            elif edge.data.get('type') == 'mux_select':
                # Skip the global orthogon selector — it's used as the case
                # expression, not as a per-variant condition
                if edge.data.get('orthogon_selector'):
                    continue
                select_index = edge.data.get('select_index', 0)
                select_source = edge.source

                # Check if this select is a simple AND operation that can be inlined
                # Pattern: instr_enable && shared_condition
                # Handle both ILA case (type='operation', operator='&&') and
                # ISA case (type='logical_and', operation='&&')
                can_inline = False
                is_and_op = False
                if select_source.data.get('type') == 'operation' and select_source.data.get('operator') == '&&':
                    is_and_op = True
                elif select_source.data.get('type') == 'logical_and' and select_source.data.get('operation') == '&&':
                    is_and_op = True

                if is_and_op:
                    # CRITICAL: Never inline instruction_enable nodes, even in mux selects
                    # These must have wire declarations for use in sequential logic
                    is_instruction_enable = (
                        select_source.data.get('type') == 'instruction_enable' or
                        select_source.id.endswith('_enable')
                    )

                    if not is_instruction_enable:
                        # Check if this AND node has exactly 2 operands
                        # Handle both edge types: 'operand' (ILA) and 'logic_input' (ISA)
                        operands = [e for e in select_source.incoming_edges if e.data.get('type') in ['operand', 'logic_input']]
                        if len(operands) == 2:
                            # Get operand names - sort by source node ID for determinism
                            op_names = []
                            for op_edge in sorted(operands, key=lambda e: e.source.id):
                                op_name = self.node_id_to_name.get(op_edge.source.id, op_edge.source.data.get('name', op_edge.source.id))
                                op_name = self._sanitize_identifier(op_name)
                                op_names.append(op_name)
                            # Inline as "op1 & op2"
                            select_name = f"({op_names[0]} & {op_names[1]})"
                            can_inline = True
                            # Mark this AND node as inlined so we don't generate a wire for it
                            if not hasattr(self, 'inlined_nodes'):
                                self.inlined_nodes = set()
                            self.inlined_nodes.add(select_source.id)

                if not can_inline:
                    select_name = self.node_id_to_name.get(edge.source.id, edge.source.data.get('name', edge.source.id))
                    select_name = self._sanitize_identifier(select_name)

                mux_selects.append((select_index, select_name))
            elif edge.data.get('type') == 'mux_default_input':
                # Use _get_node_verilog_ref to properly inline concatenations/repetitions
                default_signal = self._get_node_verilog_ref(edge.source)

        # Sort by index
        mux_inputs.sort(key=lambda x: x[0])
        mux_selects.sort(key=lambda x: x[0])

        # Extract signals in order - but also keep indices for case statement generation
        input_signals = [src for _, src in mux_inputs]
        input_indices = [idx for idx, _ in mux_inputs]  # Preserve original indices for case values
        select_signals = [sel for _, sel in mux_selects]

        # Get mux data width - first check explicit settings, then infer from inputs
        # Note: byte_mux nodes use 'bit_width' while other mux types may use 'data_width' or 'output_width'
        mux_width = node.data.get('data_width', node.data.get('output_width', node.data.get('bit_width', None)))
        if mux_width is None:
            # Infer from input widths - use max of all inputs
            max_input_width = 32  # Default
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'mux_input':
                    src_width = self._infer_bit_width(edge.source)
                    if src_width and src_width > max_input_width:
                        max_input_width = src_width
            mux_width = max_input_width

        # Check if mux output target needs byte selection from memory reads
        # This happens when multiple memory reads feed a shared byte/halfword variable
        needs_byte_sel = False
        target_width = None
        for edge in node.outgoing_edges:
            if edge.data.get('type') == 'assignment':
                target_node = edge.target
                if target_node.data.get('needs_byte_selection'):
                    needs_byte_sel = True
                if target_node.data.get('bit_width'):
                    target_width = target_node.data.get('bit_width')
                break

        # If target is narrower than mux inputs and needs byte selection, adjust mux width
        if needs_byte_sel and target_width and target_width < mux_width:
            print(f"  Applying byte selection for {node.id}: {mux_width}-bit inputs -> {target_width}-bit output")
            # Generate byte selection for each memory read input
            selected_input_signals = []
            for idx, (input_idx, src_name) in enumerate(mux_inputs):
                # Find the source node to check if it's a memory read
                source_node = None
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'mux_input' and edge.data.get('input_index', edge.data.get('mux_select', 0)) == input_idx:
                        source_node = edge.source
                        break

                if source_node and self._is_mem_type_read(source_node):
                    # This is a 'mem' type memory read - apply byte selection
                    # Extract address wire from the memory read node ID
                    # The pattern is: {instr}_{mem}[addr]_rd
                    import re
                    # Match any memory name (not just hardcoded ones)
                    match = re.match(r'(.+?)_(\w+)\[.+\]_rd', source_node.id)
                    if match:
                        instr_prefix = match.group(1)
                        addr_wire = f"{instr_prefix}_addr"
                    else:
                        addr_wire = "addr"  # Fallback

                    # Create byte-selected wire
                    byte_sel_name = f"{src_name}_byte"
                    if byte_sel_name not in self.declared_names:
                        # Add directly to declarations string (since _generate_declarations() already ran)
                        if target_width > 1:
                            self.declarations += f"    wire [{target_width-1}:0] {byte_sel_name};\n"
                        else:
                            self.declarations += f"    wire {byte_sel_name};\n"
                        self.declared_names.add(byte_sel_name)

                    # Generate byte selection: wire[addr[N:0] * 8 +: target_width]
                    # N depends on memory word width: log2(width/8)-1
                    import math
                    byte_offset_hi = int(math.log2(mux_width // 8)) - 1 if mux_width >= 16 else 0
                    self.comb_logic += f"    assign {byte_sel_name} = {src_name}[{addr_wire}[{byte_offset_hi}:0] * 8 +: {target_width}];\n"
                    selected_input_signals.append(byte_sel_name)
                else:
                    selected_input_signals.append(src_name)

            # Update mux_inputs to use byte-selected signals
            mux_inputs = [(idx, sig) for idx, sig in enumerate(selected_input_signals)]
            mux_width = target_width

        # Add zero-extension for narrow inputs if needed
        # This fixes width mismatch warnings from simulators
        # Note: Wire declarations are already added during _analyze_graph()
        extended_input_signals = []
        for idx, (input_idx, src_name) in enumerate(mux_inputs):
            # Find the source node to get its width
            source_node = None
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'mux_input' and edge.data.get('input_index', edge.data.get('mux_select', 0)) == input_idx:
                    source_node = edge.source
                    break

            src_width = None
            src_type = None
            if source_node:
                src_width = source_node.data.get('bit_width')
                src_type = source_node.data.get('type')

            # If source is narrower than mux, use zero-extended version
            if src_width and src_width < mux_width:
                # For literals and concatenations, inline the zero-extension instead of creating a wire
                # Also check if src_name looks like a Verilog literal (contains 'd or 'b or 'h)
                is_literal_type = src_type in ['literal', 'sized_literal']
                is_literal_name = "'" in src_name or src_name.isdigit()
                # Concatenation expressions contain braces and can't be used as identifiers
                is_concat = '{' in src_name or '}' in src_name

                # Check if source node is marked for NaN-boxing (set during graph construction)
                use_nan_boxing = source_node.data.get('nan_box', False) if source_node else False
                # Check if source node needs dual mode (NaN-boxed for FRF, zero-extended for RF)
                use_nan_box_dual = source_node.data.get('nan_box_dual', False) if source_node else False
                # Check if this is the FP register file mux (needs NaN-boxed version for dual nodes)
                is_frf_mux = 'frf' in node.id.lower() and 'write_data' in node.id.lower()

                ext_bits = mux_width - src_width
                if is_literal_type or is_literal_name or is_concat:
                    if use_nan_boxing or (use_nan_box_dual and is_frf_mux):
                        extended_input_signals.append(f"{{{{{ext_bits}{{1'b1}}}}, {src_name}}}")
                    else:
                        extended_input_signals.append(f"{{{{{ext_bits}'d0}}, {src_name}}}")
                else:
                    ext_name = f"{src_name}_zext"

                    # Check if a node with this zero-extension name already exists in the graph
                    # This prevents duplicate assignments when the graph already has positioned_data logic
                    ext_node_exists = ext_name in self.graph.nodes

                    if ext_node_exists:
                        # Use the existing node's Verilog reference
                        # The node's assignment will be generated separately when processing that node
                        ext_wire_name = self.node_id_to_name.get(ext_name, self._sanitize_identifier(ext_name))
                        # For dual NaN-boxing nodes feeding into FRF mux, use the NaN-boxed version
                        if use_nan_box_dual and is_frf_mux:
                            nan_boxed_wire_name = f"{ext_wire_name}_nan_boxed"
                            extended_input_signals.append(nan_boxed_wire_name)
                        else:
                            extended_input_signals.append(ext_wire_name)
                    else:
                        # Generate inline extension for signals without graph nodes
                        # Note: MuxBuilder now creates zero_extend nodes upstream for known-width signals
                        if use_nan_boxing or (use_nan_box_dual and is_frf_mux):
                            extended_input_signals.append(f"{{{{{ext_bits}{{1'b1}}}}, {src_name}}}")
                        else:
                            extended_input_signals.append(f"{{{{{ext_bits}'d0}}, {src_name}}}")
            else:
                # No width extension needed, but check if this is a nan_box_dual node
                # that needs to use the NaN-boxed version for FRF mux
                use_nan_box_dual = source_node.data.get('nan_box_dual', False) if source_node else False
                is_frf_mux = 'frf' in node.id.lower() and 'write_data' in node.id.lower()

                if use_nan_box_dual and is_frf_mux:
                    # Use the NaN-boxed version of this signal
                    nan_boxed_name = f"{src_name}_nan_boxed"
                    extended_input_signals.append(nan_boxed_name)
                else:
                    extended_input_signals.append(src_name)

        input_signals = extended_input_signals

        # Get output signal
        output_signal = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.data.get('name', node.id)))

        # Determine select signal based on mux type
        select_type = generator.select_type if hasattr(generator, 'select_type') else 'binary'

        if select_type in ['one_hot', 'priority']:
            # For one-hot or priority mux, pass the select signals as a list
            if select_signals:
                # Use the collected select signals as a list
                select_signal = select_signals
            else:
                # Fallback: create generic select signals and declare them
                select_signal = []
                for i in range(len(input_signals)):
                    sel_name = f"{output_signal}_sel_{i}"
                    select_signal.append(sel_name)
                    if sel_name not in self.declared_names:
                        self.wire_declarations.append({
                            'name': sel_name,
                            'bit_width': 1
                        })
                        self.declared_names.add(sel_name)
        else:
            # For binary mux, create select signal based on control logic
            # Prefer the orthogon global selector if available (data-select mux)
            select_signal = orthogon_selector_signal
            if not select_signal:
                # Look for control/select edge
                for edge in node.incoming_edges:
                    if edge.data.get('type') in ['mux_select', 'control']:
                        select_signal = self.node_id_to_name.get(edge.source.id, edge.source.data.get('name'))
                        select_signal = self._sanitize_identifier(select_signal)
                        break

            if not select_signal:
                # Default: create select wire name
                select_signal = f"{output_signal}_sel"
                # Declare select wire
                select_width = (len(input_signals) - 1).bit_length() if len(input_signals) > 1 else 1
                if f"{select_signal}" not in self.declared_names:
                    self.wire_declarations.append({
                        'name': select_signal,
                        'bit_width': select_width
                    })
                    self.declared_names.add(select_signal)

        # Skip mux generation if the output signal is already assigned
        # (this can happen when a ternary expression is also represented as a mux node)
        if output_signal in self.assigned_signals:
            return

        # Generate inline mux logic instead of module instantiation
        try:
            inline_logic = self._generate_inline_mux_logic(
                node=node,
                generator=generator,
                input_signals=input_signals,
                input_indices=input_indices,
                select_signal=select_signal,
                output_signal=output_signal,
                default_signal=default_signal
            )
            if inline_logic:
                self.comb_logic += inline_logic
                self.assigned_signals.add(output_signal)
        except Exception as e:
            print(f"Warning: Failed to generate inline MUX logic for {node.id}: {e}")

    def _generate_counter_instantiation(self, node: Node, generator):
        """Generate instantiation for a counter (serialization, memory access, etc.)."""
        counter_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))
        node_type = node.data.get('type', '')

        # Get counter parameters from node data
        max_count = node.data.get('max_count', 0)
        bit_width = node.data.get('bit_width', 8)
        operation_id = node.data.get('operation_id', '')

        # For uarch_counter (static latency), generate FSM with start signal
        if node_type == 'uarch_counter' and operation_id:
            # Find the associated operation to get control signals
            operation = self.graph.nodes.get(operation_id)
            if operation and operation.data.get('start_signal'):
                start_signal_id = operation.data.get('start_signal')
                complete_signal_id = operation.data.get('complete_signal')
                idle_signal_id = operation.data.get('idle_signal')
                latency_cycles = operation.data.get('latency_cycles', max_count + 1)

                # Use LatencyCounterGenerator for consistent FSM generation
                from .verilog_module_generators import LatencyCounterGenerator
                import math

                counter_bits = max(2, math.ceil(math.log2(latency_cycles + 1)))

                gen = LatencyCounterGenerator(
                    name=counter_name,
                    width=counter_bits,
                    latency_mode='static',
                    static_latency=latency_cycles
                )

                # Get start signal expression
                start_node = self.graph.nodes.get(start_signal_id)
                if start_node and start_node.incoming_edges:
                    # Start is wired to something
                    for edge in start_node.incoming_edges:
                        start_expr = self.node_id_to_name.get(
                            edge.source.id, self._sanitize_identifier(edge.source.id))
                        break
                elif operation.data.get('type') == 'fp_operation':
                    # For FP operations, use the FP-specific start signal we created
                    fp_intrinsic_name = operation.data.get('name', operation.id)
                    sanitized_fp_name = self._sanitize_identifier(fp_intrinsic_name)
                    start_expr = f"{sanitized_fp_name}_start"
                else:
                    # Start not wired - use placeholder
                    start_expr = "1'b1"  # Always start (legacy behavior)

                complete_name = self._sanitize_identifier(complete_signal_id) if complete_signal_id else f"{counter_name}_complete"
                idle_name = self._sanitize_identifier(idle_signal_id) if idle_signal_id else None

                # Generate the FSM logic
                logic = gen.generate_inline_logic(
                    counter_reg=counter_name,
                    target_reg=f"{counter_name}_target",  # Not used for static
                    start_expr=start_expr,
                    complete_name=complete_name,
                    idle_name=idle_name
                )

                # Add declarations (counter already declared, but add complete/idle if needed)
                if complete_name not in self.declared_names:
                    self.declarations += f"    wire {complete_name};\n"
                    self.declared_names.add(complete_name)
                if idle_name and idle_name not in self.declared_names:
                    self.declarations += f"    wire {idle_name};\n"
                    self.declared_names.add(idle_name)

                self.comb_logic += f"\n    // Static latency signals for {operation_id}\n"
                self.comb_logic += logic['comb_logic']
                self.seq_logic += logic['seq_logic']

                print(f"  Generated static latency FSM for {operation_id} ({latency_cycles} cycles)")
                return

        # Default: just add a comment for other counter types
        comment = f"    // Counter: {counter_name} (max={max_count}, width={bit_width})\n"
        self.comb_logic += comment

    def _generate_variable_latency_memory_logic(self):
        """Generate FSM logic for variable latency memories.

        For memories with variable_latency=True, generates:
        - State machine (idle -> busy -> complete) with random latency
        - Complete signal output
        - Idle signal output

        Uses LatencyCounterGenerator for consistent FSM generation.
        """
        from .verilog_module_generators import LatencyCounterGenerator

        self.var_latency_logic = ""

        # Find memories with variable latency
        var_latency_memories = []
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if (node.data.get('is_memory', False) and
                getattr(node, 'variable_latency', False)):
                var_latency_memories.append(node)

        if not var_latency_memories:
            return

        for memory in var_latency_memories:
            mem_name = memory.data.get('name', memory.id)
            sanitized_name = self._sanitize_identifier(mem_name)

            # Get the control signal nodes
            start_signal = memory.data.get('start_signal')
            complete_signal = memory.data.get('complete_signal')
            idle_signal = memory.data.get('idle_signal')

            if not complete_signal:
                print(f"  Warning: Variable latency memory {mem_name} missing complete signal")
                continue

            # Read latency bounds from node data (set by set_memory_variable_latency)
            min_latency = memory.data.get('min_latency', 2)   # Default: minimum 2 cycles
            max_latency = memory.data.get('max_latency', 15)  # Default: maximum 15 cycles

            # Use static mode if min == max, otherwise variable (random) mode
            if min_latency == max_latency:
                latency_mode = 'static'
                print(f"  Generating static latency ({min_latency} cycles) logic for memory: {mem_name}")
            else:
                latency_mode = 'variable'
                print(f"  Generating random latency ({min_latency}-{max_latency} cycles) logic for memory: {mem_name}")

            # Create generator with appropriate latency mode
            gen = LatencyCounterGenerator(
                name=sanitized_name,
                width=4,  # Enough for 0-15
                latency_mode=latency_mode,
                static_latency=min_latency,  # Used in static mode
                min_latency=min_latency,     # Used in variable mode
                max_latency=max_latency
            )

            counter_reg = f"{sanitized_name}_latency_counter"
            target_reg = f"{sanitized_name}_latency_target" if latency_mode == 'variable' else None
            complete_name = self._sanitize_identifier(complete_signal)
            idle_name = self._sanitize_identifier(idle_signal) if idle_signal else None

            # Determine start expression
            if start_signal:
                start_name = self._sanitize_identifier(start_signal)
                start_node = self.graph.nodes.get(start_signal)
                if start_node and start_node.incoming_edges:
                    for edge in start_node.incoming_edges:
                        source_name = self.node_id_to_name.get(
                            edge.source.id, self._sanitize_identifier(edge.source.id))
                        break
                    start_expr = start_name
                    # Wire up the start signal
                    if start_name not in self.declared_names:
                        self.declarations += f"    wire {start_name};\n"
                        self.declared_names.add(start_name)
                    self.comb_logic += f"    assign {start_name} = {source_name};\n"
                    print(f"    {start_name} = {source_name}")
                else:
                    start_expr = "1'b0"
                    print(f"    Warning: {start_signal} not wired in graph")
            else:
                start_expr = "1'b0"

            # For externalized memories, use valid-ready handshake signals instead of internal counter
            if sanitized_name in self.externalized_memories:
                # Declare complete and idle signals only
                if complete_name not in self.declared_names:
                    self.declarations += f"    wire {complete_name};\n"
                    self.declared_names.add(complete_name)
                if idle_name and idle_name not in self.declared_names:
                    self.declarations += f"    wire {idle_name};\n"
                    self.declared_names.add(idle_name)

                # Mark that complete/idle will be assigned by _finalize_externalized_memory_ports
                # The actual assignment happens after mem_ext_stall is generated
                self._externalized_memory_complete_signals = getattr(self, '_externalized_memory_complete_signals', {})
                self._externalized_memory_complete_signals[sanitized_name] = {
                    'complete_name': complete_name,
                    'idle_name': idle_name
                }

                self.comb_logic += f"\n    // Externalized memory {mem_name}: complete/idle derived from valid-ready handshake\n"
                print(f"  Externalized memory {mem_name}: complete will use valid-ready handshake")

                # Still need to generate arbiter grant registers for cache arbitration
                self._generate_memory_arbiter_logic(memory, sanitized_name, start_signal, complete_signal)

                continue  # Skip counter-based FSM generation

            # Generate the FSM logic using the unified generator
            logic = gen.generate_inline_logic(
                counter_reg=counter_reg,
                target_reg=target_reg,
                start_expr=start_expr,
                complete_name=complete_name,
                idle_name=idle_name
            )

            # Add declarations
            self.declarations += logic['declarations']
            if complete_name not in self.declared_names:
                self.declarations += f"    wire {complete_name};\n"
                self.declared_names.add(complete_name)
            if idle_name and idle_name not in self.declared_names:
                self.declarations += f"    wire {idle_name};\n"
                self.declared_names.add(idle_name)

            # Add combinational and sequential logic
            if latency_mode == 'static':
                self.comb_logic += f"\n    // Static latency signals for {mem_name} ({min_latency} cycles)\n"
            else:
                self.comb_logic += f"\n    // Variable latency signals for {mem_name} (random {min_latency}-{max_latency} cycles)\n"
            self.comb_logic += logic['comb_logic']
            self.seq_logic += logic['seq_logic']

            # Generate arbiter grant registers if multiple caches share this memory
            self._generate_memory_arbiter_logic(memory, sanitized_name, start_signal, complete_signal)

    def _generate_memory_arbiter_logic(self, memory: 'Node', mem_name: str,
                                        start_signal: str, complete_signal: str):
        """Generate grant register logic for memory arbitration.

        When multiple caches share a memory, we need to track which source was
        granted access and only signal completion to that source. This generates:
        - Grant signal declarations (combinational)
        - Registered grant declarations
        - Sequential logic to latch grants on start and clear on complete
        """
        # Find registered grant nodes for this memory
        registered_grants = []
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if (node.data.get('is_registered_grant') and
                node.data.get('latch_condition') == start_signal):
                registered_grants.append(node)

        if not registered_grants:
            return

        print(f"  Generating arbiter logic for {mem_name} with {len(registered_grants)} grant registers")

        # Get start and complete signal names
        start_name = self._sanitize_identifier(start_signal) if start_signal else None
        complete_name = self._sanitize_identifier(complete_signal) if complete_signal else None

        if not start_name or not complete_name:
            print(f"    Warning: Missing start or complete signal for arbiter")
            return

        self.comb_logic += f"\n    // Memory arbiter grants for {mem_name}\n"

        # Declare grant signals (the combinational priority logic)
        # Note: grant signals may already be declared/assigned by normal graph processing
        for reg_node in registered_grants:
            grant_signal_id = reg_node.data.get('grant_signal')
            if not grant_signal_id:
                continue

            grant_node = self.graph.nodes.get(grant_signal_id)
            if not grant_node:
                continue

            grant_name = self._sanitize_identifier(grant_signal_id)
            reg_name = self._sanitize_identifier(reg_node.id)

            # Only declare the registered grant (grant signal is handled by normal processing)
            if reg_name not in self.declared_names:
                self.declarations += f"    reg {reg_name};\n"
                self.declared_names.add(reg_name)

        # Generate sequential logic for registered grants
        self.seq_logic += f"\n    // Arbiter grant registers for {mem_name}\n"
        self.seq_logic += f"    always @(posedge clk) begin\n"
        self.seq_logic += f"        if (reset) begin\n"

        for reg_node in registered_grants:
            reg_name = self._sanitize_identifier(reg_node.id)
            self.seq_logic += f"            {reg_name} <= 1'b0;\n"

        self.seq_logic += f"        end else begin\n"
        self.seq_logic += f"            if ({start_name}) begin\n"

        for reg_node in registered_grants:
            grant_signal_id = reg_node.data.get('grant_signal')
            grant_name = self._sanitize_identifier(grant_signal_id)
            reg_name = self._sanitize_identifier(reg_node.id)
            self.seq_logic += f"                {reg_name} <= {grant_name};\n"

        self.seq_logic += f"            end else if ({complete_name}) begin\n"

        for reg_node in registered_grants:
            reg_name = self._sanitize_identifier(reg_node.id)
            self.seq_logic += f"                {reg_name} <= 1'b0;\n"

        self.seq_logic += f"            end\n"
        self.seq_logic += f"        end\n"
        self.seq_logic += f"    end\n"

        print(f"    Generated arbiter registers: {[self._sanitize_identifier(n.id) for n in registered_grants]}")

    def _generate_expression_for_node(self, node: 'Node') -> str:
        """Generate Verilog expression for a node based on its type and inputs."""
        node_type = node.data.get('type')

        if node_type == 'var':
            # Simple assignment - get the source
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'assignment':
                    return self._sanitize_identifier(edge.source.id)
            return self._sanitize_identifier(node.id)

        elif node_type == 'logical_and':
            # AND gate - collect all inputs
            inputs = []
            for edge in sorted(node.incoming_edges, key=lambda e: e.data.get('operand_position', 0)):
                if edge.data.get('type') == 'logic_input':
                    inputs.append(self._sanitize_identifier(edge.source.id))
            if inputs:
                return ' && '.join(inputs)
            return "1'b1"

        elif node_type == 'logical_or':
            # OR gate - collect all inputs
            inputs = []
            for edge in sorted(node.incoming_edges, key=lambda e: e.data.get('operand_position', 0)):
                if edge.data.get('type') == 'logic_input':
                    inputs.append(self._sanitize_identifier(edge.source.id))
            if inputs:
                return ' || '.join(inputs)
            return "1'b0"

        elif node_type == 'operation':
            operator = node.data.get('operator', '')
            if operator == '!':
                # NOT operation
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'operand':
                        return f"!{self._sanitize_identifier(edge.source.id)}"
                return "1'b0"

        # Default: just use the node name
        return self._sanitize_identifier(node.id)

    def _extract_memory_port_name(self, port_name: str, mem_name: str) -> str:
        """Extract the port-specific name from a memory access port name.

        For memories with multiple ports (like umem[pc] and umem[ea]), this extracts
        the port identifier (pc, ea) to create distinct external port names.

        Examples:
            umem[pc]_rd -> umem_pc
            umem[ea]_rd -> umem_ea
            umem_pc__rd -> umem_pc
            umem_ea_rd_addr_mux -> umem_ea
            umem_shared_rd -> umem (no specific port)
            umem_shared_wr_1 -> umem_1 (multi-port write port)

        Args:
            port_name: The internal port name (e.g., 'umem[pc]_rd' or 'umem_pc__rd')
            mem_name: The base memory name (e.g., 'umem')

        Returns:
            A clean port name for external signals (e.g., 'umem_pc' or 'umem')
        """
        import re

        # Pattern 0: Multi-port shared write/read ports with index suffix
        # e.g., umem_shared_wr_1 -> umem_1, umem_shared_wr_2 -> umem_2
        # The index comes AFTER the _wr/_rd suffix
        multi_port_match = re.match(
            rf'^{re.escape(mem_name)}_shared_(?:wr|rd)_(\d+)(?:_|$)',
            port_name
        )
        if multi_port_match:
            port_index = multi_port_match.group(1)
            return f"{mem_name}_{port_index}"

        # Pattern 1: mem[index]_suffix (e.g., umem[pc]_rd)
        bracket_match = re.match(rf'{re.escape(mem_name)}\[([^\]]+)\]', port_name)
        if bracket_match:
            port_suffix = bracket_match.group(1)
            return f"{mem_name}_{self._sanitize_identifier(port_suffix)}"

        # Pattern 2: mem_index__suffix or mem_index_suffix (e.g., umem_pc__rd, umem_ea_rd)
        # Look for patterns like mem_XXX_rd, mem_XXX_wr, mem_XXX_addr_mux, etc.
        # But avoid matching mem_shared_rd (which is the combined port)
        suffix_patterns = [
            r'__rd$', r'__wr$',  # Double underscore first (more specific)
            r'_rd$', r'_wr$',
            r'_rd_addr', r'_wr_addr', r'_rd_data', r'_wr_data',
            r'_addr_mux', r'_data_mux', r'_enable'
        ]

        for suffix in suffix_patterns:
            # Match: mem_portname{suffix}
            # The portname should NOT end with underscore (to avoid matching double underscores)
            pattern = rf'^{re.escape(mem_name)}_([a-zA-Z][a-zA-Z0-9]*(?:_[a-zA-Z0-9]+)*?)(?:{suffix})'
            match = re.match(pattern, port_name)
            if match:
                port_suffix = match.group(1)
                # Strip trailing underscores from the suffix
                port_suffix = port_suffix.rstrip('_')
                # Skip 'shared' as it's not a port-specific name
                if port_suffix == 'shared':
                    continue
                if port_suffix in ['read', 'write']:
                    continue
                if port_suffix:
                    return f"{mem_name}_{port_suffix}"

        # No port-specific identifier found - use just the memory name
        return mem_name

    def _finalize_externalized_memory_ports(self):
        """Add externalized memory port declarations and generate connection logic.

        This implements the valid-ready handshake protocol for external memory.
        For memories with multiple ports (like umem[pc] and umem[ea]), separate
        external ports are generated for each access point:

          Read Port (for each read access like umem[pc], umem[ea]):
            Output: {mem}_{port}_read_req_addr, {mem}_{port}_read_req_valid
            Input:  {mem}_{port}_read_resp_data, {mem}_{port}_read_resp_ready

          Write Port (for each write access like umem[ea]):
            Output: {mem}_{port}_write_req_addr, {mem}_{port}_write_req_data,
                    {mem}_{port}_write_req_we, {mem}_{port}_write_req_valid
            Input:  {mem}_{port}_write_resp_ready

        For variable latency (use_valid_ready=True):
          - FSM tracks pending requests per port
          - req_valid held high until resp_ready received
          - complete is a one-cycle pulse when response received
          - idle indicates no pending requests
          - All state updates gated by mem_ext_stall

        The stall logic is:
          stall = OR of all (req_valid && !resp_ready) signals
        """
        if not self.externalized_memories:
            return

        print(f"\n=== Externalized Memory Ports (Multi-Port Support) ===")

        # Track port signals for module header update
        port_additions = []
        stall_signals = []

        # Track unique port names to avoid duplicates
        generated_read_ports = set()
        generated_write_ports = set()

        # Process read ports - generate separate external port for each tracked port
        for mem_name in sorted(self.externalized_memories):
            mem_info = self.memory_declarations.get(mem_name, {})
            use_valid_ready = mem_info.get('use_valid_ready', True)
            externalize_read = mem_info.get('externalize_read', True)
            data_width = mem_info.get('bit_width', 32)
            # For externalized memory ports, use full address width (not ISA-limited addr_width)
            # This allows external memory to be any size while ISA addr_width was for internal sizing
            addr_width = mem_info.get('externalized_addr_width', 32)

            if not externalize_read:
                continue

            # Find all read ports for this memory
            read_ports_for_mem = [p for p in self.memory_read_ports if p['mem'] == mem_name]

            if read_ports_for_mem:
                print(f"  Memory: {mem_name}")
                print(f"    Read ports: {len(read_ports_for_mem)}")
                print(f"    Protocol: {'Valid-Ready' if use_valid_ready else 'Simple Enable'}")

                for read_port in read_ports_for_mem:
                    # Extract port-specific name (e.g., umem_pc from umem[pc]_rd)
                    port_name = read_port['port_name']
                    ext_port_name = self._extract_memory_port_name(port_name, mem_name)

                    # Skip if we already generated this port
                    if ext_port_name in generated_read_ports:
                        continue
                    generated_read_ports.add(ext_port_name)

                    # Store the external port name in the port dict for later connection
                    read_port['ext_port_name'] = ext_port_name

                    port_data_width = read_port.get('data_width', data_width)
                    # For externalized memory, always use full address width (not port's ISA-limited width)
                    port_addr_width = addr_width  # addr_width is already set to externalized_addr_width

                    print(f"      Port: {ext_port_name} (from {port_name})")

                    # Outputs (requests)
                    port_additions.append(f"    output wire [{port_addr_width-1}:0] {ext_port_name}_read_req_addr")
                    port_additions.append(f"    output wire {ext_port_name}_read_req_valid")
                    # Inputs (responses)
                    port_additions.append(f"    input wire [{port_data_width-1}:0] {ext_port_name}_read_resp_data")
                    if use_valid_ready:
                        port_additions.append(f"    input wire {ext_port_name}_read_resp_ready")
                        # Note: stall signals for FSM ports are generated in _generate_variable_latency_fsm
            else:
                # No tracked read ports - create a single generic read port
                ext_port_name = mem_name
                if ext_port_name not in generated_read_ports:
                    generated_read_ports.add(ext_port_name)
                    print(f"  Memory: {mem_name}")
                    print(f"    Read port: {ext_port_name} (generic)")

                    port_additions.append(f"    output wire [{addr_width-1}:0] {ext_port_name}_read_req_addr")
                    port_additions.append(f"    output wire {ext_port_name}_read_req_valid")
                    port_additions.append(f"    input wire [{data_width-1}:0] {ext_port_name}_read_resp_data")
                    if use_valid_ready:
                        port_additions.append(f"    input wire {ext_port_name}_read_resp_ready")
                        # Note: stall signals for FSM ports are generated in _generate_variable_latency_fsm

        # Process write ports - generate separate external port for each tracked port
        for mem_name in sorted(self.externalized_memories):
            mem_info = self.memory_declarations.get(mem_name, {})
            use_valid_ready = mem_info.get('use_valid_ready', True)
            externalize_write = mem_info.get('externalize_write', True)
            data_width = mem_info.get('bit_width', 32)
            # For externalized memory ports, use full address width (not ISA-limited addr_width)
            addr_width = mem_info.get('externalized_addr_width', 32)

            if not externalize_write:
                continue

            # Find all write ports for this memory
            write_ports_for_mem = [p for p in self.memory_write_ports if p['mem'] == mem_name]

            if write_ports_for_mem:
                print(f"    Write ports: {len(write_ports_for_mem)}")

                for write_port in write_ports_for_mem:
                    # Extract port-specific name (e.g., umem_ea from umem[ea]_wr)
                    port_name = write_port['port_name']
                    ext_port_name = self._extract_memory_port_name(port_name, mem_name)

                    # Skip if we already generated this port
                    if ext_port_name in generated_write_ports:
                        continue
                    generated_write_ports.add(ext_port_name)

                    # Store the external port name in the port dict for later connection
                    write_port['ext_port_name'] = ext_port_name

                    port_data_width = write_port.get('data_width', data_width)
                    # For externalized memory, always use full address width (not port's ISA-limited width)
                    port_addr_width = addr_width  # addr_width is already set to externalized_addr_width
                    num_bytes = max(1, port_data_width // 8)

                    print(f"      Port: {ext_port_name} (from {port_name})")

                    # Outputs (requests)
                    port_additions.append(f"    output wire [{port_addr_width-1}:0] {ext_port_name}_write_req_addr")
                    port_additions.append(f"    output wire [{port_data_width-1}:0] {ext_port_name}_write_req_data")
                    port_additions.append(f"    output wire [{num_bytes-1}:0] {ext_port_name}_write_req_we")
                    port_additions.append(f"    output wire {ext_port_name}_write_req_valid")
                    # Inputs (responses)
                    if use_valid_ready:
                        port_additions.append(f"    input wire {ext_port_name}_write_resp_ready")
                        # Note: stall signals for FSM ports are generated in _generate_variable_latency_fsm
            else:
                # No tracked write ports - create a single generic write port
                ext_port_name = mem_name
                if ext_port_name not in generated_write_ports:
                    generated_write_ports.add(ext_port_name)
                    num_bytes = max(1, data_width // 8)
                    print(f"    Write port: {ext_port_name} (generic)")

                    port_additions.append(f"    output wire [{addr_width-1}:0] {ext_port_name}_write_req_addr")
                    port_additions.append(f"    output wire [{data_width-1}:0] {ext_port_name}_write_req_data")
                    port_additions.append(f"    output wire [{num_bytes-1}:0] {ext_port_name}_write_req_we")
                    port_additions.append(f"    output wire {ext_port_name}_write_req_valid")
                    if use_valid_ready:
                        port_additions.append(f"    input wire {ext_port_name}_write_resp_ready")
                        # Note: stall signals for FSM ports are generated in _generate_variable_latency_fsm

        # Update module header with new ports
        if port_additions:
            # Find the closing paren in module_header and add ports before it
            if ');\n' in self.module_header:
                # Add external memory ports before the closing paren
                port_str = ',\n'.join(port_additions)
                self.module_header = self.module_header.replace(
                    ');\n',
                    f',\n    // Externalized memory ports (multi-port valid-ready handshake)\n{port_str}\n);\n'
                )

        # Generate connection logic for the externalized ports
        self.comb_logic += "\n    // === Externalized Memory Port Connections ===\n"

        # Track ports that need FSM for variable latency
        variable_latency_read_ports = []
        variable_latency_write_ports = []

        # Connect each read port
        for mem_name in sorted(self.externalized_memories):
            mem_info = self.memory_declarations.get(mem_name, {})
            externalize_read = mem_info.get('externalize_read', True)
            use_valid_ready = mem_info.get('use_valid_ready', False)

            if not externalize_read:
                continue

            read_ports_for_mem = [p for p in self.memory_read_ports if p['mem'] == mem_name]

            for read_port in read_ports_for_mem:
                ext_port_name = read_port.get('ext_port_name', mem_name)
                addr_signal = read_port['addr_signal']

                # Look up the enable signal for this read port
                # Naming convention: {ext_port_name}_rd_enable (e.g., umem_addr_rd_enable)
                enable_signal = None
                enable_patterns = [
                    f"{ext_port_name}_rd_enable",
                    f"{ext_port_name}_read_enable",
                    f"{ext_port_name}_enable",
                ]

                # For cache refill ports, also check for {cache}_refill_req
                # E.g., umem_dcache_refill_addr -> dcache_refill_req
                import re
                refill_match = re.match(rf'{re.escape(mem_name)}_(\w+)_refill_addr', ext_port_name)
                if refill_match:
                    cache_name = refill_match.group(1)
                    enable_patterns.append(f"{cache_name}_refill_req")

                for pattern in enable_patterns:
                    if pattern in self.declared_names:
                        enable_signal = pattern
                        break
                    # Also check node_id_to_name
                    for node_id, name in self.node_id_to_name.items():
                        if name == pattern or node_id == pattern:
                            enable_signal = pattern
                            break
                    if enable_signal:
                        break

                self.comb_logic += f"\n    // {ext_port_name} read interface\n"
                self.comb_logic += f"    assign {ext_port_name}_read_req_addr = {addr_signal};\n"

                if use_valid_ready:
                    # For variable latency, use FSM to track pending requests
                    # Enable signal determines when a NEW request starts
                    if enable_signal:
                        variable_latency_read_ports.append({
                            'ext_port_name': ext_port_name,
                            'enable_signal': enable_signal,
                            'is_ifetch': ext_port_name.endswith('_pc')  # Instruction fetch port
                        })
                        # req_valid will be generated by FSM
                    else:
                        # No enable signal found - assume always requesting (instruction fetch)
                        # Still need stall signal for variable latency
                        self.comb_logic += f"    assign {ext_port_name}_read_req_valid = 1'b1;  // Instruction fetch (always valid)\n"
                        stall_signals.append(f"(!{ext_port_name}_read_resp_ready)")
                else:
                    # Single-cycle memory - use enable signal or constant 1
                    if enable_signal:
                        self.comb_logic += f"    assign {ext_port_name}_read_req_valid = {enable_signal};\n"
                    else:
                        self.comb_logic += f"    assign {ext_port_name}_read_req_valid = 1'b1;  // Single-cycle (always valid)\n"

            # Fallback for memories with no tracked read ports
            if not read_ports_for_mem:
                read_addr_signal = self._find_memory_signal(mem_name, 'read', 'addr')
                read_enable_signal = self._find_memory_signal(mem_name, 'read', 'enable')

                self.comb_logic += f"\n    // {mem_name} read interface (generic)\n"
                if read_addr_signal:
                    self.comb_logic += f"    assign {mem_name}_read_req_addr = {read_addr_signal};\n"
                else:
                    addr_width = mem_info.get('addr_width', 32)
                    self.comb_logic += f"    assign {mem_name}_read_req_addr = {addr_width}'h0;  // TODO: connect to address mux\n"

                if use_valid_ready:
                    if read_enable_signal:
                        variable_latency_read_ports.append({
                            'ext_port_name': mem_name,
                            'enable_signal': read_enable_signal,
                            'is_ifetch': False
                        })
                    else:
                        # Variable latency but no enable signal - always request, still need stall
                        self.comb_logic += f"    assign {mem_name}_read_req_valid = 1'b1;  // Always valid\n"
                        stall_signals.append(f"(!{mem_name}_read_resp_ready)")
                elif read_enable_signal:
                    self.comb_logic += f"    assign {mem_name}_read_req_valid = {read_enable_signal};\n"
                else:
                    self.comb_logic += f"    assign {mem_name}_read_req_valid = 1'b1;  // Always valid (single-cycle)\n"

        # Connect each write port
        for mem_name in sorted(self.externalized_memories):
            mem_info = self.memory_declarations.get(mem_name, {})
            externalize_write = mem_info.get('externalize_write', True)
            use_valid_ready = mem_info.get('use_valid_ready', False)

            if not externalize_write:
                continue

            write_ports_for_mem = [p for p in self.memory_write_ports if p['mem'] == mem_name]

            for write_port in write_ports_for_mem:
                ext_port_name = write_port.get('ext_port_name', mem_name)
                addr_signal = write_port['addr_signal']
                data_signal = write_port['data_signal']
                enable_signal = write_port.get('enable_signal', '')
                port_data_width = write_port.get('data_width', 32)
                num_bytes = max(1, port_data_width // 8)
                combined_byte_enable = write_port.get('combined_byte_enable', '')

                self.comb_logic += f"\n    // {ext_port_name} write interface\n"
                self.comb_logic += f"    assign {ext_port_name}_write_req_addr = {addr_signal};\n"
                self.comb_logic += f"    assign {ext_port_name}_write_req_data = {data_signal};\n"

                if enable_signal:
                    if use_valid_ready:
                        # Track write port for FSM generation
                        variable_latency_write_ports.append({
                            'ext_port_name': ext_port_name,
                            'enable_signal': enable_signal,
                            'num_bytes': num_bytes,
                            'combined_byte_enable': combined_byte_enable
                        })
                        # req_valid and byte_enable will be generated by FSM
                    else:
                        self.comb_logic += f"    assign {ext_port_name}_write_req_valid = {enable_signal};\n"
                        # Use combined byte enable signal if available, otherwise all bytes
                        if combined_byte_enable:
                            self.comb_logic += f"    assign {ext_port_name}_write_req_we = {combined_byte_enable};\n"
                        else:
                            all_bytes = f"{num_bytes}'h{(1 << num_bytes) - 1:x}"
                            self.comb_logic += f"    assign {ext_port_name}_write_req_we = {enable_signal} ? {all_bytes} : {num_bytes}'h0;\n"
                else:
                    self.comb_logic += f"    assign {ext_port_name}_write_req_valid = 1'b0;  // No enable signal found\n"
                    self.comb_logic += f"    assign {ext_port_name}_write_req_we = {num_bytes}'h0;\n"

            # Fallback for memories with no tracked write ports
            if not write_ports_for_mem:
                # Check if dcache is enabled - if so, use dcache write-through signals
                dcache_wt_addr = 'dcache_write_through_addr'
                dcache_wt_data = 'dcache_write_through_data'
                dcache_wt_be = 'dcache_write_through_byte_enable'
                dcache_wt_req = 'dcache_write_through_req'
                dcache_enabled = (dcache_wt_addr in self.declared_names or
                                  dcache_wt_req in self.declared_names)

                if dcache_enabled:
                    # Use dcache write-through interface for external memory writes
                    write_addr_signal = dcache_wt_addr
                    write_data_signal = dcache_wt_data
                    write_enable_signal = dcache_wt_req
                    combined_byte_enable = dcache_wt_be

                    self.comb_logic += f"\n    // {mem_name} write interface (via dcache write-through)\n"
                    self.comb_logic += f"    assign {mem_name}_write_req_addr = {write_addr_signal};\n"
                    self.comb_logic += f"    assign {mem_name}_write_req_data = {write_data_signal};\n"

                    if use_valid_ready:
                        data_width = mem_info.get('bit_width', 32)
                        num_bytes = max(1, data_width // 8)
                        variable_latency_write_ports.append({
                            'ext_port_name': mem_name,
                            'enable_signal': write_enable_signal,
                            'num_bytes': num_bytes,
                            'combined_byte_enable': combined_byte_enable
                        })
                    else:
                        self.comb_logic += f"    assign {mem_name}_write_req_valid = {write_enable_signal};\n"
                        self.comb_logic += f"    assign {mem_name}_write_req_we = {combined_byte_enable};\n"
                    # Skip the rest of the fallback logic
                    continue

                # Try to find write port signals by looking at graph edges
                # First, find the memory_write_port node for this memory
                write_port_node = None
                for node in self.graph.nodes.values():
                    if (node.data.get('type') == 'memory_write_port' and
                        node.data.get('base_memory') == mem_name):
                        write_port_node = node
                        break

                write_addr_signal = None
                write_data_signal = None
                write_enable_signal = None
                combined_byte_enable = None

                if write_port_node:
                    # Look at incoming edges to find the signals
                    for edge in write_port_node.incoming_edges:
                        edge_type = edge.data.get('type')
                        source_name = self.node_id_to_name.get(edge.source.id,
                                                               self._sanitize_identifier(edge.source.id))
                        if edge_type == 'write_address':
                            write_addr_signal = source_name
                        elif edge_type == 'write_data':
                            write_data_signal = source_name
                        elif edge_type == 'write_enable':
                            write_enable_signal = source_name
                        elif edge_type == 'byte_enable':
                            # Track byte enable (will use combined if available)
                            pass

                    # Check for combined byte enable from node data
                    combined_byte_enable = write_port_node.data.get('combined_byte_enable', '')
                    if combined_byte_enable:
                        combined_byte_enable = self.node_id_to_name.get(
                            combined_byte_enable, self._sanitize_identifier(combined_byte_enable))
                    else:
                        # If no combined_byte_enable, try to construct from store_byte_enables
                        store_byte_enables = write_port_node.data.get('store_byte_enables', {})
                        if store_byte_enables:
                            # Collect individual byte enable signals
                            byte_enable_parts = []
                            for store_type, be_signal in sorted(store_byte_enables.items()):
                                # Get the corresponding enable signal for this store type
                                enable_patterns = [
                                    f"PIPE_Memory_PIPE_Execute_{store_type}_enable_PIPE_PIPE",
                                    f"PIPE_Memory_{store_type}_enable_PIPE",
                                    f"{store_type}_enable"
                                ]
                                for pattern in enable_patterns:
                                    if pattern in self.declared_names:
                                        be_name = self.node_id_to_name.get(be_signal, self._sanitize_identifier(be_signal))
                                        byte_enable_parts.append(f"({be_name} & {{4{{{pattern}}}}})")
                                        break
                            # Also handle full-word stores (sw) which use all 4 bytes
                            if 'sw' in write_port_node.data.get('writers', []):
                                enable_patterns = [
                                    f"PIPE_Memory_PIPE_Execute_sw_enable_PIPE_PIPE",
                                    f"PIPE_Memory_sw_enable_PIPE",
                                    f"sw_enable"
                                ]
                                for pattern in enable_patterns:
                                    if pattern in self.declared_names:
                                        byte_enable_parts.append(f"{{4{{{pattern}}}}}")
                                        break
                            if byte_enable_parts:
                                # Generate combined byte enable as OR of all parts
                                combined_expr = " | ".join(byte_enable_parts)
                                combined_byte_enable_name = f"{mem_name}_combined_byte_enable"
                                self.comb_logic += f"    wire [3:0] {combined_byte_enable_name} = {combined_expr};\n"
                                combined_byte_enable = combined_byte_enable_name

                # Fall back to pattern matching if graph search didn't find signals
                if not write_addr_signal:
                    write_addr_signal = self._find_memory_signal(mem_name, 'write', 'addr')
                if not write_data_signal:
                    write_data_signal = self._find_memory_signal(mem_name, 'write', 'data')
                if not write_enable_signal:
                    write_enable_signal = self._find_memory_signal(mem_name, 'write', 'enable')

                data_width = mem_info.get('bit_width', 32)
                num_bytes = max(1, data_width // 8)

                self.comb_logic += f"\n    // {mem_name} write interface (generic)\n"
                if write_addr_signal:
                    self.comb_logic += f"    assign {mem_name}_write_req_addr = {write_addr_signal};\n"
                else:
                    addr_width = mem_info.get('addr_width', 32)
                    self.comb_logic += f"    assign {mem_name}_write_req_addr = {addr_width}'h0;  // TODO: connect\n"

                if write_data_signal:
                    self.comb_logic += f"    assign {mem_name}_write_req_data = {write_data_signal};\n"
                else:
                    self.comb_logic += f"    assign {mem_name}_write_req_data = {data_width}'h0;  // TODO: connect\n"

                if use_valid_ready and write_enable_signal:
                    variable_latency_write_ports.append({
                        'ext_port_name': mem_name,
                        'enable_signal': write_enable_signal,
                        'num_bytes': num_bytes,
                        'combined_byte_enable': combined_byte_enable or ''
                    })
                elif write_enable_signal:
                    self.comb_logic += f"    assign {mem_name}_write_req_valid = {write_enable_signal};\n"
                    if combined_byte_enable:
                        self.comb_logic += f"    assign {mem_name}_write_req_we = {combined_byte_enable};\n"
                    else:
                        self.comb_logic += f"    assign {mem_name}_write_req_we = {write_enable_signal} ? {num_bytes}'h{(1 << num_bytes) - 1:x} : {num_bytes}'h0;\n"
                else:
                    self.comb_logic += f"    assign {mem_name}_write_req_valid = 1'b0;  // TODO: connect\n"
                    self.comb_logic += f"    assign {mem_name}_write_req_we = {num_bytes}'h0;\n"

        # Generate FSM logic for variable latency ports
        if variable_latency_read_ports or variable_latency_write_ports:
            self._generate_variable_latency_fsm(
                variable_latency_read_ports,
                variable_latency_write_ports,
                stall_signals
            )

        # Generate combined stall signal for pipeline stall controller integration
        if stall_signals:
            combined_stall = ' || '.join(stall_signals)
            self.comb_logic += f"\n    // Combined memory stall for pipeline control\n"
            self.comb_logic += f"    wire mem_ext_stall = {combined_stall};\n"
            print(f"  Generated memory stall signal: mem_ext_stall")

            # Store stall signal name for sequential logic gating
            self._mem_ext_stall_signal = 'mem_ext_stall'

            # Also track the Memory stage stall control signal for proper Writeback gating
            # When dcache completes but icache is busy, Writeback should still update
            # This optimization ONLY applies when there are caches - without caches,
            # all memory stalls should block the entire pipeline
            has_cache = any(
                node.data.get('type') in ['read_only_cache', 'read_write_cache']
                for node in self.graph.nodes.values()
            )
            if self.externalized_memories and has_cache:
                # Use the first externalized memory name for the stall control signal
                mem_name = sorted(self.externalized_memories)[0]
                mem_stage_stall = f"PIPE_Memory_{mem_name}_stall_ctrl"
                self._memory_stage_stall_ctrl = mem_stage_stall
                print(f"  Memory stage stall control: {mem_stage_stall} (cache present)")

            # Generate complete/idle signals for externalized memories using valid-ready handshake
            ext_complete_signals = getattr(self, '_externalized_memory_complete_signals', {})
            for mem_name, signals in ext_complete_signals.items():
                complete_name = signals.get('complete_name')
                idle_name = signals.get('idle_name')

                if complete_name:
                    # Complete = all responses received (not stalling on memory)
                    self.comb_logic += f"\n    // Externalized memory {mem_name}: complete when all responses received\n"
                    self.comb_logic += f"    assign {complete_name} = !mem_ext_stall;\n"
                    print(f"  Generated {complete_name} = !mem_ext_stall")

                if idle_name:
                    # Idle = no operation currently in progress (no grant registers set)
                    # This allows umem_start to happen when memory is ready for a new request
                    # Check for arbiter grant registers stored by multi_cycle_operations.py
                    mem_node = self.graph.nodes.get(mem_name)
                    grant_regs = mem_node.data.get('arbiter_grant_regs', []) if mem_node else []
                    if grant_regs:
                        grant_expr = ' || '.join(grant_regs)
                        self.comb_logic += f"    assign {idle_name} = !({grant_expr});\n"
                        print(f"  Generated {idle_name} = !({grant_expr})")
                    else:
                        # Fallback to pending registers or mem_ext_stall
                        pending_regs = getattr(self, '_pending_registers', [])
                        if pending_regs:
                            pending_expr = ' || '.join(pending_regs)
                            self.comb_logic += f"    assign {idle_name} = !({pending_expr});\n"
                            print(f"  Generated {idle_name} = !({pending_expr})")
                        else:
                            self.comb_logic += f"    assign {idle_name} = !mem_ext_stall;\n"
                            print(f"  Generated {idle_name} = !mem_ext_stall")

    def _find_memory_signal(self, mem_name: str, port_type: str, signal_type: str) -> Optional[str]:
        """Find an existing memory signal in the graph.

        Args:
            mem_name: Name of the memory (e.g., 'umem', 'dmem')
            port_type: 'read' or 'write'
            signal_type: 'addr', 'data', or 'enable'

        Returns:
            The Verilog signal name if found, None otherwise
        """
        # Patterns to search for based on graph_merger naming conventions
        patterns = []
        if port_type == 'read':
            if signal_type == 'addr':
                patterns = [
                    f"{mem_name}_shared_rd_addr",
                    f"{mem_name}_rd_addr",
                    f"{mem_name}_read_addr",
                    f"shared_{mem_name}_rd_addr"
                ]
            elif signal_type == 'enable':
                patterns = [
                    f"{mem_name}_shared_rd_enable",
                    f"{mem_name}_rd_enable",
                    f"{mem_name}_read_enable",
                    f"shared_{mem_name}_rd_enable"
                ]
            elif signal_type == 'data':
                patterns = [
                    f"{mem_name}_shared_rd",
                    f"{mem_name}_rd",
                    f"{mem_name}_read_data"
                ]
        else:  # write
            if signal_type == 'addr':
                patterns = [
                    f"{mem_name}_shared_wr_addr",
                    f"{mem_name}_wr_addr",
                    f"{mem_name}_write_addr",
                    f"shared_{mem_name}_wr_addr"
                ]
            elif signal_type == 'data':
                patterns = [
                    f"{mem_name}_shared_wr_data",
                    f"{mem_name}_wr_data",
                    f"{mem_name}_write_data",
                    f"shared_{mem_name}_wr_data"
                ]
            elif signal_type == 'enable':
                patterns = [
                    f"{mem_name}_shared_wr_enable",
                    f"{mem_name}_wr_enable",
                    f"{mem_name}_write_enable",
                    f"shared_{mem_name}_wr_enable",
                    f"{mem_name}_shared_wr_combined_enable"
                ]

        # Check if any pattern exists as a declared signal
        for pattern in patterns:
            sanitized = self._sanitize_identifier(pattern)
            if sanitized in self.declared_names or pattern in self.node_id_to_name:
                return sanitized

        # Check graph nodes for matching patterns
        for node_id in self.graph.nodes:
            for pattern in patterns:
                if pattern in node_id:
                    return self.node_id_to_name.get(node_id, self._sanitize_identifier(node_id))

        return None

    def _generate_variable_latency_fsm(self, read_ports: list, write_ports: list, stall_signals: list):
        """Generate FSM logic for variable latency memory ports.

        For each port with variable latency, generates:
        - A pending request register to track outstanding requests
        - req_valid signal that stays high while request is pending
        - Updates stall_signals list with per-port stall conditions

        Args:
            read_ports: List of {'ext_port_name', 'enable_signal', 'is_ifetch'}
            write_ports: List of {'ext_port_name', 'enable_signal', 'num_bytes', 'combined_byte_enable'}
            stall_signals: List to append stall conditions to (modified in place)
        """
        if not read_ports and not write_ports:
            return

        self.comb_logic += "\n    // === Variable Latency Memory FSM ===\n"

        # Check if this is a pipelined design (has pipeline registers)
        is_pipelined = any(
            node.data.get('type') == 'pipeline_register'
            for node in self.graph.nodes.values()
        )

        # Track all pending registers for idle signal generation
        pending_registers = []

        # Generate FSM for read ports
        for port in read_ports:
            ext_port_name = port['ext_port_name']
            enable_signal = port['enable_signal']
            is_ifetch = port.get('is_ifetch', False)

            pending_reg = f"{ext_port_name}_req_pending"
            resp_ready = f"{ext_port_name}_read_resp_ready"
            req_valid = f"{ext_port_name}_read_req_valid"
            req_addr = f"{ext_port_name}_read_req_addr"

            # For pipelined designs, prefer the valid-gated enable signal
            valid_gated_signal = f"{enable_signal}_valid_gated"
            if valid_gated_signal in self.declared_names:
                fsm_enable_signal = valid_gated_signal
            else:
                fsm_enable_signal = enable_signal

            # Declare the pending register
            self.declarations += f"    reg {pending_reg};\n"
            pending_registers.append(pending_reg)

            # Generate FSM logic
            self.comb_logic += f"\n    // {ext_port_name} read port FSM\n"

            if is_ifetch:
                # Instruction fetch: always requesting (pending when waiting for response)
                # For instruction fetch, we send a new request every cycle unless stalled
                self.comb_logic += f"    // Instruction fetch port - always active\n"
                self.comb_logic += f"    assign {req_valid} = 1'b1;\n"

                if not is_pipelined:
                    # Single-cycle design: need to detect when PC changes and stall
                    # until fresh instruction data arrives for the new address
                    last_addr_reg = f"{ext_port_name}_last_addr"
                    addr_changed = f"{ext_port_name}_addr_changed"

                    # Declare the last address register and address changed wire
                    # Note: We add to self.declarations (string) rather than self.wire_declarations
                    # because wire_declarations is processed earlier in the generation order
                    self.declarations += f"    reg [31:0] {last_addr_reg};\n"
                    self.declarations += f"    wire {addr_changed};\n"
                    self.declared_names.add(addr_changed)

                    # Address changed when current request address differs from last
                    self.comb_logic += f"    // Detect PC address change for variable latency stall\n"
                    self.comb_logic += f"    assign {addr_changed} = ({req_addr} != {last_addr_reg});\n"

                    # Generate sequential logic for last address tracking
                    self.seq_logic += f"\n    // {ext_port_name} last address tracking for single-cycle design\n"
                    self.seq_logic += f"    always @(posedge clk) begin\n"
                    self.seq_logic += f"        if (reset) begin\n"
                    self.seq_logic += f"            {last_addr_reg} <= 32'hFFFFFFFF;  // Invalid initial address\n"
                    self.seq_logic += f"        end else begin\n"
                    self.seq_logic += f"            {last_addr_reg} <= {req_addr};\n"
                    self.seq_logic += f"        end\n"
                    self.seq_logic += f"    end\n"

                    # Stall when waiting for response OR when address changed (need fresh data)
                    stall_signals.append(f"(!{resp_ready} || {addr_changed})")
                    print(f"    Generated PC change detection for single-cycle ifetch ({ext_port_name})")
                else:
                    # Pipelined design: stall only when waiting for response
                    stall_signals.append(f"(!{resp_ready})")
            else:
                # Data access: only request when enable is active or pending
                self.comb_logic += f"    assign {req_valid} = {fsm_enable_signal} || {pending_reg};\n"
                # Stall while request is in flight (from first cycle until response)
                stall_signals.append(f"({req_valid} && !{resp_ready})")

            # Generate sequential logic for pending register
            self.seq_logic += f"\n    // {ext_port_name} request pending FSM\n"
            self.seq_logic += f"    always @(posedge clk) begin\n"
            self.seq_logic += f"        if (reset) begin\n"
            self.seq_logic += f"            {pending_reg} <= 1'b0;\n"
            self.seq_logic += f"        end else begin\n"

            if is_ifetch:
                # Instruction fetch: pending when we sent request but didn't get response
                self.seq_logic += f"            // Pending = sent request, waiting for response\n"
                self.seq_logic += f"            {pending_reg} <= !{resp_ready};\n"
            else:
                # Data access: pending until response received
                # Only set pending if response is not immediate (for multi-cycle memory)
                self.seq_logic += f"            if ({fsm_enable_signal} && !{pending_reg} && !{resp_ready}) begin\n"
                self.seq_logic += f"                // Start new request, memory not immediately ready\n"
                self.seq_logic += f"                {pending_reg} <= 1'b1;\n"
                self.seq_logic += f"            end else if ({pending_reg} && {resp_ready}) begin\n"
                self.seq_logic += f"                // Response received\n"
                self.seq_logic += f"                {pending_reg} <= 1'b0;\n"
                self.seq_logic += f"            end\n"

            self.seq_logic += f"        end\n"
            self.seq_logic += f"    end\n"

            print(f"    Generated FSM for {ext_port_name} read port (using {fsm_enable_signal})")

        # Generate FSM for write ports
        for port in write_ports:
            ext_port_name = port['ext_port_name']
            enable_signal = port['enable_signal']
            num_bytes = port.get('num_bytes', 4)
            combined_byte_enable = port.get('combined_byte_enable', '')

            pending_reg = f"{ext_port_name}_write_pending"
            resp_ready = f"{ext_port_name}_write_resp_ready"
            req_valid = f"{ext_port_name}_write_req_valid"
            req_we = f"{ext_port_name}_write_req_we"

            # For pipelined designs, prefer the valid-gated enable signal
            # which includes the pipeline stage validity check
            valid_gated_signal = f"{enable_signal}_valid_gated"
            if valid_gated_signal in self.declared_names:
                fsm_enable_signal = valid_gated_signal
            else:
                fsm_enable_signal = enable_signal

            # Declare the pending register
            self.declarations += f"    reg {pending_reg};\n"
            pending_registers.append(pending_reg)

            # Generate FSM logic
            self.comb_logic += f"\n    // {ext_port_name} write port FSM\n"
            self.comb_logic += f"    assign {req_valid} = {fsm_enable_signal} || {pending_reg};\n"

            # Byte enable: use combined if available, otherwise all bytes when enabled
            if combined_byte_enable:
                self.comb_logic += f"    assign {req_we} = {req_valid} ? {combined_byte_enable} : {num_bytes}'h0;\n"
            else:
                all_bytes = f"{num_bytes}'h{(1 << num_bytes) - 1:x}"
                self.comb_logic += f"    assign {req_we} = {req_valid} ? {all_bytes} : {num_bytes}'h0;\n"

            # Stall when we have a request but no response
            stall_signals.append(f"({req_valid} && !{resp_ready})")

            # Generate sequential logic for pending register
            # Only set pending if request is not immediately acknowledged
            self.seq_logic += f"\n    // {ext_port_name} write pending FSM\n"
            self.seq_logic += f"    always @(posedge clk) begin\n"
            self.seq_logic += f"        if (reset) begin\n"
            self.seq_logic += f"            {pending_reg} <= 1'b0;\n"
            self.seq_logic += f"        end else begin\n"
            self.seq_logic += f"            if ({fsm_enable_signal} && !{pending_reg} && !{resp_ready}) begin\n"
            self.seq_logic += f"                // Start new write, memory not immediately ready\n"
            self.seq_logic += f"                {pending_reg} <= 1'b1;\n"
            self.seq_logic += f"            end else if ({pending_reg} && {resp_ready}) begin\n"
            self.seq_logic += f"                // Write acknowledged\n"
            self.seq_logic += f"                {pending_reg} <= 1'b0;\n"
            self.seq_logic += f"            end\n"
            self.seq_logic += f"        end\n"
            self.seq_logic += f"    end\n"

            print(f"    Generated FSM for {ext_port_name} write port (using {fsm_enable_signal})")

        # Store pending registers for idle signal generation
        self._pending_registers = pending_registers

    def generate_memory_wrapper(self, mem_name: str) -> str:
        """Generate a companion memory module for externalized memory.

        This module implements the valid-ready handshake protocol and can be
        used at the SoC level for simulation or as a template for real memory.
        """
        if mem_name not in self.externalized_memories:
            return ""

        mem_info = self.memory_declarations.get(mem_name, {})
        data_width = mem_info.get('bit_width', 32)
        array_depth = mem_info.get('array_depth', 67108864)
        addr_width = mem_info.get('addr_width', 24)

        wrapper = f"""// Auto-generated memory wrapper for {mem_name}
// Implements valid-ready handshake protocol for AXI-Lite compatibility
// Use this at SoC level to connect to the CPU's externalized memory ports

module {mem_name}_memory #(
    parameter DATA_WIDTH = {data_width},
    parameter ADDR_WIDTH = {addr_width},
    parameter DEPTH = {array_depth},
    parameter LATENCY = 1  // Memory read latency in cycles
)(
    input wire clk,
    input wire reset,
    // Read port (valid-ready handshake)
    input wire [ADDR_WIDTH-1:0] read_req_addr,
    input wire read_req_valid,
    output reg [DATA_WIDTH-1:0] read_resp_data,
    output reg read_resp_ready,
    // Write port (valid-ready handshake)
    input wire [ADDR_WIDTH-1:0] write_req_addr,
    input wire [DATA_WIDTH-1:0] write_req_data,
    input wire [{max(1, data_width // 8) - 1}:0] write_req_we,
    input wire write_req_valid,
    output reg write_resp_ready
);

    // Memory array
    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    // Read pipeline for latency modeling
    reg [LATENCY-1:0] read_pending;
    reg [DATA_WIDTH-1:0] read_data_pipeline [0:LATENCY-1];

    // Memory initialization
    initial begin
        integer i;
        for (i = 0; i < DEPTH; i = i + 1) begin
            mem[i] = 0;
        end
        $readmemh("{mem_name}.hex", mem);
    end

    // Read logic with configurable latency
    always @(posedge clk) begin
        if (reset) begin
            read_pending <= 0;
            read_resp_ready <= 0;
        end else begin
            // Shift read pipeline
            read_pending <= {{read_pending[LATENCY-2:0], read_req_valid}};

            // Combinational read from memory (latency added by pipeline)
            if (read_req_valid) begin
                read_data_pipeline[0] <= mem[read_req_addr >> 2];  // Word-aligned
            end

            // Pipeline the data
            for (integer i = 1; i < LATENCY; i = i + 1) begin
                read_data_pipeline[i] <= read_data_pipeline[i-1];
            end

            // Output when pipeline completes
            read_resp_ready <= read_pending[LATENCY-1];
            read_resp_data <= read_data_pipeline[LATENCY-1];
        end
    end

    // Write logic (single cycle)
    always @(posedge clk) begin
        if (reset) begin
            write_resp_ready <= 0;
        end else begin
            write_resp_ready <= write_req_valid;  // Acknowledge writes immediately
            if (write_req_valid) begin
                // Byte-enable write
                for (integer b = 0; b < DATA_WIDTH/8; b = b + 1) begin
                    if (write_req_we[b]) begin
                        mem[write_req_addr >> 2][b*8 +: 8] <= write_req_data[b*8 +: 8];
                    end
                end
            end
        end
    end

endmodule
"""
        return wrapper

    def _assemble_module(self) -> str:
        """Assemble the complete Verilog module."""
        verilog = ""

        # Add default MEM_BASE definition if not defined via -D flag
        # This allows the generated Verilog to work with simulators that
        # pass -DMEM_BASE=0x80000000 while also having a safe default
        verilog += "`ifndef MEM_BASE\n"
        verilog += "`define MEM_BASE 32'h00000000\n"
        verilog += "`endif\n\n"

        # Add FP module definitions if needed (these go before the main module)
        if self.fp_modules_needed:
            if 'cvfpu' in self.fp_modules_needed:
                # cvfpu_simple is in vendor/cvfpu_wrapper.sv and gets included
                # by the build system (verilator). Add a comment to indicate this.
                verilog += "// cvfpu_simple FPU module is used - include vendor/cvfpu_wrapper.sv\n\n"
            else:
                raise RuntimeError(
                    f"Floating-point modules requested ({self.fp_modules_needed}) "
                    "but cvfpu is not available. Ensure vendor/cvfpu/ submodule is "
                    "initialized: git submodule update --init vendor/cvfpu"
                )

        # Add generated module definitions before the main processor module
        for module_def in self.module_definitions:
            verilog += module_def + "\n\n"

        verilog += self.extra_modules
        verilog += self.module_header
        verilog += self.declarations
        verilog += self.memory_init
        verilog += self.comb_logic + "\n"

        # Add module instantiations in the combinational logic section
        for module_inst in self.module_instantiations:
            verilog += "    " + module_inst + "\n"

        # Add combined cvfpu status logic if we have cvfpu instances
        if hasattr(self, 'cvfpu_status_wires') and self.cvfpu_status_wires:
            verilog += "\n    // FPU exception flag handling\n"
            verilog += "    // Detect when FP operations that can generate exceptions are active\n"

            # Collect unique enable signals from the stored instruction enables
            # cvfpu_status_wires now contains (status_wire, verilog_name, instr_enable)
            active_enables = set()
            for entry in self.cvfpu_status_wires:
                if len(entry) >= 3:
                    status_wire, verilog_name, instr_enable = entry
                else:
                    # Backward compatibility for 2-element tuples
                    status_wire, verilog_name = entry
                    instr_enable = None
                if instr_enable and instr_enable in self.declared_names:
                    active_enables.add(instr_enable)

            # Generate fp_op_active with only the enables that actually exist
            if active_enables:
                sorted_enables = sorted(active_enables)
                verilog += f"    wire fp_op_active = {sorted_enables[0]}"
                for enable in sorted_enables[1:]:
                    verilog += f" ||\n                        {enable}"
                verilog += ";\n"
            else:
                verilog += "    wire fp_op_active = 1'b0;\n"
            verilog += "\n"
            verilog += "    // Gate each FPU's status with its enable signal to get correct flags\n"
            verilog += "    // (All FPUs compute simultaneously, but we only want status from the active one)\n"
            gated_terms = []
            for entry in self.cvfpu_status_wires:
                if len(entry) >= 3:
                    status_wire, verilog_name, instr_enable = entry
                else:
                    status_wire, verilog_name = entry
                    instr_enable = None
                # Use the stored instruction enable, or fallback to 1'b1
                enable = instr_enable if (instr_enable and instr_enable in self.declared_names) else "1'b1"
                gated_terms.append(f"({enable} ? {status_wire} : 5'b0)")
            verilog += f"    wire [4:0] cvfpu_combined_status = {' | '.join(gated_terms)};\n"
            verilog += "\n"
            verilog += "    // Registered accumulator for sticky exception flags\n"
            verilog += "    reg [4:0] fpu_exception_accum;\n"
            verilog += "\n"
            verilog += "    // New flags to accumulate (only when FP op is active)\n"
            verilog += "    wire [4:0] new_fpu_flags = fp_op_active ? cvfpu_combined_status : 5'b0;\n"
            verilog += "\n"
            verilog += "    // Detect fflags/fcsr write operations (clears flags)\n"
            # Only generate CSR-based fflags write detection if CSR instructions exist (RISC-V)
            csr_enables = ['csrrw_enable', 'csrrwi_enable', 'csrrc_enable', 'csrrci_enable']
            has_csr = any(e in self.declared_names for e in csr_enables)
            if has_csr:
                verilog += "    wire fflags_write = (csrrw_enable && (instr[31:20] == 12'h001)) ||\n"
                verilog += "                        (csrrwi_enable && (instr[31:20] == 12'h001)) ||\n"
                verilog += "                        (csrrc_enable && (instr[31:20] == 12'h001)) ||\n"
                verilog += "                        (csrrci_enable && (instr[31:20] == 12'h001)) ||\n"
                verilog += "                        (csrrw_enable && (instr[31:20] == 12'h003)) ||\n"
                verilog += "                        (csrrwi_enable && (instr[31:20] == 12'h003));\n"
            else:
                # For non-RISC-V ISAs (MIPS32, OpenPOWER), flags are just accumulated
                verilog += "    wire fflags_write = 1'b0;  // No CSR instructions in this ISA\n"
            verilog += "\n"
            verilog += "    // Accumulated flags value to use for fcsr\n"
            verilog += "    wire [4:0] fflags_accumulated = fpu_exception_accum | new_fpu_flags;\n"
            verilog += "\n"

            # Determine which FP status register exists (ISA-agnostic)
            # RISC-V/MIPS32: fcsr, OpenPOWER: fpscr
            if 'fpscr_rd' in self.declared_names:
                fp_status_wr = 'fpscr_wr'
                fp_status_rd = 'fpscr_rd'
            elif 'fcsr_rd' in self.declared_names:
                fp_status_wr = 'fcsr_wr'
                fp_status_rd = 'fcsr_rd'
            else:
                # No FP status register - skip the update logic
                fp_status_wr = None
                fp_status_rd = None

            if fp_status_wr:
                verilog += f"    // Updated {fp_status_rd} that uses accumulated fflags\n"
                verilog += f"    wire [31:0] {fp_status_wr}_with_fpu = fflags_write ? {fp_status_wr} : {{{fp_status_wr}[31:5], fflags_accumulated}};\n"

        verilog += self.seq_logic

        # If we added cvfpu status logic, patch the status register assignment and add accumulator update
        if hasattr(self, 'cvfpu_status_wires') and self.cvfpu_status_wires:
            # Determine which FP status register exists
            if 'fpscr_rd' in self.declared_names:
                fp_status_wr = 'fpscr_wr'
                fp_status_rd = 'fpscr_rd'
            elif 'fcsr_rd' in self.declared_names:
                fp_status_wr = 'fcsr_wr'
                fp_status_rd = 'fcsr_rd'
            else:
                fp_status_wr = None
                fp_status_rd = None

            if fp_status_rd:
                # Replace "XXX_rd <= XXX_wr" with "XXX_rd <= XXX_wr_with_fpu"
                verilog = verilog.replace(f"{fp_status_rd} <= {fp_status_wr};", f"{fp_status_rd} <= {fp_status_wr}_with_fpu;")

                # Add the fpu_exception_accum register update logic
                verilog += f"""
    // FPU exception flags accumulator update
    always @(posedge clk) begin
        if (reset) begin
            fpu_exception_accum <= 5'b0;
        end else if (fflags_write) begin
            // When software writes to fflags/{fp_status_rd}, use the written value
            fpu_exception_accum <= {fp_status_wr}[4:0];
        end else if (fp_op_active) begin
            // Accumulate new flags when FP op is active
            fpu_exception_accum <= fflags_accumulated;
        end
        // Otherwise, keep the current value (sticky)
    end

"""
            else:
                # No FP status register - just add basic accumulator
                verilog += """
    // FPU exception flags accumulator update
    always @(posedge clk) begin
        if (reset) begin
            fpu_exception_accum <= 5'b0;
        end else if (fp_op_active) begin
            fpu_exception_accum <= fflags_accumulated;
        end
    end

"""

        verilog += "endmodule\n"

        return verilog


def generate_verilog(graph: ResourceGraph, module_name: str = "processor") -> str:
    """Generate Verilog code from a ResourceGraph."""
    generator = VerilogGenerator(graph, module_name)
    return generator.generate()


def generate_verilog_with_testbench(graph: ResourceGraph,
                                    module_name: str = "processor",
                                    output_dir: str = "examples/verilog",
                                    testbench_config: dict = None) -> dict:
    """
    Generate Verilog RTL and testbench with FuseSoC integration.

    Args:
        graph: ResourceGraph to generate from
        module_name: Name of the processor module
        output_dir: Directory to write output files
        testbench_config: Optional testbench configuration dict

    Returns:
        Dictionary with paths to generated files
    """
    from pathlib import Path
    from backends.verilog.verilog_testbench_generator import (
        generate_testbench_files,
        TestbenchConfig
    )

    # Generate RTL
    verilog_code = generate_verilog(graph, module_name)

    # Write RTL file
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    rtl_file = output_path / f"{module_name}.v"
    rtl_file.write_text(verilog_code)

    # Create testbench config
    if testbench_config is None:
        testbench_config = {}

    # Don't pass module_name if it's already in testbench_config
    if 'module_name' not in testbench_config:
        testbench_config['module_name'] = module_name

    config = TestbenchConfig(**testbench_config)

    # Generate testbench and FuseSoC files
    tb_files = generate_testbench_files(
        module_name=module_name,
        rtl_file=str(rtl_file),
        output_dir=output_path,
        config=config
    )

    return {
        'rtl': rtl_file,
        'testbench': tb_files['testbench'],
        'core': tb_files['core']
    }