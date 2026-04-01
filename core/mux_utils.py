"""
Unified multiplexer utilities for ResourceGraph operations.

This module provides a consistent interface for creating and managing multiplexers
across different optimization passes, supporting both one-hot and priority-encoded
selection schemes.
"""

from typing import Dict, List, Optional, Tuple, Union
from .resource_graph import ResourceGraph, Node, Edge
from enum import Enum


class MuxType(Enum):
    """Type of multiplexer selection logic."""
    ONE_HOT = "one_hot_select"      # One-hot encoded (exactly one select active)
    PRIORITY = "priority_select"    # Priority encoded (first active wins)


class MuxBuilder:
    """
    Builder for creating and modifying multiplexers in a ResourceGraph.

    Supports incremental construction, allowing muxes to be created with initial
    inputs and later extended with additional inputs.
    """

    def __init__(self, graph: ResourceGraph, mux_id: str, mux_type: MuxType = MuxType.ONE_HOT,
                 bit_width: Optional[int] = None):
        """
        Initialize a MuxBuilder.

        Args:
            graph: ResourceGraph to insert mux into
            mux_id: Unique identifier for the mux node
            mux_type: Type of mux selection (one-hot or priority)
            bit_width: Optional bit width for the mux (for width mismatch handling)
        """
        self.graph = graph
        self.mux_id = mux_id
        self.mux_type = mux_type
        self.mux_node: Optional[Node] = None
        self.num_inputs = 0
        self.bit_width = bit_width

    def create_or_get_mux(self, display_name: Optional[str] = None) -> Node:
        """
        Create mux node if it doesn't exist, or return existing mux node.

        Args:
            display_name: Optional display name for the mux

        Returns:
            The mux node
        """
        if self.mux_node is not None:
            return self.mux_node

        # Check if mux already exists in graph
        if self.mux_id in self.graph.nodes:
            self.mux_node = self.graph.nodes[self.mux_id]
            # Count existing inputs
            self.num_inputs = len([e for e in self.mux_node.incoming_edges
                                  if e.data.get('type') == 'mux_input'])
            return self.mux_node

        # Create new mux node
        mux_data = {
            'type': 'multiplexer',
            'name': self.mux_id,
            'display_name': display_name or self.mux_id,
            'num_inputs': 0,  # Will be updated as inputs are added
            'operation': self.mux_type.value
        }

        # Include bit_width if specified
        if self.bit_width is not None:
            mux_data['bit_width'] = self.bit_width

        self.mux_node = Node(self.mux_id, mux_data)
        self.graph.add_node(self.mux_node)
        return self.mux_node

    def set_bit_width(self, bit_width: int):
        """
        Set the bit width for this mux.

        This enables automatic zero-extension of narrow inputs.

        Args:
            bit_width: The expected bit width for mux inputs/output
        """
        self.bit_width = bit_width
        if self.mux_node is not None:
            self.mux_node.data['bit_width'] = bit_width

    def _get_or_create_zext_node(self, source: Node, target_width: int) -> Node:
        """
        Get or create a zero_extend node for a narrow source.

        Uses the same pattern as memory_access_transform.py to create
        proper zero_extend nodes in the graph.

        Args:
            source: The narrow source node
            target_width: The target width to extend to

        Returns:
            The zero_extend node (existing or newly created)
        """
        source_width = source.data.get('bit_width', 32)
        zext_name = f"{source.id}_zext"

        # Check if zero_extend node already exists
        if zext_name in self.graph.nodes:
            return self.graph.nodes[zext_name]

        # Create new zero_extend node
        pad_bits = target_width - source_width
        zext_data = {
            'type': 'zero_extend',
            'name': zext_name,
            'display_name': f"{{{pad_bits}'d0, {source.id}}}",
            'bit_width': target_width,
            'original_width': source_width,
            'expression': {
                'type': 'zero_extend',
                'operand': {'type': 'identifier', 'name': source.id},
                'width': target_width
            }
        }
        zext_node = Node(zext_name, zext_data, is_uarch_state=False)
        self.graph.add_node(zext_node)

        # Connect source to zero_extend node
        self.graph.add_edge(Edge(source, zext_node, data={'type': 'operand'}))

        return zext_node

    def add_input(self, source: Node, select: Union[Node, str],
                  input_index: Optional[int] = None,
                  metadata: Optional[Dict] = None) -> int:
        """
        Add an input to the multiplexer.

        If the source node is narrower than the mux bit_width, a zero_extend
        node is automatically created in the graph.

        Args:
            source: Node providing the data input
            select: Node or condition string for selecting this input
            input_index: Optional specific index (auto-assigned if None)
            metadata: Optional metadata for the input edge

        Returns:
            The index assigned to this input
        """
        if self.mux_node is None:
            self.create_or_get_mux()

        # Handle width mismatch by creating zero_extend node if needed
        # Only create zext if source has EXPLICIT bit_width that is narrower than target
        # Don't assume unknown widths - let verilog_generator handle those cases
        if self.bit_width is not None:
            source_width = source.data.get('bit_width')
            if source_width is not None and source_width < self.bit_width:
                # Create or get zero_extend node and use it as the actual source
                source = self._get_or_create_zext_node(source, self.bit_width)

        # Determine input index
        if input_index is None:
            input_index = self.num_inputs

        # Create data input edge
        input_data = {
            'type': 'mux_input',
            'input_index': input_index
        }
        if metadata:
            input_data.update(metadata)

        input_edge = Edge(source, self.mux_node, data=input_data)
        self.graph.add_edge(input_edge)

        # Create select edge
        select_data = {
            'type': 'mux_select',
            'select_index': input_index
        }

        if isinstance(select, Node):
            # Select signal is a node
            select_data['select_node'] = select.id
            select_edge = Edge(select, self.mux_node, data=select_data)
            self.graph.add_edge(select_edge)
        else:
            # Select signal is a condition string
            select_data['condition'] = select
            # Store condition strings in the mux node data so generator can access them
            if 'select_conditions' not in self.mux_node.data:
                self.mux_node.data['select_conditions'] = {}
            self.mux_node.data['select_conditions'][input_index] = select

        # Update input count
        self.num_inputs = max(self.num_inputs, input_index + 1)
        self.mux_node.data['num_inputs'] = self.num_inputs

        return input_index

    def add_default_input(self, source: Node, metadata: Optional[Dict] = None):
        """
        Add a default input to the multiplexer (for PRIORITY muxes).

        This input is selected when no other select signals are active.
        Only valid for PRIORITY type muxes.

        Args:
            source: Node providing the default data input
            metadata: Optional metadata for the default input edge
        """
        if self.mux_node is None:
            self.create_or_get_mux()

        if self.mux_type != MuxType.PRIORITY:
            raise ValueError("Default inputs are only supported for PRIORITY muxes")

        # Handle width mismatch by creating zero_extend node if needed
        # Only create zext if source has EXPLICIT bit_width that is narrower than target
        if self.bit_width is not None:
            source_width = source.data.get('bit_width')
            if source_width is not None and source_width < self.bit_width:
                source = self._get_or_create_zext_node(source, self.bit_width)

        # Create default input edge with special marker
        default_data = {
            'type': 'mux_default_input'
        }
        if metadata:
            default_data.update(metadata)

        default_edge = Edge(source, self.mux_node, data=default_data)
        self.graph.add_edge(default_edge)

        # Store default input info in mux node
        self.mux_node.data['has_default'] = True
        self.mux_node.data['default_source'] = source.id

    def connect_output(self, target: Node, edge_type: str = 'assignment',
                      metadata: Optional[Dict] = None):
        """
        Connect the mux output to a target node.

        Args:
            target: Node to receive the mux output
            edge_type: Type of edge (default: 'assignment')
            metadata: Optional metadata for the output edge
        """
        if self.mux_node is None:
            raise ValueError("Mux must be created before connecting output")

        # Inherit width from target node if mux doesn't have one set
        # This ensures the mux has the correct width for its output
        if self.mux_node.data.get('bit_width') is None:
            target_width = target.data.get('bit_width') or target.data.get('data_width') or target.data.get('output_width')
            if target_width:
                self.mux_node.data['bit_width'] = target_width
                self.mux_node.data['data_width'] = target_width

        output_data = {'type': edge_type}
        if metadata:
            output_data.update(metadata)

        output_edge = Edge(self.mux_node, target, data=output_data)
        self.graph.add_edge(output_edge)

    def remove_bypassing_edges(self, sources: List[Node], target: Node):
        """
        Remove direct edges from sources to target that bypass this mux.

        This is useful when converting direct connections to multiplexed connections.

        Args:
            sources: Source nodes that feed into the mux
            target: Target node that should only receive mux output
        """
        edges_to_remove = []

        for source in sources:
            for edge in list(source.outgoing_edges):
                if edge.target == target and edge.data.get('type') == 'assignment':
                    edges_to_remove.append(edge)

        for edge in edges_to_remove:
            self.graph.remove_edge(edge.id)

        return len(edges_to_remove)


