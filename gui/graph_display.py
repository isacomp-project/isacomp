from typing import Dict, List, Set, Tuple
from core.resource_graph import ResourceGraph, Node, Edge


class ASCIIGraphDisplay:
    """ASCII terminal visualization for ResourceGraph."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph
        self.node_positions: Dict[str, Tuple[int, int]] = {}
        self.grid: List[List[str]] = []
        self.grid_width = 0
        self.grid_height = 0

    def display(self, show_node_details: bool = True, show_edge_details: bool = False) -> str:
        """Generate ASCII representation of the resource graph."""
        if not self.graph.nodes:
            return "Empty graph"

        # Calculate layout
        self._calculate_layout()

        # Create grid
        self._create_grid()

        # Place nodes
        self._place_nodes()

        # Draw edges
        self._draw_edges()

        # Convert grid to string
        result = self._grid_to_string()

        if show_node_details:
            result += "\n\n" + self._get_node_legend()

        if show_edge_details:
            result += "\n\n" + self._get_edge_legend()

        return result

    def _calculate_layout(self):
        """Calculate positions for nodes using a simple layered approach."""
        # Group nodes by type and dependencies
        layers = self._calculate_layers()

        # Position nodes in layers
        max_width = max(len(layer) for layer in layers) if layers else 1
        self.grid_width = max(80, max_width * 15)  # Min 80 chars, 15 chars per node
        self.grid_height = len(layers) * 4 + 2  # 4 rows per layer + padding

        for layer_idx, layer in enumerate(layers):
            y = layer_idx * 4 + 2
            layer_width = len(layer)
            if layer_width == 1:
                x = self.grid_width // 2
                self.node_positions[layer[0]] = (x, y)
            else:
                spacing = min(15, (self.grid_width - 20) // max(1, layer_width - 1))
                start_x = 10
                for i, node_id in enumerate(layer):
                    x = start_x + i * spacing
                    self.node_positions[node_id] = (x, y)

    def _calculate_layers(self) -> List[List[str]]:
        """Calculate topological layers for layout."""
        # Simple heuristic: group by node type and dependencies
        layers = []

        # Layer 0: ISA state nodes (architectural state)
        isa_state_nodes = [node_id for node_id, node in self.graph.nodes.items()
                          if node.is_arch_state]
        if isa_state_nodes:
            layers.append(isa_state_nodes)

        # Layer 1: Variables and inputs
        var_nodes = [node_id for node_id, node in self.graph.nodes.items()
                    if not node.is_arch_state and
                    node.data.get('type') in ['var', 'temp_var'] and
                    len(node.incoming_edges) == 0]
        if var_nodes:
            layers.append(var_nodes)

        # Layer 2: Array accesses and bit slices
        access_nodes = [node_id for node_id, node in self.graph.nodes.items()
                       if node.data.get('type') in ['array_access', 'bit_slice']]
        if access_nodes:
            layers.append(access_nodes)

        # Layer 3: Operations
        op_nodes = [node_id for node_id, node in self.graph.nodes.items()
                   if node.data.get('type') == 'operation']
        if op_nodes:
            layers.append(op_nodes)

        # Layer 4: Literals and remaining nodes
        remaining_nodes = [node_id for node_id, node in self.graph.nodes.items()
                          if node_id not in [n for layer in layers for n in layer]]
        if remaining_nodes:
            layers.append(remaining_nodes)

        return layers

    def _create_grid(self):
        """Initialize the character grid."""
        self.grid = [[' ' for _ in range(self.grid_width)] for _ in range(self.grid_height)]

    def _place_nodes(self):
        """Place node representations on the grid."""
        for node_id, (x, y) in self.node_positions.items():
            node = self.graph.nodes[node_id]
            display_name = node.data.get('display_name', node_id)

            # Truncate long names
            if len(display_name) > 12:
                display_name = display_name[:9] + "..."

            # Choose node symbol based on type
            if node.is_arch_state:
                symbol = "█"  # Solid block for ISA state
            elif node.is_uarch_state:
                symbol = "▣"  # Solid square for uarch state
            elif node.data.get('type') == 'operation':
                symbol = "◊"  # Diamond for operations
            elif node.data.get('type') == 'literal':
                symbol = "○"  # Circle for literals
            else:
                symbol = "□"  # Square for variables/temps

            # Place the node symbol and name
            if 0 <= y < self.grid_height and 0 <= x < self.grid_width:
                self.grid[y][x] = symbol

                # Place the name below the symbol
                name_y = y + 1
                if name_y < self.grid_height:
                    start_x = max(0, x - len(display_name) // 2)
                    for i, char in enumerate(display_name):
                        pos_x = start_x + i
                        if pos_x < self.grid_width:
                            self.grid[name_y][pos_x] = char

    def _draw_edges(self):
        """Draw edges between nodes."""
        for edge in self.graph.edges.values():
            source_pos = self.node_positions.get(edge.source.id)
            target_pos = self.node_positions.get(edge.target.id)

            if source_pos and target_pos:
                self._draw_line(source_pos, target_pos, edge)

    def _draw_line(self, start: Tuple[int, int], end: Tuple[int, int], edge: Edge):
        """Draw a line between two points."""
        x1, y1 = start
        x2, y2 = end

        # Simple line drawing - vertical then horizontal
        if y1 == y2:  # Horizontal line
            min_x, max_x = min(x1, x2), max(x1, x2)
            for x in range(min_x + 1, max_x):
                if 0 <= y1 < self.grid_height and 0 <= x < self.grid_width:
                    if self.grid[y1][x] == ' ':
                        self.grid[y1][x] = '─'
        elif x1 == x2:  # Vertical line
            min_y, max_y = min(y1, y2), max(y1, y2)
            for y in range(min_y + 1, max_y):
                if 0 <= y < self.grid_height and 0 <= x1 < self.grid_width:
                    if self.grid[y][x1] == ' ':
                        self.grid[y][x1] = '│'
        else:  # L-shaped line
            # Vertical part
            if y1 < y2:
                for y in range(y1 + 1, y2):
                    if 0 <= y < self.grid_height and 0 <= x1 < self.grid_width:
                        if self.grid[y][x1] == ' ':
                            self.grid[y][x1] = '│'
                # Corner
                if 0 <= y2 < self.grid_height and 0 <= x1 < self.grid_width:
                    if self.grid[y2][x1] == ' ':
                        self.grid[y2][x1] = '└' if x2 > x1 else '┘'
                # Horizontal part
                min_x, max_x = min(x1, x2), max(x1, x2)
                for x in range(min_x + 1, max_x):
                    if 0 <= y2 < self.grid_height and 0 <= x < self.grid_width:
                        if self.grid[y2][x] == ' ':
                            self.grid[y2][x] = '─'
            else:  # y1 > y2
                for y in range(y2 + 1, y1):
                    if 0 <= y < self.grid_height and 0 <= x1 < self.grid_width:
                        if self.grid[y][x1] == ' ':
                            self.grid[y][x1] = '│'
                # Corner
                if 0 <= y2 < self.grid_height and 0 <= x1 < self.grid_width:
                    if self.grid[y2][x1] == ' ':
                        self.grid[y2][x1] = '┌' if x2 > x1 else '┐'
                # Horizontal part
                min_x, max_x = min(x1, x2), max(x1, x2)
                for x in range(min_x + 1, max_x):
                    if 0 <= y2 < self.grid_height and 0 <= x < self.grid_width:
                        if self.grid[y2][x] == ' ':
                            self.grid[y2][x] = '─'

        # Add arrow at the end
        if 0 <= y2 < self.grid_height and 0 <= x2 < self.grid_width:
            if x1 < x2:
                arrow = '→'
            elif x1 > x2:
                arrow = '←'
            elif y1 < y2:
                arrow = '↓'
            else:
                arrow = '↑'

            # Place arrow near the target, but not on it
            if x1 != x2:
                arrow_x = x2 - 1 if x1 < x2 else x2 + 1
                if 0 <= arrow_x < self.grid_width and self.grid[y2][arrow_x] == '─':
                    self.grid[y2][arrow_x] = arrow
            elif y1 != y2:
                arrow_y = y2 - 1 if y1 < y2 else y2 + 1
                if 0 <= arrow_y < self.grid_height and self.grid[arrow_y][x2] == '│':
                    self.grid[arrow_y][x2] = arrow

    def _grid_to_string(self) -> str:
        """Convert the character grid to a string."""
        lines = []
        for row in self.grid:
            line = ''.join(row).rstrip()
            lines.append(line)

        # Remove trailing empty lines
        while lines and not lines[-1]:
            lines.pop()

        return '\n'.join(lines)

    def _get_node_legend(self) -> str:
        """Generate a legend for node types."""
        legend = "Node Legend:\n"
        legend += "  █ ISA State (architectural state)\n"
        legend += "  ▣ Microarchitectural State (uarch state)\n"
        legend += "  □ Variables / Temporary values\n"
        legend += "  ◊ Operations\n"
        legend += "  ○ Literal values\n"

        # Add node details
        legend += "\nNodes:\n"
        for node_id, node in self.graph.nodes.items():
            display_name = node.data.get('display_name', node_id)
            node_type = node.data.get('type', 'unknown')
            arch_indicator = " [ARCH]" if node.is_arch_state else ""
            uarch_indicator = " [UARCH]" if node.is_uarch_state else ""
            time_indicator = f" [T{node.uarch_time}]" if node.uarch_time is not None else " [T?]"
            index_indicator = " [INDEX]" if node.used_as_index else ""
            indexed_by_indicator = f" [INDEXED_BY: {node.indexed_by.id}]" if node.indexed_by else ""
            legend += f"  {display_name}: {node_type}{arch_indicator}{uarch_indicator}{time_indicator}{index_indicator}{indexed_by_indicator}\n"

        return legend

    def display_by_time(self) -> str:
        """Display nodes grouped by their uarch_time."""
        if not self.graph.nodes:
            return "Empty graph"

        result = "Nodes by Microarchitectural Time:\n"
        result += "=" * 40 + "\n\n"

        max_time = max((node.uarch_time for node in self.graph.nodes.values() if node.uarch_time is not None), default=0)

        for time in range(max_time + 1):
            nodes_at_time = [node for node in self.graph.nodes.values() if node.uarch_time == time]
            if nodes_at_time:
                result += f"Time {time}:\n"
                for node in nodes_at_time:
                    display_name = node.data.get('display_name', node.id)
                    node_type = node.data.get('type', 'unknown')

                    # Choose symbol
                    if node.is_arch_state:
                        symbol = "█"
                    elif node.is_uarch_state:
                        symbol = "▣"
                    elif node.data.get('type') == 'operation':
                        symbol = "◊"
                    elif node.data.get('type') == 'literal':
                        symbol = "○"
                    else:
                        symbol = "□"

                    result += f"  {symbol} {display_name} ({node_type})\n"
                result += "\n"

        return result

    def _get_edge_legend(self) -> str:
        """Generate a legend for edge types."""
        legend = "Edges:\n"
        edge_types = set()
        for edge in self.graph.edges.values():
            edge_type = edge.data.get('type', 'unknown')
            edge_types.add(edge_type)
            source_name = edge.source.data.get('display_name', edge.source.id)
            target_name = edge.target.data.get('display_name', edge.target.id)
            legend += f"  {source_name} → {target_name} ({edge_type})\n"

        return legend

    def display_simple(self) -> str:
        """Generate a simple text-based representation."""
        if not self.graph.nodes:
            return "Empty graph"

        result = "Resource Graph:\n"
        result += "=" * 50 + "\n\n"

        # Show nodes by type
        isa_nodes = [n for n in self.graph.nodes.values() if n.is_arch_state]
        if isa_nodes:
            result += "ISA State Nodes:\n"
            for node in isa_nodes:
                display_name = node.data.get('display_name', node.id)
                result += f"  █ {display_name}\n"
            result += "\n"

        var_nodes = [n for n in self.graph.nodes.values() if not n.is_arch_state and n.data.get('type') in ['var', 'temp_var']]
        if var_nodes:
            result += "Variables:\n"
            for node in var_nodes:
                display_name = node.data.get('display_name', node.id)
                result += f"  □ {display_name}\n"
            result += "\n"

        op_nodes = [n for n in self.graph.nodes.values() if n.data.get('type') == 'operation']
        if op_nodes:
            result += "Operations:\n"
            for node in op_nodes:
                display_name = node.data.get('display_name', node.id)
                result += f"  ◊ {display_name}\n"
            result += "\n"

        other_nodes = [n for n in self.graph.nodes.values() if n.data.get('type') not in ['var', 'temp_var', 'operation'] and not n.is_arch_state]
        if other_nodes:
            result += "Other Nodes:\n"
            for node in other_nodes:
                display_name = node.data.get('display_name', node.id)
                node_type = node.data.get('type', 'unknown')
                result += f"  ○ {display_name} ({node_type})\n"
            result += "\n"

        # Show key relationships
        result += "Data Flow:\n"
        assignment_edges = [e for e in self.graph.edges.values() if e.data.get('type') == 'assignment']
        for edge in assignment_edges:
            source_name = edge.source.data.get('display_name', edge.source.id)
            target_name = edge.target.data.get('display_name', edge.target.id)
            result += f"  {source_name} → {target_name}\n"

        return result