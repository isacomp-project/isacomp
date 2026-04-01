"""
True pipelining optimization with hazard detection and stalling.

This module implements algorithms to create true instruction pipelines where
multiple instructions can be in flight simultaneously, with automatic hazard
detection and stalling to maintain correctness.

Key concepts:
- Uses uarch_time to determine pipeline cut points
- Tracks dependencies using used_as_index/indexed_by information
- Inserts hazard detection logic for resource conflicts
- Maintains correctness through stalling rather than bypassing
- Adds pipeline stages incrementally (one at a time)
- Generates actual hardware: comparators, hazard signals, stall signals, pipeline enables
"""

from typing import Dict, List, Set, Tuple, Optional, Any
from core.resource_graph import ResourceGraph, Node, Edge
from core.hardware_builders import HardwareBuilderFactory
from core.array_access_utils import ArrayAccessAnalyzer
from core.pipeline_utils import PipelineRegisterBuilder
import math
import re


class PipelineStageSpec:
    """Specification for a single pipeline stage insertion."""

    def __init__(self, cut_location: str, stage_name: str = "", description: str = "", stage_index: Optional[int] = None):
        self.cut_location = cut_location  # Where to insert the pipeline stage
        self.stage_name = stage_name or f"pipeline_stage_{cut_location}"
        self.description = description
        self.stage_index = stage_index  # Pipeline stage index (used for pipe_time)
        self.hazard_detectors = []  # List of hazard detectors for this stage

    def add_hazard_detector(self, source_resource: str, target_resource: str,
                          hazard_type: str, check_condition: str,
                          write_index_node: Optional[Node] = None,
                          read_index_node: Optional[Node] = None):
        """Add a hazard detector for this pipeline stage."""
        # Store node IDs instead of Node objects for JSON serialization
        write_index_node_id = write_index_node.id if write_index_node else None
        read_index_node_id = read_index_node.id if read_index_node else None

        self.hazard_detectors.append({
            'source_resource': source_resource,
            'target_resource': target_resource,
            'hazard_type': hazard_type,  # 'RAW', 'WAR', 'WAW'
            'check_condition': check_condition,
            'write_index_node_id': write_index_node_id,  # ID of node that provides write index
            'read_index_node_id': read_index_node_id     # ID of node that provides read index
        })

    def __str__(self):
        return f"Pipeline stage at {self.cut_location} with {len(self.hazard_detectors)} hazard detectors"


