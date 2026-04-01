#!/usr/bin/env python3
"""
Advanced graph layout algorithms for ResourceGraph visualization.

This module provides various layout algorithms to arrange nodes in a
visually appealing and informative way.
"""

import math
import random
from typing import Dict, List, Tuple, Set, Optional
from dataclasses import dataclass

from core.resource_graph import ResourceGraph, Node, Edge


@dataclass
class Point:
    """2D point with x, y coordinates."""
    x: float
    y: float


@dataclass
class Rectangle:
    """Rectangle defined by top-left corner and dimensions."""
    x: float
    y: float
    width: float
    height: float

    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)

    def contains(self, point: Point) -> bool:
        return (self.x <= point.x <= self.x + self.width and
                self.y <= point.y <= self.y + self.height)


class GraphLayoutEngine:
    """Advanced layout algorithms for ResourceGraphs."""

    def __init__(self, canvas_width: int = 800, canvas_height: int = 600):
        self.canvas_width = canvas_width
        self.canvas_height = canvas_height
        self.margin = 50

    def hierarchical_layout(self, graph: ResourceGraph) -> Dict[str, Point]:
        """
        Create a hierarchical layout based on uarch_time levels.
        Groups nodes by their execution time and arranges them in levels.
        """
        if not graph.nodes:
            return {}

        # Group nodes by uarch_time
        time_levels: Dict[int, List[Node]] = {}
        max_time = 0

        for node in graph.nodes.values():
            time = node.uarch_time if node.uarch_time is not None else 0
            max_time = max(max_time, time)

            if time not in time_levels:
                time_levels[time] = []
            time_levels[time].append(node)

        positions = {}
        available_height = self.canvas_height - 2 * self.margin
        available_width = self.canvas_width - 2 * self.margin

        if max_time == 0:
            # Single level - use circular layout
            return self._circular_layout(list(graph.nodes.values()))

        # Calculate vertical positions for each time level
        level_height = available_height / (max_time + 1)

        for time_level, nodes in time_levels.items():
            y = self.margin + time_level * level_height

            # Sort nodes by type for better organization within each level
            sorted_nodes = sorted(nodes, key=lambda n: (
                n.data.get('type', 'z'),  # Sort by type
                n.data.get('shared_resource', False),  # Shared resources last
                n.id  # Then by ID for consistency
            ))

            # Arrange nodes horizontally within each level
            if len(sorted_nodes) == 1:
                x = self.canvas_width / 2
                positions[sorted_nodes[0].id] = Point(x, y)
            else:
                # Increase spacing between nodes to avoid label overlap
                min_node_spacing = 120  # Minimum pixels between node centers
                node_width = max(min_node_spacing, available_width / len(sorted_nodes))
                total_width = node_width * len(sorted_nodes)
                start_x = (self.canvas_width - total_width) / 2
                for i, node in enumerate(sorted_nodes):
                    x = start_x + (i + 0.5) * node_width
                    positions[node.id] = Point(x, y)

        return positions

    def force_directed_layout(self, graph: ResourceGraph, iterations: int = 200) -> Dict[str, Point]:
        """
        Create a force-directed layout using a spring model.
        Nodes repel each other, but connected nodes attract.
        """
        if not graph.nodes:
            return {}

        # Initialize with random positions
        positions = {}
        for node_id in graph.nodes:
            positions[node_id] = Point(
                random.uniform(self.margin, self.canvas_width - self.margin),
                random.uniform(self.margin, self.canvas_height - self.margin)
            )

        # Force-directed algorithm parameters
        # Increase k to provide more spacing between nodes (multiplier of 1.8 gives better label readability)
        k = 1.8 * math.sqrt((self.canvas_width * self.canvas_height) / len(graph.nodes))  # Optimal distance
        area = self.canvas_width * self.canvas_height

        for iteration in range(iterations):
            # Calculate forces for each node
            forces = {node_id: Point(0, 0) for node_id in graph.nodes}

            # Repulsive forces between all pairs of nodes
            nodes = list(graph.nodes.keys())
            for i in range(len(nodes)):
                for j in range(i + 1, len(nodes)):
                    node1, node2 = nodes[i], nodes[j]
                    pos1, pos2 = positions[node1], positions[node2]

                    dx = pos1.x - pos2.x
                    dy = pos1.y - pos2.y
                    distance = math.sqrt(dx*dx + dy*dy)

                    if distance > 0:
                        # Coulomb's law: repulsive force
                        force_magnitude = k*k / distance
                        fx = force_magnitude * dx / distance
                        fy = force_magnitude * dy / distance

                        forces[node1].x += fx
                        forces[node1].y += fy
                        forces[node2].x -= fx
                        forces[node2].y -= fy

            # Attractive forces between connected nodes
            for edge in graph.edges.values():
                source_id = edge.source.id
                target_id = edge.target.id

                pos1 = positions[source_id]
                pos2 = positions[target_id]

                dx = pos1.x - pos2.x
                dy = pos1.y - pos2.y
                distance = math.sqrt(dx*dx + dy*dy)

                if distance > 0:
                    # Hooke's law: attractive force
                    force_magnitude = distance*distance / k
                    fx = force_magnitude * dx / distance
                    fy = force_magnitude * dy / distance

                    forces[source_id].x -= fx
                    forces[source_id].y -= fy
                    forces[target_id].x += fx
                    forces[target_id].y += fy

            # Apply forces with simulated annealing
            temperature = k * math.sqrt(area) / 10 * (1 - iteration / iterations)

            for node_id in graph.nodes:
                force_x = forces[node_id].x
                force_y = forces[node_id].y
                force_magnitude = math.sqrt(force_x*force_x + force_y*force_y)

                if force_magnitude > 0:
                    # Limit displacement by temperature
                    displacement = min(force_magnitude, temperature)
                    positions[node_id].x += force_x / force_magnitude * displacement
                    positions[node_id].y += force_y / force_magnitude * displacement

                    # Keep nodes within canvas bounds
                    positions[node_id].x = max(self.margin, min(self.canvas_width - self.margin, positions[node_id].x))
                    positions[node_id].y = max(self.margin, min(self.canvas_height - self.margin, positions[node_id].y))

        return positions

    def layered_layout(self, graph: ResourceGraph) -> Dict[str, Point]:
        """
        Create a layered layout suitable for pipeline visualizations.
        Separates different types of components into distinct layers.
        """
        if not graph.nodes:
            return {}

        # Classify nodes into layers
        layers = {
            'input': [],      # Input nodes (no incoming edges)
            'isa_state': [],  # ISA state nodes
            'operations': [], # Computation nodes
            'pipeline': [],   # Pipeline components
            'output': []      # Output nodes (no outgoing edges)
        }

        for node in graph.nodes.values():
            node_type = node.data.get('type', '')

            if not node.incoming_edges:
                layers['input'].append(node)
            elif not node.outgoing_edges:
                layers['output'].append(node)
            elif node_type == 'isa_state':
                layers['isa_state'].append(node)
            elif 'pipeline' in node_type or 'hazard' in node_type:
                layers['pipeline'].append(node)
            else:
                layers['operations'].append(node)

        # Remove empty layers
        layers = {name: nodes for name, nodes in layers.items() if nodes}

        positions = {}
        layer_names = list(layers.keys())
        layer_width = (self.canvas_width - 2 * self.margin) / len(layer_names)

        for i, (layer_name, nodes) in enumerate(layers.items()):
            x_center = self.margin + (i + 0.5) * layer_width

            # Arrange nodes vertically within the layer
            if len(nodes) == 1:
                y = self.canvas_height / 2
                positions[nodes[0].id] = Point(x_center, y)
            else:
                available_height = self.canvas_height - 2 * self.margin
                # Increase minimum spacing to avoid label overlap
                min_node_spacing = 80  # Minimum pixels between node centers vertically
                node_spacing = max(min_node_spacing, available_height / (len(nodes) + 1))

                for j, node in enumerate(nodes):
                    y = self.margin + (j + 1) * node_spacing
                    positions[node.id] = Point(x_center, y)

        return positions

    def circular_layout(self, graph: ResourceGraph) -> Dict[str, Point]:
        """Create a circular layout with all nodes arranged in a circle."""
        if not graph.nodes:
            return {}

        return self._circular_layout(list(graph.nodes.values()))

    def _circular_layout(self, nodes: List[Node]) -> Dict[str, Point]:
        """Helper method for circular layout."""
        positions = {}

        if not nodes:
            return positions

        center_x = self.canvas_width / 2
        center_y = self.canvas_height / 2
        radius = min(center_x, center_y) - self.margin - 50

        for i, node in enumerate(nodes):
            angle = 2 * math.pi * i / len(nodes)
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            positions[node.id] = Point(x, y)

        return positions

    def grid_layout(self, graph: ResourceGraph) -> Dict[str, Point]:
        """Arrange nodes in a regular grid pattern."""
        if not graph.nodes:
            return {}

        nodes = list(graph.nodes.values())
        num_nodes = len(nodes)

        # Calculate grid dimensions
        cols = int(math.ceil(math.sqrt(num_nodes)))
        rows = int(math.ceil(num_nodes / cols))

        positions = {}
        available_width = self.canvas_width - 2 * self.margin
        available_height = self.canvas_height - 2 * self.margin

        cell_width = available_width / cols
        cell_height = available_height / rows

        for i, node in enumerate(nodes):
            row = i // cols
            col = i % cols

            x = self.margin + (col + 0.5) * cell_width
            y = self.margin + (row + 0.5) * cell_height

            positions[node.id] = Point(x, y)

        return positions

    def pipeline_layout(self, graph: ResourceGraph) -> Dict[str, Point]:
        """
        Specialized layout for pipelined processor graphs.
        Arranges pipeline stages horizontally and components vertically.
        """
        if not graph.nodes:
            return {}

        # Group nodes by pipeline stage
        stages = {}
        non_pipeline_nodes = []

        for node in graph.nodes.values():
            stage_name = node.data.get('stage_name')
            if stage_name:
                if stage_name not in stages:
                    stages[stage_name] = []
                stages[stage_name].append(node)
            else:
                non_pipeline_nodes.append(node)

        positions = {}

        if not stages:
            # No pipeline stages found, use hierarchical layout
            return self.hierarchical_layout(graph)

        # Sort stages by name to get consistent ordering
        stage_names = sorted(stages.keys())
        num_stages = len(stage_names)

        stage_width = (self.canvas_width - 2 * self.margin) / (num_stages + 1)

        # Position pipeline stages
        for i, stage_name in enumerate(stage_names):
            stage_nodes = stages[stage_name]
            x_center = self.margin + (i + 1) * stage_width

            # Arrange nodes vertically within each stage
            if len(stage_nodes) == 1:
                y = self.canvas_height / 2
                positions[stage_nodes[0].id] = Point(x_center, y)
            else:
                available_height = self.canvas_height - 2 * self.margin
                # Increase minimum spacing to avoid label overlap
                min_node_spacing = 80  # Minimum pixels between node centers vertically
                node_spacing = max(min_node_spacing, available_height / (len(stage_nodes) + 1))

                for j, node in enumerate(stage_nodes):
                    y = self.margin + (j + 1) * node_spacing
                    positions[node.id] = Point(x_center, y)

        # Position non-pipeline nodes in the leftmost area
        if non_pipeline_nodes:
            x_center = self.margin + 0.5 * stage_width

            if len(non_pipeline_nodes) == 1:
                y = self.canvas_height / 2
                positions[non_pipeline_nodes[0].id] = Point(x_center, y)
            else:
                available_height = self.canvas_height - 2 * self.margin
                # Increase minimum spacing to avoid label overlap
                min_node_spacing = 80  # Minimum pixels between node centers vertically
                node_spacing = max(min_node_spacing, available_height / (len(non_pipeline_nodes) + 1))

                for j, node in enumerate(non_pipeline_nodes):
                    y = self.margin + (j + 1) * node_spacing
                    positions[node.id] = Point(x_center, y)

        return positions

    def timeline_layout(self, graph: ResourceGraph) -> Dict[str, Point]:
        """
        Create a timeline layout that clearly shows execution timing.
        Arranges nodes in a timeline with time flowing left to right.
        """
        if not graph.nodes:
            return {}

        # Group nodes by uarch_time, treating None as time 0
        time_levels: Dict[int, List[Node]] = {}
        max_time = 0

        for node in graph.nodes.values():
            time = node.uarch_time if node.uarch_time is not None else 0
            max_time = max(max_time, time)

            if time not in time_levels:
                time_levels[time] = []
            time_levels[time].append(node)

        positions = {}
        available_width = self.canvas_width - 2 * self.margin
        available_height = self.canvas_height - 2 * self.margin

        if max_time == 0:
            # All nodes at same time - use layered layout
            return self.layered_layout(graph)

        # Calculate horizontal positions for each time level (left to right timeline)
        time_width = available_width / (max_time + 1)

        for time_level, nodes in time_levels.items():
            x = self.margin + time_level * time_width + time_width / 2

            # Group nodes by type within each time level
            node_groups = {}
            for node in nodes:
                node_type = node.data.get('type', 'other')
                if node_type not in node_groups:
                    node_groups[node_type] = []
                node_groups[node_type].append(node)

            # Calculate vertical spacing for groups
            total_groups = len(node_groups)
            group_height = available_height / total_groups if total_groups > 0 else available_height

            group_index = 0
            for group_type, group_nodes in sorted(node_groups.items()):
                group_y_center = self.margin + (group_index + 0.5) * group_height

                # Arrange nodes within group vertically
                if len(group_nodes) == 1:
                    y = group_y_center
                    positions[group_nodes[0].id] = Point(x, y)
                else:
                    # Spread nodes vertically within group
                    node_spacing = min(group_height * 0.8, 40 * len(group_nodes)) / len(group_nodes)
                    start_y = group_y_center - (len(group_nodes) - 1) * node_spacing / 2

                    for i, node in enumerate(group_nodes):
                        y = start_y + i * node_spacing
                        positions[node.id] = Point(x, y)

                group_index += 1

        return positions

    def architectural_layout(self, graph: ResourceGraph) -> Dict[str, Point]:
        """
        Layout based on architectural knowledge with vertical time-based regions.

        - Time flows left-to-right (time 0 on left, time 1 to the right, etc.)
        - Within each time region: reads on top, logic in middle, writes on bottom
        - Within each section, arranges nodes by dependency order
        - Arch_state sources are placed to the left of their _rd nodes
        """
        if not graph.nodes:
            return {}

        positions = {}

        # Group nodes by uarch_time
        time_groups = {}
        for node in graph.nodes.values():
            time = node.uarch_time if node.uarch_time is not None else 0
            if time not in time_groups:
                time_groups[time] = []
            time_groups[time].append(node)

        times = sorted(time_groups.keys())
        num_times = len(times)

        if num_times == 0:
            return {}

        # Calculate minimum region width based on max nodes per layer
        # Each node needs at least 50px spacing to avoid overlap (radius=20)
        min_node_spacing = 50
        max_nodes_per_layer = 1
        for time in times:
            nodes_in_region = time_groups[time]
            # Count nodes by category to estimate max per layer
            num_reads = sum(1 for n in nodes_in_region if n.id.endswith('_rd') or n.is_arch_state)
            num_writes = sum(1 for n in nodes_in_region if n.id.endswith('_wr'))
            num_logic = len(nodes_in_region) - num_reads - num_writes
            max_nodes_per_layer = max(max_nodes_per_layer, num_reads, num_writes, num_logic)

        # Ensure region is wide enough to fit all nodes without overlap
        min_region_width = max_nodes_per_layer * min_node_spacing * 1.2  # 20% padding

        # Calculate horizontal region boundaries (time flows left-to-right)
        available_width = self.canvas_width - 2 * self.margin
        region_width = max(min_region_width, available_width / num_times)

        # Process each time region
        for time_idx, time in enumerate(times):
            nodes_in_region = time_groups[time]

            # Calculate horizontal center for this time region
            region_x_center = self.margin + (time_idx + 0.5) * region_width

            # Split nodes into three categories: reads, writes, logic
            reads = []  # _rd nodes and their arch_state sources
            writes = []  # _wr nodes
            logic = []  # everything else

            for node in nodes_in_region:
                if node.id.endswith('_rd'):
                    reads.append(node)
                    # Also include arch_state that feeds this read
                    for edge in node.incoming_edges:
                        if edge.source.is_arch_state and edge.source in nodes_in_region:
                            if edge.source not in reads:
                                reads.append(edge.source)
                elif node.id.endswith('_wr'):
                    writes.append(node)
                elif node.is_arch_state:
                    # Only add arch_state to reads if not already added
                    if node not in reads:
                        reads.append(node)
                else:
                    logic.append(node)

            # Compute dependency layers for each section
            read_layers = self._compute_dependency_layers(graph, reads) if reads else []
            logic_layers = self._compute_dependency_layers(graph, logic) if logic else []
            write_layers = self._compute_dependency_layers(graph, writes) if writes else []

            # Calculate vertical space allocation
            available_height = self.canvas_height - 2 * self.margin
            num_read_layers = len(read_layers)
            num_logic_layers = len(logic_layers)
            num_write_layers = len(write_layers)
            total_layers = num_read_layers + num_logic_layers + num_write_layers

            if total_layers == 0:
                continue

            # Allocate space proportionally, but enforce minimum spacing to avoid overlap
            # Minimum layer height must be at least 2*node_radius (40px) + padding = 50px
            min_layer_height = 50  # Minimum to avoid vertical node overlap (radius=20)
            layer_height = max(min_layer_height, available_height / max(total_layers, 1))

            # Position read layers (top)
            layer_offset = 0
            for layer_idx, layer_nodes in enumerate(read_layers):
                layer_y = self.margin + (layer_offset + layer_idx + 0.5) * layer_height
                self._position_layer_vertical(layer_nodes, region_x_center, layer_y, region_width, positions)
            layer_offset += num_read_layers

            # Position logic layers (middle)
            for layer_idx, layer_nodes in enumerate(logic_layers):
                layer_y = self.margin + (layer_offset + layer_idx + 0.5) * layer_height
                self._position_layer_vertical(layer_nodes, region_x_center, layer_y, region_width, positions)
            layer_offset += num_logic_layers

            # Position write layers (bottom)
            for layer_idx, layer_nodes in enumerate(write_layers):
                layer_y = self.margin + (layer_offset + layer_idx + 0.5) * layer_height
                self._position_layer_vertical(layer_nodes, region_x_center, layer_y, region_width, positions)

        return positions

    def _position_layer_vertical(self, layer_nodes: List[Node], x_center: float, y: float,
                                 region_width: float, positions: Dict[str, Point]):
        """Helper to position nodes in a layer horizontally within a time region."""
        num_nodes = len(layer_nodes)
        if num_nodes == 1:
            positions[layer_nodes[0].id] = Point(x_center, y)
        else:
            # Spread nodes horizontally within the region
            # Minimum spacing must be at least 2*node_radius (40px) + padding to avoid overlap
            # Node radius is typically 20px, so use 50px minimum spacing
            min_spacing = 50  # Minimum to avoid circular node overlap (radius=20)
            # Constrain to stay within the region to avoid overlapping into adjacent time regions
            horizontal_spacing = max(min_spacing, min(region_width * 0.8 / max(1, num_nodes), 80))
            total_width = horizontal_spacing * num_nodes
            start_x = x_center - total_width / 2

            for i, node in enumerate(sorted(layer_nodes, key=lambda n: n.id)):
                x = start_x + (i + 0.5) * horizontal_spacing
                positions[node.id] = Point(x, y)

    def _compute_dependency_layers(self, graph: ResourceGraph, nodes: List[Node]) -> List[List[Node]]:
        """
        Compute dependency-based layers for nodes using topological sort.
        Nodes with no dependencies (or satisfied dependencies) go in earlier layers.
        """
        node_set = set(n.id for n in nodes)
        layers = []
        remaining = set(nodes)
        layer_map = {}  # node_id -> layer_index

        while remaining:
            current_layer = []

            for node in list(remaining):
                # Check if dependencies are satisfied
                dependencies_satisfied = True
                for edge in node.incoming_edges:
                    source = edge.source
                    # Only consider dependencies within this node set
                    if source.id in node_set:
                        # If source hasn't been placed yet, dependency not satisfied
                        if source.id not in layer_map:
                            dependencies_satisfied = False
                            break

                if dependencies_satisfied:
                    current_layer.append(node)

            # If no nodes can be placed, break to avoid infinite loop
            if not current_layer:
                # Place remaining nodes (handles cycles or disconnected nodes)
                current_layer = list(remaining)

            # Assign layer index
            for node in current_layer:
                layer_map[node.id] = len(layers)
                remaining.discard(node)

            layers.append(current_layer)

        return layers

    def pipeline_viewer_layout(self, graph: ResourceGraph) -> Dict[str, Point]:
        """
        Specialized pipeline viewer layout with schematic-style presentation.

        - Pipeline registers positioned between stages
        - Logic within stages organized left-to-right by depth
        - Canvas expands to avoid node overlaps
        - Suitable for horizontal scrolling
        """
        if not graph.nodes:
            return {}

        # Group nodes by pipeline stage (uarch_time)
        stage_groups = {}
        pipeline_regs = {}  # Pipeline registers between stages

        for node in graph.nodes.values():
            time = node.uarch_time if node.uarch_time is not None else 0

            # Check if this is a pipeline register or control node (between stages)
            node_type = node.data.get('type', '').lower()
            node_id = node.id.lower()
            display_name = node.data.get('display_name', '').lower()

            # Detect pipeline registers and control nodes by various heuristics
            is_pipeline_reg = (
                'pipeline' in node_type or
                node_type == 'uarch_state' or
                node.is_uarch_state or
                'stall' in node_id or
                'stall' in display_name or
                'control' in node_id or
                '_reg' in node_id or
                node_id.endswith('_r') or
                'hazard' in node_type or
                'enable' in node_id
            )

            if is_pipeline_reg:
                # Pipeline registers are placed between their source and target stages
                if node.incoming_edges:
                    # Use the source stage (max of all input stages)
                    source_time = max((e.source.uarch_time if e.source.uarch_time is not None else 0)
                                    for e in node.incoming_edges)
                    target_time = time
                    reg_pos = (source_time, target_time)
                    if reg_pos not in pipeline_regs:
                        pipeline_regs[reg_pos] = []
                    pipeline_regs[reg_pos].append(node)
                    continue

            if time not in stage_groups:
                stage_groups[time] = []
            stage_groups[time].append(node)

        positions = {}

        # Node dimensions for overlap avoidance
        node_width = 100  # Horizontal space per node
        node_height = 80  # Vertical space per node
        stage_logic_margin = 50  # Space after combinational logic before registers
        register_margin = 100  # Space for registers between stages

        stages = sorted(stage_groups.keys())
        current_x = self.margin

        for stage_idx, stage in enumerate(stages):
            stage_nodes = stage_groups[stage]

            # Compute depth of each node within this stage
            # Depth = longest path from stage inputs
            node_depths = self._compute_node_depths_in_stage(graph, stage_nodes, stage)

            # Group nodes by depth
            depth_groups = {}
            for node in stage_nodes:
                depth = node_depths[node.id]
                if depth not in depth_groups:
                    depth_groups[depth] = []
                depth_groups[depth].append(node)

            # Calculate actual width of combinational logic based on max depth
            max_depth = max(depth_groups.keys()) if depth_groups else 0
            stage_logic_width = (max_depth + 1) * node_width

            # Position nodes within stage by depth (left-to-right)
            for depth, nodes_at_depth in sorted(depth_groups.items()):
                x = current_x + depth * node_width + node_width // 2

                # Arrange nodes at this depth vertically
                # Increase vertical spacing to avoid overlaps
                start_y = self.margin + 50

                for i, node in enumerate(sorted(nodes_at_depth, key=lambda n: n.id)):
                    y = start_y + i * node_height
                    positions[node.id] = Point(x, y)

            # Move current_x to end of combinational logic
            current_x += stage_logic_width + stage_logic_margin

            # Position pipeline registers that come AFTER this stage
            # (i.e., registers whose source is this stage, regardless of target)
            regs_after_this_stage = []
            for reg_pos, regs in pipeline_regs.items():
                source_stage, target_stage = reg_pos
                if source_stage == stage:
                    regs_after_this_stage.extend(regs)

            if regs_after_this_stage:
                # Position all registers that originate from this stage
                reg_x = current_x

                for i, reg in enumerate(sorted(regs_after_this_stage, key=lambda n: n.id)):
                    y = self.margin + 50 + i * node_height
                    positions[reg.id] = Point(reg_x, y)

                # Move past the registers
                current_x += register_margin
            elif stage_idx < len(stages) - 1:
                # No registers after this stage, add some spacing before next stage
                current_x += 50

        # Handle any remaining pipeline registers that weren't positioned
        # This catches registers that don't fit the (source_stage, target_stage) pattern
        unpositioned_regs = []
        for reg_pos, regs in pipeline_regs.items():
            for reg in regs:
                if reg.id not in positions:
                    unpositioned_regs.append((reg, reg_pos))

        # Debug: Print info about unpositioned registers (only if small number)
        if unpositioned_regs and len(unpositioned_regs) <= 10:
            print(f"Warning: {len(unpositioned_regs)} pipeline registers couldn't be positioned between stages:")
            for reg, reg_pos in unpositioned_regs:
                print(f"  {reg.id}: time={reg.uarch_time}, reg_pos={reg_pos}, has_edges={bool(reg.incoming_edges)}")
            print(f"  Available stages: {stages}")
            print(f"  Pipeline reg positions: {list(pipeline_regs.keys())}")
        elif unpositioned_regs:
            print(f"Warning: {len(unpositioned_regs)} pipeline registers couldn't be positioned between stages (suppressing detailed output)")

        # Position them at the end as fallback
        for reg, _ in unpositioned_regs:
            positions[reg.id] = Point(current_x, self.margin + 50)
            current_x += node_width

        # Update canvas dimensions to fit all nodes
        if positions:
            max_x = max(pos.x for pos in positions.values()) + self.margin + 100
            max_y = max(pos.y for pos in positions.values()) + self.margin + 100
            self.canvas_width = max(self.canvas_width, int(max_x))
            self.canvas_height = max(self.canvas_height, int(max_y))

        return positions

    def _compute_node_depths_in_stage(self, graph: ResourceGraph, stage_nodes: List[Node],
                                     stage_time: int) -> Dict[str, int]:
        """
        Compute the depth of each node within a pipeline stage.
        Depth = longest path from stage inputs (nodes with no in-stage predecessors).
        Uses topological sort for O(V+E) performance.
        """
        from collections import deque

        node_set = {n.id for n in stage_nodes}
        node_map = {n.id: n for n in stage_nodes}
        depths = {}

        # Count in-stage predecessors for each node
        in_degree = {}
        for node in stage_nodes:
            in_stage_count = sum(1 for edge in node.incoming_edges if edge.source.id in node_set)
            in_degree[node.id] = in_stage_count

        # Start with nodes that have no in-stage predecessors (topological sort)
        queue = deque()
        for node in stage_nodes:
            if in_degree[node.id] == 0:
                depths[node.id] = 0
                queue.append(node)

        # Process nodes in topological order
        while queue:
            node = queue.popleft()
            current_depth = depths[node.id]

            # Update all successors within this stage
            for edge in node.outgoing_edges:
                successor = edge.target
                if successor.id in node_set:
                    # Update depth to maximum of all incoming paths
                    new_depth = current_depth + 1
                    if successor.id not in depths:
                        depths[successor.id] = new_depth
                    else:
                        depths[successor.id] = max(depths[successor.id], new_depth)

                    # Decrement in-degree and add to queue when all predecessors processed
                    in_degree[successor.id] -= 1
                    if in_degree[successor.id] == 0:
                        queue.append(successor)

        # Assign depth 0 to any nodes that weren't reached (cycles or disconnected)
        for node in stage_nodes:
            if node.id not in depths:
                depths[node.id] = 0

        return depths

    def smart_layout(self, graph: ResourceGraph) -> Dict[str, Point]:
        """
        Intelligently choose the best layout algorithm based on graph characteristics.
        """
        if not graph.nodes:
            return {}

        num_nodes = len(graph.nodes)

        # Check for pipeline stages
        has_pipeline_stages = any(node.data.get('stage_name') for node in graph.nodes.values())

        # Check for time-based structure
        has_time_structure = any(node.uarch_time is not None and node.uarch_time > 0
                               for node in graph.nodes.values())

        # Check if this looks like an ISA-based design (has _rd/_wr nodes)
        has_isa_reads_writes = any(node.id.endswith('_rd') or node.id.endswith('_wr')
                                   for node in graph.nodes.values())

        # Analyze graph connectivity
        total_edges = len(graph.edges)
        avg_degree = 2 * total_edges / num_nodes if num_nodes > 0 else 0

        # Choose layout algorithm
        # Prioritize architectural layout for ISA-based designs
        if has_isa_reads_writes:
            # Use architectural layout for ISA-based designs (handles both pipelined and non-pipelined)
            return self.architectural_layout(graph)
        elif has_pipeline_stages:
            # Only use pipeline layout for non-ISA designs with stages
            return self.pipeline_layout(graph)
        elif has_time_structure:
            return self.hierarchical_layout(graph)
        elif num_nodes <= 20 and avg_degree > 3:
            # Dense small graph - use force-directed
            return self.force_directed_layout(graph, iterations=100)
        elif num_nodes <= 10:
            # Very small graph - use circular
            return self.circular_layout(graph)
        else:
            # Large or sparse graph - use layered
            return self.layered_layout(graph)


