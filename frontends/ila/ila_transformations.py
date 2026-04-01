"""
ILA Resource Graph Transformations

Transforms ILA-specific patterns into more structural representations
that are easier to process for Verilog generation and merging.
"""

from core.resource_graph import ResourceGraph, Node, Edge
from typing import Dict, List, Optional, Tuple


def transform_memory_ternaries(graph: ResourceGraph):
    """
    Transform ILA memory ternary pattern into structural writes.
    
    ILA uses functional semantics for memory updates:
        array_next = cond ? array : memory_write(array, addr, data)
    
    This transformation converts to conditional array writes:
        if (write_enable) array[addr] = data
    where write_enable = !cond (when true branch is unchanged array)
    
    This makes the pattern compatible with ISA-style processing and
    Verilog generation without special cases.
    """
    print("Transforming ILA memory ternary patterns...")
    
    # Find all ternary nodes
    ternaries_to_transform = []
    
    for node_id, node in graph.nodes.items():
        if node.data.get('type') not in ['ternary_op', 'conditional']:
            continue
        
        # Check if this ternary involves memory operations
        has_memory_write = False
        memory_write_node = None
        memory_operand_edge = None
        array_operand_edge = None
        cond_edge = None
        
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type')
            source = edge.source
            
            if edge_type == 'ternary_condition':
                cond_edge = edge
            elif edge_type in ['ternary_true', 'ternary_false']:
                if source.data.get('type') == 'memory_write':
                    has_memory_write = True
                    memory_write_node = source
                    memory_operand_edge = edge
                elif source.data.get('is_memory') or \
                     (source.data.get('type') == 'isa_state' and 
                      source.data.get('array_depth') is not None):
                    array_operand_edge = edge
        
        if has_memory_write and array_operand_edge and cond_edge:
            ternaries_to_transform.append({
                'ternary': node,
                'memory_write': memory_write_node,
                'memory_edge': memory_operand_edge,
                'array_edge': array_operand_edge,
                'cond_edge': cond_edge
            })
    
    print(f"  Found {len(ternaries_to_transform)} memory ternaries to transform")
    
    # Transform each ternary
    for info in ternaries_to_transform:
        _transform_single_memory_ternary(graph, info)
    
    print(f"  Transformation complete: {len(ternaries_to_transform)} patterns converted")


