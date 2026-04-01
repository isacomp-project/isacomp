"""
Register renaming optimization for ResourceGraph.

This module implements register renaming, a classic microarchitectural optimization
that eliminates false dependencies (WAW and WAR hazards) by mapping architectural
registers to a larger pool of physical registers.

Key concepts:
- Renamer node: Maps architectural indices to microarchitectural indices
  - Allocations: Assigns new physical register for writes
  - Lookups: Returns current physical register for reads
- Denamer node: Maps microarchitectural indices back to architectural indices
  before writing to ISA state
- Dependency analysis uses microarchitectural indices within renamed domain
- Follows the 7-phase optimization pattern (OPTIMIZATION_ALGORITHM_PATTERN.md)

Usage:
    spec = RegisterRenamingSpec(
        resource_name='rf',
        num_physical_regs=64,
        target_indices=['rs', 'rt', 'rd']
    )
    optimizer = RegisterRenamingOptimization(graph)
    optimizer.apply(spec)
"""

from typing import Dict, List, Set, Tuple, Optional, Any
from core.resource_graph import ResourceGraph, Node, Edge
from core.array_access_utils import ArrayAccessAnalyzer, ArrayAccessInfo
from core.hardware_builders import HardwareBuilderFactory
from dataclasses import dataclass
import re


@dataclass
class RegisterRenamingSpec:
    """Specification for register renaming on a resource."""

    resource_name: str  # Resource to rename (e.g., 'rf' for register file)
    num_physical_regs: int  # Number of physical registers (must be >= architectural)
    target_indices: Optional[List[str]] = None  # Specific indices to rename (None = all)
    enable_verification: bool = True  # Add verification logic
    separate_regfiles: bool = False  # If True, create separate physical register file (PRF)
                                     # If False, just rename indices (default behavior)

    def __post_init__(self):
        if self.num_physical_regs < 1:
            raise ValueError(f"num_physical_regs must be >= 1, got {self.num_physical_regs}")


@dataclass
class IndexMapping:
    """Tracks an index that needs renaming."""

    index_name: str  # Original index name (e.g., 'rs', 'rd')
    index_node: Node  # Node that provides the architectural index
    access_type: str  # 'READ' or 'WRITE'
    array_access_node: Node  # The array access node (e.g., rf[rs])
    uarch_time: int  # Timing of this access


