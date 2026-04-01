"""
Unpipelining Optimization

This module provides functionality to reverse pipelining optimizations and restore
a design to a single-cycle implementation. It identifies and removes:
- Pipeline registers
- Hazard detection hardware (comparators, stall signals)
- Stall controllers

The optimization reconnects the original edges that were separated by pipeline
registers, effectively collapsing all pipeline stages back into a single cycle.
"""

from typing import Dict, List, Set, Tuple, Optional
from core.resource_graph import Node, Edge, ResourceGraph
import logging

logger = logging.getLogger(__name__)


class UnpipelineTransform:
    """
    Transforms a pipelined design back to a single-cycle design by removing
    all pipeline-related hardware components.
    """

    def __init__(self, graph: ResourceGraph, pipeline_prefix: str = 'PIPE'):
        """
        Initialize the unpipeline transformation.

        Args:
            graph: The resource graph containing the pipelined design
            pipeline_prefix: Prefix used for pipeline components (default: 'PIPE')
        """
        self.graph = graph
        self.pipeline_prefix = pipeline_prefix
        self.removed_nodes = []
        self.removed_edges = []
        self.restored_edges = []

    def identify_pipeline_components(self) -> Dict[str, List[Node]]:
        """
        Identify all pipeline-related components in the graph.

        Returns:
            Dictionary with categorized pipeline components:
            - 'pipeline_registers': Pipeline register nodes
            - 'hazard_comparators': Comparator nodes for hazard detection
            - 'stall_signals': Stall signal nodes
            - 'stall_controllers': Stall controller nodes
            - 'bypass_muxes': Bypass/forwarding muxes
            - 'bypass_comparators': Bypass comparators
            - 'other_pipeline_components': Other nodes marked as pipeline components
        """
        components = {
            'pipeline_registers': [],
            'hazard_comparators': [],
            'stall_signals': [],
            'stall_controllers': [],
            'bypass_muxes': [],
            'bypass_comparators': [],
            'other_pipeline_components': []
        }

        for node in self.graph.nodes.values():
            node_type = node.data.get('type')
            node_resolution = node.data.get('resolution')

            # Check for bypass muxes (may not have pipeline_component flag!)
            if node_type == 'mux' and node_resolution == 'bypass':
                components['bypass_muxes'].append(node)
                logger.debug(f"Found bypass mux: {node.id}")
                continue

            # Check for bypass comparators (may not have pipeline_component flag!)
            if (node_type == 'operation' and
                (node_resolution == 'bypass' or 'bypass' in node.id.lower())):
                components['bypass_comparators'].append(node)
                logger.debug(f"Found bypass comparator: {node.id}")
                continue

            # Check for stall comparators created by hazard resolution (may not have pipeline_component flag!)
            # These are created with IDs like "stall_rf_rd_rs_s2_s1"
            if (node_type == 'operation' and
                'stall' in node.id.lower() and
                node.data.get('operator') == '=='):
                components['stall_signals'].append(node)
                logger.debug(f"Found stall comparator (no pipeline_component flag): {node.id}")
                continue

            # Check for hazard comparators without pipeline_component flag
            # These might be created with IDs containing "hazard" and "cmp"
            if (node_type == 'operation' and
                'hazard' in node.id.lower() and
                'cmp' in node.id.lower()):
                components['hazard_comparators'].append(node)
                logger.debug(f"Found hazard comparator (no pipeline_component flag): {node.id}")
                continue

            # Check if this is a pipeline component (with pipeline_component flag)
            if not node.data.get('pipeline_component'):
                continue

            if node_type == 'pipeline_register':
                components['pipeline_registers'].append(node)
                logger.debug(f"Found pipeline register: {node.id}")

            elif node_type == 'pipeline_stall_controller':
                components['stall_controllers'].append(node)
                logger.debug(f"Found stall controller: {node.id}")

            elif node_type == 'operation':
                # Hazard comparators and stall signals are marked as operations with pipeline_component flag
                if 'hazard' in node.id.lower() and 'cmp' in node.id.lower():
                    components['hazard_comparators'].append(node)
                    logger.debug(f"Found hazard comparator: {node.id}")
                elif 'stall' in node.id.lower():
                    components['stall_signals'].append(node)
                    logger.debug(f"Found stall signal: {node.id}")
                else:
                    # Other pipeline operation
                    components['other_pipeline_components'].append(node)
                    logger.debug(f"Found other pipeline component: {node.id}")

            else:
                # Any other pipeline component
                components['other_pipeline_components'].append(node)
                logger.debug(f"Found other pipeline component: {node.id} (type: {node_type})")

        # Log summary
        logger.info(f"Identified pipeline components:")
        logger.info(f"  - {len(components['pipeline_registers'])} pipeline registers")
        logger.info(f"  - {len(components['hazard_comparators'])} hazard comparators")
        logger.info(f"  - {len(components['stall_signals'])} stall signals")
        logger.info(f"  - {len(components['stall_controllers'])} stall controllers")
        logger.info(f"  - {len(components['bypass_muxes'])} bypass muxes")
        logger.info(f"  - {len(components['bypass_comparators'])} bypass comparators")
        logger.info(f"  - {len(components['other_pipeline_components'])} other pipeline components")

        return components

    def remove_pipeline_register(self, pipeline_reg: Node) -> bool:
        """
        Remove a pipeline register and reconnect its edges.

        Pipeline registers split an edge into two parts:
            source -> pipeline_reg (pipeline_input edge)
            pipeline_reg -> target (original edge type)

        This method removes the register and restores the direct connection:
            source -> target (original edge type)

        Args:
            pipeline_reg: The pipeline register node to remove

        Returns:
            True if successful, False otherwise
        """
        logger.debug(f"Removing pipeline register: {pipeline_reg.id}")

        # Find input edges (edges feeding into the pipeline register)
        input_edges = [e for e in pipeline_reg.incoming_edges
                      if e.data.get('type') == 'pipeline_input']

        # Find output edges (edges coming from the pipeline register)
        output_edges = [e for e in pipeline_reg.outgoing_edges
                       if e.data.get('from_pipeline_reg')]

        if not input_edges:
            logger.warning(f"No input edges found for pipeline register {pipeline_reg.id}")
            return False

        if not output_edges:
            logger.warning(f"No output edges found for pipeline register {pipeline_reg.id}")
            return False

        # For each input-output pair, restore the original connection
        connections_restored = 0
        for input_edge in input_edges:
            source = input_edge.source

            for output_edge in output_edges:
                target = output_edge.target

                # Determine the original edge type
                original_type = output_edge.data.get('original_type',
                                                     output_edge.data.get('type'))

                # Skip if this is a pipeline component edge type
                if original_type == 'pipeline_input':
                    original_type = input_edge.data.get('original_type', 'operand')

                # Create the restored edge with original metadata
                edge_data = {
                    'type': original_type,
                    'restored_from_pipeline': True
                }

                # Copy any additional metadata from the output edge
                for key, value in output_edge.data.items():
                    if key not in ['type', 'pipeline_component', 'from_pipeline_reg',
                                   'gated_by', 'original_type']:
                        edge_data[key] = value

                # Create new edge (Edge constructor automatically adds to nodes)
                new_edge = Edge(source, target, data=edge_data)

                # Add edge to graph
                edge_id = f"{source.id}_to_{target.id}_{original_type}"
                self.graph.edges[edge_id] = new_edge

                self.restored_edges.append(new_edge)
                connections_restored += 1

                logger.debug(f"  Restored edge: {source.id} -> {target.id} (type: {original_type})")

        # Remove all edges connected to the pipeline register
        edges_to_remove = list(pipeline_reg.incoming_edges) + list(pipeline_reg.outgoing_edges)
        for edge in edges_to_remove:
            edge_id = next((eid for eid, e in self.graph.edges.items() if e == edge), None)
            if edge_id:
                del self.graph.edges[edge_id]
            edge.remove_from_nodes()
            self.removed_edges.append(edge)

        # Remove the pipeline register node
        del self.graph.nodes[pipeline_reg.id]
        self.removed_nodes.append(pipeline_reg)

        logger.info(f"  Removed pipeline register {pipeline_reg.id}, restored {connections_restored} connections")
        return True

    def remove_hazard_detector(self, comparator: Node) -> bool:
        """
        Remove a hazard detection comparator and its associated stall signal.

        Args:
            comparator: The comparator node used for hazard detection

        Returns:
            True if successful, False otherwise
        """
        logger.debug(f"Removing hazard detector: {comparator.id}")

        # Find and remove all connected edges
        edges_to_remove = list(comparator.incoming_edges) + list(comparator.outgoing_edges)
        for edge in edges_to_remove:
            edge_id = next((eid for eid, e in self.graph.edges.items() if e == edge), None)
            if edge_id:
                del self.graph.edges[edge_id]
            edge.remove_from_nodes()
            self.removed_edges.append(edge)

        # Remove the comparator node
        del self.graph.nodes[comparator.id]
        self.removed_nodes.append(comparator)

        logger.debug(f"  Removed hazard detector {comparator.id}")
        return True

    def remove_stall_controller(self, controller: Node) -> bool:
        """
        Remove a stall controller node.

        Args:
            controller: The stall controller node to remove

        Returns:
            True if successful, False otherwise
        """
        logger.debug(f"Removing stall controller: {controller.id}")

        # Find and remove all connected edges
        edges_to_remove = list(controller.incoming_edges) + list(controller.outgoing_edges)
        for edge in edges_to_remove:
            edge_id = next((eid for eid, e in self.graph.edges.items() if e == edge), None)
            if edge_id:
                del self.graph.edges[edge_id]
            edge.remove_from_nodes()
            self.removed_edges.append(edge)

        # Remove the controller node
        del self.graph.nodes[controller.id]
        self.removed_nodes.append(controller)

        logger.debug(f"  Removed stall controller {controller.id}")
        return True

    def remove_stall_signal(self, signal: Node) -> bool:
        """
        Remove a stall signal node.

        Args:
            signal: The stall signal node to remove

        Returns:
            True if successful, False otherwise
        """
        logger.debug(f"Removing stall signal: {signal.id}")

        # Find and remove all connected edges
        edges_to_remove = list(signal.incoming_edges) + list(signal.outgoing_edges)
        for edge in edges_to_remove:
            edge_id = next((eid for eid, e in self.graph.edges.items() if e == edge), None)
            if edge_id:
                del self.graph.edges[edge_id]
            edge.remove_from_nodes()
            self.removed_edges.append(edge)

        # Remove the signal node
        del self.graph.nodes[signal.id]
        self.removed_nodes.append(signal)

        logger.debug(f"  Removed stall signal {signal.id}")
        return True

    def remove_bypass_mux(self, mux: Node) -> bool:
        """
        Remove a bypass mux and restore the original data path.

        Bypass muxes intercept the normal data flow to allow forwarding.
        When created, they:
        1. Disconnect original: source -> target
        2. Create: source -> mux (mux_input=0, label='normal')
        3. Create: mux -> target
        4. Add forwarding paths as additional mux inputs

        To remove, we:
        1. Find the normal input (mux_input=0)
        2. Find the output
        3. Reconnect source directly to target
        4. Remove the mux and all its edges

        Args:
            mux: The bypass mux node to remove

        Returns:
            True if successful, False otherwise
        """
        logger.debug(f"Removing bypass mux: {mux.id}")

        # Find the normal data path (mux_input=0)
        normal_input_edge = None
        for edge in mux.incoming_edges:
            if edge.data.get('mux_input') == 0 or edge.data.get('label') == 'normal':
                normal_input_edge = edge
                break

        if not normal_input_edge:
            logger.warning(f"Could not find normal input for bypass mux {mux.id}")
            # Fall back to just removing the mux
            return self.remove_generic_pipeline_component(mux)

        # Find the output edge
        output_edges = [e for e in mux.outgoing_edges
                       if e.data.get('type') != 'control']

        if not output_edges:
            logger.warning(f"Could not find output for bypass mux {mux.id}")
            return self.remove_generic_pipeline_component(mux)

        # Restore the original connection for each output
        connections_restored = 0
        for output_edge in output_edges:
            source = normal_input_edge.source
            target = output_edge.target

            # Determine the original edge type (likely 'assignment')
            original_type = output_edge.data.get('type', 'assignment')

            # Create restored edge
            edge_data = {
                'type': original_type,
                'restored_from_bypass': True
            }

            new_edge = Edge(source, target, data=edge_data)
            edge_id = f"{source.id}_to_{target.id}_{original_type}_restored"
            self.graph.edges[edge_id] = new_edge

            self.restored_edges.append(new_edge)
            connections_restored += 1

            logger.debug(f"  Restored edge: {source.id} -> {target.id} (type: {original_type})")

        # Remove all edges connected to the mux
        edges_to_remove = list(mux.incoming_edges) + list(mux.outgoing_edges)
        for edge in edges_to_remove:
            edge_id = next((eid for eid, e in self.graph.edges.items() if e == edge), None)
            if edge_id:
                del self.graph.edges[edge_id]
            edge.remove_from_nodes()
            self.removed_edges.append(edge)

        # Remove the mux node
        del self.graph.nodes[mux.id]
        self.removed_nodes.append(mux)

        logger.info(f"  Removed bypass mux {mux.id}, restored {connections_restored} connections")
        return True

    def remove_generic_pipeline_component(self, component: Node) -> bool:
        """
        Remove a generic pipeline component (any node with pipeline_component=True).

        Args:
            component: The pipeline component node to remove

        Returns:
            True if successful, False otherwise
        """
        logger.debug(f"Removing generic pipeline component: {component.id}")

        # Find and remove all connected edges
        edges_to_remove = list(component.incoming_edges) + list(component.outgoing_edges)
        for edge in edges_to_remove:
            edge_id = next((eid for eid, e in self.graph.edges.items() if e == edge), None)
            if edge_id:
                del self.graph.edges[edge_id]
            edge.remove_from_nodes()
            self.removed_edges.append(edge)

        # Remove the component node
        del self.graph.nodes[component.id]
        self.removed_nodes.append(component)

        logger.debug(f"  Removed pipeline component {component.id}")
        return True

    def unpipeline(self) -> bool:
        """
        Perform the complete unpipelining transformation.

        This removes all pipeline components and restores the design to
        a single-cycle implementation.

        Returns:
            True if successful, False otherwise
        """
        logger.info("Starting unpipelining transformation...")

        # Identify all pipeline components
        components = self.identify_pipeline_components()

        total_components = sum(len(v) for v in components.values())
        if total_components == 0:
            logger.info("No pipeline components found. Design is already single-cycle.")
            return True

        logger.info(f"Found {total_components} pipeline components to remove")

        # Step 1: Remove pipeline registers (this restores edge connections)
        logger.info("Step 1: Removing pipeline registers...")
        for pipeline_reg in components['pipeline_registers']:
            self.remove_pipeline_register(pipeline_reg)

        # Step 2: Remove hazard detection comparators
        logger.info("Step 2: Removing hazard detection comparators...")
        for comparator in components['hazard_comparators']:
            self.remove_hazard_detector(comparator)

        # Step 3: Remove stall signals
        logger.info("Step 3: Removing stall signals...")
        for signal in components['stall_signals']:
            self.remove_stall_signal(signal)

        # Step 4: Remove stall controllers
        logger.info("Step 4: Removing stall controllers...")
        for controller in components['stall_controllers']:
            self.remove_stall_controller(controller)

        # Step 5: Remove bypass muxes
        logger.info("Step 5: Removing bypass muxes...")
        for mux in components['bypass_muxes']:
            self.remove_bypass_mux(mux)

        # Step 6: Remove bypass comparators
        logger.info("Step 6: Removing bypass comparators...")
        for comparator in components['bypass_comparators']:
            self.remove_hazard_detector(comparator)

        # Step 7: Remove any other pipeline components
        logger.info("Step 7: Removing other pipeline components...")
        for component in components['other_pipeline_components']:
            self.remove_generic_pipeline_component(component)

        # Step 8: Re-infer timing to restore single-cycle behavior
        logger.info("Step 8: Re-inferring timing for single-cycle design...")
        self.graph.infer_uarch_time(force_reinfer=True)

        # Verify that all nodes are now in stage 0 (single cycle)
        max_uarch_time = max((node.uarch_time for node in self.graph.nodes.values()),
                            default=0)

        logger.info(f"Unpipelining complete!")
        logger.info(f"  Removed {len(self.removed_nodes)} nodes")
        logger.info(f"  Removed {len(self.removed_edges)} edges")
        logger.info(f"  Restored {len(self.restored_edges)} connections")
        logger.info(f"  Maximum uarch_time: {max_uarch_time} (0 = single cycle)")

        if max_uarch_time > 0:
            logger.warning(f"Design still has nodes with uarch_time > 0. "
                          f"This may indicate incomplete unpipelining or "
                          f"multi-cycle operations that are not pipeline-related.")

        return True

    def get_statistics(self) -> Dict[str, int]:
        """
        Get statistics about the unpipelining transformation.

        Returns:
            Dictionary with transformation statistics
        """
        return {
            'nodes_removed': len(self.removed_nodes),
            'edges_removed': len(self.removed_edges),
            'edges_restored': len(self.restored_edges)
        }