def _transform_single_memory_ternary(graph: ResourceGraph, info: Dict):
    """Transform a single memory ternary pattern."""
    ternary_node = info['ternary']
    memory_write_node = info['memory_write']
    memory_edge = info['memory_edge']
    array_edge = info['array_edge']
    cond_edge = info['cond_edge']
    
    # Extract memory_write components
    # ILA memory_write: position 0 = array, position 1 = address, position 2 = data
    write_array = None
    write_addr = None
    write_data = None
    
    for edge in memory_write_node.incoming_edges:
        pos = edge.data.get('position')
        if pos == 0:
            write_array = edge.source
        elif pos == 1:
            write_addr = edge.source
        elif pos == 2:
            write_data = edge.source
    
    if not (write_addr and write_data):
        print(f"    Warning: Couldn't extract write address/data from {memory_write_node.id}")
        return
    
    # Determine write enable condition
    # If true branch is unchanged array, write when condition is FALSE
    # If false branch is unchanged array, write when condition is TRUE
    write_when_true = (memory_edge.data.get('type') == 'ternary_true')
    
    cond_source = cond_edge.source
    
    # Create write enable signal
    if write_when_true:
        # Write when condition is true - use condition directly
        write_enable_node = cond_source
    else:
        # Write when condition is false - need to invert
        # Create a logical NOT node
        enable_data = {
            "type": "operation",
            "operator": "==",
            "expression": {
                "type": "binary_op",
                "operator": "=="
            }
        }
        enable_node = Node(f"{ternary_node.id}_write_enable", enable_data, from_isa_spec=False)
        graph.add_node(enable_node)
        
        # Connect: enable = (cond == 0)
        edge1 = Edge(cond_source, enable_node, data={'type': 'operand', 'position': 0})
        graph.add_edge(edge1)
        
        # Create constant 0
        zero_data = {"type": "literal", "value": 0, "width": 1}
        zero_node = Node(f"{ternary_node.id}_zero", zero_data, from_isa_spec=False)
        graph.add_node(zero_node)
        
        edge2 = Edge(zero_node, enable_node, data={'type': 'operand', 'position': 1})
        graph.add_edge(edge2)
        
        write_enable_node = enable_node
    
    # Find the target (what the ternary was assigned to)
    target_node = None
    assignment_edge = None
    for edge in ternary_node.outgoing_edges:
        if edge.data.get('type') == 'assignment':
            target_node = edge.target
            assignment_edge = edge
            break
    
    if not target_node:
        print(f"    Warning: Ternary {ternary_node.id} has no assignment target")
        return
    
    # Create array_access write node
    # This represents array[addr] as the write target
    write_access_data = {
        "type": "array_access",
        "is_write": True,
        "from_ila_transform": True
    }
    write_access_node = Node(f"{ternary_node.id}_write_access", write_access_data, from_isa_spec=False)
    graph.add_node(write_access_node)
    
    # Get the base array (from array_edge)
    base_array = array_edge.source
    
    # Connect: base_array -> write_access (array being indexed)
    edge = Edge(base_array, write_access_node, data={'type': 'operand', 'position': 0})
    graph.add_edge(edge)
    
    # Connect: write_addr -> write_access (index)
    edge = Edge(write_addr, write_access_node, data={'type': 'operand', 'position': 1})
    graph.add_edge(edge)
    
    # Connect: write_data -> write_access (value to write)
    edge = Edge(write_data, write_access_node, data={'type': 'write_data'})
    graph.add_edge(edge)
    
    # Connect: write_enable -> write_access (conditional)
    edge = Edge(write_enable_node, write_access_node, data={'type': 'write_enable'})
    graph.add_edge(edge)
    
    # Redirect the assignment from ternary to write_access
    graph.remove_edge(assignment_edge)
    new_assignment = Edge(write_access_node, target_node, data={'type': 'assignment'})
    graph.add_edge(new_assignment)

    # Remove all edges to/from memory_write node
    edges_to_remove = []
    for edge in memory_write_node.incoming_edges:
        edges_to_remove.append(edge)
    for edge in memory_write_node.outgoing_edges:
        edges_to_remove.append(edge)
    for edge in edges_to_remove:
        graph.remove_edge(edge)

    # Remove all edges to/from ternary node (except assignment which we already removed)
    edges_to_remove = []
    for edge in ternary_node.incoming_edges:
        edges_to_remove.append(edge)
    for edge in ternary_node.outgoing_edges:
        edges_to_remove.append(edge)
    for edge in edges_to_remove:
        graph.remove_edge(edge)

    # Now remove the nodes (pass node IDs, not Node objects)
    graph.remove_node(memory_write_node.id)
    graph.remove_node(ternary_node.id)

    print(f"    Transformed {ternary_node.id} -> conditional write to {target_node.id}")