class RenameAnalysis:
    """Phase 1: Analysis - Identify renaming opportunities."""

    def __init__(self, graph: ResourceGraph, spec: RegisterRenamingSpec):
        self.graph = graph
        self.spec = spec
        self.array_analyzer = ArrayAccessAnalyzer(graph)

        # Analysis results
        self.read_indices: List[IndexMapping] = []
        self.write_indices: List[IndexMapping] = []
        self.all_index_nodes: Set[Node] = set()

    def analyze(self) -> bool:
        """
        Analyze the graph to identify indices that need renaming.

        Returns:
            True if renaming is possible, False if no opportunities found
        """
        print(f"\n[PHASE 1: ANALYSIS] Analyzing register renaming opportunities for '{self.spec.resource_name}'")

        # Get array_access reads for the target resource
        reads, writes = self.array_analyzer.get_reads_and_writes(self.spec.resource_name)

        # Also find writes through memory_write_port nodes (created by graph merger)
        # These replace individual array_access write nodes with a unified write port
        write_port_writes = self._find_write_port_accesses()
        all_writes = writes + write_port_writes

        if not reads and not all_writes:
            print(f"  No accesses found to resource '{self.spec.resource_name}'")
            return False

        print(f"  Found {len(reads)} read(s) and {len(all_writes)} write(s) ({len(write_port_writes)} via write ports)")

        # Process reads (lookups)
        for read_access in reads:
            if self._should_rename_index(read_access):
                mapping = IndexMapping(
                    index_name=read_access.index,
                    index_node=read_access.index_node,
                    access_type='READ',
                    array_access_node=read_access.node,
                    uarch_time=read_access.uarch_time
                )
                self.read_indices.append(mapping)
                if read_access.index_node:
                    self.all_index_nodes.add(read_access.index_node)

        # Process writes (allocations)
        for write_access in all_writes:
            if self._should_rename_index(write_access):
                mapping = IndexMapping(
                    index_name=write_access.index,
                    index_node=write_access.index_node,
                    access_type='WRITE',
                    array_access_node=write_access.node,
                    uarch_time=write_access.uarch_time
                )
                self.write_indices.append(mapping)
                if write_access.index_node:
                    self.all_index_nodes.add(write_access.index_node)

        print(f"  Selected {len(self.read_indices)} read index/indices for renaming")
        print(f"  Selected {len(self.write_indices)} write index/indices for renaming")

        if not self.read_indices and not self.write_indices:
            print(f"  No indices selected for renaming (check target_indices filter)")
            return False

        return True

    def _find_write_port_accesses(self) -> List[ArrayAccessInfo]:
        """Find write accesses through memory_write_port nodes.

        After graph merging, individual rf[rd]_wr nodes are replaced by a
        unified rf_shared_wr node of type 'memory_write_port'. This method
        finds these and creates ArrayAccessInfo objects for them.
        """
        write_port_accesses = []

        for node in self.graph.nodes.values():
            if node.data.get('type') != 'memory_write_port':
                continue

            base_memory = node.data.get('base_memory')
            if base_memory != self.spec.resource_name:
                continue

            # Find the write address index node (connected via write_address edge)
            index_node = None
            index_name = None
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'write_address':
                    index_node = edge.source
                    index_name = index_node.data.get('name', index_node.id)
                    break

            if not index_node:
                print(f"  Warning: write port {node.id} has no write_address edge")
                continue

            uarch_time = node.uarch_time if hasattr(node, 'uarch_time') and node.uarch_time is not None else 0

            access_info = ArrayAccessInfo(
                node=node,
                base_resource=base_memory,
                index=index_name,
                index_node=index_node,
                access_type='WRITE',
                access_key=f"{base_memory}[{index_name}]",
                uarch_time=uarch_time
            )
            write_port_accesses.append(access_info)

        return write_port_accesses

    def _should_rename_index(self, access: ArrayAccessInfo) -> bool:
        """Check if an access should be renamed based on spec filters."""
        if not access.index_node:
            # Can't rename if we don't have the index node
            return False

        if self.spec.target_indices is None:
            # Rename all indices
            return True

        # Check if index matches any of the target patterns
        for target in self.spec.target_indices:
            if access.index == target or access.index.endswith(f"_{target}"):
                return True

        return False


class RenamePlan:
    """Phase 2: Planning - Create renaming specifications."""

    def __init__(self, graph: ResourceGraph, spec: RegisterRenamingSpec, analysis: RenameAnalysis):
        self.graph = graph
        self.spec = spec
        self.analysis = analysis

        # Planning results
        self.renamer_id: str = ""
        self.denamer_id: str = ""
        self.rename_table_id: str = ""
        self.free_list_id: str = ""

    def plan(self) -> bool:
        """
        Create the plan for inserting renaming hardware.

        Returns:
            True if planning succeeded
        """
        print(f"\n[PHASE 2: PLANNING] Creating renaming plan")

        # Plan node IDs
        self.renamer_id = f"renamer_{self.spec.resource_name}"
        self.denamer_id = f"denamer_{self.spec.resource_name}"
        self.rename_table_id = f"rename_table_{self.spec.resource_name}"
        self.free_list_id = f"free_list_{self.spec.resource_name}"

        print(f"  Renamer node: {self.renamer_id}")
        print(f"  Denamer node: {self.denamer_id}")
        print(f"  Rename table: {self.rename_table_id}")
        print(f"  Free list: {self.free_list_id}")

        return True


