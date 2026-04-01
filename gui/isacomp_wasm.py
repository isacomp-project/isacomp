"""
isacomp-wasm: WebAssembly-compatible version of isacomp core
Includes ResourceGraph, ISA parser, and optimization algorithms
No tkinter, no subprocess, pure Python for Pyodide
"""

from typing import Any, Dict, List, Set, Callable, Optional, Tuple
from uuid import uuid4
import json
import re


class Node:
    """A node in the ResourceGraph with bidirectional edge references."""

    def __init__(self, node_id: Optional[str] = None, data: Any = None,
                 is_arch_state: bool = False, used_as_index: bool = False,
                 indexed_by: Optional['Node'] = None, is_uarch_state: bool = False,
                 uarch_time: Optional[int] = None, from_isa_spec: bool = False,
                 already_split: bool = False, latency: int = 0, variable_latency: bool = False):
        self.id = node_id or str(uuid4())
        self.data = data if data is not None else {}
        self.is_arch_state = is_arch_state
        self.is_uarch_state = is_uarch_state
        self.used_as_index = used_as_index
        self.indexed_by = indexed_by
        self.uarch_time = uarch_time
        self.from_isa_spec = from_isa_spec
        self.already_split = already_split
        self.latency = latency
        self.variable_latency = variable_latency
        self.incoming_edges: Set['Edge'] = set()
        self.outgoing_edges: Set['Edge'] = set()

    def add_incoming_edge(self, edge: 'Edge') -> None:
        self.incoming_edges.add(edge)

    def add_outgoing_edge(self, edge: 'Edge') -> None:
        self.outgoing_edges.add(edge)

    def remove_incoming_edge(self, edge: 'Edge') -> None:
        self.incoming_edges.discard(edge)

    def remove_outgoing_edge(self, edge: 'Edge') -> None:
        self.outgoing_edges.discard(edge)

    def to_dict(self) -> Dict:
        """Convert node to JSON-serializable dict for JavaScript."""
        return {
            'id': self.id,
            'data': self.data,
            'is_arch_state': self.is_arch_state,
            'is_uarch_state': self.is_uarch_state,
            'uarch_time': self.uarch_time,
            'latency': self.latency,
            'display_name': self.data.get('display_name', self.id),
            'type': self.data.get('type', 'unknown')
        }


class Edge:
    """An edge in the ResourceGraph with bidirectional node references."""

    def __init__(self, source: Node, target: Node, edge_id: Optional[str] = None, data: Any = None):
        self.id = edge_id or str(uuid4())
        self.source = source
        self.target = target
        self.data = data if data is not None else {}

        # Establish bidirectional references
        source.add_outgoing_edge(self)
        target.add_incoming_edge(self)

    def remove_from_nodes(self) -> None:
        self.source.remove_outgoing_edge(self)
        self.target.remove_incoming_edge(self)

    def to_dict(self) -> Dict:
        """Convert edge to JSON-serializable dict for JavaScript."""
        return {
            'id': self.id,
            'source': self.source.id,
            'target': self.target.id,
            'data': self.data,
            'type': self.data.get('type', 'unknown')
        }