def apply_unpipelining_optimization(graph: ResourceGraph,
                                   pipeline_prefix: str = 'PIPE') -> bool:
    """
    Apply unpipelining optimization to a resource graph.

    This function removes all pipeline-related components from the graph,
    restoring it to a single-cycle design.

    Args:
        graph: The resource graph to unpipeline
        pipeline_prefix: Prefix used for pipeline components (default: 'PIPE')

    Returns:
        True if successful, False otherwise

    Example:
        >>> from resource_graph import ResourceGraph
        >>> from unpipelining_optimization import apply_unpipelining_optimization
        >>>
        >>> # Load a pipelined design
        >>> graph = ResourceGraph.from_json('pipelined_design.json')
        >>>
        >>> # Remove pipelining
        >>> apply_unpipelining_optimization(graph)
        >>>
        >>> # Save the single-cycle design
        >>> graph.to_json('single_cycle_design.json')
    """
    transform = UnpipelineTransform(graph, pipeline_prefix)
    success = transform.unpipeline()

    if success:
        stats = transform.get_statistics()
        logger.info(f"Unpipelining optimization completed successfully")
        logger.info(f"Statistics: {stats}")
    else:
        logger.error("Unpipelining optimization failed")

    return success


# For integration with optimization framework
class UnpipeliningOptimization:
    """
    Wrapper class for integration with the optimization framework.
    """

    def __init__(self, pipeline_prefix: str = 'PIPE'):
        """
        Initialize the unpipelining optimization.

        Args:
            pipeline_prefix: Prefix used for pipeline components
        """
        self.pipeline_prefix = pipeline_prefix
        self.name = "unpipelining"
        self.priority = 10  # High priority, typically run last to undo pipelining

    def apply(self, graph: ResourceGraph) -> bool:
        """
        Apply the unpipelining optimization to the graph.

        Args:
            graph: The resource graph to transform

        Returns:
            True if successful, False otherwise
        """
        return apply_unpipelining_optimization(graph, self.pipeline_prefix)

    def __str__(self) -> str:
        return f"UnpipeliningOptimization(prefix={self.pipeline_prefix})"