class RenameStructure:
    """Phase 3: Structure - Create skeleton of renaming components."""

    def __init__(self, graph: ResourceGraph, spec: RegisterRenamingSpec,
                 analysis: RenameAnalysis, plan: RenamePlan):
        self.graph = graph
        self.spec = spec
        self.analysis = analysis
        self.plan = plan

        # Created structures
        self.renamer_node: Optional[Node] = None
        self.denamer_node: Optional[Node] = None
        self.rename_table_node: Optional[Node] = None
        self.free_list_node: Optional[Node] = None
        self.renamed_index_nodes: Dict[Node, Node] = {}  # arch_index -> uarch_index
        self.physical_regfile_node: Optional[Node] = None  # Physical register file (if separate_regfiles=True)
        self.architectural_regfile_node: Optional[Node] = None  # Reference to original arch RF

    def create_structure(self) -> bool:
        """
        Create the basic structure of renaming components.

        Returns:
            True if structure creation succeeded
        """
        print(f"\n[PHASE 3: STRUCTURE] Creating renaming component structure")

        # Create rename table (tracks architectural -> physical mappings)
        self._create_rename_table()

        # Create free list (tracks available physical registers)
        self._create_free_list()

        # Create renamer node (performs allocations and lookups)
        self._create_renamer()

        # Create denamer node (converts physical back to architectural)
        self._create_denamer()

        # Create microarchitectural index nodes (outputs from renamer)
        self._create_uarch_index_nodes()

        # Create physical register file if using separate regfiles mode
        if self.spec.separate_regfiles:
            self._create_physical_regfile()

        print(f"  Created {len(self.renamed_index_nodes)} microarchitectural index node(s)")
        if self.spec.separate_regfiles:
            print(f"  Created separate physical register file")

        return True

    def _create_rename_table(self):
        """Create the rename table node."""
        rename_table_data = {
            'type': 'rename_table',
            'name': self.plan.rename_table_id,
            'display_name': f'Rename Table ({self.spec.resource_name})',
            'resource_name': self.spec.resource_name,
            'num_physical_regs': self.spec.num_physical_regs,
            'is_uarch_state': True
        }

        self.rename_table_node = Node(
            self.plan.rename_table_id,
            rename_table_data,
            is_uarch_state=True
        )
        self.graph.add_node(self.rename_table_node)
        print(f"  Created rename table: {self.plan.rename_table_id}")

    def _create_free_list(self):
        """Create the free list node."""
        free_list_data = {
            'type': 'free_list',
            'name': self.plan.free_list_id,
            'display_name': f'Free List ({self.spec.resource_name})',
            'resource_name': self.spec.resource_name,
            'num_physical_regs': self.spec.num_physical_regs,
            'is_uarch_state': True
        }

        self.free_list_node = Node(
            self.plan.free_list_id,
            free_list_data,
            is_uarch_state=True
        )
        self.graph.add_node(self.free_list_node)
        print(f"  Created free list: {self.plan.free_list_id}")

    def _create_renamer(self):
        """Create the renamer node."""
        renamer_data = {
            'type': 'renamer',
            'name': self.plan.renamer_id,
            'display_name': f'Renamer ({self.spec.resource_name})',
            'resource_name': self.spec.resource_name,
            'num_physical_regs': self.spec.num_physical_regs,
            'num_reads': len(self.analysis.read_indices),
            'num_writes': len(self.analysis.write_indices)
        }

        self.renamer_node = Node(
            self.plan.renamer_id,
            renamer_data,
            is_uarch_state=False
        )
        self.graph.add_node(self.renamer_node)
        print(f"  Created renamer: {self.plan.renamer_id}")

    def _create_denamer(self):
        """Create the denamer node."""
        denamer_data = {
            'type': 'denamer',
            'name': self.plan.denamer_id,
            'display_name': f'Denamer ({self.spec.resource_name})',
            'resource_name': self.spec.resource_name
        }

        self.denamer_node = Node(
            self.plan.denamer_id,
            denamer_data,
            is_uarch_state=False
        )
        self.graph.add_node(self.denamer_node)
        print(f"  Created denamer: {self.plan.denamer_id}")

    def _create_uarch_index_nodes(self):
        """Create microarchitectural index nodes (outputs from renamer)."""
        for index_node in self.analysis.all_index_nodes:
            uarch_index_id = f"uarch_{index_node.id}"

            uarch_index_data = {
                'type': 'uarch_index',
                'name': uarch_index_id,
                'display_name': f'Physical {index_node.id}',
                'architectural_index': index_node.id,
                'resource_name': self.spec.resource_name
            }

            uarch_index_node = Node(
                uarch_index_id,
                uarch_index_data,
                is_uarch_state=False
            )
            self.graph.add_node(uarch_index_node)
            self.renamed_index_nodes[index_node] = uarch_index_node

    def _create_physical_regfile(self):
        """Create a separate physical register file."""
        # Find the original architectural register file
        arch_rf_node = None
        for node in self.graph.nodes.values():
            if node.is_arch_state and node.data.get('name') == self.spec.resource_name:
                arch_rf_node = node
                break

        if not arch_rf_node:
            print(f"Warning: Could not find architectural register file '{self.spec.resource_name}'")
            return

        self.architectural_regfile_node = arch_rf_node

        # Create physical register file node
        prf_id = f"prf_{self.spec.resource_name}"
        prf_data = {
            'type': 'physical_regfile',
            'name': prf_id,
            'display_name': f'Physical RF ({self.spec.resource_name})',
            'resource_name': self.spec.resource_name,
            'num_physical_regs': self.spec.num_physical_regs,
            'is_uarch_state': True,
            'architectural_counterpart': arch_rf_node.id
        }

        # Copy relevant properties from architectural RF
        if 'bit_width' in arch_rf_node.data:
            prf_data['bit_width'] = arch_rf_node.data['bit_width']
        if 'array_depth' in arch_rf_node.data:
            prf_data['array_depth'] = self.spec.num_physical_regs  # Override with physical count

        self.physical_regfile_node = Node(
            prf_id,
            prf_data,
            is_uarch_state=True
        )
        self.graph.add_node(self.physical_regfile_node)
        print(f"  Created physical register file: {prf_id} ({self.spec.num_physical_regs} registers)")