def transform_registers_to_regfile(graph: ResourceGraph):
    """
    Transform individual x0-x31 registers into a unified rf (register file) array.

    ILA models from Princeton IMDb represent registers as 32 separate state variables,
    each with a conditional write pattern:
        xN = (rd_field == N) ? result : xN

    This transformation detects this pattern and converts to:
        rf[rd_field] = result (when rd_field != 0)

    This matches the structure created by ISA parsers, allowing proper merging.
    """
    print("Transforming x0-x31 registers to register file array...")

    # Find all x register nodes (x0 through x31)
    x_regs = {}
    for node_id, node in list(graph.nodes.items()):
        if (node.data.get('type') == 'isa_state' and
            node.data.get('name', '').startswith('x')):
            name = node.data['name']
            if len(name) >= 2 and name[1:].isdigit():
                reg_num = int(name[1:])
                if 0 <= reg_num <= 31:
                    x_regs[reg_num] = node

    if len(x_regs) < 32:
        print(f"  Found only {len(x_regs)} x registers, skipping transformation")
        return

    print(f"  Found all 32 x registers, analyzing write pattern...")

    # Analyze the write pattern for x1 (representative)
    # Pattern: x1 = (rd_field == 1) ? result : x1
    x1_node = x_regs[1]
    write_info = _analyze_register_write_pattern(graph, x1_node, 1)

    if not write_info:
        print(f"  Could not detect conditional write pattern, using fallback transformation")
        _fallback_transform_registers(graph, x_regs)
        return

    rd_field_node = write_info['rd_field']
    result_nodes = write_info['result_nodes']  # Map from reg_num to result node

    print(f"  Detected pattern: xN = ({rd_field_node.id} == N) ? result : xN")
    print(f"  Creating variable-indexed write: rf[{rd_field_node.id}] = result")

    # Create unified rf memory node
    rf_data = {
        'type': 'isa_state',
        'name': 'rf',
        'display_name': 'rf',
        'bit_width': 32,
        'array_depth': 5,  # 2^5 = 32 entries
        'is_memory': True
    }
    rf_node = Node('rf', rf_data, is_arch_state=True)
    graph.add_node(rf_node)

    # Transform reads: Replace all x register reads with rf[rd_field] reads
    # Since ILA uses ITE cascades for reads, we keep those but redirect x references to rf
    _transform_register_reads(graph, x_regs, rf_node, rd_field_node)

    # Transform writes: Create single rf[rd_field] = result write
    _transform_register_writes(graph, x_regs, rf_node, rd_field_node, result_nodes)

    print(f"  Transformation complete: Created rf[{rd_field_node.id}] with variable indexing")


def _analyze_register_write_pattern(graph: ResourceGraph, x_node: Node, reg_num: int) -> Optional[Dict]:
    """
    Analyze the write pattern for a register to detect:
        xN = (rd_field == N) ? result : xN

    Returns dict with:
        - rd_field: Node representing the rd field
        - result_nodes: Map from register number to result node
    """
    # Find incoming assignment edge
    for edge in x_node.incoming_edges:
        if edge.data.get('type') == 'assignment':
            source = edge.source

            # Should be a ternary: (condition) ? true_val : false_val
            if source.data.get('type') != 'ternary_op':
                return None

            # Get ternary components
            condition = None
            true_val = None
            false_val = None

            for e in source.incoming_edges:
                pos = e.data.get('position')
                if pos == 0:
                    condition = e.source
                elif pos == 1:
                    true_val = e.source
                elif pos == 2:
                    false_val = e.source

            # false_val should be the original x register (keep old value)
            if false_val != x_node:
                return None

            # Condition should be: rd_field == reg_num
            if not condition or condition.data.get('operator') != '==':
                return None

            # Get operands of ==
            rd_field = None
            literal_val = None
            for e in condition.incoming_edges:
                pos = e.data.get('position')
                src = e.source
                if src.data.get('type') == 'literal':
                    literal_val = src.data.get('value')
                elif src.data.get('type') == 'bit_slice':
                    rd_field = src

            if literal_val != reg_num or not rd_field:
                return None

            # Found the pattern! Now collect result nodes for all registers
            result_nodes = {}
            for rnum, rx_node in graph.nodes.items():
                if rx_node.data.get('type') != 'isa_state':
                    continue
                if not rx_node.data.get('name', '').startswith('x'):
                    continue

                name = rx_node.data.get('name', '')
                if len(name) < 2 or not name[1:].isdigit():
                    continue

                rn = int(name[1:])
                if rn < 0 or rn > 31:
                    continue

                # Find its write ternary and extract the result
                for e in rx_node.incoming_edges:
                    if e.data.get('type') == 'assignment':
                        tern = e.source
                        if tern.data.get('type') == 'ternary_op':
                            # Get true value (position 1)
                            for te in tern.incoming_edges:
                                if te.data.get('position') == 1:
                                    result_nodes[rn] = te.source
                                    break

            return {
                'rd_field': rd_field,
                'result_nodes': result_nodes
            }

    return None