def create_mux(graph: ResourceGraph,
               mux_id: str,
               inputs: List[Tuple[Node, Union[Node, str]]],
               target: Node,
               mux_type: MuxType = MuxType.ONE_HOT,
               display_name: Optional[str] = None,
               output_edge_type: str = 'assignment',
               remove_direct_edges: bool = True) -> Node:
    """
    Convenience function to create a complete multiplexer in one call.

    Args:
        graph: ResourceGraph to insert mux into
        mux_id: Unique identifier for the mux
        inputs: List of (source_node, select_signal) tuples
        target: Target node to receive mux output
        mux_type: Type of mux (one-hot or priority)
        display_name: Optional display name
        output_edge_type: Type of output edge
        remove_direct_edges: Whether to remove direct source->target edges

    Returns:
        The created mux node
    """
    builder = MuxBuilder(graph, mux_id, mux_type)
    builder.create_or_get_mux(display_name)

    # Add all inputs
    source_nodes = []
    for source, select in inputs:
        builder.add_input(source, select)
        source_nodes.append(source)

    # Connect output
    builder.connect_output(target, output_edge_type)

    # Optionally remove bypassing edges
    if remove_direct_edges:
        removed = builder.remove_bypassing_edges(source_nodes, target)
        if removed > 0:
            print(f"Removed {removed} bypassing edges for mux {mux_id}")

    return builder.mux_node