class DependencyAnalysis:
    """Analyzes resource dependencies for hazard detection."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph
        self.resource_reads = {}   # resource_name -> [nodes that read it]
        self.resource_writes = {}  # resource_name -> [nodes that write it]
        self.index_dependencies = {}  # resource[index] dependencies

    def analyze_dependencies(self) -> Dict[str, Any]:
        """Analyze all resource dependencies in the graph."""

        print("\nAnalyzing resource dependencies for hazard detection...")

        # Find all reads and writes to indexed resources
        for node in self.graph.nodes.values():
            self._analyze_node_dependencies(node)

        # Identify potential hazards
        hazards = self._identify_potential_hazards()

        analysis = {
            'resource_reads': self.resource_reads,
            'resource_writes': self.resource_writes,
            'index_dependencies': self.index_dependencies,
            'potential_hazards': hazards
        }

        print(f"  Found {len(self.resource_reads)} resources with reads")
        print(f"  Found {len(self.resource_writes)} resources with writes")
        print(f"  Identified {len(hazards)} potential hazards")

        return analysis

    def _analyze_node_dependencies(self, node: Node):
        """Analyze dependencies for a single node."""

        # Check if this node is an array access (like rf[rs], rf[rt], rf[rd])
        if node.data.get('type') == 'array_access':
            # Use ArrayAccessAnalyzer to parse and classify the access
            analyzer = ArrayAccessAnalyzer(self.graph)

            # Parse the array access name
            node_name = node.data.get('name', node.id)
            parsed = analyzer.parse_array_access_name(node_name)

            if not parsed:
                return

            base_resource, index_part = parsed
            access_key = f"{base_resource}[{index_part}]"

            # Classify the access type
            access_type = analyzer.classify_access_type(node)

            # Find the index node
            index_node = analyzer.find_index_node(node)

            # Process based on access type
            if access_type == 'WRITE':
                # This is a WRITE (e.g., rf[rd] ← res)
                assignment_edges = [e for e in node.incoming_edges if e.data.get('type') == 'assignment']
                for edge in assignment_edges:
                    source = edge.source
                    if base_resource not in self.resource_writes:
                        self.resource_writes[base_resource] = []
                    self.resource_writes[base_resource].append({
                        'node': source,  # The node that produces the value
                        'target': node,
                        'index': index_part,
                        'index_node': index_node,  # The actual node that provides the index
                        'access_key': access_key,
                        'uarch_time': source.uarch_time if hasattr(source, 'uarch_time') else 0
                    })

            elif access_type == 'READ':
                # This is a READ (e.g., rf[rs] → r1)
                assignment_edges = [e for e in node.outgoing_edges if e.data.get('type') == 'assignment']
                for edge in assignment_edges:
                    target = edge.target
                    if base_resource not in self.resource_reads:
                        self.resource_reads[base_resource] = []
                    self.resource_reads[base_resource].append({
                        'node': target,  # The node that reads this value
                        'source_node': node,
                        'index': index_part,
                        'index_node': index_node,  # The actual node that provides the index
                        'access_key': access_key,
                        'uarch_time': target.uarch_time if hasattr(target, 'uarch_time') else 0
                    })

            elif access_type == 'READ_WRITE':
                # This node is both read and written (shared access)
                # Handle writes first
                assignment_in_edges = [e for e in node.incoming_edges if e.data.get('type') == 'assignment']
                for edge in assignment_in_edges:
                    source = edge.source
                    if base_resource not in self.resource_writes:
                        self.resource_writes[base_resource] = []
                    self.resource_writes[base_resource].append({
                        'node': source,
                        'target': node,
                        'index': index_part,
                        'index_node': index_node,
                        'access_key': access_key,
                        'uarch_time': source.uarch_time if hasattr(source, 'uarch_time') else 0
                    })

                # Handle reads
                assignment_out_edges = [e for e in node.outgoing_edges if e.data.get('type') == 'assignment']
                for edge in assignment_out_edges:
                    target = edge.target
                    if base_resource not in self.resource_reads:
                        self.resource_reads[base_resource] = []
                    self.resource_reads[base_resource].append({
                        'node': target,
                        'source_node': node,
                        'index': index_part,
                        'index_node': index_node,
                        'access_key': access_key,
                        'uarch_time': target.uarch_time if hasattr(target, 'uarch_time') else 0
                    })

    def _identify_potential_hazards(self) -> List[Dict]:
        """Identify potential pipeline hazards by checking each read against all writes."""

        hazards = []

        # Check for RAW hazards (Read After Write)
        # Check each indexed read against ALL indexed writes (cross-resource)
        all_reads = []
        all_writes = []

        # Collect all reads and writes from all resources
        for resource_name, reads in self.resource_reads.items():
            for read in reads:
                read['base_resource'] = resource_name
                all_reads.append(read)

        for resource_name, writes in self.resource_writes.items():
            for write in writes:
                write['base_resource'] = resource_name
                all_writes.append(write)

        # Check each read against each write
        for write in all_writes:
            for read in all_reads:
                # Only compare within the same base resource type
                if write['base_resource'] == read['base_resource']:
                    write_time = write.get('uarch_time', 0)
                    read_time = read.get('uarch_time', 0)

                    # Potential RAW hazard if read could follow write
                    if read_time >= write_time:
                        write_index = write.get('index')
                        read_index = read.get('index')

                        # Create condition for when this hazard occurs
                        if write_index and read_index:
                            condition = f"{write_index} == {read_index}"
                        else:
                            condition = None

                        hazards.append({
                            'type': 'RAW',
                            'resource': write['base_resource'],
                            'write_node': write['node'],
                            'read_node': read['node'],
                            'write_index': write_index,
                            'read_index': read_index,
                            'write_index_node': write.get('index_node'),  # Actual node that provides write index
                            'read_index_node': read.get('index_node'),    # Actual node that provides read index
                            'write_access': write['access_key'],
                            'read_access': read['access_key'],
                            'write_time': write_time,
                            'read_time': read_time,
                            'condition': condition
                        })

        return hazards


class PipelineTransform:
    """Transforms a graph to add pipeline stages with hazard detection."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph
        self.pipeline_prefix = "PIPE"  # Prefix for all pipeline components
        self.stage_counter = 0
        self.initial_analysis = None  # Cache of initial dependency analysis
        self.created_hazard_detectors = set()  # Track which hazard detectors we've created
        self.hw_factory = HardwareBuilderFactory(graph)  # Hardware builder factory
        self.pipeline_builder = PipelineRegisterBuilder(graph)  # Pipeline register builder
        self.explicit_stage_order = None  # Explicit stage order override
        self.explicit_stage_indices = None  # Explicit stage indices (dict: stage_name -> stage_index)

    def set_stage_order(self, stage_order: List[str], stage_indices: dict = None):
        """Set explicit stage order for validity signal creation.

        Use this when uarch_time inference produces incorrect stage ordering.

        Args:
            stage_order: List of stage names in pipeline order (e.g., ['Decode', 'Execute', 'Memory', 'Writeback'])
            stage_indices: Optional dict mapping stage names to their pipe_time indices (e.g., {'Decode': 1, 'Execute': 2, ...})
        """
        self.explicit_stage_order = stage_order
        self.explicit_stage_indices = stage_indices

    def _sanitize_for_verilog(self, identifier: str) -> str:
        """Sanitize an identifier for use in Verilog (remove brackets, etc.)."""
        sanitized = identifier.replace('[', '_').replace(']', '_').replace(':', '_')
        sanitized = sanitized.replace('(', '_').replace(')', '_').replace(' ', '_')
        sanitized = sanitized.replace("'", '_').replace('{', '_').replace('}', '_')
        sanitized = sanitized.replace(',', '_').replace('?', '_')
        sanitized = sanitized.replace('+', 'add').replace('-', 'sub')
        sanitized = sanitized.replace('*', 'mul').replace('/', 'div')
        sanitized = sanitized.replace('&', 'and').replace('|', 'or').replace('^', 'xor')
        sanitized = sanitized.replace('>>>', 'srlgt').replace('<<', 'sll').replace('>>', 'srl')
        sanitized = sanitized.replace('<', 'lt').replace('>', 'gt').replace('=', 'eq')
        sanitized = sanitized.replace('!', 'not').replace('~', 'inv')
        # Remove leading/trailing underscores and double underscores
        while '__' in sanitized:
            sanitized = sanitized.replace('__', '_')
        sanitized = sanitized.strip('_')
        return sanitized

    def _infer_width_from_incoming_edges(self, node: Node, depth: int = 0) -> Optional[int]:
        """
        Infer bit width from incoming assignment/bit_access edges.

        For var nodes that don't have explicit bit_width, we can often infer
        the width from their source (e.g., a bit_slice that assigns to them).
        """
        if depth > 5:  # Prevent infinite recursion
            return None

        node_type = node.data.get('type')

        # For concatenation nodes, sum widths of all components
        if node_type == 'concatenation':
            total_width = 0
            expr = node.data.get('expression', {})
            if isinstance(expr, dict) and expr.get('type') == 'concatenation':
                # ISA parser uses 'parts'; memory_access_transform may use 'expressions'
                components = expr.get('parts') or expr.get('expressions') or expr.get('components', [])
                for comp in components:
                    if comp.get('type') == 'repetition':
                        count = comp.get('count', 1)
                        # Get width of inner expression
                        inner = comp.get('expression', {})
                        inner_width = inner.get('width', inner.get('bit_width', 1))
                        total_width += count * inner_width
                    elif comp.get('type') == 'bit_slice':
                        if 'range' in comp:
                            high, low = comp['range']
                            total_width += (high - low + 1)
                        else:
                            total_width += 1
                    elif comp.get('type') == 'literal':
                        total_width += comp.get('width', comp.get('bit_width', 32))
                    elif comp.get('type') == 'identifier':
                        # Try to get width from the referenced node
                        ref_id = comp.get('name')
                        if ref_id and ref_id in self.graph.nodes:
                            ref_node = self.graph.nodes[ref_id]
                            ref_width = ref_node.data.get('bit_width') or ref_node.data.get('width')
                            if ref_width:
                                total_width += ref_width
                            else:
                                total_width += 32  # Default
                        else:
                            total_width += 32  # Default
                    else:
                        total_width += comp.get('width', comp.get('bit_width', 32))
                if total_width > 0:
                    return total_width

            # Fallback: sum widths from incoming concatenation_input edges
            if total_width == 0:
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'concatenation_input':
                        source = edge.source
                        src_width = source.data.get('bit_width') or source.data.get('width')
                        if src_width:
                            total_width += src_width
                if total_width > 0:
                    return total_width

        # For multiplexer nodes, infer width from mux inputs (max of all non-default)
        if node_type == 'multiplexer':
            best_width = None
            for edge in node.incoming_edges:
                # Mux inputs have 'position' attribute or mux_input type
                if edge.data.get('position') is not None or edge.data.get('type') == 'mux_input':
                    source = edge.source
                    # Check explicit width on source
                    if source.data.get('bit_width'):
                        src_width = source.data['bit_width']
                        if src_width and src_width != 32:
                            if best_width is None or src_width > best_width:
                                best_width = src_width
                    elif source.data.get('width'):
                        src_width = source.data['width']
                        if src_width and src_width != 32:
                            if best_width is None or src_width > best_width:
                                best_width = src_width
                    else:
                        # Recursively infer from source
                        src_width = self._infer_width_from_incoming_edges(source, depth + 1)
                        if src_width and src_width != 32:
                            if best_width is None or src_width > best_width:
                                best_width = src_width
            if best_width:
                return best_width

        for edge in node.incoming_edges:
            if edge.data.get('type') in ['assignment', 'bit_access']:
                source = edge.source
                source_type = source.data.get('type')

                # Check explicit width
                if source.data.get('bit_width'):
                    return source.data['bit_width']

                # Check bit_slice source
                if source_type == 'bit_slice':
                    # Check ILA format
                    if 'high_bit' in source.data and 'low_bit' in source.data:
                        return source.data['high_bit'] - source.data['low_bit'] + 1
                    # Check slice_high/slice_low format
                    elif 'slice_high' in source.data and 'slice_low' in source.data:
                        return source.data['slice_high'] - source.data['slice_low'] + 1
                    # Check expression with range
                    else:
                        expr = source.data.get('expression', {})
                        if expr.get('type') == 'bit_slice' and 'range' in expr:
                            high, low = expr['range']
                            return high - low + 1

                # Recursively check source
                result = self._infer_width_from_incoming_edges(source, depth + 1)
                if result and result != 32:
                    return result

        return None

    def add_multiple_pipeline_stages(self, cut_specs: List[Dict]) -> bool:
        """
        Add multiple pipeline stages at once, using a single dependency analysis.

        This is the preferred method when creating multi-stage pipelines through the GUI,
        as it avoids confusing intermediate error messages.

        Args:
            cut_specs: List of dicts with 'edges' (list of edge IDs to cut)

        Returns:
            True if all stages were added successfully
        """
        if not cut_specs:
            print("No cut specifications provided")
            return False

        print(f"\nAdding {len(cut_specs)} pipeline stages at once...")

        # Perform dependency analysis ONCE on the original graph
        print("\nAnalyzing dependencies on original graph...")
        dependency_analysis = DependencyAnalysis(self.graph)
        self.initial_analysis = dependency_analysis.analyze_dependencies()

        # For multi-stage insertion, DO NOT create hazard detectors automatically
        # The new hazard resolution GUI will handle creating stall/bypass logic
        # after the user makes their choices
        # Create all stage specifications using the initial analysis
        stage_specs = []
        for i, cut_spec in enumerate(cut_specs):
            edges_to_cut = cut_spec.get('edges', [])

            # Use the user-provided stage name from GUI, or fall back to auto-generated
            # The cut is AFTER the 'before_stage', so this cut creates the register
            # that feeds into 'after_stage'
            after_stage_name = cut_spec.get('after_stage')
            if after_stage_name:
                stage_name = after_stage_name
            else:
                stage_name = f"{self.pipeline_prefix}_stage_{i}"

            # Get stage_index from cut_spec (if provided)
            stage_index = cut_spec.get('stage_index')

            # For now, we'll use a placeholder cut location
            # The actual cuts will be based on the edge IDs
            stage_spec = PipelineStageSpec(
                cut_location=f"multi_cut_{i}",
                stage_name=stage_name,
                description=f"Pipeline stage {stage_name}",
                stage_index=stage_index
            )
            stage_spec.edges_to_cut = edges_to_cut

            # NOTE: Hazard detectors are NO LONGER added here automatically
            # The hazard resolution GUI (hazard_resolution.py) will handle this
            # based on user's choice of stall vs bypass strategies
            # if i == 0:
            #     self._add_hazard_detectors(stage_spec, self.initial_analysis)
            stage_specs.append(stage_spec)

        # Now insert all stages
        print(f"\nInserting {len(stage_specs)} pipeline stages...")

        # Collect edge metadata BEFORE any cuts happen
        # This allows the same edge to be selected for multiple cuts
        print("\nCollecting edge metadata before cutting...")
        self.original_edge_info = {}
        for edge_id, edge in self.graph.edges.items():
            self.original_edge_info[edge_id] = {
                'source_id': edge.source.id,
                'target_id': edge.target.id,
                'type': edge.data.get('type')
            }

        # Track the first stage's stall nodes to share across all stages
        shared_stall_nodes = None
        shared_hazard_unit = None

        for i, stage_spec in enumerate(stage_specs):
            print(f"\n  Stage {i+1}/{len(stage_specs)}: {stage_spec.stage_name}")

            # Create pipeline register name PREFIX (not an actual node)
            # Individual registers will be created for each signal being pipelined
            pipeline_reg_prefix = f"{self.pipeline_prefix}_{stage_spec.stage_name}_reg"

            # DON'T create stall signals or controllers during pipeline insertion
            # The hazard resolution GUI will create them later if the user chooses stalling
            # This keeps the graph clean until we know what resolution strategies are needed
            stall_controller = None

            # Insert pipeline cuts at specified edges
            if hasattr(stage_spec, 'edges_to_cut'):
                success = self._insert_pipeline_cuts_at_edges(
                    stage_spec, pipeline_reg_prefix, stall_controller, stage_spec.edges_to_cut
                )
            else:
                success = self._insert_pipeline_cuts(stage_spec, pipeline_reg_prefix, stall_controller)

            if not success:
                print(f"    Failed to insert stage {i+1}")
                return False

            self.stage_counter += 1
            print(f"    Successfully inserted stage {stage_spec.stage_name}")

        # Re-infer timing once at the end
        print("\nRe-inferring timing for complete pipeline...")
        self.graph.infer_uarch_time(force_reinfer=True)
        self.graph.infer_pipe_time(force_reinfer=True)

        # Add validity signals for bubble injection
        print("\nAdding validity signals for pipeline stages...")
        self._add_validity_signals()

        # Re-infer pipe_time after adding validity signals
        print("\nRe-inferring pipe_time after validity signal creation...")
        self.graph.infer_pipe_time(force_reinfer=True)

        print(f"\n✓ Successfully added all {len(stage_specs)} pipeline stages")
        return True

    def _add_validity_signals(self):
        """Add validity signals for each pipeline stage.

        Validity signals are used to:
        1. Mark bubbles (invalid instructions) in the pipeline
        2. Gate ISA state updates (RF writes, memory writes)
        3. Support pipeline flushing for branches
        """
        print("\n" + "=" * 70)
        print("ADDING PIPELINE VALIDITY SIGNALS")
        print("=" * 70)

        # Find all pipeline stages by looking at pipeline register names
        # PIPE_{stage}_{signal}_PIPE
        stage_names = set()
        for node_id, node in self.graph.nodes.items():
            if node.data.get('type') == 'pipeline_register' and node_id.startswith('PIPE_') and node_id.endswith('_PIPE'):
                parts = node_id.split('_')
                if len(parts) >= 3:
                    stage_names.add(parts[1])

        if not stage_names:
            print("  No pipeline stages found")
            return

        # Sort stages by pipe_time (preferred) or uarch_time of their pipeline registers
        # Each stage's registers have a pipe_time that indicates their pipeline depth
        # Earlier stages have lower pipe_time values
        stage_min_times = {}
        for node_id, node in self.graph.nodes.items():
            if node.data.get('type') == 'pipeline_register' and node_id.startswith('PIPE_') and node_id.endswith('_PIPE'):
                parts = node_id.split('_')
                if len(parts) >= 3:
                    stage = parts[1]
                    # Use pipe_time (preferred) or uarch_time to determine stage order
                    # Fall back to counting _PIPE suffixes if neither available
                    ptime = getattr(node, 'pipe_time', None)
                    utime = getattr(node, 'uarch_time', None)
                    if ptime is not None:
                        time_val = ptime
                        time_source = 'pipe_time'
                    elif utime is not None:
                        time_val = utime
                        time_source = 'uarch_time'
                    else:
                        # Count _PIPE suffixes as fallback
                        time_val = 0
                        temp = node_id
                        while temp.endswith('_PIPE'):
                            time_val += 1
                            temp = temp[:-5]
                        time_source = 'suffix_count'
                    if stage not in stage_min_times or time_val < stage_min_times[stage]:
                        stage_min_times[stage] = time_val
                        if stage in ['Decode', 'Execute', 'MemoryWriteback']:  # Debug key stages
                            print(f"  DEBUG: {stage} min_time={time_val} from {node_id} ({time_source}={ptime if time_source=='pipe_time' else utime})")

        # Use explicit stage order if set, otherwise infer from uarch_time
        if self.explicit_stage_order:
            # Use explicit order, assign depths based on provided indices or position
            if self.explicit_stage_indices:
                # Use the explicit stage indices (pipe_time values from PipelineCut.stage_index)
                stage_order = [(s, self.explicit_stage_indices[s]) for s in self.explicit_stage_order if s in stage_names and s in self.explicit_stage_indices]
                print(f"  Using explicit stage order with indices: {[(s, i) for s, i in stage_order]}")
            else:
                # Fall back to enumerate (old behavior)
                stage_order = [(s, i) for i, s in enumerate(self.explicit_stage_order) if s in stage_names]
                print(f"  Using explicit stage order: {[s[0] for s in stage_order]}")
        else:
            stage_order = []
            for stage in stage_names:
                time_val = stage_min_times.get(stage, 999)
                stage_order.append((stage, time_val))

            stage_order.sort(key=lambda x: x[1])
            print(f"  Found {len(stage_order)} pipeline stages: {[s[0] for s in stage_order]}")

        # Create validity signal for each stage
        # These will be pipeline registers that propagate validity through the pipeline
        valid_signals = {}
        prev_valid = None

        for stage_name, depth in stage_order:
            valid_id = f"PIPE_{stage_name}_valid_PIPE"
            valid_node = Node(valid_id, data={
                'type': 'pipeline_register',
                'name': valid_id,
                'display_name': f'{stage_name} valid',
                'bit_width': 1,
                'pipeline_component': True
            })
            # Set pipe_time and uarch_time to match pipeline register timing
            # depth is already the correct pipe_time from stage_index
            valid_node.pipe_time = depth
            valid_node.uarch_time = depth
            self.graph.add_node(valid_node)
            valid_signals[stage_name] = valid_node
            print(f"  Created validity signal: {valid_id}")

            # Connect to previous stage's validity (or constant 1 for first stage)
            if prev_valid:
                edge = Edge(prev_valid, valid_node, data={
                    'type': 'pipeline_input',
                    'pipeline_component': True
                })
                self.graph.add_edge(edge)
            else:
                # First stage gets constant 1 (valid)
                # Use type 'literal' to match ISA parser conventions (not 'constant')
                const_valid = Node('const_valid_1', data={
                    'type': 'literal',
                    'value': 1,
                    'bit_width': 1,
                    'name': 'const_valid_1'
                })
                if 'const_valid_1' not in self.graph.nodes:
                    self.graph.add_node(const_valid)
                edge = Edge(self.graph.nodes['const_valid_1'], valid_node, data={
                    'type': 'pipeline_input',
                    'pipeline_component': True
                })
                self.graph.add_edge(edge)

            prev_valid = valid_node

        # Now we need to:
        # 1. When stalling, inject bubble (validity=0) into next stage
        # 2. Gate RF writes with validity of the write stage

        # Find stall controller
        stall_ctrl = None
        for node_id, node in self.graph.nodes.items():
            if 'stall_ctrl' in node_id and 'stall_controller' in node.data.get('type', ''):
                stall_ctrl = node
                break

        # Connect stall controller to ALL Decode->Execute pipeline registers
        # This ensures that when stalling, ALL Execute registers hold their values
        if stall_ctrl and len(stage_order) >= 2:
            first_stage = stage_order[0][0]  # Decode
            second_stage = stage_order[1][0]  # Execute
            stall_count = 0
            for node_id, node in self.graph.nodes.items():
                # Check if this is an Execute-stage pipeline register (PIPE_Execute_*_PIPE)
                # Use NAME pattern instead of type - this catches all Execute pipeline registers
                # including operand registers that might not have is_uarch_state set
                # But NOT Memory or Writeback propagated ones (PIPE_Memory_PIPE_Execute_*_PIPE_PIPE)
                # Pattern: starts with PIPE_Execute_ and ends with _PIPE (single _PIPE at end)
                # ALSO exclude validity signals - they should NOT be gated (need to inject bubbles)
                if node_id.startswith(f'PIPE_{second_stage}_') and node_id.endswith('_PIPE') and not node_id.endswith('_PIPE_PIPE') and not node_id.endswith('_valid_PIPE'):
                    # Check if already has a stall edge
                    has_stall_edge = any(e.data.get('type') == 'stall' for e in node.incoming_edges)
                    if not has_stall_edge:
                        stall_edge = Edge(stall_ctrl, node, data={
                            'type': 'stall',
                            'description': f'Gate {second_stage} pipeline register when stalling'
                        })
                        self.graph.add_edge(stall_edge)
                        stall_count += 1
                        # Verify edge was added
                        stall_in_incoming = any(e.data.get('type') == 'stall' for e in node.incoming_edges)
                        if not stall_in_incoming:
                            print(f"  ERROR: Stall edge not added to {node_id}!")
            if stall_count > 0:
                print(f"  Connected stall controller to {stall_count} additional {second_stage} pipeline registers")
                # Verify a sample node
                sample_node = self.graph.nodes.get(f'PIPE_{second_stage}_add_enable_PIPE')
                if sample_node:
                    edge_types = [e.data.get('type') for e in sample_node.incoming_edges]
                    print(f"  Verification: PIPE_{second_stage}_add_enable_PIPE edges: {edge_types}")

        # Also connect stall controller to certain Memory-stage registers that need bubble injection
        # Specifically: branch/jump result registers that feed the PC mux
        # These contain computed PC targets, and when not valid, should output safe defaults (0)
        if stall_ctrl and len(stage_order) >= 3:
            third_stage = stage_order[2][0]  # Memory
            branch_stall_count = 0
            for node_id, node in self.graph.nodes.items():
                if node.is_uarch_state or node.data.get('type') == 'pipeline_register':
                    # Check if this is a Memory-stage branch/jump result register
                    # Pattern: PIPE_Memory_*_branch_dest_*_PIPE or PIPE_Memory_*_jump_dest_PIPE
                    # But NOT further propagated ones (PIPE_Writeback_PIPE_Memory_...)
                    if (node_id.startswith(f'PIPE_{third_stage}_') and
                        node_id.endswith('_PIPE') and
                        not node_id.endswith('_PIPE_PIPE') and
                        ('_branch_dest_' in node_id or '_jump_dest' in node_id)):
                        # Check if already has a stall edge
                        has_stall_edge = any(e.data.get('type') == 'stall' for e in node.incoming_edges)
                        if not has_stall_edge:
                            stall_edge = Edge(stall_ctrl, node, data={
                                'type': 'stall',
                                'description': f'Inject bubble into {third_stage} branch/jump result when stalling'
                            })
                            self.graph.add_edge(stall_edge)
                            branch_stall_count += 1
            if branch_stall_count > 0:
                print(f"  Connected stall controller to {branch_stall_count} {third_stage} branch/jump result registers")

        # Add valid gating for Memory-stage result pipeline registers
        # When Execute has a bubble (valid=0), we shouldn't update Memory result registers
        # with garbage values computed by the bubble
        if len(stage_order) >= 3:
            second_stage = stage_order[1][0]  # Execute
            third_stage = stage_order[2][0]  # Memory

            # Find the Execute valid signal
            execute_valid_node = valid_signals.get(second_stage)

            if execute_valid_node:
                valid_gate_count = 0
                for node_id, node in self.graph.nodes.items():
                    if node.is_uarch_state or node.data.get('type') == 'pipeline_register':
                        # Check if this is a Memory-stage result register
                        # Pattern: PIPE_Memory_*_res_PIPE but NOT propagated ones (_PIPE_PIPE)
                        # Also include other computation results like lb_addr, sb_addr, etc.
                        if (node_id.startswith(f'PIPE_{third_stage}_') and
                            node_id.endswith('_PIPE') and
                            not node_id.endswith('_PIPE_PIPE') and
                            not node_id.endswith('_valid_PIPE')):

                            # These are result registers computed in Execute and piped to Memory
                            # They should be gated by Execute valid to avoid garbage from bubbles
                            # Exclude: propagated control signals (those come from pipeline regs, not combinational)

                            # Check the source of this register - if it's from a pipeline register, skip
                            # (propagated signals don't need valid gating)
                            is_propagated = False
                            for incoming_edge in node.incoming_edges:
                                if incoming_edge.data.get('type') == 'pipeline_input':
                                    source = incoming_edge.source
                                    if source.data.get('type') == 'pipeline_register':
                                        is_propagated = True
                                        break

                            if not is_propagated:
                                # Check if already has a valid_gate edge
                                has_valid_gate = any(e.data.get('type') == 'valid_gate' for e in node.incoming_edges)
                                if not has_valid_gate:
                                    valid_gate_edge = Edge(execute_valid_node, node, data={
                                        'type': 'valid_gate',
                                        'description': f'Gate {third_stage} result register by {second_stage} valid'
                                    })
                                    self.graph.add_edge(valid_gate_edge)
                                    valid_gate_count += 1

                if valid_gate_count > 0:
                    print(f"  Added valid gating for {valid_gate_count} {third_stage} result registers")

        # Also connect stall controller to Fetch->Decode pipeline registers (with hold behavior)
        # When Decode stalls, upstream stages should also stall (hold their values)
        if stall_ctrl and len(stage_order) >= 1:
            first_stage = stage_order[0][0]  # Decode
            hold_count = 0
            for node_id, node in self.graph.nodes.items():
                if node.is_uarch_state or node.data.get('type') == 'pipeline_register':
                    # Check if this is a Decode-stage pipeline register (PIPE_Decode_*_PIPE)
                    # These are registers entering the Decode stage (from Fetch)
                    if node_id.startswith(f'PIPE_{first_stage}_') and node_id.endswith('_PIPE') and not node_id.endswith('_PIPE_PIPE'):
                        # Skip validity signal - it should NOT be held
                        if node_id.endswith('_valid_PIPE'):
                            continue
                        # Check if already has a stall edge
                        has_stall_edge = any(e.data.get('type') == 'stall' for e in node.incoming_edges)
                        if not has_stall_edge:
                            stall_edge = Edge(stall_ctrl, node, data={
                                'type': 'stall',
                                'hold': True,  # Hold behavior, not bubble injection
                                'description': f'Hold {first_stage} pipeline register when stalling'
                            })
                            self.graph.add_edge(stall_edge)
                            hold_count += 1
            if hold_count > 0:
                print(f"  Connected stall controller to {hold_count} {first_stage} pipeline registers (hold behavior)")

        if stall_ctrl and len(stage_order) >= 2:
            # When stalling Decode, the Execute stage should get an invalid instruction (bubble)
            # This means we need to modify the validity signal input
            # The next stage validity should be: prev_valid AND NOT stall
            first_stage = stage_order[0][0]
            second_stage = stage_order[1][0] if len(stage_order) > 1 else None

            if second_stage and second_stage in valid_signals:
                # Create: second_stage_valid = first_stage_valid AND NOT stall
                # When stalling, second_stage_valid becomes 0 (bubble)
                not_stall_id = f"{stall_ctrl.id}_not"
                if not_stall_id not in self.graph.nodes:
                    not_stall = Node(not_stall_id, data={
                        'type': 'operation',
                        'operator': '!',
                        'name': not_stall_id
                    })
                    self.graph.add_node(not_stall)
                    edge = Edge(stall_ctrl, not_stall, data={'type': 'operand'})
                    self.graph.add_edge(edge)

                # Create AND gate: prev_valid AND NOT stall
                and_id = f"PIPE_{second_stage}_valid_and_not_stall"
                and_node = Node(and_id, data={
                    'type': 'operation',
                    'operator': '&&',
                    'name': and_id
                })
                self.graph.add_node(and_node)

                # Connect inputs to AND
                # First, remove existing edge from const_valid_1 to second_stage valid
                second_valid = valid_signals[second_stage]
                for edge in list(second_valid.incoming_edges):
                    if edge.data.get('type') == 'pipeline_input':
                        edge.remove_from_nodes()
                        if edge.id in self.graph.edges:
                            del self.graph.edges[edge.id]

                # prev_valid -> AND left
                if first_stage in valid_signals:
                    edge1 = Edge(valid_signals[first_stage], and_node, data={
                        'type': 'left_operand',
                        'position': 'left'
                    })
                    self.graph.add_edge(edge1)
                else:
                    # Use const 1
                    edge1 = Edge(self.graph.nodes['const_valid_1'], and_node, data={
                        'type': 'left_operand',
                        'position': 'left'
                    })
                    self.graph.add_edge(edge1)

                # NOT stall -> AND right
                edge2 = Edge(self.graph.nodes[not_stall_id], and_node, data={
                    'type': 'right_operand',
                    'position': 'right'
                })
                self.graph.add_edge(edge2)

                # AND -> second_valid
                edge3 = Edge(and_node, second_valid, data={
                    'type': 'pipeline_input',
                    'pipeline_component': True
                })
                self.graph.add_edge(edge3)

                print(f"  Bubble injection: {second_stage}_valid = {first_stage}_valid AND NOT stall")

        # Also gate PC updates with stall signal
        # When stalling, PC should NOT be updated (Fetch stage holds)
        if stall_ctrl:
            pc_wr_node = self.graph.nodes.get('pc_wr')
            if pc_wr_node:
                stall_edge = Edge(stall_ctrl, pc_wr_node, data={
                    'type': 'stall',
                    'description': 'Gate PC update when stalling'
                })
                self.graph.add_edge(stall_edge)
                print(f"  PC gating: pc_rd held when stalling")

        # Gate memory write enables with validity of the appropriate write stage
        # rf writes happen at Writeback (last stage), dmem writes happen at Memory (second to last)
        if stage_order:
            # Build stage name to index mapping
            stage_name_to_idx = {name: idx for idx, (name, _) in enumerate(stage_order)}

            # Find all memory write port nodes and gate their write enables
            # Debug: list all write port nodes we find
            write_ports_found = [(n.id, n.data.get('type'), n.data.get('combined_write_enable'), n.data.get('base_memory'))
                                 for n in self.graph.nodes.values()
                                 if n.data.get('type') == 'memory_write_port']
            print(f"  DEBUG: Found {len(write_ports_found)} memory_write_port nodes: {write_ports_found}")

            for write_port in list(self.graph.nodes.values()):
                if write_port.data.get('type') != 'memory_write_port':
                    continue

                # Get the combined write enable from the write port node's data
                write_enable_name = write_port.data.get('combined_write_enable')
                if not write_enable_name:
                    continue

                # Get the combined write enable name
                base_memory = write_port.data.get('base_memory', '')

                # Flag to track if we should skip validity gating
                # (set when memory writes are controlled by a cache's write_through_req)
                skip_validity_gating = False

                # Check if this memory has a cache - if so, redirect enables
                # The memory's write enable should come from cache's write_through_req
                # The cache uses the original store enables
                cache_name = write_port.data.get('cache_name')

                # If this IS a cache write-through port, skip validity gating entirely
                # The cache has already validated the write at input time (via write_req)
                # and the write_through_req is a state machine output that fires asynchronously
                # to the pipeline stage validity
                if cache_name:
                    cache_node = self.graph.nodes.get(cache_name)
                    if cache_node:
                        # Get the original store enables timing and apply to cache_wt_enable
                        original_enable_name = cache_node.data.get('combined_write_enable')
                        original_enable = self.graph.nodes.get(original_enable_name)
                        write_enable_node = self.graph.nodes.get(write_enable_name)
                        if original_enable and write_enable_node and original_enable.pipe_time is not None:
                            write_enable_node.pipe_time = original_enable.pipe_time
                            write_enable_node.uarch_time = getattr(original_enable, 'uarch_time', original_enable.pipe_time)
                            print(f"  Set timing for {write_enable_name}: pipe_time={write_enable_node.pipe_time} (from {original_enable_name})")
                    print(f"  Skipping validity gating for cache write-through port {write_port.id} (cache handles validation)")
                    continue  # Skip to next write port - no validity gating needed

                if not cache_name and base_memory:
                    # This is the memory's own write port - check if it has a cache
                    memory_node = self.graph.nodes.get(base_memory)
                    if memory_node:
                        # Look for cache write-through port connected to this memory
                        for edge in memory_node.incoming_edges:
                            if edge.data.get('type') == 'memory_write':
                                source = edge.source
                                if source.data.get('type') == 'memory_write_port' and source.data.get('cache_name'):
                                    # Found cache write-through port - get the cache's write_through_req
                                    cache_name = source.data.get('cache_name')
                                    cache_wt_req = f"{cache_name}_write_through_req"
                                    wt_req_node = self.graph.nodes.get(cache_wt_req)
                                    if wt_req_node:
                                        # Copy timing from ORIGINAL store enables (stored in cache node)
                                        # NOT from cache_wt_enable which doesn't have timing yet
                                        cache_node = self.graph.nodes.get(cache_name)
                                        if cache_node:
                                            original_enable_name = cache_node.data.get('combined_write_enable')
                                            original_enable = self.graph.nodes.get(original_enable_name)
                                            if original_enable and original_enable.pipe_time is not None:
                                                wt_req_node.pipe_time = original_enable.pipe_time
                                                wt_req_node.uarch_time = getattr(original_enable, 'uarch_time', original_enable.pipe_time)
                                                print(f"  Copied timing to {cache_wt_req}: pipe_time={wt_req_node.pipe_time} (from {original_enable_name})")
                                        # Redirect memory's enable to use cache's write_through_req
                                        print(f"  Redirecting {write_port.id} enable: {write_enable_name} -> {cache_wt_req} (cache controls memory writes)")
                                        write_enable_name = cache_wt_req
                                        write_port.data['combined_write_enable'] = cache_wt_req
                                        # Skip validity gating - cache FSM controls write-through timing
                                        # Once cache captures write data, write-through must complete
                                        # regardless of pipeline flush/validity state
                                        skip_validity_gating = True
                                    break

                # Find the write enable node - first try by name from combined_write_enable
                write_enable = self.graph.nodes.get(write_enable_name)

                if not write_enable:
                    # The graph_merger may have renamed a node's .id without updating the dict key
                    # Search all nodes to find one with matching .id
                    for node in self.graph.nodes.values():
                        if node.id == write_enable_name:
                            write_enable = node
                            break

                if not write_enable:
                    # Look for incoming edges to write_port that represent write enable
                    for edge in write_port.incoming_edges:
                        if edge.data.get('type') == 'write_enable':
                            write_enable = edge.source
                            write_enable_name = write_enable.id
                            break

                if not write_enable:
                    continue

                # Find the deepest pipelined version of write_enable
                # This ensures we use the output of the pipeline register for validity gating
                best_enable = write_enable
                visited = set()
                def find_deepest_pipelined(current):
                    nonlocal best_enable
                    if current.id in visited:
                        return
                    visited.add(current.id)

                    # If this is a pipeline register, use it
                    if current.data.get('type') == 'pipeline_register':
                        best_enable = current

                    for edge in current.outgoing_edges:
                        target = edge.target
                        if target.data.get('type') == 'pipeline_register':
                            find_deepest_pipelined(target)

                find_deepest_pipelined(write_enable)
                write_enable = best_enable

                # Determine which stage this write happens in by using the write_enable's pipe_time
                # The deepest pipelined write_enable tells us when the write actually occurs
                write_stage = None
                # Prefer pipe_time (explicit stage assignment), fall back to uarch_time
                write_time = getattr(write_enable, 'pipe_time', None)
                if write_time is None:
                    write_time = getattr(write_enable, 'uarch_time', None)
                    # For pipeline registers using uarch_time, add 1 for output time
                    if write_enable.data.get('type') == 'pipeline_register' and write_time is not None:
                        write_time = write_time + 1

                if write_time is not None:
                    # Find the stage with matching pipe_time (preferred) or uarch_time
                    for stage_name, valid_node in valid_signals.items():
                        valid_time = getattr(valid_node, 'pipe_time', None)
                        if valid_time is None:
                            valid_time = getattr(valid_node, 'uarch_time', None)
                        if valid_time is not None and valid_time == write_time:
                            write_stage = stage_name
                            break

                # If no exact match, find the stage with the closest time <= write_time
                if write_stage is None and write_time is not None:
                    best_stage = None
                    best_time = -1
                    for stage_name, valid_node in valid_signals.items():
                        valid_time = getattr(valid_node, 'pipe_time', None)
                        if valid_time is None:
                            valid_time = getattr(valid_node, 'uarch_time', None)
                        if valid_time is not None and valid_time <= write_time and valid_time > best_time:
                            best_time = valid_time
                            best_stage = stage_name
                    if best_stage:
                        write_stage = best_stage
                        print(f"  Note: {write_port.id} write_enable (time={write_time}) mapped to {write_stage} (time={best_time})")

                # Last resort: use the last stage
                if write_stage is None:
                    write_stage = stage_order[-1][0] if stage_order else None
                    print(f"  Warning: Could not determine stage for {write_port.id} (write_enable time={write_time}), using last stage {write_stage}")

                if write_stage is None or write_stage not in valid_signals:
                    print(f"  Warning: No validity signal for write stage, skipping {write_port.id}")
                    continue

                # Skip validity gating if memory writes are controlled by cache FSM
                # Cache write-through must complete once started, regardless of pipeline state
                if skip_validity_gating:
                    print(f"  Skipping validity gating for {write_port.id} (cache controls write-through timing)")
                    continue

                # Create: write_enable_gated = write_enable AND stage_valid
                and_id = f"{write_enable_name}_valid_gated"
                and_node = Node(and_id, data={
                    'type': 'operation',
                    'operator': '&&',
                    'name': and_id,
                    'display_name': f'{write_enable_name} (valid gated)'
                })
                self.graph.add_node(and_node)

                # Move write_enable's outgoing edges to the AND node
                for edge in list(write_enable.outgoing_edges):
                    # Redirect to come from and_node instead
                    new_edge = Edge(and_node, edge.target, data=edge.data.copy())
                    self.graph.add_edge(new_edge)
                    edge.remove_from_nodes()
                    if edge.id in self.graph.edges:
                        del self.graph.edges[edge.id]

                # Connect write_enable and validity to AND
                edge1 = Edge(write_enable, and_node, data={
                    'type': 'left_operand',
                    'position': 'left'
                })
                self.graph.add_edge(edge1)

                edge2 = Edge(valid_signals[write_stage], and_node, data={
                    'type': 'right_operand',
                    'position': 'right'
                })
                self.graph.add_edge(edge2)

                print(f"  Gated {write_enable_name} with {write_stage} validity (base_memory={base_memory})")

                # Update the write_port node to reference the gated version
                write_port.data['combined_write_enable'] = and_id
                print(f"  Updated memory_write_port {write_port.id} to use {and_id}")

        # Gate hazard stall signals with writer stage validity
        # Stall signals like stall_rf_rd_rs1_s2_s1 check if Execute(s2) is writing
        # But if Execute has a bubble (valid=0), the stall shouldn't trigger
        if stall_ctrl and stage_order:
            stall_gated_count = 0
            # Debug: count how many stall nodes we see
            all_stall_nodes = [nid for nid in self.graph.nodes.keys() if 'stall_rf_rd_' in nid]
            print(f"  Found {len(all_stall_nodes)} stall nodes in graph: {all_stall_nodes[:5]}...")
            for node_id, node in list(self.graph.nodes.items()):
                # Find stall AND nodes (comparison && write_enable)
                if node_id.startswith('stall_rf_rd_') and node.data.get('type') == 'operation' and node.data.get('operator') == '&&':
                    # Parse the stage from node_id (e.g., stall_rf_rd_rs1_s2_s1 -> s2 is writer stage)
                    parts = node_id.split('_')
                    if len(parts) >= 5:
                        stage_part = parts[-2]  # e.g., 's2'
                        if stage_part.startswith('s'):
                            stage_num = int(stage_part[1:])
                            # Map stage number to stage name (1=Decode, 2=Execute, 3=Memory, 4=Writeback)
                            stage_names = {1: 'Decode', 2: 'Execute', 3: 'Memory', 4: 'Writeback'}
                            writer_stage = stage_names.get(stage_num)
                            if writer_stage and writer_stage in valid_signals:
                                # Create new AND node: original_stall && writer_valid
                                new_and_id = f"{node_id}_valid_gated"
                                new_and = Node(new_and_id, data={
                                    'type': 'operation',
                                    'operator': '&&',
                                    'name': new_and_id,
                                    'display_name': f'{node_id} (valid gated)'
                                })
                                self.graph.add_node(new_and)

                                # Redirect outgoing edges from old stall node to new AND node
                                for edge in list(node.outgoing_edges):
                                    new_edge = Edge(new_and, edge.target, data=edge.data.copy())
                                    self.graph.add_edge(new_edge)
                                    edge.remove_from_nodes()
                                    if edge.id in self.graph.edges:
                                        del self.graph.edges[edge.id]

                                # Connect old stall node to new AND node
                                edge1 = Edge(node, new_and, data={
                                    'type': 'left_operand',
                                    'position': 'left'
                                })
                                self.graph.add_edge(edge1)

                                # Connect validity signal to new AND node
                                edge2 = Edge(valid_signals[writer_stage], new_and, data={
                                    'type': 'right_operand',
                                    'position': 'right'
                                })
                                self.graph.add_edge(edge2)

                                stall_gated_count += 1

            if stall_gated_count > 0:
                print(f"  Gated {stall_gated_count} stall signals with writer stage validity")

        print("  Validity signals added successfully")

    def add_pipeline_stage(self, cut_location: Optional[str] = None) -> bool:
        """Add a single pipeline stage at the specified location."""

        print(f"\nAdding pipeline stage #{self.stage_counter + 1}...")

        # Analyze current dependencies
        dependency_analysis = DependencyAnalysis(self.graph)
        analysis = dependency_analysis.analyze_dependencies()

        # Determine cut location if not specified
        if cut_location is None:
            cut_location = self._determine_cut_location()

        print(f"  Pipeline cut location: {cut_location}")

        # Create pipeline stage specification
        stage_spec = PipelineStageSpec(
            cut_location,
            f"{self.pipeline_prefix}_stage_{self.stage_counter}",
            f"Pipeline stage {self.stage_counter + 1}"
        )

        # Add hazard detectors based on dependency analysis
        self._add_hazard_detectors(stage_spec, analysis)

        # Insert the pipeline stage
        success = self._insert_pipeline_stage(stage_spec, analysis)

        if success:
            self.stage_counter += 1
            print(f"  Successfully added pipeline stage: {stage_spec.stage_name}")

            # Update timing - force full reinference to account for new pipeline registers
            self.graph.infer_uarch_time(force_reinfer=True)
            return True
        else:
            print(f"  Failed to add pipeline stage")
            return False

    def _determine_cut_location(self) -> str:
        """Heuristically determine where to insert the next pipeline stage."""

        # Simple heuristic: find the point with maximum uarch_time spread
        max_time = self.graph.get_max_uarch_time()

        # For now, just cut at the midpoint of the longest path
        cut_time = max_time // 2

        # Find a node at approximately this time
        nodes_at_time = self.graph.get_nodes_at_time(cut_time)

        if nodes_at_time:
            # Prefer operation nodes for cutting
            operation_nodes = [n for n in nodes_at_time if n.data.get('type') == 'operation']
            if operation_nodes:
                return operation_nodes[0].id
            else:
                return nodes_at_time[0].id

        return f"uarch_time_{cut_time}"

    def _is_separated_by_pipeline_reg(self, node1: Node, node2: Node) -> bool:
        """Check if there's a pipeline register on any path from node1 to node2."""
        visited = set()

        def dfs(node, target):
            if node.id == target.id:
                return True, False  # Found target, no pipe reg yet
            if node.id in visited:
                return False, False
            visited.add(node.id)

            for edge in node.outgoing_edges:
                if edge.target.data.get('type') == 'pipeline_register':
                    # Found a pipeline register, search from there
                    for pipe_edge in edge.target.outgoing_edges:
                        found, _ = dfs(pipe_edge.target, target)
                        if found:
                            return True, True  # Found target, went through pipe reg
                else:
                    found, through_pipe = dfs(edge.target, target)
                    if found:
                        return True, through_pipe

            return False, False

        found, through_pipe = dfs(node1, node2)
        return through_pipe

    def _add_hazard_detectors(self, stage_spec: PipelineStageSpec, analysis: Dict):
        """Add hazard detectors to the pipeline stage based on dependency analysis."""

        hazards = analysis['potential_hazards']

        print(f"    Adding hazard detection for {len(hazards)} potential hazards")

        added_count = 0
        skipped_duplicate = 0
        skipped_same_stage = 0

        for hazard in hazards:
            if hazard['type'] == 'RAW' and hazard['condition']:
                # Create a unique key for this hazard detector
                write_node = hazard.get('write_index_node')
                read_node = hazard.get('read_index_node')
                write_id = write_node.id if write_node else None
                read_id = read_node.id if read_node else None

                hazard_key = (hazard['condition'], write_id, read_id)

                # Only add if we haven't created this detector before
                if hazard_key in self.created_hazard_detectors:
                    skipped_duplicate += 1
                    continue

                # Check if the read and write access nodes are separated by pipeline registers
                # ONLY if pipeline registers already exist in the graph
                # (Skip this check for the first pipeline stage)
                if self.stage_counter > 0:
                    read_access = hazard.get('read_access')  # e.g., "rf[rs]_rd"
                    write_access = hazard.get('write_access')  # e.g., "rf[rd]_wr"

                    # Find the actual array access nodes (not just the index nodes)
                    read_access_node = self.graph.nodes.get(read_access)
                    write_access_node = self.graph.nodes.get(write_access)

                    if read_access_node and write_access_node:
                        separated = self._is_separated_by_pipeline_reg(read_access_node, write_access_node)
                        if not separated:
                            skipped_same_stage += 1
                            continue

                # Add the hazard detector
                stage_spec.add_hazard_detector(
                    source_resource=hazard['resource'],
                    target_resource=hazard['resource'],
                    hazard_type='RAW',
                    check_condition=hazard['condition'],
                    write_index_node=write_node,
                    read_index_node=read_node
                )
                self.created_hazard_detectors.add(hazard_key)
                added_count += 1

        print(f"    Created {added_count} hazard detectors (skipped {skipped_duplicate} duplicates, {skipped_same_stage} same-stage)")

    def _insert_pipeline_stage(self, stage_spec: PipelineStageSpec, analysis: Dict) -> bool:
        """Insert the actual pipeline stage into the graph."""

        # Create pipeline register
        pipeline_reg = self._create_pipeline_register(stage_spec)

        # Create hazard detectors (returns stall signal nodes)
        stall_nodes = self._create_hazard_detectors(stage_spec)

        # Create stall controller
        stall_controller = self._create_stall_controller(stage_spec)

        # Connect stall signals to stall controller
        for stall_node in stall_nodes:
            self._connect_stall_to_controller(stall_node, stall_controller)

        # Connect stall controller output to pipeline register enable/stall input
        stall_edge = Edge(stall_controller, pipeline_reg, data={
            'type': 'stall',
            'pipeline_component': True
        })
        self.graph.add_edge(stall_edge)

        # Insert pipeline cuts
        cut_success = self._insert_pipeline_cuts(stage_spec, pipeline_reg, stall_controller)

        return cut_success

    def _create_pipeline_register(self, stage_spec: PipelineStageSpec) -> Node:
        """Create pipeline register for the stage."""

        reg_name = f"{self.pipeline_prefix}_{stage_spec.stage_name}_reg"

        # Use pipeline builder to create register
        reg_node = self.pipeline_builder.create_pipeline_register(
            register_id=reg_name,
            stage_name=stage_spec.stage_name,
            pipeline_prefix=self.pipeline_prefix,
            pipe_time=stage_spec.stage_index
        )

        return reg_node

    def _create_hazard_detectors(self, stage_spec: PipelineStageSpec) -> List[Node]:
        """
        Create hazard detectors for the stage.
        Returns list of stall signal nodes.
        """
        stall_nodes = []
        for i, detector in enumerate(stage_spec.hazard_detectors):
            # Creates: comparator -> stall_signal
            stall_node = self._create_hazard_detector(stage_spec, detector, i)
            if stall_node:
                stall_nodes.append(stall_node)

        return stall_nodes

    def _create_index_comparator(self, stage_spec: PipelineStageSpec,
                                detector: Dict, detector_index: int) -> Node:
        """
        Create a comparator to check if indices match for indexed resources.
        Returns the comparator node.

        For example, if checking rf[rd] vs rf[rs], this creates:
        - Comparator node that takes rd and rs as inputs and outputs the hazard signal
        """
        hazard_id = f"{self.pipeline_prefix}_{stage_spec.stage_name}_hazard_{detector_index}"
        condition = detector['check_condition']

        # Parse the condition (e.g., "rs == rt" or "rd == rs")
        # Extract the two indices being compared
        match = re.match(r'(\w+)\s*==\s*(\w+)', condition)
        if not match:
            print(f"      Warning: Could not parse condition '{condition}', creating placeholder")
            return None

        index1, index2 = match.groups()

        # Get the actual index nodes from the detector using stored IDs
        # These were tracked during dependency analysis based on array_index edges
        index1_node_id = detector.get('write_index_node_id')
        index2_node_id = detector.get('read_index_node_id')

        index1_node = self.graph.nodes.get(index1_node_id) if index1_node_id else None
        index2_node = self.graph.nodes.get(index2_node_id) if index2_node_id else None

        # If nodes weren't tracked (shouldn't happen with new code), fall back to searching
        if not index1_node or not index2_node:
            print(f"      Warning: Index nodes not found in detector, searching by name")
            for node_id, node in self.graph.nodes.items():
                if not index1_node and (node_id == index1 or node_id.endswith(f"_{index1}")):
                    index1_node = node
                if not index2_node and (node_id == index2 or node_id.endswith(f"_{index2}")):
                    index2_node = node

        if not index1_node or not index2_node:
            return None

        # Use hardware builder to create comparator
        comparator_id = f"{hazard_id}_cmp"
        display_name = f'{detector["hazard_type"]} Hazard: {condition}'

        comparator_node = self.hw_factory.comparators.create_index_comparator(
            comp_id=comparator_id,
            left_node=index1_node,
            right_node=index2_node,
            operator='==',
            display_name=display_name,
            metadata={
                'hazard_type': detector['hazard_type'],
                'pipeline_component': True,
                'pipeline_prefix': self.pipeline_prefix
            }
        )

        return comparator_node

    def _create_direct_hazard_signal(self, stage_spec: PipelineStageSpec,
                                    detector: Dict, detector_index: int) -> Node:
        """
        Create a hazard signal that is always active (for non-indexed resources).
        Returns the hazard signal node.
        """
        hazard_id = f"{self.pipeline_prefix}_{stage_spec.stage_name}_hazard_{detector_index}"

        # Use hardware builder to create constant '1' node
        const_id = f"{hazard_id}_const1"
        const_node = self.hw_factory.literals.create_or_get_constant(
            const_id=const_id,
            value=1,
            display_name='Always Hazard',
            metadata={
                'pipeline_component': True,
                'pipeline_prefix': self.pipeline_prefix
            }
        )

        # Create hazard signal node
        hazard_signal_id = f"{hazard_id}_signal"
        hazard_signal_data = {
            'type': 'operation',
            'operation': f'{detector["hazard_type"]} Hazard Signal',
            'display_name': f'{detector["hazard_type"]} (always active)',
            'hazard_type': detector['hazard_type'],
            'pipeline_component': True,
            'pipeline_prefix': self.pipeline_prefix
        }
        hazard_signal_node = Node(hazard_signal_id, hazard_signal_data)
        self.graph.add_node(hazard_signal_node)

        # Connect constant to hazard signal
        edge = Edge(const_node, hazard_signal_node, data={
            'type': 'operand',
            'pipeline_component': True
        })
        self.graph.add_edge(edge)

        return hazard_signal_node

    def _create_stall_signal(self, stage_spec: PipelineStageSpec,
                           hazard_node: Node, detector: Dict,
                           detector_index: int) -> Node:
        """
        Create stall signal based on hazard detection (combinational logic).
        Returns the stall signal node.
        """
        hazard_id = f"{self.pipeline_prefix}_{stage_spec.stage_name}_hazard_{detector_index}"
        stall_id = f"{hazard_id}_stall"

        # Use hardware builder to create stall signal
        stall_node = self.hw_factory.stall_logic.create_stall_signal(
            stall_id=stall_id,
            hazard_node=hazard_node,
            hazard_type=detector['hazard_type'],
            display_name=f'Stall on {detector["hazard_type"]}',
            metadata={
                'pipeline_component': True,
                'pipeline_prefix': self.pipeline_prefix
            }
        )

        return stall_node

    def _connect_stall_to_controller(self, stall_node: Node, stall_controller: Node):
        """Connect stall signal to the stall controller."""
        # Use hardware builder to connect stall to controller
        self.hw_factory.stall_logic.connect_stall_to_controller(
            stall_node=stall_node,
            controller_node=stall_controller,
            metadata={'pipeline_component': True}
        )

    def _create_hazard_detector(self, stage_spec: PipelineStageSpec,
                              detector: Dict, detector_index: int) -> Node:
        """
        Create individual hazard detector with actual hardware.

        This generates:
        - Comparator nodes (for indexed resources)
        - Stall signal nodes
        - Connections: comparator -> stall signal -> stall controller

        Returns the stall signal node that should be connected to the stall controller.
        """
        condition = detector.get('check_condition')

        # Check if this is an indexed resource comparison (e.g., "rs == rt")
        if condition and '==' in condition:
            # Create comparator-based hazard detection
            comparator_node = self._create_index_comparator(
                stage_spec, detector, detector_index
            )

            if comparator_node:
                # Create stall signal connected directly to comparator
                stall_node = self._create_stall_signal(
                    stage_spec, comparator_node, detector, detector_index
                )

                print(f"      Created comparator-based hazard detector: {detector['check_condition']}")
                return stall_node
            else:
                # Fallback to direct hazard if parsing failed
                hazard_node = self._create_direct_hazard_signal(
                    stage_spec, detector, detector_index
                )
                stall_node = self._create_stall_signal(
                    stage_spec, hazard_node, detector, detector_index
                )
                print(f"      Created direct hazard detector (parsing failed): {detector['check_condition']}")
                return stall_node
        else:
            # Non-indexed resource or no condition - always hazard
            hazard_node = self._create_direct_hazard_signal(
                stage_spec, detector, detector_index
            )
            stall_node = self._create_stall_signal(
                stage_spec, hazard_node, detector, detector_index
            )
            print(f"      Created direct hazard detector (always active)")
            return stall_node

    def _create_stall_controller(self, stage_spec: PipelineStageSpec) -> Node:
        """Create stall controller for the stage (combinational logic, not state)."""

        controller_id = f"{self.pipeline_prefix}_{stage_spec.stage_name}_stall_ctrl"

        # Use hardware builder to create stall controller
        stall_controller = self.hw_factory.stall_logic.create_or_get_stall_controller(
            controller_id=controller_id,
            stage_name=stage_spec.stage_name,
            pipeline_prefix=self.pipeline_prefix,
            metadata={'pipeline_component': True}
        )

        # Connect stall controller to all pipeline registers for this stage
        self._connect_stall_controller_to_pipeline_regs(stall_controller, stage_spec.stage_name)

        return stall_controller

    def _connect_stall_controller_to_pipeline_regs(self, stall_controller: Node, stage_name: str):
        """Connect a stall controller to all pipeline registers for a given stage."""

        # Find all pipeline registers for this stage
        # Pipeline registers are named like PIPE_{stage_name}_{signal}_PIPE
        stage_prefix = f"PIPE_{stage_name}_"
        pipeline_regs = []

        for node_id, node in self.graph.nodes.items():
            if (node.data.get('type') == 'pipeline_register' and
                node_id.startswith(stage_prefix) and node_id.endswith('_PIPE')):
                pipeline_regs.append(node)

        # Connect stall controller to each pipeline register
        for pipeline_reg in pipeline_regs:
            # Check if connection already exists
            already_connected = False
            for edge in pipeline_reg.incoming_edges:
                if edge.source.id == stall_controller.id and edge.data.get('type') == 'stall':
                    already_connected = True
                    break

            if not already_connected:
                stall_edge = Edge(stall_controller, pipeline_reg, data={
                    'type': 'stall',
                    'pipeline_component': True
                })
                self.graph.add_edge(stall_edge)
                print(f"    Connected stall controller {stall_controller.id} to {pipeline_reg.id}")

        print(f"    Connected stall controller to {len(pipeline_regs)} pipeline registers for stage {stage_name}")

    def create_variable_latency_stall_logic(self, operation_node: Node,
                                           dependent_stage_stall_controller: Node) -> Node:
        """
        Create stall logic for a variable latency operation.

        Generates: stall = !operation_complete

        This causes the pipeline to stall until the variable latency operation completes.

        Args:
            operation_node: The variable latency operation node
            dependent_stage_stall_controller: Stall controller for the dependent stage

        Returns:
            The NOT gate node that generates the stall signal
        """

        if not operation_node.variable_latency:
            print(f"Warning: {operation_node.id} is not a variable latency operation")
            return None

        # Get the complete signal
        complete_signal_id = operation_node.data.get('complete_signal')
        if not complete_signal_id or complete_signal_id not in self.graph.nodes:
            print(f"Warning: No complete signal found for {operation_node.id}")
            return None

        complete_signal = self.graph.nodes[complete_signal_id]

        # Create NOT gate: !complete
        not_complete_id = f"{operation_node.id}_not_complete"
        not_complete = Node(
            node_id=not_complete_id,
            data={
                'type': 'operation',
                'operation_type': 'not',
                'description': f'Stall while {operation_node.id} not complete',
                'pipeline_component': True,
                'stall_source': 'variable_latency'
            }
        )
        self.graph.add_node(not_complete)

        # Connect: complete -> NOT
        Edge(complete_signal, not_complete, data={
            'type': 'operand',
            'operand_position': 0
        })

        # Connect: NOT -> stall controller
        stall_edge = Edge(not_complete, dependent_stage_stall_controller, data={
            'type': 'stall_condition',
            'reason': 'variable_latency_not_complete',
            'operation': operation_node.id
        })
        self.graph.add_edge(stall_edge)

        print(f"  Created variable latency stall logic: {not_complete_id} -> {dependent_stage_stall_controller.id}")

        return not_complete

    def _insert_pipeline_cuts(self, stage_spec: PipelineStageSpec,
                            pipeline_reg_prefix: str, stall_controller: Optional[Node]) -> bool:
        """Insert pipeline cuts at the specified location.

        Args:
            stage_spec: Pipeline stage specification
            pipeline_reg_prefix: String prefix for naming pipeline registers (not a node)
            stall_controller: Optional stall controller node
        """

        # Find the cut point in the graph
        cut_node = self.graph.nodes.get(stage_spec.cut_location)

        if not cut_node:
            print(f"    Warning: Cut location {stage_spec.cut_location} not found")
            return False

        print(f"    Inserting pipeline cut at: {cut_node.id}")

        # Insert pipeline register between cut_node's inputs and the node itself
        edges_to_modify = list(cut_node.incoming_edges)

        for edge in edges_to_modify:
            source = edge.source

            # Remove original edge
            edge.remove_from_nodes()
            if edge.id in self.graph.edges:
                del self.graph.edges[edge.id]

            # Create a UNIQUE pipeline register for this signal
            # This avoids multiple signals overwriting the same register
            # Use PIPE_ prefix and _PIPE suffix to clearly mark pipeline registers
            # Sanitize the source.id to remove invalid characters for Verilog identifiers
            sanitized_source_id = self._sanitize_for_verilog(source.id)
            signal_reg_name = f"PIPE_{stage_spec.stage_name}_{sanitized_source_id}_PIPE"
            # Inherit width from source signal (check both bit_width and width fields)
            source_bit_width = source.data.get('bit_width')
            source_width = source.data.get('width')
            source_type = source.data.get('type')
            reg_metadata = {}
            if source_bit_width:
                reg_metadata['bit_width'] = source_bit_width
            if source_width:
                reg_metadata['width'] = source_width
            # Infer width=1 for boolean signals (enable, comparison, logical operations)
            if not source_width and not source_bit_width:
                if source.id.endswith('_enable') or source_type in ['comparison', 'logical_and', 'logical_or', 'logical_not']:
                    reg_metadata['width'] = 1
                # Infer width for bit_slice nodes from their range
                elif source_type == 'bit_slice':
                    # Check ILA format first (high_bit, low_bit)
                    if 'high_bit' in source.data and 'low_bit' in source.data:
                        high = source.data['high_bit']
                        low = source.data['low_bit']
                        reg_metadata['bit_width'] = (high - low + 1)
                    # Check slice_high/slice_low format
                    elif 'slice_high' in source.data and 'slice_low' in source.data:
                        high = source.data['slice_high']
                        low = source.data['slice_low']
                        reg_metadata['bit_width'] = (high - low + 1)
                    # Check expression with range
                    else:
                        expr = source.data.get('expression', {})
                        if expr.get('type') == 'bit_slice' and 'range' in expr:
                            high, low = expr['range']
                            reg_metadata['bit_width'] = (high - low + 1)
                # Infer width from incoming assignment/bit_access edges (for var nodes)
                else:
                    inferred_width = self._infer_width_from_incoming_edges(source)
                    if inferred_width:
                        # Accept all inferred widths including 32
                        reg_metadata['bit_width'] = inferred_width
            signal_reg = self.pipeline_builder.create_pipeline_register(
                register_id=signal_reg_name,
                stage_name=stage_spec.stage_name,
                pipeline_prefix=self.pipeline_prefix,
                metadata=reg_metadata
            )

            # Insert pipeline register in the path
            # source -> signal_reg
            edge_data = {
                'type': 'pipeline_input',
                'original_type': edge.data.get('type'),
                'pipeline_component': True
            }
            # Only add gating if stall controller exists
            if stall_controller:
                edge_data['gated_by'] = f"{stall_controller.id}_enable"

            reg_input_edge = Edge(source, signal_reg, data=edge_data)
            self.graph.add_edge(reg_input_edge)

            # signal_reg -> cut_node
            # Preserve important edge metadata (input_index, select_index, position, etc.)
            reg_output_data = {
                'type': edge.data.get('type'),
                'pipeline_component': True,
                'from_pipeline_reg': True
            }
            # Copy mux-related indices if present
            if 'input_index' in edge.data:
                reg_output_data['input_index'] = edge.data['input_index']
            if 'select_index' in edge.data:
                reg_output_data['select_index'] = edge.data['select_index']
            if 'source_instruction' in edge.data:
                reg_output_data['source_instruction'] = edge.data['source_instruction']
            # Copy position for concatenation inputs
            if 'position' in edge.data:
                reg_output_data['position'] = edge.data['position']
            reg_output_edge = Edge(signal_reg, cut_node, data=reg_output_data)
            self.graph.add_edge(reg_output_edge)

        print(f"    Modified {len(edges_to_modify)} edges for pipeline insertion")
        return True

    def _traces_back_to(self, node: Node, target_id: str, max_depth: int = 10) -> bool:
        """
        Check if a node traces back to a target node (possibly through pipeline registers).

        Args:
            node: Starting node
            target_id: ID of the target node to find
            max_depth: Maximum depth to search

        Returns:
            True if node is or traces back to target_id
        """
        if node.id == target_id:
            return True

        if max_depth <= 0:
            return False

        # If this is a pipeline register, check its inputs
        if node.data.get('type') == 'pipeline_register':
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'pipeline_input':
                    if self._traces_back_to(edge.source, target_id, max_depth - 1):
                        return True

        return False

    def _insert_pipeline_cuts_at_edges(self, stage_spec: PipelineStageSpec,
                                      pipeline_reg_prefix: str, stall_controller: Optional[Node],
                                      edge_ids: List[str]) -> bool:
        """Insert pipeline cuts at specific edges (used for multi-stage GUI).

        Args:
            stage_spec: Pipeline stage specification
            pipeline_reg_prefix: String prefix for naming pipeline registers (not a node)
            stall_controller: Optional stall controller node
            edge_ids: List of edge IDs to cut
        """

        if not edge_ids:
            print(f"    Warning: No edges specified for cutting")
            return False

        print(f"    Inserting pipeline cuts at {len(edge_ids)} edges")

        # First pass: collect edge info before any modifications
        # Use stored edge metadata if the edge was already cut in a previous stage
        edges_to_cut = []
        for edge_id in edge_ids:
            edge = self.graph.edges.get(edge_id)
            if edge:
                # Edge still exists, collect its current info
                edges_to_cut.append({
                    'edge': edge,
                    'original_source_id': edge.source.id,
                    'original_target_id': edge.target.id,
                    'original_type': edge.data.get('type'),
                    'input_index': edge.data.get('input_index'),  # Preserve for mux disambiguation
                    'select_index': edge.data.get('select_index'),  # Preserve for mux select disambiguation
                    'position': edge.data.get('position')  # Preserve for concatenation input ordering
                })
            elif hasattr(self, 'original_edge_info') and edge_id in self.original_edge_info:
                # Edge was cut in a previous stage, use stored metadata
                info = self.original_edge_info[edge_id]
                edges_to_cut.append({
                    'edge': None,
                    'original_source_id': info['source_id'],
                    'original_target_id': info['target_id'],
                    'original_type': info['type'],
                    'input_index': info.get('input_index'),
                    'select_index': info.get('select_index'),
                    'position': info.get('position')
                })
                print(f"    Using stored metadata for already-cut edge: {info['source_id']} -> {info['target_id']}")

        # Second pass: actually perform the cuts
        edges_modified = 0
        for edge_info in edges_to_cut:
            edge = edge_info['edge']
            original_source_id = edge_info['original_source_id']
            original_target_id = edge_info['original_target_id']
            original_type = edge_info['original_type']

            # Find the current edge connecting the original endpoints
            # It may have been replaced by pipeline infrastructure
            current_edge = None
            original_target = self.graph.nodes.get(original_target_id)

            if not original_target:
                print(f"    Warning: Target node {original_target_id} not found")
                continue

            # Look for an edge going to the target that has the correct type
            # and traces back to the original source (possibly through pipeline regs)
            # Also match input_index for mux inputs to handle multiple edges from same source
            original_input_index = edge_info.get('input_index')

            for incoming_edge in original_target.incoming_edges:
                edge_type = incoming_edge.data.get('type')
                from_pipeline = incoming_edge.data.get('from_pipeline_reg', False)

                # Match edges with the original type
                if edge_type == original_type or (from_pipeline and incoming_edge.data.get('original_type') == original_type):
                    # For mux inputs, also check input_index to disambiguate
                    if original_input_index is not None:
                        incoming_idx = incoming_edge.data.get('input_index')
                        if incoming_idx != original_input_index:
                            continue

                    # Check if this traces back to the original source
                    source_traces = self._traces_back_to(incoming_edge.source, original_source_id)
                    if source_traces:
                        current_edge = incoming_edge
                        break

            if not current_edge:
                print(f"    Warning: Could not find edge to cut for {original_source_id} -> {original_target_id}")
                continue

            # Check if this edge was added by a previous pipeline stage
            if current_edge.data.get('pipeline_component'):
                # This edge is part of pipeline infrastructure from a previous cut
                # If it has from_pipeline_reg=True, it's an OUTPUT from a pipeline register
                # We should cut it to extend the pipeline chain
                if current_edge.data.get('from_pipeline_reg'):
                    print(f"    Extending pipeline chain: {current_edge.source.id} -> {current_edge.target.id}")
                    # Fall through to cut this edge
                else:
                    # This is an INPUT to a pipeline register, skip it
                    print(f"    Skipping pipeline input edge")
                    continue

            source = current_edge.source
            target = current_edge.target

            # Remove current edge (which may be the original or a replacement from previous cut)
            current_edge.remove_from_nodes()
            if current_edge.id in self.graph.edges:
                del self.graph.edges[current_edge.id]

            # Create a UNIQUE pipeline register for this signal
            # This avoids multiple signals overwriting the same register
            # Use PIPE_ prefix and _PIPE suffix to clearly mark pipeline registers
            # Sanitize the source.id to remove invalid characters for Verilog identifiers
            sanitized_source_id = self._sanitize_for_verilog(source.id)
            signal_reg_name = f"PIPE_{stage_spec.stage_name}_{sanitized_source_id}_PIPE"
            # Inherit width from source signal (check both bit_width and width fields)
            source_bit_width = source.data.get('bit_width')
            source_width = source.data.get('width')
            source_type = source.data.get('type')
            reg_metadata = {}
            if source_bit_width:
                reg_metadata['bit_width'] = source_bit_width
            if source_width:
                reg_metadata['width'] = source_width
            # Infer width=1 for boolean signals (enable, comparison, logical operations)
            if not source_width and not source_bit_width:
                if source.id.endswith('_enable') or source_type in ['comparison', 'logical_and', 'logical_or', 'logical_not']:
                    reg_metadata['width'] = 1
                # Infer width for bit_slice nodes from their range
                elif source_type == 'bit_slice':
                    # Check ILA format first (high_bit, low_bit)
                    if 'high_bit' in source.data and 'low_bit' in source.data:
                        high = source.data['high_bit']
                        low = source.data['low_bit']
                        reg_metadata['bit_width'] = (high - low + 1)
                    # Check slice_high/slice_low format
                    elif 'slice_high' in source.data and 'slice_low' in source.data:
                        high = source.data['slice_high']
                        low = source.data['slice_low']
                        reg_metadata['bit_width'] = (high - low + 1)
                    # Check expression with range
                    else:
                        expr = source.data.get('expression', {})
                        if expr.get('type') == 'bit_slice' and 'range' in expr:
                            high, low = expr['range']
                            reg_metadata['bit_width'] = (high - low + 1)
                # Infer width from incoming assignment/bit_access edges (for var nodes)
                else:
                    inferred_width = self._infer_width_from_incoming_edges(source)
                    if inferred_width:
                        # Accept all inferred widths including 32 - the inference
                        # function now returns None when it can't determine width
                        reg_metadata['bit_width'] = inferred_width
            # Check if pipeline register already exists (from processing a previous edge to same source)
            if signal_reg_name in self.graph.nodes:
                signal_reg = self.graph.nodes[signal_reg_name]
                # Check if pipeline_input edge from this source already exists
                existing_input = any(
                    e.source.id == source.id and e.data.get('type') == 'pipeline_input'
                    for e in signal_reg.incoming_edges
                )
                if existing_input:
                    print(f"    Skipping duplicate pipeline register input: {source.id} -> {signal_reg_name}")
                    # Stillneed to create the output edge
                    # Fall through to create output edge below
                    skip_input_edge = True
                else:
                    skip_input_edge = False
            else:
                signal_reg = self.pipeline_builder.create_pipeline_register(
                    register_id=signal_reg_name,
                    stage_name=stage_spec.stage_name,
                    pipeline_prefix=self.pipeline_prefix,
                    metadata=reg_metadata,
                    pipe_time=stage_spec.stage_index  # Set pipe_time from stage_index
                )
                skip_input_edge = False

            # Insert pipeline register in the path
            # source -> signal_reg (only if not already exists)
            if not skip_input_edge:
                edge_data = {
                    'type': 'pipeline_input',
                    'original_type': current_edge.data.get('original_type', current_edge.data.get('type')),
                    'pipeline_component': True
                }
                # Only add gating if stall controller exists
                if stall_controller:
                    edge_data['gated_by'] = f"{stall_controller.id}_enable"

                reg_input_edge = Edge(source, signal_reg, data=edge_data)
                self.graph.add_edge(reg_input_edge)

            # signal_reg -> target
            # Preserve important edge metadata (input_index, select_index, position, etc.)
            reg_output_data = {
                'type': current_edge.data.get('type'),
                'original_type': current_edge.data.get('original_type', current_edge.data.get('type')),
                'pipeline_component': True,
                'from_pipeline_reg': True
            }
            # Copy mux-related indices if present
            if 'input_index' in current_edge.data:
                reg_output_data['input_index'] = current_edge.data['input_index']
            if 'select_index' in current_edge.data:
                reg_output_data['select_index'] = current_edge.data['select_index']
            if 'source_instruction' in current_edge.data:
                reg_output_data['source_instruction'] = current_edge.data['source_instruction']
            # Copy position for concatenation inputs
            if 'position' in current_edge.data:
                reg_output_data['position'] = current_edge.data['position']
            reg_output_edge = Edge(signal_reg, target, data=reg_output_data)
            self.graph.add_edge(reg_output_edge)

            # Update byte_enable metadata if this edge goes to a memory write port
            # This ensures the graph tracks that byte_enable was pipelined
            if target.data.get('type') == 'memory_write_port' and 'store_byte_enables' in target.data:
                store_byte_enables = target.data['store_byte_enables']
                # Check if the original source matches any byte_enable in the metadata
                for instr, byte_enable_signal in list(store_byte_enables.items()):
                    if byte_enable_signal == source.id:
                        # Update to use pipelined signal name
                        store_byte_enables[instr] = signal_reg.id
                        print(f"    Updated store_byte_enables metadata: {instr}: {source.id} -> {signal_reg.id}")

            # Store edge info for use by subsequent stages
            # This allows the same original edge ID to be found in later cuts
            if not hasattr(self, 'original_edge_info'):
                self.original_edge_info = {}
            # Use the original edge_id from the cut list
            for edge_id in edge_ids:
                if edge_id not in self.original_edge_info:
                    # Store for this specific original edge we just processed
                    if edge_info.get('edge') and edge_info['edge'].id == edge_id:
                        pass  # Will be stored below
                    elif original_source_id == edge_info['original_source_id'] and original_target_id == edge_info['original_target_id']:
                        # Match by source/target
                        pass
            # Store info for this edge
            original_edge_id = edge_info.get('edge').id if edge_info.get('edge') else None
            if original_edge_id:
                self.original_edge_info[original_edge_id] = {
                    'source_id': original_source_id,
                    'target_id': original_target_id,
                    'type': original_type,
                    'input_index': edge_info.get('input_index'),
                    'select_index': edge_info.get('select_index')
                }

            edges_modified += 1

        print(f"    Modified {edges_modified} edges for pipeline insertion")
        return edges_modified > 0

    def get_pipeline_summary(self) -> Dict:
        """Get summary of pipeline components added."""

        pipeline_components = {}

        for node in self.graph.nodes.values():
            if node.data.get('pipeline_component') and node.data.get('pipeline_prefix') == self.pipeline_prefix:
                component_type = node.data.get('type')
                if component_type not in pipeline_components:
                    pipeline_components[component_type] = []
                pipeline_components[component_type].append(node.id)

        return {
            'total_stages': self.stage_counter,
            'pipeline_prefix': self.pipeline_prefix,
            'components': pipeline_components,
            'max_uarch_time': self.graph.get_max_uarch_time()
        }