def _transform_register_reads(graph: ResourceGraph, x_regs: Dict, rf_node: Node, rd_field_node: Node):
    """Transform register reads - redirect x references to rf array accesses."""
    print(f"  Transforming reads: Creating rf[constant] read nodes for ITE cascades...")

    # For each x register, create rf[N] read node
    # ILA uses ITE cascades that reference these directly
    for reg_num, x_node in x_regs.items():
        # Create rf[N] read access
        read_data = {'type': 'array_access'}
        read_node = Node(f'rf_{reg_num}_rd', read_data)
        graph.add_node(read_node)

        # Create constant index
        index_data = {'type': 'literal', 'value': reg_num, 'width': 5}
        index_node = Node(f'rf_index_{reg_num}', index_data)
        graph.add_node(index_node)

        # Connect: rf --operand[0]--> read
        e = Edge(rf_node, read_node, data={'type': 'operand', 'position': 0})
        graph.add_edge(e)

        # Connect: index --operand[1]--> read
        e = Edge(index_node, read_node, data={'type': 'operand', 'position': 1})
        graph.add_edge(e)

        # Redirect all outgoing edges from x_node to read_node
        # This includes ternary operands (ILA uses ternary cascades for register selection)
        for edge in list(x_node.outgoing_edges):
            # Create new edge from rf_X_rd to the same target
            new_edge = Edge(read_node, edge.target, data=edge.data.copy())
            graph.add_edge(new_edge)
            graph.remove_edge(edge)


def _transform_register_writes(graph: ResourceGraph, x_regs: Dict, rf_node: Node,
                                rd_field_node: Node, result_nodes: Dict):
    """Transform register writes - create single rf[rd] = result write."""
    print(f"  Transforming writes: Creating single rf[{rd_field_node.id}] write...")

    # All 32 registers should have the same result computation (indexed by rd)
    # Just use x1's result as representative (could verify they're all structurally same)
    if 1 not in result_nodes:
        print(f"    Warning: No result found for x1, using x0")
        result_node = result_nodes.get(0)
    else:
        result_node = result_nodes[1]

    if not result_node:
        print(f"    Error: No result node found!")
        return

    # Create rf[rd] write access node
    write_data = {'type': 'array_access', 'is_write': True}
    write_node = Node(f'rf_rd_wr', write_data, is_arch_state=True)
    graph.add_node(write_node)

    # Connect: rf --operand[0]--> write
    e = Edge(rf_node, write_node, data={'type': 'operand', 'position': 0})
    graph.add_edge(e)

    # Connect: rd_field --operand[1]--> write (variable index!)
    e = Edge(rd_field_node, write_node, data={'type': 'operand', 'position': 1})
    graph.add_edge(e)

    # Connect: result --write_data--> write
    e = Edge(result_node, write_node, data={'type': 'write_data'})
    graph.add_edge(e)

    # Create write enable: rd != 0
    enable_data = {'type': 'operation', 'operator': '!=', 'expression': {'type': 'binary_op', 'operator': '!='}, 'width': 1}
    enable_node = Node(f'rf_wr_enable', enable_data)
    graph.add_node(enable_node)

    # Connect: rd_field --operand[0]--> enable
    e = Edge(rd_field_node, enable_node, data={'type': 'operand', 'position': 0})
    graph.add_edge(e)

    # Create constant 0
    zero_data = {'type': 'literal', 'value': 0, 'width': 5}
    zero_node = Node(f'rf_wr_zero', zero_data)
    graph.add_node(zero_node)

    # Connect: zero --operand[1]--> enable
    e = Edge(zero_node, enable_node, data={'type': 'operand', 'position': 1})
    graph.add_edge(e)

    # Connect: enable --write_enable--> write
    e = Edge(enable_node, write_node, data={'type': 'write_enable'})
    graph.add_edge(e)

    # Remove all x register nodes and their write ternaries
    for reg_num, x_node in x_regs.items():
        # Find and remove the write ternary
        for edge in list(x_node.incoming_edges):
            if edge.data.get('type') == 'assignment':
                ternary_node = edge.source
                # Remove all edges to/from ternary
                for e in list(ternary_node.incoming_edges):
                    graph.remove_edge(e)
                for e in list(ternary_node.outgoing_edges):
                    graph.remove_edge(e)
                graph.remove_node(ternary_node.id)

        # Remove x node
        graph.remove_node(x_node.id)