def add_mux_input(graph: ResourceGraph,
                  mux_id: str,
                  source: Node,
                  select: Union[Node, str],
                  mux_type: MuxType = MuxType.ONE_HOT) -> int:
    """
    Add an input to an existing mux (or create mux if it doesn't exist).

    Args:
        graph: ResourceGraph containing the mux
        mux_id: ID of the mux to extend
        source: Source node for new input
        select: Select signal (node or condition string)
        mux_type: Type of mux (only used if creating new mux)

    Returns:
        Index of the added input
    """
    builder = MuxBuilder(graph, mux_id, mux_type)
    builder.create_or_get_mux()
    return builder.add_input(source, select)


def get_mux_info(graph: ResourceGraph, mux_id: str) -> Optional[Dict]:
    """
    Get information about a mux node.

    Args:
        graph: ResourceGraph containing the mux
        mux_id: ID of the mux

    Returns:
        Dict with mux info or None if not found
    """
    if mux_id not in graph.nodes:
        return None

    mux_node = graph.nodes[mux_id]
    if mux_node.data.get('type') != 'multiplexer':
        return None

    # Collect input info
    inputs = []
    for edge in mux_node.incoming_edges:
        if edge.data.get('type') == 'mux_input':
            input_idx = edge.data.get('input_index', len(inputs))
            inputs.append({
                'index': input_idx,
                'source': edge.source.id,
                'metadata': edge.data
            })

    # Collect select info
    selects = []
    for edge in mux_node.incoming_edges:
        if edge.data.get('type') == 'mux_select':
            selects.append({
                'index': edge.data.get('select_index'),
                'node': edge.source.id,
                'condition': edge.data.get('condition')
            })

    # Collect output info
    outputs = []
    for edge in mux_node.outgoing_edges:
        outputs.append({
            'target': edge.target.id,
            'type': edge.data.get('type'),
            'metadata': edge.data
        })

    return {
        'mux_id': mux_id,
        'type': mux_node.data.get('operation'),
        'num_inputs': mux_node.data.get('num_inputs', 0),
        'inputs': sorted(inputs, key=lambda x: x['index']),
        'selects': sorted(selects, key=lambda x: x['index']),
        'outputs': outputs
    }