class RenameHardware:
    """Phase 4: Hardware - Generate actual hardware components."""

    def __init__(self, graph: ResourceGraph, spec: RegisterRenamingSpec,
                 analysis: RenameAnalysis, structure: RenameStructure):
        self.graph = graph
        self.spec = spec
        self.analysis = analysis
        self.structure = structure
        self.hw_factory = HardwareBuilderFactory(graph)

    def generate_hardware(self) -> bool:
        """
        Generate hardware components for renaming.

        Returns:
            True if hardware generation succeeded
        """
        print(f"\n[PHASE 4: HARDWARE] Generating renaming hardware")

        # For now, the renamer/denamer nodes themselves represent the hardware
        # In a more detailed implementation, we could add:
        # - CAM (Content Addressable Memory) for rename table lookups
        # - Allocator logic for free list management
        # - Comparators for bypass detection

        print(f"  Renaming hardware components created")
        print(f"  Note: Renamer and denamer nodes represent the renaming logic")

        return True


class RenameConnection:
    """Phase 5: Connection - Wire renaming components together."""

    def __init__(self, graph: ResourceGraph, spec: RegisterRenamingSpec,
                 analysis: RenameAnalysis, structure: RenameStructure):
        self.graph = graph
        self.spec = spec
        self.analysis = analysis
        self.structure = structure

    def wire_components(self) -> bool:
        """
        Wire all renaming components together.

        Returns:
            True if wiring succeeded
        """
        print(f"\n[PHASE 5: CONNECTION] Wiring renaming components")

        # Connect architectural indices to renamer
        self._connect_arch_indices_to_renamer()

        # Connect renamer to microarchitectural indices
        self._connect_renamer_to_uarch_indices()

        if self.spec.separate_regfiles:
            # Separate register files mode: redirect accesses to/from physical RF
            self._redirect_to_physical_regfile()
        else:
            # Index renaming mode: rename all indices to physical
            # Redirect read accesses to use physical indices
            self._redirect_read_accesses()

            # Redirect write accesses to use physical indices
            self._redirect_write_accesses()

        # Connect renamer to rename table and free list
        self._connect_state_tables()

        print(f"  Wiring complete")

        return True

    def _connect_arch_indices_to_renamer(self):
        """Connect architectural index nodes to renamer inputs."""
        print(f"  Connecting {len(self.analysis.all_index_nodes)} architectural index/indices to renamer")

        for idx, index_node in enumerate(self.analysis.all_index_nodes):
            edge = Edge(
                index_node,
                self.structure.renamer_node,
                data={
                    'type': 'rename_input',
                    'input_position': idx,
                    'architectural_index': index_node.id
                }
            )
            self.graph.add_edge(edge)

    def _connect_renamer_to_uarch_indices(self):
        """Connect renamer outputs to microarchitectural index nodes."""
        print(f"  Connecting renamer to {len(self.structure.renamed_index_nodes)} microarchitectural index/indices")

        for arch_index, uarch_index in self.structure.renamed_index_nodes.items():
            edge = Edge(
                self.structure.renamer_node,
                uarch_index,
                data={
                    'type': 'rename_output',
                    'architectural_index': arch_index.id
                }
            )
            self.graph.add_edge(edge)

    def _redirect_read_accesses(self):
        """Redirect read accesses to use microarchitectural indices."""
        print(f"  Redirecting {len(self.analysis.read_indices)} read access(es)")

        for read_mapping in self.analysis.read_indices:
            if read_mapping.index_node not in self.structure.renamed_index_nodes:
                continue

            uarch_index = self.structure.renamed_index_nodes[read_mapping.index_node]
            array_access = read_mapping.array_access_node

            # Find and remove the edge from architectural index to array access
            edges_to_remove = []
            for edge in array_access.incoming_edges:
                if edge.source == read_mapping.index_node and edge.data.get('type') == 'array_index':
                    edges_to_remove.append(edge)

            for edge in edges_to_remove:
                self.graph.remove_edge(edge.id)

            # Add edge from microarchitectural index to array access
            new_edge = Edge(
                uarch_index,
                array_access,
                data={
                    'type': 'array_index',
                    'renamed': True,
                    'original_index': read_mapping.index_node.id
                }
            )
            self.graph.add_edge(new_edge)

    def _redirect_write_accesses(self):
        """Mark write accesses for physical index override by the renamer.

        In index-renaming mode, the RF write at Writeback uses the physical
        index allocated by the renamer. However, we keep the ORIGINAL
        architectural index (rd) as the write_address edge so that:
        1. The pipelining transform correctly pipes rd through all stages
        2. The hazard analyzer can detect RAW hazards using rd comparisons

        Instead of replacing the write_address edge, we store metadata on the
        write node so the Verilog generator knows to use the renamer's
        physical index output for the actual RF write address.
        """
        print(f"  Marking {len(self.analysis.write_indices)} write access(es) for physical index override")

        for write_mapping in self.analysis.write_indices:
            if write_mapping.index_node not in self.structure.renamed_index_nodes:
                continue

            uarch_index = self.structure.renamed_index_nodes[write_mapping.index_node]
            write_node = write_mapping.array_access_node

            # Store the physical index node reference as metadata on the write node
            # The Verilog generator will use this to override the write address
            write_node.data['renamed_write_index'] = uarch_index.id
            write_node.data['original_write_index'] = write_mapping.index_node.id

            # Tag the uarch_index node as a write index so the Verilog generator
            # can correctly classify it (since it no longer has a write_address edge)
            uarch_index.data['rename_role'] = 'write'

            print(f"    Marked {write_node.id}: physical index = {uarch_index.id} (arch = {write_mapping.index_node.id})")

    def _redirect_to_physical_regfile(self):
        """
        Redirect array accesses to use physical register file.

        In separate_regfiles mode:
        - All reads come from the physical register file (PRF) using physical indices
        - All writes go to BOTH:
          1. Physical register file (PRF) using physical indices
          2. Architectural register file (ARF) using architectural indices (via denamer)
        """
        print(f"  Redirecting accesses to separate physical register file")

        if not self.structure.physical_regfile_node:
            print("  Error: Physical register file not created")
            return

        # Process read accesses - redirect to PRF
        print(f"    Redirecting {len(self.analysis.read_indices)} read(s) to PRF")
        for read_mapping in self.analysis.read_indices:
            if read_mapping.index_node not in self.structure.renamed_index_nodes:
                continue

            uarch_index = self.structure.renamed_index_nodes[read_mapping.index_node]
            array_access = read_mapping.array_access_node

            # Create new array access node for PRF
            prf_access_id = f"prf_{read_mapping.array_access_node.id}"
            prf_access_data = {
                'type': 'array_access',
                'name': f"prf_{self.spec.resource_name}[{read_mapping.index_name}]",
                'base_resource': f"prf_{self.spec.resource_name}",
                'display_name': f"PRF[{read_mapping.index_name}]"
            }

            prf_access_node = Node(prf_access_id, prf_access_data)
            self.graph.add_node(prf_access_node)

            # Connect: PRF -> prf_access
            edge_prf_to_access = Edge(
                self.structure.physical_regfile_node,
                prf_access_node,
                data={'type': 'base_resource'}
            )
            self.graph.add_edge(edge_prf_to_access)

            # Connect: uarch_index -> prf_access
            edge_idx_to_access = Edge(
                uarch_index,
                prf_access_node,
                data={'type': 'array_index', 'renamed': True, 'physical_index': True}
            )
            self.graph.add_edge(edge_idx_to_access)

            # Redirect output edges from original array_access to prf_access
            edges_to_redirect = [e for e in array_access.outgoing_edges
                                if e.data.get('type') == 'assignment']

            for edge in edges_to_redirect:
                target = edge.target
                # Remove old edge
                self.graph.remove_edge(edge.id)
                # Add new edge from PRF access
                new_edge = Edge(
                    prf_access_node,
                    target,
                    data={'type': 'assignment', 'from_prf': True}
                )
                self.graph.add_edge(new_edge)

        # Process write accesses - write to BOTH PRF and ARF
        print(f"    Redirecting {len(self.analysis.write_indices)} write(s) to PRF + ARF")
        for write_mapping in self.analysis.write_indices:
            if write_mapping.index_node not in self.structure.renamed_index_nodes:
                continue

            uarch_index = self.structure.renamed_index_nodes[write_mapping.index_node]
            array_access = write_mapping.array_access_node  # This is the ARF access

            # Create new array access node for PRF write
            prf_access_id = f"prf_{write_mapping.array_access_node.id}"
            prf_access_data = {
                'type': 'array_access',
                'name': f"prf_{self.spec.resource_name}[{write_mapping.index_name}]",
                'base_resource': f"prf_{self.spec.resource_name}",
                'display_name': f"PRF[{write_mapping.index_name}]"
            }

            prf_access_node = Node(prf_access_id, prf_access_data)
            self.graph.add_node(prf_access_node)

            # Connect: PRF -> prf_access
            edge_prf_to_access = Edge(
                self.structure.physical_regfile_node,
                prf_access_node,
                data={'type': 'base_resource'}
            )
            self.graph.add_edge(edge_prf_to_access)

            # Connect: uarch_index -> prf_access (for PRF write)
            edge_idx_to_prf = Edge(
                uarch_index,
                prf_access_node,
                data={'type': 'array_index', 'renamed': True, 'physical_index': True}
            )
            self.graph.add_edge(edge_idx_to_prf)

            # Copy input edges to PRF access (data to write)
            for edge in array_access.incoming_edges:
                if edge.data.get('type') == 'assignment':
                    source = edge.source
                    # Add edge to PRF
                    new_edge = Edge(
                        source,
                        prf_access_node,
                        data={'type': 'assignment', 'to_prf': True}
                    )
                    self.graph.add_edge(new_edge)

            # For ARF: Use denamer to convert physical index back to architectural
            # Create denamer instance for ARF write
            denamer_instance_id = f"{self.structure.denamer_node.id}_{write_mapping.index_name}_arf"
            denamer_instance_data = {
                'type': 'denamer_instance',
                'name': denamer_instance_id,
                'display_name': f'Denamer ARF ({write_mapping.index_name})',
                'resource_name': self.spec.resource_name,
                'architectural_index': write_mapping.index_node.id
            }

            denamer_instance = Node(denamer_instance_id, denamer_instance_data)
            self.graph.add_node(denamer_instance)

            # Connect: uarch_index -> denamer_instance
            edge_idx_to_denamer = Edge(
                uarch_index,
                denamer_instance,
                data={'type': 'denamer_input', 'uarch_index': uarch_index.id}
            )
            self.graph.add_edge(edge_idx_to_denamer)

            # Remove old architectural index edge from ARF access
            edges_to_remove = []
            for edge in array_access.incoming_edges:
                if edge.source == write_mapping.index_node and edge.data.get('type') == 'array_index':
                    edges_to_remove.append(edge)

            for edge in edges_to_remove:
                self.graph.remove_edge(edge.id)

            # Connect: denamer_instance -> arf_access (architectural index)
            edge_denamer_to_arf = Edge(
                denamer_instance,
                array_access,
                data={'type': 'array_index', 'denamed': True, 'architectural_index': True}
            )
            self.graph.add_edge(edge_denamer_to_arf)

            # ARF access keeps its original assignment edges (data to write)

    def _connect_state_tables(self):
        """Connect renamer to state tables (rename table and free list)."""
        print(f"  Connecting state tables")

        # Rename table read/write edges
        edge1 = Edge(
            self.structure.rename_table_node,
            self.structure.renamer_node,
            data={'type': 'state_read', 'state_type': 'rename_table'}
        )
        self.graph.add_edge(edge1)

        edge2 = Edge(
            self.structure.renamer_node,
            self.structure.rename_table_node,
            data={'type': 'state_write', 'state_type': 'rename_table'}
        )
        self.graph.add_edge(edge2)

        # Free list read/write edges
        edge3 = Edge(
            self.structure.free_list_node,
            self.structure.renamer_node,
            data={'type': 'state_read', 'state_type': 'free_list'}
        )
        self.graph.add_edge(edge3)

        edge4 = Edge(
            self.structure.renamer_node,
            self.structure.free_list_node,
            data={'type': 'state_write', 'state_type': 'free_list'}
        )
        self.graph.add_edge(edge4)


