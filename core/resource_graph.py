from typing import Any, Dict, List, Set, Callable, Optional, Tuple
from uuid import uuid4

class Node:
    """A node in the ResourceGraph with bidirectional edge references."""

    def __init__(self, node_id: Optional[str] = None, data: Any = None,
                 is_arch_state: bool = False, used_as_index: bool = False,
                 indexed_by: Optional['Node'] = None, is_uarch_state: bool = False,
                 uarch_time: Optional[int] = None, pipe_time: Optional[int] = None,
                 from_isa_spec: bool = False,
                 already_split: bool = False, latency: int = 0, variable_latency: bool = False,
                 is_shared: bool = False,
                 pipe_id: Optional[int] = None, dual_issue_time: Optional[int] = None):
        self.id = node_id or str(uuid4())
        self.data = data
        self.is_arch_state = is_arch_state
        self.is_shared = is_shared  # True if node is shared across instructions (both ISA state and intermediate nodes)
        self.is_uarch_state = is_uarch_state
        self.used_as_index = used_as_index
        self.indexed_by = indexed_by
        self.uarch_time = uarch_time
        self.pipe_time = pipe_time  # Pipeline stage time: only increments on pipeline_register nodes
        self.pipe_id = pipe_id  # Pipeline ID for dual-issue: 0=primary, 1=secondary, None=shared
        self.dual_issue_time = dual_issue_time  # For hazard detection: pipe_time * 2 + pipe_id
        self.from_isa_spec = from_isa_spec
        self.already_split = already_split
        self.latency = latency  # Latency in cycles: 0=combinational (same cycle), 1=one cycle delay, etc.
        self.variable_latency = variable_latency  # If True, latency is unknown/variable (e.g., memory with caching)
        self.incoming_edges: Set['Edge'] = set()
        self.outgoing_edges: Set['Edge'] = set()



    def add_incoming_edge(self, edge: 'Edge') -> None:
        """Add an incoming edge to this node."""
        self.incoming_edges.add(edge)

    def add_outgoing_edge(self, edge: 'Edge') -> None:
        """Add an outgoing edge from this node."""
        self.outgoing_edges.add(edge)

    def remove_incoming_edge(self, edge: 'Edge') -> None:
        """Remove an incoming edge from this node."""
        self.incoming_edges.discard(edge)

    def remove_outgoing_edge(self, edge: 'Edge') -> None:
        """Remove an outgoing edge from this node."""
        self.outgoing_edges.discard(edge)

    def get_neighbors(self) -> Set['Node']:
        """Get all neighboring nodes (connected via incoming or outgoing edges)."""
        neighbors = set()
        for edge in self.incoming_edges:
            neighbors.add(edge.source)
        for edge in self.outgoing_edges:
            neighbors.add(edge.target)
        return neighbors

    def __str__(self) -> str:
        indexed_by_id = self.indexed_by.id if self.indexed_by else None
        pipe_info = f", pipe_id={self.pipe_id}, dual_issue_time={self.dual_issue_time}" if self.pipe_id is not None else ""
        return f"Node({self.id}, data={self.data}, arch_state={self.is_arch_state}, uarch_state={self.is_uarch_state}, uarch_time={self.uarch_time}, pipe_time={self.pipe_time}{pipe_info}, index={self.used_as_index}, indexed_by={indexed_by_id})"

    def __repr__(self) -> str:
        return self.__str__()


class Edge:
    """An edge in the ResourceGraph with bidirectional node references."""

    def __init__(self, source: Node, target: Node, edge_id: Optional[str] = None, data: Any = None):
        self.id = edge_id or str(uuid4())
        self.source = source
        self.target = target
        self.data = data

        # Establish bidirectional references
        source.add_outgoing_edge(self)
        target.add_incoming_edge(self)

    def remove_from_nodes(self) -> None:
        """Remove this edge from its source and target nodes."""
        self.source.remove_outgoing_edge(self)
        self.target.remove_incoming_edge(self)

    def __str__(self) -> str:
        return f"Edge({self.id}, {self.source.id} -> {self.target.id}, data={self.data})"

    def __repr__(self) -> str:
        return self.__str__()