# =============================================================================
# Mux Refactoring
# =============================================================================

from dataclasses import dataclass


@dataclass
class MuxInputInfo:
    """Information about a single mux input."""
    source_node: Node
    source_id: str
    select_signal: Union[Node, str, None]
    input_index: int
    instruction: Optional[str] = None
    pipe_time: Optional[int] = None


class MuxRefactor:
    """
    Refactors a large mux into a hierarchy of sub-muxes based on user-defined groupings.

    This optimization reduces the fan-in of large multiplexers by creating smaller
    sub-muxes for related inputs, then combining their outputs in a smaller top-level mux.

    Example usage:
        refactor = MuxRefactor(graph, 'rf_write_data_mux')
        refactor.add_group('alu_r', ['add_res', 'sub_res', 'and_res', ...])
        refactor.add_group('alu_i', ['addi_res', 'andi_res', ...])
        refactor.add_group('mem', ['data', 'byte_data', ...])
        sub_muxes = refactor.apply()
    """

    def __init__(self, graph: ResourceGraph, mux_id: str):
        """
        Initialize a MuxRefactor.

        Args:
            graph: ResourceGraph containing the mux
            mux_id: ID of the mux to refactor
        """
        self.graph = graph
        self.mux_id = mux_id

        if mux_id not in graph.nodes:
            raise ValueError(f"Mux '{mux_id}' not found in graph")

        self.mux_node = graph.nodes[mux_id]
        if self.mux_node.data.get('type') != 'multiplexer':
            raise ValueError(f"Node '{mux_id}' is not a multiplexer")

        self.groups: Dict[str, List[str]] = {}
        self._input_info: Optional[Dict[str, MuxInputInfo]] = None

    def add_group(self, name: str, input_sources: List[str]) -> 'MuxRefactor':
        """
        Define a group of inputs to be factored into a sub-mux.

        Args:
            name: Name for this group (used in sub-mux naming)
            input_sources: List of source node IDs that should be grouped

        Returns:
            self (for method chaining)
        """
        self.groups[name] = input_sources
        return self

    def _collect_input_info(self) -> Dict[str, MuxInputInfo]:
        """Collect information about all mux inputs."""
        if self._input_info is not None:
            return self._input_info

        self._input_info = {}

        # Build map of input_index -> select info
        select_map: Dict[int, Union[Node, str, None]] = {}
        select_conditions = self.mux_node.data.get('select_conditions', {})

        for edge in self.mux_node.incoming_edges:
            if edge.data.get('type') == 'mux_select':
                idx = edge.data.get('select_index')
                if idx is not None:
                    select_map[idx] = edge.source

        # Also check for string conditions stored in node data
        for idx, condition in select_conditions.items():
            if idx not in select_map:
                select_map[idx] = condition

        # Collect input info
        for edge in self.mux_node.incoming_edges:
            if edge.data.get('type') == 'mux_input':
                source = edge.source
                input_idx = edge.data.get('input_index', 0)

                info = MuxInputInfo(
                    source_node=source,
                    source_id=source.id,
                    select_signal=select_map.get(input_idx),
                    input_index=input_idx,
                    instruction=source.data.get('instruction'),
                    pipe_time=source.pipe_time
                )
                self._input_info[source.id] = info

        return self._input_info

    def _get_mux_type(self) -> MuxType:
        """Get the type of the original mux."""
        operation = self.mux_node.data.get('operation', 'one_hot_select')
        if operation == 'priority_select':
            return MuxType.PRIORITY
        return MuxType.ONE_HOT

    def _create_combined_enable(self, group_name: str, input_infos: List[MuxInputInfo]) -> Node:
        """
        Create an OR-combined enable signal for a group of inputs.

        Args:
            group_name: Name of the group
            input_infos: List of MuxInputInfo for inputs in this group

        Returns:
            The combined enable signal node
        """
        enable_node_id = f"{group_name}_group_enable"

        # Collect enable signal names
        enable_signals = []
        enable_nodes = []

        for info in input_infos:
            select = info.select_signal
            if isinstance(select, Node):
                enable_signals.append(select.id)
                enable_nodes.append(select)
            elif isinstance(select, str):
                enable_signals.append(select)
            elif info.instruction:
                # Derive enable from instruction name
                enable_signals.append(f"{info.instruction}_enable")

        if not enable_signals:
            raise ValueError(f"No enable signals found for group '{group_name}'")

        # Create the combined enable node
        if len(enable_signals) == 1:
            # Single enable - no need for OR, just use existing signal
            if enable_nodes:
                return enable_nodes[0]
            # String-based - create reference node
            enable_data = {
                'type': 'enable_signal',
                'name': enable_node_id,
                'display_name': enable_signals[0],
                'expression': {'type': 'identifier', 'name': enable_signals[0]},
                'bit_width': 1
            }
        else:
            # Multiple enables - create OR expression
            or_expr = ' | '.join(enable_signals)
            enable_data = {
                'type': 'combined_enable',
                'name': enable_node_id,
                'display_name': f"({or_expr})",
                'expression': {
                    'type': 'binary_op',
                    'operator': '|',
                    'operands': [{'type': 'identifier', 'name': s} for s in enable_signals]
                },
                'bit_width': 1,
                'component_enables': enable_signals
            }

        enable_node = Node(enable_node_id, enable_data, is_uarch_state=False)
        self.graph.add_node(enable_node)

        # Connect enable signal source nodes to the combined enable
        for node in enable_nodes:
            edge = Edge(node, enable_node, data={'type': 'operand'})
            self.graph.add_edge(edge)

        return enable_node

    def _remove_inputs_from_mux(self, source_ids: List[str], input_info: Dict[str, 'MuxInputInfo']):
        """Remove specified inputs from the original mux.

        Args:
            source_ids: List of source node IDs to remove
            input_info: Pre-collected input info (must be collected before calling this method)
        """
        edges_to_remove = []

        # Collect indices to remove BEFORE removing edges (using pre-collected info)
        indices_to_remove = set()
        for source_id in source_ids:
            if source_id in input_info:
                indices_to_remove.add(input_info[source_id].input_index)

        for edge in list(self.mux_node.incoming_edges):
            edge_type = edge.data.get('type')

            if edge_type == 'mux_input':
                if edge.source.id in source_ids:
                    edges_to_remove.append(edge)

            elif edge_type == 'mux_select':
                # Find corresponding input index and check if its source is being removed
                select_idx = edge.data.get('select_index')
                # Find the input with this index
                for inp_edge in self.mux_node.incoming_edges:
                    if (inp_edge.data.get('type') == 'mux_input' and
                        inp_edge.data.get('input_index') == select_idx and
                        inp_edge.source.id in source_ids):
                        edges_to_remove.append(edge)
                        break

        for edge in edges_to_remove:
            self.graph.remove_edge(edge.id)

        # Update select_conditions in mux node data
        if 'select_conditions' in self.mux_node.data:
            new_conditions = {
                k: v for k, v in self.mux_node.data['select_conditions'].items()
                if k not in indices_to_remove
            }
            self.mux_node.data['select_conditions'] = new_conditions

    def apply(self) -> Dict[str, Node]:
        """
        Apply the refactoring.

        Creates sub-muxes for each defined group, connects them to the original mux,
        and removes the grouped inputs from the original mux.

        Returns:
            Dict mapping group names to their sub-mux nodes
        """
        if not self.groups:
            raise ValueError("No groups defined. Use add_group() before apply().")

        input_info = self._collect_input_info()
        mux_type = self._get_mux_type()
        bit_width = self.mux_node.data.get('bit_width')

        sub_muxes: Dict[str, Node] = {}

        print(f"\nRefactoring mux '{self.mux_id}' ({len(input_info)} inputs) into {len(self.groups)} sub-muxes:")

        for group_name, source_ids in self.groups.items():
            # Validate sources exist
            valid_sources = []
            for source_id in source_ids:
                if source_id in input_info:
                    valid_sources.append(source_id)
                else:
                    print(f"  Warning: Source '{source_id}' not found in mux inputs, skipping")

            if not valid_sources:
                print(f"  Skipping empty group '{group_name}'")
                continue

            # Get input info for this group
            group_inputs = [input_info[sid] for sid in valid_sources]

            # Create sub-mux
            sub_mux_id = f"{self.mux_id}_{group_name}_submux"
            builder = MuxBuilder(self.graph, sub_mux_id, mux_type, bit_width)
            builder.create_or_get_mux(display_name=f"{group_name} sub-mux")

            # Add inputs to sub-mux
            for info in group_inputs:
                builder.add_input(info.source_node, info.select_signal or f"{info.instruction}_enable")

            sub_mux_node = builder.mux_node
            sub_muxes[group_name] = sub_mux_node

            # Create combined enable for this group
            combined_enable = self._create_combined_enable(group_name, group_inputs)

            # Remove original inputs from main mux
            self._remove_inputs_from_mux(valid_sources, input_info)

            # Add sub-mux output as new input to main mux
            main_builder = MuxBuilder(self.graph, self.mux_id, mux_type)
            main_builder.mux_node = self.mux_node
            main_builder.num_inputs = self.mux_node.data.get('num_inputs', 0)
            main_builder.add_input(sub_mux_node, combined_enable)

            print(f"  Created '{sub_mux_id}' with {len(valid_sources)} inputs, enable: {combined_enable.id}")

        # Update main mux input count
        remaining_inputs = len([e for e in self.mux_node.incoming_edges
                               if e.data.get('type') == 'mux_input'])
        self.mux_node.data['num_inputs'] = remaining_inputs

        print(f"  Main mux now has {remaining_inputs} inputs")

        return sub_muxes


