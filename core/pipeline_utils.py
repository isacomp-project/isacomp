"""
Pipeline utilities for ResourceGraph optimizations.

This module provides common pipeline-related building blocks used across multiple
optimizations (pipelining, multi-cycle operations, resource sharing).
"""

from typing import Optional, Dict, Any
from .resource_graph import ResourceGraph, Node, Edge


class PipelineRegisterBuilder:
    """Builder for creating pipeline registers and related infrastructure."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    def create_pipeline_register(
        self,
        register_id: str,
        stage_name: Optional[str] = None,
        display_name: Optional[str] = None,
        pipeline_prefix: str = 'PIPE',
        metadata: Optional[Dict[str, Any]] = None,
        pipe_time: Optional[int] = None
    ) -> Node:
        """
        Create a pipeline register node.

        Args:
            register_id: ID for the pipeline register node
            stage_name: Name of the pipeline stage this register belongs to
            display_name: Display name for the register
            pipeline_prefix: Prefix for pipeline components (default 'PIPE')
            metadata: Additional metadata to include in node data
            pipe_time: Pipeline time (stage index) for this register

        Returns:
            Created pipeline register node
        """
        if display_name is None:
            if stage_name:
                display_name = f"Pipeline register for {stage_name}"
            else:
                display_name = f"Pipeline register {register_id}"

        reg_data = {
            'type': 'pipeline_register',
            'name': register_id,
            'display_name': display_name,
            'pipeline_component': True,
            'pipeline_prefix': pipeline_prefix
        }

        if stage_name:
            reg_data['stage_name'] = stage_name

        # Add any additional metadata
        if metadata:
            reg_data.update(metadata)

        reg_node = Node(register_id, reg_data, is_uarch_state=True)

        # Set pipe_time if provided
        if pipe_time is not None:
            reg_node.pipe_time = pipe_time
            reg_node.uarch_time = pipe_time  # Also set uarch_time for consistency

        self.graph.add_node(reg_node)

        return reg_node

    def create_input_register(
        self,
        register_id: str,
        source_signal: str,
        display_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Node:
        """
        Create an input capture register (for multi-cycle operations).

        Args:
            register_id: ID for the input register node
            source_signal: ID of the source signal being captured
            display_name: Display name for the register
            metadata: Additional metadata

        Returns:
            Created input register node
        """
        if display_name is None:
            display_name = f"Input register: {source_signal}"

        reg_data = {
            'type': 'pipeline_input_register',
            'name': register_id,
            'display_name': display_name,
            'source_signal': source_signal
        }

        if metadata:
            reg_data.update(metadata)

        reg_node = Node(register_id, reg_data, is_uarch_state=True)
        self.graph.add_node(reg_node)

        return reg_node

    def create_output_register(
        self,
        register_id: str,
        target_signal: str,
        display_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Node:
        """
        Create an output register (for multi-cycle operations).

        Args:
            register_id: ID for the output register node
            target_signal: ID of the target signal
            display_name: Display name for the register
            metadata: Additional metadata

        Returns:
            Created output register node
        """
        if display_name is None:
            display_name = f"Output register: {target_signal}"

        reg_data = {
            'type': 'pipeline_output_register',
            'name': register_id,
            'display_name': display_name,
            'target_signal': target_signal
        }

        if metadata:
            reg_data.update(metadata)

        reg_node = Node(register_id, reg_data, is_uarch_state=True)
        self.graph.add_node(reg_node)

        return reg_node

    def insert_register_in_edge(
        self,
        edge: Edge,
        register_node: Node,
        stall_controller: Optional[Node] = None,
        preserve_original_type: bool = True
    ) -> tuple[Edge, Edge]:
        """
        Insert a pipeline register in the middle of an edge.

        This removes the original edge and creates two new edges:
        - source -> register
        - register -> target

        For variable latency sources, adds complete signal as enable condition.

        Args:
            edge: The edge to cut
            register_node: The register node to insert
            stall_controller: Optional stall controller to gate the register input
            preserve_original_type: If True, preserve the original edge type in metadata

        Returns:
            Tuple of (input_edge, output_edge) - the two edges created
        """
        source = edge.source
        target = edge.target
        original_type = edge.data.get('type')

        # Check if source has variable latency
        variable_latency_source = None
        complete_signal_node = None

        if source.variable_latency:
            variable_latency_source = source
        else:
            # Check if source depends on variable latency
            deps = source.data.get('depends_on_variable_latency', [])
            if deps:
                # Find the variable latency operation
                for dep_id in deps:
                    if dep_id in self.graph.nodes:
                        dep_node = self.graph.nodes[dep_id]
                        if dep_node.variable_latency:
                            variable_latency_source = dep_node
                            break

        # Get complete signal if we have a variable latency source
        if variable_latency_source:
            complete_signal_id = variable_latency_source.data.get('complete_signal')
            if complete_signal_id and complete_signal_id in self.graph.nodes:
                complete_signal_node = self.graph.nodes[complete_signal_id]

        # Remove original edge
        edge.remove_from_nodes()
        if edge.id in self.graph.edges:
            del self.graph.edges[edge.id]

        # Create input edge: source -> register
        input_edge_data = {
            'type': 'pipeline_input',
            'pipeline_component': True
        }

        if preserve_original_type:
            input_edge_data['original_type'] = original_type

        if stall_controller:
            input_edge_data['gated_by'] = f"{stall_controller.id}_enable"

        input_edge = Edge(source, register_node, data=input_edge_data)
        self.graph.add_edge(input_edge)

        # Create output edge: register -> target
        output_edge_data = {
            'type': original_type,
            'pipeline_component': True,
            'from_pipeline_reg': True
        }

        if preserve_original_type:
            output_edge_data['original_type'] = original_type

        output_edge = Edge(register_node, target, data=output_edge_data)
        self.graph.add_edge(output_edge)

        # Add variable latency gating if needed
        if complete_signal_node:
            # Add complete signal as enable condition for pipeline register
            enable_edge = Edge(
                source=complete_signal_node,
                target=register_node,
                data={
                    'type': 'pipeline_control',
                    'control_type': 'enable',
                    'signal_type': 'variable_complete',
                    'description': f'Variable latency completion gates {register_node.id}'
                }
            )
            self.graph.add_edge(enable_edge)

            # Mark register as variable-latency gated
            register_node.data['variable_latency_gated'] = True
            register_node.data['gated_by_operation'] = variable_latency_source.id
            register_node.data['gated_by_signal'] = complete_signal_node.id

            print(f"  Pipeline register {register_node.id} gated by variable latency operation {variable_latency_source.id}")

        return (input_edge, output_edge)

    def find_pipeline_registers(
        self,
        pipeline_prefix: Optional[str] = None
    ) -> list[Node]:
        """
        Find all pipeline registers in the graph.

        Args:
            pipeline_prefix: Optional prefix to filter by (e.g., 'PIPE')

        Returns:
            List of pipeline register nodes
        """
        registers = []

        for node in self.graph.nodes.values():
            if node.data.get('type') == 'pipeline_register':
                if pipeline_prefix is None or node.data.get('pipeline_prefix') == pipeline_prefix:
                    registers.append(node)

        return registers

    def find_stage_register(
        self,
        stage_name: str,
        pipeline_prefix: str = 'PIPE'
    ) -> Optional[Node]:
        """
        Find the pipeline register for a specific stage.

        Args:
            stage_name: Name of the pipeline stage
            pipeline_prefix: Prefix for pipeline components

        Returns:
            Pipeline register node, or None if not found
        """
        register_id = f"{pipeline_prefix}_{stage_name}_reg"
        return self.graph.nodes.get(register_id)


# Convenience functions

def create_pipeline_register(
    graph: ResourceGraph,
    register_id: str,
    stage_name: Optional[str] = None,
    **kwargs
) -> Node:
    """
    Convenience function to create a pipeline register.

    See PipelineRegisterBuilder.create_pipeline_register for full documentation.
    """
    builder = PipelineRegisterBuilder(graph)
    return builder.create_pipeline_register(register_id, stage_name, **kwargs)


def insert_register_in_edge(
    graph: ResourceGraph,
    edge: Edge,
    register_node: Node,
    **kwargs
) -> tuple[Edge, Edge]:
    """
    Convenience function to insert a register in an edge.

    See PipelineRegisterBuilder.insert_register_in_edge for full documentation.
    """
    builder = PipelineRegisterBuilder(graph)
    return builder.insert_register_in_edge(edge, register_node, **kwargs)


def find_pipeline_registers(
    graph: ResourceGraph,
    pipeline_prefix: Optional[str] = None
) -> list[Node]:
    """
    Convenience function to find pipeline registers.

    See PipelineRegisterBuilder.find_pipeline_registers for full documentation.
    """
    builder = PipelineRegisterBuilder(graph)
    return builder.find_pipeline_registers(pipeline_prefix)