def _fallback_transform_registers(graph: ResourceGraph, x_regs: Dict):
    """Fallback: Create literal-indexed rf array (old behavior)."""
    print(f"  Using fallback transformation with literal indices...")

    # Create unified rf memory node
    rf_data = {
        'type': 'isa_state',
        'name': 'rf',
        'display_name': 'rf',
        'bit_width': 32,
        'array_depth': 5,
        'is_memory': True
    }
    rf_node = Node('rf', rf_data, is_arch_state=True)
    graph.add_node(rf_node)

    # Create literal-indexed accesses for each register
    for reg_num, x_node in x_regs.items():
        index_data = {'type': 'literal', 'value': reg_num, 'width': 5}
        index_node = Node(f'rf_index_{reg_num}', index_data)
        graph.add_node(index_node)

        # Create read access
        incoming_edges = list(x_node.incoming_edges)
        outgoing_edges = list(x_node.outgoing_edges)

        if outgoing_edges:
            read_data = {'type': 'array_access'}
            read_node = Node(f'rf_{reg_num}_rd', read_data)
            graph.add_node(read_node)

            e = Edge(rf_node, read_node, data={'type': 'operand', 'position': 0})
            graph.add_edge(e)
            e = Edge(index_node, read_node, data={'type': 'operand', 'position': 1})
            graph.add_edge(e)

            for edge in outgoing_edges:
                new_edge = Edge(read_node, edge.target, data=edge.data.copy())
                graph.add_edge(new_edge)
                graph.remove_edge(edge)

        # Create write access
        for edge in incoming_edges:
            if edge.data.get('type') == 'assignment':
                write_data = {'type': 'array_access', 'is_write': True}
                write_node = Node(f'rf_{reg_num}_wr', write_data)
                graph.add_node(write_node)

                e = Edge(rf_node, write_node, data={'type': 'operand', 'position': 0})
                graph.add_edge(e)
                e = Edge(index_node, write_node, data={'type': 'operand', 'position': 1})
                graph.add_edge(e)
                e = Edge(edge.source, write_node, data={'type': 'write_data'})
                graph.add_edge(e)

                enable_data = {'type': 'literal', 'value': 1, 'width': 1}
                enable_node = Node(f'rf_{reg_num}_wr_enable', enable_data)
                graph.add_node(enable_node)
                e = Edge(enable_node, write_node, data={'type': 'write_enable'})
                graph.add_edge(e)

                graph.remove_edge(edge)

        graph.remove_node(x_node.id)