def refactor_mux(graph: ResourceGraph,
                 mux_id: str,
                 groups: Dict[str, List[str]]) -> Dict[str, Node]:
    """
    Refactor a mux into sub-muxes based on groupings.

    This is a convenience function that creates sub-muxes for each group of inputs,
    replacing the original high fan-in mux with a hierarchy of smaller muxes.

    Args:
        graph: The ResourceGraph
        mux_id: ID of mux to refactor
        groups: Dict mapping group name to list of input source node IDs

    Returns:
        Dict mapping group names to created sub-mux nodes

    Example:
        sub_muxes = refactor_mux(graph, 'rf_write_data_mux', {
            'alu_r': ['add_res', 'sub_res', 'and_res', 'or_res', 'xor_res',
                      'sll_res', 'srl_res', 'sra_res', 'slt_res', 'sltu_res'],
            'alu_i': ['addi_res', 'andi_res', 'ori_res', 'xori_res',
                      'slli_res', 'srli_res', 'srai_res', 'slti_res', 'sltiu_res'],
            'upper': ['lui_res', 'auipc_res'],
            'mem':   ['data', 'byte_data', 'halfword_data'],
            'jump':  ['ret_addr']
        })
    """
    refactor = MuxRefactor(graph, mux_id)
    for name, sources in groups.items():
        refactor.add_group(name, sources)
    return refactor.apply()