class RenameCleanup:
    """Phase 6: Cleanup - Remove superseded edges and nodes."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    def cleanup(self) -> bool:
        """
        Clean up any bypassed edges or orphaned nodes.

        Returns:
            True if cleanup succeeded
        """
        print(f"\n[PHASE 6: CLEANUP] Cleaning up graph")

        # Remove any orphaned nodes
        orphaned_nodes = []
        for node in self.graph.nodes.values():
            if not node.incoming_edges and not node.outgoing_edges:
                # Check if it's not an input or architectural state
                if not node.is_arch_state and not node.data.get('type') in ['input', 'field']:
                    orphaned_nodes.append(node.id)

        for node_id in orphaned_nodes:
            self.graph.remove_node(node_id)

        if orphaned_nodes:
            print(f"  Removed {len(orphaned_nodes)} orphaned node(s)")
        else:
            print(f"  No cleanup needed")

        return True


class RenameTiming:
    """Phase 7: Timing - Update timing information."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    def update_timing(self) -> bool:
        """
        Update timing information after renaming transformations.

        Returns:
            True if timing update succeeded
        """
        print(f"\n[PHASE 7: TIMING] Updating timing information")

        # Re-infer timing for the entire graph
        self.graph.infer_uarch_time(force_reinfer=True)

        max_time = self.graph.get_max_uarch_time()
        print(f"  Timing re-inference complete")
        print(f"  Maximum uarch_time: {max_time}")

        return True