def replace_register_read_cascades(graph: ResourceGraph):
    """
    Replace ternary cascades for register reads with variable-indexed array accesses.

    Pattern: (rs1==31) ? rf_31_rd : (rs1==30) ? rf_30_rd : ... rf_0_rd
    Replace with: rf[rs1]

    This makes ILA register reads match ISA structure.
    """
    print("Replacing register read ternary cascades with variable-indexed reads...")

    # Find rf node
    rf_node = None
    for node in graph.nodes.values():
        if node.data.get('name') == 'rf' and node.data.get('type') == 'isa_state':
            rf_node = node
            break

    if not rf_node:
        print("  No rf node found, skipping cascade replacement")
        return

    # Build a map of index_field -> rf[index_field]_rd node
    # We'll create these as we identify cascades
    index_to_rf_read = {}

    # Find all ternary nodes that are part of register read cascades
    ternaries_to_replace = []

    for node_id, node in list(graph.nodes.items()):
        if node.data.get('type') != 'ternary_op':
            continue

        # Check if this ternary is part of a register read cascade
        cascade_info = _analyze_register_read_cascade(graph, node)
        if cascade_info and cascade_info['index_node']:
            index_field = cascade_info['index_node'].id

            # Create rf[index]_rd node if it doesn't exist yet
            if index_field not in index_to_rf_read:
                # Create rf[index] read node
                read_data = {'type': 'array_access'}
                read_node = Node(f'rf[{index_field}]_rd', read_data)
                graph.add_node(read_node)

                # Connect rf -> read
                e1 = Edge(rf_node, read_node, data={'type': 'operand', 'position': 0})
                graph.add_edge(e1)

                # Connect index -> read
                index_node = cascade_info['index_node']
                e2 = Edge(index_node, read_node, data={'type': 'operand', 'position': 1})
                graph.add_edge(e2)

                index_to_rf_read[index_field] = read_node
                print(f"  Created rf[{index_field}]_rd")

            ternaries_to_replace.append({
                'ternary_node': node,
                'index_field': index_field,
                'rf_read_node': index_to_rf_read[index_field]
            })

    print(f"  Found {len(ternaries_to_replace)} ternary cascades to replace")

    # Build a set of all ternary IDs that are being replaced
    ternary_ids_to_replace = {info['ternary_node'].id for info in ternaries_to_replace}

    # Replace each ternary with the appropriate rf[index]_rd
    for info in ternaries_to_replace:
        ternary_node = info['ternary_node']
        rf_read_node = info['rf_read_node']

        # Redirect all outgoing edges from ternary to rf[index]_rd
        # BUT skip edges that point to other ternaries in the cascade (they will be removed anyway)
        for edge in list(ternary_node.outgoing_edges):
            target_id = [k for k, v in graph.nodes.items() if v == edge.target][0]

            # Skip if target is another ternary being replaced
            if target_id in ternary_ids_to_replace:
                graph.remove_edge(edge.id)
                continue

            # Create new edge from rf_read to target
            new_edge = Edge(rf_read_node, edge.target, data=edge.data.copy())
            graph.add_edge(new_edge)
            graph.remove_edge(edge.id)

    # Clean up orphaned ternary nodes (nodes with no outgoing edges)
    removed_count = 0
    for node_id, node in list(graph.nodes.items()):
        if node.data.get('type') == 'ternary_op':
            if len(list(node.outgoing_edges)) == 0:
                # This ternary has no uses, remove it
                for edge in list(node.incoming_edges):
                    graph.remove_edge(edge.id)
                graph.remove_node(node_id)
                removed_count += 1

    print(f"  Removed {removed_count} orphaned ternary nodes")
    print(f"  Replaced {len(ternaries_to_replace)} register read cascades")

    # Clean up orphaned rf_N_rd nodes (literal-indexed reads that are no longer used)
    # After cascade replacement, we use rf[op_X]_rd instead of rf_0_rd, rf_1_rd, etc.
    orphaned_rf_reads = []
    for node_id, node in list(graph.nodes.items()):
        # Match pattern: rf_0_rd, rf_1_rd, ..., rf_31_rd
        if node_id.startswith('rf_') and node_id.endswith('_rd'):
            middle = node_id[3:-3]  # Extract the number between 'rf_' and '_rd'
            if middle.isdigit():
                # This is a literal-indexed read
                if len(list(node.outgoing_edges)) == 0:
                    # No longer used, remove it
                    orphaned_rf_reads.append(node_id)

                    # Remove incoming edges
                    for edge in list(node.incoming_edges):
                        graph.remove_edge(edge.id)

                    # Remove the node
                    graph.remove_node(node_id)

                    # Also remove the associated rf_index_N literal if it's orphaned
                    index_node_id = f'rf_index_{middle}'
                    if index_node_id in graph.nodes:
                        index_node = graph.nodes[index_node_id]
                        if len(list(index_node.outgoing_edges)) == 0:
                            # Remove incoming edges (shouldn't have any)
                            for edge in list(index_node.incoming_edges):
                                graph.remove_edge(edge.id)
                            graph.remove_node(index_node_id)

    if orphaned_rf_reads:
        print(f"  Removed {len(orphaned_rf_reads)} orphaned literal-indexed rf reads and their index constants")

    # Clean up orphaned comparison and literal nodes from register decode
    # After cascade replacement, we no longer need (rd == N), (rs1 == N), (rs2 == N) comparisons
    orphaned_comparisons = []
    orphaned_literals = []

    for node_id, node in list(graph.nodes.items()):
        # Find orphaned comparison nodes (==, !=, etc. with no outgoing edges)
        if node.data.get('type') == 'operation' and len(list(node.outgoing_edges)) == 0:
            # Check if it's comparing against register indices (0-31)
            is_reg_decode = False
            for edge in node.incoming_edges:
                src = edge.source
                if src.data.get('type') == 'literal':
                    val = src.data.get('value')
                    if isinstance(val, int) and 0 <= val <= 31:
                        is_reg_decode = True
                        break

            if is_reg_decode:
                orphaned_comparisons.append(node_id)

                # Remove incoming edges and collect orphaned literals
                for edge in list(node.incoming_edges):
                    src = edge.source
                    # Check if the source literal will be orphaned
                    if src.data.get('type') == 'literal':
                        # Will this literal have no more uses after we remove this edge?
                        if len(list(src.outgoing_edges)) == 1:  # Only this comparison uses it
                            orphaned_literals.append(src.id)
                    graph.remove_edge(edge.id)

                # Remove the comparison node
                graph.remove_node(node_id)

    # Clean up the orphaned literals
    for lit_id in orphaned_literals:
        if lit_id in graph.nodes:  # May have been removed already
            lit_node = graph.nodes[lit_id]
            # Remove any remaining edges (shouldn't be any)
            for edge in list(lit_node.incoming_edges):
                graph.remove_edge(edge.id)
            for edge in list(lit_node.outgoing_edges):
                graph.remove_edge(edge.id)
            graph.remove_node(lit_id)

    if orphaned_comparisons:
        print(f"  Removed {len(orphaned_comparisons)} orphaned register decode comparisons and {len(orphaned_literals)} associated literals")