def analyze_mux(graph: ResourceGraph, mux_id: str) -> Optional[Dict]:
    """
    Analyze a mux to help determine grouping strategy.

    Provides detailed information about mux inputs including their source nodes,
    select signals, instruction associations, and pipeline timing. This information
    can be used to define groupings for refactor_mux().

    Args:
        graph: ResourceGraph containing the mux
        mux_id: ID of the mux to analyze

    Returns:
        Dict with:
            - inputs: List of input info dicts
            - by_instruction: Inputs grouped by instruction
            - by_pipe_time: Inputs grouped by pipeline time
            - suggested_groups: Heuristic groupings based on common patterns

        Returns None if mux not found.
    """
    if mux_id not in graph.nodes:
        return None

    mux_node = graph.nodes[mux_id]
    if mux_node.data.get('type') != 'multiplexer':
        return None

    # Use MuxRefactor to collect input info
    try:
        refactor = MuxRefactor(graph, mux_id)
        input_info = refactor._collect_input_info()
    except ValueError:
        return None

    # Build input list
    inputs = []
    for source_id, info in input_info.items():
        select_str = None
        if isinstance(info.select_signal, Node):
            select_str = info.select_signal.id
        elif isinstance(info.select_signal, str):
            select_str = info.select_signal

        inputs.append({
            'source_id': source_id,
            'input_index': info.input_index,
            'select_signal': select_str,
            'instruction': info.instruction,
            'pipe_time': info.pipe_time
        })

    # Group by instruction
    by_instruction: Dict[str, List[str]] = {}
    for info in input_info.values():
        instr = info.instruction or 'unknown'
        if instr not in by_instruction:
            by_instruction[instr] = []
        by_instruction[instr].append(info.source_id)

    # Group by pipe_time
    by_pipe_time: Dict[int, List[str]] = {}
    for info in input_info.values():
        pt = info.pipe_time if info.pipe_time is not None else -1
        if pt not in by_pipe_time:
            by_pipe_time[pt] = []
        by_pipe_time[pt].append(info.source_id)

    # Generate suggested groups based on common patterns
    suggested_groups: Dict[str, List[str]] = {}

    # Pattern 1: Group by instruction category (based on common RISC-V naming)
    alu_r_ops = []
    alu_i_ops = []
    mem_ops = []
    jump_ops = []
    other_ops = []

    for source_id in input_info.keys():
        lower_id = source_id.lower()
        if any(x in lower_id for x in ['add_res', 'sub_res', 'and_res', 'or_res',
                                        'xor_res', 'sll_res', 'srl_res', 'sra_res',
                                        'slt_res', 'sltu_res']):
            alu_r_ops.append(source_id)
        elif any(x in lower_id for x in ['addi_res', 'andi_res', 'ori_res', 'xori_res',
                                          'slli_res', 'srli_res', 'srai_res', 'slti_res',
                                          'sltiu_res', 'lui_res', 'auipc_res']):
            alu_i_ops.append(source_id)
        elif any(x in lower_id for x in ['data', 'byte', 'half', 'word', 'load', 'mem']):
            mem_ops.append(source_id)
        elif any(x in lower_id for x in ['ret_addr', 'jal', 'jalr', 'jump', 'link']):
            jump_ops.append(source_id)
        else:
            other_ops.append(source_id)

    if alu_r_ops:
        suggested_groups['alu_r'] = alu_r_ops
    if alu_i_ops:
        suggested_groups['alu_i'] = alu_i_ops
    if mem_ops:
        suggested_groups['mem'] = mem_ops
    if jump_ops:
        suggested_groups['jump'] = jump_ops
    if other_ops:
        suggested_groups['other'] = other_ops

    return {
        'mux_id': mux_id,
        'mux_type': mux_node.data.get('operation'),
        'num_inputs': len(inputs),
        'bit_width': mux_node.data.get('bit_width'),
        'inputs': sorted(inputs, key=lambda x: x['input_index']),
        'by_instruction': by_instruction,
        'by_pipe_time': {k: v for k, v in sorted(by_pipe_time.items())},
        'suggested_groups': suggested_groups
    }