class ResourceGraph:
    """A graph data structure with nodes and edges."""

    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.edges: Dict[str, Edge] = {}

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        self.edges[edge.id] = edge
        if edge.source.id not in self.nodes:
            self.add_node(edge.source)
        if edge.target.id not in self.nodes:
            self.add_node(edge.target)

    def remove_node(self, node_id: str) -> None:
        if node_id not in self.nodes:
            return
        node = self.nodes[node_id]
        edges_to_remove = list(node.incoming_edges | node.outgoing_edges)
        for edge in edges_to_remove:
            self.remove_edge(edge.id)
        del self.nodes[node_id]

    def remove_edge(self, edge_id: str) -> None:
        if edge_id not in self.edges:
            return
        edge = self.edges[edge_id]
        edge.remove_from_nodes()
        del self.edges[edge_id]

    def infer_uarch_time(self) -> None:
        """Infer microarchitectural timing for nodes."""
        # Initialize all nodes to None
        for node in self.nodes.values():
            node.uarch_time = None

        # Set ISA state nodes to time 0
        for node in self.nodes.values():
            if node.is_arch_state:
                node.uarch_time = 0

        # Propagate timing through the graph
        changed = True
        max_iterations = 100
        iteration = 0

        while changed and iteration < max_iterations:
            changed = False
            iteration += 1

            for node in self.nodes.values():
                if node.uarch_time is not None:
                    continue

                # Check if all predecessors have timing
                predecessors = [edge.source for edge in node.incoming_edges]
                if not predecessors:
                    node.uarch_time = 0
                    changed = True
                    continue

                pred_times = [p.uarch_time for p in predecessors]
                if all(t is not None for t in pred_times):
                    max_pred_time = max(pred_times)
                    node.uarch_time = max_pred_time + node.latency
                    changed = True

    def to_dict(self) -> Dict:
        """Convert graph to JSON-serializable dict for JavaScript."""
        return {
            'nodes': [node.to_dict() for node in self.nodes.values()],
            'edges': [edge.to_dict() for edge in self.edges.values()]
        }

    @staticmethod
    def from_isa_text(isa_text: str) -> 'ResourceGraph':
        """Parse ISA specification text and create ResourceGraph."""
        graph = ResourceGraph()

        lines = isa_text.strip().split('\n')
        isa_states = {}
        variables = {}
        index_mappings = {}

        for line in lines:
            line = line.strip()
            if not line or line.startswith('//'):
                continue

            # Parse isa_state declarations
            if line.startswith('isa_state'):
                match = re.match(r'isa_state\s+(\w+)\[(\d+):(\d+)\];', line)
                if match:
                    name, high, low = match.groups()
                    node = Node(f'isa_{name}', {
                        'type': 'isa_state',
                        'name': name,
                        'display_name': name.upper(),
                        'bit_width': int(high) - int(low) + 1
                    }, is_arch_state=True)
                    graph.add_node(node)
                    isa_states[name] = node
                    continue

                # Array isa_state
                match = re.match(r'isa_state\s+(\w+)\[(\d+):(\d+)\]\[(\d+):(\d+)\];', line)
                if match:
                    name, data_high, data_low, idx_high, idx_low = match.groups()
                    node = Node(f'isa_{name}', {
                        'type': 'isa_state',
                        'name': name,
                        'display_name': name.upper(),
                        'bit_width': int(data_high) - int(data_low) + 1,
                        'array_depth': 2 ** (int(idx_high) - int(idx_low) + 1)
                    }, is_arch_state=True)
                    graph.add_node(node)
                    isa_states[name] = node
                    continue

            # Parse var declarations
            if line.startswith('var'):
                var_name = line.replace('var', '').replace(';', '').strip()
                node = Node(f'var_{var_name}', {
                    'type': 'variable',
                    'name': var_name,
                    'display_name': var_name,
                    'bit_width': 32  # default
                })
                graph.add_node(node)
                variables[var_name] = node
                continue

            # Parse index declarations
            if line.startswith('index'):
                match = re.match(r'index\s+(\w+)\s+for\s+(\w+);', line)
                if match:
                    index_var, array_name = match.groups()
                    index_mappings[index_var] = array_name
                    continue

            # Parse assignments (simplified)
            if '=' in line and not line.startswith('index'):
                parts = line.split('=', 1)
                if len(parts) == 2:
                    lhs = parts[0].strip()
                    rhs = parts[1].replace(';', '').strip()

                    # Create nodes for the assignment
                    # This is simplified - full parser would handle expressions
                    lhs_node = None
                    if lhs in variables:
                        lhs_node = variables[lhs]
                    elif '[' in lhs:
                        # Array access
                        base = lhs.split('[')[0]
                        if base in isa_states:
                            lhs_node = isa_states[base]

                    # Parse RHS - detect operations
                    if '+' in rhs:
                        # Addition operation
                        op_node = Node(f'add_{uuid4().hex[:8]}', {
                            'type': 'operation',
                            'operator': '+',
                            'display_name': 'ADD',
                            'bit_width': 32
                        })
                        graph.add_node(op_node)

                        if lhs_node:
                            edge = Edge(op_node, lhs_node, data={'type': 'assignment'})
                            graph.add_edge(edge)

        # Infer timing
        graph.infer_uarch_time()

        return graph


# Demo/example ISA specifications
EXAMPLE_ADD = """
isa_state rf[31:0][4:0];
isa_state pc[31:0];

var rs;
var rt;
var rd;
var r1;
var r2;
var res;

index rs for rf;
index rt for rf;
index rd for rf;

rs = instr[25:21];
rt = instr[20:16];
rd = instr[15:11];

r1 = rf[rs];
r2 = rf[rt];

res = r1 + r2;

rf[rd] = res;
pc = pc + 4;
"""

EXAMPLE_LOAD = """
isa_state rf[31:0][4:0];
isa_state dmem[31:0][9:0];
isa_state pc[31:0];

var rs;
var rt;
var offset;
var addr;
var data;

index rs for rf;
index rt for rf;
index addr for dmem;

rs = instr[25:21];
rt = instr[20:16];
offset = instr[15:0];

addr = rf[rs] + offset;
data = dmem[addr];
rf[rt] = data;

pc = pc + 4;
"""


# JavaScript API functions
def create_graph_from_isa(isa_text: str) -> str:
    """Create a ResourceGraph from ISA text and return JSON."""
    try:
        graph = ResourceGraph.from_isa_text(isa_text)
        return json.dumps({
            'success': True,
            'graph': graph.to_dict(),
            'stats': {
                'nodes': len(graph.nodes),
                'edges': len(graph.edges)
            }
        })
    except Exception as e:
        return json.dumps({
            'success': False,
            'error': str(e)
        })


def get_example_isa(name: str) -> str:
    """Get an example ISA specification."""
    examples = {
        'add': EXAMPLE_ADD,
        'load': EXAMPLE_LOAD
    }
    return examples.get(name, EXAMPLE_ADD)


def optimize_graph(graph_json: str, optimization: str) -> str:
    """Apply an optimization to a graph (placeholder for future features)."""
    return json.dumps({
        'success': False,
        'error': 'Optimizations not yet implemented in WASM version'
    })


# For testing in Python environment
def main():
    """Test the WASM core functionality."""
    print("=== isacomp WASM Core Test ===\n")

    print("Creating graph from example ADD instruction:")
    result = create_graph_from_isa(EXAMPLE_ADD)
    data = json.loads(result)

    if data['success']:
        print(f"✓ Success! Created graph with {data['stats']['nodes']} nodes and {data['stats']['edges']} edges")
        print("\nNodes:")
        for node in data['graph']['nodes']:
            print(f"  - {node['display_name']} ({node['type']})")
    else:
        print(f"✗ Error: {data['error']}")


if __name__ == '__main__':
    main()