def _analyze_register_read_cascade(graph: ResourceGraph, root_node: Node) -> Optional[Dict]:
    """
    Analyze if a ternary node is the root of a register read cascade.

    Returns dict with:
        - index_node: The node used for indexing (e.g., op_21 for rs1)
        - ternary_nodes: List of all ternary nodes in the cascade
    Or None if not a register read cascade.
    """

    def is_rf_read(node_id: str) -> bool:
        """Check if a node is a register file read (literal or variable-indexed)."""
        # Matches both rf_X_rd and rf[...]_rd patterns
        return (node_id.startswith('rf_') or node_id.startswith('rf[')) and node_id.endswith('_rd')

    # Check if this ternary selects from rf_X_rd nodes
    ternary_nodes = []
    rf_reads = set()
    index_node = None

    def traverse_cascade(tern_node):
        """Recursively traverse the cascade."""
        nonlocal index_node

        if tern_node.data.get('type') != 'ternary_op':
            return

        ternary_nodes.append(tern_node)

        # Get ternary components
        condition = None
        true_val = None
        false_val = None

        for edge in tern_node.incoming_edges:
            edge_type = edge.data.get('type')
            if edge_type == 'ternary_condition':
                condition = edge.source
            elif edge_type == 'ternary_true':
                true_val = edge.source
            elif edge_type == 'ternary_false':
                false_val = edge.source

        # Check if true value is rf_X_rd or rf[...]_rd
        if true_val and is_rf_read(true_val.id):
            rf_reads.add(true_val.id)

        # Check condition pattern: (index == constant)
        if condition and condition.data.get('operator') == '==':
            # Extract the index operand (should be same across all conditions)
            for edge in condition.incoming_edges:
                source = edge.source
                if source.data.get('type') != 'literal':
                    if index_node is None:
                        index_node = source
                    elif index_node.id != source.id:
                        # Different index nodes - not a valid cascade
                        return False

        # Recurse on false branch if it's another ternary
        if false_val and false_val.data.get('type') == 'ternary_op':
            traverse_cascade(false_val)
        elif false_val and is_rf_read(false_val.id):
            # Leaf node is also rf read (literal or variable-indexed)
            rf_reads.add(false_val.id)

    traverse_cascade(root_node)

    # Valid cascade must have:
    # - Multiple rf reads (or at least one if the false branch is a variable-indexed read)
    # - Consistent index node
    # - Index node must be 5 bits (register index) to avoid confusing with byte-enable logic
    if len(rf_reads) >= 1 and index_node:
        # Check bit width of index node
        # For RISC-V, register index should be 5 bits (for 32 registers)
        # Byte-enable logic uses 2 bits (address[1:0]), so we can filter it out
        index_width = index_node.data.get('bit_width')

        # Also check if it's a bit_slice - get the slice width
        if index_node.data.get('type') == 'bit_slice':
            # Try high_bit/low_bit fields (set by ILA parser)
            high_bit = index_node.data.get('high_bit')
            low_bit = index_node.data.get('low_bit')
            if high_bit is not None and low_bit is not None:
                index_width = high_bit - low_bit + 1
            # Also try bitslice tuple
            elif 'bitslice' in index_node.data:
                bitslice = index_node.data['bitslice']
                index_width = bitslice[0] - bitslice[1] + 1

        # Only accept if index is 5 bits (valid register index)
        if index_width != 5:
            # This is not a register read cascade - likely byte-enable or other logic
            return None

        return {
            'index_node': index_node,
            'ternary_nodes': ternary_nodes,
            'rf_reads': rf_reads
        }

    return None