class RegisterRenamingOptimization:
    """
    Main optimization class that orchestrates register renaming.

    Follows the 7-phase pattern:
    1. ANALYSIS - Identify renaming opportunities
    2. PLANNING - Create renaming specifications
    3. STRUCTURE - Build renaming component skeleton
    4. HARDWARE - Generate hardware components
    5. CONNECTION - Wire everything together
    6. CLEANUP - Remove superseded elements
    7. TIMING - Update timing information
    """

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    def apply(self, spec: RegisterRenamingSpec) -> bool:
        """
        Apply register renaming optimization to the graph.

        Args:
            spec: Specification for what to rename

        Returns:
            True if optimization was applied successfully
        """
        print("=" * 70)
        print(f"REGISTER RENAMING OPTIMIZATION: {spec.resource_name}")
        print("=" * 70)

        # Phase 1: Analysis
        analysis = RenameAnalysis(self.graph, spec)
        if not analysis.analyze():
            print("\nRegister renaming not applicable - skipping")
            return False

        # Phase 2: Planning
        plan = RenamePlan(self.graph, spec, analysis)
        if not plan.plan():
            print("\nPlanning failed - skipping")
            return False

        # Phase 3: Structure
        structure = RenameStructure(self.graph, spec, analysis, plan)
        if not structure.create_structure():
            print("\nStructure creation failed - skipping")
            return False

        # Phase 4: Hardware
        hardware = RenameHardware(self.graph, spec, analysis, structure)
        if not hardware.generate_hardware():
            print("\nHardware generation failed - skipping")
            return False

        # Phase 5: Connection
        connection = RenameConnection(self.graph, spec, analysis, structure)
        if not connection.wire_components():
            print("\nConnection failed - skipping")
            return False

        # Phase 5.5: Expand register file for physical registers (index renaming mode)
        if not spec.separate_regfiles:
            self._expand_register_file(spec)

        # Phase 6: Cleanup
        cleanup = RenameCleanup(self.graph)
        if not cleanup.cleanup():
            print("\nCleanup failed - skipping")
            return False

        # Phase 7: Timing
        timing = RenameTiming(self.graph)
        if not timing.update_timing():
            print("\nTiming update failed - skipping")
            return False

        print("\n" + "=" * 70)
        print("REGISTER RENAMING COMPLETE")
        print("=" * 70)

        return True

    def _expand_register_file(self, spec: RegisterRenamingSpec):
        """Expand the architectural register file to hold physical registers.

        In index-renaming mode, the same register file is used but with more
        entries. The array_depth (address width in bits) is increased to
        accommodate num_physical_regs entries.
        """
        import math
        new_addr_width = math.ceil(math.log2(spec.num_physical_regs)) if spec.num_physical_regs > 1 else 1
        print(f"\n[PHASE 5.5] Expanding register file '{spec.resource_name}' to {spec.num_physical_regs} entries ({new_addr_width}-bit address)")

        rf_node = None
        for node in self.graph.nodes.values():
            if node.is_arch_state and node.data.get('name') == spec.resource_name:
                rf_node = node
                break

        if not rf_node:
            print(f"  Warning: Could not find register file '{spec.resource_name}'")
            return

        old_depth = rf_node.data.get('array_depth', 5)
        # array_depth is address width in bits, not entry count
        rf_node.data['array_depth'] = new_addr_width
        # Also update dimensions if present
        if 'dimensions' in rf_node.data:
            dims = rf_node.data['dimensions']
            if len(dims) >= 2:
                # Second dimension is the address range
                rf_node.data['dimensions'] = [dims[0], (new_addr_width - 1, 0)]
        print(f"  Expanded {spec.resource_name} array_depth: {old_depth} -> {new_addr_width} bits ({2**old_depth} -> {2**new_addr_width} entries)")