def apply_pipelining_optimization(graph: ResourceGraph, num_stages: int = 1) -> bool:
    """
    Apply pipelining optimization to a ResourceGraph.

    Args:
        graph: ResourceGraph to transform
        num_stages: Number of pipeline stages to add

    Returns:
        True if pipelining was applied successfully, False otherwise
    """

    print(f"\nApplying pipelining optimization: {num_stages} stages")

    transform = PipelineTransform(graph)

    success_count = 0
    for stage_num in range(num_stages):
        print(f"\n--- Adding Pipeline Stage {stage_num + 1}/{num_stages} ---")

        if transform.add_pipeline_stage():
            success_count += 1
        else:
            print(f"Failed to add stage {stage_num + 1}, stopping pipeline insertion")
            break

    if success_count > 0:
        summary = transform.get_pipeline_summary()
        print(f"\nPipelining optimization summary:")
        print(f"  Successfully added: {success_count}/{num_stages} stages")
        print(f"  Pipeline depth: {summary['max_uarch_time'] + 1} cycles")
        print(f"  Pipeline components:")
        for comp_type, components in summary['components'].items():
            print(f"    {comp_type}: {len(components)}")

    return success_count > 0


def create_example_pipelining_specs():
    """Create example pipelining configurations."""

    return [
        {
            'name': 'simple_2stage',
            'stages': 2,
            'description': 'Simple 2-stage pipeline with hazard detection'
        },
        {
            'name': 'classic_5stage',
            'stages': 5,
            'description': 'Classic 5-stage RISC pipeline'
        }
    ]


if __name__ == "__main__":
    # Test pipelining optimization
    from core.resource_graph import ResourceGraph

    print("PIPELINING OPTIMIZATION TEST")
    print("=" * 50)

    # Test with a simple instruction
    graph = ResourceGraph.from_isa_file('add_instr.isa')
    graph.infer_uarch_time()

    print(f"Original graph: {graph}")
    print(f"Original max time: {graph.get_max_uarch_time()}")

    # Apply pipelining
    success = apply_pipelining_optimization(graph, num_stages=2)

    if success:
        print(f"\nAfter pipelining: {graph}")
        print(f"New max time: {graph.get_max_uarch_time()}")
    else:
        print("\nPipelining optimization failed")