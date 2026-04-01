#!/usr/bin/env python3
"""
Multi-file VHDL Parser for Hierarchical Analysis

This parser can:
1. Parse multiple VHDL files
2. Build a component library from entity declarations
3. Link component instantiations to entity implementations
4. Propagate ISA state through component hierarchy
5. Generate unified ResourceGraph for whole system
"""

from pathlib import Path
from typing import Dict, List, Set, Optional
from frontends.vhdl.vhdl_parser_pyghdl import VHDLParserPyGHDL
from core.resource_graph import ResourceGraph, Node, Edge


class MultiFileVHDLParser:
    """Parser for multi-file VHDL designs with hierarchical analysis"""

    def __init__(self):
        self.entity_graphs: Dict[str, ResourceGraph] = {}  # entity_name -> graph
        self.entity_parsers: Dict[str, VHDLParserPyGHDL] = {}  # entity_name -> parser
        self.entity_files: Dict[str, str] = {}  # entity_name -> filename
        self.arch_state_entities: Set[str] = set()  # entities with ISA state

    def parse_files(self, file_list: List[str]) -> None:
        """Parse multiple VHDL files and build entity library"""
        print("=" * 80)
        print("MULTI-FILE VHDL PARSER")
        print("=" * 80)

        # Phase 1: Parse all files individually
        print("\nPhase 1: Parsing individual files...")
        print("-" * 80)
        for filename in file_list:
            self._parse_single_file(filename)

        # Phase 2: Identify entities with ISA state
        print("\nPhase 2: Identifying ISA state entities...")
        print("-" * 80)
        self._identify_arch_state_entities()

        print("\n" + "=" * 80)
        print(f"Parsed {len(self.entity_graphs)} entities")
        print(f"Found {len(self.arch_state_entities)} entities with ISA state")
        print("=" * 80)

    def _parse_single_file(self, filename: str) -> None:
        """Parse a single VHDL file"""
        parser = VHDLParserPyGHDL()
        graph = parser.parse_file(filename)

        if parser.entity_name:
            entity_name = parser.entity_name
            self.entity_graphs[entity_name] = graph
            self.entity_parsers[entity_name] = parser
            self.entity_files[entity_name] = filename

            print(f"  ✓ {entity_name} ({Path(filename).name}): "
                  f"{len(graph.nodes)} nodes, {len(graph.edges)} edges")

            # Track if this entity has ISA state
            if parser.arch_state_signals:
                self.arch_state_entities.add(entity_name)

    def _identify_arch_state_entities(self) -> None:
        """Identify which entities contain ISA state"""
        for entity_name in self.arch_state_entities:
            parser = self.entity_parsers[entity_name]
            arch_signals = parser.arch_state_signals
            print(f"  ✓ {entity_name}: {', '.join(arch_signals)}")

    def build_hierarchical_graph(self, top_entity: str) -> ResourceGraph:
        """
        Build a unified hierarchical graph starting from top entity.

        This connects component instances to their entity implementations.
        """
        print("\n" + "=" * 80)
        print(f"Building hierarchical graph from: {top_entity}")
        print("=" * 80)

        # Create unified graph
        unified_graph = ResourceGraph()

        # Track which entities we've expanded
        expanded: Set[str] = set()

        # Recursively expand hierarchy
        self._expand_entity(top_entity, "", unified_graph, expanded)

        print(f"\nUnified graph: {len(unified_graph.nodes)} nodes, {len(unified_graph.edges)} edges")

        return unified_graph

    def _expand_entity(self, entity_name: str, prefix: str,
                       unified_graph: ResourceGraph, expanded: Set[str]) -> None:
        """
        Recursively expand an entity into the unified graph.

        Args:
            entity_name: Name of entity to expand
            prefix: Hierarchical prefix (e.g., "cpu.alu.")
            unified_graph: Unified graph to add nodes/edges to
            expanded: Set of already-expanded (prefix, entity) pairs
        """
        # Check if this (prefix, entity) has already been expanded
        expansion_key = f"{prefix}{entity_name}"
        if expansion_key in expanded:
            return
        expanded.add(expansion_key)

        # Get parser and graph for this entity
        if entity_name not in self.entity_parsers:
            print(f"  Warning: No implementation found for entity '{entity_name}'")
            return

        parser = self.entity_parsers[entity_name]
        graph = self.entity_graphs[entity_name]

        print(f"  Expanding: {prefix}{entity_name}")

        # Copy all nodes from this entity into unified graph (with prefix)
        for node in graph.nodes.values():
            # Create prefixed node ID
            prefixed_id = f"{prefix}{node.id}"

            # Copy node data and update 'name' field to include hierarchical prefix
            node_data = node.data.copy() if node.data else {}
            if 'name' in node_data:
                # CRITICAL: Update the 'name' field to include hierarchical prefix
                # This ensures VHDL generator uses unique names (e.g., i_alu_a instead of a)
                node_data['name'] = f"{prefix}{node_data['name']}"

            # CRITICAL: Update default_value reference to include prefix
            # This ensures combinational defaults reference the correct prefixed signal
            if 'default_value' in node_data:
                node_data['default_value'] = f"{prefix}{node_data['default_value']}"

            # Copy node with prefix
            unified_node = Node(
                node_id=prefixed_id,
                data=node_data,
                is_arch_state=node.is_arch_state,
                is_uarch_state=node.is_uarch_state
            )

            # Add hierarchical metadata
            if unified_node.data is None:
                unified_node.data = {}
            unified_node.data["entity"] = entity_name
            unified_node.data["hierarchy_path"] = prefix.rstrip('.')

            unified_graph.add_node(unified_node)

        # Copy all edges from this entity into unified graph (with prefix)
        for edge in graph.edges.values():
            source_id = f"{prefix}{edge.source.id}"
            target_id = f"{prefix}{edge.target.id}"

            if source_id in unified_graph.nodes and target_id in unified_graph.nodes:
                # Copy edge data and update any node ID references
                edge_data = edge.data.copy() if edge.data else {}

                # CRITICAL: Update condition node ID reference to include prefix
                # This ensures conditional assignments reference the correct prefixed signal
                if 'condition' in edge_data:
                    edge_data['condition'] = f"{prefix}{edge_data['condition']}"

                # ALSO update all_conditions entries for nested conditionals
                if 'all_conditions' in edge_data:
                    prefixed_conditions = []
                    for cond_info in edge_data['all_conditions']:
                        new_cond_info = cond_info.copy()
                        new_cond_info['node_id'] = f"{prefix}{cond_info['node_id']}"
                        prefixed_conditions.append(new_cond_info)
                    edge_data['all_conditions'] = prefixed_conditions

                # CRITICAL: Update array_index to include prefix (for array writes)
                # This ensures array writes reference the correct prefixed index signal
                if 'array_index' in edge_data:
                    edge_data['array_index'] = f"{prefix}{edge_data['array_index']}"

                # ALSO update default_value reference to include prefix
                if 'default_value' in edge_data:
                    edge_data['default_value'] = f"{prefix}{edge_data['default_value']}"

                unified_edge = Edge(
                    unified_graph.nodes[source_id],
                    unified_graph.nodes[target_id],
                    data=edge_data
                )
                unified_graph.add_edge(unified_edge)

        # Expand component instances
        for inst_name, inst_info in parser.instances.items():
            component_name = inst_info["component"]
            inst_prefix = f"{prefix}{inst_name}."

            # Recursively expand this component
            self._expand_entity(component_name, inst_prefix, unified_graph, expanded)

            # Connect parent signals to child entity ports
            self._connect_instance_ports(inst_name, inst_info, prefix, inst_prefix, unified_graph)

    def _connect_instance_ports(self, inst_name: str, inst_info: Dict,
                                parent_prefix: str, child_prefix: str,
                                unified_graph: ResourceGraph) -> None:
        """
        Connect instance port mappings between parent and child entities.

        Args:
            inst_name: Instance name (e.g., "i_alu")
            inst_info: Instance information with port_map
            parent_prefix: Hierarchical prefix of parent (e.g., "cpu.")
            child_prefix: Hierarchical prefix of child (e.g., "cpu.i_alu.")
            unified_graph: Unified graph to add connections to
        """
        component_name = inst_info["component"]
        port_map = inst_info["port_map"]

        # Get component entity info
        if component_name not in self.entity_parsers:
            return

        component_parser = self.entity_parsers[component_name]

        # For each port mapping, create connection
        for formal_port, actual_signal in port_map.items():
            # Parent signal (e.g., "cpu.a_bus")
            parent_signal_id = f"{parent_prefix}{actual_signal}"

            # Child port (e.g., "cpu.i_alu.a")
            child_port_id = f"{child_prefix}{formal_port}"

            # Check if both exist in unified graph
            if parent_signal_id not in unified_graph.nodes:
                continue
            if child_port_id not in unified_graph.nodes:
                continue

            parent_node = unified_graph.nodes[parent_signal_id]
            child_node = unified_graph.nodes[child_port_id]

            # Propagate bit_width from child port to parent signal if parent doesn't have it
            if parent_node.data.get('bit_width') is None and child_node.data.get('bit_width') is not None:
                parent_node.data['bit_width'] = child_node.data['bit_width']

            # Determine connection direction based on port direction
            # (For now, create bidirectional connection for simplicity)
            edge_parent_to_child = Edge(
                parent_node, child_node,
                data={"type": "hierarchical_connection", "instance": inst_name,
                      "port": formal_port, "direction": "parent_to_child"}
            )
            edge_child_to_parent = Edge(
                child_node, parent_node,
                data={"type": "hierarchical_connection", "instance": inst_name,
                      "port": formal_port, "direction": "child_to_parent"}
            )

            unified_graph.add_edge(edge_parent_to_child)
            unified_graph.add_edge(edge_child_to_parent)

    def get_all_arch_state_nodes(self, unified_graph: ResourceGraph) -> List[Node]:
        """Get all ISA state nodes from unified graph"""
        return [n for n in unified_graph.nodes.values() if n.is_arch_state]

    def print_summary(self) -> None:
        """Print summary of parsed entities"""
        print("\n" + "=" * 80)
        print("ENTITY SUMMARY")
        print("=" * 80)

        for entity_name, graph in self.entity_graphs.items():
            parser = self.entity_parsers[entity_name]
            is_arch = "✓ ISA STATE" if entity_name in self.arch_state_entities else ""

            print(f"\n{entity_name} {is_arch}")
            print(f"  File: {Path(self.entity_files[entity_name]).name}")
            print(f"  Nodes: {len(graph.nodes)}")
            print(f"  Edges: {len(graph.edges)}")
            print(f"  Components: {len(parser.components)}")
            print(f"  Instances: {len(parser.instances)}")

            if parser.arch_state_signals:
                print(f"  ISA state: {', '.join(parser.arch_state_signals)}")