class GraphLayoutOptimizer:
    """Optimize existing layouts by reducing edge crossings and improving aesthetics."""

    def __init__(self):
        pass

    def reduce_edge_crossings(self, graph: ResourceGraph, positions: Dict[str, Point]) -> Dict[str, Point]:
        """Reduce edge crossings by swapping node positions."""
        optimized_positions = positions.copy()

        # Simple heuristic: try swapping nodes and keep if it reduces crossings
        nodes = list(graph.nodes.keys())
        initial_crossings = self._count_edge_crossings(graph, optimized_positions)

        for _ in range(50):  # Limited iterations
            for i in range(len(nodes)):
                for j in range(i + 1, len(nodes)):
                    # Try swapping positions
                    node1, node2 = nodes[i], nodes[j]

                    # Swap
                    optimized_positions[node1], optimized_positions[node2] = \
                        optimized_positions[node2], optimized_positions[node1]

                    # Check if it's better
                    new_crossings = self._count_edge_crossings(graph, optimized_positions)

                    if new_crossings < initial_crossings:
                        initial_crossings = new_crossings
                    else:
                        # Revert swap
                        optimized_positions[node1], optimized_positions[node2] = \
                            optimized_positions[node2], optimized_positions[node1]

        return optimized_positions

    def _count_edge_crossings(self, graph: ResourceGraph, positions: Dict[str, Point]) -> int:
        """Count the number of edge crossings in the current layout."""
        edges = list(graph.edges.values())
        crossings = 0

        for i in range(len(edges)):
            for j in range(i + 1, len(edges)):
                edge1, edge2 = edges[i], edges[j]

                # Skip if edges share a node
                if (edge1.source.id == edge2.source.id or
                    edge1.source.id == edge2.target.id or
                    edge1.target.id == edge2.source.id or
                    edge1.target.id == edge2.target.id):
                    continue

                # Check if edges cross
                pos1_src = positions[edge1.source.id]
                pos1_tgt = positions[edge1.target.id]
                pos2_src = positions[edge2.source.id]
                pos2_tgt = positions[edge2.target.id]

                if self._lines_intersect(pos1_src, pos1_tgt, pos2_src, pos2_tgt):
                    crossings += 1

        return crossings

    def _lines_intersect(self, p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
        """Check if two line segments intersect."""
        def ccw(A, B, C):
            return (C.y - A.y) * (B.x - A.x) > (B.y - A.y) * (C.x - A.x)

        return ccw(p1, p3, p4) != ccw(p2, p3, p4) and ccw(p1, p2, p3) != ccw(p1, p2, p4)

    def improve_node_distribution(self, positions: Dict[str, Point],
                                canvas_width: int, canvas_height: int) -> Dict[str, Point]:
        """Improve node distribution to use canvas space more effectively."""
        if not positions:
            return positions

        improved_positions = positions.copy()

        # Find current bounds
        xs = [pos.x for pos in positions.values()]
        ys = [pos.y for pos in positions.values()]

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        # Calculate scaling to better use available space
        margin = 50
        available_width = canvas_width - 2 * margin
        available_height = canvas_height - 2 * margin

        current_width = max_x - min_x if max_x > min_x else 1
        current_height = max_y - min_y if max_y > min_y else 1

        scale_x = available_width / current_width
        scale_y = available_height / current_height
        scale = min(scale_x, scale_y, 1.0)  # Don't scale up, only down

        # Apply scaling and centering
        for node_id, pos in improved_positions.items():
            # Scale relative to center of current layout
            center_x = (min_x + max_x) / 2
            center_y = (min_y + max_y) / 2

            new_x = (pos.x - center_x) * scale + canvas_width / 2
            new_y = (pos.y - center_y) * scale + canvas_height / 2

            improved_positions[node_id] = Point(new_x, new_y)

        return improved_positions