class ResourceGraph:
    """A graph data structure with nodes and edges, supporting filtering and edge node insertion."""

    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.edges: Dict[str, Edge] = {}
        self.aspect_declarations: List[Dict] = []  # Store aspect declarations
        self.assume_expressions: List[Dict] = []  # Parsed assume constraint ASTs
        self.orthogon_uses: List[Dict] = []  # Store orthogon use declarations

    def add_node(self, node: Node) -> None:
        """Add a node to the graph.

        If a node with the same ID already exists, transfers all edges from
        the old node to the new one to maintain graph connectivity.
        """
        # Check if node with same ID already exists
        if node.id in self.nodes:
            old_node = self.nodes[node.id]

            # Transfer all incoming edges to new node
            for edge in list(old_node.incoming_edges):
                old_node.remove_incoming_edge(edge)
                edge.target = node  # Update edge to point to new node
                node.add_incoming_edge(edge)

            # Transfer all outgoing edges to new node
            for edge in list(old_node.outgoing_edges):
                old_node.remove_outgoing_edge(edge)
                edge.source = node  # Update edge to point to new node
                node.add_outgoing_edge(edge)

        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        """Add an edge to the graph."""
        self.edges[edge.id] = edge
        # Ensure nodes are in the graph
        if edge.source.id not in self.nodes:
            self.add_node(edge.source)
        if edge.target.id not in self.nodes:
            self.add_node(edge.target)

    def remove_node(self, node_id: str) -> None:
        """Remove a node and all its connected edges from the graph."""
        if node_id not in self.nodes:
            return

        node = self.nodes[node_id]

        # Remove all connected edges
        edges_to_remove = list(node.incoming_edges | node.outgoing_edges)
        for edge in edges_to_remove:
            self.remove_edge(edge.id)

        # Remove the node
        del self.nodes[node_id]

    def remove_edge(self, edge_id: str) -> None:
        """Remove an edge from the graph."""
        if edge_id not in self.edges:
            return

        edge = self.edges[edge_id]
        edge.remove_from_nodes()
        del self.edges[edge_id]

    def insert_node_on_edge(self, edge_id: str, new_node: Node) -> Tuple[Edge, Edge]:
        """
        Insert a node on an existing edge, replacing the edge with two new edges.
        Returns the two new edges: (source->new_node, new_node->target)
        """
        if edge_id not in self.edges:
            raise ValueError(f"Edge {edge_id} not found in graph")

        old_edge = self.edges[edge_id]
        source = old_edge.source
        target = old_edge.target

        # Remove the old edge
        self.remove_edge(edge_id)

        # Add the new node to the graph
        self.add_node(new_node)

        # Create two new edges
        edge1 = Edge(source, new_node, data=old_edge.data)
        edge2 = Edge(new_node, target, data=old_edge.data)

        self.add_edge(edge1)
        self.add_edge(edge2)

        return edge1, edge2

    def filter_nodes(self, predicate: Callable[[Node], bool]) -> List[Node]:
        """Filter nodes based on a predicate function."""
        return [node for node in self.nodes.values() if predicate(node)]

    def filter_edges(self, predicate: Callable[[Edge], bool]) -> List[Edge]:
        """Filter edges based on a predicate function."""
        return [edge for edge in self.edges.values() if predicate(edge)]

    def filter_subgraph(self, node_predicate: Callable[[Node], bool],
                       edge_predicate: Callable[[Edge], bool]) -> 'ResourceGraph':
        """
        Create a subgraph containing only nodes and edges that match the predicates.
        Only includes edges where both source and target nodes match the node predicate.
        """
        subgraph = ResourceGraph()

        # Add matching nodes
        filtered_nodes = self.filter_nodes(node_predicate)
        node_ids = {node.id for node in filtered_nodes}

        for node in filtered_nodes:
            # Create a new node to avoid reference issues
            new_node = Node(node.id, node.data, node.is_arch_state,
                          node.used_as_index, node.indexed_by,
                          node.is_uarch_state, node.uarch_time,
                          pipe_time=node.pipe_time,
                          latency=node.latency, is_shared=node.is_shared)
            subgraph.add_node(new_node)

        # Add matching edges (only if both endpoints are included)
        for edge in self.edges.values():
            if (edge.source.id in node_ids and
                edge.target.id in node_ids and
                edge_predicate(edge)):

                source_node = subgraph.nodes[edge.source.id]
                target_node = subgraph.nodes[edge.target.id]
                new_edge = Edge(source_node, target_node, edge.id, edge.data)
                subgraph.add_edge(new_edge)

        return subgraph

    def get_node_count(self) -> int:
        """Get the number of nodes in the graph."""
        return len(self.nodes)

    def get_edge_count(self) -> int:
        """Get the number of edges in the graph."""
        return len(self.edges)

    @classmethod
    def from_isa_file(cls, filename: str, defines: dict = None) -> 'ResourceGraph':
        """Create a ResourceGraph from an ISA description file."""
        from .isa_parser import parse_isa_file
        return parse_isa_file(filename, defines=defines)

    @classmethod
    def from_verilog_file(cls, filename: str) -> 'ResourceGraph':
        """Create a ResourceGraph from a Verilog/SystemVerilog file."""
        from frontends.verilog import parse_verilog_file
        return parse_verilog_file(filename)

    @classmethod
    def from_verilog_text(cls, verilog_text: str, module_name: str = "top") -> 'ResourceGraph':
        """Create a ResourceGraph from Verilog/SystemVerilog text."""
        from frontends.verilog import parse_verilog_text
        return parse_verilog_text(verilog_text, module_name)

    @classmethod
    def from_ila_json_file(cls, filename: str) -> 'ResourceGraph':
        """Create a ResourceGraph from an ILA JSON file."""
        from frontends.ila import parse_ila_json_file
        return parse_ila_json_file(filename)

    @classmethod
    def from_ila_json(cls, ila_json: dict) -> 'ResourceGraph':
        """Create a ResourceGraph from an ILA JSON object."""
        from frontends.ila import parse_ila_json
        return parse_ila_json(ila_json)

    @classmethod
    def from_sail_file(cls, filename: str) -> 'ResourceGraph':
        """Create a ResourceGraph from a SAIL ISA specification file."""
        from frontends.sail.sail_parser import parse_sail_file
        return parse_sail_file(filename)

    @classmethod
    def from_sail_text(cls, sail_text: str) -> 'ResourceGraph':
        """Create a ResourceGraph from SAIL ISA specification text."""
        from frontends.sail.sail_parser import parse_sail_text
        return parse_sail_text(sail_text)

    def display_ascii(self, simple: bool = False) -> str:
        """Display the graph as ASCII art."""
        from gui.graph_display import ASCIIGraphDisplay
        display = ASCIIGraphDisplay(self)
        if simple:
            return display.display_simple()
        else:
            return display.display()

    def print_ascii(self, simple: bool = False) -> None:
        """Print the graph as ASCII art to console."""
        print(self.display_ascii(simple))

    def display_by_time(self) -> str:
        """Display nodes grouped by their uarch_time."""
        from gui.graph_display import ASCIIGraphDisplay
        display = ASCIIGraphDisplay(self)
        return display.display_by_time()

    def print_by_time(self) -> None:
        """Print nodes grouped by their uarch_time to console."""
        print(self.display_by_time())

    def generate_verilog(self, module_name: str = "processor") -> str:
        """Generate Verilog code from this ResourceGraph."""
        from backends.verilog import generate_verilog
        return generate_verilog(self, module_name)

    def generate_circt(self, module_name: str = "processor") -> str:
        """Generate CIRCT MLIR code from this ResourceGraph."""
        from backends.circt.circt_generator import generate_circt
        return generate_circt(self, module_name)

    def generate_cpp_sim(self, module_name: str = "processor") -> str:
        """Generate C++ simulation code from this ResourceGraph."""
        from backends.sim_cpp.generator import generate_cpp_sim
        return generate_cpp_sim(self, module_name)

    def generate_rtlil(self, module_name: str = "processor") -> str:
        """Generate Yosys RTLIL code from this ResourceGraph."""
        from backends.rtlil import generate_rtlil
        return generate_rtlil(self, module_name)

    def optimize(self, enable_all: bool = True,
                 propagate_aliases: bool = True,
                 merge_nested_muxes: bool = True,
                 split_arch_state: bool = True) -> None:
        """
        Apply optimization transformations to this graph.

        Args:
            enable_all: If True, enables all optimizations
            propagate_aliases: Propagate wire aliases to simplify graph
            merge_nested_muxes: Flatten nested muxes/ternary operators
            split_arch_state: Split arch state nodes into read/write
        """
        from .graph_optimizer import GraphOptimizer
        optimizer = GraphOptimizer(self)
        optimizer.optimize(
            enable_all=enable_all,
            propagate_aliases=propagate_aliases,
            merge_nested_muxes=merge_nested_muxes,
            split_arch_state=split_arch_state
        )

    def infer_uarch_time(self, force_reinfer: bool = False) -> None:
        """
        Infer uarch_time for all nodes in the graph.

        Algorithm:
        1. ISA state nodes get uarch_time = 0
        2. Traverse forward through the graph
        3. Each time we pass through a uarch_state node, increment time by 1
        4. Other nodes inherit the time from their inputs

        Args:
            force_reinfer: If True, reset all timing and re-infer. If False,
                         preserve existing timing from optimizations.
        """
        # Check if timing has already been set by optimizations
        has_existing_timing = any(node.uarch_time is not None for node in self.nodes.values())

        if has_existing_timing and not force_reinfer:
            # Timing already set by optimization - only infer missing times
            unset_nodes = [node for node in self.nodes.values() if node.uarch_time is None]
            if not unset_nodes:
                return  # All timing is already set
        else:
            # Reset all uarch_time values for fresh inference
            # BUT preserve explicitly set uarch_time on pipeline_register and validity_bit nodes
            for node in self.nodes.values():
                # Don't reset uarch_time for pipeline registers or validity bits if it was explicitly set
                if node.data.get('type') in ['pipeline_register', 'validity_bit']:
                    continue  # Keep explicitly set uarch_time
                node.uarch_time = None

        # Step 1: Set ISA state READ nodes to time 0 (only if not already set by optimizations)
        # Write nodes (_wr suffix) should inherit timing from their sources, not default to 0
        # Memory access nodes ([addr]_rd, [addr]_wr) should inherit timing from their address inputs
        # Multiplexers and write ports should inherit timing from their data inputs
        isa_state_nodes = [node for node in self.nodes.values() if node.is_arch_state]
        for node in isa_state_nodes:
            # Only set to 0 if timing hasn't been set by optimizations
            # AND this is a read node (not a write node)
            # AND this is NOT one of these types that should inherit timing:
            #   - Memory access operations (dmem[addr]_rd, rf[rs]_rd, etc.)
            #   - Multiplexers (rf_write_data_mux, etc.)
            #   - Memory write ports (rf_shared_wr, etc.)
            node_type = node.data.get('type', '')
            is_memory_access = '[' in node.id and ']_rd' in node.id
            is_multiplexer = node_type == 'multiplexer'
            is_write_port = node_type == 'memory_write_port'
            is_write_node = node.id.endswith('_wr')

            should_inherit_timing = is_memory_access or is_multiplexer or is_write_port or is_write_node

            if node.uarch_time is None and not should_inherit_timing:
                node.uarch_time = 0

        # Step 2: Propagate time through the graph using topological traversal
        changed = True
        max_iterations = len(self.nodes) * 2  # Prevent infinite loops
        iteration = 0

        while changed and iteration < max_iterations:
            changed = False
            iteration += 1

            for node in self.nodes.values():
                if node.uarch_time is not None:
                    continue  # Already has a time

                # Calculate time based on incoming edges
                input_times = []
                has_all_inputs = True

                for edge in node.incoming_edges:
                    edge_type = edge.data.get('type', '') if edge.data else ''

                    # Skip stall/enable signals - these are feedback from later stages
                    # and don't determine the timing of the register
                    if edge_type in ['stall', 'enable', 'pipeline_control']:
                        continue

                    source_node = edge.source
                    if source_node.uarch_time is None:
                        has_all_inputs = False
                        break

                    # If source has variable latency, use its base time but mark dependency
                    if source_node.variable_latency:
                        # Operation's uarch_time is its BASE stage (where it starts)
                        # Downstream nodes inherit this but are marked as dependent on variable completion
                        input_times.append(source_node.uarch_time)
                        # Track variable latency dependency
                        if 'depends_on_variable_latency' not in node.data:
                            node.data['depends_on_variable_latency'] = []
                        if source_node.id not in node.data['depends_on_variable_latency']:
                            node.data['depends_on_variable_latency'].append(source_node.id)
                    # If source is uarch_state, add 1 to its time (pipeline register delay)
                    elif source_node.is_uarch_state:
                        input_times.append(source_node.uarch_time + 1)
                    # If source has latency > 0, add the latency (pipelined or multi-cycle operation)
                    elif source_node.latency > 0:
                        input_times.append(source_node.uarch_time + source_node.latency)
                    else:
                        # latency = 0 means combinational, output same cycle as input
                        input_times.append(source_node.uarch_time)

                # If we have all input times, set this node's time
                if has_all_inputs and input_times:
                    # Take the maximum time from all inputs
                    # Note: Enable/gating signals don't affect data timing
                    base_time = max(input_times)
                    node.uarch_time = base_time
                    changed = True
                elif has_all_inputs and not input_times:
                    # Node with no inputs - default to time 0
                    node.uarch_time = 0
                    changed = True

        # Handle any remaining nodes without time (shouldn't happen in well-formed graphs)
        for node in self.nodes.values():
            if node.uarch_time is None:
                node.uarch_time = 0  # Default fallback

    def get_nodes_at_time(self, time: int) -> List['Node']:
        """Get all nodes that execute at a specific uarch_time."""
        return [node for node in self.nodes.values() if node.uarch_time == time]

    def get_max_uarch_time(self) -> int:
        """Get the maximum uarch_time in the graph."""
        times = [node.uarch_time for node in self.nodes.values() if node.uarch_time is not None]
        return max(times) if times else 0

    def infer_pipe_time(self, force_reinfer: bool = False) -> None:
        """
        Infer pipe_time for all nodes in the graph.

        pipe_time is similar to uarch_time but ONLY increments when passing through
        pipeline_register nodes (nodes with data['type'] == 'pipeline_register').
        This allows for pipeline stages that have latency greater than a single cycle
        (e.g., for memory operations with variable latency).

        Differences from uarch_time:
        - uarch_time: increments on ALL uarch_state nodes and adds latency
        - pipe_time: ONLY increments on pipeline_register nodes

        Algorithm:
        1. ISA state nodes get pipe_time = 0
        2. Pipeline registers have pipe_time explicitly set to their stage index
        3. Traverse forward through the graph
        4. All nodes inherit pipe_time from their inputs without incrementing
           (pipeline_register nodes already have the correct stage time)

        Args:
            force_reinfer: If True, reset all timing and re-infer. If False,
                         preserve existing timing from optimizations.
        """
        # Check if timing has already been set
        has_existing_timing = any(node.pipe_time is not None for node in self.nodes.values())

        if has_existing_timing and not force_reinfer:
            # Timing already set - only infer missing times
            unset_nodes = [node for node in self.nodes.values() if node.pipe_time is None]
            if not unset_nodes:
                return  # All timing is already set
        else:
            # Reset all pipe_time values for fresh inference
            # BUT preserve explicitly set pipe_time on pipeline_register and validity_bit nodes
            for node in self.nodes.values():
                # Don't reset pipe_time for pipeline registers or validity bits if it was explicitly set
                if node.data.get('type') in ['pipeline_register', 'validity_bit']:
                    continue  # Keep explicitly set pipe_time
                node.pipe_time = None

        # Step 1: Set ISA state READ nodes to time 0 (only if not already set)
        # Same logic as uarch_time for determining which nodes start at time 0
        isa_state_nodes = [node for node in self.nodes.values() if node.is_arch_state]
        for node in isa_state_nodes:
            node_type = node.data.get('type', '')
            is_memory_access = '[' in node.id and ']_rd' in node.id
            is_multiplexer = node_type == 'multiplexer'
            is_write_port = node_type == 'memory_write_port'
            is_write_node = node.id.endswith('_wr')

            should_inherit_timing = is_memory_access or is_multiplexer or is_write_port or is_write_node

            if node.pipe_time is None and not should_inherit_timing:
                node.pipe_time = 0

        # Step 2: Propagate time through the graph using topological traversal
        changed = True
        max_iterations = len(self.nodes) * 2  # Prevent infinite loops
        iteration = 0

        while changed and iteration < max_iterations:
            changed = False
            iteration += 1

            for node in self.nodes.values():
                if node.pipe_time is not None:
                    continue  # Already has a time

                # Calculate time based on incoming edges
                input_times = []
                has_all_inputs = True

                for edge in node.incoming_edges:
                    edge_type = edge.data.get('type', '') if edge.data else ''

                    # Skip stall/enable signals - these are feedback from later stages
                    # Also skip state_write edges - writes to state tables are feedback
                    # (the table's read output depends on its previous value, not current writes)
                    if edge_type in ['stall', 'enable', 'pipeline_control', 'state_write']:
                        continue

                    source_node = edge.source
                    if source_node.pipe_time is None:
                        has_all_inputs = False
                        break

                    # Pipeline register nodes already have the correct pipe_time for their stage
                    # Their outputs inherit this time without incrementing
                    if source_node.data.get('type') == 'pipeline_register':
                        input_times.append(source_node.pipe_time)
                    else:
                        # All other nodes (including non-pipeline uarch_state, latency ops)
                        # inherit the time without incrementing
                        input_times.append(source_node.pipe_time)

                # If we have all input times, set this node's time
                if has_all_inputs and input_times:
                    # Take the maximum time from all inputs
                    base_time = max(input_times)
                    node.pipe_time = base_time
                    changed = True
                elif has_all_inputs and not input_times:
                    # Node with no inputs - default to time 0
                    node.pipe_time = 0
                    changed = True

        # Handle any remaining nodes without time (shouldn't happen in well-formed graphs)
        for node in self.nodes.values():
            if node.pipe_time is None:
                node.pipe_time = 0  # Default fallback

    def get_nodes_at_pipe_time(self, time: int) -> List['Node']:
        """Get all nodes that are at a specific pipe_time (pipeline stage)."""
        return [node for node in self.nodes.values() if node.pipe_time == time]

    def get_max_pipe_time(self) -> int:
        """Get the maximum pipe_time in the graph (number of pipeline stages - 1)."""
        times = [node.pipe_time for node in self.nodes.values() if node.pipe_time is not None]
        return max(times) if times else 0

    def infer_dual_issue_time(self, force_reinfer: bool = False) -> None:
        """
        Infer dual_issue_time for all nodes in a dual-issue pipeline.

        dual_issue_time = pipe_time * 2 + pipe_id

        This creates an interleaved ordering where p0 at stage N is always
        "older" than p1 at stage N for hazard detection purposes.

        IMPORTANT: dual_issue_time is used ONLY for hazard detection (comparing
        when values are produced vs consumed). It is NOT used for:
        - Bubble propagation (which stays within each pipeline)
        - Stall signal routing (which is per-pipeline)
        - Pipeline stage identification (use pipe_time for that)

        Prerequisites:
        - pipe_time must already be inferred
        - pipe_id must be set on pipeline-specific nodes (0 for p0, 1 for p1)

        Shared nodes (pipe_id=None) get dual_issue_time=None, as they are not
        part of the hazard timing analysis.

        Args:
            force_reinfer: If True, recalculate all dual_issue_time values.
                          If False, only set values for nodes where it's None.
        """
        nodes_updated = 0

        for node in self.nodes.values():
            # Skip if already set and not forcing re-inference
            if not force_reinfer and node.dual_issue_time is not None:
                continue

            # Can only compute dual_issue_time if both pipe_time and pipe_id are set
            if node.pipe_id is not None and node.pipe_time is not None:
                node.dual_issue_time = node.pipe_time * 2 + node.pipe_id
                nodes_updated += 1
            else:
                # Shared nodes or nodes without pipe_id don't have dual_issue_time
                node.dual_issue_time = None

        if nodes_updated > 0:
            print(f"  Inferred dual_issue_time for {nodes_updated} nodes")

    def get_nodes_at_dual_issue_time(self, time: int) -> List['Node']:
        """Get all nodes at a specific dual_issue_time."""
        return [node for node in self.nodes.values() if node.dual_issue_time == time]

    def get_max_dual_issue_time(self) -> int:
        """Get the maximum dual_issue_time in the graph."""
        times = [node.dual_issue_time for node in self.nodes.values() if node.dual_issue_time is not None]
        return max(times) if times else 0

    def create_uarch_state_node(self, node_id: str, data: Any = None, bit_width: int = 32) -> 'Node':
        """Create a new uarch_state node and add it to the graph."""
        if data is None:
            data = {
                'type': 'uarch_state',
                'name': node_id,
                'display_name': node_id,
                'bit_width': bit_width
            }

        node = Node(node_id, data, is_uarch_state=True)
        self.add_node(node)
        return node

    def _node_depends_on(self, expr_node: Node, target_node: Node, visited: Optional[Set[str]] = None) -> bool:
        """
        Check if expr_node's computation depends on target_node.
        Used to detect self-referential writes like pc = pc+4.
        """
        if visited is None:
            visited = set()

        if expr_node.id in visited:
            return False

        visited.add(expr_node.id)

        # Check if this is the target node
        if expr_node.id == target_node.id:
            return True

        # Recursively check all incoming edges
        for edge in expr_node.incoming_edges:
            if self._node_depends_on(edge.source, target_node, visited):
                return True

        return False

    def classify_architectural_state(self):
        """
        Analyze usage patterns to properly classify nodes as architectural state.

        Architectural state nodes are those that:
        1. Have multi-dimensional arrays (like memory and register files)
        2. Are written to AND read from in different contexts (persistent state)
        3. Are not just temporary computation results
        4. Have self-referential writes (e.g., pc = pc+4)

        Temporary/intermediate nodes are those that:
        1. Are only assigned once and used immediately (like 'instr')
        2. Are computation results that don't persist

        NOTE: If a node is already marked is_arch_state=True (e.g., from ISA parser),
        we preserve that classification and don't override it with heuristics.
        """
        for node in self.nodes.values():
            if node.data.get('type', '').startswith('isa_state'):
                # If already explicitly marked as arch state (e.g., by ISA parser), keep it
                if node.is_arch_state:
                    continue

                # Multi-dimensional arrays are typically architectural state (memory, register files)
                if node.data.get('is_memory', False):
                    node.is_arch_state = True
                    continue

                # Check usage patterns
                is_written_to = False
                is_read_from = False
                write_count = 0
                has_self_referential_write = False

                # Count writes (incoming assignment edges)
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'assignment':
                        is_written_to = True
                        write_count += 1
                        # Check if the assignment expression uses the node itself (e.g., pc = pc+4)
                        source_node = edge.source
                        if self._node_depends_on(source_node, node):
                            has_self_referential_write = True

                # Count reads (outgoing edges that aren't array indices)
                for edge in node.outgoing_edges:
                    if edge.data.get('type') in ['operand', 'bit_access', 'array_index']:
                        is_read_from = True

                # Heuristics for architectural state classification:
                # 1. If it's written to multiple times, it's likely arch state
                # 2. If it's a register file or memory (already handled above)
                # 3. If it has a self-referential write (e.g., pc = pc+4), it's arch state
                # 4. If it's only written once and immediately consumed, it's temporary
                if write_count > 1:
                    node.is_arch_state = True
                elif has_self_referential_write:
                    node.is_arch_state = True
                elif is_written_to and is_read_from:
                    # Written once and read - likely temporary (like instr fetch)
                    node.is_arch_state = False
                elif is_written_to and not is_read_from:
                    # Written but never read - could be output state
                    node.is_arch_state = True
                elif not is_written_to and is_read_from:
                    # Only read from - likely input/architectural state
                    node.is_arch_state = True

    def cleanup_disconnected_nodes(self):
        """
        Remove nodes that have become disconnected (no incoming or outgoing edges).
        This can happen after optimizations that remove edges.
        """
        disconnected_nodes = []

        for node in self.nodes.values():
            # Skip architectural state - these should be preserved even if temporarily disconnected
            if node.is_arch_state:
                continue

            # Skip uarch_state nodes - these are structural nodes from optimizations
            if node.is_uarch_state:
                continue

            # Skip control nodes that may appear disconnected but serve purposes
            node_type = node.data.get('type', '')
            if node_type in ['uarch_counter', 'hazard_detection_unit', 'stall_controller',
                           'pipeline_register', 'completion_signal']:
                continue

            # Check if node has no connections
            if not node.incoming_edges and not node.outgoing_edges:
                # Allow certain node types to exist without connections
                if node_type in ['literal', 'isa_state']:
                    continue

                # Only remove clearly temporary nodes that are truly disconnected
                if node_type in ['temp_var', 'operation', 'bit_slice', 'array_access']:
                    disconnected_nodes.append(node.id)

        # Remove disconnected nodes
        for node_id in disconnected_nodes:
            print(f"Removing disconnected node: {node_id}")
            del self.nodes[node_id]

    def copy(self):
        """Create a deep copy of this ResourceGraph."""
        new_graph = ResourceGraph()

        # Copy all nodes
        for node_id, node in self.nodes.items():
            new_data = node.data.copy() if node.data else {}
            new_node = Node(
                node_id, new_data,
                is_arch_state=node.is_arch_state,
                used_as_index=node.used_as_index,
                is_uarch_state=node.is_uarch_state,
                uarch_time=node.uarch_time,
                pipe_time=node.pipe_time,
                latency=node.latency
            )
            new_graph.add_node(new_node)

        # Copy all edges
        for edge_id, edge in self.edges.items():
            source = new_graph.nodes[edge.source.id]
            target = new_graph.nodes[edge.target.id]
            new_data = edge.data.copy() if edge.data else {}
            new_edge = Edge(source, target, edge_id, new_data)
            new_graph.add_edge(new_edge)

        return new_graph

    def set_memory_width(self, mem_name: str, width: int) -> None:
        """
        Set the width of a memory after the graph has been created.
        This allows changing memory width multiple times.

        Args:
            mem_name: Name of the memory (e.g., 'dmem', 'imem')
            width: Desired width in bits

        Raises:
            ValueError: If memory not found
        """
        # Find the memory node (type='isa_state mem')
        mem_node = None
        for node in self.nodes.values():
            node_type = node.data.get('type', '')
            if (node_type == 'isa_state mem' and
                node.data.get('name') == mem_name):
                mem_node = node
                break

        if not mem_node:
            raise ValueError(f"Memory '{mem_name}' not found in graph")

        # Update the memory width
        old_width = mem_node.data.get('bit_width')
        mem_node.data['bit_width'] = width
        print(f"Changed {mem_name} width from {old_width} to {width} bits")

        # Preserve original access widths (before propagation) for transformation detection
        # Only do this the first time set_memory_width is called
        if 'access_widths' not in mem_node.data:
            access_widths = []
            for node in self.nodes.values():
                # Pattern: [instr_]memname[...]_rd or [instr_]memname[...]_wr
                if f'{mem_name}[' in node.id and ('_rd' in node.id or '_wr' in node.id):
                    # Skip transformation-created nodes
                    if not node.data.get('is_narrow_access') and not node.data.get('is_split_port'):
                        orig_width = node.data.get('bit_width', old_width)
                        access_widths.append(orig_width)

            if access_widths:
                mem_node.data['access_widths'] = access_widths
                print(f"  Stored original access widths: {access_widths}")

        # Propagate width to all access nodes
        updated_count = 0
        for node in self.nodes.values():
            # Pattern: [instr_]memname[...]_rd or [instr_]memname[...]_wr
            if f'{mem_name}[' in node.id and ('_rd' in node.id or '_wr' in node.id):
                # Don't propagate to transformation-created narrow accesses
                if not node.data.get('is_narrow_access'):
                    node.data['bit_width'] = width
                    updated_count += 1

        if updated_count > 0:
            print(f"  Propagated {width}-bit width to {updated_count} access node(s)")

    def optimize_memory_accesses(
        self,
        memory: str = 'umem',
        strategy: str = 'set_port_width',
        merge_from: Optional[List[str]] = None,
        dry_run: bool = False,
        target_width: Optional[int] = None,
        endianness: str = 'little',
        alignment: str = 'port_width'
    ) -> Dict[str, Any]:
        """
        Transform memory accesses to match memory width constraints (bidirectional).

        This helper auto-detects current access widths and applies one of the
        supported strategies. Available strategies:
        - 'set_port_width': Single-cycle byte/word selection with byte-select
            multiplexers. Best for word-addressed memories where sub-word
            accesses should be selected via muxes (no cycle overhead).
        - 'serialize_parallelize': Multi-cycle with counter. Forward (narrowing)
            serializes accesses over multiple cycles; reverse parallelizes.
        - 'split_merge': Parallel multi-port transformation (creates multiple
            ports for narrow accesses or merges them back).
        - 'none': Do not transform; only set/verify width constraint.

        Args:
            memory: Memory name (default: 'umem')
            strategy: Strategy to apply (default: 'set_port_width')
            merge_from: For 'split_merge' reverse, list of ports to merge
            dry_run: If True, analyze but don't modify the graph
            target_width: Optional explicit target width (bits). If omitted,
                the memory node's `bit_width` is used or defaults to 32.
            endianness: 'little' or 'big' (affects byte selection mux ordering)
            alignment: 'port_width' (aligned) or 'unaligned' (cross-word support)

        Returns:
            Dictionary with transformation info (see strategy-specific results).
        """
        from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec

        # Get memory node
        mem_node = self.nodes.get(memory)
        if not mem_node:
            return {
                'transformed': False,
                'reason': f"Memory {memory} not found"
            }

        # Resolve target width: explicit param > memory metadata > default 32
        if target_width is None:
            target_width = mem_node.data.get('bit_width') or 32

        # Normalize endianness/alignment in node metadata for downstream tools
        mem_node.data['endianness'] = endianness
        mem_node.data['alignment'] = alignment

        # Determine current access width (from original access patterns)
        current_width = self._get_max_memory_access_width(memory)

        if current_width is None:
            return {
                'transformed': False,
                'reason': f"Cannot determine access width for {memory}"
            }

        # Determine direction
        if current_width > target_width:
            direction = 'forward'   # Narrowing
        elif current_width < target_width:
            direction = 'reverse'   # Widening
        else:
            # Check if we need to update an existing transformation
            if self._has_existing_transformation(memory):
                direction = 'update'
            else:
                return {
                    'transformed': False,
                    'reason': 'Width already matches and no transformation exists'
                }

        # Create spec
        spec = MemoryAccessTransformSpec(
            memory=memory,
            strategy=strategy,
            current_width=current_width,
            target_width=target_width,
            direction=direction,
            merge_from=merge_from,
            endianness=endianness,
            alignment=alignment
        )

        # Apply transformation with error handling and logging
        transform = MemoryAccessTransform(self)
        try:
            result = transform.apply_transformation(spec, dry_run=dry_run)
        except Exception as e:
            return {
                'transformed': False,
                'reason': 'exception',
                'exception': str(e)
            }

        # Summarize results for convenience
        try:
            nodes_added = result.get('nodes_added', [])
            nodes_removed = result.get('nodes_removed', [])
            nodes_updated = result.get('nodes_updated', [])
            print(f"Memory transform '{strategy}' on '{memory}': {direction} {current_width}→{target_width} bits")
            print(f"  Accesses affected: {result.get('num_accesses_affected', 0)}")
            print(f"  Nodes added: {len(nodes_added)}; removed: {len(nodes_removed)}; updated: {len(nodes_updated)}")
            if dry_run:
                print("  Dry run: no graph modifications applied")
        except Exception:
            # Best-effort logging; ignore logging errors
            pass

        return result

    def _get_max_memory_access_width(self, memory: str) -> Optional[int]:
        """
        Get the maximum access width for a memory.

        Returns the widest access, or None if no accesses found.
        If memory is serialized, returns the narrow serialized width (word_width),
        NOT the original wide width.
        """
        mem_node = self.nodes.get(memory)
        if not mem_node:
            return None

        # If serialized, get the NARROW width from merge node's word_width
        # (which doesn't get propagated by set_memory_width)
        if self._has_existing_transformation(memory):
            # Look for merge node to get current serialized word width
            for node in self.nodes.values():
                if node.data.get('type') == 'memory_data_merge':
                    if node.data.get('memory') == memory:
                        # Return the narrow word width (what we're currently using)
                        return node.data.get('word_width')

        # Check if there's serialization metadata
        if 'access_widths' in mem_node.data and mem_node.data['access_widths']:
            return max(mem_node.data['access_widths'])

        # Otherwise infer from memory width
        return mem_node.data.get('bit_width')

    def _has_existing_transformation(self, memory: str) -> bool:
        """Check if memory has existing serialization transformation."""
        # Look for counter node
        counter_name = f"{memory}_access_counter"
        return counter_name in self.nodes

    def to_json(self) -> Dict:
        """
        Serialize the graph to a JSON-compatible dictionary.

        Returns:
            Dictionary containing all graph data
        """
        # Serialize nodes
        nodes_data = []
        for node_id, node in self.nodes.items():
            node_data = {
                'id': node.id,
                'data': node.data,
                'is_arch_state': node.is_arch_state,
                'is_shared': node.is_shared,
                'is_uarch_state': node.is_uarch_state,
                'used_as_index': node.used_as_index,
                'indexed_by': node.indexed_by.id if node.indexed_by else None,
                'uarch_time': node.uarch_time,
                'pipe_time': node.pipe_time,
                'latency': node.latency,
                'variable_latency': node.variable_latency
            }
            nodes_data.append(node_data)

        # Serialize edges
        edges_data = []
        for edge_id, edge in self.edges.items():
            edge_data = {
                'id': edge.id,
                'source': edge.source.id,
                'target': edge.target.id,
                'data': edge.data
            }
            edges_data.append(edge_data)

        return {
            'nodes': nodes_data,
            'edges': edges_data
        }

    @staticmethod
    def from_json(data: Dict) -> 'ResourceGraph':
        """
        Deserialize a graph from a JSON-compatible dictionary.

        Args:
            data: Dictionary containing graph data

        Returns:
            Reconstructed ResourceGraph
        """
        graph = ResourceGraph()

        # First pass: create all nodes (without indexed_by references)
        for node_data in data['nodes']:
            node = Node(
                node_id=node_data['id'],
                data=node_data['data'],
                is_arch_state=node_data['is_arch_state'],
                is_shared=node_data.get('is_shared', False),  # Default to False for backward compatibility
                is_uarch_state=node_data['is_uarch_state'],
                used_as_index=node_data['used_as_index'],
                indexed_by=None,  # Will set in second pass
                uarch_time=node_data['uarch_time'],
                pipe_time=node_data.get('pipe_time'),  # May be None for backward compatibility
                latency=node_data.get('latency', 1),  # Default to 1 for backward compatibility
                variable_latency=node_data.get('variable_latency', False)  # Default to False for backward compatibility
            )
            graph.add_node(node)

        # Second pass: set indexed_by references
        for node_data in data['nodes']:
            if node_data['indexed_by']:
                graph.nodes[node_data['id']].indexed_by = graph.nodes[node_data['indexed_by']]

        # Third pass: create all edges
        for edge_data in data['edges']:
            source = graph.nodes[edge_data['source']]
            target = graph.nodes[edge_data['target']]
            edge = Edge(source, target, edge_data['id'], edge_data['data'])
            graph.add_edge(edge)

        return graph

    def save_to_file(self, filename: str) -> None:
        """
        Save the graph to a JSON file.

        Args:
            filename: Path to save the graph
        """
        import json
        with open(filename, 'w') as f:
            json.dump(self.to_json(), f, indent=2)

    @staticmethod
    def load_from_file(filename: str) -> 'ResourceGraph':
        """
        Load a graph from a JSON file.

        Args:
            filename: Path to load the graph from

        Returns:
            Loaded ResourceGraph
        """
        import json
        with open(filename, 'r') as f:
            data = json.load(f)
        return ResourceGraph.from_json(data)

    def __str__(self) -> str:
        return f"ResourceGraph(nodes={len(self.nodes)}, edges={len(self.edges)})"

    def __repr__(self) -> str:
        return self.__str__()