def apply_register_renaming(graph: ResourceGraph, spec: RegisterRenamingSpec) -> bool:
    """
    Convenience function to apply register renaming to a graph.

    Args:
        graph: The ResourceGraph to transform
        spec: Register renaming specification

    Returns:
        True if renaming was applied successfully
    """
    optimizer = RegisterRenamingOptimization(graph)
    return optimizer.apply(spec)


def get_microarchitectural_index_nodes(graph: ResourceGraph) -> Dict[str, Node]:
    """
    Get all microarchitectural index nodes in the graph.

    This is useful for dependency analysis after renaming, so that
    hazard detection uses physical register indices instead of architectural ones.

    Args:
        graph: The ResourceGraph to search

    Returns:
        Dictionary mapping architectural index names to uarch index nodes
    """
    uarch_indices = {}

    for node in graph.nodes.values():
        if node.data.get('type') == 'uarch_index':
            arch_index = node.data.get('architectural_index')
            if arch_index:
                uarch_indices[arch_index] = node

    return uarch_indices


def has_register_renaming(graph: ResourceGraph) -> bool:
    """Check if register renaming has been applied to the graph."""
    for node in graph.nodes.values():
        if node.data.get('type') in ['renamer', 'rename_table', 'uarch_index']:
            return True
    return False


def get_renamed_resources(graph: ResourceGraph) -> List[str]:
    """Get list of resource names that have been renamed."""
    renamed_resources = set()
    for node in graph.nodes.values():
        if node.data.get('type') == 'renamer':
            resource_name = node.data.get('resource_name')
            if resource_name:
                renamed_resources.add(resource_name)
    return list(renamed_resources)