def _remove_ternary_cascade(graph: ResourceGraph, root_node: Node, ternary_nodes: List[Node]):
    """Remove all nodes in a ternary cascade that are no longer needed."""
    # Don't remove nodes that have other uses
    for tern_node in ternary_nodes:
        # Check if this ternary is used elsewhere
        has_other_uses = False
        for edge in tern_node.outgoing_edges:
            if edge.target != root_node:  # Has uses besides parent in cascade
                has_other_uses = True
                break

        if not has_other_uses and tern_node.id in graph.nodes:
            # Remove all incoming edges
            for edge in list(tern_node.incoming_edges):
                graph.remove_edge(edge)
            # Remove all outgoing edges
            for edge in list(tern_node.outgoing_edges):
                graph.remove_edge(edge)
            # Remove the node
            graph.remove_node(tern_node.id)


def apply_ila_transformations(graph: ResourceGraph, include_regfile=True):
    """
    Apply all ILA-specific transformations to a resource graph.

    Args:
        graph: The resource graph to transform
        include_regfile: If True, transform x0-x31 to rf array (default True)
                        Set to False when applying per-instruction to avoid
                        creating separate rf arrays for each instruction
    """
    if include_regfile:
        transform_registers_to_regfile(graph)
        replace_register_read_cascades(graph)
    transform_memory_ternaries(graph)
